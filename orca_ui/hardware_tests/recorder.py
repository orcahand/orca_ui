"""Run one hardware-test scenario with whichever orca_core this interpreter imports.

The console runs this file under each side's own checkout environment::

    uv run --project <checkout> --no-dev --python <x.y> python recorder.py \\
        <scenario> --args-json <file> --out <dir> [--mock]

so the same scenario runs once with main's orca_core and once with the
branch's. It imports nothing from orca_ui: only the standard library and
orca_core. Every run writes ``<out>/result.json`` (also on error, with the
traceback); scenarios that move the hand also write ``<out>/readings.jsonl``
sampled at about 20 Hz (time, motor positions, currents, temperatures, and the
joint encoders when present).

A scenario that needs something this side's orca_core lacks reports
``available: false`` with the reason instead of failing. Creating the
``stop_file`` named in the arguments (default ``<out>/STOP``), SIGTERM or
SIGINT stops the running task; torque goes off and the hand is disconnected
on every way out.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import enum
import inspect
import json
import logging
import math
import os
import platform
import signal
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

RESULT_FILE = "result.json"
READINGS_FILE = "readings.jsonl"
STOP_FILE = "STOP"
SAMPLE_HZ = 20.0
TEMPERATURE_EVERY = 10
"""Temperatures change slowly, so they are read on every 10th sample only."""
TASK_STOP_TIMEOUT_S = 30.0
HOLD_START_TIMEOUT_S = 180.0
MOVE_STEPS = 25
MOVE_STEP_S = 0.02
ENCODER_COUNT_MASK = 0x3FFF


class Unavailable(Exception):
    """The scenario cannot run with this side's orca_core or on this hand."""


class Stopped(Exception):
    """A stop was requested while the scenario ran."""


# ----- JSON ---------------------------------------------------------------------------


def jsonable(value):
    """``value`` as plain JSON data: dataclasses, numpy values and enums included."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, enum.Enum):
        return jsonable(value.value)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: jsonable(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [jsonable(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (bytes, bytearray)):
        return value.hex()
    if hasattr(value, "tolist"):
        return jsonable(value.tolist())
    if hasattr(value, "item"):
        return jsonable(value.item())
    return str(value)


def write_json_atomic(path: Path, data) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    with open(tmp, "w") as fh:
        json.dump(data, fh, indent=2, default=str)
    os.replace(tmp, path)


# ----- run state ------------------------------------------------------------------------


class _LogCapture(logging.Handler):
    def __init__(self, run: "Run"):
        super().__init__(level=logging.WARNING)
        self._run = run

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
        except Exception:
            message = str(record.msg)
        self._run.log_records.append({
            "t": self._run.t(), "level": record.levelname,
            "logger": record.name, "message": message,
        })


class Run:
    """What a scenario works with: its arguments, output folder, clock and stop."""

    def __init__(self, scenario: str, out_dir: Path, args: dict, *, mock: bool):
        self.scenario = scenario
        self.out = out_dir
        self.args = args
        self.mock = mock
        self.t0 = time.monotonic()
        self.stop_event = threading.Event()
        self.stop_file = Path(args.get("stop_file") or (out_dir / STOP_FILE))
        self.events: list[dict] = []
        self.notes: list[str] = []
        self.log_records: list[dict] = []
        self.thread_errors: list[str] = []
        self.hand_info: Optional[dict] = None
        self.readings_count = 0

    def t(self) -> float:
        return round(time.monotonic() - self.t0, 4)

    def stopped(self) -> bool:
        if not self.stop_event.is_set() and self.stop_file.exists():
            self.stop_event.set()
        return self.stop_event.is_set()

    def check_stop(self) -> None:
        if self.stopped():
            raise Stopped()

    def wait(self, seconds: float) -> None:
        """Sleep ``seconds``, raising :class:`Stopped` as soon as a stop arrives."""
        end = time.monotonic() + seconds
        while True:
            self.check_stop()
            left = end - time.monotonic()
            if left <= 0:
                return
            self.stop_event.wait(min(left, 0.05))

    def event(self, event: dict) -> None:
        """Keep a progress event from orca_core, stamped with the run's clock."""
        entry = {"t": self.t(), **jsonable(dict(event))}
        self.events.append(entry)
        name = entry.get("event")
        if name and name not in ("winding_progress", "spread"):
            detail = entry.get("joint") or entry.get("phase") or ""
            say(f"{name} {detail}".rstrip())

    def note(self, text: str) -> None:
        self.notes.append(text)
        say(text)


