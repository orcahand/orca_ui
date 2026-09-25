"""Endurance-test recorder: what the hand settled to at every waypoint hold.

A long looping replay is an endurance test. What matters afterwards is not
how far the hand moved but *when* something changed: the holding current a
motor needs at the flexed extreme (it falls as its tendon slackens and
collapses when the tendon snaps), the range a joint actually settles into,
the force a fingertip reports at the grip pose, a tactile sensor going quiet
or noisy, a motor latching a hardware error, torque dropping, and how much
motor travel each calibration checkpoint measures between the hardstops.

The recorder adds no bus traffic. Every per-reversal sample is the read the
player already makes while it holds at a waypoint until the hand arrives
(``sampled_state`` — one transaction for positions and currents), and every
other input is a telemetry payload the console already assembles. Nothing is
polled during motion.

Persistence, next to ``joint_usage.json``:

- ``endurance.json`` — the list of tests, each bounded: events and
  checkpoints at full resolution up to a cap, per-reversal samples rolled
  into time buckets whose width doubles whenever the count would exceed
  ``MAX_BUCKETS``. Whatever the test length, the summary stays a few hundred
  kilobytes.
- ``endurance/<test id>.csv`` — every per-reversal sample as recorded, one
  row per hold: seconds since the test started, run, cycle, leg, settled
  angle per joint, holding current per motor, fingertip force per finger.
  Append-only, never read back by the console; served for download.
"""

from __future__ import annotations

import json
import logging
import math
import os
import threading
import time
import uuid
from datetime import datetime, timezone

from orca_ui.hand import calibration_log

logger = logging.getLogger(__name__)

ENDURANCE_BASENAME = "endurance.json"
SAMPLES_DIRNAME = "endurance"
SCHEMA = 1
AUTOSAVE_S = 60.0
# Buckets start this wide and double whenever a test outgrows MAX_BUCKETS, so
# a one-hour test plots at 10 s resolution and a 60-hour one at ~11 min.
INITIAL_BUCKET_S = 10.0
MAX_BUCKETS = 360
MAX_EVENTS = 5000
MAX_CHECKPOINTS = 500
MAX_RUNS = 500
# A fingertip force older than this at a hold is not the force at the hold.
FORCE_FRESH_S = 2.0
# Unflushed CSV rows are appended at the autosave or after this many holds.
CSV_FLUSH_ROWS = 50

TERMINAL_OP_STATES = frozenset({"done", "error"})


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def recorder_path(calibration_path: str) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(calibration_path)),
                        ENDURANCE_BASENAME)


def force_magnitudes(forces: dict | None, taxels: dict | None) -> dict[str, float]:
    """Per-finger fingertip force magnitude (N) from whichever stream is
    armed: the resultant vector, else the vector sum of the taxels."""
    out: dict[str, float] = {}
    if forces:
        for finger, vec in forces.items():
            try:
                out[finger] = math.sqrt(sum(float(v) ** 2 for v in vec))
            except (TypeError, ValueError):
                continue
    elif taxels:
        for finger, rows in taxels.items():
            try:
                total = [0.0, 0.0, 0.0]
                for row in rows:
                    for axis in range(3):
                        total[axis] += float(row[axis])
                out[finger] = math.sqrt(sum(v * v for v in total))
            except (TypeError, ValueError, IndexError):
                continue
    return out


def _finite(value) -> float | None:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


