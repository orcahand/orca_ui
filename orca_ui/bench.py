"""ORCA Motor Bench: a few hand motors on a bus, no hand around them.

``orca-bench`` is its own tool with its own page, but it runs the console's
backend stack over a config that names only the bench's motors. Every safety
layer the hand gets — the torque gate, the current ceiling, the e-stop, the
operation arbiter, fault accounting — applies unchanged; what differs is that
nothing is calibrated and nothing is a joint, so the bench page works in
motor-shaft degrees and the cycling operation writes motor space directly.

The config lives in the user's home so the port and baud rate orca_core
resolves at connect are remembered across runs, and so motor IDs can be
edited by hand. ``--motors`` rewrites the motor set in place; the page's bus
scan does the same from what it finds.
"""

from __future__ import annotations

import argparse
import logging
import os
import tempfile
import threading

import yaml

from orca_ui.settings import UiSettings

logger = logging.getLogger(__name__)

BENCH_MODEL_NAME = "orca-bench"
BENCH_PRODUCT = "ORCA BENCH"
DEFAULT_PORT = 5002
DEFAULT_BENCH_MOTORS = (1, 2)
# Nominal joint ROM per bench "joint". Only there because the config schema
# needs one; the bench never commands joint space.
_NOMINAL_ROM = [0.0, 360.0]


def bench_model_dir(root: str | None = None) -> str:
    root = root or os.path.join(os.path.expanduser("~"), ".orca_ui", "bench")
    return os.path.join(root, BENCH_MODEL_NAME)


def is_bench_config(config) -> bool:
    """True for a config materialized by this module (named by its folder)."""
    path = getattr(config, "config_path", None) or ""
    return os.path.basename(os.path.dirname(os.path.abspath(path))) == BENCH_MODEL_NAME


def joint_for_number(number: int) -> str:
    """The joint name a bench motor number maps to. The number is what the
    operator calls the motor ("motor 1"); the bus id is whatever the servo
    was programmed with, and the two are tied only in the config's map."""
    return f"motor_{int(number)}"


def number_of_joint(joint: str) -> int | None:
    if joint.startswith("motor_"):
        try:
            return int(joint[len("motor_"):])
        except ValueError:
            return None
    return None


def default_assignments(motor_ids: list[int],
                        keep: dict[int, int] | None = None) -> list[tuple[int, int]]:
    """``(bus id, number)`` pairs: ids that already have a number keep it,
    the rest take the lowest free numbers in id order."""
    keep = {int(k): int(v) for k, v in (keep or {}).items()}
    taken = {keep[m] for m in motor_ids if m in keep}
    out: list[tuple[int, int]] = []
    free = 1
    for motor_id in sorted(int(m) for m in motor_ids):
        if motor_id in keep:
            out.append((motor_id, keep[motor_id]))
            continue
        while free in taken:
            free += 1
        taken.add(free)
        out.append((motor_id, free))
    return sorted(out, key=lambda pair: pair[1])


def assignments_of(config) -> dict[int, int]:
    """``{bus id: number}`` as the config in force has it."""
    out: dict[int, int] = {}
    for joint, motor_id in (getattr(config, "joint_to_motor_map", None) or {}).items():
        number = number_of_joint(str(joint))
        if number is not None:
            out[int(motor_id)] = number
    return out


def _motor_block(assignments: list[tuple[int, int]]) -> dict:
    """Config keys for a motor set: ordered by number, joints named by it."""
    ordered = sorted(((int(m), int(n)) for m, n in assignments), key=lambda p: p[1])
    joints = [joint_for_number(n) for _, n in ordered]
    return {
        "motor_ids": [m for m, _ in ordered],
        "joint_ids": joints,
        "joint_to_motor_map": {j: m for j, (m, _) in zip(joints, ordered)},
        "joint_roms": {j: list(_NOMINAL_ROM) for j in joints},
        "neutral_position": {},
    }


def _fresh_config(motor_ids: list[int]) -> dict:
    config = {
        # Same servos as the hand; pinning the family skips the probe sweep.
        "motor_type": "dynamixel",
        "port": "auto",
        "max_current": 300,
        "calibration_current": 200,
        "control_mode": "current_based_position",
    }
    config.update(_motor_block(default_assignments(motor_ids)))
    return config