def say(message: str) -> None:
    """One line for the console's live log (it forwards lines with this prefix)."""
    print(f"[recorder] {message}", flush=True)


# ----- orca_core access, feature-detected ---------------------------------------------------


def accepted(fn: Callable, kwargs: dict, run: Run, what: str) -> dict:
    """``kwargs`` minus what ``fn`` does not accept on this side, noting each drop."""
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return kwargs
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return kwargs
    kept = {}
    for key, value in kwargs.items():
        if key in params:
            kept[key] = value
        elif value is not None:
            run.note(f"{what}() has no {key!r} parameter on this side; not passed")
    return kept


def side_hardware_version(version) -> Optional[int]:
    """``version`` (three-digit form, 210 = v2.1.0) in this side's encoding.

    An orca_core without ``normalize_hardware_version`` stores ``major*10 + minor``
    (21 = v2.1) and a bare major for x.0 (2 = v2.0).
    """
    if version is None:
        return None
    version = int(version)
    try:
        from orca_core.constants import normalize_hardware_version
    except ImportError:
        if version >= 100:
            major, minor = version // 100, version // 10 % 10
            return major * 10 + minor if minor else major
        return version
    return normalize_hardware_version(version)


def orca_core_info() -> dict:
    try:
        import orca_core
    except Exception as e:
        return {"version": None, "path": None, "error": repr(e)}
    version = getattr(orca_core, "__version__", None)
    if version is None:
        try:
            from importlib.metadata import version as dist_version
            version = dist_version("orca_core")
        except Exception:
            version = None
    return {"version": version, "path": os.path.dirname(os.path.abspath(orca_core.__file__))}


def _yaml_io():
    from orca_core.utils.utils import read_yaml, write_yaml_atomic
    return read_yaml, write_yaml_atomic


def adapt_config_copy(run: Run) -> None:
    """Rewrite a pinned ``hardware_version`` in the config copy into this side's encoding."""
    path = run.args.get("config_path")
    if not path or not os.path.isfile(path):
        return
    read_yaml, write_yaml_atomic = _yaml_io()
    data = read_yaml(path) or {}
    pinned = data.get("hardware_version")
    if isinstance(pinned, bool) or not isinstance(pinned, int):
        return
    adapted = side_hardware_version(pinned)
    if adapted != pinned:
        data["hardware_version"] = adapted
        write_yaml_atomic(path, data)
        run.note(f"hardware_version {pinned} is written as {adapted} for this side's orca_core")


def require_config(run: Run) -> str:
    path = run.args.get("config_path")
    if not path:
        raise ValueError(f"scenario {run.scenario!r} needs config_path in its arguments")
    if not os.path.isfile(path):
        raise FileNotFoundError(f"config not found: {path}")
    return path


def load(run: Run, *, engage_feedback: bool = True, engage_sensors: bool = True):
    from orca_core import load_hand

    kwargs = {
        "config_path": require_config(run),
        "mock": run.mock,
        "engage_feedback": engage_feedback,
        "engage_sensors": engage_sensors,
        "detected_hardware_version": side_hardware_version(
            run.args.get("detected_hardware_version")),
    }
    hand = load_hand(**accepted(load_hand, kwargs, run, "load_hand"))
    run.hand_info = describe_hand(hand)
    return hand


def describe_hand(hand) -> dict:
    config = hand.config
    info = {
        "class": type(hand).__name__,
        "config_path": getattr(config, "config_path", None),
        "model": os.path.basename(os.path.dirname(getattr(config, "config_path", "") or "")),
    }
    for name in ("port", "motor_type", "baudrate", "hardware_version", "control_mode",
                 "max_current", "calibration_current", "calibration_travel_margin",
                 "calibration_travel_retries", "joint_feedback_enabled",
                 "encoder_serial_port", "sensor_port", "motor_ids", "joint_ids",
                 "joint_to_motor_map", "neutral_position", "joint_roms_dict"):
        if hasattr(config, name):
            info[name] = jsonable(getattr(config, name))
    for name in ("uses_motor_travel", "is_v21"):
        try:
            info[name] = bool(getattr(config, name))
        except Exception:
            pass
    return info


