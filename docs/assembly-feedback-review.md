# Assembly guide feedback review · updated 16 October 2026

This edition preserves the existing guide and adds the supplied feedback and Touch
installation procedure. It lives on `feature/assembly-feedback-touch` in the
`orca_ui_assembly_review` worktree. No changes to motor control, hardware API,
calibration, connection handling or normal Setup behavior are included.

## Branch separation

The recent tendon-rendering work, corrected stills, handover additions and offline
comparison were first preserved in commit `d89768b`. The original worktree on
`feature/better_stat_logging` was restored to its committed guide at `3985b50`.
Its existing `pyproject.toml` and `uv.lock` development overrides were left alone.
Nothing has been pushed by this review.

## Evidence and editorial approach

Both supplied documents were read as text and visually checked in full:

- **Assembly guide comments.pdf:** 12 pages of mechanical corrections and layout feedback.
- **Touch Assembly Instructions.pdf:** 12 slides covering materials, wire wrapping,
  routing, sensor IDs, connector polarity, fasteners and connector-board installation.

The PDFs are not shipped or linked in the walkthrough. Relevant Touch image regions
are extracted into `frontend/public/assembly/touch/`; `sources.json` records their
page and crop for maintainers. Mold previews come from the V2 Base and Touch 3MF
projects, with provenance in `frontend/public/assembly/molds/sources.json`.
Technical imagery is taken from supplied geometry or instructions, not generated
from an imagined connector or cable route.

Retain the warm neutral page, dark green/teal accents, mint model background,
restrained typography and existing interactive controls. The principal layout
change is that **all numbered instructions stay visible together**, with each
image, command or interactive model directly below its relevant instruction. There
is no instruction paging or walkthrough playback toolbar. Progress remains explicitly checked;
viewing an instruction or playing an animation never marks a step complete.

## Feedback coverage

| Concern | Implementation / remaining limit |
| --- | --- |
| Thumb DP/PP pins | Resolved by the owner on 16 October: use the finger recipe, Ø2×8 mm middle pin and Ø2×6 mm lower and upper pins. Removed the earlier 5 mm ambiguity warning. |
| Thumb AP routing is reversed | The step explicitly marks the current route as awaiting a corrected channel assignment. Existing CAD paths are retained for review, not silently swapped. |
| Thumb AP / TP bearings are 3 mm | Parts and instructions use 4×8×3 mm for both, including Touch. This handover records the 2 mm labels still present in the supplied Touch CAD. |
| Connector probe appears on wrong side | Touch instructions specify the back-side pads and flashing before mounting. Ambiguous probe-placement images are removed from those steps. |
| AP PTFE too long | Use measured channel depth plus about 2 mm; leave about 1 mm at either end. 5–8 mm is an estimate, not a universal cut dimension. BOM notes agree. |
| Flashing choices prominent | Method selector is immediately below the title, above Parts and instructions. Console and terminal remain alternatives. |
| One Parts box with sizes | Parts/tools are listed together at the top of every applicable step. Bearing dimensions are there; vague “confirm size below” is removed. Actual source conflicts are stated upfront. |
| All instructions together | Every numbered instruction is visible; media and commands follow the matching instruction. Supplementary videos are below the checklist and Previous/Next navigation. The primary knot video remains inside its lesson. |
| Repeated text | Removed “Walk through this step,” duplicate flashing walkthrough and redundant image captions where they repeated the full instruction. |
| Clear tendon legend | Dedicated separated swatches replace the run-on top-right text; colors match each scene's actual palette. |
| Full-range rotation | Demonstrations use the complete joint limits from the bundled left/right V2 URDFs, converted through the existing CAD axis/rest-angle calibration. This affects visual demonstrations only; connected-hand test limits are unchanged. |
| Named thumb-to-carpal channels | Eight named selectors highlight the corresponding existing CAD path; white rings mark the selected TP exit and carpal entrance. Other routes fade. |
| Random assembly/side labels | Removed the redundant RIGHT/TOUCH ASSEMBLY header from detail cards. |
| Forward-looking instructions | Removed unnecessary later-step commentary from affected thumb, pulley and wrist steps; footer navigation still identifies the next step. |
| Icon controls | Fitting playback and image/model enlargement use accessible icons. A left-edge chevron collapses or expands the chapter sidebar. |
| Overlap / room for models | Desktop sidebar can collapse. Instruction images occupy the main width; images retain their full aspect ratio, including tall screw diagrams. |
| Movement controls | Flexion/extension and tendon selectors play their movement directly. No extra Play movement button. Fitting animations retain their own playback and scrubber. |
| Commands with instructions | Firmware setup, flash command, connector flash and motor configuration are attached to their corresponding numbered instruction. |
| Consistent electronics appearance | Adds the OH-board CAD identification render while retaining the port-labeled diagram and factual connector orientation photos. |
| Final checklist placement | “Final assembly checklist” precedes the completed-hand model. All its checks are still required. |
| Tensioning beside controls | Guide hands off to the existing Setup workflow instead of repeating its spool-adjustment procedure. Existing hardware controls are unchanged. |
| Unspecified silicone | Explicit Base recipe; actual product and demolding schedule remain open. Touch does not inherit unverified Base batch masses or ratios. |
| Mold and skin renders | Adds previews from the matching V2 3MF and existing skin CAD thumbnails. Print layouts are not presented as single-hand quantities. Full-specific mold evidence is unavailable. |
| Carpal cleanup screw size | No size is documented. Clear loose debris; seek the correct tool before enlarging an obstructed channel. The arbitrary-screw instruction is removed. |
| Seat bearing before fitting top spool | Bench-support instruction and animation agree: bearing seats in loose spool, then they move together onto the motor. Outdated still sequence is omitted for Dynamixel. FeeTech retains an identification photo with the corrected order in its text. |

