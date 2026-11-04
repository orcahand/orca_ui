"""Thermal test for the motor bench: locked motors, a current waveform, the
temperature over time.

The motors under test are coupled pairwise, shaft to shaft, so each is the
other's load and neither can turn. With the shaft blocked, a motor in current-based position mode
told to go somewhere far away pushes with exactly its Goal Current and stays
put, so Goal Current is the knob: this operation writes it as a waveform —
a sine around an offset, a square wave, or a constant — and flips the far
target's side whenever the signed current changes sign. Nothing is supposed
to move; a shaft that drifts more than the slip tolerance from where it
started means the coupling let go, and that motor is cut (Goal Current 0,
target where it is) while the rest go on. A motor reaching the temperature
ceiling is cut the same way, and its cooling is still recorded. A pair is
cut together: a cut motor has no torque, so its partner would only spin it.

The run has two phases: ``heating`` for the set duration (or until stopped)
and ``cooldown``, with the current off, for the set time after. Positions,
currents and temperatures are sampled throughout and go to CSV when logging
is on; a decimated temperature history stays in memory for the page.

On exit — finished, stopped or e-stopped — every motor gets Goal Current 0
and a target at its present position, then the console's current ceiling is
written back so the motors are simply held, as before the run.
"""

from __future__ import annotations

import logging
import math
import os
import threading
import time
from datetime import datetime

import numpy as np

from orca_ui.bench import assignments_of
from orca_ui.hand.operations.base import OpContext, Operation
from orca_ui.hand.operations.bench import _CsvLog, _finite, cycle_log_dir
from orca_ui.hand.states import ControlSource

logger = logging.getLogger(__name__)

WAVEFORMS = ("sine", "square", "constant")
LOADS = ("coupled", "free")
MIN_FREQ_HZ, MAX_FREQ_HZ = 0.01, 5.0
DEFAULT_FREQ_HZ = 1.0
MAX_DURATION_S = 24 * 3600.0
DEFAULT_DURATION_S = 600.0
DEFAULT_COOLDOWN_S = 300.0
MIN_TEMP_LIMIT_C = 30.0
DEFAULT_TEMP_LIMIT_C = 65.0
FALLBACK_MAX_TEMP_C = 70.0
MIN_SLIP_DEG, MAX_SLIP_DEG = 5.0, 720.0
DEFAULT_SLIP_DEG = 45.0
# Two shaft turns: far enough that a blocked motor never gets there, close
# enough that a motor whose fixture let go stops on its own soon after.
FAR_DEG = 720.0

MIN_TICK_HZ, MAX_TICK_HZ = 10.0, 50.0
TICKS_PER_PERIOD = 24.0
SAMPLE_PERIOD_S = 0.1
TEMP_PERIOD_S = 1.0
PUBLISH_PERIOD_S = 0.5
HISTORY_PERIOD_S = 2.0
HISTORY_MAX_POINTS = 5400     # 3 h at 2 s; decimated (period doubled) past it
RATE_WINDOW_S = 60.0
MIN_LOG_HZ, MAX_LOG_HZ, DEFAULT_LOG_HZ = 0.2, 10.0, 10.0
DEFAULT_LOG_PART_MB = 50
MIN_LOG_PART_MB, MAX_LOG_PART_MB = 0.001, 2000

DRIVING, COOLING, LIMIT, SLIPPED, DONE = "driving", "cooling", "limit", "slipped", "done"
HEATING, COOLDOWN = "heating", "cooldown"
LOG_ON, LOG_OFF = "log on", "log off"
LOG_COLUMNS = (
    "time", "t_s", "phase", "event", "motor", "id", "state", "goal_ma",
    "current_ma", "position_deg", "drift_deg", "temp_c",
)


def _deg(rad: float) -> float:
    return math.degrees(float(rad))


# ----- the page's setup, kept beside the config ------------------------------------
#
# Which motors are coupled, whether the partner is driven opposed, when a
# pair last passed its coupling check, and the waveform settings. The bench
# is a physical thing in one place; its pairing belongs to it, not to
# whichever browser last looked at it.

SETUP_FILE = "thermal_setup.yaml"
SETUP_KEYS = ("pairs", "settings", "motors")


def setup_path(settings) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(settings.config_path)),
                        SETUP_FILE)


def load_setup(settings) -> dict:
    import yaml

    path = setup_path(settings)
    data: dict = {}
    if os.path.isfile(path):
        try:
            with open(path) as f:
                data = yaml.safe_load(f) or {}
        except Exception:
            data = {}
    return {key: data.get(key) for key in SETUP_KEYS}


