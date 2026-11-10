# Tensioning findings — running record

Everything learned about getting a hand cleanly tensioned and calibrated,
one dated entry per piece of evidence. Append, never rewrite.
Data lives beside the hand's calibration in the installed `orca_core` models
folder (`travel_baselines.yaml`, `tension_probes.yaml`, `tension_progress.yaml`);
backups under `~/Documents/Projects/orca/hand_data_backup/<serial>/<timestamp>/`
(a detached loop copies both model folders there on every change; `backup.log`
beside them lists each copy).

## Reference hand: ser-9097 (orcahand-right, HW 210)

| Artefact | Name | What it is |
|---|---|---|
| Travel baseline | GT_00 | manual calibration 2026-10-15 17:50, before the final tensioning round; reference only |
| Travel baseline | GT_01 (active) | automatic calibration 2026-10-15 18:55 after that round; scores guided tensioning |
| Travel baseline | GT_02 (pending) | manual calibration after the 2026-10-15 late-evening manual tensioning; promote + activate when done |
| Probe | GT_tension_00/01/02 | same hand state, started from resting / neutral / mid-range |
| Probe | GT_tension_03 | after the late-evening manual tensioning, mid-range; reference probe for new hands |
| Probe | GT_tension_04 (right) | same settings, one hour after 03, no clicks in between: the repeat run |

## Findings

### 2026-10-15 — probe method behaviour
- Take-up free travel at 60 mA measures tendon slack only where the joint
  resists more than 60 mA. On low-friction joints (middle mcp, ring pip,
  pinky mcp) the motor drags the finger to the 40° cap in both directions;
  that is a free joint, not slack. Rule: free travel that stalls at a finite
  value is slack; free travel that runs to the cap on a joint with breakaway
  under 50 mA is a free joint.
- Breakaway current repeats within one 10 mA step across runs on the same
  hand state when the start pose is the same (mid-range). Changing the start
  pose (resting → neutral → mid) moves it by one to two steps. Mid-range is the
  default because resting and neutral poses skipped 10–12 probes at limits.
- Automatic calibration reads 2–9 % more motor travel than manual on MCP/PIP
  joints (the stall current pushes a little past where a hand stops).

### 2026-10-15 — effect of one manual tensioning round (GT_tension_02 → 03)
- Thumb dip: take-up 39° → 0.7°, breakaway 40 → 90 mA. Slack removed.
- Thumb cmc flex breakaway 80 → 180 mA, thumb abd 110 → 170 mA: now the
  stiffest joints on the hand; likely over-tight.
- Thumb cmc extend had a repeatable 20° dead zone in 00/01/02 (slack on the
  extend side); in 03 that probe was skipped at the limit — recheck after GT_02.
- Middle pip take-up 6° → 2°, breakaway 20 → 70 mA.
- Pinky abd breakaway 80 → 50 mA and a new 12° dead zone both sides: loosened.
- Index/middle mcp unchanged (140 / 30 mA): untouched joints repeat.

### Provisional "well tensioned" definition (to confirm with more hands)
Per joint and direction, against the reference probe:
1. No dead zone: take-up < 3° motor, or ran to the cap with breakaway < 50 mA.
2. Symmetric: flex vs extend breakaway within 40 mA.
3. Breakaway between 75 % and 150 % of the reference joint. Under → more
   clicks; over → back off. The 150 % ceiling is the least certain number.

### Open questions
- Manual calibration records overshoot: moving a finger onto its hardstop
  fast lets the (torque-off) motor spin past the position the joint
  actually stops at, and Record captures that peak. Idea for later: record
  the position after it has been still for ~0.5 s (settled value), or show
  the live reading and only accept Record once the motor speed is ~0, and
  warn when the captured value exceeds the settled one by more than a
  couple of degrees. Raised by the user 2026-10-16; not to be built yet.
- Degrees of motor free travel removed per ratchet click (click test, planned
  2026-10-16 on a fresh hand; script `scripts/click_test.py`, console stopped).
- Noise band of the probe: needs a same-pose repeat on an unchanged hand
  (GT_tension_04 after the GT_02 calibration on ser-9097).
- Does breakaway per joint transfer between hands of the same build, or does
  each hand need its own reference? First new hand answers this.

### 2026-10-16 — data is per model folder, not per hand
- Baselines, probes and calibration live in the installed model folder
  (`orcahand-right/`, `orcahand-left/`). A left hand sees none of the right
  hand's data. GT_01 (travel) and GT_tension_03 (reference probe) were copied
  into `orcahand-left/` and activated so new left hands score against ser-9097.
  Entries carry `hand_key`, so hands stay distinguishable inside one folder.
- Guided tensioning reads the active baseline when it starts; a run already in
  progress keeps its expected travel until resumed.

