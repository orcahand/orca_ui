"""TeleopManager: one teleop session at a time, arbiter-integrated.

Session FSM (published on the ``teleop.state`` topic):

    idle -> starting -> preview -> engaged <-> preview -> idle
                \\-> error (sticky; cleared by the next start/stop)

``preview``: the child streams retargeted targets, published only on the
``teleop.targets`` topic (3D ghost) — the hand never moves. ``engaged``: the
manager owns the control-source arbiter as TELEOP and forwards targets through
``service.set_targets`` with a ramp-in blend; manual control 409s everywhere.

Threading: ingress messages arrive on the event loop (WS endpoint), REST calls
on the FastAPI threadpool, and a watchdog thread ticks at 100 ms while a
session is live. State lives behind one lock; service calls and topic
publishes happen outside it.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import deque
from typing import Callable

from orca_ui.hand.states import ControlSource
from orca_ui.hand.teleop import protocol
from orca_ui.hand.teleop.runner import ChildRunner
from orca_ui.settings import UiSettings
from orca_ui.streaming import topics as T

logger = logging.getLogger(__name__)

# FSM states (strings so the snapshot serializes directly).
IDLE = "idle"
STARTING = "starting"
PREVIEW = "preview"
ENGAGED = "engaged"
ERROR = "error"

ACTIVE_STATES = (STARTING, PREVIEW, ENGAGED)

WATCHDOG_TICK_S = 0.1
START_TIMEOUT_S = 300.0   # generous: first managed spawn may build the env
RE_RAMP_MAX_S = 1.0       # ramp duration after a tracking-loss recovery
LOG_BUFFER_LINES = 500
TARGET_HZ_WINDOW_S = 2.0

# Config keys forwarded to the child / echoed in the snapshot. "recalibrate"
# is a transient trigger, forwarded but never stored.
_CONFIG_KEYS = ("camera_index", "zmq_addr", "avp_ip", "retargeter", "rate",
                "manual_wrist_deg", "preview", "lp_alpha", "orientation_gate")


def build_teleop_manager(service, settings: UiSettings,
                         publish_topic: Callable[[str, dict], None] | None = None,
                         ) -> "TeleopManager":
    return TeleopManager(service, settings, publish_topic)


class TeleopManager:
    def __init__(self, service, settings: UiSettings,
                 publish_topic: Callable[[str, dict], None] | None = None):
        self._service = service
        self._settings = settings
        self._publish_topic = publish_topic or (lambda topic, payload: None)
        self._runner = ChildRunner(settings, on_output=self._append_log)

        self._lock = threading.Lock()
        self._state = IDLE
        self._error: str | None = None
        # Transient, human-facing note about the last automatic transition
        # (e.g. "auto-disengaged — tracking lost 10s"); cleared on the next
        # engage/stop/start so it never goes stale silently.
        self._notice: str | None = None
        self._session_id: str | None = None
        self._source: str | None = None
        self._mode: str | None = None
        self._token: str | None = None
        self._config: dict = {}
        self._link = None                    # ChildLink from the WS endpoint
        self._child_pid: int | None = None
        self._child_hand: dict = {}
        self._started_at = 0.0
        self._stop_requested = False

        # engage / ramp
        self._ramping = False
        self._ramp_t0 = 0.0
        self._ramp_duration = 0.0
        self._ramp_start_pose: dict[str, float] = {}
        self._last_forwarded: dict[str, float] = {}

        # tracking / stats
        self._last_target_mono: float | None = None
        self._frame_times: deque[float] = deque(maxlen=512)
        self._targets_seq = 0
        self._child_tracking = True
        self._tracking_lost_since: float | None = None
        self._child_stats: dict = {}
        self._calibrating: dict | None = None

        # cumulative log (same {run_id, next_seq, lines} scheme as operation.log)
        self._log: deque[dict] = deque(maxlen=LOG_BUFFER_LINES)
        self._log_seq = 0

        # Camera catalogue from the last scan (None = never scanned). Kept
        # across sessions — cameras rarely change while the server runs.
        self._cameras: list[dict] | None = None

        self._watchdog: threading.Thread | None = None

        config = service.supervisor.config
        self._roms = {j: (float(rom[0]), float(rom[1]))
                      for j, rom in config.joint_roms_dict.items()}
        self._neutral = {j: float(v)
                         for j, v in config.neutral_position.items()}

    # ----- reads ------------------------------------------------------------------

    def snapshot(self) -> dict:
        with self._lock:
            age_ms = None
            if self._last_target_mono is not None and self._state in ACTIVE_STATES:
                age_ms = round((time.monotonic() - self._last_target_mono) * 1000.0, 1)
            stats = dict(self._child_stats)
            stats["target_hz"] = self._target_hz_locked()
            stats["last_target_age_ms"] = age_ms
            return {
                "state": self._state,
                "source": self._source,
                "session_id": self._session_id,
                "mode": self._mode,
                "engaged": self._state == ENGAGED,
                "ramping": self._ramping,
                "tracking": "lost" if self._tracking_lost_since is not None else "ok",
                "calibrating": self._calibrating,
                "child": {
                    "mode": self._mode,
                    "pid": self._child_pid,
                    "connected": self._link is not None,
                } if self._state in ACTIVE_STATES else None,
                "stats": stats,
                "config": dict(self._config),
                "availability": self._runner.availability(),
                "notice": self._notice,
                "error": self._error,
            }

    def _target_hz_locked(self) -> float | None:
        now = time.monotonic()
        recent = [t for t in self._frame_times if now - t <= TARGET_HZ_WINDOW_S]
        if len(recent) < 2:
            return None
        return round((len(recent) - 1) / max(now - recent[0], 1e-6), 1)

    def active(self) -> bool:
        with self._lock:
            return self._state in ACTIVE_STATES

    def log_payload(self) -> dict:
        with self._lock:
            return {
                "run_id": self._session_id,
                "next_seq": self._log_seq,
                "lines": list(self._log),
            }

    def sources(self) -> dict:
        """Source catalogue for the Teleop tab picker."""
        availability = self._runner.availability()
        runner_ok = availability["available"]
        sources = {
            "mediapipe": {"installed": runner_ok, "ready": True,
                          "detail": None},
            "synthetic": {"installed": runner_ok, "ready": True,
                          "detail": "waveform generator — no hardware needed"},
            "manus": {"installed": runner_ok, "ready": False,
                      "detail": "needs the Manus SDK publisher running on a "
                                "Linux box (see docs) — use external mode"},
            "avp": {"installed": runner_ok, "ready": False,
                    "detail": "needs the Tracking Streamer visionOS app"},
        }
        with self._lock:
            cameras = list(self._cameras) if self._cameras is not None else None
        return {
            "runner": availability,
            "sources": sources,
            # None = never scanned; [] = scanned, nothing found.
            "cameras": cameras,
            "default_camera_index": _default_camera(cameras),
        }

    def scan_cameras(self, force: bool = True) -> dict:
        """Probe webcams through the streamer child and label them with the
        host's camera names. Slow (opens each device once); rejected while a
        session is live — a mediapipe session owns its camera."""
        from orca_ui.hand.service import ServiceError

        with self._lock:
            cached = self._cameras
            active = self._state in ACTIVE_STATES
        if active:
            if not force and cached is not None:
                return {"cameras": cached,
                        "default_camera_index": _default_camera(cached)}
            raise ServiceError(
                "cannot scan cameras while a teleop session is active",
                status_code=409)
        if not force and cached is not None:
            return {"cameras": cached,
                    "default_camera_index": _default_camera(cached)}
        try:
            probed = self._runner.probe_cameras()
        except RuntimeError as e:
            raise ServiceError(str(e), status_code=503)
        names = _host_camera_names()
        cameras = []
        seen: set[int] = set()
        for entry in probed:
            index = int(entry.get("index", -1))
            seen.add(index)
            cameras.append({
                "index": index,
                "width": entry.get("width"),
                "height": entry.get("height"),
                # cv2's AVFoundation indices follow the OS device order, so
                # positional pairing with system_profiler names is right in
                # practice (best-effort labels either way).
                "name": names[index] if 0 <= index < len(names) else None,
                "available": True,
            })
        # The OS may know cameras the probe couldn't open — typically an
        # iPhone Continuity Camera that's asleep or out of position. List
        # them anyway (marked unavailable) so the user knows they exist;
        # picking one is allowed, the child reports if it can't open it.
        for index, name in enumerate(names):
            if index not in seen:
                cameras.append({"index": index, "width": None,
                                "height": None, "name": name,
                                "available": False})
        cameras.sort(key=lambda c: c["index"])
        with self._lock:
            self._cameras = cameras
        self._append_log(
            "camera scan: " + (", ".join(
                f"{c['index']}: {c['name'] or 'camera'}" for c in cameras)
                or "none found"))
        return {"cameras": cameras,
                "default_camera_index": _default_camera(cameras)}

    # ----- session lifecycle --------------------------------------------------------

    def start(self, source: str, mode: str = "managed",
              config: dict | None = None) -> dict:
        from orca_ui.hand.service import ServiceError

        if source not in protocol.SOURCES:
            raise ServiceError(
                f"unknown teleop source {source!r} "
                f"(expected one of {sorted(protocol.SOURCES)})", status_code=400)
        if mode not in ("managed", "external"):
            raise ServiceError(f"unknown mode {mode!r}", status_code=400)

        clean_config = {k: v for k, v in (config or {}).items()
                        if k in _CONFIG_KEYS}

        with self._lock:
            if self._state in ACTIVE_STATES:
                raise ServiceError(
                    "teleop session already active — stop it first",
                    status_code=409)
            token = protocol.new_token()
            session_id = f"tp-{uuid.uuid4().hex[:8]}"
            self._reset_session_locked()
            self._state = STARTING
            self._session_id = session_id
            self._source = source
            self._mode = mode
            self._token = token
            self._config = clean_config
            self._started_at = time.monotonic()

        self._append_log(f"session {session_id} starting (source={source}, "
                         f"mode={mode})")
        self._ensure_watchdog()

        if mode == "managed":
            argv = [
                "--connect", f"ws://127.0.0.1:{self._settings.port}/ws/teleop",
                "--token", token,
                "--model-path", self._settings.config_path,
            ] + protocol.config_to_argv(source, clean_config)
            env_extra = {"ORCA_TELEOP_TOKEN": token}
            urdf_dir = self._resolve_urdf_dir()
            if urdf_dir:
                env_extra["ORCAHAND_DESCRIPTION_DIR"] = urdf_dir
            try:
                pid = self._runner.spawn(argv, env_extra)
            except RuntimeError as e:
                self._fail_session(str(e))
                raise ServiceError(str(e), status_code=503)
            with self._lock:
                self._child_pid = pid

        self._publish_state()
        result = {"session": self.snapshot()}
        if mode == "external":
            result["token"] = token
        return result

    def _resolve_urdf_dir(self) -> str | None:
        import os
        configured = getattr(self._settings, "teleop_urdf_dir", None)
        if configured:
            return configured
        # Sibling convention, same as the orca_teleop checkout itself.
        from orca_ui.hand.teleop.runner import _find_sibling_teleop_dir
        teleop_dir = _find_sibling_teleop_dir()
        if teleop_dir:
            candidate = os.path.join(os.path.dirname(teleop_dir),
                                     "orcahand_description")
            if os.path.isdir(candidate):
                return candidate
        return None

    def _reset_session_locked(self) -> None:
        self._error = None
        self._notice = None
        self._child_pid = None
        self._child_hand = {}
        self._link = None
        self._stop_requested = False
        self._ramping = False
        self._ramp_start_pose = {}
        self._last_forwarded = {}
        self._last_target_mono = None
        self._frame_times.clear()
        self._targets_seq = 0
        self._child_tracking = True
        self._tracking_lost_since = None
        self._child_stats = {}
        self._calibrating = None
        self._log.clear()
        self._log_seq = 0

    def stop(self, estop: bool = False) -> bool:
        """End the session (any state). Idempotent, never raises."""
        with self._lock:
            if self._state == IDLE:
                return False
            self._stop_requested = True
            link = self._link
            was_engaged = self._state == ENGAGED
        if was_engaged:
            self._disengage_internal(reason="stop")
        if link is not None:
            try:
                link.send_json({"type": protocol.MSG_STOP, "data": {}})
            except Exception:
                pass
        self._runner.terminate()
        with self._lock:
            self._state = IDLE
            self._token = None
            link = self._link
            self._link = None
            self._ramping = False
        if link is not None:
            try:
                link.close()
            except Exception:
                pass
        self._append_log("session stopped (e-stop)" if estop else "session stopped")
        self._publish_state()
        return True

    def estop(self) -> bool:
        """E-stop hook: never raises; ends the whole session."""
        try:
            return self.stop(estop=True)
        except Exception:
            logger.exception("teleop estop failed")
            return False

    def shutdown(self) -> None:
        self.stop()
        watchdog = self._watchdog
        if watchdog is not None and watchdog.is_alive():
            watchdog.join(timeout=1.0)

    def _fail_session(self, message: str) -> None:
        """Transition to sticky error; releases control and kills the child."""
        with self._lock:
            if self._state == IDLE:
                return
            was_engaged = self._state == ENGAGED
            self._state = ERROR
            self._error = message
            self._token = None
            link = self._link
            self._link = None
            self._ramping = False
        if was_engaged:
            self._release_control()
        if link is not None:
            try:
                link.close()
            except Exception:
                pass
        self._runner.terminate()
        self._append_log(f"error: {message}")
        self._publish_state()

    # ----- ingress socket callbacks (event loop) --------------------------------------

    def ingress_connected(self, hello: dict, link) -> dict:
        """Validate a child ``hello``; returns the ``hello_ok`` payload or
        raises :class:`protocol.HelloRejected`."""
        config = self._service.supervisor.config
        with self._lock:
            if self._state not in (STARTING,) or self._link is not None:
                raise protocol.HelloRejected(
                    "no session awaiting a child (or one is already connected)",
                    protocol.CLOSE_SESSION_BUSY)
            parsed = protocol.validate_hello(
                hello, token=self._token, expected_side=config.type)
            if parsed["source"] != self._source:
                logger.warning("teleop child source %r != session source %r",
                               parsed["source"], self._source)
                self._source = parsed["source"]
            self._link = link
            self._child_hand = parsed["hand"]
            if parsed["pid"]:
                self._child_pid = int(parsed["pid"])
            self._state = PREVIEW
            session_id = self._session_id
            session_config = dict(self._config)
        model_name = self._child_hand.get("model_name")
        if model_name and model_name != self._model_name():
            self._append_log(f"note: child model {model_name!r} != "
                             f"ui model {self._model_name()!r}")
        self._append_log(f"child connected (source={parsed['source']}) — preview")
        self._publish_state()
        # session_config: anything set while the child was still starting
        # (e.g. preview toggled from the browser) rides along in the ack.
        return protocol.hello_ok_payload(session_id, config,
                                         session_config=session_config)

    def _model_name(self) -> str:
        import os
        return os.path.basename(
            os.path.dirname(self._service.supervisor.config.config_path))

    def ingress_disconnected(self, link) -> None:
        with self._lock:
            if self._link is not link:
                return   # stale/rejected connection, not the active child
            self._link = None
            stop_requested = self._stop_requested
            state = self._state
        if stop_requested or state not in ACTIVE_STATES:
            return
        self._fail_session("teleop child link lost")

    def ingress_targets(self, angles: dict) -> None:
        """Hot path: clamp, publish, and (engaged) forward with ramp blend."""
        now = time.monotonic()
        clean = self._clamp(angles)
        if not clean:
            return
        publish_state = False
        forward: dict[str, float] | None = None
        with self._lock:
            if self._state not in (PREVIEW, ENGAGED):
                return
            self._last_target_mono = now
            self._frame_times.append(now)
            self._targets_seq += 1
            seq = self._targets_seq
            if self._tracking_lost_since is not None:
                # tracking resumed: re-ramp from the last commanded pose so
                # the hand never jumps to wherever the operator's hand went.
                self._tracking_lost_since = None
                publish_state = True
                if self._state == ENGAGED:
                    start = dict(self._last_forwarded) or dict(self._ramp_start_pose)
                    self._begin_ramp_locked(start, min(
                        self._ramp_duration or RE_RAMP_MAX_S, RE_RAMP_MAX_S))
            if self._state == ENGAGED:
                forward, ramp_done = self._blend_locked(clean, now)
                self._last_forwarded.update(forward)
                if ramp_done:
                    publish_state = True
            tracking = self._tracking_lost_since is None
        self._publish_topic(T.TELEOP_TARGETS,
                            {"angles": clean, "seq": seq, "tracking": tracking})
        if forward is not None:
            self._forward(forward)
        if publish_state:
            self._publish_state()

    def ingress_status(self, data: dict) -> None:
        with self._lock:
            if self._state not in ACTIVE_STATES:
                return
            for key in ("ingress_fps", "retarget_ms"):
                if key in data:
                    self._child_stats[key] = data[key]
            if "tracking" in data:
                self._child_tracking = bool(data["tracking"])
            if "calibrating" in data:
                self._calibrating = data["calibrating"]
        self._publish_state()

    def ingress_log(self, data: dict) -> None:
        line = str(data.get("line", "")).strip()
        if line:
            level = data.get("level")
            self._append_log(f"[{level}] {line}" if level else line)

    def ingress_preview(self, data: dict) -> None:
        jpeg = data.get("jpeg")
        if not jpeg:
            return
        self._publish_topic(T.TELEOP_PREVIEW,
                            {"jpeg": jpeg, "seq": data.get("seq")})

    # ----- engage / disengage ----------------------------------------------------------

    def engage(self, ramp_s: float | None = None) -> dict:
        """Take the control channel. Deliberately allowed while tracking is
        lost (a camera operator's hand is on the mouse, not in frame): the
        hand simply holds until targets arrive, then ramps in from its
        current pose. The watchdog's auto-disengage timer covers the case
        where tracking never shows up."""
        from orca_ui.hand.service import ServiceError

        with self._lock:
            if self._state != PREVIEW:
                raise ServiceError(
                    f"teleop is not in preview (state: {self._state})",
                    status_code=409)
            source = self._source
        session = self._service.session
        if session is None:
            raise ServiceError("hand not connected", status_code=503)
        if not session.caps.motors:
            raise ServiceError("no motor bus in this session", status_code=409)
        if not self._service.supervisor.status().torque_enabled:
            raise ServiceError("torque is disabled — enable it first",
                               status_code=409)

        self._service.acquire_control(ControlSource.TELEOP,
                                      owner_label=f"teleop ({source})")
        try:
            start_pose = self._service.current_pose()
            if not start_pose:
                raise ServiceError(
                    "no current pose to ramp from — encoders/estimate "
                    "unavailable", status_code=409)
            duration = float(ramp_s if ramp_s is not None
                             else self._settings.teleop_ramp_s)
            with self._lock:
                self._state = ENGAGED
                self._notice = None
                self._last_forwarded = {}
                self._begin_ramp_locked(start_pose, max(duration, 0.0))
        except Exception:
            self._release_control()
            raise
        self._send_engaged(True)
        self._append_log(f"engaged (ramp {duration:.1f}s)")
        self._publish_state()
        return self.snapshot()

    def disengage(self) -> dict:
        self._disengage_internal(reason="disengage")
        return self.snapshot()

    def _disengage_internal(self, reason: str, auto: bool = False) -> None:
        with self._lock:
            if self._state != ENGAGED:
                return
            self._state = PREVIEW
            self._ramping = False
            self._last_forwarded = {}
            # Automatic releases must be loud — a silent drop back to
            # preview reads as "engage is broken" (ghost keeps moving, hand
            # doesn't).
            self._notice = f"auto-disengaged — {reason}" if auto else None
        self._release_control()
        self._send_engaged(False)
        self._append_log(f"disengaged ({reason}) — holding last pose")
        self._publish_state()

    def _release_control(self) -> None:
        try:
            self._service.release_control(expected=ControlSource.TELEOP)
        except Exception:
            logger.exception("teleop release_control failed")

    def _send_engaged(self, engaged: bool) -> None:
        with self._lock:
            link = self._link
        if link is not None:
            try:
                link.send_json({"type": protocol.MSG_ENGAGED,
                                "data": {"engaged": engaged}})
            except Exception:
                pass

    # ----- config -----------------------------------------------------------------------

    def set_config(self, updates: dict) -> dict:
        from orca_ui.hand.service import ServiceError

        clean = {k: v for k, v in updates.items()
                 if k in _CONFIG_KEYS or k == "recalibrate"}
        if not clean:
            raise ServiceError("no recognized config keys", status_code=400)
        with self._lock:
            self._config.update(
                {k: v for k, v in clean.items() if k != "recalibrate"})
            link = self._link
        if link is not None:
            try:
                link.send_json({"type": protocol.MSG_CONFIG, "data": clean})
            except Exception:
                pass
        self._publish_state()
        with self._lock:
            return dict(self._config)

    # ----- ramp / clamp helpers -----------------------------------------------------------

    def _begin_ramp_locked(self, start_pose: dict[str, float],
                           duration: float) -> None:
        self._ramp_start_pose = dict(start_pose)
        self._ramp_t0 = time.monotonic()
        self._ramp_duration = duration
        self._ramping = duration > 0.0

    def _blend_locked(self, clean: dict[str, float],
                      now: float) -> tuple[dict[str, float], bool]:
        """Ramp-in blend from the captured start pose. Returns (targets,
        ramp_just_finished)."""
        if not self._ramping:
            return dict(clean), False
        elapsed = now - self._ramp_t0
        blend = 1.0 if self._ramp_duration <= 0 else min(
            1.0, elapsed / self._ramp_duration)
        if blend >= 1.0:
            self._ramping = False
            return dict(clean), True
        out = {}
        for joint, target in clean.items():
            start = self._ramp_start_pose.get(
                joint, self._neutral.get(joint, target))
            out[joint] = start * (1.0 - blend) + target * blend
        return out, False

    def _clamp(self, angles: dict) -> dict[str, float]:
        """Defense-in-depth: drop unknown joints and non-finite values,
        clamp everything to the hand's ROM. The child already clamps; the
        child is untrusted."""
        import math
        out = {}
        unknown = []
        for joint, value in (angles or {}).items():
            rom = self._roms.get(joint)
            if rom is None:
                unknown.append(joint)
                continue
            try:
                v = float(value)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(v):
                continue
            out[joint] = min(max(v, rom[0]), rom[1])
        if unknown:
            self._warn_unknown_joints(unknown)
        return out

    def _warn_unknown_joints(self, joints: list[str]) -> None:
        with self._lock:
            already = getattr(self, "_unknown_warned", False)
            self._unknown_warned = True
        if not already:
            self._append_log(f"dropping unknown joints from child: "
                             f"{sorted(set(joints))}")

    def _forward(self, targets: dict[str, float]) -> None:
        from orca_ui.hand.service import ServiceError

        try:
            self._service.set_targets(targets, source=ControlSource.TELEOP)
        except ServiceError as e:
            # Torque flipped off / session tore down mid-frame: the watchdog
            # reconciles within a tick; don't spam per-frame errors.
            logger.debug("teleop forward rejected: %s", e)

    # ----- watchdog ------------------------------------------------------------------------

    def _ensure_watchdog(self) -> None:
        if self._watchdog is not None and self._watchdog.is_alive():
            return
        self._watchdog = threading.Thread(
            target=self._watchdog_loop, name="TeleopWatchdog", daemon=True)
        self._watchdog.start()

    def _watchdog_loop(self) -> None:
        while True:
            time.sleep(WATCHDOG_TICK_S)
            with self._lock:
                state = self._state
            if state not in ACTIVE_STATES:
                return
            try:
                self._watchdog_tick(state)
            except Exception:
                logger.exception("teleop watchdog tick failed")

    def _watchdog_tick(self, state: str) -> None:
        now = time.monotonic()

        # Managed child died?
        if self._mode == "managed":
            code = self._runner.poll()
            if code is not None:
                self._fail_session(f"teleop child exited (code {code})")
                return

        if state == STARTING:
            if now - self._started_at > START_TIMEOUT_S:
                self._fail_session("timed out waiting for the teleop child "
                                   "to connect")
            return

        if state != ENGAGED:
            return

        # The hand itself went away or torque dropped: teleop must let go.
        if self._service.session is None or \
                not self._service.supervisor.status().torque_enabled:
            self._disengage_internal(reason="hand unavailable / torque off",
                                     auto=True)
            return

        # Target freshness -> tracking lost -> hold; eventually auto-disengage.
        hold_after_s = self._settings.teleop_hold_after_ms / 1000.0
        publish = False
        with self._lock:
            stale = (self._last_target_mono is None or
                     now - self._last_target_mono > hold_after_s)
            lost = stale or not self._child_tracking
            if lost and self._tracking_lost_since is None:
                self._tracking_lost_since = now
                publish = True
                self._log_locked("tracking lost — holding last pose")
            lost_for = (now - self._tracking_lost_since
                        if self._tracking_lost_since is not None else 0.0)
            disengage_after = self._settings.teleop_disengage_after_s
        if publish:
            self._publish_state()
            self._publish_log()
        if self._tracking_lost_since is not None and disengage_after > 0 \
                and lost_for > disengage_after:
            self._disengage_internal(
                reason=f"tracking lost for {lost_for:.0f}s", auto=True)

    # ----- log / publish ----------------------------------------------------------------------

    def _log_locked(self, line: str) -> None:
        self._log.append({"seq": self._log_seq, "t": time.time(), "line": line})
        self._log_seq += 1

    def _append_log(self, line: str) -> None:
        with self._lock:
            self._log_locked(line)
        self._publish_log()

    def _publish_log(self) -> None:
        self._publish_topic(T.TELEOP_LOG, self.log_payload())

    def _publish_state(self) -> None:
        self._publish_topic(T.TELEOP_STATE, self.snapshot())


def _host_camera_names() -> list[str]:
    """Camera names in OS device order (macOS only; best-effort)."""
    import json
    import subprocess
    import sys

    if sys.platform != "darwin":
        return []
    try:
        result = subprocess.run(
            ["system_profiler", "SPCameraDataType", "-json"],
            capture_output=True, text=True, timeout=10)
        data = json.loads(result.stdout or "{}")
        return [str(item.get("_name", "")) for item
                in data.get("SPCameraDataType", [])]
    except Exception:
        logger.debug("camera name lookup failed", exc_info=True)
        return []


# Continuity/iPhone cameras enumerate before the built-in one on some Macs —
# opening them silently is exactly the "index 0 doesn't work" trap.
# ("macbook … camera" is how newer macOS names the built-in FaceTime camera.)
_BUILTIN_HINTS = ("facetime", "built-in", "integrated", "macbook")
_REMOTE_HINTS = ("iphone", "ipad", "continuity", "desk view")


def _default_camera(cameras: list[dict] | None) -> int | None:
    """Most-likely-intended camera: prefer the built-in one by name, avoid
    phone/Continuity cameras, else the lowest index. Only cameras that
    actually opened during the probe qualify."""
    openable = [c for c in (cameras or []) if c.get("available", True)]
    if not openable:
        return None

    def rank(camera: dict) -> tuple:
        name = (camera.get("name") or "").lower()
        builtin = any(hint in name for hint in _BUILTIN_HINTS)
        remote = any(hint in name for hint in _REMOTE_HINTS)
        return (0 if builtin else 2 if remote else 1, camera["index"])

    return min(openable, key=rank)["index"]
