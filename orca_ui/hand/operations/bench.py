"""Motor cycling for the testbench: each picked motor runs its own cycle,
back and forth between two shaft positions, the way a hand's motor runs in
service — and each on its own terms.

Every motor carries its own definition: endpoints A and B in *motor-shaft
degrees* (absolute positions the operator captured, so the range is whatever
the bench actually allows), a speed, a dwell at each end, a cycle count or
nonstop, ``glide`` or ``step``, and which end it starts from. The motors are
not synchronized: one can run slow with long holds while its neighbour runs
fast and nonstop. One scheduler ticks them all at the frame rate the hand's
loop writes at, and every tick's commands go out in a single bus write.

``glide`` streams interpolated positions, so the servo sees the kind of
command stream it sees in a hand; ``step`` sends the endpoint alone and the
motor runs the whole range at its own speed — the harshest treatment the
bench has.

Each leg ends with a settle: wait until the motor arrives (or stops
approaching), dwell, and record where it sat and how much current it needed
to sit there. The holding current at an extreme is the tension indicator — it
falls as a tendon slackens and collapses when one snaps — and the settled
span shrinking is a cable stretching. Those, the peak current, the shaft
odometer and the temperature are what the bench page shows live and what the
run returns when it stops. A motor that has finished its count parks at its
start end while the others go on; the run ends when every motor is done or
when it is stopped.

A run can log to CSV: every bus sample as one row per motor, and one row per
completed cycle with the settled reach and holding currents. Logging is a
switch, not a mode — it can be turned on and off while the run goes on
(``log on`` / ``log off`` as operation input), and every row written so far
stays in the files the run owns under the model's ``logs/`` folder — one
numbered part after another, each capped in size so no single file outgrows
a spreadsheet.

Safety is the console's: torque must be on (the ceiling is applied with it),
the e-stop drops torque and ends the run, and a motor that *is* calibrated
(a hand motor cycled from this page) must keep its range inside its
calibrated travel.
"""

from __future__ import annotations

import csv
import math
import os
import time
from collections import deque
from datetime import datetime

import numpy as np

from orca_ui.bench import assignments_of
from orca_ui.hand.operations.base import OpContext, Operation
from orca_ui.hand.states import ControlSource

STREAM_HZ = 50.0            # scheduler tick and glide command rate
SAMPLE_PERIOD_S = 0.2       # bus state reads while nothing is settling
SETTLE_SAMPLE_PERIOD_S = 0.05  # faster reads while a motor waits to arrive
PUBLISH_PERIOD_S = 0.2      # ceiling on operation.state updates
TEMP_PERIOD_S = 5.0
SETTLE_MIN_S = 0.1
SETTLE_MAX_S = 2.0
ARRIVE_TOL_DEG = 2.0
# Position change per sample below which a motor is treated as having stopped
# approaching (held off by the tendon rather than still travelling).
STALL_TOL_DEG = 0.3
STALL_SAMPLES = 3

DEFAULT_SPEED_DEG_S = 180.0
MIN_SPEED_DEG_S = 1.0
MAX_SPEED_DEG_S = 2000.0
DEFAULT_HOLD_S = 0.3
MAX_HOLD_S = 60.0
DEFAULT_CYCLES = 100
MAX_CYCLES = 100_000_000    # also the backstop for a nonstop motor
MIN_TRAVEL_DEG = 1.0
# Five shaft turns. A bench spool never needs more; a typo should not spin a
# motor for minutes.
MAX_SPAN_DEG = 1800.0
# A calibrated motor's endpoints may sit on its hardstops, not past them.
CALIBRATED_SLACK_DEG = 1.0
MODES = ("glide", "step")
RATE_WINDOW = 10            # cycles averaged for the rate / ETA

END_A = "from"
END_B = "to"
ENDS = (END_A, END_B)

MOVING, SETTLING, HOLDING, DONE = "moving", "settling", "holding", "done"

LOG_ON, LOG_OFF = "log on", "log off"
DEFAULT_LOG_PART_MB = 50
MIN_LOG_PART_MB, MAX_LOG_PART_MB = 0.001, 2000
LOG_COLUMNS = (
    "time", "t_s", "event", "motor", "id", "cycle", "state", "heading",
    "target_deg", "position_deg", "velocity_deg_s", "current_ma", "temp_c",
    "reached_from_deg", "reached_to_deg", "span_deg",
    "hold_current_from_ma", "hold_current_to_ma", "cycle_s",
)


