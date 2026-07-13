"""Command-line entry point: resolve the hand config, start the server.

Config resolution happens here, once, so the rest of the app only ever sees a
concrete ``config.yaml`` path via :class:`~orca_ui.settings.UiSettings`.
"""

from __future__ import annotations

import argparse
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
    parser.add_argument("--mock", action="store_true",
                        help="Simulate the hand in-memory (motors, joint encoders, "
                             "tactile sine signals). No hardware needed. Without "
                             "--config/--model this uses the bundled full-featured "
                             "mock model.")
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


def resolve_config_path(args: argparse.Namespace) -> str:
    """Turn --config/--model/--side/--mock into a concrete config.yaml path."""
    if args.config:
        # Accept either a config.yaml file or the directory containing it.
        config_path = args.config
        if os.path.isdir(config_path):
            config_path = os.path.join(config_path, "config.yaml")
        if not os.path.isfile(config_path):
            raise SystemExit(f"Config not found: {config_path}")
        return os.path.abspath(config_path)

    if args.mock and not (args.model or args.side):
        # Bundled mock model, copied to a tempdir so runtime writes
        # (persisted ports, sensor offsets) never dirty the installed package.
        from orca_ui.mock import materialize_mock_model
        return materialize_mock_model()

    model_name = args.model or (f"orcahand-{args.side}" if args.side else None)
    if model_name is None:
        # Plug-and-play: nothing was specified, so ask the connected board which
        # hand it is. detect_hand() degrades to the default model when nothing is
        # plugged in, so this never blocks a headless/no-hardware start.
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
            None, model_version=args.model_version, model_name=model_name)
    except Exception as e:
        raise SystemExit(f"Could not resolve bundled model "
                         f"(model={model_name!r}, version={args.model_version!r}): {e}")


def build_settings(argv=None) -> UiSettings:
    args = parse_args(argv)
    return UiSettings(
        config_path=resolve_config_path(args),
        mock=args.mock,
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


def main(argv=None) -> None:
    import uvicorn
    from orca_ui.console import install_stdout_dedupe
    from orca_ui.server import create_app

    settings = build_settings(argv)

    mode = "MOCK — no hardware" if settings.mock else "hardware"
    if settings.mock is False and not settings.motors_enabled:
        mode += ", sensors only (--no-motors)"
    rule = "─" * 62
    print(f"\n{rule}\n"
          f"  ORCA UI   http://localhost:{settings.port}\n"
          f"  config    {settings.config_path}\n"
          f"  mode      {mode}\n"
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