class EnduranceRecorder:
    """Thread-safe; fed from the operation thread (``record_hold``), the fast
    telemetry tick (``feed_forces``) and the slow tick (``observe``); managed
    from request threads."""

    def __init__(self, path: str, calibration_path: str, joints: list[str],
                 motors: list[int], motor_joint: dict[int, str],
                 fingers: list[str]):
        self._path = path
        self._calibration_path = calibration_path
        self._joints = [str(j) for j in joints]
        self._motors = [int(m) for m in motors]
        self._motor_joint = {int(m): str(j) for m, j in motor_joint.items()}
        self._fingers = [str(f) for f in fingers]
        self._lock = threading.Lock()
        self._dirty = False
        self._data = self._load()
        self._last_save_mono = time.monotonic()
        # Volatile: latest fingertip forces, change-detection baselines for
        # events, the run being tracked, unflushed CSV rows.
        self._forces: dict[str, float] = {}
        self._forces_mono = 0.0
        self._states: dict[str, str] = {}
        self._stream_zero_ticks = 0
        self._run_id: str | None = None
        self._csv_rows: list[str] = []

    # ----- persistence ---------------------------------------------------------

    def _load(self) -> dict:
        try:
            with open(self._path, encoding="utf-8") as f:
                data = json.load(f)
            if data.get("schema") == SCHEMA and isinstance(data.get("tests"), list):
                return data
            logger.warning("endurance record at %s has an unknown schema — "
                           "starting fresh", self._path)
        except FileNotFoundError:
            pass
        except Exception:
            logger.exception("could not load endurance record — starting fresh")
        return {"schema": SCHEMA, "created_at": _now_iso(), "updated_at": None,
                "active_id": None, "tests": []}

    def save(self) -> None:
        with self._lock:
            rows, self._csv_rows = self._csv_rows, []
            active = self._active()
            csv_path = self._samples_path(active["id"]) if active else None
            payload = None
            if self._dirty:
                self._data["updated_at"] = _now_iso()
                payload = json.dumps(self._data, separators=(",", ":"))
                self._dirty = False
            self._last_save_mono = time.monotonic()
        if rows and csv_path:
            try:
                with open(csv_path, "a", encoding="utf-8") as f:
                    f.write("".join(rows))
            except Exception:
                logger.exception("could not append endurance samples")
        if payload is None:
            return
        try:
            tmp = self._path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(payload)
            os.replace(tmp, self._path)
        except Exception:
            logger.exception("could not save endurance record")

    def _autosave(self) -> None:
        if (time.monotonic() - self._last_save_mono >= AUTOSAVE_S
                or len(self._csv_rows) >= CSV_FLUSH_ROWS):
            self.save()

    def _samples_dir(self) -> str:
        return os.path.join(os.path.dirname(self._path), SAMPLES_DIRNAME)

    def _samples_path(self, test_id: str) -> str:
        return os.path.join(self._samples_dir(), f"{test_id}.csv")

    def samples_path(self, test_id: str) -> str | None:
        with self._lock:
            if self._find(test_id) is None:
                return None
        path = self._samples_path(test_id)
        return path if os.path.exists(path) else None

    # ----- tests ---------------------------------------------------------------

    def _find(self, test_id: str) -> dict | None:
        return next((t for t in self._data["tests"] if t["id"] == test_id), None)

    def _active(self) -> dict | None:
        active_id = self._data.get("active_id")
        return self._find(active_id) if active_id else None

    def start(self, label: str | None = None) -> dict:
        """Begin a test: t0 is now. Refuses while another test is running."""
        with self._lock:
            if self._active() is not None:
                raise RuntimeError("an endurance test is already running — "
                                   "stop it first")
            seq = int(self._data.get("test_seq", 0)) + 1
            self._data["test_seq"] = seq
            test = {
                "id": f"e{uuid.uuid4().hex[:12]}",
                "label": label or f"test {seq}",
                "started_at": _now_iso(),
                "ended_at": None,
                "t0": time.time(),
                "joints": list(self._joints),
                "motors": list(self._motors),
                "motor_joint": {str(m): j for m, j in self._motor_joint.items()},
                "fingers": list(self._fingers),
                "samples": 0,
                "closed_cycles": 0,
                "cycles_total": 0,
                "bucket_s": INITIAL_BUCKET_S,
                "buckets": [],
                "runs": [],
                "runs_dropped": 0,
                "events": [],
                "events_dropped": 0,
                "checkpoints": [],
                "checkpoints_dropped": 0,
                "latest": None,
            }
            self._data["tests"].append(test)
            self._data["active_id"] = test["id"]
            # Every test starts its own baselines: the first observation of
            # each subsystem is not a transition.
            self._states = {}
            self._run_id = None
            self._dirty = True
            header = self._csv_header()
            path = self._samples_path(test["id"])
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(header)
        except Exception:
            logger.exception("could not create endurance samples file")
        self.save()
        return self.test(test["id"]) or {}

    def stop(self, test_id: str) -> bool:
        with self._lock:
            test = self._find(test_id)
            if test is None:
                return False
            if self._data.get("active_id") == test_id:
                test["ended_at"] = _now_iso()
                self._event(test, self._elapsed(test), "test", "test",
                            "stopped")
                self._data["active_id"] = None
                self._dirty = True
        self.save()
        return True

    def rename(self, test_id: str, label: str) -> bool:
        with self._lock:
            test = self._find(test_id)
            if test is None:
                return False
            test["label"] = label or test["label"]
            self._dirty = True
        self.save()
        return True

    def delete(self, test_id: str) -> bool:
        with self._lock:
            test = self._find(test_id)
            if test is None:
                return False
            self._data["tests"].remove(test)
            if self._data.get("active_id") == test_id:
                self._data["active_id"] = None
                self._csv_rows = []
            self._dirty = True
            path = self._samples_path(test_id)
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        except Exception:
            logger.exception("could not remove endurance samples file")
        self.save()
        return True

    def note(self, test_id: str, text: str) -> bool:
        """Operator marker: a tendon replaced, a sensor reseated, anything
        the plots should be read against."""
        with self._lock:
            test = self._find(test_id)
            if test is None:
                return False
            self._event(test, self._elapsed(test), "note", "operator", text)
        self.save()
        return True

    # ----- per-reversal samples ------------------------------------------------

    def feed_forces(self, forces: dict | None, taxels: dict | None) -> None:
        """Latest fingertip forces from the fast tick's in-memory tactile read."""
        magnitudes = force_magnitudes(forces, taxels)
        if not magnitudes:
            return
        with self._lock:
            self._forces = magnitudes
            self._forces_mono = time.monotonic()

    def record_hold(self, joints: dict | None, currents: dict | None,
                    cycle: int | None, leg: int | None) -> None:
        """One settled sample: what the hand read at the end of a waypoint
        hold. ``joints`` are the sampled angles (deg), ``currents`` the
        per-motor holding currents (mA) from the same read, or None on a hand
        whose joint source is not the motors."""
        if not joints:
            return
        with self._lock:
            test = self._active()
            if test is None:
                return
            t = self._elapsed(test)
            cycle = int(cycle or 0)
            cycle_total = int(test["closed_cycles"]) + cycle
            angles = {j: _finite(joints.get(j)) for j in test["joints"]}
            amps = {}
            if currents:
                for m in test["motors"]:
                    value = currents.get(m, currents.get(str(m)))
                    amps[str(m)] = _finite(value)
            forces = {}
            if self._forces and time.monotonic() - self._forces_mono <= FORCE_FRESH_S:
                forces = {f: _finite(self._forces.get(f)) for f in test["fingers"]}
            test["samples"] += 1
            test["cycles_total"] = max(int(test["cycles_total"]), cycle_total)
            test["latest"] = {
                "t": round(t, 3), "cycle": cycle, "cycle_total": cycle_total,
                "leg": leg, "run_id": self._run_id,
                "angles": {j: None if v is None else round(v, 2)
                           for j, v in angles.items()},
                "currents": {m: None if v is None else round(v, 1)
                             for m, v in amps.items()},
                "forces": {f: None if v is None else round(v, 2)
                           for f, v in forces.items()},
            }
            self._bucket(test, t, cycle_total, angles, amps, forces)
            self._csv_rows.append(self._csv_row(
                test, t, self._run_id or "", cycle, cycle_total, leg, angles,
                amps, forces))
            self._dirty = True
        self._autosave()

    def _bucket(self, test: dict, t: float, cycle_total: int, angles: dict,
                amps: dict, forces: dict) -> None:
        width = float(test["bucket_s"])
        index = int(t // width)
        buckets = test["buckets"]
        bucket = buckets[-1] if buckets else None
        if bucket is None or bucket["i"] != index:
            bucket = {"i": index, "t0": round(index * width, 1),
                      "t1": round((index + 1) * width, 1), "n": 0,
                      "c0": cycle_total, "c1": cycle_total,
                      "angle": {}, "current": {}, "force": {}}
            buckets.append(bucket)
            if len(buckets) > MAX_BUCKETS:
                self._coarsen(test)
                bucket = test["buckets"][-1]
        bucket["n"] += 1
        bucket["c1"] = max(bucket["c1"], cycle_total)
        for joint, value in angles.items():
            if value is None:
                continue
            cell = bucket["angle"].get(joint)
            if cell is None:
                bucket["angle"][joint] = [round(value, 2), round(value, 2)]
            else:
                cell[0] = min(cell[0], round(value, 2))
                cell[1] = max(cell[1], round(value, 2))
        for table, values, digits in (("current", amps, 1), ("force", forces, 2)):
            for key, value in values.items():
                if value is None:
                    continue
                cell = bucket[table].get(key)
                if cell is None:
                    bucket[table][key] = [value, value, 1]
                else:
                    cell[0] += (value - cell[0]) / (cell[2] + 1)
                    cell[1] = max(cell[1], value)
                    cell[2] += 1

    @staticmethod
    def _coarsen(test: dict) -> None:
        """Double the bucket width, merging neighbours pairwise."""
        width = float(test["bucket_s"]) * 2.0
        merged: list[dict] = []
        for bucket in test["buckets"]:
            index = int(bucket["t0"] // width)
            into = merged[-1] if merged and merged[-1]["i"] == index else None
            if into is None:
                bucket = dict(bucket, i=index, t0=round(index * width, 1),
                              t1=round((index + 1) * width, 1))
                merged.append(bucket)
                continue
            into["n"] += bucket["n"]
            into["c0"] = min(into["c0"], bucket["c0"])
            into["c1"] = max(into["c1"], bucket["c1"])
            for joint, cell in bucket["angle"].items():
                mine = into["angle"].get(joint)
                into["angle"][joint] = (list(cell) if mine is None else
                                        [min(mine[0], cell[0]),
                                         max(mine[1], cell[1])])
            for table in ("current", "force"):
                for key, cell in bucket[table].items():
                    mine = into[table].get(key)
                    if mine is None:
                        into[table][key] = list(cell)
                        continue
                    n = mine[2] + cell[2]
                    mine[0] = (mine[0] * mine[2] + cell[0] * cell[2]) / n
                    mine[1] = max(mine[1], cell[1])
                    mine[2] = n
        test["bucket_s"] = width
        test["buckets"] = merged

    # ----- CSV -----------------------------------------------------------------

    def _csv_header(self) -> str:
        columns = ["t_s", "run_id", "cycle", "cycle_total", "leg"]
        columns += [f"angle_deg:{j}" for j in self._joints]
        columns += [f"current_ma:{m}" for m in self._motors]
        columns += [f"force_n:{f}" for f in self._fingers]
        return ",".join(columns) + "\n"

    @staticmethod
    def _csv_row(test: dict, t: float, run_id: str, cycle: int,
                 cycle_total: int, leg: int | None, angles: dict, amps: dict,
                 forces: dict) -> str:
        def cell(value, digits):
            return "" if value is None else f"{value:.{digits}f}"

        fields = [f"{t:.3f}", run_id, str(cycle), str(cycle_total),
                  "" if leg is None else str(leg)]
        fields += [cell(angles.get(j), 2) for j in test["joints"]]
        fields += [cell(amps.get(str(m)), 1) for m in test["motors"]]
        fields += [cell(forces.get(f), 2) for f in test["fingers"]]
        return ",".join(fields) + "\n"

    # ----- events from the slow tick -------------------------------------------

    def observe(self, health: dict | None, faults: dict | None,
                operation: dict | None, torque_enabled: bool | None) -> None:
        """One slow-tick observation of everything that can change state.
        Transitions become events; a finished calibration becomes a
        checkpoint. Nothing here reads hardware."""
        with self._lock:
            test = self._active()
            if test is None:
                self._run_id = (operation or {}).get("run_id")
                return
            t = self._elapsed(test)
            self._observe_operation(test, operation, t)
            if torque_enabled is not None:
                self._transition(test, t, "torque", "torque",
                                 "on" if torque_enabled else "off",
                                 healthy="on")
            self._observe_faults(test, faults, t)
            self._observe_health(test, health, t)
            test["cycles_total"] = max(int(test["cycles_total"]),
                                       int(test["closed_cycles"]))
        self._autosave()

    def _observe_operation(self, test: dict, snap: dict | None, t: float) -> None:
        run_id = snap.get("run_id") if snap else None
        run = test["runs"][-1] if test["runs"] else None
        if run is not None and run["run_id"] != self._run_id:
            run = None
        if run_id != self._run_id:
            if run is not None and run.get("ended_t") is None:
                run["ended_t"] = round(t, 3)
                run["state"] = "lost"
            self._run_id = run_id
            run = None
            # The run's own start time places it: one that began before the
            # test is a leftover, whatever state it is in now, while one that
            # began and finished between two ticks still belongs here.
            started = _finite(snap.get("started_at")) if snap else None
            started_t = None if started is None else started - float(test["t0"])
            if snap and (started_t is None or started_t >= 0.0):
                t_start = t if started_t is None else max(started_t, 0.0)
                run = {"run_id": run_id, "kind": snap.get("kind"),
                       "params": snap.get("params") or {},
                       "t": round(t_start, 3), "ended_t": None, "cycles": 0,
                       "state": snap.get("state")}
                if len(test["runs"]) >= MAX_RUNS:
                    del test["runs"][0]
                    test["runs_dropped"] += 1
                test["runs"].append(run)
                self._event(test, t_start, "operation", str(snap.get("kind")),
                            "started " + _describe_params(snap.get("params")))
        if snap is None or run is None or run.get("ended_t") is not None:
            return
        extra = snap.get("extra") or {}
        cycle = extra.get("cycle")
        if isinstance(cycle, (int, float)):
            run["cycles"] = max(int(run["cycles"]), int(cycle))
        run["state"] = snap.get("state")
        test["cycles_total"] = max(int(test["cycles_total"]),
                                   int(test["closed_cycles"]) + int(run["cycles"]))
        if snap.get("state") in TERMINAL_OP_STATES:
            result = snap.get("result") or {}
            cycles = result.get("cycles")
            if isinstance(cycles, (int, float)):
                run["cycles"] = int(cycles)
            run["ended_t"] = round(t, 3)
            test["closed_cycles"] = int(test["closed_cycles"]) + int(run["cycles"])
            if snap.get("state") == "error":
                detail = f"error: {snap.get('error')}"
            else:
                stopped = "stopped" in str(snap.get("detail") or "")
                detail = "stopped" if stopped else "done"
                if isinstance(cycles, (int, float)) or run["cycles"]:
                    detail += f" · {run['cycles']} cycle(s)"
            self._event(test, t, "operation", str(snap.get("kind")), detail)
            if snap.get("kind") == "calibrate":
                self._checkpoint(test, t)

    def _observe_faults(self, test: dict, faults: dict | None, t: float) -> None:
        for mid, entry in ((faults or {}).get("motors") or {}).items():
            flags = entry.get("hw_error_flags") or []
            info = entry.get("hw_error") or {}
            state = "ok" if not flags else (
                f"{info.get('kind') or 'latched'}: {', '.join(flags)}")
            joint = entry.get("joint") or self._motor_joint.get(int(mid))
            subject = f"motor {mid}" + (f" ({joint})" if joint else "")
            self._transition(test, t, "fault", subject, state, healthy="ok",
                             detail=info.get("headline"))

    def _observe_health(self, test: dict, health: dict | None, t: float) -> None:
        if not health:
            return
        tactile = health.get("tactile")
        if tactile:
            # The rate needs two ticks to exist at all, so one zero reading
            # is not a stall; two in a row are.
            if (tactile.get("hz") or 0) > 0:
                self._stream_zero_ticks = 0
                self._transition(test, t, "tactile", "tactile stream",
                                 "streaming", healthy="streaming")
            else:
                self._stream_zero_ticks += 1
                if self._stream_zero_ticks >= 2:
                    self._transition(test, t, "tactile", "tactile stream",
                                     "stalled", healthy="streaming")
            for finger, info in (tactile.get("fingers") or {}).items():
                if not info.get("connected"):
                    state = "disconnected"
                else:
                    state = info.get("verdict") or "live"
                self._transition(test, t, "tactile", f"{finger} fingertip",
                                 state, healthy="live",
                                 detail=info.get("reason"))
        encoders = health.get("encoders")
        if encoders:
            for joint, info in (encoders.get("joints") or {}).items():
                self._transition(test, t, "encoder", f"{joint} encoder",
                                 info.get("verdict") or "unknown",
                                 healthy="live", detail=info.get("reason"))
        for name, link in (health.get("links") or {}).items():
            up = bool(link.get("connected")) and not link.get("port_dead")
            self._transition(test, t, "link", f"{name} link",
                             "up" if up else "down", healthy="up",
                             detail=link.get("port_error"))

    def _transition(self, test: dict, t: float, kind: str, subject: str,
                    state: str, healthy: str, detail: str | None = None) -> None:
        previous = self._states.get(subject)
        self._states[subject] = state
        if previous == state or (previous is None and state == healthy):
            return
        text = f"{previous or 'unknown'} → {state}"
        if detail:
            text += f" ({detail})"
        self._event(test, t, kind, subject, text,
                    severity="ok" if state == healthy else "bad")

    def _event(self, test: dict, t: float, kind: str, subject: str,
               detail: str, severity: str = "info") -> None:
        if len(test["events"]) >= MAX_EVENTS:
            test["events_dropped"] += 1
            return
        test["events"].append({
            "t": round(t, 3), "cycle": int(test["cycles_total"]),
            "leg": (test["latest"] or {}).get("leg"),
            "kind": kind, "subject": subject, "detail": detail,
            "severity": severity,
        })
        self._dirty = True

    # ----- calibration checkpoints ---------------------------------------------

    def _checkpoint(self, test: dict, t: float) -> None:
        """Motor travel per joint from the calibration run just archived —
        travel between the hardstops grows as a tendon slackens."""
        runs = calibration_log.read_runs(self._calibration_path, limit=1)
        if not runs:
            return
        record = runs[0]
        travel: dict[str, float] = {}
        ratio: dict[str, float] = {}
        limits: dict[str, dict[str, float]] = {}
        for event in record.get("events") or []:
            kind = event.get("event")
            joint = event.get("joint")
            if kind == "travel_checked" and joint:
                value = _finite(event.get("travel_deg"))
                if value is not None:
                    travel[joint] = round(value, 3)
            elif kind == "joint_calibrated" and joint:
                value = _finite(event.get("ratio"))
                if value is not None:
                    ratio[joint] = value
            elif kind == "limit_recorded" and joint and event.get("bound"):
                value = _finite(event.get("limit"))
                if value is not None:
                    limits.setdefault(joint, {})[event["bound"]] = value
            elif kind == "calibration_done":
                for j, value in (event.get("motor_travel_deg") or {}).items():
                    value = _finite(value)
                    if value is not None:
                        travel.setdefault(j, round(value, 3))
        # A run that recorded both hardstops but no travel check still
        # measured the travel: the motor-shaft distance between them.
        for joint, bounds in limits.items():
            if joint not in travel and "lower" in bounds and "upper" in bounds:
                travel[joint] = round(
                    abs(bounds["upper"] - bounds["lower"]) * 180.0 / math.pi, 3)
        if len(test["checkpoints"]) >= MAX_CHECKPOINTS:
            test["checkpoints_dropped"] += 1
            return
        test["checkpoints"].append({
            "t": round(t, 3), "cycle": int(test["cycles_total"]),
            "started_at": record.get("started_at"),
            "finished_at": record.get("finished_at"),
            "completed": bool(record.get("completed")),
            "travel_deg": travel,
            "ratio": ratio,
            "problems": [p.get("headline") for p in record.get("problems") or []
                         if p.get("headline")],
        })
        self._dirty = True

    # ----- reads ---------------------------------------------------------------

    @staticmethod
    def _elapsed(test: dict) -> float:
        return max(time.time() - float(test["t0"]), 0.0)

    def _summary(self, test: dict) -> dict:
        active = self._data.get("active_id") == test["id"]
        return {
            "id": test["id"], "label": test["label"],
            "started_at": test["started_at"], "ended_at": test["ended_at"],
            "t0": test["t0"], "active": active,
            "elapsed_s": round(self._elapsed(test) if active else
                               _ended_elapsed(test), 1),
            "samples": test["samples"], "cycles_total": test["cycles_total"],
            "events": len(test["events"]),
            "checkpoints": len(test["checkpoints"]),
        }

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "path": self._path,
                "active_id": self._data.get("active_id"),
                "tests": [self._summary(t) for t in self._data["tests"]],
            }

    def test(self, test_id: str) -> dict | None:
        """Full record for the page: columnar buckets plus events,
        checkpoints, runs and the latest sample."""
        with self._lock:
            test = self._find(test_id)
            if test is None:
                return None
            out = self._summary(test)
            out.update({
                "joints": list(test["joints"]), "motors": list(test["motors"]),
                "motor_joint": dict(test["motor_joint"]),
                "fingers": list(test["fingers"]),
                "bucket_s": test["bucket_s"],
                "buckets": _columnar(test),
                "runs": json.loads(json.dumps(test["runs"])),
                "runs_dropped": test["runs_dropped"],
                "events": list(test["events"]),
                "events_dropped": test["events_dropped"],
                "checkpoints": json.loads(json.dumps(test["checkpoints"])),
                "checkpoints_dropped": test["checkpoints_dropped"],
                "latest": json.loads(json.dumps(test["latest"])),
                "samples_url": f"/api/endurance/tests/{test['id']}/samples.csv",
            })
            return out


def _ended_elapsed(test: dict) -> float:
    try:
        ended = datetime.fromisoformat(test["ended_at"]).timestamp()
        return max(ended - float(test["t0"]), 0.0)
    except (TypeError, ValueError):
        latest = test.get("latest") or {}
        return float(latest.get("t") or 0.0)


def _columnar(test: dict) -> dict:
    buckets = test["buckets"]
    out = {
        "t0": [b["t0"] for b in buckets],
        "t1": [b["t1"] for b in buckets],
        "n": [b["n"] for b in buckets],
        "cycle0": [b["c0"] for b in buckets],
        "cycle1": [b["c1"] for b in buckets],
        "angle_min": {}, "angle_max": {},
        "current_mean": {}, "current_max": {},
        "force_mean": {}, "force_max": {},
    }
    for joint in test["joints"]:
        cells = [b["angle"].get(joint) for b in buckets]
        out["angle_min"][joint] = [None if c is None else c[0] for c in cells]
        out["angle_max"][joint] = [None if c is None else c[1] for c in cells]
    for motor in test["motors"]:
        cells = [b["current"].get(str(motor)) for b in buckets]
        out["current_mean"][str(motor)] = [
            None if c is None else round(c[0], 1) for c in cells]
        out["current_max"][str(motor)] = [
            None if c is None else round(c[1], 1) for c in cells]
    for finger in test["fingers"]:
        cells = [b["force"].get(finger) for b in buckets]
        out["force_mean"][finger] = [
            None if c is None else round(c[0], 2) for c in cells]
        out["force_max"][finger] = [
            None if c is None else round(c[1], 2) for c in cells]
    return out


def _describe_params(params: dict | None) -> str:
    if not params:
        return ""
    keep = ("name", "speed", "loop", "cycles", "joints", "interp_steps",
            "manual", "force_wrist")
    parts = []
    for key in keep:
        if key in params and params[key] not in (None, False, ""):
            value = params[key]
            if isinstance(value, list):
                value = ",".join(str(v) for v in value)
            parts.append(f"{key}={value}")
    return " ".join(parts)
