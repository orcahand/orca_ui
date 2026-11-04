# ORCA Hand Console

> ## ⚠️ Experimental branch: `merge/assembly-calibration-with-main`
>
> This branch combines the assembly guide, the new tensioning and calibration, and the fixes on `main`. It is
> unreleased and only lightly tested, and it will be replaced by a release on `main`. See
> [Using this experimental branch](#using-this-experimental-branch).

## Welcome to ORCA UI!
Orca Ui is the web based user-interface for the [ORCA Hand](https://www.orcahand.com), it offers: 
 1. Helpful and guided/automated setup and maintenance procedures for you ORCA Hand
 2. Pose and trajectory capture, visualization, and playback.
 3. Detailed tunable parameters for each joint, study how each affects your trajectory!
 4. Live sensor and 3D hand visualization.
 5. Coming soon, simple data collection interface, select exactly the data you need and where to write it to.

Uses
[orca_core](https://github.com/orcahand/orca_core) for all hardware
communication.

The UI adapts to the hand described by the config: tactile-only hands get the
taxel/force views, joint-sensing hands get encoder gauges and the closed-loop
control panel, full hands support everything. 

## Using this experimental branch

The console on this branch runs a matching unreleased `orca_core`, which it installs by itself from [`feature/improve-calibration`](https://github.com/orcahand/orca_core/tree/feature/improve-calibration). You don't need a separate `orca_core` clone.

```bash
git clone --depth 1 --branch merge/assembly-calibration-with-main https://github.com/orcahand/orca_ui.git
cd orca_ui
uv run orca-ui
```

If you already have orca_ui cloned, stash or commit any changes, then run:

```bash
git fetch origin merge/assembly-calibration-with-main:merge/assembly-calibration-with-main
git switch merge/assembly-calibration-with-main
uv run orca-ui
```

- The clone is large because the assembly guide's media is in the repository, and the first start takes a few minutes.
- The header should show **DEV CORE · feature/improve-calibration**. If it doesn't, you aren't running this version.
- If the install stops on a build error, try `uv run --python 3.12 orca-ui`.
- This setup has had a fresh-clone test on a Mac, and hasn't been tried on a Windows clone. Please report any setup
  problem.
- Run `git pull` only when you want to update. This branch will be replaced at the release, and you will need a fresh
  clone of `main` then. Your hand folders stay where they are.

**What's different from `main`**

- **Each hand gets its own folder.** A plain `uv run orca-ui` keeps a hand's config and calibration in
  `~/orca_bench/<serial>/<model>/`, created the first time the hand connects. A hand set up earlier in
  `~/orca_bench/<serial>/` has its files copied in, and the originals stay. A hand that reports no serial uses the
  shared model folder, and the console logs a warning.
- **One hand per run.** Each run stays on the first hand it identifies. To use another hand, press Ctrl+C and start the
  console again.
- **One console per hand.** A second console in another terminal holds the hand, so the one you're looking at can't
  connect. Close the others first.
- **Naming a model or config skips this.** `--config` and `--model` use exactly what you name, with no hand folder and
  no one-hand limit.
- **Tensioning.** Motors pull, settle where they stopped, then hold at each motor's ceiling while you ratchet. The
  default pull is 15°, and **Pull more** adds 15°. The Tensioning current field is gone. Avoid hard pushes on a finger
  while the motors hold, because they may loosen the tendon.
- **Calibration.** Fingers drive onto their stops at each motor's ceiling, so keep your fingers clear and the power
  switch within reach. The calibration current sliders are gone. Manual calibration asks once per step and has **Back**.
- **Slack test and tension sweep.** Currents come from the motor type: 60 mA on Dynamixel and 120 mA on Feetech for the
  slack test, and you can still choose another. Feetech values are provisional. On Feetech a pass can miss small slack,
  so also check the tendons by hand. The sweep can stop short on some joints.
- **Motor faults.** You can reboot one motor with its torque on.
- **Teleoperation.** Point it at the same hand folder, so it reads the calibration you just made:
  `--model_path ~/orca_bench/<serial>/<model>/config.yaml`. Tension first and calibrate last.

To get started with the released console, follow these steps:

## Installation

**Pre-installation steps**

1. **Git clone the orca_ui repository**:
   ```
   #use any preferred method, ssh clone shown here
   git clone git@github.com:orcahand/orca_ui.git
    ```

2. **Install uv (found at: https://docs.astral.sh/uv/getting-started/)**

**Installing the repository**

1. **Path into your cloned orca_ui repository and uv sync**
```bash
cd orca_ui
uv sync
```

Amongst other setup procedures uv sync installs the `orca_core` fixed in `uv.lock`, from GitHub on this experimental branch and from PyPI on `main`. This allows you to utilize the ui WITHOUT using or affecting your local orca repository.

2. IF you wish to run the ui from your local orca_core, rebuild the frontend,
or developing against an unreleased `orca_core` make sure to consult
[DEVELOPMENT.md](DEVELOPMENT.md). Enable the hooks once per clone if you will
be committing:

```bash
git config core.hooksPath .githooks
```

## Usage

```bash
uv run orca-ui                              # autodetects the connected hand
uv run orca-ui --mock                       # full simulated hand, no hardware
uv run orca-ui --help                       # full set of flags you can launch with
```

A browser app window opens automatically and closes when you stop the program
(Ctrl-C); pass `--no-browser` to open `http://localhost:5001` yourself.

The backend probes for hardware continuously upon initialization: motor bus, tactile sensors, and
joint encoders are discovered by USB id (plus the OH board's `ORCA_ID?`
handshake) and connected at the best achievable tier. Unplugging triggers
reconnection; a reconnect/sensor rescan can be triggered manually from the ui

The header's red **E-STOP** button stops whatever is running (operation, playback,
sweep) and disables torque.

### Views

- **Dashboard** — This handy ui will greet you on ui-startup, it will provide
  you with a 3d view of your hand, as well as other visualization panels based
  which sensors were detected. Also a quick evaluation of motor and sensor
  health will allow the quick spotting of any component that was expected to
  respond, but failed to. Additionally, once your hand is calibrated, you can
  use the manual control mode in the dashboard to move and observe each joint.
  
- **3D View** — the 3d model of your ORCA Hand will show up here, and move
  in real time in response to any movements of your physical hand, once
  calibration is complete. Additionally touch hand users can toggle force
  vector views projected onto the 3d model from their tactile sensors.
  
- **Poses** — click through some basic pose presets or record your own
  poses and trajectories and replay them, all in this handy panel.
  
- **Teleop** — Not Fully Implemented! Drive the hand with your own: webcam (MediaPipe), Manus
  gloves, Apple Vision Pro, or a synthetic waveform (no hardware). The
  retargeting pipeline runs as a separate `orca_teleop` process (spawned with
  `uv run --frozen` in the `orca_teleop` checkout, or launched manually/remotely
  in *external* mode with a session token). Sessions start in **preview** —
  retargeted poses render as a cyan ghost in the 3D view and the hand never
  moves — then **engage** takes the control channel (manual sliders lock,
  named owner tooltips) and ramps in from the current pose. Tracking loss
  holds the last pose and auto-disengages after a timeout; E-stop ends the
  whole session. Webcam sessions get a live annotated camera preview
  (landmarks green when the orientation gate passes).
  
- **Setup** — This menu contains all functionality you will need to tension and
  calibrate your ORCA Hand, hardware 2.1 hands additionally support a guided
  tensioning procedure.
  
- **Motors** — This menu will contain live feedback of motor temperatures
  and currents as well as a panel that allows you to tune every minute detail
  of your joints' control loops. Feel free to adjust parameters live while
  a replay from the Poses tab is in effect, allowing you to directly see
  the effect your tuning has on the performed trajectory.

While anything long-running is active (calibration, tensioning, playback, 
recording, a teleop session) a status tab will appear on the ui with 
progress reports, relevant interactive prompts, and stop work from every tab.

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

Running from source, the frontend build, the 3D asset bundle and releasing
are covered in [DEVELOPMENT.md](DEVELOPMENT.md).
