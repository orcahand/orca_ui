"""Per-motor fault accounting: bus errors + command adherence.

Two independent signals feed one ``motors.faults`` table:

- Bus errors. orca_core's motor clients report failed transactions through
  the logging module ("> write_byte: [Motor ID: 3] [TxRxResult] Port is in
  use!", overload reboots, sync-write failures) rather than raising, so a
  motor can be failing every write while the UI shows a healthy hand. A
  handler on the root logger parses those records into per-motor counters —
  which motor fails, how often, and what its last error was.

- Adherence. A motor can ack every packet and still not move (latched
  overload, slack tendon, mechanical jam). The tracking monitor compares
  each joint's commanded target against where the joint actually is;
  deviation sustained past a grace window counts as "not following", with
  the stall's duration and a per-session total accumulated.

Counters reset when a new session connects.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass, field

# Deviation that counts as "not on target". Generous on purpose: the command
# ramp plus tendon tracking lag sit well inside it during normal motion.
TRACKING_TOLERANCE_DEG = 10.0
# Deviation must persist this long before it becomes a stall — a large
# commanded jump legitimately spends a moment out of tolerance while the
# speed-capped ramp catches up.
TRACKING_GRACE_S = 1.5
# Ignore accumulation gaps longer than this (sampler stalled, reconnect).
MAX_ACCUMULATE_GAP_S = 5.0


# ---------------------------------------------------------------------------
# Bus errors (log-derived)
# ---------------------------------------------------------------------------

_MOTOR_RE = re.compile(r"\[Motor ID:\s*(\d+)\]\s*(.*)")
_OVERLOAD_RE = re.compile(r"Motor (\d+) overload detected")
_ID_LIST_RE = re.compile(
    r"(?:Sync write failed for|Could not set torque \w+ for IDs?):\s*"
    r"\[([\d,\s]*)\]")


def _summarize(message: str) -> str:
    """Strip the SDK's bracket noise down to the human part."""
    message = re.sub(r"\[TxRxResult\]\s*", "", message)
    message = re.sub(r"\[RxPacketError\]\s*", "", message)
    return message.strip() or "bus error"


@dataclass
class _MotorErrors:
    errors: int = 0
    overloads: int = 0
    last_error: str | None = None
    last_error_t: float | None = None


class BusErrorMonitor(logging.Handler):
    """Root-logger handler that turns orca_core's motor-client error records
    into per-motor counters.

    Only records from the root logger (the Dynamixel/Feetech clients call
    ``logging.error`` directly) and ``orca_core.*`` are considered, so
    orca_ui's own error logs never count as bus traffic.
    """

    def __init__(self):
        super().__init__(level=logging.WARNING)
        self._data_lock = threading.Lock()
        self._motors: dict[int, _MotorErrors] = {}
        self._bus_errors = 0
        self._bus_last: str | None = None
        self._bus_last_t: float | None = None

    def attach(self) -> None:
        logging.getLogger().addHandler(self)

    def detach(self) -> None:
        logging.getLogger().removeHandler(self)

    def emit(self, record: logging.LogRecord) -> None:
        if record.name != "root" and not record.name.startswith("orca_core"):
            return
        try:
            message = record.getMessage()
        except Exception:
            return
        try:
            self._ingest(message, record.levelno)
        except Exception:
            # A stats counter must never break the logging path.
            pass

    def _ingest(self, message: str, levelno: int) -> None:
        now = time.monotonic()
        overload = _OVERLOAD_RE.search(message)
        if overload:
            with self._data_lock:
                entry = self._motors.setdefault(int(overload.group(1)),
                                                _MotorErrors())
                entry.overloads += 1
                entry.last_error = "overload"
                entry.last_error_t = now
            return
        if levelno < logging.ERROR:
            return
        motor = _MOTOR_RE.search(message)
        if motor:
            summary = _summarize(motor.group(2))
            with self._data_lock:
                entry = self._motors.setdefault(int(motor.group(1)),
                                                _MotorErrors())
                entry.errors += 1
                entry.last_error = summary
                entry.last_error_t = now
                self._bus_errors += 1
                self._bus_last = summary
                self._bus_last_t = now
            return
        id_list = _ID_LIST_RE.search(message)
        if id_list:
            ids = [int(x) for x in id_list.group(1).split(",") if x.strip()]
            summary = _summarize(message.split(":")[0])
            with self._data_lock:
                for mid in ids:
                    entry = self._motors.setdefault(mid, _MotorErrors())
                    entry.errors += 1
                    entry.last_error = summary
                    entry.last_error_t = now
                self._bus_errors += len(ids)
                self._bus_last = summary
                self._bus_last_t = now

    def reset(self) -> None:
        with self._data_lock:
            self._motors.clear()
            self._bus_errors = 0
            self._bus_last = None
            self._bus_last_t = None

    @staticmethod
    def _age(then: float | None, now: float) -> float | None:
        return None if then is None else round(now - then, 1)

    def snapshot(self) -> dict:
        now = time.monotonic()
        with self._data_lock:
            return {
                "motors": {
                    mid: {
                        "errors": entry.errors,
                        "overloads": entry.overloads,
                        "last_error": entry.last_error,
                        "last_error_age_s": self._age(entry.last_error_t, now),
                    }
                    for mid, entry in self._motors.items()
                },
                "bus": {
                    "errors": self._bus_errors,
                    "last_error": self._bus_last,
                    "last_error_age_s": self._age(self._bus_last_t, now),
                },
            }