def connect(run: Run, hand, *, engage_feedback: bool = True) -> None:
    kwargs = accepted(hand.connect, {"interactive": False, "engage_feedback": engage_feedback},
                      run, "connect")
    ok, message = hand.connect(**kwargs)
    say(f"connect: {message}")
    if not ok:
        raise RuntimeError(f"connect failed: {message}")
    run.hand_info = describe_hand(hand)
    check_same_hand(run, hand)


def check_same_hand(run: Run, hand) -> None:
    """Refuse to go on when autodetection opened another hand than the console's."""
    expected = run.args.get("expected_motor_port")
    actual = getattr(hand.config, "port", None)
    if not expected or not actual or os.path.realpath(expected) == os.path.realpath(actual):
        return
    release(run, hand)
    raise RuntimeError(f"connected to {actual}, but the console's hand is on {expected}; "
                       "unplug the other hand and run the check again")


def release(run: Run, hand, *, motors: bool = True) -> None:
    """Stop any task, take torque off and close the hand; never raises.
    ``motors=False`` for a hand whose motor bus was never opened."""
    steps = [("stop_task", lambda: hand.stop_task(timeout=TASK_STOP_TIMEOUT_S))]
    if motors:
        steps.append(("disable_torque", hand.disable_torque))
    steps.append(("disconnect", hand.disconnect))
    for name, call in steps:
        try:
            call()
        except Exception as e:
            run.notes.append(f"{name} on the way out failed: {e!r}")


def require_calibrated(hand) -> None:
    if not getattr(hand, "calibrated", False):
        raise RuntimeError(
            "the config copy has no complete calibration; calibrate the hand in the console first")


def joint_by_motor(hand) -> dict:
    return {str(m): j for j, m in (getattr(hand.config, "joint_to_motor_map", {}) or {}).items()}


def wait_task(run: Run, hand) -> None:
    """Wait for the hand's background task, stopping it if a stop arrives."""
    try:
        while hand.task_running:
            run.wait(0.1)
    except Stopped:
        hand.stop_task(timeout=TASK_STOP_TIMEOUT_S)
        raise
    if run.thread_errors:
        raise RuntimeError("the task failed:\n" + run.thread_errors[-1])


# ----- readings ---------------------------------------------------------------------------


class Sampler:
    """Writes one line per sample to ``readings.jsonl`` from a background thread."""

    def __init__(self, run: Run, hand, *, encoder_client=None):
        self.run = run
        self.hand = hand
        self.encoder_client = encoder_client
        self.period = 1.0 / float(run.args.get("sample_hz") or SAMPLE_HZ)
        self.path = run.out / READINGS_FILE
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="recorder-sampler", daemon=True)
        self.errors = 0

    def __enter__(self) -> "Sampler":
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        self._thread.join(timeout=5.0)
        if self.errors:
            self.run.notes.append(f"{self.errors} reading(s) failed while sampling")

    def _read(self, name: str):
        try:
            return jsonable(getattr(self.hand, name)())
        except Exception:
            self.errors += 1
            return None

    def _encoders(self):
        if self.encoder_client is not None:
            try:
                reading = self.encoder_client.get_latest()
            except Exception:
                return None
            if reading is None:
                return None
            return {"counts": [int(c) & ENCODER_COUNT_MASK for c in jsonable(reading.raw_counts)]}
        if hasattr(self.hand, "get_measured_joints"):
            try:
                return {"deg": jsonable(self.hand.get_measured_joints())}
            except Exception:
                return None
        return None

    def _loop(self) -> None:
        n = 0
        next_at = time.monotonic()
        with open(self.path, "a") as fh:
            while not self._stop.is_set():
                sample = {"t": self.run.t(), "pos": self._read("get_motor_pos"),
                          "cur": self._read("get_motor_current")}
                if n % TEMPERATURE_EVERY == 0:
                    sample["temp"] = self._read("get_motor_temp")
                encoders = self._encoders()
                if encoders is not None:
                    sample["enc"] = encoders
                fh.write(json.dumps(sample) + "\n")
                fh.flush()
                n += 1
                self.run.readings_count = n
                next_at += self.period
                self._stop.wait(max(0.0, next_at - time.monotonic()))


