"""One app session at a time: start, link, preview, engage, end.

States (published on ``app.state``)::

    idle -> starting -> preview <-> engaged
    starting | preview | engaged -> stopping -> idle | error

``preview``: the app's targets only pose the ghost. ``engaged``: the session
owns the control-source arbiter as APP and forwards clamped, ramped targets
to the hand. ``error`` stays until the next start or stop.

Every state change is a check-and-set under ``_lock``; hardware calls, the
app process and publishes happen outside it. Every end (Stop, E-STOP, the app
exiting, the link dropping, a hand change) goes through :meth:`_end`. Ending
an engaged session turns torque off where the hand is (E-STOP's own torque
off covers that case). The slow part of an end runs on its own thread unless
the caller waits, so nothing blocks the event loop.

Safety rules are small ``_rule_*`` methods called from :meth:`tick`, each
with its setting in ``UiSettings``.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Callable

from orca_ui.hand.app import protocol
from orca_ui.hand.app.motion import blend, clamp
from orca_ui.hand.app.process import AppProcess, split_command
from orca_ui.hand.app.store import AppStore
from orca_ui.hand.service import ServiceError
from orca_ui.hand.states import ControlSource
from orca_ui.home import ui_home
from orca_ui.settings import UiSettings
from orca_ui.streaming import topics as T

logger = logging.getLogger(__name__)

IDLE = "idle"
STARTING = "starting"
PREVIEW = "preview"
ENGAGED = "engaged"
STOPPING = "stopping"
ERROR = "error"

LIVE = (STARTING, PREVIEW, ENGAGED)

TICK_S = 0.1
START_TIMEOUT_S = 300.0   # the first start of an app may build its environment
RE_RAMP_MAX_S = 1.0       # ramp after targets come back from a hold
MIN_RAMP_S = 0.5          # no engage is ever instant
LOG_LINES = 500
LOG_LINE_CHARS = 2000
TARGET_HZ_WINDOW_S = 2.0
MAX_STREAMS = 8


@dataclass(frozen=True)
class AppInfo:
    title: str
    example_command: str


# The apps the console has a tab for. Adding one is one entry here and one tab.
APPS = {
    "teleop": AppInfo("Teleop", "uv run --frozen --project <orca_teleop folder> --extra teleop orca-teleop-streamer"),
    "rl": AppInfo("RL", "uv run --frozen --project <orca_rl folder> orca-rl-console"),
}


@dataclass
class _Ramp:
    start: dict[str, float]
    duration: float
    began: dict[str, float] = field(default_factory=dict)  # per joint, first target


class AppSessions:
    def __init__(self, service, settings: UiSettings,
                 publish_topic: Callable[[str, dict], None],
                 browsers: Callable[[], int] = lambda: 0,
                 clock: Callable[[], float] = time.monotonic):
        self._service = service
        self._settings = settings
        self._publish_topic = publish_topic
        self._browsers = browsers
        self.clock = clock
        root = settings.apps_dir or ui_home() / "apps"
        self._store = AppStore(root)
        self._process = AppProcess(on_output=self._append_log)

        self._lock = threading.Lock()
        self._state = IDLE
        self._app: str | None = None
        self._session_id: str | None = None
        self._mode: str | None = None
        self._token: str | None = None
        self._link = None
        self._pid: int | None = None
        self._started_at = 0.0
        self._hand: dict | None = None
        self._hand_config = None
        self._schema: list[dict] = []
        self._values: dict = {}
        self._errors: dict = {}
        self._info: dict = {}
        self._app_tracking = True
        self._lost_since: float | None = None
        self._last_target: float | None = None
        self._target_times: deque[float] = deque(maxlen=512)
        self._ramp: _Ramp | None = None
        self._last_forwarded: dict[str, float] = {}   # full pose while engaged
        self._halted = False   # E-STOP: forward nothing until the next start
        self._frames: dict[str, dict] = {}
        self._frame_seq = 0
        self._browser_seen = False
        self._browser_gone_since: float | None = None
        self._unknown_warned = False
        self._notice: str | None = None
        self._error: str | None = None
        self._log: deque[dict] = deque(maxlen=LOG_LINES)
        self._log_seq = 0
        self._ranges_cache: tuple | None = None
        self._closed = threading.Event()
        self._watchdog: threading.Thread | None = None
        self._ender: threading.Thread | None = None

    # ----- reads -------------------------------------------------------------------

    def snapshot(self) -> dict:
        now = self.clock()
        with self._lock:
            live = self._state in LIVE
            age_ms = None
            if live and self._last_target is not None:
                age_ms = round((now - self._last_target) * 1000.0, 1)
            return {
                "state": self._state,
                "app": self._app,
                "title": APPS[self._app].title if self._app else None,
                "session_id": self._session_id,
                "mode": self._mode,
                "engaged": self._state == ENGAGED,
                "ramping": self._ramp is not None and (
                    not self._ramp.began or any(now - t0 < self._ramp.duration
                                                for t0 in self._ramp.began.values())),
                "tracking": "lost" if self._lost_since is not None else "ok",
                "info": dict(self._info),
                "settings": {"schema": list(self._schema),
                             "values": dict(self._values),
                             "errors": dict(self._errors)},
                "stats": {"target_hz": self._target_hz_locked(now),
                          "last_target_age_ms": age_ms},
                "process": {"pid": self._pid, "connected": self._link is not None}
                if live else None,
                "notice": self._notice,
                "error": self._error,
            }

    def _target_hz_locked(self, now: float) -> float | None:
        recent = [t for t in self._target_times if now - t <= TARGET_HZ_WINDOW_S]
        if len(recent) < 2:
            return None
        return round((len(recent) - 1) / max(now - recent[0], 1e-6), 1)

    def log_payload(self) -> dict:
        with self._lock:
            return {"run_id": self._session_id, "next_seq": self._log_seq,
                    "lines": list(self._log)}

    def apps(self) -> list[dict]:
        """Every app with what the console remembers about it."""
        out = []
        for app_id, info in APPS.items():
            record = self._store.load(app_id)
            out.append({"id": app_id, "title": info.title,
                        "example_command": info.example_command,
                        "command": record["command"],
                        "schema": protocol.clean_schema(record["schema"]),
                        "values": record["values"]})
        return out

    def _ranges(self) -> dict[str, tuple[float, float]]:
        """Joint ranges of the model in force, cached on the config object."""
        config = self._service.supervisor.config
        cached = self._ranges_cache
        if cached is None or cached[0] is not config:
            ranges = {j: (float(rom[0]), float(rom[1]))
                      for j, rom in config.joint_roms_dict.items()}
            cached = self._ranges_cache = (config, ranges)
        return cached[1]

    def _current_hand(self) -> tuple[object, dict]:
        config = self._service.supervisor.config
        return config, protocol.hand_block(config, self._service.supervisor.model_name)

    # ----- remembered command and settings ---------------------------------------------

    def set_command(self, app: str, command: str) -> dict:
        _require_app(app)
        try:
            split_command(command)
        except ValueError as e:
            raise ServiceError(f"can't read the command: {e}", status_code=400)
        return self._store.update(app, command=command.strip())

    def set_values(self, app: str, values: dict) -> dict:
        """A settings change from the user. Sent to the running app, which
        answers with ``settings``; remembered for the next start otherwise.
        Values that don't fit the schema are refused, each with its reason."""
        _require_app(app)
        if not isinstance(values, dict) or not values:
            raise ServiceError("no settings given", status_code=400)
        stored = self._store.load(app)
        with self._lock:
            live = self._state in LIVE and self._app == app
            schema = self._schema if live else protocol.clean_schema(stored["schema"])
            by_key = {s["key"]: s for s in schema}
            unknown = sorted(k for k in values if k not in by_key)
            if unknown:
                hint = "" if by_key else " (settings appear after the app's first start)"
                raise ServiceError(f"unknown settings {unknown}{hint}", status_code=400)
            if live and self._state == ENGAGED:
                locked = sorted(k for k in values if not by_key[k].get("live"))
                if locked:
                    raise ServiceError(
                        f"disengage to change {', '.join(locked)}", status_code=409)
            errors = {k: e for k, v in values.items()
                      if (e := protocol.check_value(by_key[k], v))}
            good = {k: v for k, v in values.items() if k not in errors}
            if live and self._link is not None:
                if good:
                    self._send_locked(protocol.MSG_SET, good)
                return {"sent": bool(good), "errors": errors}
            if live:
                self._values.update(good)
        record = self._store.update(app, values={**stored["values"], **good}) if good else stored
        self._publish_state()
        return {"sent": False, "values": record["values"], "errors": errors}

    # ----- lifecycle ---------------------------------------------------------------------

    def start(self, app: str, mode: str = "managed") -> dict:
        _require_app(app)
        if mode not in ("managed", "external"):
            raise ServiceError(f"unknown mode {mode!r}", status_code=400)
        record = self._store.load(app)
        command = record["command"].strip()
        if mode == "managed" and not command:
            raise ServiceError(f"set the command for {APPS[app].title} first",
                               status_code=409)
        with self._lock:
            if self._state in LIVE or self._state == STOPPING:
                running = APPS[self._app].title if self._app else "an app"
                raise ServiceError(f"{running} is running — stop it first",
                                   status_code=409)
            self._reset_locked()
            self._state = STARTING
            self._app = app
            self._mode = mode
            self._token = token = protocol.new_token()
            self._session_id = session_id = f"app-{uuid.uuid4().hex[:8]}"
            self._started_at = self.clock()
            self._schema = protocol.clean_schema(record["schema"])
            self._values = dict(record["values"])
        try:
            return self._launch(app, mode, command, session_id, token)
        except ServiceError:
            raise
        except Exception as e:
            # Never leave a session in STARTING behind, nor its process running.
            logger.exception("app start failed")
            self._end(f"start failed: {e}", error=f"start failed: {e}", wait=True)
            raise ServiceError(f"couldn't start {APPS[app].title}: {e}", status_code=500)

    def _launch(self, app: str, mode: str, command: str, session_id: str,
                token: str) -> dict:
        self._append_log(f"session {session_id}: starting {APPS[app].title} ({mode})")
        self._ensure_watchdog()
        if mode == "managed":
            url = f"ws://127.0.0.1:{self._settings.port}/ws/app"
            try:
                pid = self._process.spawn(command, url, token)
            except RuntimeError as e:
                self._end(str(e), error=str(e), wait=True)
                raise ServiceError(str(e), status_code=503)
            with self._lock:
                ended = self._session_id != session_id or self._state not in LIVE
                if not ended:
                    self._pid = pid
            if ended:
                # Stopped while the process was being started: it has no session.
                self._process.terminate()
                raise ServiceError("the app session was stopped while starting",
                                   status_code=409)
        self._publish_state()
        result = {"session": self.snapshot()}
        if mode == "external":
            result["token"] = token
        return result

    def _reset_locked(self) -> None:
        self._link = None
        self._pid = None
        self._hand = None
        self._hand_config = None
        self._errors = {}
        self._info = {}
        self._app_tracking = True
        self._lost_since = None
        self._last_target = None
        self._target_times.clear()
        self._ramp = None
        self._last_forwarded = {}
        self._halted = False
        self._frames = {}
        self._unknown_warned = False
        self._notice = None
        self._error = None
        self._log.clear()
        self._log_seq = 0

    def stop(self, session_id: str | None = None) -> bool:
        """End the session and wait until the app is gone. Clears an error.
        With ``session_id``, only that session (409 when another is current)."""
        if self._end("stopped", wait=True, expected=session_id):
            return True
        with self._lock:
            _check_session_locked(self._session_id, session_id)
            if self._state != ERROR:
                return False
            self._state = IDLE
            self._error = None
        self._publish_state()
        return True

    def halt_forwarding(self) -> None:
        """E-STOP, before torque off: forward no more targets to the hand. Only takes the lock."""
        with self._lock:
            self._halted = True

    def estop(self) -> bool:
        """E-STOP hook, called after torque is already off. Never blocks or raises."""
        try:
            return self._end("E-STOP", torque_off=False)
        except Exception:
            logger.exception("app estop failed")
            return False

    def shutdown(self) -> None:
        """Ends the session and waits, including an end already under way."""
        self._end("console shutting down", wait=True)
        ender = self._ender
        if ender is not None:
            ender.join(timeout=10.0)
        self._process.terminate()
        self._closed.set()
        watchdog = self._watchdog
        if watchdog is not None and watchdog.is_alive():
            watchdog.join(timeout=1.0)

    def _end(self, reason: str, *, error: str | None = None,
             torque_off: bool = True, wait: bool = False,
             expected: str | None = None) -> bool:
        """The one end path. False when no session was live."""
        with self._lock:
            if self._state not in LIVE:
                return False
            _check_session_locked(self._session_id, expected)
            was_engaged = self._state == ENGAGED
            self._state = STOPPING
            self._ramp = None
            link, self._link = self._link, None
            self._token = None
            session_id = self._session_id
        self._publish_state()

        def finish() -> None:
            try:
                if was_engaged:
                    if torque_off:
                        self._torque_off()
                    self._release_control()
                if link is not None:
                    try:
                        link.send_json({"type": protocol.MSG_STOP, "data": {}})
                        link.close()
                    except Exception:
                        logger.debug("app link close failed", exc_info=True)
                self._process.terminate()
                # Still STOPPING here, so no new session can start and receive these.
                self._append_log(f"session ended: {reason}"
                                 + (" — torque off" if was_engaged and torque_off else ""))
                self._publish_topic(T.APP_TARGETS, {"session_id": None, "angles": {},
                                                    "tracking": False})
                self._publish_topic(T.APP_FRAMES, {"session_id": None, "streams": {}})
            except Exception:
                logger.exception("app session end: cleanup failed")
            finally:
                # Whatever failed above, a session never stays in STOPPING.
                with self._lock:
                    if self._session_id == session_id:
                        self._state = ERROR if error else IDLE
                        self._error = error
                self._publish_state()

        if wait:
            finish()
        else:
            self._ender = threading.Thread(target=finish, name="AppSessionEnd", daemon=True)
            self._ender.start()
        return True

    def _torque_off(self) -> None:
        try:
            self._service.disable_torque()
        except Exception:
            logger.exception("app session end: torque off failed")

    # ----- engage / disengage --------------------------------------------------------

    def engage(self, ramp_s: float | None = None, *, session_id: str | None = None) -> dict:
        """Take the hand. Allowed while tracking is lost: the hand holds until
        targets arrive, then ramps in from where it is."""
        with self._lock:
            _check_session_locked(self._session_id, session_id)
            if self._state != PREVIEW:
                raise ServiceError(f"the app is not in preview (state: {self._state})",
                                   status_code=409)
            session_id = self._session_id
            title = APPS[self._app].title
        session = self._service.session
        if session is None:
            raise ServiceError("hand not connected", status_code=503)
        if not session.caps.motors:
            raise ServiceError("no motor bus in this session", status_code=409)
        if not self._service.supervisor.status().torque_enabled:
            raise ServiceError("torque is disabled — enable it first", status_code=409)

        self._service.acquire_control(ControlSource.APP, owner_label=f"app ({title})")
        try:
            try:
                start = self._service.current_pose()
            except ServiceError:
                raise
            except Exception as e:
                raise ServiceError(f"couldn't read the hand's pose: {e}", status_code=409)
            missing = sorted(set(self._ranges()) - set(start))
            if missing:
                raise ServiceError(
                    f"no current pose for {', '.join(missing)} — can't ramp in safely",
                    status_code=409)
            duration = max(float(self._settings.app_ramp_s if ramp_s is None else ramp_s),
                           MIN_RAMP_S)
            with self._lock:
                if self._state != PREVIEW or self._session_id != session_id:
                    raise ServiceError("the app session ended", status_code=409)
                self._state = ENGAGED
                self._notice = None
                self._last_forwarded = dict(start)
                self._ramp = _Ramp(start, duration)
                # A hold in preview doesn't count against the engaged session.
                self._lost_since = None if self._app_tracking else self.clock()
                self._browser_seen = False
                self._browser_gone_since = None
                self._send_locked(protocol.MSG_ENGAGED, {"engaged": True})
        except Exception:
            self._release_control()
            raise
        self._append_log(f"engaged (ramp {duration:.1f} s)")
        self._publish_state()
        return self.snapshot()

    def disengage(self, session_id: str | None = None) -> dict:
        self._disengage("disengaged", expected=session_id)
        return self.snapshot()

    def _disengage(self, reason: str, auto: bool = False,
                   expected: str | None = None) -> None:
        """Back to preview; the hand holds its pose with torque on."""
        with self._lock:
            _check_session_locked(self._session_id, expected)
            if self._state != ENGAGED:
                return
            self._state = PREVIEW
            self._ramp = None
            self._last_forwarded = {}
            self._notice = f"auto-disengaged — {reason}" if auto else None
            self._send_locked(protocol.MSG_ENGAGED, {"engaged": False})
        self._release_control()
        self._append_log(f"{'auto-disengaged' if auto else 'disengaged'}: {reason} "
                         "— holding the pose")
        self._publish_state()

    def _release_control(self) -> None:
        try:
            self._service.release_control(expected=ControlSource.APP)
        except Exception:
            logger.exception("app release_control failed")

    # ----- the app link (event loop) ----------------------------------------------------

    def on_hello(self, hello: dict, link) -> dict:
        """Validate ``hello``; returns ``hello_ok`` or raises HelloRejected."""
        config, hand = self._current_hand()
        with self._lock:
            if self._state != STARTING or self._link is not None:
                raise protocol.HelloRejected("no session is waiting for an app",
                                             protocol.CLOSE_SESSION_BUSY)
            name = protocol.check_hello(hello, token=self._token)
            self._link = link
            self._state = PREVIEW
            self._hand, self._hand_config = hand, config
            reply = protocol.hello_ok(self._session_id, hand, self._values)
        self._append_log(f"{name} connected — preview")
        self._publish_state()
        return reply

    def on_link_closed(self, link) -> None:
        with self._lock:
            if self._link is not link:
                return
        self._end("the app disconnected", error="the app disconnected")

    def on_message(self, link, kind: str, data: dict) -> None:
        with self._lock:
            if self._link is not link:
                return
        if kind == protocol.MSG_TARGETS:
            self._on_targets(data.get("angles"))
        elif kind == protocol.MSG_SETTINGS:
            self._on_settings(data)
        elif kind == protocol.MSG_STATUS:
            self._on_status(data)
        elif kind == protocol.MSG_FRAME:
            self._on_frame(data)
        elif kind == protocol.MSG_LOG:
            line = str(data.get("line", "")).strip()
            if line:
                level = data.get("level")
                self._append_log(f"[{level}] {line}" if level else line)

    def _on_targets(self, angles) -> None:
        """Hot path: clamp, publish for the ghost, forward when engaged."""
        now = self.clock()
        clean, unknown = clamp(protocol.finite_angles(angles), self._ranges())
        if unknown:
            self._warn_unknown(unknown)
        if not clean:
            return
        forward = None
        changed = False
        with self._lock:
            if self._state not in (PREVIEW, ENGAGED):
                return
            self._last_target = now
            self._target_times.append(now)
            engaged = self._state == ENGAGED
            if self._app_tracking and self._lost_since is not None:
                # Back from a hold: ramp again from the last command, never jump.
                held_at, self._lost_since = self._lost_since, None
                changed = True
                # An engage ramp nothing has used yet stays as it is.
                if engaged and not (self._ramp and not self._ramp.began):
                    self._ramp = _Ramp(dict(self._last_forwarded),
                                       self._resume_ramp_s_locked(held_at))
            if engaged and self._app_tracking and not self._halted:
                ramping = self._ramp is not None
                forward = self._blend_locked(clean, now)
                self._last_forwarded.update(forward)
                changed = changed or (ramping and self._ramp is None)
            payload = {"session_id": self._session_id, "angles": clean,
                       "tracking": self._lost_since is None}
        self._publish_topic(T.APP_TARGETS, payload)
        if forward:
            try:
                self._service.set_targets(forward, source=ControlSource.APP)
            except ServiceError as e:
                logger.debug("app targets refused: %s", e)
        if changed:
            self._publish_state()

    def _resume_ramp_s_locked(self, held_at: float) -> float:
        """Short after a hold, but a hold mid-ramp resumes with what was left of
        that ramp (from its latest joint), so the speed the user chose holds."""
        ramp = self._ramp
        base = ramp.duration if ramp else self._settings.app_ramp_s
        duration = min(max(base, MIN_RAMP_S), RE_RAMP_MAX_S)
        if ramp is not None and ramp.began:
            ran = max(held_at - max(ramp.began.values()), 0.0)
            duration = max(duration, ramp.duration - ran)
        return duration

    def _blend_locked(self, target: dict[str, float], now: float) -> dict[str, float]:
        ramp = self._ramp
        if ramp is None:
            return dict(target)
        pose, done = blend(ramp.start, target, ramp.began, now, ramp.duration)
        if done:
            self._ramp = None
        return pose

    def _on_settings(self, data: dict) -> None:
        schema = protocol.clean_schema(data.get("schema"))
        values = protocol.clean_values(data.get("values"))
        errors = data.get("errors") if isinstance(data.get("errors"), dict) else {}
        with self._lock:
            self._schema, self._values = schema, dict(values)
            self._errors = {str(k): str(v) for k, v in errors.items()}
            app = self._app
        self._store.update(app, schema=schema, values=dict(values))
        self._publish_state()

    def _on_status(self, data: dict) -> None:
        with self._lock:
            if isinstance(data.get("info"), dict):
                self._info = {str(k)[:64]: str(v)[:200]
                              for k, v in list(data["info"].items())[:16]}
            if "tracking" in data:
                self._app_tracking = bool(data["tracking"])
                if not self._app_tracking and self._lost_since is None:
                    self._lost_since = self.clock()
        self._publish_state()

    def _on_frame(self, data: dict) -> None:
        jpeg = data.get("jpeg")
        if not isinstance(jpeg, str) or not jpeg:
            return
        stream = str(data.get("stream") or "main")[:64]
        with self._lock:
            if stream not in self._frames and len(self._frames) >= MAX_STREAMS:
                return
            self._frame_seq += 1
            self._frames[stream] = {"jpeg": jpeg, "seq": self._frame_seq, "t": time.time()}
            payload = {"session_id": self._session_id, "streams": dict(self._frames)}
        self._publish_topic(T.APP_FRAMES, payload)

    def _warn_unknown(self, joints: list[str]) -> None:
        with self._lock:
            warned, self._unknown_warned = self._unknown_warned, True
        if not warned:
            self._append_log(f"ignoring joints this hand doesn't have: {sorted(joints)}")

    def _send_locked(self, kind: str, data: dict) -> None:
        if self._link is not None:
            try:
                self._link.send_json({"type": kind, "data": data})
            except Exception:
                logger.debug("app link send failed", exc_info=True)

    # ----- watchdog and safety rules ----------------------------------------------------------

    def _ensure_watchdog(self) -> None:
        """Started by the first session and kept until shutdown, so a quick
        Stop and Start can never leave a session without one."""
        with self._lock:
            if self._watchdog is not None:
                return
            self._watchdog = threading.Thread(target=self._watch, name="AppWatchdog",
                                              daemon=True)
        self._watchdog.start()

    def _watch(self) -> None:
        while not self._closed.wait(TICK_S):
            self.tick()

    def tick(self) -> None:
        """Run every safety rule once. The watchdog calls this every TICK_S."""
        now = self.clock()
        for rule in (self._rule_app_exited, self._rule_start_timeout,
                     self._rule_hand_changed, self._rule_hand_unavailable,
                     self._rule_hold, self._rule_auto_disengage,
                     self._rule_browser_closed):
            try:
                rule(now)
            except Exception:
                # One failing rule must not switch off the others.
                logger.exception("app safety rule %s failed", rule.__name__)

    def _state_now(self) -> str:
        with self._lock:
            return self._state

    def _rule_app_exited(self, now: float) -> None:
        """An app process that exits ends its session."""
        if self._state_now() in LIVE and self._mode == "managed":
            code = self._process.poll()
            if code is not None:
                self._end(f"the app exited (code {code})",
                          error=f"the app exited (code {code})")

    def _rule_start_timeout(self, now: float) -> None:
        """An app that never says hello is given up on."""
        with self._lock:
            late = self._state == STARTING and now - self._started_at > START_TIMEOUT_S
        if late:
            self._end("the app never connected", error="the app never connected")

    def _rule_hand_changed(self, now: float) -> None:
        """The app was told about one hand; a different one ends the session."""
        config = self._service.supervisor.config
        with self._lock:
            if self._hand is None or config is self._hand_config:
                return
            sent = self._hand
        _, hand = self._current_hand()
        if hand != sent:
            self._end("the hand changed", error="the hand changed — start the app again")
        else:
            with self._lock:
                self._hand_config = config

    def _rule_hand_unavailable(self, now: float) -> None:
        """No hand or no torque: an engaged session lets go."""
        if self._state_now() != ENGAGED:
            return
        if self._service.session is None or \
                not self._service.supervisor.status().torque_enabled:
            self._disengage("the hand is unavailable or torque is off", auto=True)

    def _rule_hold(self, now: float) -> None:
        """No fresh targets (or the app reports no tracking): hold the pose."""
        hold_after = self._settings.app_hold_after_ms / 1000.0
        with self._lock:
            if self._state not in (PREVIEW, ENGAGED) or self._lost_since is not None:
                return
            stale = self._last_target is None or now - self._last_target > hold_after
            if not (stale or not self._app_tracking):
                return
            self._lost_since = now
        self._append_log("no fresh targets — holding the pose")
        self._publish_state()

    def _rule_auto_disengage(self, now: float) -> None:
        """Held for too long: disengage."""
        limit = self._settings.app_disengage_after_s
        with self._lock:
            if limit <= 0 or self._state != ENGAGED or self._lost_since is None:
                return
            held_for = now - self._lost_since
        if held_for > limit:
            self._disengage(f"no targets for {held_for:.0f} s", auto=True)

    def _rule_browser_closed(self, now: float) -> None:
        """The last console browser tab closing disengages (after a grace for reloads)."""
        grace = self._settings.app_browser_grace_s
        if grace <= 0:
            return
        count = self._browsers()
        with self._lock:
            if self._state != ENGAGED:
                return
            if count > 0:
                self._browser_seen = True
                self._browser_gone_since = None
                return
            if not self._browser_seen:
                return
            if self._browser_gone_since is None:
                self._browser_gone_since = now
            gone_for = now - self._browser_gone_since
        if gone_for >= grace:
            self._disengage("the console's last browser tab closed", auto=True)

    # ----- log and publish -------------------------------------------------------------------

    def _append_log(self, line: str) -> None:
        with self._lock:
            self._log.append({"seq": self._log_seq, "t": time.time(),
                              "line": line[:LOG_LINE_CHARS]})
            self._log_seq += 1
        self._publish_topic(T.APP_LOG, self.log_payload())

    def _publish_state(self) -> None:
        self._publish_topic(T.APP_STATE, self.snapshot())


def _check_session_locked(current: str | None, expected: str | None) -> None:
    """A caller naming a session acts only on that one (a stale tab or agent)."""
    if expected is not None and expected != current:
        raise ServiceError(f"app session {expected} is no longer the current one "
                           f"(now {current or 'none'}) — refresh and try again",
                           status_code=409)


def _require_app(app: str) -> None:
    if app not in APPS:
        raise ServiceError(f"unknown app {app!r} (expected one of {sorted(APPS)})",
                           status_code=404)
