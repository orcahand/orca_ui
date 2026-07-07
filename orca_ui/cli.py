"""Command-line entry point: resolve the hand config, start the server.

Config resolution happens here, once, so the rest of the app only ever sees a
concrete ``config.yaml`` path via :class:`~orca_ui.settings.UiSettings`.
"""

from __future__ import annotations

import argparse
import os

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
        host=args.host,
        port=args.port,
        open_browser=not args.no_browser,
        fast_hz=args.fast_hz,
        mid_hz=args.mid_hz,
        slow_hz=args.slow_hz,
    )


def main(argv=None) -> None:
    import uvicorn
    from orca_ui.server import create_app

    settings = build_settings(argv)
    print(f"ORCA UI · config: {settings.config_path}"
          f"{' · MOCK MODE (no hardware)' if settings.mock else ''}")

    app = create_app(settings)

    if settings.open_browser:
        from orca_ui.browser import launch_after_startup
        # Browser targets localhost even when bound wider.
        launch_after_startup(f"http://localhost:{settings.port}")

    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