def read_mean_positions(run: Run, hand, *, samples: int = 10, spacing_s: float = 0.05) -> dict:
    """Mean motor position (rad) per motor id over a few reads."""
    sums: dict[str, float] = {}
    count = 0
    for _ in range(samples):
        positions = hand.get_motor_pos(as_dict=True)
        for motor, value in positions.items():
            sums[str(motor)] = sums.get(str(motor), 0.0) + float(value)
        count += 1
        run.wait(spacing_s)
    return {m: s / count for m, s in sums.items()}


def joint_positions(hand) -> dict:
    positions = hand.get_joint_position()
    return jsonable(positions.as_dict() if hasattr(positions, "as_dict") else positions)


def offset_pose(config, neutral: dict, joints, delta_deg: float) -> dict:
    """``neutral`` with each of ``joints`` moved ``delta_deg`` toward the middle of its ROM."""
    roms = getattr(config, "joint_roms_dict", {}) or {}
    pose = dict(neutral)
    for joint in joints:
        start = neutral.get(joint)
        if start is None:
            continue
        rom = roms.get(joint)
        if rom:
            low, high = float(rom[0]), float(rom[1])
            direction = 1.0 if (low + high) / 2 >= start else -1.0
            pose[joint] = min(max(start + direction * delta_deg, low), high)
        else:
            pose[joint] = start + delta_deg
    return pose


def move_to(hand, pose: dict) -> None:
    hand.set_joint_positions(pose, num_steps=MOVE_STEPS, step_size=MOVE_STEP_S)


def finger_joints(config) -> list:
    return [j for j in getattr(config, "joint_ids", []) if j != "wrist"]


# ----- scenarios ----------------------------------------------------------------------------

SCENARIOS: dict[str, Callable[[Run], dict]] = {}


def scenario(name: str):
    def register(fn):
        SCENARIOS[name] = fn
        return fn
    return register


@scenario("detect")
def detect(run: Run) -> dict:
    if run.mock:
        raise Unavailable("detection probes real hardware; a mock hand has nothing to detect")
    from orca_core.hand_factory import detect_hand

    return {"detection": jsonable(detect_hand())}


@scenario("load_configs")
def load_configs(run: Run) -> dict:
    """Load every packaged model config, plainly and as v2.1 hardware."""
    import orca_core
    from orca_core import load_hand

    models_dir = Path(orca_core.__file__).parent / "models"
    v21 = side_hardware_version(210)
    takes_version = "detected_hardware_version" in inspect.signature(load_hand).parameters
    models = {}
    for config_path in sorted(models_dir.glob("*/*/config.yaml")):
        run.check_stop()
        key = f"{config_path.parent.parent.name}/{config_path.parent.name}"
        entry = {}
        variants = [("plain", None)] + ([("v2.1", v21)] if takes_version else [])
        for label, version in variants:
            kwargs = {"config_path": str(config_path), "mock": True}
            if version is not None:
                kwargs["detected_hardware_version"] = version
            try:
                hand = load_hand(**kwargs)
                entry[label] = {"ok": True, "class": type(hand).__name__,
                                "joints": len(getattr(hand.config, "joint_ids", []) or []),
                                "hardware_version": jsonable(getattr(hand.config, "hardware_version", None))}
            except Exception as e:
                entry[label] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        models[key] = entry
    return {"models": models}


@scenario("load_config")
def load_config(run: Run) -> dict:
    """Load the config copy without connecting; the log keeps any pin warning."""
    hand = load(run, engage_feedback=False, engage_sensors=False)
    return {"hardware_version": jsonable(getattr(hand.config, "hardware_version", None)),
            "hand": describe_hand(hand)}


