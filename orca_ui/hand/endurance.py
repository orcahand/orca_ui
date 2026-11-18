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


def _csv_row(values: list) -> str:
    line = io.StringIO()
    csv.writer(line, lineterminator="\n").writerow(
        ["" if v is None else v for v in values]
    )
    return line.getvalue()


def _stamp(t: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t))


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
        self._writes: queue.Queue = queue.Queue()
        threading.Thread(
            target=self._write_loop, name="endurance-writer", daemon=True
        ).start()

    # ----- feeding --------------------------------------------------------------

    def feed_forces(self, forces: dict) -> None:
        with self._lock:
            if self._run is None:
                return
            for finger, vector in forces.items():
                value = _magnitude(vector)
                if value is not None and value > self._peaks.get(finger, -1.0):
                    self._peaks[finger] = value

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
            while (folder / f"{run['run_id']}.json").exists():
                taken += 1
                run["run_id"] = f"{run_id}-{taken}"
            run_id = run["run_id"]
            _write_synced(folder / f"{run_id}.csv", text)
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
            run.update(
                cycles=run["carried_cycles"] + cycles,
                last_cycle_at=now,
                fingers=fingers,
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
            run.update(state=state, ended_at=time.time())
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
        return {"current": current, "runs": runs[:RECENT_RUNS]}

    def _publish_locked(self) -> None:
        # Under the lock, so an older snapshot can never land after a newer one.
        self._publish(T.ENDURANCE, self._state_locked())