def cycle_log_dir(settings) -> str:
    """Where a run's CSV goes: ``logs/`` beside the model's config."""
    return os.path.join(os.path.dirname(os.path.abspath(settings.config_path)),
                        "logs")


class _CsvLog:
    """One run's CSV log: numbered parts, appended to whenever logging is on,
    the next part started once the current one reaches ``max_bytes``."""

    def __init__(self, directory: str, started: datetime, max_bytes: int):
        os.makedirs(directory, exist_ok=True)
        self._dir = directory
        self._base = started.strftime("cycle-%Y%m%d-%H%M%S")
        self.max_bytes = max_bytes
        self.part = 0
        self.files: list[str] = []
        self.rows = 0
        self._file = None
        self._writer = None
        self._next_part()

    def _next_part(self) -> None:
        self.part += 1
        self.name = f"{self._base}-{self.part:03d}.csv"
        self.path = os.path.join(self._dir, self.name)

    @property
    def on(self) -> bool:
        return self._file is not None

    def open(self) -> None:
        if self._file is not None:
            return
        new = not os.path.exists(self.path) or os.path.getsize(self.path) == 0
        self._file = open(self.path, "a", newline="")
        self._writer = csv.writer(self._file)
        if new:
            self._writer.writerow(LOG_COLUMNS)
            self.files.append(self.name)
        self._file.flush()

    def _rotate_if_full(self) -> None:
        if self._file.tell() < self.max_bytes:
            return
        self.close()
        self._next_part()
        self.open()

    def close(self) -> None:
        if self._file is None:
            return
        self._file.close()
        self._file = self._writer = None

    def write(self, **fields) -> None:
        if self._writer is None:
            return
        row = [fields.get(c, "") for c in LOG_COLUMNS]
        self._writer.writerow(["" if v is None else
                               (round(v, 3) if isinstance(v, float) else v)
                               for v in row])
        self.rows += 1
        # Flush per row: a run that ends in a power cut keeps what it logged.
        self._file.flush()
        self._rotate_if_full()


def _deg(rad: float) -> float:
    return math.degrees(float(rad))


def _finite(value) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise ValueError
    if not math.isfinite(value):
        raise ValueError
    return value


