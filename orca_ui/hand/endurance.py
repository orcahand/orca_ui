"""Endurance record: what a looping replay did, cycle by cycle, kept on disk.

A looping replay is an endurance run. Every completed cycle appends one CSV row
(peak fingertip force and tactile health per finger, bus errors and latched
motors so far) and rewrites the run's JSON summary, both synced to disk, so a
crash or power cut keeps every cycle up to the last one and a restarted console
still lists the run with its count. Files live in the hand's folder, under
``endurance/``: ``<run id>.csv`` and ``<run id>.json``.

The motion never waits on the disk: the operation thread only hands each
cycle's rows to a writer thread. Nothing here touches the bus: forces arrive
from the telemetry fast tick (``feed_forces``), health and faults are the
payloads telemetry already published.

A fingertip the board stops reporting (gone from the force stream) is a drop
until it comes back; a stream with no new frame for ``STALE_S`` is a drop of
the whole ``board``. Each drop is a row of ``<run id>-drops.csv`` (start, end,
cycle, where in the cycle), and the summary keeps per-tip statistics. Only tips
seen in the stream count, so a hand without a sensor on a finger never drops it.

A run may continue earlier ones (``carried_cycles``, some of them possibly
estimated): its count starts there, and the CSV's first row says those cycles
carry no per-cycle data.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import math
import os
import queue
import re
import threading
from collections import deque
import time
from pathlib import Path
from typing import Callable

from orca_core.constants import FINGER_NAMES

from orca_ui.home import ui_home
from orca_ui.streaming import topics as T

logger = logging.getLogger(__name__)

RUN_ID_RE = re.compile(r"^\d{8}-\d{6}-[A-Za-z0-9_.-]+$")
RECENT_RUNS = 10
HEADER = (
    ["cycle", "time", "elapsed_s"]
    + [f"{f}_peak_N" for f in FINGER_NAMES]
    + [f"{f}_tactile" for f in FINGER_NAMES]
    + ["tactile_hz", "bus_errors", "latched_motors", "note"]
)
DROP_HEADER = ["tip", "start", "end", "duration_s", "cycle", "s_into_cycle",
               "cycle_fraction", "joints_at_start", "note"]
BOARD = "board"
STALE_S = 0.5
STATS_WINDOW = 500  # drops the per-tip statistics look back over


def endurance_folder(settings, config) -> Path:
    """The hand's ``endurance/`` folder. The mock's hand folder is temporary,
    so its runs go to the console's own folder to outlive a restart."""
    hand_dir = getattr(config, "hand_dir", "")
    if getattr(settings, "mock", False) or not hand_dir:
        return ui_home() / "endurance"
    return Path(hand_dir) / "endurance"


def _magnitude(vector) -> float | None:
    try:
        value = math.sqrt(sum(float(v) ** 2 for v in vector))
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _write_synced(path: Path, text: str, append: bool = False) -> None:
    """Append to ``path``, or replace it whole through a temporary file."""
    target = path if append else path.with_suffix(".tmp")
    with open(target, "a" if append else "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    if not append:
        os.replace(target, path)


def _tip_stats(events, count: int, open_since: float | None,
               open_mono: float | None) -> dict:
    """Per-tip summary. ``events`` are the last ``STATS_WINDOW`` closed drops,
    ``(start, start_mono, duration_s, cycle_fraction)``; ``count`` is all of them
    plus the open one."""
    durations = sorted(e[2] for e in events)
    starts = [e[1] for e in events] + ([open_mono] if open_mono is not None else [])
    gaps = [b - a for a, b in zip(starts, starts[1:])]
    mean = sum(gaps) / len(gaps) if gaps else None
    cv = None
    if len(gaps) >= 2 and mean:
        cv = round(math.sqrt(sum((g - mean) ** 2 for g in gaps) / (len(gaps) - 1)) / mean, 2)
    phases = [e[3] for e in events if e[3] is not None]
    peak = p = None
    if len(phases) >= 5:
        # Rayleigh test: do drops gather at one point of the cycle?
        c = sum(math.cos(2 * math.pi * x) for x in phases)
        s = sum(math.sin(2 * math.pi * x) for x in phases)
        r = math.hypot(c, s) / len(phases)
        p = round(math.exp(-len(phases) * r * r), 4)
        peak = round((math.atan2(s, c) / (2 * math.pi)) % 1, 2)
    return {
        "count": count,
        "last_at": open_since or (events[-1][0] if events else None),
        "open_since": open_since,
        "min_s": durations[0] if durations else None,
        "median_s": durations[len(durations) // 2] if durations else None,
        "max_s": durations[-1] if durations else None,
        "interval_mean_s": None if mean is None else round(mean, 1),
        "interval_cv": cv,
        "phase_peak": peak,
        "phase_p": p,
    }


def _csv_row(values: list) -> str:
    line = io.StringIO()
    csv.writer(line, lineterminator="\n").writerow(
        ["" if v is None else v for v in values]
    )
    return line.getvalue()


def _stamp(t: float, ms: bool = False) -> str:
    text = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t))
    return text + f".{int(t % 1 * 1000):03d}" if ms else text


