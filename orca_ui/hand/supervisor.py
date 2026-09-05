"""Background thread owning the hand lifecycle: detect → connect → watch.

The supervisor is the only place sessions are created or destroyed. It
publishes :class:`StatusSnapshot` on every transition via ``on_status`` and
hands the live session to callers through the thread-safe :attr:`session`
property. Auto-connect never enables torque or moves the hand.

It also owns the *model*. Unless the command line pinned one, which hand
config is in force is a running conclusion rather than a startup decision:
every detection pass re-reads the side and sensing capabilities the boards
report, so a hand that was powered off at startup — or a different hand
plugged in later — is adopted rather than forced into the guess the CLI made
against an empty bus.

:meth:`HandSupervisor.select_model` is the other way in: a hand with no ORCA
board to answer ``ORCA_ID?`` cannot be named by detection at all, so the
operator names it instead and the choice is pinned exactly as ``--model``
would have pinned it.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

from orca_core import HandDetection
from orca_core.hand_config import (
    OrcaHandConfig,
    OrcaHandTouchConfig,
    _resolve_config_path,
)
from orca_core.utils.utils import read_yaml

from orca_ui.hand.boards import detect_pinned_board
from orca_ui.hand.detection import (
    names_a_hand,
    presence_from_detection,
    probe_hardware,
    run_detection,
)
from orca_ui.hand.sessions import (
    HandSession,
    SessionConnectError,
    connect_session,
    declared_capabilities,
)
from orca_ui.hand.states import Capabilities, HandState, StatusSnapshot
from orca_ui.settings import UiSettings

logger = logging.getLogger(__name__)

DETECT_BACKOFF_START_S = 2.0
DETECT_BACKOFF_MAX_S = 10.0
HEALTH_PERIOD_S = 2.0
UPGRADE_PROBE_PERIOD_S = 10.0
MOTOR_FAILURES_BEFORE_RECONNECT = 3

MODEL_CONFIRM_PROBES = 3
"""Model re-checks to run after connecting at a model that could still be an
understatement. A hand that has just been powered on can answer on the motor
bus a moment before its encoder stream is flowing, which reads as a simpler
hand than it is; these probes (one per :data:`UPGRADE_PROBE_PERIOD_S`) catch
the late arrival. Bounded because the probe opens serial ports, and a hand
that genuinely has no sensors would otherwise be probed forever."""


def load_config(config_path: str):
    """Load the model config with the same class selection as the factory."""
    raw = read_yaml(config_path) or {}
    config_cls = OrcaHandTouchConfig if "sensors" in raw else OrcaHandConfig
    return config_cls.from_config_path(config_path=config_path)


def model_name_of(config) -> str:
    """The bundled-model name a config came from (its directory name)."""
    return os.path.basename(os.path.dirname(config.config_path))


RELEASED_MESSAGE = "disconnected on request — press Reconnect to search again"


class HandBusyError(RuntimeError):
    """An operation holds the hardware, so the request cannot be honoured."""


class ModelSelectError(RuntimeError):
    """A requested model cannot be put in force."""


@dataclass(frozen=True)
class MaintenanceLease:
    """Proof that the supervisor released the hardware to an operation.

    ``presence`` is the post-teardown port probe (None in mock mode, where
    real serial discovery is skipped)."""

    kind: str
    presence: object | None = None


class HandSupervisor(threading.Thread):
    def __init__(
        self,
        settings: UiSettings,
        on_status: Callable[[StatusSnapshot], None] | None = None,
        on_session_ready: Callable[[HandSession], None] | None = None,
        on_error: Callable[[str], None] | None = None,
        on_model_changed: Callable[[object], None] | None = None,
    ):
        super().__init__(name="HandSupervisor", daemon=True)
        self._settings = settings
        self._on_status = on_status or (lambda snapshot: None)
        self._on_session_ready = on_session_ready or (lambda session: None)
        self._on_error = on_error or (lambda message: None)
        self._on_model_changed = on_model_changed or (lambda config: None)

        self.config = load_config(settings.config_path)
        self._declared = declared_capabilities(
            self.config, settings.engage_feedback,
            motors_enabled=settings.motors_enabled)
        # Mock mode has no bus to ask, so its model is its own answer.
        self._model_pinned = bool(settings.model_pinned or settings.mock)
        self._model_probes_left = 0
        # Board pin: None = first board to answer. Read/written under the
        # GIL only (str swap), like _model_pinned.
        self._board_pinned: str | None = settings.board or None

        self._lock = threading.Lock()
        self._session: Optional[HandSession] = None
        self._state = HandState.DISCONNECTED
        self._message = "starting"
        self._ports: dict = {}
        self._torque_enabled = False
        self._since = time.time()

        self._wake = threading.Event()
        self._stop_event = threading.Event()
        self._backoff = DETECT_BACKOFF_START_S
        self._motor_failures = 0
        self._last_upgrade_probe = 0.0
        self._tactile_health = (0, time.time())  # (frames_ok, last_progress_ts)

        # Maintenance lease: teardown always executes on the supervisor
        # thread (the single owner of sessions) so lease entry serializes
        # with connect/health by construction — no fresh session can appear
        # while an operation holds the hardware.
        self._maintenance_kind: str | None = None
        self._in_maintenance = False
        self._maintenance_ack = threading.Event()

        # Set by disconnect(): the ladder stops climbing until someone asks
        # for the hand back.
        self._released = False

    # ----- public API -------------------------------------------------------

    @property
    def session(self) -> Optional[HandSession]:
        with self._lock:
            return self._session

    @property
    def model_name(self) -> str:
        return model_name_of(self.config)

    def status(self) -> StatusSnapshot:
        config = self.config
        with self._lock:
            caps = self._session.caps if self._session else None
            return StatusSnapshot(
                state=self._state,
                capabilities=caps,
                torque_enabled=self._torque_enabled,
                message=self._message,
                ports=dict(self._ports),
                since=self._since,
                model=model_name_of(config),
                side=str(config.type),
                model_pinned=self._model_pinned,
                released=self._released,
                board_pinned=self._board_pinned,
            )

    def set_torque_flag(self, enabled: bool) -> None:
        with self._lock:
            self._torque_enabled = enabled
        self._publish()

    def request_reconnect(self) -> None:
        """Drop the session and redial. Also the way back from
        :meth:`disconnect` — it lifts the hold."""
        self._released = False
        self._teardown_session("reconnect requested")
        self._wake.set()

    def disconnect(self) -> None:
        """Close the session and stay closed until asked to reconnect.

        The connect ladder is relentless by design: it exists so a hand that
        was powered off, or briefly unplugged, comes back without anyone
        touching the console. That is the wrong behaviour when a human wants
        the ports *free* — to power the hand down, to move the USB cable, or
        to run orca_core's own scripts against the same bus while the console
        stays open. This is how they get them.

        Torque goes off on the way out: closing the session disables it, and
        a released supervisor never opens another.
        """
        with self._lock:
            if self._maintenance_kind is not None or self._in_maintenance:
                raise HandBusyError(
                    "an operation holds the hand — stop it before "
                    "disconnecting")
            self._released = True
            session, self._session = self._session, None
            self._torque_enabled = False
        self._set_state(HandState.DISCONNECTED, RELEASED_MESSAGE, ports={})
        if session is not None:
            try:
                session.close()
            except Exception:
                logger.exception("session close failed on disconnect")
        self._wake.set()

    def select_model(self, model_name: str | None,
                     model_version: str | None = None) -> str:
        """Put a model in force by name, or (``None``) hand the choice back
        to detection. Returns the model name now in force.

        A named model is *pinned*: detection stops revising it, exactly as
        ``--model`` does. That is the point of the call — the hands that need
        it are the ones detection cannot name, and a guess must not be
        allowed to overwrite the answer.

        Whatever session exists was opened against the old config, so a
        change reconnects: the joint↔motor map, gains and ROMs are installed
        by ``connect()`` and nothing short of a fresh one replaces them.
        Selecting the model already pinned is a no-op instead, so re-picking
        it never costs a live hand its torque.
        """
        with self._lock:
            if self._maintenance_kind is not None or self._in_maintenance:
                raise HandBusyError(
                    "an operation holds the hand — stop it before changing "
                    "the model")
            was_pinned = self._model_pinned

        if model_name is None:
            if self._settings.mock:
                # Nothing to ask: mock mode has no bus, so its model can only
                # ever be the one it was told to simulate.
                raise ModelSelectError(
                    "mock mode has no hardware to detect a model from")
            self._model_pinned = False
            self._model_probes_left = 0
            logger.info("model choice handed back to detection")
        else:
            if model_name == self.model_name:
                # Already the config in force. All that can be left to do is
                # take it out of detection's hands; the session stays up.
                if was_pinned:
                    return self.model_name
                self._model_pinned = True
                self._model_probes_left = 0
                logger.info("model %s pinned", model_name)
                self._publish()
                return self.model_name
            try:
                config = load_config(
                    self._config_path_for(model_name, model_version))
            except Exception as e:
                raise ModelSelectError(
                    f"could not load model {model_name!r}: {e}")
            logger.info("model selected: %s (was %s)",
                        model_name, self.model_name)
            self._model_pinned = True
            self._model_probes_left = 0
            self._install_config(config)

        self._teardown_session("model changed — reconnecting")
        self._backoff = DETECT_BACKOFF_START_S
        self._publish()
        self._wake.set()
        return self.model_name

    def select_board(self, device: str | None) -> None:
        """Pin the console to one board by device path, or (``None``) let it
        take the first board that answers. Reconnects on any change.

        The pin is what makes two consoles on one machine deterministic:
        a pinned supervisor probes and opens only that board's CDCs, so two
        dashboards can never trade hands behind the operators' backs. It is
        deliberately orthogonal to :meth:`select_model` — the pin says which
        *hardware* is ours, the model says what to run it as.
        """
        if self._settings.mock:
            raise ModelSelectError("mock mode has no boards to pin")
        with self._lock:
            if self._maintenance_kind is not None or self._in_maintenance:
                raise HandBusyError(
                    "an operation holds the hand — stop it before changing "
                    "the board")
            if device == self._board_pinned:
                return
            self._board_pinned = device
            # Naming a board is an ask to connect to it, so it also lifts a
            # disconnect hold — same contract as request_reconnect().
            self._released = False
        logger.info("board %s",
                    f"pinned to {device}" if device else "handed back to auto")
        self._teardown_session("board changed — reconnecting")
        self._backoff = DETECT_BACKOFF_START_S
        self._publish()
        self._wake.set()

    def enter_maintenance(self, kind: str, timeout: float = 15.0) -> MaintenanceLease:
        """Hand the hardware to an operation: the run loop tears the session
        down, suspends health checks and reconnects, and acks. Blocks the
        calling (operation) thread until the hardware is actually free."""
        with self._lock:
            if self._maintenance_kind is not None or self._in_maintenance:
                raise RuntimeError("maintenance already active")
            self._maintenance_kind = kind
            self._maintenance_ack.clear()
        self._wake.set()
        if not self._maintenance_ack.wait(timeout=timeout):
            with self._lock:
                self._maintenance_kind = None
                # The run loop may have flipped to MAINTENANCE in the same
                # instant we gave up — with no lease holder left, roll the
                # supervisor back or it idles in MAINTENANCE forever.
                entered_anyway = self._in_maintenance
            if entered_anyway:
                self.exit_maintenance()
            raise RuntimeError("supervisor did not release the hand in time")
        presence = None
        if not self._settings.mock:
            # Ports are closed now — a probe finally sees the real picture.
            try:
                presence = self._probe_hardware()
            except Exception:
                logger.exception("maintenance port probe failed")
        return MaintenanceLease(kind=kind, presence=presence)

    def _probe_hardware(self):
        """Port probe for a maintenance lease, scoped to the pinned board
        when one is pinned — an operation drives the pinned hand or nothing.
        The global probe would happily resolve another console's hand the
        moment its ports were free, and calibration would then drive it."""
        if self._board_pinned:
            return presence_from_detection(
                self.config, detect_pinned_board(self._board_pinned),
                fallback_motor_scan=False)
        return probe_hardware(self.config)

    def exit_maintenance(self) -> None:
        """Return the hardware; the supervisor reconnects via the normal ladder."""
        with self._lock:
            self._maintenance_kind = None
            self._in_maintenance = False
        self._backoff = DETECT_BACKOFF_START_S
        self._set_state(HandState.DETECTING, "maintenance finished — reconnecting")
        self._wake.set()

    def _config_path_for(self, model_name: str,
                         model_version: str | None) -> str:
        """The config.yaml a selected model name resolves to.

        The mock's own model is not one of orca_core's, so it does not
        resolve — but it is re-materializable, which keeps it a choice after
        switching the simulated hand to a bundled model and back.
        """
        from orca_ui.mock import MOCK_MODEL_NAME, materialize_mock_model

        if self._settings.mock and model_name == MOCK_MODEL_NAME:
            return materialize_mock_model()
        return _resolve_config_path(None, model_version=model_version,
                                    model_name=model_name)

    def shutdown(self) -> None:
        self._stop_event.set()
        self._wake.set()
        self.join(timeout=5.0)
        self._teardown_session("shutdown")

    # ----- thread body ------------------------------------------------------

    def run(self) -> None:
        self._set_state(HandState.DETECTING, "searching for hardware")
        while not self._stop_event.is_set():
            if self._process_maintenance_request():
                continue
            if self._maintenance_active():
                self._wake.wait(timeout=1.0)
                self._wake.clear()
                continue
            if self._released:
                # Hands off: no probing, no connecting, no port opening at
                # all — the point of the hold is that the bus is someone
                # else's until request_reconnect() lifts it.
                self._wake.wait(timeout=1.0)
                self._wake.clear()
                continue
            if self.session is None:
                delay = self._try_connect()
            else:
                delay = self._health_tick()
            self._wake.wait(timeout=delay)
            self._wake.clear()

    def _maintenance_active(self) -> bool:
        with self._lock:
            return self._in_maintenance

    def _process_maintenance_request(self) -> bool:
        """Run-loop-owned lease entry: close the session, flip to
        MAINTENANCE, and ack the waiting operation thread."""
        with self._lock:
            pending = self._maintenance_kind is not None and not self._in_maintenance
            kind = self._maintenance_kind
        if not pending:
            return False
        with self._lock:
            session, self._session = self._session, None
            self._torque_enabled = False
        if session is not None:
            try:
                session.close()
            except Exception:
                logger.exception("session close failed entering maintenance")
        with self._lock:
            # The waiting operation may have timed out mid-teardown and
            # cleared the request (enter_maintenance raised) — entering
            # MAINTENANCE now would strand the supervisor with no lease
            # holder to ever call exit_maintenance.
            if self._maintenance_kind is None:
                logger.warning(
                    "maintenance request for %s abandoned mid-teardown — "
                    "resuming the detection ladder", kind)
                abandoned = True
            else:
                abandoned = False
                self._in_maintenance = True
        if abandoned:
            self._backoff = DETECT_BACKOFF_START_S
            self._set_state(HandState.DETECTING,
                            "maintenance request abandoned — reconnecting")
            return True
        self._set_state(HandState.MAINTENANCE, f"hand handed to {kind}")
        self._maintenance_ack.set()
        return True

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
        pin = self._board_pinned
        self._set_state(HandState.DETECTING,
                        f"searching for board {pin}" if pin
                        else "searching for hardware")
        presence = None
        if not self._settings.mock:
            # Nothing is connected, so every port is free and this detection
            # sees the whole hand — the one moment its answer is authoritative
            # about which model this is. Adopting it here also means the
            # presence below is resolved against the *new* config's declared
            # capabilities, off the same probe.
            if pin:
                detection = detect_pinned_board(pin)
                if detection is None:
                    # The pin means this board or nothing: no wider probe, no
                    # VID fallback — just wait for it to come back.
                    self._set_state(
                        HandState.DETECTING,
                        f"pinned board {pin} not answering (unplugged, "
                        "powered off, or held by another process) — retrying")
                    delay = self._backoff
                    self._backoff = min(self._backoff * 1.5,
                                        DETECT_BACKOFF_MAX_S)
                    return delay
                self._adopt_model(detection)
                presence = presence_from_detection(self.config, detection,
                                                   fallback_motor_scan=False)
            else:
                detection = run_detection(self.config,
                                          force=not self._model_pinned)
                self._adopt_model(detection)
                presence = presence_from_detection(self.config, detection)
        try:
            session = connect_session(self._settings, self.config,
                                      presence=presence)
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

        # Enforce the auto-connect contract physically, not just in the flag:
        # motor clients historically enabled torque inside connect().
        if session.caps.motors:
            try:
                session.hand.disable_torque()
            except Exception:
                logger.exception("post-connect torque disable failed")

        with self._lock:
            self._session = session
            self._torque_enabled = False
            self._motor_failures = 0
            self._tactile_health = (0, time.time())
        self._backoff = DETECT_BACKOFF_START_S
        self._model_probes_left = (
            0 if self._model_pinned or self._model_is_maximal()
            else MODEL_CONFIRM_PROBES)

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

        if not self._settings.mock:
            now = time.time()
            if now - self._last_upgrade_probe > UPGRADE_PROBE_PERIOD_S:
                self._last_upgrade_probe = now
                reason = self._rescan(session)
                if reason:
                    self._teardown_session(reason)
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

    def _rescan(self, session: HandSession) -> str | None:
        """Has the hand more to offer than this session took? Returns the
        reconnect reason, or None to stay put.

        Two ways to be short-changed: the config declares hardware the connect
        ladder couldn't reach (the session is ``degraded``), or the *config
        itself* understates the hand — the model was derived while a capability
        was still coming up. The second is only re-checked for a bounded window
        after connecting; see :data:`MODEL_CONFIRM_PROBES`.
        """
        confirming_model = self._model_probes_left > 0
        if not (session.caps.degraded or confirming_model):
            return None
        if confirming_model:
            self._model_probes_left -= 1
        try:
            pin = self._board_pinned
            detection = (detect_pinned_board(pin) if pin
                         else run_detection(self.config, force=confirming_model))
            if confirming_model and self._adopt_model(detection, upgrade_only=True):
                return ("hand reports more hardware than the model declared — "
                        f"switching to {self.model_name}")
            if not session.caps.degraded:
                return None
            presence = presence_from_detection(self.config, detection,
                                               fallback_motor_scan=pin is None)
        except Exception:
            logger.exception("upgrade probe failed")
            return None
        caps = session.caps
        if ((self._declared["motors"] and not caps.motors and presence.motor_port)
                or (self._declared["tactile"] and not caps.tactile
                    and presence.sensing.tactile)
                or (self._declared["encoders"] and not caps.encoders
                    and presence.sensing.encoder)):
            return "missing hardware appeared — upgrading"
        return None

    # ----- model adoption ---------------------------------------------------

    def _model_is_maximal(self) -> bool:
        """True when no richer bundled model exists than the current one, so
        re-checking the model while connected could only ever confirm it."""
        return (isinstance(self.config, OrcaHandTouchConfig)
                and bool(self.config.has_joint_encoders))

    def _is_upgrade(self, detection: HandDetection) -> bool:
        """True when ``detection`` names a strictly more capable model of the
        same side.

        The only model change that is safe to make while a session holds
        ports: probes can't see through a link we own ourselves, so a
        *poorer* answer describes our own connection, not the hardware.
        """
        if detection.side != self.config.type:
            return False
        tactile = isinstance(self.config, OrcaHandTouchConfig)
        encoders = bool(self.config.has_joint_encoders)
        if detection.has_tactile < tactile or detection.has_encoders < encoders:
            return False
        return detection.has_tactile > tactile or detection.has_encoders > encoders

    def _adopt_model(self, detection: HandDetection | None, *,
                     upgrade_only: bool = False) -> bool:
        """Swap in the model the hardware reports. Returns True when the
        config changed.

        No-ops when the command line pinned a model, and when nothing
        answered — ``detect_hand()`` degrades to the plain right-hand model on
        an empty bus, and adopting that would throw away what we know about
        the hand that was just unplugged.
        """
        if self._model_pinned or not names_a_hand(detection):
            return False
        if detection.model_name == self.model_name:
            return False
        if upgrade_only and not self._is_upgrade(detection):
            return False
        try:
            path = _resolve_config_path(
                None, model_version=self._settings.model_version,
                model_name=detection.model_name)
            config = load_config(path)
        except Exception:
            logger.exception("could not load detected model %r",
                             detection.model_name)
            return False

        logger.info("hand identifies as %s (was %s) — switching model",
                    detection.model_name, self.model_name)
        self._install_config(config)
        return True

    def _install_config(self, config) -> None:
        """Put ``config`` in force and repoint everything keyed by the model."""
        with self._lock:
            self.config = config
            self._declared = declared_capabilities(
                config, self._settings.engage_feedback,
                motors_enabled=self._settings.motors_enabled)
        try:
            self._on_model_changed(config)
        except Exception:
            logger.exception("model-change hook failed")
        # The model rides on the status snapshot, so the browser learns about
        # the swap even while there is still no session to connect.
        self._publish()

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
