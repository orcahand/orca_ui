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

That installs the pinned `orca_core 0.6.0` release from PyPI. A separate
`orca_core` checkout is not required.

### Assembly guide branch

From an existing `orca_ui` clone:

```bash
git fetch origin
git switch feature/assembly-feedback-touch
git pull --ff-only
uv run orca-ui --mock --host 127.0.0.1 --port 5005
```

Open <http://localhost:5005>, then **Setup → Open assembly guide**.
`uv run` installs the locked dependencies automatically. Python 3.10 or newer
and `uv` are required; Node, a frontend build, and a separate core repository
are not. The built UI, illustrations, videos and model ZIP archives are included.
The first launch extracts the four assembly models and can take longer.

`--mock` runs without hardware, so this guide can run alongside a calibration
UI on a different port. To connect a real hand, omit `--mock` and first
disconnect that hand from any other UI instance.

Working on the console itself, or on `orca_core` alongside it? See
**[DEVELOPMENT.md](DEVELOPMENT.md)** — `./dev` points the console at your own
`orca_core` checkout in one step.

## Usage

```bash
uv run orca-ui                              # ask the hand which model it is
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

Without `--model`/`--side`/`--config`, *which* hand it is stays an open
question too: the side and sensing capabilities are re-read from the boards on
every detection pass, so starting the console before switching the hand on, or
swapping a left hand for a right one while it runs, picks the right model up
instead of holding on to the startup guess. Name a model and that model is
final — nothing detected overrides it.

That re-reading depends on there being an OH board to ask. A hand built on
other electronics — a legacy hand, or any hand whose motor bus is a plain
USB adapter — never answers the handshake, so it resolves to the default
model whatever it actually is: a left hand drives mirrored, a touch hand
shows no taxels. The **model picker** in the header is the fix without a
restart. Pick `orcahand-touch-left`, `orcahand-full-right` or whichever it
really is and the console reconnects on that config; the choice is *pinned*
exactly as `--model` pins it, so detection stops second-guessing it. The
marker beside the picker says which is in force — `AUTO` (following the
hardware) or `PINNED` (following you) — and the first entry in the menu,
*auto-detect from hardware*, hands the choice back.

**Disconnect** in the header closes the session, disables torque and leaves
the serial ports free — the connect ladder stops climbing until **Reconnect**
asks it to. Use it to power the hand down, move a USB cable, or run
orca_core's own scripts against the same bus without closing the console.
Reconnect works in both states: while connected it drops the session and
redials from scratch, and while disconnected it is the way back.

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
  orca_core's record/replay example scripts. A **stress test** cycles any
  set of joints hardstop to hardstop for as many cycles as you ask for and
  reports how much travel each one is still achieving — the number that
  shrinks as a tendon stretches.
- **Teleop** — drive the hand with your own: webcam (MediaPipe), Manus gloves,
  Apple Vision Pro, or a synthetic waveform. Sessions start in **preview**, where
  retargeted poses render as a cyan ghost in the 3D view and the hand never
  moves; **engage** then takes the control channel (manual sliders lock) and
  ramps in from the current pose. Tracking loss holds the last pose and
  auto-disengages after a timeout. See [Teleop](#teleop) below for setup.
- **Setup** — **full setup** leads: (tension → calibrate) × N rounds with a
  confirm gate between them, like orca_core's `scripts/setup.py`, written as
  step-by-step instructions for a hand that has just been built. Under it, the
  same two things on their own — tensioning (wind → hold while you ratchet the
  spools → release) and calibration (all joints, or a picked subset). These take
  the hand into *maintenance*: the session is handed to the operation and
  reconnects automatically afterwards.
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

### Motor testbench (`orca-bench`)

A separate tool for a few of the hand's motors on a bus, with no hand around
them — for tensioning tendons and cycling them until something gives. It is
its own command and its own page, running the console's motor stack:

```bash
uv run orca-bench                   # motors 1 and 2 on the first adapter found
uv run orca-bench --motors 3,7      # a different motor set (remembered)
uv run orca-bench --mock            # simulated bench, no hardware
```

It serves on port 5002 by default, so a console on 5001 can stay open (not on
the same bus: one process owns a port at a time). The bench config lives at
`~/.orca_ui/bench/orca-bench/config.yaml`; the port and baud rate orca_core
resolves on first connect are remembered there, and the file can be edited by
hand (pin `port:` to a device path to skip detection). `--config` runs the
bench page over any other config, a hand's included. Everything is in
motor-shaft degrees — nothing is calibrated and nothing is a joint:

- **Bus.** A folded row naming the bench's motors; it unfolds by itself
  while a scan runs or when a scan found something to decide, and folds
  again once the bench matches the bus.
- **Any motor IDs.** With nothing connected, the bench scans the bus by
  itself after a few seconds and adopts whatever answers, so the motors can
  carry any IDs and `--motors` is only a shortcut. **Scan bus** does the
  same on demand: it pings IDs 0 to 50 at 1 M baud (the hand's rate) and
  lists what answered, by ID, model and rate. Tick the motors to use and give each a
  number — the number is what the bench calls it ("motor 1"), the ID stays
  the servo's, so ID 2 can be motor 1 and ID 4 motor 4 — and **Use … as
  numbered** rewrites the config to that set and reconnects. A scan closes
  the session for its duration (torque off), and a set whose motors answer
  at different baud rates is reported but not adopted.
- **Hold / release, per motor or all.** Hold turns torque on and pins a
  motor where it is; the jog buttons (hold to repeat) then wind its spool in
  small steps. Holding one motor while the other stays released is the
  tensioning posture: wind the free spool by hand against the held one, then
  hold it too. Release lets a spool turn by hand again. A run needs every
  armed motor held.
- **Set A / Set B.** Capture the live shaft position as an endpoint — turn
  the spool there by hand with the motors released, or jog there holding.
  Endpoints are editable and remembered per browser.
- **Cycle, per motor.** Every motor card carries its own definition — speed
  in °/s, dwell at each end, a cycle count or nonstop, `glide` (positions
  streamed at 50 Hz, the way the hand's loop drives a servo) or `step` (one
  command per leg; the motor runs the range at its own speed — the harshest
  setting), and whether to start at A or B. The motors run independently, not
  in lockstep; a motor that reaches its count parks at its start end while the
  others carry on. A defaults row with **Apply to all motors** sets them alike
  when that is what you want.
- **Progress.** Per motor its cycle count, rate and state, the settled
  position at each end and its shortfall against the commanded travel (a cable
  stretching), the mean holding current at each end (a tendon slackening), the
  peak current, the shaft odometer and the temperature; a 30 s strip chart of
  position and current for all motors.
- **Log CSV.** A switch next to Start: on, the run writes every bus sample
  (one row per motor: target, position, velocity, current, temperature,
  cycle count and state) and one row per completed cycle (settled reach,
  span, holding currents, cycle time) to
  `~/.orca_ui/bench/orca-bench/logs/cycle-<date>-<time>-001.csv`. It can be
  flipped while a run goes on; rows are only written while it is on. A long
  run is split into numbered parts, each with its own header, once a part
  reaches the **split at** size (50 MB by default, roughly 300 000 rows), so
  no single file outgrows a spreadsheet. The Progress panel links every part
  for download, and `GET /api/bench/logs/{name}` serves them.

Torque must be on before a run starts, the current ceiling applies, and the
E-stop ends the run and drops torque, exactly as in the console. The full
console is one click away at `/console` on the same backend; a calibrated
hand motor cycled from the bench page is refused any range outside its
calibrated travel.

### Endurance reports

Every endurance test gets a self-contained HTML report — findings, timeline,
pose repeatability, holding current, calibration checkpoints, fingertip
force, joint usage, event log — built from the console's own records. It is
built automatically when a test stops and on demand from the **Report**
button on the Stats page's Endurance panel (**Open report** shows the last
one). Files live next to the samples, `endurance/reports/<name>.html` in the
hand's config directory, and are served at
`/api/endurance/tests/{id}/report.html`; `POST …/report` rebuilds one. The
Slack side (announcements, `/endurance` commands, the report landing in the
channel) is a separate bot in the `orca_slack` repo that talks to this API.

The same page can be built without a console from the files the Stats page
downloads (`endurance.json`, `endurance-<label>-samples.csv`, `config.yaml`,
`calibration_history.jsonl`, `joint_usage.json`):

```bash
uv run python -m orca_ui.hand.endurance_report ~/Downloads out.html
```

and such a download can be merged into a hand's config directory, so the
console lists, serves and rebuilds that test like one it recorded itself
(stop the console on that directory first):

```bash
uv run python -m orca_ui.hand.endurance_report import ~/Downloads ~/.orca_ui/my-hand
```

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
the guided full setup) and PID gain tuning are not exposed.

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