@scenario("calibrate")
def calibrate(run: Run) -> dict:
    """Calibrate (all joints, or ``joints``), persisting into the config copy."""
    hand = load(run, engage_feedback=False, engage_sensors=False)
    try:
        connect(run, hand, engage_feedback=False)
        with contextlib.ExitStack() as streams:
            encoder_client = open_encoders(run, hand, streams)
            kwargs = {
                "blocking": False,
                "joints": run.args.get("joints"),
                "force_wrist": bool(run.args.get("force_wrist", False)),
                "joint_encoder_client": encoder_client,
                "progress_callback": run.event,
                "persist": True,
            }
            with Sampler(run, hand, encoder_client=encoder_client):
                hand.calibrate(**accepted(hand.calibrate, kwargs, run, "calibrate"))
                wait_task(run, hand)
        names = [e.get("event") for e in run.events]
        outcome = ("done" if "calibration_done" in names
                   else "aborted" if "calibration_aborted" in names else "unknown")
        calibration_path = os.path.join(os.path.dirname(require_config(run)), "calibration.yaml")
        saved = None
        if os.path.isfile(calibration_path):
            read_yaml, _ = _yaml_io()
            saved = jsonable(read_yaml(calibration_path))
        return {
            "outcome": outcome,
            "joints": run.args.get("joints"),
            "encoder_pass": encoder_client is not None,
            "calibration": jsonable(getattr(hand, "calibration", None)),
            "calibration_path": calibration_path,
            "saved": saved,
            "joint_by_motor": joint_by_motor(hand),
        }
    finally:
        release(run, hand)


def open_encoders(run: Run, hand, streams: contextlib.ExitStack):
    """The joint-encoder stream for calibration's encoder pass, as the calibrate script opens it."""
    config = hand.config
    wanted = run.args.get("encoders", True)
    if not wanted or run.mock or not getattr(config, "joint_feedback_enabled", False):
        return None
    if getattr(config, "encoder_serial_port", None) == "disabled":
        return None
    try:
        from orca_core.utils.cli import open_encoder_stream
    except ImportError:
        run.note("open_encoder_stream is not available on this side; no encoder pass")
        return None
    return streams.enter_context(open_encoder_stream(
        config.encoder_serial_port, config.encoder_baudrate))


@scenario("neutral")
def neutral(run: Run) -> dict:
    """Move away and back to neutral ``cycles`` times, reading the motors each time."""
    cycles = int(run.args.get("cycles", 3))
    away_deg = float(run.args.get("away_deg", 10.0))
    settle_s = float(run.args.get("settle_s", 1.0))
    hand = load(run, engage_feedback=False, engage_sensors=False)
    try:
        connect(run, hand, engage_feedback=False)
        require_calibrated(hand)
        hand.init_joints(move_to_neutral=False)
        neutral_pose = {j: float(v) for j, v in (hand.config.neutral_position or {}).items()}
        away = offset_pose(hand.config, neutral_pose, finger_joints(hand.config), away_deg)
        results = []
        with Sampler(run, hand):
            for cycle in range(cycles):
                say(f"neutral cycle {cycle + 1}/{cycles}")
                move_to(hand, away)
                run.wait(settle_s)
                hand.set_neutral_position()
                run.wait(settle_s)
                results.append({"t": run.t(), "motor_pos": read_mean_positions(run, hand),
                                "joint_pos": joint_positions(hand)})
        return {"cycles": results, "neutral": neutral_pose,
                "targets": neutral_targets(run, hand, neutral_pose),
                "mapping": joint_mapping(hand),
                "joint_by_motor": joint_by_motor(hand)}
    finally:
        release(run, hand)


def neutral_targets(run: Run, hand, pose: dict) -> Optional[dict]:
    """The motor position (rad) this side commands for ``pose``, per motor id."""
    to_motor = getattr(hand, "_joint_to_motor_pos", None)
    if to_motor is None:
        run.note("this side cannot report its commanded motor targets")
        return None
    try:
        values = to_motor(pose)
    except Exception as e:
        run.note(f"commanded motor targets unavailable: {e!r}")
        return None
    return {str(m): float(v) for m, v in zip(hand.config.motor_ids, values) if v is not None}


def joint_mapping(hand) -> dict:
    """What turns a joint angle into a motor position on this side, for comparing sides."""
    config = hand.config
    roms = getattr(hand, "effective_joint_roms_dict", None)
    if roms is None:
        roms = getattr(config, "joint_roms_dict", {})
    return jsonable({
        "joint_roms": roms,
        "joint_to_motor_map": getattr(config, "joint_to_motor_map", {}),
        "joint_inversion": getattr(config, "joint_inversion_dict", {}),
        "neutral_position": getattr(config, "neutral_position", {}),
    })


