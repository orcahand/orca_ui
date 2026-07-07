# ORCA UI

Web interface for the [ORCA Hand](https://www.orcahand.com): live sensor
visualization (tactile taxels + joint encoders), motor control, and a 3D hand
view. Uses [orca_core](https://github.com/orcahand/orca_core) (the
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
exposure is opt-in), `--model-version`, `--side`.

### Views

- **Dashboard** — tactile taxel grids (magnitude / direction / arrows, zeroing,
  stream modes), per-finger resultant-force dials, joint-encoder ROM bars with
  target markers and expandable history sparklines, and the motor slider panel
  (torque, neutral, per-joint sliders, PI tuning + rebase on feedback hands).
- **3D View** — the v2 hand posed live from the joint encoders, an optional
  translucent ghost showing the naive motor-based estimate, joint rings that
  glow with tracking error, and fingertip force arrows (resultant mode; the
  per-taxel mode activates once sensor→fingertip transforms land in
  orca_core).

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
