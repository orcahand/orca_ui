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
    mock: bool = False
    engage_feedback: bool = True
    motors_enabled: bool = True
    # 0.0.0.0: reachable from the network (LAN, Tailscale). The UI can move
    # motors — bind 127.0.0.1 on untrusted networks.
    host: str = "0.0.0.0"
    port: int = 5001
    open_browser: bool = True
    # Pose/trajectory library root; None -> ~/.orca_ui/library. Recordings and
    # user poses live under <root>/<model_name>/.
    library_dir: str | None = None

    # Browser-facing stream rates (Hz). Producers run at hardware rates; the
    # broadcaster decimates to these. Tunable for slow machines / debugging.
    fast_hz: float = 60.0
    mid_hz: float = 10.0
    slow_hz: float = 1.0

    # Teleoperation. The streamer child runs in the orca_teleop env, launched
    # via teleop_cmd (explicit command) or `uv run --project <teleop_dir>`
    # (teleop_dir / $ORCA_TELEOP_DIR / auto-detected sibling checkout).
    teleop_enabled: bool = True
    teleop_cmd: str | None = None
    teleop_dir: str | None = None
    # orcahand_description checkout for the retargeter's URDF; None ->
    # auto-detect the sibling checkout, exported as ORCAHAND_DESCRIPTION_DIR.
    teleop_urdf_dir: str | None = None
    teleop_ramp_s: float = 2.0             # engage ramp-in duration
    teleop_hold_after_ms: int = 250        # target silence -> tracking lost
    teleop_disengage_after_s: float = 10.0  # lost this long -> auto-disengage (0 = never)
