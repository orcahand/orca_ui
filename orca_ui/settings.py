"""Resolved runtime settings shared by the CLI, server, and hand service."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UiSettings:
    """Everything the server needs to run, resolved once by the CLI.

    ``config_path`` always points at a concrete ``config.yaml`` (the CLI
    resolves ``--config``/``--model``/``--side``/``--mock`` down to a file
    before the server starts).
    """

    config_path: str
    # False only when nothing on the command line named a model, i.e.
    # ``config_path`` is a guess from whatever was plugged in at startup. The
    # supervisor then keeps re-deriving the model from the hardware, so a hand
    # that was off (or a different hand entirely) is picked up later.
    # ``model_version`` is carried along so re-derivation stays on the version
    # the user asked for.
    model_pinned: bool = True
    model_version: str | None = None
    # Device path of the board this console is pinned to, or None for "first
    # board to answer". Pinning is what makes two consoles on one machine
    # deterministic: a pinned supervisor never opens another board's ports.
    board: str | None = None
    mock: bool = False
    # Bare motor mode: loose motors on a bench, not a hand. The config is
    # synthesised from a bus scan, so detection and the connect ladder are
    # skipped entirely and the session is motors-only by construction.
    bare: bool = False
    engage_feedback: bool = True
    motors_enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 5001
    open_browser: bool = True
    # Pose/trajectory library root; None -> ~/.orca/ui/library. Recordings and
    # user poses live under <root>/<model_name>/.
    library_dir: str | None = None

    # Browser-facing stream rates (Hz). Producers run at hardware rates; the
    # broadcaster decimates to these. Tunable for slow machines / debugging.
    fast_hz: float = 60.0
    mid_hz: float = 10.0
    slow_hz: float = 1.0

    # App sessions (orca_ui/hand/app), e.g. orca_teleop and orca_rl. What the
    # console remembers per app lives in apps_dir; None -> ~/.orca/ui/apps.
    apps_enabled: bool = True
    apps_dir: str | None = None
    app_ramp_s: float = 2.0             # engage ramp-in duration
    app_hold_after_ms: int = 250        # no targets this long -> hold the pose
    app_disengage_after_s: float = 10.0  # held this long -> auto-disengage (0 = never)
    app_browser_grace_s: float = 2.0    # no browser tab this long -> disengage (0 = never)