## Per-hand log
(one entry per hand: serial, date, rounds, baselines/probes saved, verdict)
- ser-9785 (orcahand-left, HW 210) — 2026-10-16 00:46: guided tensioning round 2,
  scored against the shared v2.1 block (run started before GT_01 was imported).
  Best fractions so far: pinky_abd 0.25, ring_mcp 0.45, thumb_cmc 0.50,
  thumb_mcp 0.52, ring_abd 0.55, pinky_pip 0.60; rest 0.64–0.92. Saved
  fractions are relative to the baseline in force when scored, so a Restart
  (not Resume) is needed for clean GT_01 numbers on this hand.
  - 00:49 round 3: thumb_cmc 0.50→0.81, pinky_abd 0.25→0.60, pinky_pip 0.60→0.74,
    middle_pip 0.77→0.84. Still low: ring_mcp 0.48, thumb_mcp 0.52, ring_abd 0.55.
  - 01:41 round 4 (Resume, now against GT_01; best values are max over both
    baselines so the table is mixed): index_abd 0.98, index_mcp/pip 0.89,
    pinky_pip 0.92, pinky_abd 0.74, ring_pip 1.03 (exceeds GT_01 travel).
    Still low: thumb_mcp 0.52, ring_abd 0.55, ring_mcp 0.60.
  - 01:45 round 5: pinky_abd 0.74→0.88, pinky_mcp 0.92, pinky_pip 0.93,
    middle_pip 0.91. Unchanged low: thumb_mcp 0.52, ring_abd 0.55, ring_mcp 0.60.
  - 01:47 round 6, run ended: thumb_mcp 0.52→0.90, thumb_cmc 0.88, middle_abd
    0.73→0.87. Only ring_abd 0.55 and ring_mcp 0.60 stay low after six rounds
    (never improved: check that ring's spools are being ratcheted, or the
    ring tendons are routed/seated wrong). thumb_abd 0.79 also flat since round 2.
  - 02:13 round 7 (new run, GT_01): ring_mcp 0.60→0.71 after the hardware
    fix. ring_abd still 0.55, thumb_abd still 0.79; everything else ≥ 0.87.
  - 02:16 round 8: ring_mcp 0.71→0.76, thumb_abd 0.79→0.81. ring_abd 0.55
    unchanged for eight rounds.
  - 02:16 Restart (scores erased): fresh run scored only against GT_01 from here.
  - 02:18 clean round 1 vs GT_01 (this is the hand's true state after ~8
    rounds): index_abd 1.10, index_mcp 0.97, index_pip 0.98, middle_abd 0.95,
    pinky_abd 0.96, pinky_mcp 0.95, ring_pip 0.95, thumb_mcp 0.90, middle
    mcp/pip 0.89, pinky_pip 0.87, ring_mcp 0.81, thumb_cmc 0.80, thumb_dip
    0.80, thumb_abd 0.78, ring_abd 0.51. Index abd exceeding GT_01 by 10 %
    means ser-9097's index abd travel (40.2° motor) is on the small side for
    the baseline; revisit once a few hands are in.
  - 02:19 round 2: thumb_abd 0.78→0.90, ring_mcp 0.81→0.87, ring_pip 1.00,
    thumb_dip 0.82. ring_abd 0.51 unchanged.
  - 02:20 round 3: ring_mcp 0.87→0.91, ring_abd 0.51→0.53 (first movement in
    eleven rounds; still half).
  - 02:21 round 4: ring_abd 0.53→0.91 in one round (whatever was holding it
    back was mechanical, not tension), ring_pip 1.04. Hand now ≥ 0.80
    everywhere; lowest: thumb_cmc 0.80, thumb_dip 0.82, pinky_pip 0.87.
  - 02:22 full manual calibration, snapshot manual_2026-10-16T00-22-47
    (complete, wrist too). Motor travel vs GT_01 (ser-9097): within ±5 % on
    13 of 17 joints; index_abd 1.09, ring_abd 1.08, middle_abd 1.05 larger;
    thumb_dip 0.86 smaller (93.6° vs 109.3°). Cross-hand travel agrees to
    about 5 % except thumb_dip, so GT_01 is a usable baseline for the fleet;
    revisit thumb_dip after a third hand. Probe started straight from the
    finished-calibration dialog (new button works on hardware).
  - 02:26 probe GT_tension_04 (mid-range, vs GT_01 calibration), scored
    against GT_tension_03: 18 ok, 6 under, 6 over of 30 scored sides.
    Direct slack (stalled take-up): index_pip extend 36°, middle_pip extend
    8.4°, thumb_mcp extend 3.1° — these extensor sides need clicks. Under by
    breakaway: thumb_mcp ext 30 mA, index_pip ext 30, ring_abd ext 80 (vs
    130), ring_mcp flex 30 (vs 80), pinky_pip 30/30 (vs 90/90, runs free to
    the cap). Over: middle_abd 150/140 (vs 90/90), pinky_abd 150/140 (vs
    50/50), pinky_mcp 80/90 (vs 30/50). Thumb cmc/abd flex 230/220 mA (vs
    180/170): both hands stiff there; extend sides skipped at the limit again
    (mid-range of thumb cmc/abd is still within 10° of a motor limit — the
    probe's limit margin bites on these short-travel joints).

### 2026-10-16 — a one-hand reference inherits that hand's flaws
- GT_tension_03's pinky_abd (50 mA with a 12° dead zone) and pinky_mcp
  (30/50 mA, free joint) were themselves not well tensioned, so ser-9785's
  healthy pinky scores "over" against them. The reference for breakaway
  should be a per-joint band built from several well-tensioned hands (median
  ± noise), not one hand. Keep GT_tension_03 as the reference until a third
  hand is in, then replace the per-joint reference with fleet medians.
- The take-up column is the trustworthy actionable signal: a stalled free
  travel of several degrees is slack on that tendon side, independent of any
  reference. Index_pip extend 36° on ser-9785 is the clearest case so far.
- Thumb cmc/abd extend probes get skipped from mid-range because the pose
  move never got there: GT_tension_04's centre for thumb_cmc sat 6° from the
  extend limit (should be ~30°). The move ran at the 200 mA hold current and
  those joints break away at 230 mA. Fixed in core: the pose move uses its
  own pose_current_ma (350 mA default) and the probe reports joints that
  ended more than 10° from the pose (`pose_short`); the dialog shows them.
  Takes effect after the console is restarted.
  - 02:33 round 1 of a restarted run, first scoring after the manual
    calibration: most joints read ~0.10 LOWER than the 02:18 clean round 1
    with the same tendons (index_abd 1.10→0.91, index_pip 0.98→0.86,
    middle_pip 0.89→0.79, ring_mcp 0.91→0.81, thumb_abd 0.90→0.76, pinky_abd
    0.96→0.86; ring_abd 0.53→0.89 is the one real gain). Either the probe's
    extend-side slack take-up is not it (no clicks between the two), or the
    range check's measured spread depends on the calibration in force (the
    stage poses are driven through the calibrated joint→motor map). Watch
    this: if scores shift with every recalibration, the guided score needs
    to be reported in raw motor degrees, not only as a fraction.
  - 02:35 round 2: middle_pip 0.79→0.90, ring_mcp 0.81→0.96, middle_mcp
    0.84→0.94, thumb_abd 0.76→0.81. Index_pip stays 0.86 (its 36° extend
    slack not yet taken up?). Lowest now: thumb_abd 0.81, thumb_dip 0.82,
    thumb_cmc 0.84, index_pip 0.86, pinky_abd 0.86.
  - 02:36 round 3, run ended: thumb_cmc 0.84→0.89, thumb_abd 0.81→0.84.
    Nothing else changed. State: all ≥ 0.82; thumb_dip 0.82, thumb_abd 0.84,
    index_pip 0.86, pinky_abd 0.86 lowest.
  - 02:37 second full manual calibration (manual_2026-10-16T00-37-22), 15 min
    and three tensioning rounds after the first: median |diff| 0.5° motor,
    max 5.2° (ring_mcp 122.5→127.7, clicked in between); thumb_dip +1.9,
    pinky_mcp +1.6, pinky_pip +1.2. Manual calibration repeats to ~0.5° on
    untouched joints — far below the ~10 % swing seen in the guided score
    after recalibration, so that swing is not calibration noise. Probe
    started right after (GT_tension_05 pending).

### 2026-10-16 — manual calibration repeatability
- Same hand, same operator, 15 min apart: 13 of 17 joints within 1° of motor
  travel; the four that moved more had been clicked in between. The manual
  hardstop capture is repeatable enough to be the baseline source.
  - 02:41 probe GT_tension_05 (after 3 rounds + recalibration; still the old
    probe code, so thumb cmc/abd again sat 1–3° from the extend limit).
    Breakaway 04→05 where clicks went in: ring_mcp 30/30→140/120 (score
    0.81→0.96), middle_mcp 30/30→140/140 (0.84→0.94), thumb_mcp 90/30→160/120
    (0.87→0.90), middle_pip 80/70→100/90 with extend slack 8.4°→1.5°
    (0.79→0.90). Breakaway tracks clicks strongly: a joint that ran free to
    the cap at 30 mA becomes a 120–140 mA joint with zero dead zone after
    one round. That is the "well tensioned" signature.
    Joints that got LOOSER with no clicks on them: thumb_dip 100/100→50/50
    with a new 22° extend dead zone (was 1.6°); index_pip flex 80→40 with a
    new 20° flex dead zone, extend dead zone still 39°; index_mcp 140→110.
    Scores on those stayed flat (0.82 / 0.86). A tendon that loses 50 mA and
    gains 20° of slack in 15 minutes is slipping: check the index_pip and
    thumb_dip spool ratchets / tendon knots on ser-9785.
    Unchanged free joints: ring_pip 30/30, pinky_pip 30/30 (both run to the
    cap at 60 mA, 0 dead zone) — these have no preload at all yet scored
    1.01 / 0.95 on travel: travel fraction alone cannot see missing preload.

