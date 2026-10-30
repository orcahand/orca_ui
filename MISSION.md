# Mission: Calibration UX — slack test, tensioning entry points, sweep with built-in ratchet
Status: active

## Goal
Make the Setup tab's slack test, tensioning and tension sweep match the 2026-10-30 feedback:
- **Slack test.** Each movement starts and ends promptly. Back can redo any joint, the last one
  included. At most 5 clicks are recommended. The text spans the whole dialog, and pressing Test
  doesn't shift the layout. The final screen offers only Close and On to tensioning.
- **Tensioning.** On to tensioning opens guided tensioning straight at the ratchet step, with the
  slack test's clicks. Every other start opens at the first "move the finger" stage. The Tension
  row is renamed Guided tensioning, and a new Simple tensioning row opens the v2.0 hold-and-ratchet
  dialog.
- **Info icons.** The descriptions of slack test, guided tensioning, simple tensioning and tension
  sweep sit behind an (i) hover icon.
- **Tension sweep.** The "Tension again" row is gone. The sweep dialog holds the motors for
  ratcheting itself. The sweep shows no percentages and recommends at most 3 clicks.

Done when: every task below is ticked with Log evidence, `./dev test` passes, the core suite passes,
`npm run build` passes, and the user has checked the hardware/visual tasks.

## Decisions
- **Repos.** The UI work is in `orca_ui_merge` (worktree of orca_ui, branch
  `merge/assembly-calibration`). The core work is in `../orca_core` (branch
  `feature/improve-calibration`, version 0.6.0). The UI runs against the core through `./dev run`
  and `./dev test`, never through a `[tool.uv.sources]` entry.
- **Another session.** Something else is editing `frontend/src/components/assembly/*` in this
  worktree (AssemblyGuide.tsx and buildContent.ts were modified on 2026-10-30 at 12:36, while this
  mission was being planned). Those files are never touched or staged here. The bundle in
  `orca_ui/webui` is built from the whole tree, so it would carry their uncommitted work. Rebuild
  it only for verification, and commit it only by agreement.
- **Slack "doesn't start".** Evidence: the slack tests of 21 Oct on the touch-right hand have
  directions reading 0–1° on most joints, at 40 mA and at 60 mA. Stall detection compares single
  50 ms samples against 2°/s, which is only about one encoder tick (0.088°) per sample. Tick jitter
  can keep a held motor from ever counting as stalled, which runs the phase into its 10 s timeout.
  The return to start also waits up to 4 s for a motor that can't get within 2°. Fix: detect a stall
  by net movement over a window, end the return when the motor stops, and log why each phase ended
  (stall / budget / timeout) so a hardware run shows which case it was.
- **Back.** Back already exists on the hold prompt from the second joint on. It becomes always
  visible (disabled on the first joint), and a new core review step after the last joint lets Back
  redo that joint too. The review screen offers Back, Close and On to tensioning. Close and On to
  tensioning first answer Finish, so the test is always saved.
