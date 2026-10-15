# Assembly guide feedback review · 15 October 2026

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
change is one instruction followed immediately by its media. A **Show all** control
preserves access to the complete sequence. Progress remains explicitly checked;
viewing an instruction or playing an animation never marks a step complete.

## Feedback coverage

| Concern | Implementation / remaining limit |
| --- | --- |
| Thumb PP needs a 5 mm pin | Calls out the missing pin specification in Parts, the instruction and review notes. Diameter and hole are not supplied; no guessed substitution. |
| Thumb AP routing is reversed | The step explicitly marks the current route as awaiting a corrected channel assignment. Existing CAD paths are retained for review, not silently swapped. |
| Thumb AP / TP bearings are 3 mm | Parts and instructions use 4×8×3 mm for both, including Touch. Review notes identify the 2 mm labels still present in the supplied Touch CAD. |
| Connector probe appears on wrong side | Touch instructions specify the back-side pads and flashing before mounting. Ambiguous probe-placement images are removed from those steps. |
| AP PTFE too long | Use measured channel depth plus about 2 mm; leave about 1 mm at either end. 5–8 mm is an estimate, not a universal cut dimension. BOM notes agree. |
| Flashing choices prominent | Method selector is immediately below the title, above Parts and instructions. Console and terminal remain alternatives. |
| One Parts box with sizes | Parts/tools are listed together at the top of every applicable step. Bearing dimensions are there; vague “confirm size below” is removed. Actual source conflicts are stated upfront. |
| Guided sequence by default | One instruction is visible initially; image galleries and commands are placed inside that instruction. Playback is user-triggered. |
| Repeated text | Removed “Walk through this step,” duplicate flashing walkthrough and redundant image captions where they repeated the full instruction. |
| Clear tendon legend | Dedicated separated swatches replace the run-on top-right text; colors match each scene's actual palette. |
| Rotation too small | Larger illustrative movement with an explicit statement that the animation is not a calibrated range limit. Physical checks ask for free movement without forcing stops. |
| Named thumb-to-carpal channels | Eight named selectors highlight the corresponding existing CAD path; white rings mark the selected TP exit and carpal entrance. Other routes fade. |
| Random assembly/side labels | Removed the redundant RIGHT/TOUCH ASSEMBLY header from detail cards. |
| Forward-looking instructions | Removed unnecessary later-step commentary from affected thumb, pulley and wrist steps; footer navigation still identifies the next step. |
| Icon controls | Walkthrough and fitting playback, static image enlargement and shared model enlargement use icons with accessible labels. |
| Overlap / room for models | Desktop sidebar can collapse. Instruction images occupy the main width; images retain their full aspect ratio, including tall screw diagrams. |
| Play at right edge | Walkthrough playback is the final toolbar control, with the instruction count on the left. |
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

1. **Thumb PP pin:** full diameter × length and exact hole for the reported 5 mm pin.
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