## Touch sequence

Eleven stable step IDs are added only to Touch builds. Base and Full do not receive
these instructions by assumption. The first eight follow thumb attachment while
the carpals remain accessible: kit, IDs, short wraps, long wraps, coloring, routing,
sensor connection and sensor fastening. OH-board identification and the selected
flashing method move here for Touch. Connector-board mounting and wiring follow
flashing; external/preflashed builds omit the flashing procedure. The installed
five-finger response check follows completed electronics and precedes final review.

The supplied procedure includes:

- Paxini sensors: one thumb, three middle-size, one pinky; IDs 0–4 respectively
  for thumb, index, middle, ring, pinky. Program and test one at a time using the
  Windows Paxini software and adapter.
- Three 130 mm and two 280 mm cables; Ø0.2 mm copper wire, approximately 50 cm per
  cable. Clove hitch at both ends; approximately 1 mm between turns; tails under
  2 mm. Short-cable illustration gives approximately 3 cm wrap and 7 cm to the
  pictured connector, with about 5 mm positioning tolerance.
- Black marker on the wraps; gentle bottom-to-top routing; wrapped sections at APs.
- Correct versus reversed sensor and board plugs, gentle hand tightening and flush
  sensor seating.
- Four fingers: two M1.4×3 at each tip, two M1.4×4 below. Thumb: two M1.4×4 at its
  tip and two M1.4×6 below. Board: two M1.4×6 self-tapping screws.
- Physical PCB port map, component side facing the viewer and white 4-wire connector
  downward: thumb top, middle upper left, index lower left, ring upper right,
  pinky lower right. The board map is not mirrored for a left hand.

## Decisions still requiring hardware-owner confirmation

These are visible at the affected step, not buried only in this document:

1. **Thumb PP pin — resolved:** owner explicitly confirmed the finger pin sizes (Ø2×8 mm middle; Ø2×6 mm lower and upper).
2. **Thumb AP:** which channels reverse, in which viewing orientation. A verbal
   “other way around” does not define a reliable replacement geometry.
3. **Touch cables:** allocation of the three short/two long leads to fingers, and
   wrap offset/length for the long leads. The source provides only short-lead dimensions.
4. **Touch screw discrepancy:** kit slide lists six M1.4×6; the installation maps
   allocate four, plus eight M1.4×3 and ten M1.4×4. Two M1.4×6 remain unallocated.
   Current left/right CAD also differs in fastener completeness. The BOM adds only
   missing sensor screws per area and preserves unrelated CAD hardware. Both CAD
   models contain two carpal M1.4×8 where the new board procedure calls for M1.4×6.