- **Click caps.** `reference.clicks_for_slack` / `clicks_for_share` take a cap. Slack-derived clicks
  (slack test, its summary, guided tensioning's own ratchet list) are capped at 5. Sweep clicks are
  capped at 3. The dialogs say the cap is per round and that a re-test lists more if needed.
- **On to tensioning.** It's offered after a failed slack test too, because ratcheting is the
  remedy. It opens guided tensioning at the ratchet step. The backend blocks only calibration on a
  failed test. The Guided tensioning row keeps its existing "pass the slack test first" gate.
  Simple tensioning has no slack gate.
- **The dialog selector goes.** The "dialog" setting (auto / force guided / force hold) is removed,
  because the two explicit rows replace it. Guided on a non-v2.1 hand still passes
  `any_hardware=true` and shows its existing warning.
- **Info icons.** Explanatory text moves behind the (i) (the existing `HoverNote`). Result lines
  (passed date, most slack, clicks, block reason, latest sweep) stay visible under the row title.
- **Sweep ratchet.** The sweep dialog starts the existing `tension` op (`move_motors=false`, the
  page's pull offset) and keeps showing the finished sweep (tower marks plus clicks), with Pull
  more and Done — release inline. `TensionDialogs` keeps the sweep snapshot in `tensionFlow` while
  that hold runs. Hold tensioning holds every finger motor; only the listed spools get ratcheted.
- **Commit policy.** See the Log (asked at plan approval).
- **Approved 2026-10-30.** Commit policy: no commits, and no pushes. Everything stays in the
  working trees for the user to review.
- **"Doesn't start" confirmed.** The user sees the motor sit still for up to ~30 s. That matches
  two 10 s phase timeouts plus two 4 s returns, so it's the jitter and stall case, not a motor
  failing to break away. No current kick.
- **Failed slack test advice.** A failed slack test shows a prominent box: tension by hand. Remove
  the top spools from the assembly and attach them back with more pretension, rather than taking
  that much slack up with the ratchet.

- **Formatter hook.** A PostToolUse formatter on Edit rewraps whole Python files to 88 columns
  (there's no ruff config here, and both repos use ~120). The first time it fired it reflowed all
  of `slack_test.py`. That churn was reverted, and Python edits now go through small Bash/Python
  replace scripts, so the diffs stay in the files' own style.

- **Start grace (2026-10-30, after review).** The review pointed out that a 0.5 s stall window
  with no grace reads a late breakaway as ~0° slack, which errs in the unsafe direction, and that
  the old code (in effect a 10 s window) had at least caught breakaways up to 10 s. So a motor that
  hasn't moved yet gets `start_grace_s = 3.0` before it can count as stalled. After that, the
  0.5 s windowed rule applies. The watch reads the signed offset and starts from the position
  read before the goal is written. Cost: a taut direction now takes about 3 s, against 10 s+4 s
  before. Still no current kick. The log's `seconds` field shows how late real starts are, so the
  grace can be tuned against the hand.
- **Left as is after review.** `pct` in `ratchet_joints` stays an optional, unused field of the
  API. Simple tensioning stays ungated by the slack block (by design). The slack lease is held
  while the review prompt waits, the same as every hold prompt.

- **Hardware-check feedback (2026-10-30).**
  - The guided tooltip was wrong: the motors hold the pose and resist, they don't follow.
  - v2.0 and unknown hands get no guided tensioning anywhere, only simple tensioning. On to
    tensioning on those hands starts the hold directly and lists the slack clicks in the hold
    dialog.
  - Cancel stops the run and closes the dialog, in every tensioning, sweep and manual
    calibration dialog.
  - The sweep has no note field and no passes selector; it always does 1 pass.
  - The flowchart is read-only. Its texts are reviewed, and it shows the v2.0 or the v2.1 flow to
    match the hand.

## Tasks
- [x] 1. Core slack test: stall detected by net movement over the `stall_hold_s` window; the return
      ends on a stall as well as on arrival; each phase reports its end reason (`slack_phase_done`:
      reason, deg, seconds), and the UI logs it — check: `cd ../orca_core && uv run pytest tests/`
      passes, with one new test where ±1-tick jitter on a held motor still stalls within ~1 s
- [x] 2. Core slack test review step: an optional `review_callback` after the last joint; HOLD_BACK
      redoes the last joint — check: core `tests/test_slack_test.py` passes, with one new test for
      Back from the review
- [x] 3. UI backend: click caps (slack 5, sweep 3) through `reference.py`; the slack op's review
      prompt (Back / Finish) in the real and simulated op; the guided presenter opens at the first
      stage unless `start_at='tension'` — check: `./dev test` passes, and a mock API run shows
      step=review, then Back → hold on the last joint, then Finish → done
- [x] 4. Slack test dialog: full-width copy; a stable pane (heading, copy and action row always
      rendered, buttons disabled while testing); Back always shown; the review screen; Calibrate
      removed; Close / On to tensioning (guided at the ratchet step with the slack clicks) — check:
      `npm run build` passes, and a mock API run of On to tensioning starts guided_tension with
      start_at=tension, ratchet_joints from the slack clicks, and step=tension
- [x] 5. Setup rows: Tension → Guided tensioning, a new Simple tensioning row (hold dialog), the
      dialog selector removed, descriptions behind (i) for slack test, guided, simple and sweep; the
      Tension again row removed from CalibrateStep, workflow.ts and WorkflowChart — check:
      `npm run build` passes, and grep finds no "Tension again" in `frontend/src`
- [x] 6. Tension sweep: percentages removed (verdict text, tower tags, heading, footnote,
      CalibrateStep, the guided ratchet colour); hold-and-ratchet inside the sweep dialog — check:
      `npm run build` passes, grep finds no `share * 100` in `frontend/src`, and a mock run shows
      sweep → hold → release with the sweep dialog kept
- [ ] 7. Hardware and visual pass — check: user — on the real hand: slack test phases start and end
      promptly (log shows the end reasons), Back works on every joint including the last, clicks
      ≤ 5, full-width text, no jump on Test, On to tensioning lands on the ratchet with clicks;
      Guided opens at the first finger; Simple opens the hold dialog; (i) tooltips; sweep shows no
      %, ≤ 3 clicks, and the inline hold works
- [x] 9. The failed-slack-test advice box in the slack dialog (review and done screens), shown
      while any joint fails — check: `npm run build` passes, and a mock run with `unspool` shows
      the box
- [x] 10. Guided tooltip text (motors resist); v2.0/unknown → only Simple tensioning (Tension step
      rows, settings, slack On to tensioning → hold op with clicks shown in HoldTensionDialog) —
      check: `npm run build` passes, and a grep shows `startGuidedTension` is reached only on v2.1
- [x] 11. Cancel closes the dialog (slack, sweep, sweep hold, hold, guided, manual calibration) —
      check: `npm run build` passes, and every `operationStop` Cancel in those dialogs also calls
      onClose
- [x] 12. Sweep: no note or passes controls; repeats always 1 — check: `npm run build` passes,
      and grep finds no `sweepRepeats` / `runNote` in `frontend/src`
- [x] 13. Flowchart: edit mode and localStorage removed; texts reviewed; v2.0 and v2.1 variants —
      check: `npm run build` passes, and grep finds no `saveWorkflow` / `workflow-input`
- [x] 14. Calibrate row buttons read Automatic / Manual — check: `npm run build` passes
- [x] 15. Tension step has no settings drawer. Guided uses the family currents and the default
      pull (both adjustable inside the dialogs); the pull is no longer persisted; the kai-page
      BaselinePicker moved to the Calibrate settings — check: `npm run build` passes, and grep
      finds no `setOffsetDeg` / `OFFSET_BOUNDS_DEG`
- [x] 8. Fresh-context review against the Goal; fix gaps — check: the reviewer's findings are
      resolved or logged

## Log (append-only)
- 2026-10-30 12:40 · planned · baseline: `./dev test` 451 passed; core `tests/test_slack_test.py`
  4 passed; the previous (complete) mission was copied to MISSION-archive.md
- 2026-10-30 12:55 · plan approved (no commits); task 9 added (failed-test advice box); the
  ~30 s stall confirms the jitter hypothesis
- run started 2026-10-30T12:55+01:00
- 2026-10-30 13:10 · tasks 1+2 · core `tests/test_slack_test.py` 6 passed (2 new: jitter stall,
  review Back). Full core suite: 1654 passed, 3 failed in `test_hardware_version.py`, all because
  the git-ignored runtime file `models/v2/orcahand-right/local_config.yaml` (the console's
  hardware-version pin) is present; nothing to do with this change. A scratch comparison with
  ±1-tick jitter around a displaced motor: the old `_wind` takes 10.0 s (timeout), the new one
  0.6 s (stall). The UI presenter logs `slack_phase_done`.
- 2026-10-30 13:35 · task 3 · `./dev test` 451 passed. `test_too_much_slack_blocks_calibration…`
  now drives review → Back → hold(ring_mcp) → Test → Finish → done (it was extended, not added
  to). Scratch check: slack 2000° gives 5 clicks, sweep share 0 gives 1 (capped at 3), the
  sweep's slack path at 2000° gives 3. `_first_stage`: pose@0 → none, pose@2 → goto:thumb,
  score → goto:thumb
- 2026-10-30 13:55 · tasks 4+9 · `npm run build` passes (tsc clean; the only oxlint warning,
  only-export-components on `marksFromSlack`, was already there). Mock API walk
  (`scratchpad/mock_flow.py`): after the last joint step=review with options [Finish, Back];
  clicks index_pip 0, ring_mcp 5 (capped; 180° at 8°/click would be 22); Finish → done, saved and
  blocked; guided `start_at=tension` with those clicks → step=tension, ratchet {ring_mcp: 5}; a
  plain guided start's first prompt is pose at stage thumb, index 0. The advice box renders on the
  review and done screens whenever a joint fails; it's verified in code only, and the visual
  check is in task 7. The frontend chain (Finish → `startAfter` → guided start) is verified only
  as far as the API; the in-browser click is part of task 7.
- 2026-10-30 14:15 · task 5 · `npm run build` passes, and grep finds no "Tension again" or
  `tensionAgain` in `frontend/src`. TensionStep: a) Slack test, b) Guided tensioning,
  c) Simple tensioning (`openHold`). The descriptions moved behind `FlowRowTitle` (HoverNote (i));
  result lines stay. The forced-mode selector and `useTensionMode` are gone from tensionFlow.
  CalibrateStep: the sweep's status line now carries the clicks the removed row used to show.
  workflow.ts is v5: the again box is gone, measure→calibrate loops "clicks listed: ratchet,
  calibrate again", the chart has 2 rows, and the slack and measure texts are updated (no %)