def save_setup(settings, body: dict) -> dict:
    """Store the page's setup. Validated for shape only — motors can come
    and go on the bus, and a pair naming a motor that left is dropped by the
    page when it loads, not refused here."""
    import yaml

    from orca_ui.hand.service import ServiceError

    clean: dict = {}
    pairs = body.get("pairs")
    if pairs is not None:
        if not isinstance(pairs, list):
            raise ServiceError("pairs must be a list")
        out = []
        seen: set[int] = set()
        for entry in pairs:
            if not isinstance(entry, dict):
                raise ServiceError("each pair is {a, b, opposed, checked?}")
            try:
                a, b = int(entry["a"]), int(entry["b"])
            except (KeyError, TypeError, ValueError):
                raise ServiceError("each pair needs integer motor ids a and b")
            if a == b or a in seen or b in seen:
                raise ServiceError(f"pair {a}/{b}: a motor can be in one pair only")
            seen.update((a, b))
            pair = {"a": a, "b": b, "opposed": bool(entry.get("opposed", True))}
            checked = entry.get("checked")
            if isinstance(checked, dict) and checked.get("at"):
                pair["checked"] = {"at": str(checked["at"]),
                                   "sense": 1 if int(checked.get("sense", 1)) >= 0 else -1}
            out.append(pair)
        clean["pairs"] = out
    for key in ("settings", "motors"):
        value = body.get(key)
        if value is not None:
            if not isinstance(value, dict):
                raise ServiceError(f"{key} must be an object")
            clean[key] = value
    current = load_setup(settings)
    current = {k: v for k, v in current.items() if v is not None}
    current.update(clean)
    with open(setup_path(settings), "w") as f:
        yaml.safe_dump(current, f, sort_keys=False)
    return {key: current.get(key) for key in SETUP_KEYS}


class _Motor:
    """One motor under test: its waveform sign, its cut state, its numbers."""

    def __init__(self, motor_id: int, invert: bool):
        self.id = motor_id
        self.invert = invert
        self.phase_s = 0.0               # the waveform is evaluated at t - phase_s
        self.partner: int | None = None
        self.via_partner = False
        self.state = DRIVING
        self.stopped_at: float | None = None
        self.side = 0                    # -1 / +1: which far target is written
        self.goal_ma = 0.0
        self.written_ma: float | None = None
        self.start_deg: float | None = None
        self.pos_deg: float | None = None
        self.current_ma: float | None = None
        self.drift_max_deg = 0.0
        self.peak_ma = 0.0
        self.sq_sum = 0.0
        self.sq_n = 0
        self.temp_start_c: float | None = None
        self.temp_c: float | None = None
        self.temp_max_c: float | None = None
        self.temp_at: float | None = None
        self.limit_at_s: float | None = None
        self.window_sum = 0.0            # |current| since the last history point
        self.window_n = 0

    @property
    def driving(self) -> bool:
        return self.state == DRIVING

    def cut(self, state: str, now: float) -> None:
        self.state = state
        self.stopped_at = now
        self.goal_ma = 0.0

    def observe(self, pos: float, cur: float) -> None:
        self.pos_deg = pos
        self.current_ma = cur
        if self.start_deg is not None:
            self.drift_max_deg = max(self.drift_max_deg, abs(pos - self.start_deg))
        if self.driving:
            self.peak_ma = max(self.peak_ma, abs(cur))
            self.sq_sum += cur * cur
            self.sq_n += 1
        self.window_sum += abs(cur)
        self.window_n += 1

    def take_window(self) -> float | None:
        mean = self.window_sum / self.window_n if self.window_n else None
        self.window_sum = 0.0
        self.window_n = 0
        return mean

    def note_temp(self, temp: float, now: float) -> None:
        if self.temp_start_c is None:
            self.temp_start_c = temp
        self.temp_c = temp
        self.temp_at = now
        self.temp_max_c = temp if self.temp_max_c is None else max(self.temp_max_c, temp)

    @property
    def drift_deg(self) -> float | None:
        if self.pos_deg is None or self.start_deg is None:
            return None
        return self.pos_deg - self.start_deg

    def report(self, now: float, t0: float, rate: float | None) -> dict:
        rms = math.sqrt(self.sq_sum / self.sq_n) if self.sq_n else None
        return {
            "id": self.id,
            "invert": self.invert,
            "partner": self.partner,
            "phase_s": round(self.phase_s, 3),
            "state": self.state,
            # Cut because the partner was, not on this motor's own reading.
            "via_partner": self.via_partner,
            "stopped_s": (round(self.stopped_at - t0, 1)
                          if self.stopped_at is not None else None),
            "goal_ma": round(self.goal_ma, 1),
            "current_ma": self.current_ma,
            "current_rms_ma": round(rms, 1) if rms is not None else None,
            "peak_current_ma": round(self.peak_ma, 1),
            "position_deg": self.pos_deg,
            "drift_deg": self.drift_deg,
            "drift_max_deg": round(self.drift_max_deg, 2),
            "temp_start_c": self.temp_start_c,
            "temp_c": self.temp_c,
            "temp_max_c": self.temp_max_c,
            "rise_c": (round(self.temp_c - self.temp_start_c, 1)
                       if self.temp_c is not None and self.temp_start_c is not None
                       else None),
            # °C per minute over the last RATE_WINDOW_S of history.
            "rate_c_per_min": rate,
            "limit_at_s": self.limit_at_s,
        }