def parse_motor_ids(text: str) -> list[int]:
    ids: list[int] = []
    for part in text.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            value = int(part)
        except ValueError:
            raise ValueError(f"motor id {part!r} is not an integer")
        if not 0 <= value <= 252:
            raise ValueError(f"motor id {value} is outside the bus range 0..252")
        if value in ids:
            raise ValueError(f"motor id {value} is listed twice")
        ids.append(value)
    if not ids:
        raise ValueError("no motor ids given")
    return ids


def rewrite_bench_motors(config_path: str,
                         assignments: list[tuple[int, int]]) -> None:
    """Replace the motor block of an existing bench config in place with
    ``(bus id, number)`` pairs, keeping everything else (port, baud rate,
    current ceiling, user edits)."""
    with open(config_path) as f:
        config = yaml.safe_load(f) or {}
    config.update(_motor_block(assignments))
    with open(config_path, "w") as f:
        yaml.safe_dump(config, f, sort_keys=False)


def materialize_bench_model(motor_ids: list[int] | None = None, *,
                            root: str | None = None,
                            mock: bool = False) -> str:
    """Write (or update) the bench config and return its ``config.yaml`` path.

    An existing file keeps everything orca_core persisted into it (port, baud
    rate) and anything the user edited; only the motor block is replaced, and
    only when ``motor_ids`` is given. Mock runs get a throwaway copy so a
    simulated session never touches the real bench's remembered port.
    """
    if mock:
        root = tempfile.mkdtemp(prefix="orca_ui_bench_mock_")
    model_dir = bench_model_dir(root)
    os.makedirs(model_dir, exist_ok=True)
    config_path = os.path.join(model_dir, "config.yaml")
    calibration_path = os.path.join(model_dir, "calibration.yaml")

    existing: dict = {}
    if os.path.isfile(config_path):
        with open(config_path) as f:
            existing = yaml.safe_load(f) or {}

    if existing and motor_ids is None:
        config = existing
    elif existing:
        config = dict(existing)
        keep = {int(m): number_of_joint(str(j)) for j, m in
                (existing.get("joint_to_motor_map") or {}).items()}
        keep = {m: n for m, n in keep.items() if n is not None}
        config.update(_motor_block(default_assignments(list(motor_ids), keep)))
    else:
        config = _fresh_config(list(motor_ids or DEFAULT_BENCH_MOTORS))
    if mock:
        config["port"] = "mock"

    with open(config_path, "w") as f:
        yaml.safe_dump(config, f, sort_keys=False)
    if not os.path.isfile(calibration_path):
        with open(calibration_path, "w") as f:
            f.write("calibrated: false\n")
    return config_path


