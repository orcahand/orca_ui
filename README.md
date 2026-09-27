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
trajectory storage, default `~/.orca_ui/library`), `--slack-webhook` (see
[Slack notifications](#slack-notifications)).

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

### Slack notifications

A long endurance test is watched from Slack rather than from the Stats page.
Create an [Incoming Webhook](https://api.slack.com/messaging/webhooks) for the
channel that should hear about it, hand the console its URL through the
environment, and start as usual:

```bash
export ORCA_UI_SLACK_WEBHOOK='https://hooks.slack.com/services/T000/B000/xxxx'
export ORCA_UI_SLACK_MENTION='<!here>'      # optional: who to ping on alerts
uv run orca-ui --config ~/.orca_ui/my-hand
```

The URL is a secret: keep it in the environment (or a shell profile the
console machine reads), not on the command line, where `ps` shows it to
everyone on the box. A `slack` line in the startup banner confirms it was
picked up, and the first message — *console up* — confirms the webhook
works.

From then on every endurance test posts, to that one channel:

- **Start, stop, notes.** The stop message carries the digest: events (and
  how many were bad), runs, checkpoints, each motor's holding current at the
  hold against its first-hour mean, each joint's motor travel against the
  first calibration checkpoint, what is still in a bad state, and a link to
  the raw samples CSV.
- **Timeline events** — an operation starting or finishing, torque dropping,
  a motor latching a hardware error, a fingertip freezing or dropping out, a
  link going down, and each recovery. The first event after a quiet minute
  posts at once; anything that follows within that minute is folded into one
  message, so a flapping sensor costs one post a minute, not one a second.
- **Calibration checkpoints** — motor travel per joint with the change since
  the test's first checkpoint, plus any problems the run flagged.
- **A digest every hour** while a test is running (`--slack-heartbeat 2` for
  every two hours, `0` for none), and on demand from the **Slack** button on
  the Stats page's Endurance panel.

Messages that mention an alert — a fault latch, a sensor dropping out, a
calibration that did not complete — are prefixed with `ORCA_UI_SLACK_MENTION`
(`--slack-mention`): `<!channel>`, `<!here>` or a user id such as
`<@U0123ABC>`.

Delivery runs on one background thread with a bounded queue and never
touches the hand's threads: a Slack outage costs nothing but the messages
that were queued during it, and the next successful post says how many were
dropped. Nothing is written to disk.

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
