"""Bench excitation tests: drive one motor with a chirp and record what it did.

A chirp is a sine whose frequency sweeps from ``f0`` to ``f1`` over the run,
with a cosine ramp at both ends so the motor is never stepped. The runner
commands and samples on one thread at a fixed rate -- command, then one bus
round trip reading position, velocity and current -- so every sample is
aligned with the command that produced it by construction.

Two command modes:

* ``position`` -- goal position around a centre, amplitude in radians.
* ``current``  -- signed goal current, amplitude in mA or in N.m. Torque is
  translated to current through the motor model's fitted torque curve and
  only offered where the connected client can actually drive the motor in
  current-control mode.

Runs are saved as CSV with a JSON sidecar under ``motortestingdata/``, which
is never committed.
"""

from __future__ import annotations

import csv
import json
import logging
import math
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np

from orca_core.constants import CURRENT, MODE_MAP

from orca_ui.hand import motor_models
from orca_ui.streaming import topics as T

logger = logging.getLogger(__name__)

RATE_HZ_DEFAULT = 200.0
RATE_HZ_MIN, RATE_HZ_MAX = 20.0, 500.0
TRACE_PUBLISH_HZ = 30.0          # live plot feed; the full record goes to disk
READ_FAILURES_TO_ABORT = 10
POSITION_ENVELOPE_RAD = 1.0      # current mode: abort if the motor runs this far

SWEEPS = ("linear", "exponential")
TAPERS = ("cosine", "none")
MODES = ("position", "current")
TORQUE_UNITS = ("ma", "nm")


class MotorTestError(ValueError):
    pass


@dataclass(frozen=True)
class ChirpSpec:
    motor_id: int
    mode: str                       # position | current
    amplitude: float                # rad (position) | mA or N.m (current, see torque_unit)
    f0_hz: float
    f1_hz: float
    duration_s: float
    offset: float = 0.0             # position: centre in rad (None -> present); current: mA bias
    centre_on_present: bool = True  # position mode: ignore offset, chirp about where the motor is
    sweep: str = "linear"
    taper: str = "cosine"
    taper_s: float = 0.5
    rate_hz: float = RATE_HZ_DEFAULT
    torque_unit: str = "ma"         # current mode only
    position_envelope_rad: float = POSITION_ENVELOPE_RAD

    def validate(self) -> None:
        if self.mode not in MODES:
            raise MotorTestError(f"mode must be one of {MODES}")
        if self.sweep not in SWEEPS:
            raise MotorTestError(f"sweep must be one of {SWEEPS}")
        if self.taper not in TAPERS:
            raise MotorTestError(f"taper must be one of {TAPERS}")
        if self.torque_unit not in TORQUE_UNITS:
            raise MotorTestError(f"torque_unit must be one of {TORQUE_UNITS}")
        for name in ("amplitude", "f0_hz", "f1_hz", "duration_s", "taper_s", "rate_hz", "offset"):
            v = getattr(self, name)
            if not isinstance(v, (int, float)) or not math.isfinite(v):
                raise MotorTestError(f"{name} must be a finite number")
        if self.amplitude <= 0:
            raise MotorTestError("amplitude must be positive")
        if self.f0_hz <= 0 or self.f1_hz <= 0:
            raise MotorTestError("frequencies must be positive")
        if self.duration_s <= 0 or self.duration_s > 600:
            raise MotorTestError("duration_s must be in (0, 600]")
        if not RATE_HZ_MIN <= self.rate_hz <= RATE_HZ_MAX:
            raise MotorTestError(f"rate_hz must be in [{RATE_HZ_MIN:.0f}, {RATE_HZ_MAX:.0f}]")
        if self.taper_s < 0 or 2 * self.taper_s > self.duration_s:
            raise MotorTestError("taper_s must be >= 0 and at most half the duration")
        if self.sweep == "exponential" and abs(self.f1_hz - self.f0_hz) < 1e-9:
            raise MotorTestError("an exponential sweep needs f0 != f1")


# --- the signal ------------------------------------------------------------

def chirp_phase(spec: ChirpSpec, t: float) -> float:
    """Instantaneous phase in radians at time ``t`` into the run."""
    T_ = spec.duration_s
    if spec.sweep == "linear":
        return 2 * math.pi * (spec.f0_hz * t + (spec.f1_hz - spec.f0_hz) * t * t / (2 * T_))
    k = spec.f1_hz / spec.f0_hz
    return 2 * math.pi * spec.f0_hz * T_ / math.log(k) * (k ** (t / T_) - 1.0)