# ----- command line ------------------------------------------------------------


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="orca-bench",
        description="ORCA Motor Bench: hold, jog, range and cycle a few hand "
                    "motors on a bus, with live motor statistics. Runs the "
                    "console's motor stack; opens its own compact page.",
    )
    parser.add_argument("--motors", type=str, default=None, metavar="IDS",
                        help="Motor ids on the bus, comma-separated (default "
                             "1,2 on first use; later runs keep the saved set, "
                             "which the page's bus scan can also update).")
    parser.add_argument("--config", type=str, default=None,
                        help="Run over another config.yaml instead of the bench's "
                             "own (a hand's, say — its calibrated motors are then "
                             "kept inside their calibrated travel).")
    parser.add_argument("--board", type=str, default=None, metavar="DEVICE",
                        help="Pin the bench to one adapter by device path when "
                             "several are plugged in.")
    parser.add_argument("--mock", action="store_true",
                        help="Simulate the bench in memory; no hardware needed.")
    parser.add_argument("--host", type=str, default="0.0.0.0",
                        help="Bind address (default: 0.0.0.0). The page moves "
                             "motors: bind 127.0.0.1 on untrusted networks.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help=f"HTTP port (default: {DEFAULT_PORT}, so a console "
                             "on 5001 can stay open).")
    parser.add_argument("--no-browser", action="store_true",
                        help="Don't open a browser window on startup.")
    parser.add_argument("--library-dir", type=str, default=None,
                        help="Pose/trajectory library root (default "
                             "~/.orca_ui/library); unused by the bench page.")
    return parser.parse_args(argv)


def build_settings(argv=None) -> UiSettings:
    args = parse_args(argv)
    if args.config:
        config_path = args.config
        if os.path.isdir(config_path):
            config_path = os.path.join(config_path, "config.yaml")
        if not os.path.isfile(config_path):
            raise SystemExit(f"Config not found: {config_path}")
        config_path = os.path.abspath(config_path)
    else:
        motor_ids = None
        if args.motors:
            try:
                motor_ids = parse_motor_ids(args.motors)
            except ValueError as e:
                raise SystemExit(f"--motors: {e}")
        config_path = materialize_bench_model(motor_ids, mock=args.mock)
    return UiSettings(
        config_path=config_path,
        model_pinned=True,
        board=None if args.mock else args.board,
        mock=args.mock,
        bench=True,
        host=args.host,
        port=args.port,
        open_browser=not args.no_browser,
        library_dir=args.library_dir,
        # No hand, no glove: the teleop subsystem has nothing to drive here.
        teleop_enabled=False,
    )


def main(argv=None) -> None:
    from orca_ui.cli import run_server

    settings = build_settings(argv)
    mode = "MOCK — simulated bench" if settings.mock else "hardware"
    run_server(settings, product=BENCH_PRODUCT, mode=mode)


if __name__ == "__main__":
    main()


# ----- finding the motors by itself ---------------------------------------------


class BenchAutoAdopt(threading.Thread):
    """While the bench has nothing to connect to, scan the bus and adopt
    whatever answers.

    The bench config can only guess at motor IDs, and the motors can carry
    any. Rather than sit in "searching" until someone presses Scan, this
    waits a few seconds of fruitless detection, runs the ordinary ``bus_scan``
    operation through the operation manager (so it shows up on the page like
    a manual scan and obeys the same locks), and if the answer is a clean set
    that differs from the config, adopts it exactly as the page's button
    would. Then the connect ladder gets its turn. Backs off between attempts
    so an unpowered bench is polled, not hammered; never runs over an
    operator's operation, a non-bench config, or a deliberate disconnect.
    """

    IDLE_BEFORE_SCAN_S = 4.0
    RETRY_S = 20.0
    POLL_S = 1.0

    def __init__(self, service):
        super().__init__(name="BenchAutoAdopt", daemon=True)
        self._service = service
        self._stop = threading.Event()
        self._detecting_since: float | None = None
        self._last_scan = float("-inf")

    def shutdown(self) -> None:
        self._stop.set()

    def run(self) -> None:
        while not self._stop.wait(self.POLL_S):
            try:
                self._tick()
            except Exception:
                logger.exception("bench auto-scan failed")

    def _tick(self) -> None:
        import time

        from orca_ui.hand.states import ControlSource

        status = self._service.status()
        state = status.get("state")
        if state != "detecting" or status.get("released"):
            self._detecting_since = None
            return
        now = time.monotonic()
        if self._detecting_since is None:
            self._detecting_since = now
        if now - self._detecting_since < self.IDLE_BEFORE_SCAN_S:
            return
        if now - self._last_scan < self.RETRY_S:
            return
        manager = self._service.operation_manager
        config = self._service.supervisor.config
        if (manager is None or manager.active()
                or self._service.control_source != ControlSource.MANUAL
                or not is_bench_config(config)):
            return
        self._last_scan = now
        try:
            snapshot = manager.start("bus_scan", {})
        except Exception as e:
            logger.info("bench auto-scan not started: %s", e)
            return
        run_id = snapshot.get("run_id")
        logger.info("bench: nothing connected — scanning the bus for motors")
        while not self._stop.wait(0.2):
            current = manager.snapshot() or {}
            if current.get("run_id") != run_id or current.get("state") in ("done", "error"):
                break
        result = (manager.snapshot() or {}).get("result") or {}
        ids = sorted(int(m) for m in result.get("motor_ids") or [])
        self._detecting_since = None
        if not ids or result.get("mixed_baud"):
            return
        if ids == sorted(int(m) for m in config.motor_ids):
            return
        try:
            # Bare ids: motors already numbered keep their number, newcomers
            # take the lowest free ones.
            self._service.set_bench_motors(ids)
            logger.info("bench: adopted motors %s from the bus", ids)
        except Exception as e:
            logger.info("bench: could not adopt %s: %s", ids, e)
