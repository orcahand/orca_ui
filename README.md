# ORCA Hand Console

Web interface for the [ORCA Hand](https://www.orcahand.com): live sensor
visualization (tactile taxels + joint encoders), motor control, a 3D hand
view, pose/trajectory playback, and the hand's lifecycle operations
(tensioning, calibration, guided setup). Uses
[orca_core](https://github.com/orcahand/orca_core) (the
`feature/joint-sensing` line) for all hardware communication.

The UI adapts to the hand described by the config: tactile-only hands get the
taxel/force views, joint-sensing hands get encoder gauges and the closed-loop
control panel, full hands get everything. Hardware is auto-detected and
connected on startup — no connect button.

## Installation

This project uses [uv](https://docs.astral.sh/uv/). During development
`orca_core` tracks a local sibling checkout (`../orca_core`); on machines
without one, switch the `[tool.uv.sources]` entry in `pyproject.toml` to the
git source (instructions in the comment there).

```bash
uv sync
```

The frontend ships pre-built in released wheels. From a git checkout, build it
once (requires node):

```bash
cd frontend && npm install && npm run build && cd ..
```

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
**Torque is never enabled automatically** — use the Motor Control panel's
Enable Torque button (on feedback hands the loop is rebased first so nothing
lurches).

Useful flags: `--no-feedback` (open-loop sliders even on feedback hands),
`--host/--port` (default `127.0.0.1:5001` — this UI can move motors, so LAN
exposure is opt-in), `--model-version`, `--side`, `--library-dir` (pose &
trajectory storage, default `~/.orca_ui/library`).

The header's red **E-STOP** stops whatever is running (operation, playback,
sweep) and disables torque — it never errors, it reports what it actioned.

### Views

- **Dashboard** — tactile taxel grids (magnitude / direction / arrows, zeroing,
  stream modes), per-finger resultant-force dials, joint-encoder ROM bars with
  target markers and expandable history sparklines, and the motor slider panel
  (torque, neutral, per-joint sliders).
- **3D View** — the v2 hand posed live from the joint encoders, an optional
  translucent ghost showing the naive motor-based estimate, joint rings that
  glow with tracking error, and tactile force arrows rendered in the real
  sensor frames (orca_core's mesh-registered sensor mounts): toggle the
  per-finger resultant vector, all per-taxel vectors, or both.
- **Poses** — preset pose buttons (built-ins are ROM-fraction placeholders
  until tuned; capture your own from the live hand), orca_core demo
  sequences, and trajectory record/replay: record waypoints or continuous
  (≤60 Hz) joint streams by physically posing the hand (torque drops and
  stays off), then replay at ×0.5/×1/×2 with looping. Trajectory YAMLs are
  interchangeable with orca_core's record/replay example scripts.
- **Teleop** — drive the hand with your own: webcam (MediaPipe), Manus
  gloves, Apple Vision Pro, or a synthetic waveform (no hardware). The
  retargeting pipeline runs as a separate `orca_teleop` process (spawned via
  `uv run --project ../orca_teleop`, or launched manually/remotely in
  *external* mode with a session token). Sessions start in **preview** —
  retargeted poses render as a cyan ghost in the 3D view and the hand never
  moves — then **engage** takes the control channel (manual sliders lock,
  named owner tooltips) and ramps in from the current pose. Tracking loss
  holds the last pose and auto-disengages after a timeout; E-stop ends the
  whole session. Webcam sessions get a live annotated camera preview
  (landmarks green when the orientation gate passes).
- **Setup** — tensioning (wind → hold while you ratchet the spools →
  release), calibration (all joints, or expand to select fingers/joints;
  progress streamed live; partial runs keep completed steps), and the guided
  setup wizard ((tension → calibrate) × N rounds, like orca_core's
  `scripts/setup.py`). These take the hand into *maintenance*: the session
  is handed to the operation and reconnects automatically afterwards.
- **Motors** — per-motor temps/currents, PI tuning + loop stats (feedback
  hands), stream rates, a supervisor event log, a manual reconnect, and the
  **motor chain** panel: assembly-time motor ID'ing (orca_core's
  `configure_motor_chain` workflow) with a live per-motor chain
  visualization — reachable with no hand connected, since that's when you
  need it. Factory reset sits behind an explicit are-you-sure confirmation
  (a reset means redoing the whole ID'ing process). Dynamixel only for now;
  Feetech chains still use the CLI script.

A transport bar appears under the header while anything long-running is
active (calibration, tensioning, playback, recording, a teleop session) —
progress, prompts (e.g. tension's Release), engage/disengage, and stop work
from every tab.

Teleop flags: `--teleop-dir` points at an orca_teleop checkout (default:
`$ORCA_TELEOP_DIR` or the sibling `../orca_teleop`), `--teleop-cmd` overrides
the launch command entirely, `--no-teleop` disables the subsystem. The
retargeter's URDF resolves from the sibling `../orcahand_description`
checkout. Without hardware: `uv run orca-ui --mock`, then either pick the
*synthetic* source in the Teleop tab or run
`uv run python scripts/dev_teleop_synthetic.py` for an external-mode session.

### Mock mode

`--mock` runs the full production stack (real tactile/encoder clients, real
PI loop) over in-memory serial links: taxels stream sine waves and the joint
loop genuinely converges on slider targets. Useful for UI development, demos,
and CI. Mock mode adds a joint-sweep tool in the 3D view for verifying the
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
register with `claude mcp add orca-hand -- uv run orca-ui-mcp`. The MCP
server boots fine with no backend running — tools return a "backend not
reachable" hint until it is up. Flags: `--url` (or `ORCA_UI_URL`, default
`http://127.0.0.1:5001`), `--timeout`, `--read-only` (observation tools plus
e-stop only), `--require-mock` (refuse mutations unless the backend reports a
mock hand — for unattended runs).

22 tools, grouped: status/telemetry reads (`orca_get_status`,
`orca_get_hand_info`, `orca_read_telemetry`, `orca_get_camera_preview`,
`orca_list_library`, `orca_get_operation`), connection & safety
(`orca_estop`, `orca_reconnect`, `orca_set_torque`, `orca_set_max_current`,
`orca_park`), motion (`orca_set_joints` — ROM-clamped, convergence-verified;
`orca_apply_pose`), library writes (`orca_save_pose`, `orca_delete_asset`),
operations (`orca_start_operation`, `orca_control_operation`,
`orca_send_operation_input`), tactile (`orca_configure_tactile`), and teleop
(`orca_teleop_start`, `orca_teleop_engage`, `orca_teleop_stop`). Run `/mcp`
in Claude Code to inspect the live catalog.

Safety model: motion needs torque explicitly enabled; nothing enables it
implicitly. On real hardware the first torque enable, maintenance operations
(calibrate/tension), teleop engage, and current-limit raises require a
`confirm` argument — against `--mock` the gates are inactive, so develop
there. De-escalation (e-stop, torque off, `orca_park`, stop/disengage) is
never gated. Assembly-time tools (`configure_chain`, `wizard`) and PID gain
tuning are deliberately not exposed.

## Development

```bash
uv run orca-ui --mock --no-browser        # backend on :5001
cd frontend && npm run dev                 # Vite dev server on :5173, proxied
```

Tests: `uv run pytest tests/`. The frontend has a headless URDF check:
`cd frontend && node scripts/check-urdf.mjs`.

### 3D asset bundle

`orca_ui/models/hand_v2/` is generated from the `orcahand_description` repo by

```bash
uv run --group assets python scripts/build_hand_bundle.py
```

which renames the Fusion-exported URDF joints to orca_core canonical ids,
decimates the meshes to browser-friendly GLBs, adds fingertip frames, and
prints a per-joint ROM report cross-checking the URDF limits against
orca_core's ROMs (orca_core degrees map onto the URDF 1:1 — there is no
per-joint correction table). Verify joint directions with the mock sweep
tool, one joint at a time.

## Releasing

```bash
cd frontend && npm run build && cd ..
uv build
```

The wheel force-includes the gitignored `orca_ui/webui` build output.