class _History:
    """Decimated per-motor temperature and mean-current traces for the page.
    Past the point cap every other point is dropped and the period doubles,
    so a day-long run still fits in one payload."""

    def __init__(self, ids: list[int]):
        self._lock = threading.Lock()
        self.period_s = HISTORY_PERIOD_S
        self.t: list[float] = []
        self.temps: dict[str, list[float | None]] = {str(i): [] for i in ids}
        self.currents: dict[str, list[float | None]] = {str(i): [] for i in ids}
        self._next = 0.0

    def due(self, t_s: float) -> bool:
        return t_s >= self._next

    def add(self, t_s: float, motors: list[_Motor]) -> None:
        with self._lock:
            self.t.append(round(t_s, 1))
            for m in motors:
                self.temps[str(m.id)].append(m.temp_c)
                mean = m.take_window()
                self.currents[str(m.id)].append(
                    round(mean, 1) if mean is not None else None)
            if len(self.t) > HISTORY_MAX_POINTS:
                self.t = self.t[::2]
                for table in (self.temps, self.currents):
                    for key in table:
                        table[key] = table[key][::2]
                self.period_s *= 2
            self._next = t_s + self.period_s

    def rate(self, motor: _Motor) -> float | None:
        """Temperature slope over the last RATE_WINDOW_S, °C/min."""
        with self._lock:
            t = self.t
            series = self.temps.get(str(motor.id)) or []
            if len(t) < 2:
                return None
            end = len(t) - 1
            start = end
            while start > 0 and t[end] - t[start] < RATE_WINDOW_S:
                start -= 1
            if start == end or series[start] is None or series[end] is None:
                return None
            span = t[end] - t[start]
            if span < RATE_WINDOW_S / 2:
                return None
            return round((series[end] - series[start]) / span * 60.0, 2)

    def payload(self, run_id: str | None) -> dict:
        with self._lock:
            return {
                "run_id": run_id,
                "period_s": self.period_s,
                "t_s": list(self.t),
                "temps": {k: list(v) for k, v in self.temps.items()},
                "currents": {k: list(v) for k, v in self.currents.items()},
            }