### 2026-10-16 — what the two signals mean, from ser-9785
- Travel fraction (guided score) saturates near 1.0 before the tendon has
  any preload: ring_pip / pinky_pip score ≥ 0.95 while breaking away at
  30 mA and running free. Breakaway is the only signal that sees preload.
- Breakaway jumps from ~30 to 120–160 mA within one round of clicks on a
  taut tendon; untouched taut joints repeat within 10–30 mA. So a per-joint
  "well tensioned" band of roughly 90–160 mA breakaway with < 3° dead zone
  fits every joint that was deliberately tensioned on both hands; thumb
  cmc/abd sit at 170–250 mA on both and may simply be stiffer joints.

### 2026-10-16 — probe repeatability and post-tensioning relaxation (ser-9097)
- GT_tension_03 vs 04 on the right hand, same settings and pose, one hour
  apart, nothing ratcheted in between: breakaway |diff| median 10 mA, 75th
  percentile 20 mA over 31 sides. Noise band for the verdict: ±20 mA, i.e.
  two ramp steps. Take-up dead zones repeat to ~1° (pinky_abd 12.1→12.2,
  pinky_mcp 38.7→38.6, ring_mcp ext 3.9→3.4).
- The outliers are not noise, they are relaxation: thumb_cmc flex 180→140
  with a new 15.6° extend dead zone, thumb_dip 90/80→60/60 with a new 12.7°
  extend dead zone, middle_pip flex 70→20. The same joints relaxed on
  ser-9785 between GT_tension_04 and 05 (thumb_dip 100→50 + 22° dead zone,
  index_pip 80→40 + 20° dead zone). Freshly ratcheted tendons lose 30–50 mA
  and gain 10–20° of slack within an hour; thumb_dip does it on both hands.
  Either the tendon/knot settles after loading or those spools' ratchets
  creep back a tooth. Consequence: probe twice — right after tensioning and
  again after ~30–60 min (or after a calibration) — and only call a hand
  done on the second probe. Worth checking the thumb_dip spool pawl on both.
  - 02:54–02:56 hold-and-ratchet tension (2 min hold) after the relaxation
    finding; no scores from this dialog. Next probe tells what it did.