class EnduranceRecorder:
    """Thread-safe: started and advanced from the operation thread, fed from
    the telemetry thread, read from request threads, written by its own."""

    def __init__(
        self,
        folder: Callable[[], Path],
        latest: Callable[[str], tuple | None],
        publish: Callable[[str, dict], None],
    ):
        self._folder = folder
        self._latest = latest
        self._publish = publish
        self._lock = threading.Lock()
        self._run: dict | None = None
        # The run that just ended, until its final summary is on disk.
        self._ended: dict | None = None
        # The newest summaries on disk, re-read on start, on an end and on a REST read.
        self._recent: list[dict] = []
        self._dir: Path | None = None
        self._peaks: dict[str, float] = {}
        self._bus_last = 0
        # Tips this hand streams, so a missing one is a drop, not a missing sensor.
        self._tips: set[str] = set()
        self._seq = self._seq_at = None
        self._period: float | None = None
        self._tips_dir: Path | None = None
        self._open: dict[str, dict] = {}
        self._events: dict[str, deque] = {}
        self._closed: dict[str, int] = {}
        self._writes: queue.Queue = queue.Queue()
        threading.Thread(
            target=self._write_loop, name="endurance-writer", daemon=True
        ).start()

    # ----- feeding --------------------------------------------------------------

    def feed_forces(self, forces: dict | None, seq: int | None = None) -> None:
        """One telemetry tick: ``forces`` per streamed tip (``None``: no reading
        at all), ``seq`` the frame number, unchanged while no new frame came."""
        wall, mono = time.time(), time.monotonic()
        with self._lock:
            if seq is not None and seq != self._seq:
                self._seq, self._seq_at = seq, mono
            stale = (
                self._seq_at is not None
                and (forces is None or seq is not None)
                and mono - self._seq_at > STALE_S
            )
            if forces and not stale:
                self._tips.update(f for f in forces if f in FINGER_NAMES)
            if self._run is None or (forces is None and not stale):
                return
            changed = False
            if stale:
                # It went quiet at its last new frame, not when that was noticed.
                quiet = self._seq_at
                changed = self._drop_open(BOARD, wall - (mono - quiet), quiet)
            else:
                for finger, vector in forces.items():
                    value = _magnitude(vector)
                    if value is not None and value > self._peaks.get(finger, -1.0):
                        self._peaks[finger] = value
                board = self._open.get(BOARD)
                took_over = False
                for tip in self._tips:
                    if tip in forces:
                        changed |= self._drop_close(tip, mono)
                    elif board:
                        # The board stalls while it drops a tip: that is the tip's drop.
                        took_over |= self._drop_open(tip, board["start"], board["start_mono"])
                    else:
                        changed |= self._drop_open(tip, wall, mono)
                if board:
                    if took_over:
                        del self._open[BOARD]
                        self._set_tip(BOARD)
                    else:
                        self._drop_close(BOARD, mono)
                    changed = True
            if changed:
                self._publish_locked()

    def _drop_open(self, tip: str, start: float, start_mono: float) -> bool:
        if tip in self._open:
            return False
        run = self._run
        if start < run["started_at"]:
            start_mono += run["started_at"] - start
            start = run["started_at"]
        cycle, since = run["cycles"] + 1, run["last_cycle_at"] or run["started_at"]
        if start < since and self._period:
            cycle, since = cycle - 1, since - self._period
        into = max(0.0, start - since)
        angles = self._payload_of(T.JOINTS_TARGET).get("angles") or {}
        self._open[tip] = {
            "start": start,
            "start_mono": start_mono,
            "cycle": cycle,
            "s_into_cycle": round(into, 3),
            "cycle_fraction": round(into / self._period % 1, 3) if self._period else None,
            "joints": ";".join(
                f"{j}={float(a):.1f}" for j, a in sorted(angles.items())
                if tip == BOARD or j.startswith(f"{tip}_")
            ),
        }
        self._set_tip(tip)
        return True

    def _drop_close(self, tip: str, mono: float, note: str | None = None) -> bool:
        drop = self._open.pop(tip, None)
        if drop is None:
            return False
        duration = round(mono - drop["start_mono"], 3)
        self._events.setdefault(tip, deque(maxlen=STATS_WINDOW)).append(
            (drop["start"], drop["start_mono"], duration, drop["cycle_fraction"]))
        self._closed[tip] = self._closed.get(tip, 0) + 1
        self._set_tip(tip)
        row = [tip, _stamp(drop["start"], ms=True), _stamp(drop["start"] + duration, ms=True),
               duration, drop["cycle"], drop["s_into_cycle"], drop["cycle_fraction"],
               drop["joints"], note]
        self._writes.put(([(self._dir / f"{self._run['run_id']}-drops.csv",
                            _csv_row(row), True)], None))
        return True

    def _set_tip(self, tip: str) -> None:
        # Replaced, never changed in place: published snapshots share it.
        drop = self._open.get(tip)
        stats = _tip_stats(
            self._events.get(tip, ()),
            self._closed.get(tip, 0) + (1 if drop else 0),
            drop and drop["start"],
            drop and drop["start_mono"],
        )
        self._run["drops"] = {**self._run["drops"], tip: stats}

    def _payload_of(self, topic: str) -> dict:
        entry = self._latest(topic)
        return entry[2] if entry and isinstance(entry[2], dict) else {}

    def _bus_errors_total(self, faults: dict) -> int:
        # The bus total already counts every per-motor error once.
        return int((faults.get("bus") or {}).get("errors") or 0)

    # ----- run lifecycle ----------------------------------------------------------

    def start(
        self,
        motion: str,
        carried_cycles: int = 0,
        carried_estimated: int = 0,
        continues: str | None = None,
        carried_note: str | None = None,
        speed: float | None = None,
    ) -> None:
        """``carried_cycles`` (of which ``carried_estimated`` are an estimate)
        start the count; they ran before this run, mostly in ``continues``."""
        carried_estimated = min(carried_estimated, carried_cycles)
        now = time.time()
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", motion) or "replay"
        run_id = time.strftime("%Y%m%d-%H%M%S", time.localtime(now)) + "-" + safe
        run = {
            "run_id": run_id,
            "motion": motion,
            "speed": speed,
            "state": "running",
            "started_at": now,
            "last_cycle_at": None,
            "ended_at": None,
            "cycles": carried_cycles,
            "carried_cycles": carried_cycles,
            "carried_estimated": carried_estimated,
            "continues": continues,
            "carried_note": None,
            "fingers": {},
            "tactile_hz": None,
            "bus_errors": 0,
            "latched_motors": 0,
            "drops": {f: _tip_stats([], 0, None, None) for f in [*FINGER_NAMES, BOARD]},
            "tips": [],
        }
        text = ",".join(HEADER) + "\n"
        if carried_cycles:
            exact = carried_cycles - carried_estimated
            note = (
                f"cycles 1-{carried_cycles} carried over: {exact} exact from "
                f"{continues or 'an earlier run'}"
                + (f" + {carried_estimated} estimated from earlier runs" if carried_estimated else "")
                + (f" ({carried_note})" if carried_note else "")
                + "; no per-cycle data"
            )
            run["carried_note"] = note
            text += _csv_row(
                [carried_cycles, _stamp(now), 0.0] + [None] * (len(HEADER) - 4) + [note]
            )
        # The record never holds up the motion: if it cannot start, the
        # replay runs unrecorded.
        try:
            folder = self._folder()
            folder.mkdir(parents=True, exist_ok=True)
            taken = 1
            while any((folder / f"{run['run_id']}{end}").exists()
                      for end in (".json", ".csv", "-drops.csv")):
                taken += 1
                run["run_id"] = f"{run_id}-{taken}"
            run_id = run["run_id"]
            _write_synced(folder / f"{run_id}.csv", text)
            _write_synced(folder / f"{run_id}-drops.csv", ",".join(DROP_HEADER) + "\n")
            _write_synced(folder / f"{run_id}.json", json.dumps(run))
        except Exception:
            logger.exception("could not start the endurance record")
            return
        bus = self._bus_errors_total(self._payload_of(T.MOTORS_FAULTS))
        recent = self._read_recent()
        with self._lock:
            self._run, self._dir = run, folder
            self._peaks = {}
            self._bus_last = bus
            self._recent = recent
            self._period, self._open, self._events, self._closed = None, {}, {}, {}
            if self._tips_dir not in (None, folder):  # another hand
                self._tips = set()
            self._tips_dir = folder
            # A tip already out when the console started still counts.
            for earlier in recent:
                if earlier.get("tips"):
                    self._tips.update(earlier["tips"])
                    break
            self._publish_locked()

    def cycle_done(self, cycles: int) -> None:
        """``cycles`` completed in this run; returns without touching the disk."""
        health = self._payload_of(T.SENSORS_HEALTH).get("tactile") or {}
        faults = self._payload_of(T.MOTORS_FAULTS)
        now = time.time()
        with self._lock:
            run = self._run
            if run is None:
                return
            peaks, self._peaks = self._peaks, {}
            total = self._bus_errors_total(faults)
            # Counters restart with a new session; count what came after.
            run["bus_errors"] += (
                total - self._bus_last if total >= self._bus_last else total
            )
            self._bus_last = total
            run["latched_motors"] = sum(
                1
                for m in (faults.get("motors") or {}).values()
                if m.get("hw_error_flags")
            )
            hz = health.get("hz")
            run["tactile_hz"] = hz
            connected = health.get("fingers") or {}
            fingers = {}
            for finger in FINGER_NAMES:
                if finger not in connected:
                    state = None
                elif not connected[finger].get("connected"):
                    state = "disconnected"
                else:
                    state = "ok" if hz and finger in peaks else "no data"
                peak = peaks.get(finger)
                fingers[finger] = {
                    "peak_n": None if peak is None else round(peak, 3),
                    "health": state,
                }
            if run["last_cycle_at"]:
                self._period = now - run["last_cycle_at"]
            run.update(
                cycles=run["carried_cycles"] + cycles,
                last_cycle_at=now,
                fingers=fingers,
                tips=sorted(self._tips),
            )
            row = (
                [run["cycles"], _stamp(now), round(now - run["started_at"], 1)]
                + [fingers[f]["peak_n"] for f in FINGER_NAMES]
                + [fingers[f]["health"] for f in FINGER_NAMES]
                + [hz, run["bus_errors"], run["latched_motors"], None]
            )
            folder, run_id = self._dir, run["run_id"]
            summary = json.dumps(run)
        self._writes.put(
            (
                [
                    (folder / f"{run_id}.csv", _csv_row(row), True),
                    (folder / f"{run_id}.json", summary, False),
                ],
                None,
            )
        )

    def finish(self, state: str) -> None:
        with self._lock:
            run = self._run
            if run is None:
                return
            now, mono = time.time(), time.monotonic()
            for tip in list(self._open):
                self._drop_close(tip, mono, note="still out when the run ended")
            run.update(state=state, ended_at=now, tips=sorted(self._tips))
            self._run, self._ended = None, run
            path = self._dir / f"{run['run_id']}.json"
            summary = json.dumps(run)
        self._writes.put(([(path, summary, False)], run))

    def flush(self, timeout: float = 5.0) -> bool:
        """Wait until every queued write is on disk (shutdown, tests)."""
        done = threading.Event()
        self._writes.put(done)
        return done.wait(timeout)

    def _write_loop(self) -> None:
        """Jobs are ``(writes, ended_run)``; ``ended_run`` marks a run's final summary."""
        while True:
            job = self._writes.get()
            if isinstance(job, threading.Event):
                job.set()
                continue
            writes, ended = job
            try:
                for path, text, append in writes:
                    _write_synced(path, text, append)
                written = True
            except Exception:
                logger.exception("could not write the endurance record")
                written = False
            try:
                recent = self._read_recent() if ended is not None else None
                with self._lock:
                    # Until its summary is on disk, the ended run is shown from memory.
                    if written and ended is not None and self._ended is ended:
                        self._ended = None
                    if recent is not None:
                        self._recent = recent
                    self._publish_locked()
            except Exception:
                logger.exception("could not publish the endurance record")

    # ----- reads ------------------------------------------------------------------

    def csv_path(self, run_id: str) -> Path | None:
        if not RUN_ID_RE.match(run_id):
            return None
        path = self._folder() / f"{run_id}.csv"
        return path if path.is_file() else None

    def _read_recent(self) -> list[dict]:
        runs = []
        try:
            paths = sorted(self._folder().glob("*.json"), reverse=True)[:RECENT_RUNS]
        except Exception:
            paths = []
        for path in paths:
            try:
                runs.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
        return runs

    def state(self) -> dict:
        """``{current, runs}``: the run in progress, and the newest runs on disk."""
        recent = self._read_recent()
        with self._lock:
            self._recent = recent
            return self._state_locked()

    def _state_locked(self) -> dict:
        current = dict(self._run) if self._run else None
        live = {r["run_id"]: dict(r) for r in (self._run, self._ended) if r}
        runs = []
        for run in self._recent:
            run = live.pop(run.get("run_id"), None) or dict(run)
            if run.get("state") == "running" and not (
                current and run["run_id"] == current["run_id"]
            ):
                # Its console went away mid-run; the count is what it reached.
                run["state"] = "interrupted"
            runs.append(run)
        # Live runs newer than the last read of the folder go first.
        runs = sorted(live.values(), key=lambda r: r["started_at"], reverse=True) + runs
        # Server clock, so a browser on another machine can time drops without skew.
        return {"current": current, "runs": runs[:RECENT_RUNS], "server_time": time.time()}

    def _publish_locked(self) -> None:
        # Under the lock, so an older snapshot can never land after a newer one.
        self._publish(T.ENDURANCE, self._state_locked())