5. **Touch bearing CAD:** reconcile the older 2 mm AP/TP bearing geometry/labels
   against the explicit newer 3 mm feedback. The model was not arbitrarily scaled.
6. **Other existing conflicts:** fan screws M3×12 in CAD versus M3×14 in the earlier
   guide; top-spool screws M2.5×8 in CAD versus M2×8 in the text; carpal cleanup tool;
   actual silicone product and cure schedule. Existing arm-mount quantity/thread
   conflicts remain explicitly identified.

These are assembly-review limitations. Browser/render verification cannot validate
fit, electrical polarity, force, screw length or physical tendon routing.

## Removing the review layer

Each step has a Structure / Content / Images box, including retained steps.
The toolbar's **Hide change notes** control hides all boxes during use. For release,
set `SHOW_ASSEMBLY_REVIEW_NOTES = false` in `ReviewChanges.tsx`; the boxes and toolbar
toggle disappear together. The review component and its map are separate from the
assembly content. Removing the notes must not remove unresolved assembly warnings.

`guide:feedback = oct15-v1` invalidates completion only for mechanically revised
steps on first load. Unaffected checks survive. New Touch IDs are recognized by
the existing progress parser and server schema; changing configuration still
invalidates the appropriate build-specific checks.

## Verification

- TypeScript project build and targeted lint passed.
- Data audit covered all 48 combinations of hand side, version, motor, audience
  and flashing method: unique IDs, Touch filtering/order, parts coverage,
  instruction-to-image assignments and 442 image URLs passed.
- Progress migration retained unrelated completion and was idempotent.
- Touch screw quantities were checked per area for both left and right inventory.
- All 68 steps of the internal Touch/Console route were opened in the browser:
  every step had its review box and the applicable guided default, with no runtime
  errors. Named thumb selection and the 390 px layout passed.
- Isolated mock-browser checks passed in both Vite and the packaged UI for guided
  text, command association, review toggle, sidebar collapse, final-checklist order
  and the top-spool scene, without runtime errors. Screw diagrams, mold previews,
  PCB port image and updated thumb framing were visually checked.
- Bearing seating was checked at seven positions for each of the four CAD builds:
  the bearing seats before mounting and then travels with the top spool.
- `npm run build` passed. It reports the existing large-chunk warning; this edition
  does not solve the separate GLB/bundle-size architecture issue.

Development evidence is in `/tmp/orca-guide-review-oct15/`. The preview uses a
dedicated mock backend and progress file; it does not modify the user's normal
assembly progress. Two Touch bearing stills were regenerated with neutral bearing
labels so that the older CAD dimension does not contradict the corrected Parts box.

## 16 October layout revision

- The Ashley stopper lesson has no second generic numbered instruction block.
- Palmar/dorsal controls sit within the anatomy model surface. DP/PP/AP/TP use
  **phalanx** terminology; the direction legend defines distal, proximal, palmar
  and dorsal together.
- Reference/inspection steps without required materials omit the Parts card.
- `prepare-pp` precedes `p33`. Its three preparation images and first video excerpt
  are separated from the three joining images and second excerpt. Migration
  clears prior `p33` completion once so the newly separated checks are explicit.
- Repeated captions, “Need a reminder?” boxes and in-product review notes are
  removed. Unique orientation labels, correct/wrong comparisons and tendon color
  legends remain. Skin fitting directions are in the numbered instructions.
- Illustration background is `#91a89a`. Connector PCB materials and six board
  thumbnails are black; four arm-cover stills containing connector PCBs were
  regenerated from the same CAD scenes.
- Exploded models have dedicated model/label slots in a fixed 1:0.68 viewport. All five areas fit without a separate viewport scrollbar.
  Labels and area controls appear only after the fully exploded layout settles;
  they are inert during movement. Hardware, tendon, PTFE and cable detail views
  and the full BOM remain available.

