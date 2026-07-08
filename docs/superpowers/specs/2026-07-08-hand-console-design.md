# ORCA Hand Console — operations, poses, setup & IA redesign

**Date:** 2026-07-08
**Status:** approved (brainstorm with user, this session)
**Branch:** `feature/full-hand-ui`

## Context & goals

The rewrite branch has a solid observe-and-drive UI (tactile, encoders, motor
sliders, 3D view) but is missing the hand's *lifecycle* operations: tensioning,
calibration (full and per-joint/finger), the guided bring-up routine, and pose
/ trajectory playback. This design adds them, restructures the UI so the new
features don't clutter the daily-driver view, and gives the app a professional
identity ("ORCA Hand Console").

Explicit user decisions from the brainstorm:

- Structure: **tab bar** — `Dashboard · 3D · Poses · Setup · Motors`.
- **Poses is its own tab** (presets, movement scripts, trajectory record/replay).
- Cross-tab control of running playback/recording via a **global transport bar**
  (appears only while an operation is active).
- Start screen: **boot-screen hero**; brand: **ORCA Hand Console**.
- Prominent, good-looking **E-stop** in the header.
- Motor detail (temps/currents, tuning, loop stats, event log, reconnect
  button) lives in the **Motors tab**, not the dashboard.
- Tension uses the **full wind → hold → release** interactive flow.
- Tactile zeroing stays as-is (it already exists in the tactile toolbar; the
  gap was discoverability only — keep it visible, change nothing else).
- Batch-2 scope: **reconnect button only** (no jitter, no zero-pose button).
- Backend architecture: **single operations subsystem** (approach A).
- Keep all orca_core touchpoints behind **one adapter seam** — the user plans
  to refactor orca_core's motor side to a state-based system soon.

## Information architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│ ◈ ORCA HAND CONSOLE   model-badge  ●status   Dashboard 3D Poses     │
│                                              Setup Motors   ■E-STOP │
├─────────────────────────────────────────────────────────────────────┤
│ [transport bar — only while an operation runs]                      │
├─────────────────────────────────────────────────────────────────────┤
│ active view                                                         │
└─────────────────────────────────────────────────────────────────────┘
```

- **Dashboard** (unchanged in essence): tactile panel (incl. existing Zero /
  Reset Zero), encoder ROM bars + sparklines, motor slider panel with
  torque/neutral. TuningPanel, LoopStatsBar, capability badges and Hz meters
  move out (→ Motors tab).
- **3D**: unchanged (scene + motor panel).
- **Poses**: preset pose grid, movement scripts/demos, trajectory library
  with record & replay.
- **Setup**: tension card, calibrate card (with expandable joint selection),
  wizard card, live operation log pane.
- **Motors**: per-motor health table (temp/current, warning thresholds, from
  the existing 1 Hz `motors.telemetry`), TuningPanel, LoopStatsBar,
  capability badges + stream Hz meters, supervisor event log, Reconnect
  button (wired to the existing unused `POST /api/reconnect`). The event log
  is a client-side timestamped accumulation of `status`, `error`, and
  `operation.state` events (bounded buffer, no new backend storage).

### Boot-screen hero

While the backend is offline or no session exists (detecting/connecting), the
content area is a full-viewport centered lockup: large `◈ ORCA` wordmark,
`HAND CONTROL CONSOLE` subtitle, animated status line ("SEARCHING FOR
HARDWARE …"), a hardware checklist that ticks on as the connection ladder
climbs (motors → encoders → tactile, driven by the `status` topic and
`/api/ports`), and a model/version footer. Collapses into the normal header
when connected. Browser title becomes "ORCA Hand Console".

### Transport bar

Rendered under the header on every tab whenever an operation is active:

- Replay/demo: `▶ name · progress bar · elapsed/total · ⏸ · ■ stop`.
- Record: `● REC · mode + frequency + frame count · ■ stop & save`
  (waypoint mode adds a `capture` button).
- Maintenance ops: `CALIBRATING index_mcp (4/12) · ■ stop`, etc.
- `awaiting_input` prompts render inline as buttons (e.g. tension's
  "Release", wizard's "Continue round 2?") so they work from any tab.

One-shot pose applications are instant and do not spawn the bar.

## Backend: operations subsystem

New package `orca_ui/hand/operations/`.

### OperationManager

- Runs **at most one exclusive operation** at a time on a dedicated worker
  thread. Starting another while one runs → 409.
- Publishes to a new WS topic **`operation.state`** (event-driven, latest
  snapshot replayed on subscribe — a page reload mid-calibration resyncs):

  ```json
  {"kind": "calibrate", "run_id": "...", "state": "running",
   "phase": "step", "detail": "index_mcp flex", "progress": 0.33,
   "params": {...}, "awaiting": null, "result": null}
  ```

  `state ∈ starting | running | paused | awaiting_input | stopping | done |
  error` (`paused` applies to replay/demo only — playback holds position and
  resumes from the same frame).
- Companion topic **`operation.log`**: line-level progress for the Setup
  tab's log pane (frontend accumulates).
- `stop()` sets the op's stop event; ops are responsible for cleanup.
- **Await-input**: an op may park in `awaiting_input` with
  `{prompt, options: [...]}`; `POST /api/operation/input` answers it. Used by
  tension (release), waypoint record (capture / stop), wizard (round gates).

### Two hardware-access classes

1. **In-session ops** — `demo`, `replay`, `record`. Use the existing
   connected session. (Pose *apply* shares their preconditions and gating but
   is a plain one-shot endpoint, not managed by OperationManager — it
   finishes in one motion and needs no progress/stop.)
   - `replay` streams waypoints through the existing CommandWorker at the
     recording's `sampling_frequency_hz` (scaled by speed factor); while it
     runs, manual slider targets are rejected — the operation owns the target
     channel.
   - `record` reads measured joints from the already-running telemetry path;
     it **disables torque at start** (recording = physically moving the hand)
     and never re-enables it.
2. **Maintenance ops** — `calibrate`, `tension`, `wizard`. The supervisor
   gains one new FSM state, **`MAINTENANCE`**: it closes the current session
   and lends the hardware to the operation (health checks and auto-reconnect
   suspended). The op builds its own motor-only `OrcaHand` plus a UI-owned
   encoder client for calibration anchors — exactly the `scripts/calibrate.py`
   pattern, which sidesteps orca_core's refusal to calibrate while the 100 Hz
   feedback loop runs. On finish/abort the lease is released and the
   supervisor reconnects through the normal detection ladder. Sensor streams
   pause during maintenance; dashboards show a slim "hand in maintenance —
   <op>" banner.

### The operations

- **`tension`**: full orca_core flow — winding (bounded ~40 s), current
  ramp-down, then indefinite **hold** phase surfaced as
  `awaiting_input {prompt: "Motors holding — tension the spools, then
  release", options: ["Release"]}`. Release → cleanup (restore control mode,
  torque off) → done.