def envelope(spec: ChirpSpec, t: float) -> float:
    """0..1 amplitude window: cosine ramps of ``taper_s`` at both ends."""
    if spec.taper == "none" or spec.taper_s <= 0:
        return 1.0
    T_, r = spec.duration_s, spec.taper_s
    if t < r:
        return 0.5 - 0.5 * math.cos(math.pi * t / r)
    if t > T_ - r:
        return 0.5 - 0.5 * math.cos(math.pi * (T_ - t) / r)
    return 1.0


def chirp_value(spec: ChirpSpec, t: float) -> float:
    """The command's deviation from its centre at time ``t``, in the spec's unit."""
    return spec.amplitude * envelope(spec, t) * math.sin(chirp_phase(spec, t))


# --- torque <-> current, through the model's fitted curve ------------------

def current_a_for_torque(model: motor_models.MotorModel, torque_nm: float) -> tuple[float, bool]:
    """Current in A that the fitted curve says produces ``torque_nm``.

    Sign-preserving: the fit is for |torque|, the sign is the direction.
    Returns ``(current_a, extrapolated)``; ``extrapolated`` is True when the
    requested torque lies outside what the datasheet curve covers, in which
    case the current is clamped to the end of the fitted range.
    """
    mag = abs(torque_nm)
    sign = 1.0 if torque_nm >= 0 else -1.0
    poly = model.torque_poly_nm
    rng = model.torque_poly_current_range_a
    if not poly or not rng:
        if model.torque_constant_nm_per_a:
            return sign * mag / model.torque_constant_nm_per_a, False
        raise MotorTestError(f"{model.label} has no torque curve to translate N.m into current")
    lo, hi = rng
    t_lo, t_hi = model.torque_nm(lo) or 0.0, model.torque_nm(hi) or 0.0
    if mag >= t_hi:
        return sign * hi, mag > t_hi
    if mag <= t_lo:
        # Below the fitted range: a straight line through the origin to the
        # curve's first point, and flagged, since the curve does not cover it.
        return sign * lo * (mag / t_lo if t_lo else 0.0), mag < t_lo
    # Bisection on a curve that is monotonic over the fitted range.
    a, b = lo, hi
    for _ in range(60):
        m = 0.5 * (a + b)
        if (model.torque_nm(m) or 0.0) < mag:
            a = m
        else:
            b = m
    return sign * 0.5 * (a + b), False


# --- the run ----------------------------------------------------------------

@dataclass
class RunState:
    run_id: str | None = None
    status: str = "idle"            # idle | running | done | stopped | error
    detail: str = ""
    progress: float = 0.0
    samples: int = 0
    achieved_rate_hz: float | None = None
    file: str | None = None
    spec: dict | None = field(default=None)

    def as_dict(self) -> dict:
        return asdict(self)