- 2026-10-30 14:45 · task 6 · `npm run build` passes and `./dev test` 451 passed. The display
  no longer has `share * 100` or 40/60/90/110 % anywhere; the only % left are code comments in
  types.ts and guidedSettings.ts. Verdict words: well tensioned / a little low / too loose /
  slack / tighter. Mock walk (`scratchpad/mock_sweep_hold.py`, load_scale 0) gives index_pip low
  with 1 click and middle_mcp low with 1 click; then `tension` (move_motors=false, 15°) awaits
  [Release, Pull more], Pull more makes pulled_deg 30, Release ends done {released: true}. The
  sweep dialog renders the hold inline via `tensionFlow.sweepRatchet`, and `openHold` clears it so
  Simple tensioning never lands in the sweep dialog. Also: a `start_at=tension` run now jumps to
  the ratchet from a first *score* prompt too, for when every stage has already passed.
- 2026-10-30 15:20 · task 8 · fresh validator: PARTIAL. Every goal item passes in code, tests or
  mock, except the visual and hardware ones, which can't be verified here. Fixed: an empty ratchet
  list now gets an explanatory line in the guided ratchet step; the stale "force guided" 409 text
  and comments in `HoldTensionDialog.tsx` and `service.py` are corrected; a trailing space is
  gone; the core start grace (see Decisions) is in, with a new test that a 1.5 s late breakaway is
  measured fully (it fails with the grace set to 0). Core slack tests: 7 passed; core suite: 1655
  passed, plus the 3 pre-existing local_config failures. A stale .pyc from two same-second,
  same-size seds briefly masked the result, and a touch fixed it. `./dev test` 451 passed,
  `npm run build` passes, `mock_flow.py` passes. Remaining: task 7 (user, hardware and visual)