- 09784BB1BE210831 (orcahand-left; board reports its raw UID, no ser- label
  assigned) — 2026-10-16 02:58 guided round 1 vs GT_01: ring_abd 0.47,
  thumb_cmc 0.55, ring_pip 0.65, ring_mcp 0.66, pinky_pip 0.78, index_pip
  0.80, thumb_dip 0.81; rest 0.85–0.99. Same pattern as ser-9785's start:
  the ring finger and thumb_cmc arrive loosest.
  - 03:01 round 1 again (run restarted twice, three minutes after the 02:58
    round 1, nothing ratcheted that we know of): index_abd 0.94→0.74,
    middle_abd 0.86→0.60, middle_mcp 0.88→0.78, index_pip 0.80→0.71,
    ring_mcp 0.66→0.57, ring_pip 0.65→0.78. Two range checks of the same
    loose hand differ by up to 0.26. On a loose hand the range check is not
    repeatable round to round: slack tendons let the finger settle
    differently each time it is posed. Treat guided scores below ~0.8 as
    "loose", not as a number; the fraction only becomes meaningful once the
    tendons are taut (ser-9785's clean rounds repeated within ~0.05).
- ser-7339 (orcahand-right) — 2026-10-16 03:11 guided round 1 vs GT_01, a
  fresh untensioned hand: thumb_cmc 0.08, thumb_abd 0.06, thumb_dip 0.03,
  middle_abd 0.03, ring_abd 0.04, index_pip 0.29, thumb_mcp 0.26, pinky_abd
  0.30, pinky_pip 0.32, index_abd 0.32, ring_mcp 0.36, pinky_mcp 0.48,
  middle_mcp 0.57, ring_pip 0.58, index_mcp 0.63, middle_pip 0.79. This is
  what "straight from assembly" looks like: abductions and thumb near zero.
  - 03:15 round 2: big first-round gains on the fingers — thumb_mcp 0.26→0.73,
    thumb_dip 0.03→0.81, index_abd 0.32→0.81, index_pip 0.29→0.86, ring_mcp
    0.36→0.84, pinky_mcp/pip 0.90/0.91, ring_pip 0.88. Still near zero:
    thumb_cmc 0.15, thumb_abd 0.13, ring_abd 0.09; pinky_abd 0.30, middle_abd
    0.56, index_mcp 0.66.
  - 03:18 round 3: thumb_cmc 0.15→0.65, thumb_abd 0.13→0.65, pinky_abd
    0.30→0.76, thumb_mcp 0.92, middle_mcp 0.94, ring_mcp 0.93, ring_pip 0.95.
    ring_abd 0.10 unchanged (third hand in a row where ring_abd is the last
    to come up); middle_abd 0.56, middle_pip 0.79, index_abd 0.81 flat.
  - 03:20 round 4: middle_abd 0.56→0.90, ring_abd 0.10→0.47, middle_pip
    0.79→0.92, pinky_abd 0.87. Lowest: ring_abd 0.47, thumb_cmc/abd 0.65,
    index_abd 0.81; everything else ≥ 0.85.
  - 03:24 round 5: thumb_cmc 0.65→0.86, ring_abd 0.47→0.55. thumb_abd 0.67
    flat. Lowest: ring_abd 0.55, thumb_abd 0.67; rest ≥ 0.84.
  - 03:25 round 6: ring_abd 0.55→0.76, nothing else changed. thumb_abd 0.67
    is now the only joint under 0.76 and has been flat for three rounds.
  - 03:27 round 7: guided tensioning COMPLETED (every joint ≥ 0.85 pass
    fraction) — 7 rounds, ~16 min from an untensioned hand. Final spreads in
    last_tension.yaml (progress entry cleared on completion). Manual
    calibration started straight after.
  - 03:28 full manual calibration manual_2026-10-16T01-28-37 (complete).
    Travel vs GT_01: 14 of 16 finger joints within ±5 %; index_abd 1.08,
    middle_abd 1.06, ring_abd 1.05 larger again (same three as ser-9785, so
    GT_01's abduction travels are ~6 % small for the fleet); thumb_dip 0.91
    (GT_01's 109° is large; 9785 and 7339 have 95–99°). vs ser-9785: all
    finger joints within ±8 %. WRIST: 102.7° vs 147° on both other hands —
    one wrist end stop was not reached or was recorded early; redo the wrist
    (Calibrate settings → redo wrist) before trusting wrist ROM on ser-7339.

### 2026-10-16 — three hands calibrated: fleet travel table
- Finger-joint motor travel agrees across ser-9097 (auto), ser-9785 and
  ser-7339 (manual) to within ±8 % everywhere, ±5 % on most joints. A
  per-joint median of the three is a better baseline than any one hand:
  saved as FLEET_01 in both model folders (not activated; GT_01 stays the
  scoring baseline until the user switches). Wrist taken from GT_01.
  - 03:32 probe GT_tension_05 (right folder; first run on the new probe
    code): 0 skipped — the pose fix works, thumb cmc/abd centred with ~30°
    room each side (was 1–6° before). Result right after passing guided
    tensioning at ≥ 0.85 everywhere:
    · preloaded (90–200 mA, no dead zone): thumb_abd 170/160, middle_abd
      200/180, ring_abd 130/140, pinky_abd 120/120, pinky_mcp 90/100,
      thumb_dip 80/80, thumb_cmc 120/70, index_abd 70/80 (5° flex slack).
    · NO preload (30–60 mA, finger runs 25–40° both ways at 60 mA): index_mcp,
      index_pip, middle_mcp, middle_pip, ring_mcp, ring_pip, pinky_pip, and
      thumb_mcp (40/50 with a 37° flex dead zone).
    So a hand that passes the guided travel check can still have every
    finger MCP/PIP at zero preload. On ser-9785 the same joints went from
    30 to 120–140 mA after one more round of clicks with almost no change in
    travel score. The guided pass criterion is necessary but not sufficient;
    the probe's breakaway is the second gate.
    Reference caveat again: ser-9097's own ring_pip/pinky_pip/middle_mcp were
    at 30 mA too, so "ok 100 %" there means "as unpreloaded as the reference".

### 2026-10-16 — the gap in the pass criterion (three hands)
- Guided tensioning passes on travel fraction alone. All three hands reached
  ≥ 0.85 travel while 6–8 finger MCP/PIP tendons still broke away at 30 mA
  with the finger running free. Proposal for the UI verdict: a joint is
  "done" only when travel ≥ pass AND breakaway ≥ ~70 mA on both sides AND
  stalled take-up < 3°. Open question for the user: is a free 30 mA PIP
  acceptable on purpose (low friction, full range) or should every joint
  carry preload? The band's lower edge depends on that answer.
  - 03:34–03:40 run-in, then 03:41 guided round 1 (fresh entry): scores fell
    across the hand compared with the 03:27 pass — index_abd 0.98→0.39,
    ring_abd 0.92→0.28, middle_abd 0.90→0.65, thumb_cmc 0.86→0.75, thumb_mcp
    0.92→0.75, thumb_abd 0.86→0.77, index_mcp 0.86→0.79. Abductions lost the
    most. The run-in cycling bedded the tendons in and took the fresh tension
    out of them: this is the relaxation seen on the other two hands, now
    with a clear trigger.

### 2026-10-16 — run-in undoes a fresh tensioning
- Cycling the joints right after a guided pass drops the travel score by
  0.1–0.6, worst on abductions. A hand is not tensioned until it has been
  run in and re-tensioned: the loop should be tension → run-in → tension
  (→ calibrate → probe), and the UI should not call a hand done on a pass
  that has not survived a run-in.
  - 03:42 round 2 after run-in: no joint improved on round 1 (best values
    unchanged), so this round's spreads were all at or below the previous.
- ser-7577 (orcahand-left, FEETECH motors — user, 04:2x) — 2026-10-16 04:11 guided round 1 vs GT_01
  (fourth hand; possibly the board-UID hand from 02:58 after its serial was
  assigned, or a new one): thumb_cmc 0.41, ring_mcp 0.67, index_pip 0.78,
  thumb_dip 0.81, middle_abd 0.82; rest 0.86–1.00. Arrives much tighter than
  ser-7339 did; thumb_cmc is again the loosest joint.
  - 04:17 round 2: thumb_cmc 0.41→0.81, index_pip 0.78→0.96, thumb_abd 0.94,
    index_abd 1.05, ring_abd 1.01. Only ring_mcp 0.73 left under 0.81.
  - 04:19 guided tensioning COMPLETED after 2 rounds (~8 min); every joint
    ≥ 0.85, lowest middle_abd 0.88, ring_mcp 0.73→0.95. Fastest hand so far. Needs the run-in → re-tension check
    before it counts as done (see ser-7339).
  - 04:21 full manual calibration manual_2026-10-16T02-21-03 (complete,
    wrist 145° — good). vs FLEET_01: 15 of 17 within ±5 %; thumb_cmc 1.10
    (66° — largest of the four hands), middle_abd 0.92, pinky_mcp 0.92,
    index_pip 0.93. Four hands now agree on finger travel to ±10 %, most
    joints ±5 %. Probe started right after.

### 2026-10-16 — Feetech hands are a separate population for currents
- ser-7577 runs Feetech motors. Motor-degree travel is comparable (its
  calibration matched FLEET_01 within ±10 %), but every current is not:
  the config's guided-tension holds are ~1.9× Dynamixel (abd 380/200,
  mcp 320/140, pip 280/100, tension 800/400). Breakaway currents from a
  Feetech probe must not be scored against GT_tension_03 (Dynamixel).
  Probe datasets are now tagged with motor_type; the dialog only scores
  against a same-family reference; Feetech probe defaults are the Dynamixel
  ones ×2 (hold 400, take-up 120, ramp 40→600 by 20, pose 600 mA). The probe
  run at 04:21 on ser-7577 used the Dynamixel defaults (old code) — treat
  its currents as provisional. A Feetech reference probe is still needed.
  - 04:26 probe GT_tension_06 (left folder) on the Feetech hand with the
    Dynamixel settings (hold 200, ramp to 300 mA, take-up 60): unusable as
    a tension measurement — 17 of 32 breakaway sides never moved 2° before
    the 300 mA ramp ceiling (reported None), 4 skipped, and the sides that
    did move did so at the very first 20 mA step. The 60 mA take-up barely
    moved anything. Confirms Feetech needs the doubled defaults (ramp to
    600 mA) and the ramp ceiling may need to go higher still; rerun after
    the console restart and pick that run as the Feetech reference.
  - 04:27–04:31 run-in, then guided tensioning again: COMPLETED at 04:35
    after 2 rounds, every joint ≥ 0.85 (min thumb_cmc 0.88, several joints
    ≥ 1.0). Unlike ser-7339 (Dynamixel, scores fell 0.1–0.6 after run-in),
    this Feetech hand held its tension through the run-in: the post-run-in
    spreads equal or exceed the pre-run-in pass. First hand to survive the
    run-in check. Candidate for the Feetech reference probe once re-probed
    with Feetech settings.
- ser-1943 (orcahand-left, Dynamixel — user, 04:37) — 2026-10-16 04:41
  guided round 2 vs GT_01 (round 1 was the all-zero start entry): thumb_cmc
  0.11, thumb_abd 0.20, pinky_abd 0.32, index_abd 0.36, ring_abd 0.52,
  middle_abd 0.54, thumb_mcp 0.63, middle_mcp 0.65, index_mcp 0.66, ring_mcp
  0.73; PIPs 0.82–0.89, thumb_dip 0.80. Fresh hand: abductions and thumb
  loosest, same as ser-7339.
  - 04:46 round 3: MCPs all ≥ 0.84 (thumb_mcp 0.63→0.86, index_mcp 0.90,
    ring_mcp 0.91), index_abd 0.36→0.74, pinky_abd 0.32→0.64. Still low:
    thumb_cmc 0.32, thumb_abd 0.34, ring_abd 0.52, middle_abd 0.66.
  - 04:49 round 4: thumb_cmc 0.32→0.46, pinky_abd 0.64→0.77, PIPs ≥ 0.90.
    thumb_abd 0.36, ring_abd 0.52, middle_abd 0.66 flat.
  - 04:52 round 5: thumb_cmc 0.46→0.87, thumb_abd 0.36→0.85, ring_abd
    0.52→0.71, index_abd 0.88, pinky_abd 0.89. Only middle_abd and ring_abd
    (0.71) left under 0.85.
  - 04:53 round 6: ring_abd 0.71→0.98. middle_abd 0.72 is the last joint
    under 0.85.
  - 04:53 round 7: middle_abd 0.72→0.88; every joint now ≥ 0.85 (min
    thumb_dip 0.85). Pass expected on the next check; ~16 min, 7 rounds —
    same as ser-7339 (Dynamixel), vs 2 rounds for the Feetech ser-7577.
  - 04:54 full manual calibration manual_2026-10-16T02-54-35 (complete,
    wrist 148.5°): EVERY joint within ±5 % of FLEET_01 — the closest match
    of the five hands. Fleet table holds. Probe started right after.
  - 04:58 probe GT_tension_07 (left folder, Dynamixel settings, 0 skipped,
    thumb centred). Preloaded ≥ 70 mA: all thumb sides except cmc extend,
    index_pip flex 130, middle_pip 140/120, ring_mcp 90/90, ring_abd flex
    100, pinky_abd 80/80, middle_abd flex 90. Free < 70 mA: ring_pip 40/40,
    pinky_pip 30/30, pinky_mcp 50/60, middle_mcp flex 20, thumb_cmc extend
    20 (18° free run), ring_abd extend 60. Dead zones: index_abd 12°/9°,
    index_mcp ext 8°, middle_abd ext 8°, middle_mcp ext 6°, index_pip ext 3°.
    Run-in started at 04:58; the next guided round tests relaxation.

### 2026-10-16 — the same four joints read "free" on every Dynamixel hand
- ring_pip, pinky_pip, pinky_mcp and middle_mcp break away at 20–60 mA and
  run to the cap on ser-9097, ser-9785, ser-7339 and ser-1943 alike, right
  after each passed guided tensioning. Four of four. Either those joints are
  mechanically freer by design (short tendon path, low routing friction) or
  the ratchet geometry there cannot build preload. Either way the "well
  tensioned" band must be per joint, not one number: those four get a low
  floor (~20 mA), the thumb and abductions ~80–200 mA, the other MCP/PIPs
  ~70–150 mA. Breakaway medians across the four Dynamixel hands are the
  natural per-joint reference, replacing the single-hand GT_tension_03.
  - 04:58–05:04 run-in, then guided round (Resume, so the best table hides
    drops; the run's own score says 15 of 16 joints passed on the first
    post-run-in range check). This Dynamixel hand held its tension through
    the run-in, unlike ser-7339 (which fell to 8/16). So the post-run-in
    loss is per hand, not per motor family; ser-7339's drop may have been a
    tendon/knot settling. Rule stands: pass must be confirmed after run-in.
  - 05:06 CORRECTION. The run was restarted (scores erased) and the clean
    round 1 after the run-in passed only 7 of 16: thumb_abd 0.88→0.68,
    ring_abd 0.98→0.64, middle_abd 0.88→0.69, index_abd 0.88→0.73, pinky_abd
    0.89→0.77, thumb_mcp 0.86→0.82, index_mcp 0.90→0.81. So ser-1943 DID
    relax after the run-in, abductions worst, exactly like ser-7339. The
    earlier "15 of 16 passed" came from a Resume: a resumed run counts a
    joint as passed on its stored best, not on the round it just measured.
    The same applies to ser-7577's "survived the run-in" at 04:35 — its
    completion spreads equal its pre-run-in bests, so that was a Resume
    reporting history, not a fresh measurement. Withdraw both claims.

### 2026-10-16 — Resume hides relaxation (console behaviour to change)
- Guided tensioning scores a joint against the best spread ever recorded
  for the hand. After a run-in, a Resume therefore reports the hand as
  still passing even when every abduction has dropped 0.2–0.3. Only a
  Restart shows the true state. Change: score the pass on the current
  round's spread (keep the best for history), and show both; make the
  post-run-in check a Restart by default. Until then: always Restart after
  a run-in.
- With that, run-in relaxation is 3 for 3 (ser-7339, ser-7577 unknown but
  unverified, ser-1943 confirmed): abductions lose 0.2–0.35, thumb and
  MCPs 0.05–0.1, PIPs ~0. The loop tension → run-in → Restart → tension is
  mandatory, not optional.
  - 05:09 round 2 after the restart (re-tensioning post run-in): 11 of 16
    pass on this round's own spread; abductions back to thumb_abd 0.84,
    ring_abd 0.87, pinky_abd 0.87, middle_abd 0.82, index_abd 0.79; thumb_cmc
    0.85. Still under: index_abd 0.79, index_mcp 0.81, thumb_dip 0.82,
    middle_abd 0.82.
  - 05:10 round 3: 11 of 16 again, no best value moved — a round without
    effective clicks.

### 2026-10-16 — range check rebuilt: slack in degrees, settled ends, no carry-over
Built after the review (core `feature/improve-calibration`, console
`orca_ui_calibration`, both uncommitted; console needs a restart to pick it up):
- Pass criterion is now `expected travel − swept spread` in motor degrees per
  joint ("slack"), against a tolerance per group: AP 3°, MCP 5°, PIP 5°
  (editable live, `pass:<group>=<deg>`, bounds 0.5–30°). The 85 % fraction
  is gone; it allowed 22° on the wrist and 6° on an abduction.
- Only settled positions become ends: the motor must move < 1° between
  4 consecutive samples (0.2 s). A fast flick that overshoots the hardstop and
  springs back is not recorded. Hold each end still for a moment.
- Each end must be reached twice (within 2°, after leaving it by ≥ 25 % of the
  travel). Within tolerance but one visit → status `unconfirmed` ("again"),
  not a pass and not a ratchet target.
- Every round scores its own sweep. `tension_progress.yaml` now stores the
  last round's `scores` (slack, fraction, status) and the round count, nothing
  is kept as "best", and no stage is skipped on Continue (was "Resume").
- Probe gate: the hand's newest probe (if newer than its last completed
  tensioning) feeds stalled take-up free travel per joint into round 1; a
  joint above its tolerance there scores `slack` and must be tensioned before
  the sweep can pass it. Dropped after the first ratchet step.
- Clicks remaining: `probes.click_model()` averages saved click tests
  (take-up degrees per click, per joint, fleet mean as fallback); the ratchet
  step shows "~N clicks" per joint once a click test exists, slack° until then.
- Self-referencing slack estimate (idea 2, analysis form): after a calibration
  of the same hand that follows its last completed tensioning, the Calibrate
  step shows per joint (motor-driven travel − hand-swept travel)/2 = slack and
  (sum)/2 = the hand's own travel. The full motor-driven sweep inside the
  range check is still to build.
- FLEET_01 is now the active travel baseline in both model folders (was
  GT_01). Its abductions are ~6 % longer than GT_01, so abduction slack reads
  ~2–3° higher than yesterday's numbers would suggest.
- `scripts/click_test.py` rewritten: several joints per session, take-up and
  breakaway per click, per-joint and mean summary, saves per joint under
  `clicks/` with the structure the console's click model reads. Mock smoke
  test passes (values trivial on the mock).
Open: tolerance defaults are a first guess from yesterday's noise (taut hands
repeat to ~0.05 of travel = 2–6°); tune after the first hands run with the
new check. Hold-current drag on stiff joints (ser-7339 wrist 103° vs 147°) is
still untested.