- **`calibrate`**: params `{joints: [...] | null, force_wrist: bool}`.
  `joints: null` = full calibration. Per-finger selection is a frontend
  convenience that expands to joint lists (mapping as in
  `scripts/calibrate.py` `FINGER_TO_JOINTS`). Progress = calibration-sequence
  steps completed / total. Partial runs are safe: orca_core persists
  calibration.yaml after every step.
- **`wizard`**: composite maintenance op mirroring `scripts/setup.py`:
  `(tension → calibrate) × rounds` (param `rounds`, default 3) with
  `awaiting_input` confirm gates between phases.
- **`demo`**: runs an orca_core demo preset or an orca_ui built-in sequence
  (open–close, pinch cycle — shipped as waypoint-trajectory YAMLs).
- **`replay`**: params `{name, speed ∈ {0.5, 1, 2}, loop: bool}`. Validates
  the file's `joint_ids` and `hand_type` against the connected config before
  moving anything.
- **`record`**: params `{mode: waypoints | continuous, frequency (continuous,
  default 50), name}`. Waypoint mode: each `capture` input appends the
  current measured pose; continuous mode samples at `frequency`. Stop & save
  writes the library YAML.

### E-stop

`POST /api/estop`: stop current operation (its cleanup runs) + disable torque
+ stop the mock sweeper. One code path, valid in every state.

### orca_core changes (local checkout; upstream candidates)

Minimal and additive: optional `progress_callback` parameter on `calibrate()`
and `tension()`, invoked with structured events (step started/done, joint
calibrated + ratio, tension phase transitions). Default `None` preserves
current behavior.

### Adapter seam

All orca_core calls made by operations go through **one module**
(`orca_ui/hand/operations/hand_ops.py`). When orca_core's motor side becomes
state-based, this module is the only planned rewrite point.

### Mock mode

The mock serial link does not emulate motor stalls, so real
`calibrate()`/`tension()` would hang. Mock mode substitutes **simulated
implementations** that emit the identical `operation.state`/`operation.log`
event stream on a timer (including `awaiting_input` phases). This gives
deterministic backend tests and lets the Setup/Poses UI be developed without
hardware. In-session ops (record/replay/demo/pose) run for real against the
mock stack.

## API surface

New endpoints (existing `HandService`/router patterns; sync handlers):

- `POST /api/operation/{kind}/start` — kinds `calibrate | tension | wizard |
  replay | record | demo`, per-kind params as above. 409 if one is running or
  preconditions fail (human-readable `detail`).
- `POST /api/operation/stop`
- `POST /api/operation/input` — `{value}` answering `awaiting_input`.
- `POST /api/estop`
- Poses: `GET /api/poses`, `PUT /api/poses/{name}`, `DELETE /api/poses/{name}`,
  `POST /api/poses/{name}/apply`, `POST /api/poses/capture` `{name}` (saves
  current measured pose).
- Trajectories: `GET /api/trajectories`, `DELETE /api/trajectories/{name}`.
- Demos: `GET /api/demos` (orca_core presets + built-in sequences).