Validation for this revision: 48 configuration/edition/method combinations,
442 image sources, all 69 Touch-console steps rendered, desktop and 390 px mobile,
sidebar collapse/expand, selector-triggered movement, component drilldown and
video ordering. The 68 joint scenes (17 × four CAD builds) were sampled in both
movement directions at five positions, including exact ROM endpoints and framing;
32 assembly rotation scenes were also checked. Temporary audit scripts/results
are under `/tmp/orca-guide-review-oct16/`, not part of the shipped application.

The review worktree also contains unrelated local tuning/calibration edits that
predate this revision. They are not guide changes and must not be staged with it.
The rebuilt local bundle preserves those existing source changes. No push or
commit is made by this revision.

Packaged UI verification also passed across all 69 Touch-console steps. The
explosion was checked against actual projected mesh bounds and DOM label boxes
for Base/Touch × left/right at widths 390, 1000 and 1440 px: no model/label or
label/label intersections. Production build and the existing test suite passed
(106 tests). Unrelated local source files match their pre-task SHA-256 snapshots.

## 16 October refinement pass

- The explosion slider preserves the viewer dimensions from assembled through fully
  exploded. All five areas use the available frame; part/hardware drilldowns and
  the full BOM remain available.
- Palmar/dorsal buttons share their background, text and border colors. An inset
  underline indicates the selected face. See-through controls sit inside the model frame.
- Rotation and axial-play demonstrations are separate from assembly animations and
  appear below the relevant later instruction. PP skins and bearings share one instruction.
- TP routing includes a rotatable, zoomable CAD view and named tendon selection,
  alongside the entry/exit diagrams. The seating lesson has shorter captions and
  removes the repeated routing legend and explanatory paragraphs.
- White is used behind views without white cord/material. Mint remains where it
  provides needed contrast for white tendons, PTFE or skins.
- `beltGuideGeometry.ts` corrects the displayed belt waist between the two sleeved
  M4 screws using their model-space centers and 6 mm sleeve outer diameter. This
  is a guide-only geometry correction; source STEP/GLB archives are untouched.
  The five affected stills are regenerated for all four supplied CAD configurations.
- Touch steps retain the supplied pictures, connector comparisons, screw sizes,
  wrapping dimensions, sensor IDs and port map with shorter numbered instructions.
- Additional native video excerpts cover the Ashley stopper, thumb joints, TP
  routing/seating, carpal finishing, motor setup and hull closure. Finger skin
  clips move to the skin/bearing step. The importer records every excerpt boundary.
  The old tutorial has no Touch or current OH-board flashing footage; those steps
  retain their supplied pictures and current procedure instead of unrelated clips.

Refinement verification:

- Fixed viewport ratio and dimensions checked at 0%, 50% and 100% explosion,
  for Base/Touch × left/right at 1440, 1000 and 390 px window widths. All five
  areas fit; projected mesh bounds do not overlap labels or area controls.
- Browser checks verified all eight joint-check placements, matching palmar/dorsal
  colors, the inside-frame toggle, the combined skin/bearing instruction, thumb pin
  text, actual TP camera rotation/zoom and named tendon selection.
- The complete 69-step Touch walkthrough has no browser errors. Content validation
  covers 48 side/version/motor/audience/flashing combinations and 442 image sources.
- All 48 native video excerpts and posters exist, match their declared durations,
  and are embedded in the corresponding 36 visible steps (the AP trim excerpts
  share the AP preparation step). Sampled playback advanced continuously; range
  requests work. Packaged clips and posters match frontend source assets.
- Belt waist geometry stays between both 6 mm sleeves for all four CAD builds;
  the minimum sampled clearance is 0.34 mm. This validates the illustration,
  not the manufactured belt's installation clearance.
- All 68 joint scenes and 32 inspection scenes pass the geometry/motion audit.
- Frontend production build and all 106 existing tests pass. The existing large
  JavaScript chunk warning remains. Packaged-UI smoke checks passed, including
  explicit checkbox completion and progress persistence after reload.
- Existing non-assembly source files match the pre-work hashes. No hardware was
  operated. No commit or push was made. Temporary evidence for this pass is in
  `/tmp/orca-guide-review-oct16b/`.