### 2026-10-16 — verification sweep of the rebuilt range check
- Independent review + mock-console end-to-end run (isolated copy of the model
  folder, port 5057): scoring, settle gate, two-visit rule, probe gate, keys
  consumed by the frontend, and the hardware command paths (hold, pull,
  currents untouched) all checked out. Fixed on the way:
  - Each stage's sweep is now measured from the pose held FOR THAT STAGE. The
    old sampler kept the round's first centre for every stage, so a finger
    re-posed between stages (every abduction: "fully away" → "centred") had its
    spread anchored to a stale zero — inflated when the sweep crossed it, and
    with the new two-visit rule never confirmable. This likely contributed to
    yesterday's abduction noise on loose hands.
  - Take-up results that got within 3.5° of the travel cap are "ran free", not
    slack: the probe decelerates for its goal and flags them `stalled`. On
    GT_tension_03/04 that is exactly the four free joints (middle_mcp,
    ring_pip, pinky_mcp flex, plus thumb_cmc/pinky_abd where the cap is the
    limit margin). The probe gate and the click test now skip them; real slack
    on ser-9097's GT_tension_04 is thumb_dip 12.7°, pinky_mcp extend 18.0°,
    middle_pip 3.7°, ring_mcp 3.4°. Yesterday's "stalled ≥ 3° = slack" rule
    needs this cap exclusion.
  - Core CLI `scripts/guided_tension.py` moved to `--pass-slack-deg`; mock
    motors carry the full row shape (hit counts, fault); click-count fallback
    uses the fleet mean when a joint's own per-click mean is ≤ 0.
