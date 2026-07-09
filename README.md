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
derives `joint_calibration.yaml` (per-joint `{sign, offset_deg}` corrections
between orca_core angles and the URDF). Verify corrections with the mock
sweep tool joint by joint, then set `verified: true` — rebuilds never
overwrite verified entries. The calibration file is re-read per request, so
edit → refresh iterates in seconds.

## Releasing

```bash
cd frontend && npm run build && cd ..
uv build
```

The wheel force-includes the gitignored `orca_ui/webui` build output.