@scenario("tension_hold")
def tension_hold(run: Run) -> dict:
    """Run tensioning until it holds, hold ``hold_s`` seconds, then stop it."""
    hold_s = float(run.args.get("hold_s", 10.0))
    hand = load(run, engage_feedback=False, engage_sensors=False)
    try:
        connect(run, hand, engage_feedback=False)
        kwargs = {"blocking": False, "move_motors": bool(run.args.get("move_motors", True)),
                  "progress_callback": run.event}
        with Sampler(run, hand):
            hand.tension(**accepted(hand.tension, kwargs, run, "tension"))
            hold_started = wait_for_phase(run, hand, "holding")
            run.wait(hold_s)
            hold_ended = run.t()
            hand.stop_task(timeout=TASK_STOP_TIMEOUT_S)
            run.wait(0.5)
        if run.thread_errors:
            raise RuntimeError("tensioning failed:\n" + run.thread_errors[-1])
        return {"hold_started_t": hold_started, "hold_ended_t": hold_ended,
                "joint_by_motor": joint_by_motor(hand)}
    finally:
        release(run, hand)


def wait_for_phase(run: Run, hand, phase: str) -> float:
    deadline = time.monotonic() + HOLD_START_TIMEOUT_S
    while True:
        for e in run.events:
            if e.get("event") == "phase" and e.get("phase") == phase:
                return e["t"]
        if not hand.task_running:
            raise RuntimeError(f"the task ended before reaching the {phase!r} phase")
        if time.monotonic() > deadline:
            raise TimeoutError(f"no {phase!r} phase within {HOLD_START_TIMEOUT_S:.0f} s")
        try:
            run.wait(0.05)
        except Stopped:
            hand.stop_task(timeout=TASK_STOP_TIMEOUT_S)
            raise


@scenario("joint_loop")
def joint_loop(run: Run) -> dict:
    """Command neutral, an offset pose and neutral again; record the encoder angles."""
    delta_deg = float(run.args.get("delta_deg", 10.0))
    hold_s = float(run.args.get("hold_s", 2.0))
    hand = load(run, engage_feedback=True, engage_sensors=False)
    if not hasattr(hand, "get_measured_joints"):
        raise Unavailable("this hand's config runs no joint-encoder loop")
    try:
        connect(run, hand, engage_feedback=True)
        loop_joints = list(getattr(hand, "loop_joint_names", None) or [])
        if not loop_joints:
            raise Unavailable("the loop closes on no joint (incomplete encoder calibration)")
        require_calibrated(hand)
        hand.init_joints(move_to_neutral=True)
        neutral_pose = {j: float(v) for j, v in (hand.config.neutral_position or {}).items()}
        chosen = [j for j in (run.args.get("joints") or loop_joints)
                  if j in loop_joints and j != "wrist"]
        offset = offset_pose(hand.config, neutral_pose, chosen, delta_deg)
        poses = []
        with Sampler(run, hand):
            for name, pose in (("neutral", neutral_pose), ("offset", offset),
                               ("neutral again", neutral_pose)):
                say(f"joint loop: {name}")
                start = run.t()
                move_to(hand, pose)
                run.wait(max(hold_s - 0.5, 0.0))
                measured = mean_measured(run, hand)
                poses.append({"name": name, "t_start": start, "t_end": run.t(),
                              "commanded": {j: pose[j] for j in chosen if j in pose},
                              "measured": measured})
        stats = None
        try:
            stats = jsonable(hand.get_loop_stats())
        except Exception as e:
            run.notes.append(f"get_loop_stats failed: {e!r}")
        return {"loop_joints": loop_joints, "joints": chosen, "poses": poses,
                "loop_stats": stats}
    finally:
        release(run, hand)


def mean_measured(run: Run, hand, *, samples: int = 10, spacing_s: float = 0.05) -> dict:
    sums: dict[str, float] = {}
    counts: dict[str, int] = {}
    for _ in range(samples):
        for joint, value in (hand.get_measured_joints() or {}).items():
            if value is None:
                continue
            sums[joint] = sums.get(joint, 0.0) + float(value)
            counts[joint] = counts.get(joint, 0) + 1
        run.wait(spacing_s)
    return {j: sums[j] / counts[j] for j in sums}