- Left as is: the stage "passed" navigation helpers are now constants (every
  round checks every stage); rebooting a latched motor during the pose step
  holds it at the global current (pre-existing).

### 2026-10-19 — the touch hand scored against the wrong table; tool split into two pages
- ser-0191 (orcahand-touch-right) ran the rebuilt range check and read 10–56°
  of slack on every joint. Two causes: the touch folder has no travel
  baselines file, so it fell back to the shared v2.1 table (MCPs/PIPs 10–30°
  above any measured hand), and even against FLEET_01 a hand sweep falls
  short of motor-driven calibration travel by ~4–7° on the MCPs and 16–33° on
  abductions, thumb and PIPs. Calibration loads the tendon past where a hand
  can push, so the degree-based rule can never pass those groups against a
  calibration table. Only pinky_mcp (−55°) and ring_abd (−31°) looked like
  real slack.
- The touch/joint/full folders never had anything but the shared table; only
  right/left diverged because baselines were recorded there.
- Decision: the Setup page now has two pages. "ccc" is the page as committed
  (fraction scoring: spread ≥ 85 % of the config's expected travel, best kept
  across rounds, passed stages skipped, ends recorded on every sample), plus
  the manual-calibration Back option and latched-fault handling. "kai" carries
  the newer tooling (slack in degrees against the active baseline, settled and
  twice-reached ends, no carry-over, probe gate, click counts, probes,
  baselines, slack estimate). One core routine, `scoring="fraction"|"slack"`;
  `tension_progress.yaml` keeps the fraction record at the top level and the
  slack record under `slack:`, so neither page sees the other's numbers.
- Reverted: the Feetech tension current back to 580 mA (core constants and all
  eight model configs; the installed copy too).
- Verified on an isolated mock console: both scorings start, stream rows in
  their own shape, take live threshold changes in their own unit, save and
  resume their own progress; `hand_info` carries `tension_progress` (fraction)
  and `tension_progress_slack`. Core 53 tests, console 446 + the known
  environmental failure, frontend typecheck/lint/build clean. Not yet run on a
  hand; the console still needs a restart to pick any of this up.

### 2026-10-20 — index ranges in Clemens's table overshoot every hand; "Measure slack" added to the ccc page

Hand 7CFBEC24BE210835 (orcahand-right, 9 rounds, fraction scoring) was tensioned
well by feel, yet index_mcp stopped at 0.846 and index_pip at 0.714 of the
`joint_motor_travel_v21` table. The table says index_mcp 139.39° and index_pip
131.04° of motor travel (pass at 85 %: 118.5° and 111.4°). The motor-driven
calibration right after found 125.51° and 99.84°. Every calibration recorded so
far (ten hands, both folders) puts index_mcp at 113.8–125.5° and index_pip at
93.5–106.9°, so the table's index_pip is 24–37° above anything a hand reaches
with the motors, and 85 % of it (111.4°) is above every calibration. The
tensioning spreads above the calibration travel (ser-9097 index_mcp 135°,
ser-9785 134.7°) are hands with slack: a hand push turns the motor past the
taut travel. Decision pending: adjust the index entries (and check the rest of
the table against the calibration log) without touching the pass rule.

The ccc page gained "Measure slack" (Tension and Calibrate steps, and the done
step of both tensioning dialogs). It runs the existing tension probe (take-up
at 60 mA, breakaway ramp 20→300 mA) and shows only the measurement: per joint
the largest stalled take-up as slack, per side take-up and "breakaway → joint
follows" currents. No reference, no verdicts; the run is still saved as
GT_tension_NN. What to do with the numbers is the next step.

### 2026-10-20 (afternoon) — travel table set to the fleet averages; take-up dropped, breakaway averaged over passes

`joint_motor_travel_v21` in all eight v2 configs now holds the integer average
calibration travel of the six Dynamixel hands (ser-9097, ser-9785, ser-7339,
ser-1943, 09784BB1BE210831, 7CFBEC24BE210835; ser-7577 excluded). Saved
`best`/`last_tension` fractions were rescaled so their degrees are unchanged.
Wrist left at 156.18 (not in the range check; readings bimodal).

GT_tension_06 on 7CFBEC24BE210835 (well tensioned by feel) showed the take-up
method cannot measure slack: at 60 mA the finger follows the motor on the long
tendons (20–40° of travel, five sides to the cap) and the method reads that as
slack or "free". The ser-9097 reference only looked clean because 60 mA did not
move its fingers. Breakaway on this hand is 30–50 mA on the long tendons where
ser-9097 needed 90–140 mA: it measures how hard the finger is to move.

Decision: breakaway is the measurement. Ramp now starts at 10 mA in 5 mA
steps, "moved" is 1°, and the whole sequence runs `repeats` passes (default 5
in the console) from the same held pose; the dialog shows the mean and min–max
per side plus the flex/extend balance (weaker side under 70 % of the other =
flagged). Take-up is no longer run by default. The next measurement on this
hand, kept as the well-tensioned reference, defines the currents a tensioned
joint needs. Slack measurement idea for later: drive to one extreme, come back
at low current, and measure how far the motor goes before the current to keep
moving reaches the reference breakaway.

Open: `joint_roms` in the config is not a measurement (hand-edited 2026-03/04/09);
calibration maps the motor span onto it, so joint degrees are a convention. The
user will supply the CAD stop angles; until then tensioning and calibration are
unaffected (both run in motor degrees).

### 2026-10-20 (evening) — calibration in three parts: slack test, calibrate, measure tension