WS topics added: `operation.state`, `operation.log` (both event-driven,
snapshot-replayed on subscribe like `status`).

### Storage & formats

- Library root: `~/.orca_ui/library/<model_name>/` → `poses.yaml` +
  `trajectories/*.yaml`.
- Trajectory files use the **exact YAML schema of orca_core's
  record/replay examples** (`metadata.type: discrete_waypoints | continuous`,
  `joint_ids`, `hand_type`, `sampling_frequency_hz`, `waypoints`/`angles`) —
  recordings are interchangeable with the CLI scripts, both directions.
- Built-in presets (fist, open, peace, pinch, point) are defined as
  **ROM-fraction poses** (applied via `pose_from_fractions`) so they survive
  recalibration; flagged `builtin: true` and `placeholder: true` until tuned
  on the real hand. User poses are stored as joint-angle dicts (degrees) and
  shadow built-ins by name.

## Frontend

- View enum grows to `dashboard | 3d | poses | setup | motors`.
- New zustand **`operationStore`** fed by `operation.state`; log lines
  accumulate in a bounded buffer for the Setup log pane.
- **Gating:** one derived selector (`exclusiveActive`) disables motor
  sliders, torque buttons, and op-start buttons, with a tooltip naming the
  running operation. `MAINTENANCE` status shows the banner on
  dashboard/3D/poses.
- **TransportBar** component in `App` under the header (behavior above).
- **Header:** brand lockup `◈ ORCA HAND CONSOLE`, model badge, status pill,
  five tabs, red E-STOP hard right (styled to the instrument aesthetic:
  bordered, high-contrast, not a gimmick). Capability badges + Hz meters move
  to Motors.
- **E-stop button:** immediate (no confirm — it's an e-stop), always enabled
  when a backend is reachable.
- **Poses tab:** preset grid (built-ins + user poses, `+ capture current
  pose`), movement scripts section (demos), trajectory library (list with
  replay controls: speed ×0.5/×1/×2, loop; delete) + record controls (mode,
  frequency, name). Pose apply/replay/demo buttons disabled with hint when
  torque is off (torque is never auto-enabled); a torque toggle sits in the
  tab toolbar for convenience.
- **Setup tab:** three cards + log pane:
  - *Tension:* Start → phase indicator (winding → ramp → **holding**, with
    prominent "Release" while holding).
  - *Calibrate:* primary "Calibrate all" button; collapsed **"Select
    joints"** expander → per-finger chips (thumb/index/middle/ring/pinky/
    wrist) each expandable to individual joint checkboxes; `force wrist`
    toggle; per-joint calibration status list (from hand info:
    `encoder_calibrated`, motor calibration present).
  - *Wizard:* rounds selector (default 3), phase timeline
    (tension₁ → calibrate₁ → … ), runs with confirm gates.
- **Boot hero** replaces the current placeholder cards in `DashboardView`
  (and is hoisted above the view switch so it covers all tabs while
  disconnected).

## Error handling & safety

- Preconditions checked at op start (409 + reason): motors required for
  calibrate/tension/wizard/replay/demo/pose-apply; encoders required for
  record; replay validates joint order/hand type. Degraded tiers render the
  corresponding buttons disabled with the reason.
- Torque is never auto-enabled. Replay/demo/pose-apply require it already on;
  record turns it off.
- Op failure → `operation.state: error` + error banner + log; maintenance
  failures run orca_core's abort cleanup (restore max-current, disable
  torque), release the lease, and the supervisor re-detects. Partial
  calibration keeps completed steps (persisted per step).
- WS drop mid-op: op continues server-side; client resyncs via
  replay-on-subscribe.
- Hand unplugged mid-maintenance: serial errors surface as op failure, then
  normal re-detection.
- E-stop stops the op and disables torque; the op reports
  `error/stopped (e-stop)`.

## Testing

Backend pytest over the mock hand (existing patterns):

- Operation lifecycle: start / 409 on conflict / stop / input / estop.
- Simulated calibrate + tension event streams (states, phases,
  awaiting_input).
- Maintenance-lease FSM transitions with fakes (style of
  `test_connect_ladder.py`).
- Record → YAML → replay round-trip: recorded mock trajectory replays and the
  mock loop converges.
- Poses/trajectories CRUD; `pose_from_fractions` built-ins apply on the mock.
- `operation.state` snapshot replay on WS subscribe (TestClient).

Frontend: no unit runner (consistent with today); every flow is drivable
end-to-end against `--mock` in a browser; final visual check via the Chrome
extension (also clears the pending browser-check follow-up from project
memory).

## Out of scope / future

- Jitter and zero-pose buttons (explicitly deferred by user).
- Splitting tactile vs joint sensing into separate views (kept together).
- orca_core state-based motor refactor (tracked; `hand_ops.py` is the seam).
- Keeping sensor streams alive during maintenance ops (possible later: the
  calibrate op owns an encoder client and could feed `joints.measured`; not
  in this round).
- Upstreaming `progress_callback`, `interactive` connect param, and
  `set_taxel_offsets` facade to orca_core origin.
