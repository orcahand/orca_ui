# Implementation plan — ORCA Hand Console

**Spec:** `docs/superpowers/specs/2026-07-08-hand-console-design.md`
**Date:** 2026-07-08 · **Branch:** `feature/full-hand-ui`
**Reviewed:** adversarially verified against both codebases (3-critic pass);
all confirmed findings folded in below.

Seven milestones, each landable and testable on its own. M1 defines the
API/topic contracts; after it, backend (M2–M3) and frontend (M4) can proceed
in parallel. `uv run pytest tests/` green + `npm run build` clean at every
milestone boundary.

---

## M0 — orca_core: `progress_callback` + stop-safety (separate repo)

Repo `../orca_core`, branch `feature/joint-sensing`. Additive only.

1. `orca_core/hardware_hand.py`
   - `calibrate(..., progress_callback: Callable[[dict], None] | None = None)`
     (signature at ~:687) — thread through to `_calibrate` (~:778). Emit at
     the existing print points, wrapped in try/except so a bad callback never
     aborts calibration:
     - `{"event": "calibration_started", "steps": N, "joints": [...]}`
     - `{"event": "step_started", "index": i, "joint": j, "direction": "flex"|"extend"}`
     - `{"event": "step_done", "index": i, "joint": j}`
     - `{"event": "joint_calibrated", "joint": j, "ratio": r}` (at ~:1044)
     - `{"event": "calibration_done"}` / `{"event": "calibration_aborted"}`
   - `tension(..., progress_callback=None)` (~:1398) → `_tension` (~:1501):
     - `{"event": "phase", "phase": "winding"|"ramp"|"holding"|"released"}`
     - during winding: `{"event": "winding_progress", "motor": id, ...}` (coarse)
   - Callbacks fire from the calling/task thread; document that they must be
     fast and non-blocking (orca_ui's handler just enqueues to the hub).
2. **Stop-safety fix (critic-confirmed corruption bug):** in `_calibrate`,
   when `_task_stop_event` is set the drive loop exits with the joint NOT at
   its hardstop, but execution currently falls through to
   `_run_joint_encoder_pass_for_step` and the per-step persist (~:1075-1080)
   — a UI "stop calibration" would bake a wrong encoder anchor into
   calibration.yaml. Insert `if self._task_stop_event.is_set(): return None`
   immediately after the drive while-loop (~:978), before the encoder pass
   and limit capture. (CLI is unaffected — Ctrl-C raises out of the loop.)
3. Note for orca_ui callers: `calibrate()` clears the stop event at entry
   (~:710), so the op must check its own stop flag right before invoking
   calibrate (a stop that lands during connect/encoder-open would otherwise
   be swallowed).
4. Verify: run `scripts/calibrate.py` + `scripts/tension.py` unchanged
   (default `None` path); a quick REPL check that events arrive on a mock
   hand is enough — orca_ui's simulated ops (M2) are the tested surface.
5. Commit on `feature/joint-sensing` (orca_ui pins the local checkout via
   `[tool.uv.sources]`, so no version bump needed).

**Done when:** both scripts behave identically with no callback; events
arrive when one is passed; stop mid-step persists nothing for that step.

---

## M1 — Backend core: control-source arbiter + operations skeleton

All contracts (endpoints, topics, payloads) land here so the frontend can
start against `--mock` immediately after.

1. **Topics** — `orca_ui/streaming/topics.py`: add `OPERATION_STATE =
   "operation.state"` and `OPERATION_LOG = "operation.log"` (both
   event-driven, no min-interval cap; `ws.py`'s subscribe replay
   (ws.py:71-75) covers any topic with a stored hub snapshot, so both replay
   automatically).
   - **`operation.log` contract (critic-confirmed):** the hub is a
     latest-value store with 3 layers of latest-wins coalescing — per-line
     publishes would drop most burst lines. The payload is therefore
     **cumulative**: OperationManager owns the run's bounded ring buffer
     (last 500 lines, monotonic `seq` per line) and publishes
     `{run_id, next_seq, lines: [{seq, t, line}]}` (full buffer each time —
     latest-wins then loses nothing). Frontend appends lines with
     `seq > last seen`; reload mid-op resyncs the whole visible log for free.
2. **Control-source arbiter** — `orca_ui/hand/service.py`:
   - New enum `ControlSource(str, Enum): MANUAL, OPERATION, TELEOP` (TELEOP
     reserved/unused) in `orca_ui/hand/states.py`.
   - `HandService` gains `_control_source` (guarded by the existing
     `_state_lock`), `acquire_control(source) / release_control()`.
   - **`set_targets` gains a `source: ControlSource = MANUAL` parameter**
     (critic-confirmed: without it the player would either 409 against
     itself or bypass validation + the `joints.target` echo). It rejects
     with 409 naming the owner when `source != _control_source`; joint
     validation, torque gate, `_targets` bookkeeping, and the JOINTS_TARGET
     publish apply to every source. WS/REST handlers keep the default;
     operations pass `OPERATION`.
   - **Gate `enable_torque` and `go_neutral` the same way** while control
     source ≠ MANUAL (409 naming the owner) — otherwise a second tab/curl
     can enable torque mid-record while someone is physically posing the
     hand.
   - Add `control_source` to the `control.state` payload (built around
     service.py:249-251) and to `hand_info`.
3. **Operations package** — new `orca_ui/hand/operations/`:
   - `events.py`: `OpState` enum (`starting running paused awaiting_input
     stopping done error`), `OperationSnapshot` dataclass → `as_dict()`
     matching the spec JSON (`kind, run_id, state, phase, detail, progress,
     params, awaiting, result, error`).
   - `base.py`: `Operation` ABC — `kind: str`, `exclusive: bool`,
     `requires: Capabilities-predicate`, `run(ctx)`; `ctx: OpContext`
     bundles `service`, session accessor, `settings`, `emit(state|log)`,
     `stop_event`, `input_queue` (`queue.Queue`), and helpers
     `wait_input(prompt, options)` / `check_stop()`.
   - `manager.py`: `OperationManager` — `start(kind, params)` (validates via
     registry + preconditions, 409-style `ServiceError` if one is active),
     `stop()`, `send_input(value)`, `snapshot()`. One worker thread per run
     (daemon); publishes snapshots to `operation.state` and the cumulative
     log payload to `operation.log` via an injected publish callback (the
     `HandService(publish_topic=hub.publish)` precedent, server.py:29-34).
     On finally: release control source / maintenance lease, publish
     terminal state. `shutdown()` (lifespan) stops any active op with a join
     timeout.
   - `hand_ops.py`: the **adapter seam** — every orca_core call used by
     operations lives here (`build_maintenance_hand()`, `calibrate()`,
     `tension()`, `request_stop(hand)` (sets `hand._task_stop_event` — the
     one private access, confined here), `set_joint_positions()`,
     `pose_from_fractions()`, `demo_poses()` incl. synthesized timing,
     `FINGER_TO_JOINTS` — copied from `orca_core/scripts/calibrate.py:14-21`
     since scripts aren't importable). Docstring: this is the rewrite point
     for the planned orca_core state-based refactor.
4. **REST** — `orca_ui/api/rest.py` + `schemas.py` (pydantic models, as the
   existing schemas are):
   - `POST /api/operation/{kind}/start` (per-kind params model),
     `POST /api/operation/stop`, `POST /api/operation/input` (`{value}`),
     `GET /api/operation` (snapshot), `GET /api/operation/log` (current
     buffer, initial fetch), `POST /api/estop`.
   - **E-stop is never-raising and state-aware (critic-confirmed):** the
     naive `stop → disable_torque → sweeper` chain 503s during MAINTENANCE
     (`_require_session` raises when the lease closed the session — exactly
     when motors drive into hardstops). Instead, each stage is best-effort
     under try/except: (1) signal op stop (maintenance ops' stop path
     disables torque on the op-owned hand via orca_core's abort cleanup);
     (2) disable torque on the supervisor session *only if one exists*;
     (3) stop the sweeper *if it exists* (hardware mode has none — hoist the
     mock-only `JointSweeper` (rest.py:124-135) onto `app.state`/service as
     an optional handle); (4) always return 200 with a report of what was
     actioned. An e-stopped op publishes the terminal snapshot
     `state=error, detail="stopped (e-stop)"`.
   - Wiring: `service.attach_operation_manager(manager)` setter injection in
     `create_app` (manager needs service, service.estop needs manager);
     `build_router` gains the manager (or reads it via `request.app.state`).
5. **Wiring** — `orca_ui/server.py`: construct `OperationManager` in
   `create_app`, start/stop in lifespan (server.py:37-47), store on
   `app.state`.
6. **Tests** — `tests/test_operations.py` with a `DummyOp`: start → running
   → done; second start → 409; stop → done(stopped); `awaiting_input`
   round-trip; estop stops op + torque and returns 200, snapshot says
   `stopped (e-stop)`; `operation.state` snapshot replayed to a fresh WS
   subscriber; cumulative `operation.log` payload accumulates + resyncs;
   manual targets 409 while a DummyOp holds OPERATION **and**
   `set_targets(source=OPERATION)` succeeds and publishes JOINTS_TARGET;
   `enable_torque` 409s while an op owns control.

**Done when:** contracts frozen; dummy-op lifecycle green over TestClient.

---

## M2 — Maintenance lease + calibrate & tension operations

1. **Supervisor lease** — `orca_ui/hand/supervisor.py`:
   - New FSM state `MAINTENANCE` in `states.py` (states.py:9-15) + status
     message carries the op kind.
   - **Teardown runs on the supervisor thread (critic-confirmed race):**
     `enter_maintenance()` (called from the op thread) sets a
     `_maintenance_requested` flag, wakes the run loop, and waits on an ack
     Event (with timeout). The run loop — the only owner of sessions —
     performs the teardown, transitions to MAINTENANCE, and acks. This
     serializes lease entry with `_try_connect`/`_health_tick` by
     construction (no fresh session can appear mid-lease; no health probe
     can race a closing session). While MAINTENANCE: the loop just waits.
     State+session swap under `self._lock`; `session.close()` outside it.
   - `exit_maintenance()`: clear flag, state → `DETECTING`, wake → normal
     ladder reconnect.
   - Lease port info: probe **after** the session's ports are closed
     (probe_hardware opens ports exclusively; probing earlier reads busy
     ports as absent). Skip the probe entirely under `settings.mock`
     (lease carries `ports=None`; simulated ops never read it). Ops retry
     port-open briefly (~2 s) to absorb OS release latency.
2. **Calibrate op** — `operations/calibrate.py`:
   - Params `{joints: [str] | null, force_wrist: bool}`. **Backend contract
     is joints-only** (validate against config joint ids, reject unknown
     names); per-finger expansion is purely a frontend convenience in
     CalibrateCard (single expansion point, per spec).
   - Via `hand_ops`: build motor-only `OrcaHand(config_path)` (never the
     feedback subclass), `connect()`; if `config.joint_feedback_enabled`,
     open a UI-owned `JointEncoderClient` (construction as in
     `sessions._connect_sensors_only`, sessions.py:306-374) and pass it as
     `joint_encoder_client`.
   - Check `ctx.stop_event` immediately before invoking calibrate (M0 note:
     calibrate clears the orca_core stop event at entry). Run
     `calibrate(blocking=True, joints=..., force_wrist=...,
     progress_callback=emit)` on the op thread; stop/estop from other
     threads via `hand_ops.request_stop(hand)`. Progress = steps done /
     total from callback events.
   - Finally: disconnect hand, close encoder client, release lease.
   - **Structure the body as a lease-free function**
     `run_calibrate(hand, encoder_client, ctx)` with the Operation class as
     a thin lease-acquiring wrapper — M6's wizard composes the functions
     under one lease without refactoring.
3. **Tension op** — `operations/tension.py`: same lease pattern, body as
   `run_tension(hand, ctx)`.
   - **Run `tension(blocking=True, move_motors=True,
     progress_callback=emit)` on the op thread** (critic-confirmed: the
     `blocking=False` path has a lost-stop race — `_run_task` clears the
     stop event after thread start — and `stop_task()` joins without
     timeout, which can hang the op thread on a torque-holding hand).
     The progress callback's `"holding"` event flips the snapshot to
     `awaiting_input("Motors holding — tension the spools, then release",
     ["Release"])`; Release/stop/estop are answered from the REST thread via
     `hand_ops.request_stop(hand)` (the hold loop polls the event;
     `_tension`'s finally restores control mode and disables torque). No
     second thread, no join.
4. **Simulated ops (mock)** — `operations/simulated.py`: when
   `settings.mock`, the registry maps `calibrate`/`tension`/`wizard` to
   simulated implementations emitting the identical event/state sequence on
   a timer (~0.3 s/step; tension parks in `awaiting_input` until released).
   They still acquire/release the real maintenance lease so the FSM path is
   exercised.
5. **Tests** — `tests/test_maintenance.py`: lease transitions (connected →
   maintenance → detecting → connected); health tick suppressed during
   maintenance; simulated calibrate full + subset (`{joints: ["index_mcp"]}`
   reflected in events; unknown joint → 400); simulated tension
   awaiting_input → release → done; **estop during simulated maintenance op
   returns 200 and terminates it**; op failure releases lease and the
   supervisor reconnects.

**Done when:** on `--mock`, calibrate/tension run end-to-end from curl with
correct FSM + event streams; real-hardware path code-complete (validated on
hardware in M7).

---

## M3 — Library, poses, record/replay/demo

1. **Library** — new `orca_ui/library.py`:
   - Root `~/.orca_ui/library/<model_name>/` (override:
     `UiSettings.library_dir` + `--library-dir` in cli.py for tests).
   - `poses.yaml`: `{name: {angles: {joint: deg}}}`; built-ins (fist, open,
     peace, pinch, point) defined as `{fractions: {joint: 0..1}}` in
     `orca_ui/hand/presets.py`, flagged `builtin/placeholder`; user poses
     shadow built-ins by name.
   - `trajectories/*.yaml`: exact orca_core example schemas
     (`metadata.type: discrete_waypoints|continuous`, `joint_ids`,
     `hand_type`, `sampling_frequency_hz`, `waypoints`/`angles`).
   - Name validation `^[a-zA-Z0-9_-]{1,64}$` everywhere (no path traversal).
2. **REST** — poses `GET/PUT/DELETE /api/poses[/{name}]`,
   `POST /api/poses/{name}/apply`, `POST /api/poses/capture`;
   trajectories `GET /api/trajectories`, `DELETE /api/trajectories/{name}`;
   `GET /api/demos`. Apply resolves fractions via
   `hand_ops.pose_from_fractions` and runs as a **CommandWorker exclusive
   op** (the `go_neutral` pattern, commands.py:42-46) with interpolation
   steps — requires torque (existing `_require_torque`), rejected while
   control source ≠ MANUAL. **Capture uses measured joints only** (spec);
   no session/encoders → 409 with reason, no estimate fallback.
3. **TrajectoryPlayer** — `operations/player.py`: shared engine for `replay`
   and `demo`. Acquires `ControlSource.OPERATION`; **owns frame pacing on
   the op thread** (sleep-per-frame, submit latest via
   `service.set_targets(source=OPERATION)`); effective rates above the
   worker's `MAX_APPLY_HZ` (50, commands.py:18) are downsampled by
   latest-wins coalescing — documented, kinematically benign for position
   streaming. Validates `speed ∈ {0.5, 1, 2}` and `joint_ids`/`hand_type`
   before the first frame; honors pause/resume (`paused` state), loop, stop;
   requires torque already on. Waypoint files play as interpolated segments
   at a fixed default rate. Demos = built-in sequence YAMLs shipped in
   `orca_ui/data/sequences/` (open–close, pinch cycle — hand-authored from
   ROM fractions) + orca_core `demo_presets` converted via `hand_ops` —
   **timing is synthesized there** (demo presets carry poses only; use a
   per-segment duration constant mirroring `run_demo`'s defaults).
4. **Record op** — `operations/record.py`: params `{mode, frequency
   (default 50, cap 60 — the encoder read path is fresher than the 60 Hz
   rounded hub store, see below), name, disable_torque: bool = true}`.
   Requires encoders; disables torque at start (default) **and never
   re-enables it** (on stop, save, or error — the spec's "torque is never
   auto-enabled" rule). `disable_torque=false` exists for mock tests where
   the sweeper must keep driving motion. Sampling source:
   `session.measured_joints()` (fresh full-precision decode,
   sessions.py:103-118, lock-guarded) — not the hub store (60 Hz, rounded);
   dedupe identical frames by the encoder reading's seq/timestamp. Waypoint
   mode captures on `input("capture")`; stop & save → library YAML; frame
   counts in `detail`. Continuous recordings capped at 30k frames
   (= 10 min @ 50 Hz), surfaced in the UI.
5. **Tests** — `tests/test_library.py` (CRUD, name validation, fraction
   presets resolve on mock config), `tests/test_playback.py`:
   - record continuous on mock (`disable_torque=false`) while the sweeper
     moves a joint → valid YAML → replay → mock loop converges;
   - waypoint capture via input; torque stays off after a default record
     finishes; replay 409 without torque; joint-order mismatch rejected;
     invalid speed rejected; pause/resume; sliders 409 during replay;
   - built-in pose apply end-to-end over TestClient: enable torque →
     `POST /api/poses/fist/apply` → targets move toward fraction-resolved
     angles; 409 without torque.

**Done when:** record→replay round-trip green on mock; poses apply green
over TestClient.

---

## M4 — Frontend: IA restructure, header, boot hero, Motors tab, E-stop

1. **Contracts** — `frontend/src/api/types.ts`: `operation.state` /
   cumulative `operation.log` payloads, `control_source` on control state;
   **add `'maintenance'` to the `HandState` union** (types.ts:9-15) and give
   the status pill an explicit class/label for it plus a defensive fallback
   for unknown states (AppHeader's `STATE_CLASS`/`STATE_LABEL` are
   exhaustive records — an unmapped state currently renders a blank pill).
   `rest.ts`: operation/estop/poses/trajectories/demos wrappers.
2. **Stores** — `state/appStore.ts`: view enum → `'dashboard'|'3d'|'poses'|
   'setup'|'motors'`; new `operationStore` (operation snapshot + seq-merged
   log buffer + derived `controlOwner`/`exclusiveActive` gating selector);
   `streamClient.ts` dispatch for the two new topics.
3. **Header** — `components/header/AppHeader.tsx`: `◈ ORCA HAND CONSOLE`
   lockup, model badge, status pill, five tabs, `EStopButton` hard right
   (POST `/api/estop`, no confirm, styled in theme.css: bordered
   high-contrast red, hover/active states, disabled only when backend
   offline). Capability badges + Hz meters removed (→ Motors tab).
   `index.html` title → "ORCA Hand Console".
4. **Boot hero** — `components/BootHero.tsx`, rendered by `App.tsx` instead
   of any view while `!wsConnected || status.state ∈ {disconnected,
   detecting, connecting}` (maintenance/reconnecting do NOT trigger it):
   `◈ ORCA` wordmark + `HAND CONTROL CONSOLE` subtitle, animated status
   line, hardware checklist from `status.capabilities` + `/api/ports`,
   model/version footer. Remove the old placeholder cards from
   `DashboardView.tsx:13-32`.
5. **Motors tab** — `views/MotorsView.tsx`: `MotorHealthPanel` (per-motor
   temp/current table from `motors.telemetry`, warn thresholds ~55 °C /
   near max-current tint), relocated `TuningPanel` + `LoopStatsBar` +
   capability badges + Hz meters, `EventLog` (client-side bounded
   accumulation of status/error/operation events), Reconnect button
   (`api.reconnect`, already defined rest.ts:49).
6. **Gating & errors** — `MotorPanel` sliders/torque/neutral disabled with
   owner tooltip when `controlOwner !== 'manual'` or maintenance; slim
   maintenance banner on dashboard/3D/poses. **Terminal `error` operation
   snapshots feed the existing error banner** (appStore.error) so an op
   failure is visible on every tab, not just the Setup log pane.

**Done when:** `npm run build` + lint clean; on `--mock`: hero → connected
transition, five tabs, E-stop disables torque, Motors tab live.

---

## M5 — Frontend: TransportBar, Setup tab, Poses tab

1. **TransportBar** — `components/transport/TransportBar.tsx` in `App`
   under the header whenever an operation is active: kind-specific renderers
   (replay/demo: name + progress + **elapsed/total** + pause/stop; record:
   REC dot + mode/freq/frames + capture (waypoint) + stop&save; maintenance:
   phase + step counter + stop). `awaiting_input` prompts render as inline
   buttons → `/api/operation/input`. On terminal `error` the bar lingers
   with the message and a dismiss control (belt-and-braces with the error
   banner). Generic session-strip design (spec: teleop later adds a
   renderer).
2. **Setup tab** — `views/SetupView.tsx`:
   - `TensionCard`: Start → phase indicator (winding → ramp → holding) →
     prominent Release (input) — mirrors transport bar state.
   - `CalibrateCard`: "Calibrate all" primary; collapsed "Select joints"
     expander → finger chips → per-joint checkboxes (groups from
     `EncoderPanel`'s grouping, EncoderPanel.tsx:11; chips expand to joint
     lists client-side — the API takes joints only); force-wrist toggle;
     per-joint status list from `hand_info` (`encoder_calibrated` +
     calibrated flags).
   - `WizardCard`: rounds selector (default 3), phase timeline, confirm
     gates via awaiting_input.
   - `OperationLogPane`: seq-merged log from `operationStore`.
   - All start buttons disabled (with reason) when motors absent or an op is
     active.
3. **Poses tab** — `views/PosesView.tsx`: preset grid (built-ins + user,
   placeholder styling for untuned built-ins, `+ capture current pose`
   dialog), movement-scripts section (demos list), trajectory library (list
   with type/frames/duration, replay speed ×0.5/×1/×2 + loop, delete with
   confirm) + record controls (mode, frequency, name; **disabled with
   reason when encoders are unavailable**, from `status.capabilities`).
   Torque-off → apply/replay/demo buttons disabled with hint + torque
   toggle in the tab toolbar.

**Done when:** every operation is drivable end-to-end from the UI on
`--mock`, including cross-tab control via the transport bar.

---

## M6 — Wizard + polish

1. `operations/wizard.py`: composite maintenance op — params
   `{rounds: int = 3}`; composes M2's lease-free `run_tension` /
   `run_calibrate` bodies under a single lease with `awaiting_input` gates
   between phases; simulated variant for mock. Tests: full 2-round simulated
   run, abort mid-round releases lease.
2. Polish: theme.css for new components (cards, transport bar, hero
   animation via CSS keyframes), empty states (no poses yet, no
   trajectories), README update (new tabs + operations + library location),
   `hand_info`/`status` additions documented in types.ts header comment.

---

## M7 — Verification

1. `uv run pytest tests/` (all new suites) + `npm run build` +
   `node frontend/scripts/check-urdf.mjs`.
2. Mock browser walkthrough via Chrome extension (also clears the pending
   browser-check follow-up): hero → connect, all five tabs, calibrate subset
   flow, tension hold/release, wizard round, record→replay, E-stop during
   each class of op, page reload mid-operation resyncs transport bar + log.
3. Real-hardware smoke (user-run, guided): tension hold/release, single
   finger calibrate, full calibrate, verify reconnect at full tier after
   maintenance, stop-mid-calibration persists nothing for the aborted step.

## Risks & mitigations

- **Serial handover races**: lease teardown executes on the supervisor
  thread (flag + ack) so it serializes with connect/health by construction;
  ports probed only after close; ops retry opens ~2 s.
- **Calibration steps are unbounded** (stall-detection loop): stop button +
  estop always available (both never-raising); document that a stuck step
  means a mechanical problem.
- **orca_core divergence**: M0 stays additive; all orca_core touchpoints in
  `hand_ops.py` (state-based refactor lands there only).
- **Mock fidelity**: simulated maintenance ops share the manager/lease code
  paths with real ones; only the hardware layer is faked.