GT_tension_07 (7CFBEC24BE210835, five breakaway passes, 160 results) is the
breakaway reference. The user judged the hand well tensioned apart from one
slightly over-tensioned joint ("i-dip"; which joint that is remains to be
named).

Decision: breakaway alone is one number at one pose. The tension measurement
is now a sweep: each joint driven at 30°/s between its two calibrated motor
limits (2° margin) and back, the present current sampled at 20 Hz against the
position, the others holding at 200 mA from the mid-range pose. Per sweep the
mean |current| over the central 60 % of the travel is the tension level, the
mean over the last fifth is the preload into the stop, and the travel after
the reversal before the current stays above 25 mA for three samples is the
dead band (slack). A reference sweep (`tension_sweeps.yaml`, GT_sweep_NN) is
the well-tensioned hand; later sweeps are scored per joint and side: mean
under 70 % of the reference = under-tensioned, over 140 % = over-tensioned,
dead band more than 8° wider = slack. The tower view marks the spools.

The slack test replaces the take-up idea: every finger motor at once aims half
a turn away at 20 mA (choices 10–40), first positive then negative, and the
degrees each spool turns before stalling are its slack per direction. A spool
that completes the half turn (within 5°) has nothing holding it, the test is
saved as blocked (`slack_tests.yaml`) and calibration is refused (HTTP 409)
until a later test on the same hand passes. The Calibrate step of the Setup
tab now shows a) slack test, b) calibrate, c) measure tension; the tensioning
dialogs end with "Slack test"; the breakaway probe stays under the settings.

Open on hardware: whether an XC330 turns at all at 20 mA with the tendon slack
(if its own friction needs more, every joint reads taut), and the sweep's
current curves on the real hand (level, noise, how the position loop at 300 mA
reads into the stop). Next step after that: measure, ratchet one click,
measure again, to turn a tension deficit into a click count.

Addendum (same evening): a tension check sits inside the tensioning loop, before
any calibration. It is the breakaway probe started with `ignore_calibration`:
the hand holds where it stands, the stale motor limits are ignored so every
side is probed the full 40° cap, and the passes are averaged as before. The
dialog scores each side against the breakaway reference (GT_tension_07): under
75 % = ratchet that spool, over 150 % = too tight, and marks the spools on the
tower. It is advice between rounds; the sweep after calibration is the exact
check. Flow: tension → slack test → tension check → (tension again) →
calibrate → measure tension. Datasets from a check carry `check: true`.

### 2026-10-21 — first full sweep read; the loop reworked around a faster check

GT_sweep_00 (7CFBEC24BE210835, after the user's calibration, one pass, 32
sweeps, now the sweep reference) is readable on about half the joints and
shows three things to fix, all fixed in the console today:

- The level is clear where the tendon loads the motor: thumb cmc 84/58 mA
  (flex/extend), ring mcp 56/55, pinky pip 47/46, thumb abd 51/55, middle abd
  56/62, pinky mcp 36/38, thumb mcp 38/35.
- Four joints ran under the 25 mA dead-band level almost the whole travel
  (thumb dip 10/9 mA, middle mcp 13/9, middle pip 7/9, ring pip 6/7): on these
  the dead band reads ~100° and is meaningless, and a ratio against a 6 mA
  reference is noise. The comparison now treats a difference inside 5 mA as
  "ok" whatever the ratio.
- Three sides stalled against a stop at the 300 mA sweep current (index mcp
  flex 17° short at 293 mA, index pip flex 8° short at 271 mA, ring abd flex
  the whole way at 273 mA): the calibration's limit is further than the sweep
  pose reaches, so the motor pushed into the stop. Worse, every sweep then sat
  against its far stop at full current until the walk's deadline (10–18 s
  each, the whole run ~8 min): the walk ended only within 1° of the target.
  The walk now ends half a second after the motor stops moving at its goal.
  Those stalled sides' end currents are the stop, not the tendon.

Decisions:

- Sweep bands per side: more than 20 % off the reference = red (under /
  over), 10–20 % off = yellow (low / high), within 10 % or within 5 mA =
  green; dead band 8° wider than the reference = slack.
- The sweep drives the joints of one kind together (all abductions, all MCPs,
  the PIPs with the thumb dip, the thumb cmc alone), the way calibration
  drives them, so a full measurement is about a fifth of the time. Same for
  the breakaway probe: a group ramps under one current limit, a motor that
  has moved is driven back while the others keep ramping, and every motor is
  back at its start before the other direction.
- Tension check (breakaway, limits ignored) = one pass; GT_tension_07's five
  passes were only for the reference. It now begins torque-off with the
  mid-range pose on screen: the operator brings the hand there first, so no
  tendon starts against a stop. Bands for the check: under 80 % of the
  reference = still needs the ratchet (yellow), 80–100 % = right (green), over
  100 % = tighter than the reference, leave it (red). Deliberately loose: the
  sweep after calibration is the exact check and this one must never drive
  over-tensioning.
- The check sits inside guided tensioning: score → "Check & tension" → pose
  prompt → check → ratchet step listing only the tendons under 80 %. The
  check's dialog also offers "Continue to tensioning", which opens guided
  tensioning straight at the ratchet with the check's list. The slack test
  only lives in the Calibrate step now.
- Setup page: a flowchart (tension → check → ratchet ⟲ → slack test →
  calibrate → measure tension → run in) under the step tiles; clicking a box
  explains what happens and why; text and colours are editable in the browser.

GT_tension_08 (the first check taken with the new flow, five passes, held
pose) against GT_tension_07, before today's changes: most sides within 10 %;
pinky abd extend 310 %, pinky pip 145–168 %, ring pip 164–196 %, index pip
133–140 % over; thumb cmc extend 68 %, pinky mcp flex 69 %, index mcp flex
71 % under. The user has since made GT_tension_08 the breakaway reference.
Pose matters for these numbers (the check now starts from a mid pose).

Open on hardware: the grouped ramps (five abductions moving at once at low
current), the sweep's stop detection on the real motors, and whether the
sweep pose should hold the untested joints at mid so the calibrated limits
are reachable (index mcp / pip, ring abd stalled short).

Addendum (2026-10-21, later): the grouped sweep collided fingers (the group
moved in motor direction, which is a different joint direction per finger, so
abductions swung toward each other; the thumb crossed moving fingers). Groups
are now collision-free and move one sense at a time: every thumb joint alone,
the four finger abductions together (same joint direction, as calibration
drives them), the finger MCPs and PIPs in non-adjacent pairs (index+ring,
middle+pinky). While a finger group sweeps the thumb is parked straight
(extend limit, 5° inside); while a thumb joint sweeps all fingers are parked
straight with the abductions at mid. The probe check uses the same groups.