class _MotorRun:
    """One motor's definition, its state machine and its statistics."""

    def __init__(self, spec: dict):
        self.id = int(spec["id"])
        self.ends = {END_A: float(spec["from_deg"]), END_B: float(spec["to_deg"])}
        self.speed = float(spec["speed_deg_s"])
        self.hold_s = float(spec["hold_s"])
        self.loop = bool(spec["loop"])
        self.cycles_target = int(spec["cycles"])
        self.mode = spec["mode"]
        self.start_end = spec["start_at"]
        self.other_end = END_B if self.start_end == END_A else END_A

        # Scheduler state.
        self.state = MOVING
        self.approaching = True          # first leg: to the start end, uncounted
        self.target_end = self.start_end
        self.cmd: float | None = None     # last commanded position (deg)
        self.pending_step = False         # step mode: endpoint not yet written
        self.settle_deadline = 0.0
        self.settle_prev: float | None = None
        self.still = 0
        self.hold_until = 0.0
        self.hold_sum = 0.0
        self.hold_n = 0
        self.last_pos: float | None = None
        self.last_cur: float | None = None

        # Statistics.
        self.completed = 0
        self.cycle_started: float | None = None
        self.cycle_times: deque[float] = deque(maxlen=RATE_WINDOW)
        self.last_cycle_s: float | None = None
        self.reached: dict[str, float | None] = {END_A: None, END_B: None}
        self.hold_current: dict[str, float | None] = {END_A: None, END_B: None}
        self.peak_current_ma = 0.0
        self.travel_deg = 0.0
        self.temp_c: float | None = None
        self.temp_max_c: float | None = None
        self.finished_at: float | None = None

    # ----- definition --------------------------------------------------------

    @property
    def span_deg(self) -> float:
        return abs(self.ends[END_B] - self.ends[END_A])

    @property
    def target(self) -> float:
        return self.ends[self.target_end]

    @property
    def done(self) -> bool:
        return self.state == DONE

    # ----- scheduler ---------------------------------------------------------

    def begin(self, position: float, now: float) -> None:
        self.cmd = position
        self.last_pos = position
        self._start_leg(now)

    def _start_leg(self, now: float) -> None:
        self.state = MOVING
        self.pending_step = self.mode == "step"
        if self.cmd is not None and abs(self.cmd - self.target) < 1e-9:
            self._enter_settling(now)

    def tick(self, now: float, dt: float) -> bool:
        """Advance the commanded position. Returns True when ``cmd`` changed
        and must be written this tick."""
        if self.state != MOVING or self.cmd is None:
            return False
        if self.mode == "step":
            self.cmd = self.target
            self.pending_step = False
            self._enter_settling(now)
            return True
        remaining = self.target - self.cmd
        step = self.speed * dt
        if abs(remaining) <= step:
            self.cmd = self.target
            self._enter_settling(now)
        else:
            self.cmd += math.copysign(step, remaining)
        return True

    def _enter_settling(self, now: float) -> None:
        self.state = SETTLING
        distance = abs(self.target - (self.last_pos if self.last_pos is not None
                                      else self.cmd or self.target))
        self.settle_deadline = now + max(
            SETTLE_MAX_S, distance / self.speed * 1.5 + SETTLE_MIN_S)
        self.settle_started = now
        self.settle_prev = None
        self.still = 0

    def observe(self, now: float, position: float, current: float) -> None:
        """Feed one bus sample; drives settling and holding."""
        self.last_pos = position
        self.last_cur = current
        self.peak_current_ma = max(self.peak_current_ma, abs(current))
        if self.state == SETTLING:
            if now - self.settle_started < SETTLE_MIN_S:
                return
            arrived = abs(position - self.target) <= ARRIVE_TOL_DEG
            if self.settle_prev is not None and \
                    abs(position - self.settle_prev) < STALL_TOL_DEG:
                self.still += 1
            else:
                self.still = 0
            self.settle_prev = position
            if arrived or self.still >= STALL_SAMPLES or now >= self.settle_deadline:
                self.state = HOLDING
                self.hold_until = now + self.hold_s
                self.hold_sum = 0.0
                self.hold_n = 0
        if self.state == HOLDING:
            self.hold_sum += abs(current)
            self.hold_n += 1

    def finish_hold_if_due(self, now: float) -> bool:
        """Close the hold once its dwell has elapsed; returns True when a
        cycle was completed on this call (for logging)."""
        if self.state != HOLDING or now < self.hold_until:
            return False
        hold = (self.hold_sum / self.hold_n) if self.hold_n else (
            abs(self.last_cur) if self.last_cur is not None else None)
        position = self.last_pos if self.last_pos is not None else self.target
        cycled = False
        if self.approaching:
            self.approaching = False
            self.cycle_started = now
        else:
            self.reached[self.target_end] = position
            self.hold_current[self.target_end] = hold
            self.travel_deg += self.span_deg
            if self.target_end == self.start_end:
                # Back where the cycle began: one full cycle.
                self.completed += 1
                cycled = True
                if self.cycle_started is not None:
                    self.last_cycle_s = now - self.cycle_started
                    self.cycle_times.append(self.last_cycle_s)
                self.cycle_started = now
                if self.completed >= self.cycles_target:
                    self.state = DONE
                    self.finished_at = now
                    return True
        self.target_end = self.other_end if self.target_end == self.start_end \
            else self.start_end
        self._start_leg(now)
        return cycled

    # ----- statistics --------------------------------------------------------

    def note_temp(self, temp: float) -> None:
        self.temp_c = temp
        self.temp_max_c = temp if self.temp_max_c is None else max(self.temp_max_c, temp)

    def progress(self) -> float | None:
        if self.loop:
            return None
        if self.done:
            return 1.0
        legs = 0.0 if self.approaching else (
            0.5 if self.target_end == self.start_end else 0.0)
        return min((self.completed + legs) / max(self.cycles_target, 1), 1.0)

    def report(self, now: float) -> dict:
        reached_a, reached_b = self.reached[END_A], self.reached[END_B]
        span = (abs(reached_b - reached_a)
                if reached_a is not None and reached_b is not None else None)
        mean_cycle = (sum(self.cycle_times) / len(self.cycle_times)
                      if self.cycle_times else None)
        remaining = None if self.loop else max(self.cycles_target - self.completed, 0)
        return {
            "id": self.id,
            "from_deg": self.ends[END_A],
            "to_deg": self.ends[END_B],
            "start_at": self.start_end,
            "speed_deg_s": self.speed,
            "hold_s": self.hold_s,
            "mode": self.mode,
            "loop": self.loop,
            "cycles": None if self.loop else self.cycles_target,
            "cycle": self.completed,
            "state": "approach" if self.approaching and not self.done else self.state,
            "heading": None if self.done else self.target_end,
            "progress": self.progress(),
            "cycle_s": (round(self.last_cycle_s, 2)
                        if self.last_cycle_s is not None else None),
            "cycles_per_min": round(60.0 / mean_cycle, 2) if mean_cycle else None,
            "eta_s": (round(remaining * mean_cycle)
                      if mean_cycle and remaining is not None and not self.done else None),
            "commanded_span_deg": self.span_deg,
            "reached_from_deg": reached_a,
            "reached_to_deg": reached_b,
            "span_deg": span,
            # Commanded travel minus achieved travel: grows as a cable stretches.
            "shortfall_deg": (self.span_deg - span) if span is not None else None,
            "hold_current_from_ma": self.hold_current[END_A],
            "hold_current_to_ma": self.hold_current[END_B],
            "peak_current_ma": self.peak_current_ma,
            "travel_deg": self.travel_deg,
            "temp_c": self.temp_c,
            "temp_max_c": self.temp_max_c,
            "finished_s": (round(now - self.finished_at, 1)
                           if self.finished_at is not None else None),
        }