@scenario("tactile_health")
def tactile_health(run: Run) -> dict:
    """Open the tactile link alone, stream for ``duration_s`` and read its health."""
    duration_s = float(run.args.get("duration_s", 3.0))
    hand = load(run, engage_feedback=False, engage_sensors=True)
    if not hasattr(hand, "connect_sensors_only"):
        raise Unavailable("this hand's config declares no tactile sensors")
    try:
        ok, message = hand.connect_sensors_only()
        say(f"tactile: {message}")
        if not ok:
            raise RuntimeError(f"tactile connect failed: {message}")
        configuration = jsonable(hand.get_tactile_configuration())
        hand.start_tactile_stream(resultant=True)
        before = jsonable(hand.get_tactile_stats())
        seqs = set()
        period = 1.0 / float(run.args.get("sample_hz") or SAMPLE_HZ)
        with open(run.out / READINGS_FILE, "a") as fh:
            end = time.monotonic() + duration_s
            while time.monotonic() < end:
                reading = hand.get_tactile_forces()
                if reading is not None:
                    seq = getattr(reading, "seq", None)
                    seqs.add(seq if seq is not None else getattr(reading, "timestamp", None))
                    fh.write(json.dumps({"t": run.t(), "seq": seq,
                                         "forces": jsonable(getattr(reading, "forces", None))}) + "\n")
                    run.readings_count += 1
                run.wait(period)
        after = jsonable(hand.get_tactile_stats())
        health = None
        try:
            health = jsonable(hand.get_fingertip_health())
        except Exception as e:
            run.notes.append(f"get_fingertip_health failed: {e!r}")
        link = jsonable(hand.get_tactile_link_health())
        frames = None
        if isinstance(before, dict) and isinstance(after, dict):
            frames = (after.get("frames_ok") or 0) - (before.get("frames_ok") or 0)
        seqs.discard(None)
        return {"configuration": configuration, "stats_before": before, "stats_after": after,
                "frames_ok": frames, "distinct_readings": len(seqs), "duration_s": duration_s,
                "fingertip_health": health, "link_health": link}
    finally:
        with contextlib.suppress(Exception):
            hand.stop_tactile_stream()
        release(run, hand, motors=False)


@scenario("guided_tension_gate")
def guided_tension_gate(run: Run) -> dict:
    """Start guided tensioning with and without the any-hardware override and
    report whether it refused. A start ends at its first prompt, with torque off."""
    try:
        from orca_core.maintenance.guided_tension import run_guided_tension
    except ImportError as e:
        raise Unavailable(f"this side has no guided tensioning: {e}")
    params = inspect.signature(run_guided_tension).parameters
    hand = load(run, engage_feedback=False, engage_sensors=False)
    try:
        connect(run, hand, engage_feedback=False)
        attempts = []
        for any_hardware in run.args.get("any_hardware", [False, True]):
            run.check_stop()
            if any_hardware and "any_hardware" not in params:
                attempts.append({"any_hardware": True, "outcome": "unavailable",
                                 "message": "run_guided_tension has no any_hardware parameter"})
                continue
            attempts.append(try_guided_tension(run, hand, run_guided_tension, bool(any_hardware)))
            with contextlib.suppress(Exception):
                hand.disable_torque()
        return {"attempts": attempts, "hardware_version": jsonable(hand.config.hardware_version)}
    finally:
        release(run, hand)


def try_guided_tension(run: Run, hand, run_guided_tension, any_hardware: bool) -> dict:
    prompts: list[dict] = []
    reached = threading.Event()

    def prompt(payload: dict) -> str:
        prompts.append({"action": payload.get("action"), "options": payload.get("options")})
        reached.set()
        return (payload.get("options") or [""])[0]

    kwargs = {"prompt_callback": prompt, "progress_callback": run.event,
              "should_stop": lambda: reached.is_set() or run.stopped(),
              "persist": False, "resume": False, "any_hardware": any_hardware}
    say(f"guided tension, any_hardware={any_hardware}")
    entry = {"any_hardware": any_hardware}
    try:
        run_guided_tension(hand, **accepted(run_guided_tension, kwargs, run, "run_guided_tension"))
        entry.update(outcome="finished", message="it ran to the end without a prompt")
    except ValueError as e:
        entry.update(outcome="refused", message=str(e))
    except InterruptedError as e:
        run.check_stop()
        entry.update(outcome="started" if prompts else "stopped", message=str(e))
    except Exception as e:
        entry.update(outcome="error", message=f"{type(e).__name__}: {e}",
                     traceback=traceback.format_exc())
    entry["first_prompt"] = prompts[0] if prompts else None
    return entry


