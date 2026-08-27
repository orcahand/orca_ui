"""Lifetime per-joint usage statistics, organized into user-managed sessions.

Fed from the telemetry ticks and persisted to ``joint_usage.json`` next to
the hand's calibration.yaml, so the numbers describe THIS hand's mechanical
life on this computer.

Motion is logged ONLY while a joint is actually travelling: a step must
exceed the noise deadband to count, and dwell time (histogram/observed
seconds) accrues only in a short window around accepted movement. A hand
that is merely on — torque enabled, motors holding a commanded pose, sensors
streaming — accumulates nothing, no matter how long it sits there.

Sensor health, by contrast, is watched whenever the hand is connected:
per-joint encoder verdicts, tactile finger connections, sensing links and
the motor bus. State transitions are logged as events and unhealthy time is
accumulated per subsystem, into the same session.

The stats file holds a list of sessions. The UI can start a fresh session
(the old ones are kept for the lifetime total), delete individual sessions,
or wipe everything; "total" views stitch sessions together downstream.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

STATS_BASENAME = "joint_usage.json"
NUM_BINS = 24
# Ignore steps smaller than this: encoder noise is ~0.1°, real motion is not.
DEADBAND_DEG = 0.35
# Dwell time (histogram / observed seconds) accrues only this long after an
# accepted movement — a parked joint stops counting almost immediately.
ACTIVE_LINGER_S = 1.0
# A sample this long after the previous one is a gap (hand off / UI down):
# the elapsed time is not credited anywhere.
MAX_SAMPLE_GAP_S = 2.0
# Most "moving time" a single accepted step may credit: bounds how much
# stillness between two slow nudges counts as motion.
MOVING_CREDIT_MAX_S = 0.5
# Health samples ride the slow telemetry tick (~1 Hz); a longer silence is a
# disconnect, not downtime.
HEALTH_GAP_S = 5.0
MAX_HEALTH_EVENTS = 300
AUTOSAVE_S = 60.0
SCHEMA = 2


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def stats_path(calibration_path: str) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(calibration_path)),
                        STATS_BASENAME)


def _new_joint(rom: "list[float]") -> dict:
    return {
        "rom": [float(rom[0]), float(rom[1])],
        "travel_deg": 0.0,
        "moving_s": 0.0,
        "observed_s": 0.0,
        "hist": [0.0] * NUM_BINS,
        "min_deg": None,
        "max_deg": None,
        "reversals": 0,
        "max_speed_dps": 0.0,
        "first_seen": None,
        "last_active": None,
    }


def _new_health() -> dict:
    return {
        "observed_s": 0.0,
        "down_s": {},
        "events": [],
        "events_dropped": 0,
    }


def _new_session(label: "str | None" = None) -> dict:
    started = _now_iso()
    return {
        "id": f"s{uuid.uuid4().hex[:12]}",
        "label": label,
        "started_at": started,
        "ended_at": None,
        "joints": {},
        "health": _new_health(),
    }


def _append_session(data: dict, label: "str | None" = None) -> dict:
    """Append a fresh session; unnamed ones get an automatic sequential
    name ("session N") the user can rename later. There is always exactly
    one running session — the last in the list."""
    if not label:
        seq = int(data.get("session_seq", 0)) + 1
        data["session_seq"] = seq
        label = f"session {seq}"
    session = _new_session(label)
    data["sessions"].append(session)
    return session


class JointUsageTracker:
    """Accumulates joint motion + sensor health; thread-safe; persists itself.

    ``feed``/``feed_health`` run on telemetry threads; the session management
    and ``snapshot`` on request threads.
    """

    def __init__(self, path: str, joint_roms: "dict[str, list]"):
        self._path = path
        self._roms = {j: [float(r[0]), float(r[1])]
                      for j, r in joint_roms.items()}
        self._lock = threading.Lock()
        self._dirty = False
        self._data = self._load()   # a v1 migration marks the tracker dirty
        # Volatile per-joint motion state and health change-detection state
        # (never persisted).
        self._live: dict[str, dict] = {}
        self._health_state: dict[str, str] = {}
        self._last_health_mono: float | None = None
        self._last_save_mono = time.monotonic()

    # ----- persistence ---------------------------------------------------------

    def _load(self) -> dict:
        try:
            with open(self._path, encoding="utf-8") as f:
                data = json.load(f)
            if data.get("schema") == SCHEMA and isinstance(
                    data.get("sessions"), list) and data["sessions"]:
                return data
            if data.get("schema") == 1 and isinstance(
                    data.get("joints"), dict):
                # v1 had one flat joint table: carry it over as a closed
                # session so nothing already accumulated is lost.
                imported = _new_session(label="imported")
                imported["started_at"] = data.get("created_at") or _now_iso()
                imported["ended_at"] = data.get("updated_at") or _now_iso()
                imported["joints"] = data["joints"]
                self._dirty = True
                migrated = {"schema": SCHEMA,
                            "created_at": data.get("created_at") or _now_iso(),
                            "updated_at": None,
                            "sessions": [imported]}
                _append_session(migrated)
                return migrated
            logger.warning("usage stats at %s have an unknown schema — "
                           "starting fresh", self._path)
        except FileNotFoundError:
            pass
        except Exception:
            logger.exception("could not load usage stats — starting fresh")
        fresh = {"schema": SCHEMA, "created_at": _now_iso(),
                 "updated_at": None, "sessions": []}
        _append_session(fresh)
        return fresh

    def save(self) -> None:
        with self._lock:
            if not self._dirty:
                return
            self._data["updated_at"] = _now_iso()
            payload = json.dumps(self._data, separators=(",", ":"))
            self._dirty = False
            self._last_save_mono = time.monotonic()
        try:
            tmp = self._path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(payload)
            os.replace(tmp, self._path)
        except Exception:
            logger.exception("could not save usage stats")

    # ----- sessions ------------------------------------------------------------

    def _current(self) -> dict:
        return self._data["sessions"][-1]

    def new_session(self, label: "str | None" = None) -> str:
        """Close the running session and start a fresh one (auto-named
        unless a label is given)."""
        with self._lock:
            self._current()["ended_at"] = _now_iso()
            session = _append_session(self._data, label)
            self._live = {}
            self._health_state = {}
            self._dirty = True
            session_id = session["id"]
        self.save()
        return session_id

    def delete_session(self, session_id: str) -> bool:
        """Remove one session. Deleting the running one starts a fresh one."""
        with self._lock:
            sessions = self._data["sessions"]
            index = next((i for i, s in enumerate(sessions)
                          if s["id"] == session_id), None)
            if index is None:
                return False
            was_current = index == len(sessions) - 1
            del sessions[index]
            if was_current or not sessions:
                _append_session(self._data)
                self._live = {}
                self._health_state = {}
            self._dirty = True
        self.save()
        return True

    def rename_session(self, session_id: str, label: str) -> bool:
        with self._lock:
            for session in self._data["sessions"]:
                if session["id"] == session_id:
                    session["label"] = label or None
                    self._dirty = True
                    break
            else:
                return False
        self.save()
        return True

    def reset(self) -> None:
        """Wipe everything and start over with one empty session."""
        with self._lock:
            self._data = {"schema": SCHEMA, "created_at": _now_iso(),
                          "updated_at": None, "sessions": []}
            _append_session(self._data)
            self._live = {}
            self._health_state = {}
            self._dirty = True
        self.save()

    # ----- motion accumulation -------------------------------------------------

    def feed(self, angles: "dict[str, float] | None",
             now: float | None = None) -> None:
        """Accumulate one angles sample into the running session.

        ``now`` (monotonic seconds) is injectable for tests; production
        callers leave it None.
        """
        if not angles:
            return
        if now is None:
            now = time.monotonic()
        with self._lock:
            session = self._current()
            moved = False
            for joint, value in angles.items():
                try:
                    angle = float(value)
                except (TypeError, ValueError):
                    continue
                moved |= self._feed_joint(session, joint, angle, now)
            if moved:
                self._dirty = True
        if now - self._last_save_mono >= AUTOSAVE_S:
            self.save()

    def _feed_joint(self, session: dict, joint: str, angle: float,
                    now: float) -> bool:
        """Returns True when the sample changed the stats at all."""
        live = self._live.get(joint)
        if live is None:
            self._live[joint] = {
                "t": now, "anchor": angle, "anchor_t": now, "sign": 0,
                "active_until": 0.0}
            return False

        dt = now - live["t"]
        live["t"] = now
        if dt <= 0 or dt > MAX_SAMPLE_GAP_S:
            # Gap: re-anchor so the jump is not counted as travel.
            live["anchor"] = angle
            live["anchor_t"] = now
            live["sign"] = 0
            live["active_until"] = 0.0
            return False

        delta = angle - live["anchor"]
        active = now <= live["active_until"]
        if abs(delta) < DEADBAND_DEG:
            # Still (or noise): dwell time only accrues in the short window
            # after real movement — a parked joint logs nothing, even under
            # a standing position command.
            if active:
                stats = self._stats(session, joint)
                self._observe(stats, angle, dt)
                return True
            return False

        stats = self._stats(session, joint)
        self._observe(stats, angle, dt)
        stats["travel_deg"] += abs(delta)
        stats["moving_s"] += min(now - live["anchor_t"], MOVING_CREDIT_MAX_S)
        speed = abs(delta) / max(now - live["anchor_t"], 1e-3)
        if speed > stats["max_speed_dps"]:
            stats["max_speed_dps"] = round(speed, 1)
        sign = 1 if delta > 0 else -1
        if live["sign"] != 0 and sign != live["sign"]:
            stats["reversals"] += 1
        live["sign"] = sign
        live["anchor"] = angle
        live["anchor_t"] = now
        live["active_until"] = now + ACTIVE_LINGER_S
        stats["last_active"] = _now_iso()
        return True

    def _stats(self, session: dict, joint: str) -> dict:
        stats = session["joints"].get(joint)
        if stats is None:
            rom = self._roms.get(joint, [0.0, 1.0])
            stats = session["joints"][joint] = _new_joint(rom)
            stats["first_seen"] = _now_iso()
        return stats

    @staticmethod
    def _observe(stats: dict, angle: float, dt: float) -> None:
        if stats["min_deg"] is None or angle < stats["min_deg"]:
            stats["min_deg"] = round(angle, 2)
        if stats["max_deg"] is None or angle > stats["max_deg"]:
            stats["max_deg"] = round(angle, 2)
        if dt <= 0:
            return
        stats["observed_s"] += dt
        lower, upper = stats["rom"]
        span = upper - lower
        if span <= 0:
            return
        index = int((angle - lower) / span * NUM_BINS)
        stats["hist"][min(max(index, 0), NUM_BINS - 1)] += dt

    # ----- sensor health -------------------------------------------------------

    def feed_health(self, payload: "dict | None", caps,
                    now: float | None = None) -> None:
        """One sensors-health sample (the slow telemetry tick's payload).

        Health is watched whenever the hand is connected — connections and
        dropouts matter exactly when the hand is idle too. State transitions
        become events; unhealthy time accumulates per subsystem.
        """
        if now is None:
            now = time.monotonic()
        states: dict[str, str] = {}
        if caps is not None:
            states["motors"] = "up" if getattr(caps, "motors", False) else "down"
        encoders = (payload or {}).get("encoders")
        if encoders and encoders.get("joints"):
            for joint, info in encoders["joints"].items():
                states[f"encoder:{joint}"] = info.get("verdict") or "unknown"
        tactile = (payload or {}).get("tactile")
        if tactile and tactile.get("fingers"):
            for finger, info in tactile["fingers"].items():
                states[f"tactile:{finger}"] = (
                    "up" if info.get("connected") else "down")
        for name, link in ((payload or {}).get("links") or {}).items():
            healthy = link.get("connected") and not link.get("port_dead")
            states[f"link:{name}"] = "up" if healthy else "down"

        with self._lock:
            session = self._current()
            health = session.setdefault("health", _new_health())
            last = self._last_health_mono
            self._last_health_mono = now
            dt = 0.0 if last is None else now - last
            if 0 < dt <= HEALTH_GAP_S:
                health["observed_s"] += dt
                for key, state in states.items():
                    if not _healthy(key, state):
                        down = health["down_s"]
                        down[key] = down.get(key, 0.0) + dt
            for key, state in states.items():
                previous = self._health_state.get(key)
                self._health_state[key] = state
                # The very first sample only logs if something is wrong —
                # "everything came up healthy" is not an event.
                if previous == state or (
                        previous is None and _healthy(key, state)):
                    continue
                if len(health["events"]) >= MAX_HEALTH_EVENTS:
                    health["events_dropped"] += 1
                else:
                    health["events"].append({
                        "t": _now_iso(),
                        "subject": key,
                        "from": previous,
                        "to": state,
                    })
            self._dirty = True
        if now - self._last_save_mono >= AUTOSAVE_S:
            self.save()

    # ----- reads ---------------------------------------------------------------

    def snapshot(self) -> dict:
        with self._lock:
            data = json.loads(json.dumps(self._data))
        sessions = data["sessions"]
        for session in sessions:
            for stats in session["joints"].values():
                stats["travel_deg"] = round(stats["travel_deg"], 1)
                stats["moving_s"] = round(stats["moving_s"], 1)
                stats["observed_s"] = round(stats["observed_s"], 1)
                stats["hist"] = [round(v, 1) for v in stats["hist"]]
            health = session.get("health") or _new_health()
            health["observed_s"] = round(health["observed_s"], 1)
            health["down_s"] = {k: round(v, 1)
                                for k, v in health["down_s"].items()}
            session["health"] = health
        return {
            "path": self._path,
            "created_at": data.get("created_at"),
            "updated_at": data.get("updated_at"),
            "bins": NUM_BINS,
            "current_id": sessions[-1]["id"] if sessions else None,
            "sessions": sessions,
        }


def _healthy(key: str, state: str) -> bool:
    if key.startswith("encoder:"):
        return state == "live"
    return state == "up"