class MotorCycleOperation(Operation):
    kind = "motor_cycle"
    control_source = ControlSource.OPERATION

    def __init__(self, params: dict):
        super().__init__(params)
        self._log_wanted = bool(params.get("log", False))

    # ----- validation ----------------------------------------------------------

    @classmethod
    def validate(cls, service, params: dict) -> dict:
        from orca_ui.hand.service import ServiceError

        session = service.session
        if session is None:
            raise ServiceError("hand not connected", status_code=503)
        if not session.caps.motors:
            raise ServiceError("no motor bus in this session", status_code=409)
        held = set(service.held_motors())
        if not held:
            raise ServiceError("torque is off — hold the motors first",
                               status_code=409)
        config = session.hand.config
        known = [int(m) for m in config.motor_ids]

        raw = params.get("motors")
        if not isinstance(raw, (list, tuple)) or not raw:
            raise ServiceError("pick at least one motor to cycle")
        limits = getattr(session.hand, "motor_limits_dict", None) or {}
        motors: list[dict] = []
        seen: set[int] = set()
        for entry in raw:
            if not isinstance(entry, dict):
                raise ServiceError("each motor needs {id, from_deg, to_deg, ...}")
            try:
                motor_id = int(entry.get("id"))
                lo = _finite(entry.get("from_deg"))
                hi = _finite(entry.get("to_deg"))
            except (TypeError, ValueError):
                raise ServiceError("each motor needs an integer id and finite "
                                   "from_deg / to_deg")
            if motor_id not in known:
                raise ServiceError(f"unknown motor {motor_id}")
            if motor_id in seen:
                raise ServiceError(f"motor {motor_id} is listed twice")
            seen.add(motor_id)
            if motor_id not in held:
                raise ServiceError(
                    f"motor id {motor_id} is released — hold it first",
                    status_code=409)
            span = abs(hi - lo)
            if span < MIN_TRAVEL_DEG:
                raise ServiceError(
                    f"motor {motor_id}: the range is {span:.1f}° — set A and B "
                    f"at least {MIN_TRAVEL_DEG:g}° apart")
            if span > MAX_SPAN_DEG:
                raise ServiceError(
                    f"motor {motor_id}: {span:.0f}° of travel is more than "
                    f"{MAX_SPAN_DEG:g}° ({MAX_SPAN_DEG / 360:g} turns)")
            bounds = limits.get(motor_id)
            if bounds and None not in bounds:
                lim_lo, lim_hi = sorted(_deg(b) for b in bounds)
                if (min(lo, hi) < lim_lo - CALIBRATED_SLACK_DEG
                        or max(lo, hi) > lim_hi + CALIBRATED_SLACK_DEG):
                    raise ServiceError(
                        f"motor {motor_id} is calibrated to "
                        f"{lim_lo:.1f}°..{lim_hi:.1f}° — keep its range inside "
                        "that travel")
            motors.append(cls._validate_cycle(motor_id, entry, lo, hi))
        # Config order, so the run reads the same way whatever order the
        # cards were ticked in.
        motors.sort(key=lambda m: known.index(m["id"]))
        try:
            part_mb = _finite(params.get("log_part_mb", DEFAULT_LOG_PART_MB))
        except ValueError:
            raise ServiceError("log_part_mb must be a number")
        if not MIN_LOG_PART_MB <= part_mb <= MAX_LOG_PART_MB:
            raise ServiceError(
                f"log_part_mb must be {MIN_LOG_PART_MB}..{MAX_LOG_PART_MB}")
        return {"motors": motors, "log": bool(params.get("log", False)),
                "log_part_mb": part_mb}

    @staticmethod
    def _validate_cycle(motor_id: int, entry: dict, lo: float, hi: float) -> dict:
        from orca_ui.hand.service import ServiceError

        who = f"motor {motor_id}: "
        try:
            speed = _finite(entry.get("speed_deg_s", DEFAULT_SPEED_DEG_S))
        except ValueError:
            raise ServiceError(who + "speed_deg_s must be a number")
        if not MIN_SPEED_DEG_S <= speed <= MAX_SPEED_DEG_S:
            raise ServiceError(
                who + f"speed_deg_s must be {MIN_SPEED_DEG_S:g}..{MAX_SPEED_DEG_S:g}")
        try:
            hold_s = _finite(entry.get("hold_s", DEFAULT_HOLD_S))
        except ValueError:
            raise ServiceError(who + "hold_s must be a number")
        if not 0.0 <= hold_s <= MAX_HOLD_S:
            raise ServiceError(who + f"hold_s must be 0..{MAX_HOLD_S:g}")
        loop = bool(entry.get("loop", False))
        try:
            cycles = int(entry.get("cycles", DEFAULT_CYCLES))
        except (TypeError, ValueError):
            raise ServiceError(who + "cycles must be an integer")
        if not loop and not 1 <= cycles <= MAX_CYCLES:
            raise ServiceError(who + f"cycles must be between 1 and {MAX_CYCLES}")
        mode = str(entry.get("mode", "glide"))
        if mode not in MODES:
            raise ServiceError(who + f"mode must be one of {MODES}")
        start_at = str(entry.get("start_at", END_A))
        if start_at not in ENDS:
            raise ServiceError(who + f"start_at must be one of {ENDS}")
        return {
            "id": motor_id,
            "from_deg": lo,
            "to_deg": hi,
            "speed_deg_s": speed,
            "hold_s": hold_s,
            "cycles": MAX_CYCLES if loop else cycles,
            "loop": loop,
            "mode": mode,
            "start_at": start_at,
        }

    # ----- run -----------------------------------------------------------------

    def run(self, ctx: OpContext) -> dict:
        from orca_ui.hand.service import ServiceError

        service = ctx.service
        session = service.session
        if session is None:
            raise ServiceError("hand not connected", status_code=503)
        self._hand = session.hand
        self._index = {int(m): i for i, m in enumerate(self._hand.config.motor_ids)}
        self._runs = [_MotorRun(spec) for spec in self.params["motors"]]
        self._ids = [r.id for r in self._runs]
        self._t0 = time.monotonic()
        self._live: dict = {"t": time.time(), "positions": {}, "currents": {},
                            "velocities": {}, "targets": {}}
        self._last_publish = 0.0
        self._last_sample = 0.0
        self._last_temp = float("-inf")
        client = getattr(self._hand, "motor_client", None)
        self._max_temp_c = getattr(client, "max_operating_temp_c", None)
        self._numbers = assignments_of(self._hand.config)
        self._csv = _CsvLog(
            cycle_log_dir(ctx.settings), datetime.now(),
            int(self.params.get("log_part_mb", DEFAULT_LOG_PART_MB) * 1_000_000))

        self._log_plan(ctx)
        service.set_direct_motor_mode(True, from_operation=True)
        try:
            now = time.monotonic()
            positions = self._hand.get_motor_pos(as_dict=True)
            for run in self._runs:
                run.begin(_deg(positions[run.id]), now)
            ctx.set_phase("cycling", detail=self._detail(), progress=self._progress())
            self._publish(ctx, force=True)
            self._loop(ctx)
        finally:
            service.set_direct_motor_mode(False, from_operation=True)
            self._csv.close()
            # A stopped run has no result: the final row count lives in extra.
            self._publish(ctx, force=True)

        now = time.monotonic()
        report = [r.report(now) for r in self._runs]
        self._log_report(ctx, report)
        if self._csv.rows:
            ctx.log(f"  log: {self._csv.rows} rows in {len(self._csv.files)} "
                    f"file(s) under {os.path.dirname(self._csv.path)}")
        return {
            "elapsed_s": now - self._t0,
            "cycles": {str(r.id): r.completed for r in self._runs},
            "motors": report,
            "log_file": self._csv.files[-1] if self._csv.files else None,
            "log_files": list(self._csv.files),
            "log_rows": self._csv.rows,
        }

    def handle_input(self, value: str) -> bool:
        """The log switch, flipped from any thread; the run thread acts on it."""
        if value not in (LOG_ON, LOG_OFF):
            return False
        self._log_wanted = value == LOG_ON
        return True

    def _sync_log(self, ctx: OpContext) -> None:
        if self._log_wanted == self._csv.on:
            return
        if self._log_wanted:
            self._csv.open()
            ctx.log(f"logging to {self._csv.name}")
        else:
            self._csv.close()
            ctx.log(f"logging off after {self._csv.rows} rows")
        self._publish(ctx, force=True)

    def _loop(self, ctx: OpContext) -> None:
        dt = 1.0 / STREAM_HZ
        next_t = time.monotonic()
        while not all(r.done for r in self._runs):
            ctx.check_stop()
            ctx.pause_point()
            now = time.monotonic()
            self._sync_log(ctx)
            period = (SETTLE_SAMPLE_PERIOD_S
                      if any(r.state == SETTLING for r in self._runs)
                      else SAMPLE_PERIOD_S)
            if now - self._last_sample >= period:
                self._sample(ctx, now)
            cycled = [r for r in self._runs if r.finish_hold_if_due(now)]
            for run in cycled:
                self._log_cycle(run, now)
                if run.done:
                    ctx.log(f"motor {run.id} done: {run.completed} cycle(s)")
                elif run.completed % 50 == 0:
                    ctx.log(self._progress_line(run, now))
            changed = [r.tick(now, dt) for r in self._runs]
            if any(changed):
                self._write()
            if cycled:
                ctx.set_detail(self._detail())
                ctx.set_progress(self._progress()) if self._progress() is not None else None
                self._publish(ctx, force=True)
            else:
                self._publish(ctx)
            next_t += dt
            delay = next_t - time.monotonic()
            if delay > 0:
                ctx.sleep(delay)
            else:
                next_t = time.monotonic()

    # ----- bus -------------------------------------------------------------------

    def _write(self) -> None:
        # The hardware client divides positions by its scale — array, not list.
        self._hand.write_motor_pos(
            self._ids,
            np.asarray([math.radians(r.cmd) for r in self._runs], dtype=float))
        self._live["targets"] = {str(r.id): round(r.cmd, 2) for r in self._runs}

    def _sample(self, ctx: OpContext, now: float) -> None:
        """One bus transaction: positions, velocities and currents."""
        self._last_sample = now
        state = self._hand.get_motor_state()
        positions, currents, velocities = {}, {}, {}
        for run in self._runs:
            i = self._index[run.id]
            pos, cur, vel = _deg(state.position[i]), float(state.current[i]), \
                _deg(state.velocity[i])
            run.observe(now, pos, cur)
            positions[str(run.id)] = round(pos, 2)
            currents[str(run.id)] = round(cur, 1)
            velocities[str(run.id)] = round(vel, 1)
            if self._csv.on:
                self._csv.write(**self._log_fields(run, now), event="sample",
                                target_deg=run.cmd, position_deg=pos,
                                velocity_deg_s=vel, current_ma=cur)
        self._live = {"t": time.time(), "positions": positions,
                      "currents": currents, "velocities": velocities,
                      "targets": self._live.get("targets", {})}
        if now - self._last_temp >= TEMP_PERIOD_S:
            self._last_temp = now
            try:
                temps = self._hand.get_motor_temp(as_dict=True)
                for run in self._runs:
                    run.note_temp(float(temps[run.id]))
            except Exception:
                pass

    # ----- snapshot ----------------------------------------------------------------

    def _progress(self) -> float | None:
        parts = [r.progress() for r in self._runs]
        if any(p is None for p in parts):
            return None
        return sum(parts) / len(parts)

    def _detail(self) -> str:
        done = sum(1 for r in self._runs if r.done)
        bits = []
        for r in self._runs:
            if r.done:
                bits.append(f"m{r.id} done")
            else:
                total = "" if r.loop else f"/{r.cycles_target}"
                bits.append(f"m{r.id} {r.completed}{total}")
        return (f"{done}/{len(self._runs)} finished · " if done else "") + " · ".join(bits)

    def _publish(self, ctx: OpContext, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_publish < PUBLISH_PERIOD_S:
            return
        self._last_publish = now
        ctx.set_extra({
            "elapsed_s": round(now - self._t0, 1),
            "progress": self._progress(),
            "finished": sum(1 for r in self._runs if r.done),
            "total": len(self._runs),
            "max_temp_c": self._max_temp_c,
            "live": dict(self._live),
            "motors": [r.report(now) for r in self._runs],
            "log": {"on": self._csv.on, "file": self._csv.name,
                    "files": list(self._csv.files), "rows": self._csv.rows},
        })

    # ----- csv ---------------------------------------------------------------------

    def _log_fields(self, run: _MotorRun, now: float) -> dict:
        return {
            "time": datetime.now().isoformat(timespec="milliseconds"),
            "t_s": now - self._t0,
            "motor": self._numbers.get(run.id),
            "id": run.id,
            "cycle": run.completed,
            "state": "approach" if run.approaching and not run.done else run.state,
            "heading": None if run.done else run.target_end,
            "temp_c": run.temp_c,
        }

    def _log_cycle(self, run: _MotorRun, now: float) -> None:
        if not self._csv.on:
            return
        report = run.report(now)
        self._csv.write(**self._log_fields(run, now), event="cycle",
                        target_deg=run.cmd, position_deg=run.last_pos,
                        current_ma=run.last_cur,
                        reached_from_deg=report["reached_from_deg"],
                        reached_to_deg=report["reached_to_deg"],
                        span_deg=report["span_deg"],
                        hold_current_from_ma=report["hold_current_from_ma"],
                        hold_current_to_ma=report["hold_current_to_ma"],
                        cycle_s=report["cycle_s"])

    # ----- logging ---------------------------------------------------------------

    def _log_plan(self, ctx: OpContext) -> None:
        ctx.log(f"motor cycle: {len(self._runs)} motor(s), each on its own cycle"
                + (" — logging to CSV" if self._log_wanted else ""))
        for r in self._runs:
            count = "nonstop" if r.loop else f"{r.cycles_target} cycle(s)"
            ctx.log(f"  motor {r.id}: {r.ends[END_A]:.1f}° ↔ {r.ends[END_B]:.1f}° "
                    f"({r.span_deg:.1f}°), {count} at {r.speed:g}°/s, hold "
                    f"{r.hold_s:g} s, {r.mode}, from {'A' if r.start_end == END_A else 'B'}")

    @staticmethod
    def _progress_line(run: _MotorRun, now: float) -> str:
        report = run.report(now)
        line = f"motor {run.id}: {run.completed} cycles"
        if report["span_deg"] is not None:
            line += (f", span {report['span_deg']:.1f}° "
                     f"({report['shortfall_deg']:+.1f}°)")
        hold = report["hold_current_to_ma"]
        if hold is not None:
            line += f", hold {hold:.0f} mA"
        return line

    @staticmethod
    def _log_report(ctx: OpContext, report: list[dict]) -> None:
        for row in report:
            if row["span_deg"] is None:
                ctx.log(f"  motor {row['id']}: {row['cycle']} cycle(s) — travel "
                        "not measured")
                continue
            ctx.log(
                f"  motor {row['id']}: {row['cycle']} cycle(s), reached "
                f"{row['reached_from_deg']:.1f}° ↔ {row['reached_to_deg']:.1f}° = "
                f"{row['span_deg']:.1f}° of {row['commanded_span_deg']:.1f}° "
                f"({row['shortfall_deg']:+.1f}°), peak {row['peak_current_ma']:.0f} mA, "
                f"{row['travel_deg'] / 360:.1f} turns"
                + (f", {row['temp_max_c']:.0f} °C max"
                   if row["temp_max_c"] is not None else ""))