# ---------------------------------------------------------------------------
# Command adherence
# ---------------------------------------------------------------------------


@dataclass
class _JointTrack:
    out_since: float | None = None   # deviation first exceeded tolerance
    stalled: bool = False
    stalls: int = 0
    stalled_total_s: float = 0.0
    deviation: float | None = None
    last_update: float | None = None


@dataclass
class TrackingMonitor:
    """Sustained target-vs-actual deviation per joint.

    ``update`` runs at the sampler's mid rate with the last *written* command
    per joint and the sampled pose. Deviation beyond the tolerance for longer
    than the grace window marks the joint stalled; the stall's live duration
    and a cumulative per-session total are kept per joint.
    """

    tolerance_deg: float = TRACKING_TOLERANCE_DEG
    grace_s: float = TRACKING_GRACE_S
    _joints: dict[str, _JointTrack] = field(default_factory=dict)

    def update(self, targets: dict[str, float], actual: dict[str, float],
               now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        for joint, target in targets.items():
            value = actual.get(joint)
            if value is None:
                continue
            st = self._joints.setdefault(joint, _JointTrack())
            deviation = abs(float(target) - float(value))
            if deviation > self.tolerance_deg:
                # Only time spent already-stalled accumulates — the grace
                # window is legitimate travel, not fault time.
                if st.stalled and st.last_update is not None:
                    gap = now - st.last_update
                    if 0.0 < gap <= MAX_ACCUMULATE_GAP_S:
                        st.stalled_total_s += gap
                if st.out_since is None:
                    st.out_since = now
                elif not st.stalled and now - st.out_since >= self.grace_s:
                    st.stalled = True
                    st.stalls += 1
            else:
                st.out_since = None
                st.stalled = False
            st.deviation = deviation
            st.last_update = now

    def idle(self) -> None:
        """Nothing is commanding (torque off, direct motor mode, no session):
        deviation is expected, so live stall state clears. Totals survive."""
        for st in self._joints.values():
            st.out_since = None
            st.stalled = False
            st.deviation = None
            st.last_update = None

    def reset(self) -> None:
        self._joints.clear()

    def snapshot(self, now: float | None = None) -> dict[str, dict]:
        now = time.monotonic() if now is None else now
        out = {}
        for joint, st in self._joints.items():
            out[joint] = {
                "following": not st.stalled,
                "deviation_deg": (None if st.deviation is None
                                  else round(st.deviation, 1)),
                "stall_s": (round(now - st.out_since, 1)
                            if st.stalled and st.out_since is not None
                            else 0.0),
                "stalls": st.stalls,
                "stalled_total_s": round(st.stalled_total_s, 1),
            }
        return out