Datasets are now named by kind and time (`check_20261021_094012`,
`probe_…`, `sweep_…`), accept a note from the Tension/Calibrate step ("before
clicks", "after 1 click"), and every probe records the calibration limits in
force. Files stay `tension_probes.yaml` / `tension_sweeps.yaml` in the model
folder (per model, datasets keyed by hand). A labelled copy of the whole
folder as calibrated today (auto + manual + checks) is in
`hand_data_backup/7CFBEC24BE210835/2026-10-21_calibrated_auto+manual_before_clicks/`.

Automatic vs manual calibration on 7CFBEC24BE210835 (motor degrees, span):
within 2° on 10 of 17 joints; manual narrower on middle pip (−12.7), thumb
dip (−9.2), ring pip (−7.7), wrist (−6.7), middle mcp (−6.2), index mcp
(−3.0). The hand reaches less by hand than the motors push at the calibration
current; the manual one is the active calibration.yaml.

Click experiment (planned): check + sweep before, one ratchet click on the
seven tendons the check listed under 80 %, check + sweep after. The ratchet
list shows clicks from a provisional 15 % per click (editable in the dialog)
until this sets the real figure.

Addendum (2026-10-21, evening): the Setup page now carries the loop as the
user described it. Tension step: a) slack test, b) tension check, c) tension
(opens on the check and its ratchet list, then move fingers → check → ratchet
until the check is green). Calibrate step: a) calibrate, automatic or manual,
b) measure tension, c) tension again (only the tendons the measurement found
low, then calibrate and measure again). Third window renamed Run. The
flowchart shows slack → check → ratchet → move (↺ check) → calibrate →
measure → tension again (↺ calibrate) → run; the operation log is collapsed
at the bottom; the kai tab is gone. Shareable auto-vs-manual calibration page:
https://claude.ai/artifact/FowttoVh4hmxi1tV2fDsWj

Where the data lives, for another computer: every file (calibration.yaml,
calibration_auto/manual.yaml, tension_probes.yaml, tension_sweeps.yaml,
slack_tests.yaml, tension_progress.yaml, last_tension.yaml,
travel_baselines.yaml) is written beside the model's config.yaml inside the
installed orca_core package (site-packages/orca_core/models/v2/<model>/).
One folder per model, not per hand: calibration.yaml is overwritten by every
hand that is calibrated, the datasets accumulate in one file keyed by the
board id (hand_key), the references are per model, and a reinstall or
upgrade of orca_core wipes all of it. A fresh install has no reference, so
checks and sweeps are saved but not scored. The clean design is a per-hand
data directory outside the package (one folder per board id) with the
reference datasets shipped in the package; not built yet.

Addendum (2026-10-21, later): the sweep groups are now the four fingers
together per joint kind (abductions, MCPs, PIPs), each thumb joint alone,
one joint sense at a time. The Setup tab's tower pictures are rendered from
the base assembly STEP (scratchpad `render_tower.py` → `tower_F.png`,
`tower_B.png`, `tower_faces.json` beside each side's model; the console draws
a box the size of each spool over the picture, colour by status, and lists
the spools beside the picture). The flowchart is an SVG on two rows with
labelled arrows, the detail panel empty until a box is clicked, with a
"what to do" per step (slack test: unmount and reattach the top spool with
more inherent tension if a spool ran the half turn, per the assembly manual).
Auto-vs-manual page now covers every pair found in the backups (two so far),
rebuilt by scratchpad `calib/build.py`.

Open question raised by the user on the sweep table: the per-joint numbers
(mean current, % of reference) are not what the measurement is for. The
point of the sweep is the behaviour along the whole range: where each tendon
has how much friction. Proposal (not built): keep the sweep but score it as
curves. From the out-and-back pass at each position bin, static load =
(I_flex + I_extend)/2 (tendon/skin preload, what the ratchet changes) and
friction = (I_flex − I_extend)/2 (routing drag, which tension raises); compare
both curves with the reference sweep's curves in mA per bin, flag the
stretches that depart, and show the plot per joint. The check keeps a
one-number-per-side reference (breakaway); the sweep gets a curve reference.
Current display bugs: the status is the worse side while the % shown is the
mean of both sides; joints whose reference runs at noise level (6–10 mA) give
meaningless ratios (thumb dip 436 %).

Addendum (2026-10-21, sweep scoring by curves): the tension sweep is now
scored along the travel. Each joint's out-and-back pass is binned into 20
steps of its travel; in flex-positive units the two directions give static
load = (I_flex + I_extend) / 2 (tendon and skin preload, what the ratchet
changes) and friction = (I_flex − I_extend) / 2 (routing drag). Both curves
are compared bin by bin with the reference sweep (sweep_20261021_102653,
"pre ratchet", the user's last run); a departure beyond max(8 mA, 15 % of the
reference level) over at least 10 % of the travel is a flagged stretch, and
the joint is "under" (looser, ratchet it) or "over" (tighter) when the mean
of either curve is off by more than that, "slack" when the dead band is 8°
wider. The sweep dialog shows a chart per joint (friction solid, static thin,
reference dashed, stretches shaded) and the Calibrate step's "Tension again"
lists the under joints. On the real data static load is near zero on every
joint (symmetric spools) and friction carries the tension: GT_sweep_01 vs the
reference agrees within tolerance on 14 joints; thumb dip friction 8 vs 42 mA.
The tension check keeps a one-number-per-side reference; the sweep now has a
curve reference.

Addendum (2026-10-21, 10:50): the tension check's breakaway ramp made the
four abductions start one after another (index moves at 40 mA, middle at
90), which the user ruled out: every finger must move at the same instant.
The check is therefore a "stroke" now: the four fingers of a joint kind are
driven together, position-controlled at 30°/s under a 150 mA limit, 40°
motor from the hold pose and back, then the other way, each thumb joint
alone; each motor's mean current over the stroke (past its first 20 %) is the
reading, the same friction quantity the sweep measures over the whole
travel. A stroke can only be scored against a stroke reference: the first
check on the well-tensioned hand must be kept as the new reference
(GT_tension_08 is breakaway and is refused with a message). The sweep dialog
hides the per-joint charts; clicking a joint row opens its chart over the
whole dialog, with previous/next.

### 2026-10-21 (11:05) — one ratchet click, measured

The user ratcheted ring pip, pinky pip, index pip, pinky mcp, middle abd,
ring abd and ring mcp by one click each, with the check (breakaway, before
the restart) and the sweep before and after.

Check (breakaway, % of GT_tension_08), before → after one click: ring pip
51/61 → 102/110; pinky pip 59/53 → 85/101; index pip 56/67 → 151/150; pinky
mcp 167/67 → 333/127; middle abd 100/75 → 150/130; ring abd 77/100 →
137/138; ring mcp 123/79 → 170/145 (flex/extend). On the ten sides that were
under 90 % one click added +27 to +95 points, median +60. Unclicked joints
drifted by up to ±28 points between the two breakaway runs (one pass each):
that is the breakaway's run-to-run noise, the stroke should do better.

Sweep (friction share of the pre-ratchet reference), before → after: middle
abd 95 → 134 %, ring abd 93 → 150, ring mcp 93 → 155, pinky mcp 102 → 223,
index pip 86 → 201, pinky pip 96 → 165, ring pip +16 mA on a 2 mA reference.
Unclicked joints stayed within 10 points except index abd (90 → 64 %).

Conclusion: one click is coarse, about +60 points of the reference in the
check and +40 to +120 in the sweep. The ratchet list now uses 60 points per
click (editable), rounds to the nearest whole click toward 100 %, and shows
"leave · 1 click overshoots" for a side in the yellow band that a click would
push into the grey band. Bands everywhere: 90–110 % green, 70–90 % yellow
(ratchet), under 70 % red (loose), over 110 % grey (tighter, left alone);
the sweep uses the same bands on the friction share, with a reference under
15 mA judged by the absolute difference instead.