- 2026-10-30 15:45 · hardware-check feedback → tasks 10–13 added
- 2026-10-30 16:20 · tasks 10–13 · `npm run build` passes (tsc clean) and `./dev test` 451
  passed.
  - 10: GUIDED_INFO now says the motors hold the pose and resist. The guided row renders only
    when `isV21`, and `any_hardware` is dropped from both guided starts. `startGuidedTension` is
    called only in SlackTestDialog's `isV21` branch; otherwise it's `startHoldTension` with
    `tensionFlow.holdClicks`, which HoldTensionDialog lists in its ratchet step.
  - 11: all 6 dialog Cancel buttons (slack; sweep; sweep hold; hold; guided; manual) call
    `operationStop` and then `onClose`.
  - 12: the note and passes controls are gone, `startTensionSweep` sends repeats 1, and grep
    finds no `sweepRepeats` / `runNote` / `SWEEP_REPEAT`.
  - 13: workflow.ts is static GUIDED_WORKFLOW / SIMPLE_WORKFLOW (the v2.0 one is slack → simple
    tensioning → calibrate…). The chart picks one by hardware version and has no edit, reset or
    localStorage; the edit CSS is removed; grep is clean. The texts were reviewed: the motors
    resist, caps 5/3, Hold & ratchet in the sweep, and Back.
- 2026-10-30 16:50 · tasks 14+15 (feedback round 3) · tsc clean, `npm run build` passes, grep is
  clean. orca_core comparison for the user: the merge base with origin/main is 6735e94
  (2026-10-12, #124 guided tensioning). The branch is 5 commits ahead plus the uncommitted slack
  change; origin/main is 64 ahead (0.7.0 → 0.12.0); 16 files changed on both sides