class ChirpRunner:
    """One run at a time, on its own thread, against the console's live hand."""

    def __init__(self, service, data_dir: Path) -> None:
        self._service = service
        self._dir = data_dir
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._state = RunState()
        self._trace: list[list[float]] = []

    # -- public ---------------------------------------------------------------

    def state(self) -> dict:
        with self._lock:
            return self._state.as_dict()

    def start(self, spec: ChirpSpec) -> dict:
        spec.validate()
        service = self._service
        session = service._require_torque()
        hand = session.hand
        client = hand.motor_client
        if spec.motor_id not in hand.config.motor_ids:
            raise MotorTestError(f"unknown motor id {spec.motor_id}")
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                raise MotorTestError("a test is already running")
        if spec.mode == "current" and not client.supports_current_control(spec.motor_id):
            raise MotorTestError(
                f"motor {spec.motor_id} cannot be driven in current control mode")

        model = self._model_for(session, spec.motor_id)
        centre, current_bias = self._centre(hand, spec)
        amplitude_ma, extrapolated = None, False
        if spec.mode == "current":
            if spec.torque_unit == "nm":
                current_a, extrapolated = current_a_for_torque(model, spec.amplitude)
                amplitude_ma = abs(current_a) * 1000.0
            else:
                amplitude_ma = spec.amplitude
            ceiling = client.read_current_limits().get(spec.motor_id)
            if ceiling is not None and abs(current_bias) + amplitude_ma > ceiling:
                raise MotorTestError(
                    f"|bias| + amplitude = {abs(current_bias) + amplitude_ma:.0f} mA exceeds the "
                    f"motor's ceiling of {ceiling:.0f} mA; lower the amplitude or raise the ceiling")
        else:
            rng = service._bench_ranges.get(spec.motor_id)
            if rng is not None:
                lo, hi = min(rng), max(rng)
                if centre - spec.amplitude < lo or centre + spec.amplitude > hi:
                    raise MotorTestError(
                        f"centre ± amplitude ({centre - spec.amplitude:.2f}..{centre + spec.amplitude:.2f} rad) "
                        f"leaves the motor's recorded range ({lo:.2f}..{hi:.2f} rad)")

        run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + f"-m{spec.motor_id}-{spec.mode}"
        with self._lock:
            self._state = RunState(run_id=run_id, status="running", detail="starting",
                                   spec={**asdict(spec), "centre": centre,
                                         "amplitude_ma": amplitude_ma,
                                         "torque_extrapolated": extrapolated,
                                         "model": model.key})
            self._trace = []
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="motor-test",
            args=(session, spec, model, centre, current_bias, amplitude_ma, run_id), daemon=True)
        self._thread.start()
        return self.state()

    def stop(self) -> bool:
        """Ask a running test to stop. Returns whether one was running."""
        running = self._thread is not None and self._thread.is_alive()
        self._stop.set()
        return running

    def join(self, timeout: float = 5.0) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    # -- storage -------------------------------------------------------------

    def list_runs(self) -> list[dict]:
        out = []
        for meta in sorted(self._dir.glob("*.json"), reverse=True):
            try:
                d = json.loads(meta.read_text())
            except Exception:
                continue
            d["run_id"] = meta.stem
            d["csv"] = meta.with_suffix(".csv").name
            out.append(d)
        return out

    def run_path(self, run_id: str, suffix: str) -> Path:
        if not run_id or "/" in run_id or ".." in run_id:
            raise MotorTestError("bad run id")
        path = self._dir / f"{run_id}{suffix}"
        if not path.exists():
            raise MotorTestError(f"no such run {run_id!r}")
        return path

    def delete_run(self, run_id: str) -> None:
        for suffix in (".csv", ".json"):
            p = self._dir / f"{run_id}{suffix}"
            if p.exists():
                p.unlink()

    # -- internals -------------------------------------------------------------

    def _model_for(self, session, motor_id: int) -> motor_models.MotorModel:
        declared = self._service._bench_declared.get(int(motor_id), {})
        model = motor_models.get(declared.get("model"))
        reported = self._service._reported_model_number(session, motor_id)
        identified = motor_models.for_model_number(reported)
        return identified or model

    def _centre(self, hand, spec: ChirpSpec) -> tuple[float, float]:
        if spec.mode == "position":
            if spec.centre_on_present:
                return float(hand.get_motor_pos(as_dict=True)[spec.motor_id]), 0.0
            return float(spec.offset), 0.0
        return 0.0, float(spec.offset)

    def _set_state(self, **changes) -> None:
        with self._lock:
            for k, v in changes.items():
                setattr(self._state, k, v)
            snapshot = self._state.as_dict()
        self._service._publish_topic(T.TESTING_STATE, snapshot)

    def _run(self, session, spec, model, centre, current_bias, amplitude_ma, run_id) -> None:
        service = self._service
        hand = session.hand
        client = hand.motor_client
        idx = hand.config.motor_ids.index(spec.motor_id)
        period = 1.0 / spec.rate_hz
        publish_every = max(1, int(round(spec.rate_hz / TRACE_PUBLISH_HZ)))
        previous_mode = None
        failures = 0
        status, detail = "done", "complete"
        service.pause_bench_telemetry(True)
        service.stop_all_playback()
        t0 = None
        try:
            if spec.mode == "current":
                previous_mode = (client.operating_mode(spec.motor_id)
                                 if hasattr(client, "operating_mode") else None)
                if previous_mode is None:
                    # Unknown: go back to what the config asks for afterwards.
                    previous_mode = MODE_MAP.get(getattr(hand.config, "control_mode", None))
                if previous_mode != MODE_MAP[CURRENT]:
                    with hand._motor_lock:
                        hand.set_control_mode(CURRENT, [spec.motor_id])
                start_pos = float(hand.get_motor_pos(as_dict=True)[spec.motor_id])
            else:
                start_pos = centre
            self._set_state(detail="running")
            t0 = time.perf_counter()
            n = 0
            while not self._stop.is_set():
                t = time.perf_counter() - t0
                if t > spec.duration_s:
                    break
                u = chirp_value(spec, t)
                if spec.mode == "position":
                    cmd = centre + u
                    hand.write_motor_pos([spec.motor_id], np.asarray([cmd]))
                else:
                    cmd = current_bias + (u / spec.amplitude) * amplitude_ma
                    with hand._motor_lock:
                        client.write_goal_current_signed([spec.motor_id], [cmd])
                with hand._motor_lock:
                    read = client.read_position_velocity_current()
                ok = bool(getattr(client, "last_read_ok", True))
                if not ok:
                    failures += 1
                    if failures >= READ_FAILURES_TO_ABORT:
                        raise RuntimeError(f"{failures} consecutive read failures")
                else:
                    failures = 0
                pos, vel, cur = (float(read.position[idx]), float(read.velocity[idx]),
                                 float(read.current[idx]))
                self._trace.append([t, cmd, pos, vel, cur])
                n += 1
                if spec.mode == "current" and abs(pos - start_pos) > spec.position_envelope_rad:
                    raise RuntimeError(
                        f"motor ran {abs(pos - start_pos):.2f} rad from where it started; "
                        f"envelope is {spec.position_envelope_rad:.2f} rad")
                if n % publish_every == 0:
                    self._set_state(progress=min(1.0, t / spec.duration_s), samples=n)
                    service._publish_topic(T.TESTING_TRACE, {
                        "run_id": run_id, "t": t, "cmd": cmd, "pos": pos, "vel": vel, "cur": cur})
                # pace: sleep what is left of the period
                remaining = (t0 + (n) * period) - time.perf_counter()
                if remaining > 0:
                    time.sleep(remaining)
            if self._stop.is_set():
                status, detail = "stopped", "stopped by operator"
        except Exception as e:                       # noqa: BLE001 - reported, not raised
            status, detail = "error", str(e)
            logger.warning("motor test aborted: %s", e)
        finally:
            try:
                if spec.mode == "current":
                    with hand._motor_lock:
                        try:
                            client.write_goal_current_signed([spec.motor_id], [0.0])
                        except Exception:
                            pass
                        if previous_mode is not None and previous_mode != MODE_MAP[CURRENT]:
                            mode_name = next((k for k, v in MODE_MAP.items() if v == previous_mode), None)
                            if mode_name:
                                hand.set_control_mode(mode_name, [spec.motor_id])
            except Exception as e:                   # noqa: BLE001
                logger.warning("could not restore the motor after the test: %s", e)
                if status == "done":
                    status, detail = "error", f"complete, but restoring the motor failed: {e}"
            service.pause_bench_telemetry(False)
            elapsed = (time.perf_counter() - t0) if t0 else None
            achieved = (len(self._trace) / elapsed) if elapsed and self._trace else None
            path = self._save(run_id, spec, model, centre, current_bias, amplitude_ma, status, detail, achieved)
            changes = dict(status=status, detail=detail, samples=len(self._trace),
                           achieved_rate_hz=achieved, file=path.name if path else None)
            if status == "done":
                changes["progress"] = 1.0
            self._set_state(**changes)

    def _save(self, run_id, spec, model, centre, current_bias, amplitude_ma, status, detail, achieved):
        if not self._trace:
            return None
        self._dir.mkdir(parents=True, exist_ok=True)
        csv_path = self._dir / f"{run_id}.csv"
        unit = "rad" if spec.mode == "position" else "mA"
        with csv_path.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["t_s", f"command_{unit}", "position_rad", "velocity_rad_s", "current_ma"])
            w.writerows(self._trace)
        meta = {
            "spec": asdict(spec), "centre": centre, "current_bias_ma": current_bias,
            "amplitude_ma": amplitude_ma, "model": model.key, "model_label": model.label,
            "torque_poly_nm": model.torque_poly_nm,
            "torque_poly_current_range_a": model.torque_poly_current_range_a,
            "status": status, "detail": detail, "samples": len(self._trace),
            "achieved_rate_hz": achieved, "saved_at": datetime.now().isoformat(timespec="seconds"),
        }
        (self._dir / f"{run_id}.json").write_text(json.dumps(meta, indent=2))
        return csv_path
