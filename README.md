# ORCA Hand Console

Web interface for the [ORCA Hand](https://www.orcahand.com): live sensor
visualization (tactile taxels + joint encoders), motor control, a 3D hand
view, pose/trajectory playback, and the hand's lifecycle operations
(tensioning, calibration, guided setup). Uses
[orca_core](https://github.com/orcahand/orca_core) for all hardware
communication.

The UI adapts to the hand described by the config: tactile-only hands get the
taxel/force views, joint-sensing hands get encoder gauges and the closed-loop
control panel, full hands get everything.

## Installation

This project uses [uv](https://docs.astral.sh/uv/).

```bash
uv sync
```

That installs the released `orca_core` from PyPI.

Working on the console itself, or on `orca_core` alongside it? See
**[DEVELOPMENT.md](DEVELOPMENT.md)** — `uv run orca-dev` points the console at
your own `orca_core` checkout in one step.

## Usage

```bash
uv run orca-ui                              # orca_core default model
uv run orca-ui --model orcahand-full-right  # bundled model by name
uv run orca-ui --config /path/to/config.yaml   # explicit config (or its folder)
uv run orca-ui --mock                       # full simulated hand, no hardware
```

A browser app window opens automatically and closes when you stop the program
(Ctrl-C); pass `--no-browser` to open `http://localhost:5001` yourself.

The backend probes for hardware continuously: motor bus, tactile sensors, and
joint encoders are discovered by USB id (plus the OH board's `ORCA_ID?`
handshake) and connected at the best achievable tier. Unplugging triggers
reconnection; sensors-only operation (motor power off) works for viewing.
**Torque is never enabled automatically** — use the Enable Torque button in the
Motor Control panel.

The header's red **E-STOP** stops whatever is running (operation, playback,
sweep) and disables torque.

Useful flags: `--no-feedback` (open-loop sliders even on feedback hands),
`--host/--port` (default `127.0.0.1:5001` — this UI can move motors, so LAN
exposure is opt-in), `--model-version`, `--side`, `--library-dir` (pose &
trajectory storage, default `~/.orca_ui/library`).

### Views

- **Dashboard** — tactile taxel grids (magnitude / direction / arrows, with
  zeroing and stream modes), per-finger resultant-force dials, joint-encoder
  ROM bars with target markers and expandable history sparklines, and the
  motor slider panel.
- **3D View** — the hand posed live from the joint encoders, with tactile
  force arrows rendered in the real sensor frames (orca_core's mesh-registered
  sensor mounts). An optional translucent ghost overlays the naive
  motor-based estimate, and joint rings glow with tracking error.
- **Poses** — preset pose buttons, orca_core demo sequences, and trajectory
  record/replay. Record waypoints or continuous (≤60 Hz) joint streams by
  physically posing the hand (torque drops and stays off), then replay at
  ×0.5/×1/×2 with looping. Trajectory YAMLs are interchangeable with
  orca_core's record/replay example scripts.
- **Teleop** — drive the hand with your own: webcam (MediaPipe), Manus gloves,
  Apple Vision Pro, or a synthetic waveform. Sessions start in **preview**, where
  retargeted poses render as a cyan ghost in the 3D view and the hand never
  moves; **engage** then takes the control channel (manual sliders lock) and
  ramps in from the current pose. Tracking loss holds the last pose and
  auto-disengages after a timeout. See [Teleop](#teleop) below for setup.
- **Setup** — tensioning (wind → hold while you ratchet the spools → release),
  calibration (all joints, or expand to select fingers/joints), and the guided
  setup wizard ((tension → calibrate) × N rounds, like orca_core's
  `scripts/setup.py`). These take the hand into *maintenance*: the session is
  handed to the operation and reconnects automatically afterwards.
- **Motors** — per-motor temps/currents, PI tuning and loop stats (feedback
  hands), stream rates, a supervisor event log, and a manual reconnect. The
  **motor chain** panel does assembly-time motor ID'ing (orca_core's
  `configure_motor_chain` workflow) with a live per-motor visualization, and
  works with no hand connected. Dynamixel only for now; Feetech chains still
  use the CLI script.

A transport bar appears under the header while anything long-running is active
(calibration, tensioning, playback, recording, a teleop session) — progress,
prompts (e.g. tension's Release), engage/disengage, and stop work from every
tab.

### Teleop

The retargeting pipeline runs as a separate `orca_teleop` process, spawned via
`uv run --project ../orca_teleop`, or launched manually/remotely in *external*
mode with a session token. `--teleop-dir` points at an orca_teleop checkout
(default: `$ORCA_TELEOP_DIR` or the sibling `../orca_teleop`), `--teleop-cmd`
overrides the launch command entirely, and `--no-teleop` disables the
subsystem. The retargeter's URDF resolves from the sibling
`../orcahand_description` checkout.

Without hardware: `uv run orca-ui --mock`, then either pick the *synthetic*
source in the Teleop tab or run `uv run python
scripts/dev_teleop_synthetic.py` for an external-mode session.

### Mock mode

`--mock` runs the full production stack (real tactile/encoder clients, real PI
loop) over in-memory serial links: taxels stream sine waves and the joint loop
genuinely converges on slider targets. Useful for UI development, demos, and
CI. Mock mode also adds a joint-sweep tool in the 3D view for verifying the
model calibration.

## MCP server

`orca-ui-mcp` exposes the running console to MCP clients (Claude Code, etc.)
so AI agents can operate the hand: read telemetry, command poses, run
operations, debug. It is a pure HTTP/WebSocket client of the backend — the
same API the browser uses — so agents and the browser coexist under the same
arbitration (control ownership, torque gates, e-stop), and the backend stays
the single owner of the hardware.

Start the backend first, then the MCP server:

```bash
uv run orca-ui --mock --no-browser   # or `uv run orca-ui` for hardware
uv run orca-ui-mcp                   # stdio; started automatically by clients
```

Claude Code picks up `.mcp.json` in this repo automatically; elsewhere,
register with `claude mcp add orca-hand -- uv run orca-ui-mcp`. The MCP server
boots fine with no backend running — tools return a "backend not reachable"
hint until it is up. Flags: `--url` (or `ORCA_UI_URL`, default
`http://127.0.0.1:5001`), `--timeout`, `--read-only` (observation tools plus
e-stop only), `--require-mock` (refuse mutations unless the backend reports a
mock hand — for unattended runs).

The tools cover status and telemetry reads, connection and safety, motion,
library writes, operations, tactile configuration, and teleop. Run `/mcp` in
Claude Code for the live catalog. Assembly-time tools (chain configuration,
the setup wizard) and PID gain tuning are not exposed.

Safety model: motion needs torque explicitly enabled; nothing enables it
implicitly. On real hardware the first torque enable, maintenance operations
(calibrate/tension), teleop engage, and current-limit raises require a
`confirm` argument — against `--mock` the gates are inactive, so develop
there. De-escalation (e-stop, torque off, `orca_park`, stop/disengage) is
never gated.

## Development

Running the console from source, working against an unreleased `orca_core`,
rebuilding the frontend or the 3D asset bundle, and releasing are all covered
in **[DEVELOPMENT.md](DEVELOPMENT.md)**.
