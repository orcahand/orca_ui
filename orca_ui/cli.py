"""Command-line entry point: resolve the hand config, start the server.

Config resolution happens here, once, so the rest of the app only ever sees a
concrete ``config.yaml`` path via :class:`~orca_ui.settings.UiSettings`.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from orca_ui.settings import UiSettings


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="orca-ui",
        description="Web UI for the ORCA Hand: sensor visualization, motor "
                    "control, and a 3D hand view.",
    )
    parser.add_argument("--config", type=str, default=None,
                        help="Path to a hand config.yaml (or the folder containing "
                             "it). Overrides --model/--side. The hand's capabilities "
                             "(motors / tactile / joint encoders) are read from it.")
    parser.add_argument("--model", type=str, default=None,
                        help="Name of an orca_core bundled model, e.g. "
                             "orcahand-full-right (default: orca_core's default model).")
    parser.add_argument("--model-version", type=str, default=None,
                        help="Bundled model version, e.g. v2 (default: orca_core's "
                             "latest).")
    parser.add_argument("--side", choices=["right", "left"], default=None,
                        help="Shorthand for --model orcahand-<side>.")
    parser.add_argument("--board", type=str, default=None, metavar="DEVICE",
                        help="Pin the console to one board by device path "
                             "(e.g. /dev/cu.usbmodemXXXX — its motor CDC, or a "
                             "legacy motor adapter). Default: connect to the "
                             "first board that answers. Pin it when running "
                             "one console per hand on the same machine, so "
                             "each keeps to its own board; also changeable "
                             "from the header picker while running. With "
                             "--bare, this is the one bus that gets scanned.")
    parser.add_argument("--mock", action="store_true",
                        help="Simulate the hand in-memory (motors, joint encoders, "
                             "tactile sine signals). No hardware needed. Without "
                             "--config/--model this uses the bundled full-featured "
                             "mock model.")
    parser.add_argument("--bare", action="store_true",
                        help="Bare motor mode: scan every motor bus for whatever "
                             "motors answer and bring one bus up for per-motor "
                             "control, ID/baud programming and testing. For "
                             "loose motors on a bench — no hand, no joints, no "
                             "calibration, no sensing.")
    parser.add_argument("--scan-all", action="store_true",
                        help="With --bare, sweep every motor ID (0-253) and "
                             "every baud rate up to 1M instead of the default "
                             "IDs 0-25 at 1M. Minutes rather than seconds on "
                             "Feetech, whose protocol cannot broadcast a ping.")
    parser.add_argument("--no-feedback", action="store_true",
                        help="Do not engage the closed-loop joint-feedback "
                             "controller even if the config enables it (sliders "
                             "drive motors open-loop).")
    parser.add_argument("--no-motors", action="store_true",
                        help="Skip the motor bus entirely and connect sensors "
                             "only (tactile / joint-encoder viewing, no control). "
                             "Useful when motors are unpowered or the motor "
                             "stack is being worked on.")
    parser.add_argument("--host", type=str, default="127.0.0.1",
                        help="Bind address (default: 127.0.0.1). This UI can move "
                             "motors, so exposing it on the LAN is opt-in via "
                             "--host 0.0.0.0.")
    parser.add_argument("--port", type=int, default=5001,
                        help="HTTP port (default: 5001).")
    parser.add_argument("--no-browser", action="store_true",
                        help="Don't automatically open a browser window on startup.")
    parser.add_argument("--fast-hz", type=float, default=60.0,
                        help="Sampling rate for encoder/tactile telemetry "
                             "(in-memory reads; default 60).")
    parser.add_argument("--mid-hz", type=float, default=10.0,
                        help="Sampling rate for the motor-based joint estimate "
                             "(one motor-bus read per tick; lower this if the "
                             "bus complains; default 10).")
    parser.add_argument("--slow-hz", type=float, default=1.0,
                        help="Sampling rate for temps/currents/stats "
                             "(motor-bus reads; default 1).")
    parser.add_argument("--library-dir", type=str, default=None,
                        help="Pose/trajectory library root "
                             "(default ~/.orca_ui/library).")
    parser.add_argument("--teleop-dir", type=str, default=None,
                        help="Path to an orca_teleop checkout; the streamer "
                             "child is launched with `uv run --project <dir>` "
                             "(default: $ORCA_TELEOP_DIR or the sibling "
                             "checkout next to this repo).")
    parser.add_argument("--teleop-cmd", type=str, default=None,
                        help="Explicit command to launch the teleop streamer "
                             "(overrides --teleop-dir).")
    parser.add_argument("--no-teleop", action="store_true",
                        help="Disable the teleoperation subsystem entirely.")
    return parser.parse_args(argv)


def resolve_config_path(args: argparse.Namespace) -> tuple[str, bool]:
    """Turn --config/--model/--side/--mock into a concrete config.yaml path.

    Returns ``(path, pinned)``. ``pinned`` is False when nothing on the
    command line named a model: the path is then only a best guess from
    whatever answered at startup, and the supervisor keeps re-deriving it
    from the hardware for as long as the process runs.
    """
    if args.config:
        # Accept either a config.yaml file or the directory containing it.
        config_path = args.config
        if os.path.isdir(config_path):
            config_path = os.path.join(config_path, "config.yaml")
        if not os.path.isfile(config_path):
            raise SystemExit(f"Config not found: {config_path}")
        return os.path.abspath(config_path), True

    if args.bare:
        # The scan also decides how many buses there are, and the per-bus
        # configs are needed to connect them; carry them on args rather than
        # scanning the hardware a second time to ask again.
        config_path, args.bare_buses = _resolve_bare_config(args)
        return config_path, True

    if args.mock and not (args.model or args.side):
        # Bundled mock model, copied to a tempdir so runtime writes
        # (persisted ports, sensor offsets) never dirty the installed package.
        from orca_ui.mock import materialize_mock_model
        return materialize_mock_model(), True

    model_name = args.model or (f"orcahand-{args.side}" if args.side else None)
    pinned = model_name is not None
    if model_name is None:
        # Plug-and-play: nothing was specified, so ask the connected board which
        # hand it is. detect_hand() degrades to the default model when nothing is
        # plugged in, so this never blocks a headless/no-hardware start — and
        # because the model stays unpinned, the supervisor revises this guess
        # as soon as a board answers.
        try:
            from orca_core.hand_factory import detect_hand
            model_name = detect_hand().model_name
            print(f"No model given — auto-detected {model_name}.", file=sys.stderr)
        except Exception as e:
            print(f"Hand autodetection failed ({e}); using the default model.", file=sys.stderr)
    # Same resolver load_hand() uses, so --model names match orca_core's docs.
    from orca_core.hand_config import _resolve_config_path
    try:
        return _resolve_config_path(
            None, model_version=args.model_version, model_name=model_name), pinned
    except Exception as e:
        raise SystemExit(f"Could not resolve bundled model "
                         f"(model={model_name!r}, version={args.model_version!r}): {e}")


def _resolve_bare_config(args) -> "tuple[str, tuple[str, ...]]":
    """Survey every motor bus and synthesise the configs that describe them.

    Returns ``(config_path, bus_config_paths)``. One populated bus is the
    normal case and gets one config with nothing else to say about it. Several
    get one config each, plus a merged bench view that ``config_path`` points
    at — an ``OrcaHand`` pins a single port, family and rate, so two families
    are two hands behind one session rather than one hand over two buses.

    Fails loudly with what was tried: a bare-mode start that silently fell
    back to a packaged 17-motor model would drive a hand that is not there.
    """
    from orca_core.utils.utils import serial_port_exists
    from orca_ui.hand import bare as bare_mode

    if args.board:
        if not serial_port_exists(args.board):
            raise SystemExit(
                f"--board {args.board} is not a serial port on this machine.")
        ports = [args.board]
    else:
        ports = bare_mode.candidate_ports()
    if not ports:
        raise SystemExit(
            "--bare found no serial adapter. Plug the motor bus in, or name "
            "its device path with --board /dev/cu.usbmodemXXXX.")
    id_range = bare_mode.FULL_ID_RANGE if args.scan_all else bare_mode.DEFAULT_ID_RANGE
    print(f"Scanning {len(ports)} bus(es) for motors "
          f"(IDs {id_range[0]}-{id_range[1]}"
          f"{', every baud rate' if args.scan_all else ', 1M baud'}): "
          f"{', '.join(ports)}...", file=sys.stderr)

    def progress(port: str, motor_type: str, _phase: str, baud: int) -> None:
        print(f"  {port}: {motor_type} @ {baud} baud...", file=sys.stderr)

    survey = bare_mode.survey_buses(ports, id_range=id_range,
                                   all_rates=args.scan_all, progress=progress)
    print(bare_mode.describe_survey(survey), file=sys.stderr)
    populated = survey.populated
    if not populated:
        raise SystemExit(
            "--bare found no motors. Check power and wiring, then retry with "
            "--scan-all to sweep every ID and baud rate."
            if not args.scan_all else
            "--bare found no motors after a full sweep. Check power and wiring.")
    for bus in populated:
        if bus.mixed_baud:
            raise SystemExit(
                f"Motors on {bus.port} answered at more than one baud rate, "
                "which cannot be physically true on a shared line. Scan "
                "again, or power-cycle the bus.")
    clashing = _ids_on_more_than_one_bus(populated)
    if clashing:
        raise SystemExit(
            f"Motor ID(s) {', '.join(str(i) for i in clashing)} answered on "
            "more than one bus. Every command names a motor by ID alone, so "
            "there is no way to say which of them is meant. Give them "
            "distinct IDs, or bring up one bus at a time with --board.")
    bus_paths = tuple(bare_mode.synthesize_config(bus) for bus in populated)
    if len(populated) == 1:
        return bus_paths[0], ()
    print(f"Bringing up {len(populated)} buses as one bench "
          f"({', '.join(bus.motor_type for bus in populated)}).",
          file=sys.stderr)
    return bare_mode.synthesize_merged_config(populated), bus_paths


def _ids_on_more_than_one_bus(buses) -> list[int]:
    """Motor IDs that answered on two buses at once.

    Bare mode routes every command by ID alone, so a duplicate is not a
    degraded case to work around — it is two motors the console cannot tell
    apart, and one of them would silently take the other's commands.
    """
    seen: dict[int, int] = {}
    for bus in buses:
        for motor_id in bus.motor_ids:
            seen[motor_id] = seen.get(motor_id, 0) + 1
    return sorted(mid for mid, count in seen.items() if count > 1)


def build_settings(argv=None) -> UiSettings:
    args = parse_args(argv)
    config_path, model_pinned = resolve_config_path(args)
    return UiSettings(
        config_path=config_path,
        model_pinned=model_pinned,
        model_version=args.model_version,
        board=None if args.mock else args.board,
        mock=args.mock,
        bare=args.bare,
        bare_buses=tuple(getattr(args, "bare_buses", ())),
        engage_feedback=not args.no_feedback,
        motors_enabled=not args.no_motors,
        host=args.host,
        port=args.port,
        open_browser=not args.no_browser,
        fast_hz=args.fast_hz,
        mid_hz=args.mid_hz,
        slow_hz=args.slow_hz,
        library_dir=args.library_dir,
        teleop_enabled=not args.no_teleop,
        teleop_cmd=args.teleop_cmd,
        teleop_dir=args.teleop_dir,
    )


def configure_logging() -> None:
    """WARNING and above on stderr.

    Explicit because the console installs a root-logger handler of its own
    (the bus-error monitor), which would otherwise stop Python from putting
    its default one in place on the first warning.
    """
    logging.basicConfig(level=logging.WARNING)


def main(argv=None) -> None:
    import uvicorn
    from orca_ui.console import install_stdout_dedupe
    from orca_ui.core_source import resolve as resolve_core_source
    from orca_ui.server import create_app

    configure_logging()
    settings = build_settings(argv)

    mode = "MOCK — no hardware" if settings.mock else "hardware"
    if settings.mock is False and not settings.motors_enabled:
        mode += ", sensors only (--no-motors)"
    # Which orca_core is driving the hardware is invisible otherwise: a dev
    # checkout and the release it was cut from carry the same version string.
    core = resolve_core_source()
    rule = "─" * 62
    provisional = "" if settings.model_pinned else "  (re-detected while running)"
    print(f"\n{rule}\n"
          f"  ORCA UI   http://localhost:{settings.port}\n"
          f"  config    {settings.config_path}{provisional}\n"
          f"  mode      {mode}\n"
          f"  core      {core.summary()}\n"
          f"{rule}\n")

    # orca_core prints hardware diagnostics; the connect ladder would repeat
    # them for every tier and retry. First occurrence passes, repeats don't.
    # (Installed after the banner — its rules are identical lines.)
    install_stdout_dedupe()

    app = create_app(settings)

    if settings.open_browser:
        from orca_ui.browser import launch_after_startup
        # Browser targets localhost even when bound wider.
        launch_after_startup(f"http://localhost:{settings.port}")

    # access_log=False: per-request lines (assets, 60 Hz websocket chatter's
    # HTTP siblings) drown the hardware diagnostics that actually matter.
    uvicorn.run(app, host=settings.host, port=settings.port,
                log_level="info", access_log=False)


if __name__ == "__main__":
    main()
