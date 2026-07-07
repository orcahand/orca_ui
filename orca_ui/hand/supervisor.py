"""Background thread owning the hand lifecycle: detect → connect → watch.

The supervisor is the only place sessions are created or destroyed. It
publishes :class:`StatusSnapshot` on every transition via ``on_status`` and
hands the live session to callers through the thread-safe :attr:`session`
property. Auto-connect never enables torque or moves the hand.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

from orca_core.hand_config import OrcaHandConfig, OrcaHandTouchConfig
from orca_core.utils.utils import read_yaml

from orca_ui.hand.detection import probe_hardware
from orca_ui.hand.sessions import (
    HandSession,
    SessionConnectError,
    connect_session,
    declared_capabilities,
)
from orca_ui.hand.shims import neutralize_interactive_picker
from orca_ui.hand.states import Capabilities, HandState, StatusSnapshot
from orca_ui.settings import UiSettings

logger = logging.getLogger(__name__)

DETECT_BACKOFF_START_S = 2.0
DETECT_BACKOFF_MAX_S = 10.0
HEALTH_PERIOD_S = 2.0
UPGRADE_PROBE_PERIOD_S = 10.0
MOTOR_FAILURES_BEFORE_RECONNECT = 3


def load_config(config_path: str):
    """Load the model config with the same class selection as the factory."""
    raw = read_yaml(config_path) or {}
    config_cls = OrcaHandTouchConfig if "sensors" in raw else OrcaHandConfig
    return config_cls.from_config_path(config_path=config_path)


class HandSupervisor(threading.Thread):
    def __init__(
        self,
        settings: UiSettings,
        on_status: Callable[[StatusSnapshot], None] | None = None,
        on_session_ready: Callable[[HandSession], None] | None = None,
        on_error: Callable[[str], None] | None = None,
    ):
        super().__init__(name="HandSupervisor", daemon=True)
        neutralize_interactive_picker()
        self._settings = settings
        self._on_status = on_status or (lambda snapshot: None)
        self._on_session_ready = on_session_ready or (lambda session: None)
        self._on_error = on_error or (lambda message: None)

        self.config = load_config(settings.config_path)
        self._declared = declared_capabilities(
            self.config, settings.engage_feedback,
            motors_enabled=settings.motors_enabled)

        self._lock = threading.Lock()
        self._session: Optional[HandSession] = None
        self._state = HandState.DISCONNECTED
        self._message = "starting"
        self._ports: dict = {}
        self._torque_enabled = False
        self._since = time.time()

        self._wake = threading.Event()
        self._stop = threading.Event()
        self._backoff = DETECT_BACKOFF_START_S
        self._motor_failures = 0
        self._last_upgrade_probe = 0.0
        self._tactile_health = (0, time.time())  # (frames_ok, last_progress_ts)

    # ----- public API -------------------------------------------------------

    @property
    def session(self) -> Optional[HandSession]:
        with self._lock:
            return self._session

    def status(self) -> StatusSnapshot:
        with self._lock:
            caps = self._session.caps if self._session else None
            return StatusSnapshot(
                state=self._state,
                capabilities=caps,
                torque_enabled=self._torque_enabled,
                message=self._message,
                ports=dict(self._ports),
                since=self._since,
            )

    def set_torque_flag(self, enabled: bool) -> None:
        with self._lock:
            self._torque_enabled = enabled
        self._publish()

    def request_reconnect(self) -> None:
        self._teardown_session("reconnect requested")
        self._wake.set()

    def shutdown(self) -> None:
        self._stop.set()
        self._wake.set()
        self.join(timeout=5.0)
        self._teardown_session("shutdown")

    # ----- thread body ------------------------------------------------------

    def run(self) -> None:
        self._set_state(HandState.DETECTING, "searching for hardware")
        while not self._stop.is_set():
            if self.session is None:
                delay = self._try_connect()
            else:
                delay = self._health_tick()
            self._wake.wait(timeout=delay)
            self._wake.clear()

    # ----- internals --------------------------------------------------------

    def _publish(self) -> None:
        self._on_status(self.status())

    def _set_state(self, state: HandState, message: str, ports: dict | None = None) -> None:
        with self._lock:
            self._state = state
            self._message = message
            if ports is not None:
                self._ports = ports
            self._since = time.time()
        logger.info("hand state -> %s: %s", state.value, message)
        self._publish()

    def _try_connect(self) -> float:
        self._set_state(HandState.DETECTING, "searching for hardware")
        try:
            session = connect_session(self._settings, self.config)
        except SessionConnectError as e:
            detail = "; ".join(e.attempts) if e.attempts else str(e)
            self._set_state(HandState.DETECTING,
                            f"no connection: {detail} — retrying")
            delay = self._backoff
            self._backoff = min(self._backoff * 1.5, DETECT_BACKOFF_MAX_S)
            return delay
        except Exception as e:
            logger.exception("unexpected connect failure")
            self._on_error(f"connect failed unexpectedly: {e}")
            self._set_state(HandState.DETECTING, f"connect error: {e} — retrying")
            delay = self._backoff
            self._backoff = min(self._backoff * 1.5, DETECT_BACKOFF_MAX_S)
            return delay

        with self._lock:
            self._session = session
            self._torque_enabled = False
            self._motor_failures = 0
            self._tactile_health = (0, time.time())
        self._backoff = DETECT_BACKOFF_START_S

        state = HandState.DEGRADED if session.caps.degraded else HandState.CONNECTED
        self._set_state(state, f"[{session.tier}] {session.message}", session.ports)

        try:
            self._on_session_ready(session)
        except Exception as e:
            logger.exception("session-ready hook failed")
            self._on_error(f"session init: {e}")
        return HEALTH_PERIOD_S

    def _health_tick(self) -> float:
        session = self.session
        if session is None:
            return 0.1

        reason = self._check_health(session)
        if reason:
            self._on_error(reason)
            self._teardown_session(reason)
            return 0.1  # go straight back to detection

        if session.caps.degraded and not self._settings.mock:
            now = time.time()
            if now - self._last_upgrade_probe > UPGRADE_PROBE_PERIOD_S:
                self._last_upgrade_probe = now
                if self._upgrade_available(session):
                    self._teardown_session("missing hardware appeared — upgrading")
                    return 0.1
        return HEALTH_PERIOD_S

    def _check_health(self, session: HandSession) -> str | None:
        if session.caps.motors:
            try:
                session.hand.get_motor_pos()
                self._motor_failures = 0
            except Exception as e:
                self._motor_failures += 1
                logger.warning("motor health read failed (%d): %s",
                               self._motor_failures, e)
                if self._motor_failures >= MOTOR_FAILURES_BEFORE_RECONNECT:
                    return f"motor bus unresponsive: {e}"

        if session.caps.feedback_loop:
            try:
                stats = session.loop_stats() or {}
                if stats.get("fallback_active"):
                    return "joint loop e-stopped (encoder stream stalled)"
            except Exception:
                pass

        if session.caps.tactile:
            try:
                stats = session.tactile_stats()
                if stats is not None:
                    frames_ok, last_ts = self._tactile_health
                    if stats.frames_ok > frames_ok:
                        self._tactile_health = (stats.frames_ok, time.time())
                    elif (
                        stats.frames_ok > 0
                        and stats.stream_rearms >= 2
                        and time.time() - last_ts > 5.0
                    ):
                        # The client's own re-arm keeps failing: device gone.
                        return "tactile stream dead despite re-arms"
            except Exception:
                pass
        return None

    def _upgrade_available(self, session: HandSession) -> bool:
        try:
            presence = probe_hardware(self.config)
        except Exception:
            return False
        caps = session.caps
        if self._declared["motors"] and not caps.motors and presence.motor_port:
            return True
        if self._declared["tactile"] and not caps.tactile and presence.sensing.tactile:
            return True
        if self._declared["encoders"] and not caps.encoders and presence.sensing.encoder:
            return True
        return False

    def _teardown_session(self, reason: str) -> None:
        with self._lock:
            session, self._session = self._session, None
            self._torque_enabled = False
        if session is not None:
            self._set_state(HandState.RECONNECTING, reason)
            try:
                session.close()
            except Exception:
                logger.exception("session close failed")