# ----- entry point --------------------------------------------------------------------------


def parse_args(argv: Optional[list] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one hardware-test scenario with this orca_core.")
    parser.add_argument("scenario", choices=sorted(SCENARIOS))
    parser.add_argument("--args-json", dest="args_json", default=None,
                        help="JSON file with the scenario's arguments.")
    parser.add_argument("--out", required=True, help="Folder for result.json and readings.jsonl.")
    parser.add_argument("--mock", action="store_true", help="Use orca_core's in-memory mock hand.")
    return parser.parse_args(argv)


def read_args(path: Optional[str]) -> dict:
    if not path:
        return {}
    with open(path) as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must hold a JSON object")
    return data


def _install_stop_signals(run: Run) -> None:
    if threading.current_thread() is not threading.main_thread():
        return
    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(ValueError, OSError):
            signal.signal(sig, lambda *_: run.stop_event.set())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def execute(scenario_name: str, out_dir: Path, args: dict, *, mock: bool,
            stop_signals: bool = False) -> dict:
    """Run one scenario and write its ``result.json``; returns what was written.
    ``stop_signals`` makes SIGTERM/SIGINT stop the run (the script's own process only)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    run = Run(scenario_name, out_dir, args, mock=mock)
    if stop_signals:
        _install_stop_signals(run)
    capture = _LogCapture(run)
    root = logging.getLogger()
    root.addHandler(capture)
    previous_hook = threading.excepthook

    def thread_hook(hook_args) -> None:
        run.thread_errors.append("".join(traceback.format_exception(
            hook_args.exc_type, hook_args.exc_value, hook_args.exc_traceback)))
        previous_hook(hook_args)

    threading.excepthook = thread_hook
    result = {
        "scenario": scenario_name, "ok": False, "available": True, "reason": None,
        "stopped": False, "error": None, "traceback": None,
        "mock": mock, "python": platform.python_version(), "orca_core": orca_core_info(),
        "started_at": _now(), "args": jsonable(args),
    }
    data = None
    try:
        adapt_config_copy(run)
        data = SCENARIOS[scenario_name](run)
        result["ok"] = True
    except Unavailable as e:
        result.update(available=False, reason=str(e))
    except Stopped:
        result.update(stopped=True, error="stopped on request")
    except BaseException as e:
        result.update(error=f"{type(e).__name__}: {e}", traceback=traceback.format_exc())
        if run.stopped():
            result["stopped"] = True
    finally:
        threading.excepthook = previous_hook
        root.removeHandler(capture)
        readings = out_dir / READINGS_FILE
        result.update(
            finished_at=_now(), duration_s=run.t(), hand=run.hand_info, data=jsonable(data),
            events=run.events, log=run.log_records, notes=run.notes,
            thread_errors=run.thread_errors,
            readings=READINGS_FILE if readings.exists() else None,
            readings_count=run.readings_count,
        )
        write_json_atomic(out_dir / RESULT_FILE, result)
    return result


def main(argv: Optional[list] = None) -> int:
    opts = parse_args(argv)
    out_dir = Path(opts.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        args = read_args(opts.args_json)
    except Exception as e:
        write_json_atomic(out_dir / RESULT_FILE, {
            "scenario": opts.scenario, "ok": False, "available": True,
            "error": f"could not read the arguments: {e}", "traceback": traceback.format_exc()})
        return 2
    logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    mock = bool(opts.mock or args.get("mock"))
    result = execute(opts.scenario, out_dir, args, mock=mock, stop_signals=True)
    if result.get("ok") or not result.get("available", True):
        return 0
    return 3 if result.get("stopped") else 1


if __name__ == "__main__":
    raise SystemExit(main())