class ThermalTestOperation(Operation):
    kind = "motor_thermal"
    control_source = ControlSource.OPERATION

    def __init__(self, params: dict):
        super().__init__(params)
        self._log_wanted = bool(params.get("log", False))
        self._history: _History | None = None
        self._run_id: str | None = None

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
        known = [int(m) for m in session.hand.config.motor_ids]

        raw = params.get("motors")
        if not isinstance(raw, (list, tuple)) or not raw:
            raise ServiceError("pick at least one motor")
        motors: list[dict] = []
        seen: set[int] = set()
        for entry in raw:
            if isinstance(entry, dict):
                motor_id, invert = entry.get("id"), bool(entry.get("invert", False))
            else:
                motor_id, invert = entry, False
            try:
                motor_id = int(motor_id)
            except (TypeError, ValueError):
                raise ServiceError("each motor needs an integer id")
            if motor_id not in known:
                raise ServiceError(f"unknown motor {motor_id}")
            if motor_id in seen:
                raise ServiceError(f"motor {motor_id} is listed twice")
            seen.add(motor_id)
            if motor_id not in held:
                raise ServiceError(
                    f"motor id {motor_id} is released — hold it first",
                    status_code=409)
            motors.append({"id": motor_id, "invert": invert})
        motors.sort(key=lambda m: known.index(m["id"]))
        in_test = {m["id"] for m in motors}
        pairs: list[list[int]] = []
        paired: set[int] = set()
        for entry in params.get("pairs") or []:
            try:
                a, b = (int(v) for v in entry)
            except (TypeError, ValueError):
                raise ServiceError("each pair needs two integer motor ids")
            if a == b or a not in known or b not in known:
                raise ServiceError(f"pair {a}/{b}: two different known motors")
            if a in paired or b in paired:
                raise ServiceError(f"pair {a}/{b}: a motor can be in one pair only")
            if (a in in_test) != (b in in_test):
                raise ServiceError(
                    f"pair {a}/{b}: a coupled pair is driven together — "
                    "put both in the test or neither")
            paired.update((a, b))
            if a in in_test:
                pairs.append([a, b])

        def number(key, default, lo, hi, what=None):
            try:
                value = _finite(params.get(key, default))
            except ValueError:
                raise ServiceError(f"{key} must be a number")
            if not lo <= value <= hi:
                raise ServiceError(f"{key} must be {lo:g}..{hi:g}" + (f" {what}" if what else ""))
            return value

        waveform = str(params.get("waveform", "sine"))
        if waveform not in WAVEFORMS:
            raise ServiceError(f"waveform must be one of {WAVEFORMS}")
        load = str(params.get("load", "coupled"))
        if load not in LOADS:
            raise ServiceError(f"load must be one of {LOADS}")
        if load == "free":
            # Free motors have no partner to be cut with; pairs are moot.
            pairs = []
            if "current" not in getattr(session.hand.motor_client, "supported_modes", {"current"}):
                raise ServiceError("this motor family has no current control mode",
                                   status_code=409)
        ceiling = service.control_state().get("max_current")
        if ceiling is None:
            raise ServiceError("motor current limits are not resolved yet",
                               status_code=409)
        ceiling = float(ceiling)
        amplitude = number("amplitude_ma", 0.0, 0.0, ceiling, "mA")
        offset = number("offset_ma", 0.0, -ceiling, ceiling, "mA")
        if waveform == "constant":
            amplitude = 0.0
        peak = abs(offset) + amplitude
        if peak <= 0:
            raise ServiceError("amplitude_ma and offset_ma are both zero — "
                               "nothing would be driven")
        if peak > ceiling:
            raise ServiceError(
                f"|offset| + amplitude is {peak:.0f} mA, above the {ceiling:.0f} mA "
                "current ceiling — lower them or raise max current first")
        client = getattr(session.hand, "motor_client", None)
        max_temp = float(getattr(client, "max_operating_temp_c", None)
                         or FALLBACK_MAX_TEMP_C)
        loop = bool(params.get("loop", False))
        return {
            "motors": motors,
            "pairs": pairs,
            "load": load,
            "waveform": waveform,
            "amplitude_ma": amplitude,
            "offset_ma": offset,
            "frequency_hz": number("frequency_hz", DEFAULT_FREQ_HZ,
                                   MIN_FREQ_HZ, MAX_FREQ_HZ, "Hz"),
            "duration_s": number("duration_s", DEFAULT_DURATION_S, 1.0,
                                 MAX_DURATION_S, "s"),
            "loop": loop,
            "cooldown_s": number("cooldown_s", DEFAULT_COOLDOWN_S, 0.0,
                                 MAX_DURATION_S, "s"),
            "temp_limit_c": number("temp_limit_c", min(DEFAULT_TEMP_LIMIT_C, max_temp),
                                   MIN_TEMP_LIMIT_C, max_temp, "°C"),
            "max_temp_c": max_temp,
            "slip_deg": number("slip_deg", DEFAULT_SLIP_DEG, MIN_SLIP_DEG,
                               MAX_SLIP_DEG, "°"),
            "stagger": bool(params.get("stagger", True)),
            "log": bool(params.get("log", False)),
            "log_hz": number("log_hz", DEFAULT_LOG_HZ, MIN_LOG_HZ, MAX_LOG_HZ, "Hz"),
            "log_part_mb": number("log_part_mb", DEFAULT_LOG_PART_MB,
                                  MIN_LOG_PART_MB, MAX_LOG_PART_MB),
        }

    # ----- waveform ------------------------------------------------------------

    def _assign_phases(self) -> None:
        """One phase slot per pair (and per lone motor), spread evenly over
        the period of |i(t)| — half a period for a waveform symmetric about
        zero, a whole one otherwise — so the slots' peaks never coincide."""
        p = self.params
        for m in self._motors:
            m.phase_s = 0.0
        if not p["stagger"] or p["waveform"] == "constant":
            return
        slots: list[list[_Motor]] = []
        seen: set[int] = set()
        for m in self._motors:
            if m.id in seen:
                continue
            group = [m]
            seen.add(m.id)
            if m.partner is not None and m.partner not in seen:
                group.append(self._by_id[m.partner])
                seen.add(m.partner)
            slots.append(group)
        if len(slots) < 2:
            return
        period = 1.0 / p["frequency_hz"]
        span = period / 2 if p["offset_ma"] == 0 else period
        for k, group in enumerate(slots):
            for m in group:
                m.phase_s = k * span / len(slots)

    def _signed_ma(self, t: float) -> float:
        p = self.params
        amp, offset, f = p["amplitude_ma"], p["offset_ma"], p["frequency_hz"]
        if p["waveform"] == "sine":
            return offset + amp * math.sin(2 * math.pi * f * t)
        if p["waveform"] == "square":
            return offset + (amp if (t * f) % 1.0 < 0.5 else -amp)
        return offset

    # ----- run -----------------------------------------------------------------

    def history(self) -> dict:
        if self._history is None:
            return {"run_id": self._run_id, "t_s": [], "temps": {}, "currents": {}}
        return self._history.payload(self._run_id)

    def run(self, ctx: OpContext) -> dict:
        from orca_ui.hand.service import ServiceError

        service = ctx.service
        session = service.session
        if session is None:
            raise ServiceError("hand not connected", status_code=503)
        self._run_id = ctx.run_id
        self._service = service
        self._hand = session.hand
        self._index = {int(m): i for i, m in enumerate(self._hand.config.motor_ids)}
        self._motors = [_Motor(m["id"], m["invert"]) for m in self.params["motors"]]
        self._ids = [m.id for m in self._motors]
        self._by_id = {m.id: m for m in self._motors}
        for a, b in self.params["pairs"]:
            self._by_id[a].partner, self._by_id[b].partner = b, a
        self._assign_phases()
        self._numbers = assignments_of(self._hand.config)
        self._history = _History(self._ids)
        self._free = self.params["load"] == "free"
        # Mock motors teleport to their target: there is no fixture to slip.
        # Free motors are meant to move.
        self._slip_check = not bool(getattr(ctx.settings, "mock", False)) and not self._free
        self._t0 = time.monotonic()
        self._phase = HEATING
        self._phase_t0 = self._t0
        self._last_publish = 0.0
        self._last_sample = 0.0
        self._last_temp = float("-inf")
        self._last_log = float("-inf")
        self._live: dict = {"t": time.time(), "goal_ma": {}, "currents": {},
                            "positions": {}, "temps": {}}
        self._csv = _CsvLog(
            cycle_log_dir(ctx.settings), datetime.now(),
            int(self.params["log_part_mb"] * 1_000_000),
            prefix="thermal", columns=LOG_COLUMNS)

        self._log_plan(ctx)
        service.set_direct_motor_mode(True, from_operation=True)
        try:
            if self._free:
                self._write_current(self._ids, [0.0] * len(self._ids))
                self._hand.set_control_mode("current", self._ids)
            positions = self._hand.get_motor_pos(as_dict=True)
            for m in self._motors:
                m.start_deg = m.pos_deg = _deg(positions[m.id])
            self._read_temps(ctx, time.monotonic(), force=True)
            ctx.set_phase(HEATING, detail=self._detail(), progress=self._progress())
            self._publish(ctx, force=True)
            self._loop(ctx)
        finally:
            self._release()
            service.set_direct_motor_mode(False, from_operation=True)
            self._csv.close()
            self._publish(ctx, force=True)

        now = time.monotonic()
        report = self._reports(now)
        self._log_report(ctx, report)
        if self._csv.rows:
            ctx.log(f"  log: {self._csv.rows} rows in {len(self._csv.files)} "
                    f"file(s) under {os.path.dirname(self._csv.path)}")
        return {
            "elapsed_s": round(now - self._t0, 1),
            "motors": report,
            "log_file": self._csv.files[-1] if self._csv.files else None,
            "log_files": list(self._csv.files),
            "log_rows": self._csv.rows,
        }

    def handle_input(self, value: str) -> bool:
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

    def _tick_hz(self) -> float:
        if self.params["waveform"] == "constant":
            return MIN_TICK_HZ
        return min(MAX_TICK_HZ, max(MIN_TICK_HZ,
                                    TICKS_PER_PERIOD * self.params["frequency_hz"]))

    def _loop(self, ctx: OpContext) -> None:
        dt = 1.0 / self._tick_hz()
        next_t = time.monotonic()
        while True:
            ctx.check_stop()
            ctx.pause_point()
            now = time.monotonic()
            self._sync_log(ctx)
            if self._phase == HEATING:
                self._drive(now)
            if now - self._last_sample >= SAMPLE_PERIOD_S:
                self._sample(ctx, now)
            if now - self._last_temp >= TEMP_PERIOD_S:
                self._read_temps(ctx, now)
            if self._advance_phase(ctx, now):
                return
            self._publish(ctx)
            next_t += dt
            delay = next_t - time.monotonic()
            if delay > 0:
                ctx.sleep(delay)
            else:
                next_t = time.monotonic()

    def _advance_phase(self, ctx: OpContext, now: float) -> bool:
        """Move heating → cooldown → done as time runs out or every motor is
        cut. Returns True when the run is complete."""
        p = self.params
        if self._phase == HEATING:
            elapsed = now - self._phase_t0
            timed_out = not p["loop"] and elapsed >= p["duration_s"]
            all_cut = not any(m.driving for m in self._motors)
            if not (timed_out or all_cut):
                return False
            for m in self._motors:
                if m.driving:
                    m.cut(COOLING, now)
            self._release()
            self._phase = COOLDOWN
            self._phase_t0 = now
            ctx.log("heating done" + (" — every motor is cut" if all_cut and not timed_out
                                      else "") + f"; cooling down for {p['cooldown_s']:g} s")
            ctx.set_phase(COOLDOWN, detail=self._detail(), progress=self._progress())
            self._publish(ctx, force=True)
            if p["cooldown_s"] > 0:
                return False
        elif now - self._phase_t0 < p["cooldown_s"]:
            return False
        for m in self._motors:
            if m.state == COOLING:
                m.state = DONE
        return True

    # ----- bus -------------------------------------------------------------------

    def _drive(self, now: float) -> None:
        t = now - self._t0
        value = self._signed_ma(t)
        flip_ids, flip_pos, cur_ids, cur_ma = [], [], [], []
        for m in self._motors:
            if not m.driving or m.start_deg is None:
                continue
            own = value if m.phase_s == 0.0 else self._signed_ma(t - m.phase_s)
            signed = -own if m.invert else own
            if self._free:
                # Current control: the sign goes to the servo itself.
                m.goal_ma = signed
            else:
                side = 1 if signed > 0 else (-1 if signed < 0 else m.side or 1)
                if side != m.side:
                    m.side = side
                    flip_ids.append(m.id)
                    flip_pos.append(math.radians(m.start_deg + side * FAR_DEG))
                m.goal_ma = abs(signed)
            if m.written_ma is None or abs(m.goal_ma - m.written_ma) >= 0.5:
                cur_ids.append(m.id)
                cur_ma.append(m.goal_ma)
        if flip_ids:
            self._hand.write_motor_pos(flip_ids, np.asarray(flip_pos, dtype=float))
        if cur_ids:
            self._write_current(cur_ids, cur_ma)
            for mid, ma in zip(cur_ids, cur_ma):
                self._by_id[mid].written_ma = ma
        self._live["goal_ma"] = {str(m.id): round(m.goal_ma, 1) for m in self._motors}

    def _write_current(self, ids: list[int], ma: list[float]) -> None:
        client = self._hand.motor_client
        with self._hand._motor_lock:
            client.write_desired_current(ids, np.asarray(ma, dtype=float))

    def _cut(self, ctx: OpContext, m: _Motor, state: str, now: float, why: str) -> None:
        """Stop driving a motor — and its partner, which has nothing to push
        against once this one goes slack."""
        if not m.driving:
            return
        m.cut(state, now)
        if state == LIMIT:
            m.limit_at_s = round(now - self._t0, 1)
        cut = [m]
        partner = self._by_id.get(m.partner) if m.partner is not None else None
        if partner is not None and partner.driving:
            partner.cut(state, now)
            partner.via_partner = True
            cut.append(partner)
        self._park(cut)
        ctx.log(f"motor {self._label(m)} cut: {why}"
                + (f" — partner {self._label(partner)} cut with it"
                   if len(cut) > 1 else ""))
        if self._csv.on:
            for motor in cut:
                self._csv.write(**self._fields(motor, now), event="cut")

    def _park(self, motors: list[_Motor]) -> None:
        """Goal Current 0 and a target at the present position: the motor
        stops pushing and stays where it is."""
        if not motors:
            return
        ids = [m.id for m in motors]
        try:
            self._write_current(ids, [0.0] * len(ids))
            if not self._free:
                positions = self._hand.get_motor_pos(as_dict=True)
                self._hand.write_motor_pos(
                    ids, np.asarray([positions[i] for i in ids], dtype=float))
        except Exception:
            pass
        for m in motors:
            m.goal_ma = 0.0
            m.written_ma = 0.0
            m.side = 0
        self._live["goal_ma"] = {str(m.id): round(m.goal_ma, 1) for m in self._motors}

    def _release(self) -> None:
        """Everything off and held where it is, then the console's ceiling
        back on every motor so they are simply held, as before the run. A
        free run first puts the servos back into their configured mode —
        and, after an e-stop, leaves them released rather than letting the
        mode switch re-arm them."""
        self._park(self._motors)
        if self._free:
            try:
                self._hand.set_control_mode(self._hand.config.control_mode, self._ids)
            except Exception:
                logger.exception("could not restore the control mode after a free run")
            if not self._service.supervisor.status().torque_enabled:
                try:
                    self._hand.disable_torque(self._ids)
                except Exception:
                    pass
                return
        try:
            self._service.reapply_current_ceiling()
        except Exception:
            pass

    def _sample(self, ctx: OpContext, now: float) -> None:
        self._last_sample = now
        try:
            state = self._hand.get_motor_state()
        except Exception:
            return
        positions, currents = {}, {}
        slipped: list[_Motor] = []
        for m in self._motors:
            i = self._index[m.id]
            pos, cur = _deg(state.position[i]), float(state.current[i])
            m.observe(pos, cur)
            positions[str(m.id)] = round(pos, 2)
            currents[str(m.id)] = round(cur, 1)
            if (self._slip_check and m.driving and m.start_deg is not None
                    and abs(pos - m.start_deg) > self.params["slip_deg"]):
                slipped.append(m)
        for m in slipped:
            self._cut(ctx, m, SLIPPED, now,
                      f"shaft moved {m.drift_deg:+.0f}° — the fixture let go")
        self._live.update({"t": time.time(), "positions": positions,
                           "currents": currents})
        if self._csv.on and now - self._last_log >= 1.0 / self.params["log_hz"]:
            self._last_log = now
            for m in self._motors:
                self._csv.write(**self._fields(m, now), event="sample")

    def _read_temps(self, ctx: OpContext, now: float, force: bool = False) -> None:
        self._last_temp = now
        try:
            temps = self._hand.get_motor_temp(as_dict=True)
        except Exception:
            return
        limit = self.params["temp_limit_c"]
        hot: list[_Motor] = []
        for m in self._motors:
            temp = float(temps[m.id])
            m.note_temp(temp, now)
            if m.driving and temp >= limit and not force:
                hot.append(m)
        for m in hot:
            self._cut(ctx, m, LIMIT, now, f"{m.temp_c:.0f} °C reached the {limit:g} °C limit")
        self._live["temps"] = {str(m.id): m.temp_c for m in self._motors}
        t_s = now - self._t0
        if self._history is not None and (force or self._history.due(t_s)):
            self._history.add(t_s, self._motors)

    # ----- snapshot ----------------------------------------------------------------

    def _progress(self) -> float | None:
        p = self.params
        now = time.monotonic()
        total = (0.0 if p["loop"] else p["duration_s"]) + p["cooldown_s"]
        if p["loop"] and self._phase == HEATING:
            return None
        if total <= 0:
            return 1.0
        done = (now - self._phase_t0) if self._phase == HEATING else \
            (0.0 if p["loop"] else p["duration_s"]) + (now - self._phase_t0)
        return min(max(done / total, 0.0), 1.0)

    def _detail(self) -> str:
        driving = sum(1 for m in self._motors if m.driving)
        cut = [m for m in self._motors if m.state in (LIMIT, SLIPPED)]
        bits = [f"{self._phase}"]
        if self._phase == HEATING:
            bits.append(f"{driving}/{len(self._motors)} driving")
        if cut:
            bits.append(f"{len(cut)} cut (" + ", ".join(
                f"m{self._numbers.get(m.id, m.id)} {m.state}" for m in cut) + ")")
        return " · ".join(bits)

    def _reports(self, now: float) -> list[dict]:
        history = self._history
        return [m.report(now, self._t0, history.rate(m) if history else None)
                for m in self._motors]

    def _publish(self, ctx: OpContext, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_publish < PUBLISH_PERIOD_S:
            return
        self._last_publish = now
        p = self.params
        phase_total = (None if p["loop"] else p["duration_s"]) \
            if self._phase == HEATING else p["cooldown_s"]
        ctx.set_extra({
            "elapsed_s": round(now - self._t0, 1),
            "phase": self._phase,
            "phase_elapsed_s": round(now - self._phase_t0, 1),
            "phase_total_s": phase_total,
            "progress": self._progress(),
            "waveform": p["waveform"],
            "frequency_hz": p["frequency_hz"],
            "amplitude_ma": p["amplitude_ma"],
            "offset_ma": p["offset_ma"],
            "temp_limit_c": p["temp_limit_c"],
            "max_temp_c": p["max_temp_c"],
            "slip_deg": p["slip_deg"],
            "slip_check": self._slip_check,
            "pairs": p["pairs"],
            "load": p["load"],
            "stagger": p["stagger"],
            "driving": sum(1 for m in self._motors if m.driving),
            "live": dict(self._live),
            "motors": self._reports(now),
            "history_points": len(self._history.t) if self._history else 0,
            "log": {"on": self._csv.on, "file": self._csv.name,
                    "files": list(self._csv.files), "rows": self._csv.rows},
        })
        ctx.set_detail(self._detail())
        progress = self._progress()
        if progress is not None:
            ctx.set_progress(progress)

    # ----- csv / log ---------------------------------------------------------------

    def _label(self, m: _Motor) -> str:
        number = self._numbers.get(m.id)
        return f"{number} (id {m.id})" if number is not None else f"id {m.id}"

    def _fields(self, m: _Motor, now: float) -> dict:
        return {
            "time": datetime.now().isoformat(timespec="milliseconds"),
            "t_s": now - self._t0,
            "phase": self._phase,
            "motor": self._numbers.get(m.id),
            "id": m.id,
            "state": m.state,
            "goal_ma": m.goal_ma,
            "current_ma": m.current_ma,
            "position_deg": m.pos_deg,
            "drift_deg": m.drift_deg,
            "temp_c": m.temp_c,
        }

    def _log_plan(self, ctx: OpContext) -> None:
        p = self.params
        wave = p["waveform"]
        if wave == "constant":
            shape = f"constant {p['offset_ma']:+.0f} mA"
        else:
            shape = (f"{wave} {p['offset_ma']:+.0f} ± {p['amplitude_ma']:.0f} mA "
                     f"at {p['frequency_hz']:g} Hz")
        length = "until stopped" if p["loop"] else f"for {p['duration_s']:g} s"
        ctx.log(f"thermal test: {len(p['motors'])} motor(s), {shape}, {length}, "
                f"then {p['cooldown_s']:g} s cooldown"
                + (", free — the motors turn, current control mode" if self._free
                   else ", coupled — shafts blocked")
                + (" — logging to CSV" if self._log_wanted else ""))
        ctx.log(f"  cut at {p['temp_limit_c']:g} °C"
                + ("" if self._free else f" or {p['slip_deg']:g}° of shaft drift"
                   + ("" if self._slip_check else " (drift check off: mock)")))
        if p["pairs"]:
            ctx.log("  coupled pairs: " + ", ".join(
                f"{self._label(self._by_id[a])} ↔ {self._label(self._by_id[b])}"
                for a, b in p["pairs"]))
        phases = sorted({round(m.phase_s, 3) for m in self._motors})
        if len(phases) > 1:
            ctx.log(f"  phases staggered over {len(phases)} slots: "
                    + ", ".join(f"{ph * 1000:.0f} ms" for ph in phases))
        loose = [self._label(m) for m in self._motors if m.partner is None]
        if loose and not self._free:
            ctx.log(f"  no load partner: {', '.join(loose)} — clamped some other way?")
        inverted = [str(m["id"]) for m in p["motors"] if m["invert"]]
        if inverted:
            ctx.log(f"  inverted: id {', '.join(inverted)}")

    def _log_report(self, ctx: OpContext, report: list[dict]) -> None:
        ctx.log(f"thermal test over after {self._fmt_s(time.monotonic() - self._t0)}")
        for row in report:
            temp = ("—" if row["temp_c"] is None else
                    f"{row['temp_start_c']:.0f}→{row['temp_c']:.0f} °C "
                    f"(max {row['temp_max_c']:.0f})")
            rms = "—" if row["current_rms_ma"] is None else f"{row['current_rms_ma']:.0f} mA rms"
            ctx.log(f"  motor {self._label(self._by_id[row['id']])}: {temp}, {rms}, "
                    f"drift {row['drift_max_deg']:.1f}°, {row['state']}")

    @staticmethod
    def _fmt_s(seconds: float) -> str:
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        return f"{h}h {m:02d}m {s:02d}s" if h else f"{m}m {s:02d}s"
