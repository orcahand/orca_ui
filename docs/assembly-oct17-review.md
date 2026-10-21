# Assembly guide refinement — October 17

Scope: improve the assembly guide only; preserve hardware controls, saved completion semantics and the existing design palette.

## Completion criteria

- Wrist routing progresses left to right across both rows with the correct carpal exit and wrist entrance highlighted simultaneously, for both hands and Base/Touch geometry.
- Spooling explains the two spool positions, opposing tendons, winding and installation sequence with an understandable visual and unambiguous checks.
- Touch shows the four-wire connector-board to OH-board connection, both sockets, routing and clearance check.
- Opening page lists tools for the selected build; every step lists its tools separately from parts, including optional equipment where applicable.
- Navigation has clear ordered chapters, concise action titles and an accessible clickable hand that selects the relevant chapter/finger.
- Images are reviewed at their actual display size; CAD renders have clean edges, useful framing and readable annotations. Original photographs remain where they are needed to verify physical connector detail.
- All supported configurations, responsive layouts, navigation, media loading and checkbox-only completion are verified in the browser.
- Production build and appropriate existing tests pass; unrelated user files remain unchanged.

## Evidence and decisions

Baseline: `59a6686`. Only `pyproject.toml` and `uv.lock` were modified before work; their hashes are recorded outside the repository.

The source PDF describes palm-row-first wrist routing; the requested left-to-right sequence must retain that same channel correspondence. The existing measured conduit paths provide paired endpoints for all 32 tendons.

The Touch kit already lists the four-wire board lead, but the connection step only shows finger sockets. A dedicated connection illustration is required.

Several connector photographs contain fewer than 500 pixels in one dimension. Enlarging their files cannot recover physical detail. CAD diagrams and useful close-ups must carry the instruction instead of stretching these photographs across the page.

## Implemented

The new chapter navigation, hand selector, per-step tools, build-wide tools,
paired left-to-right wrist view, spool overview and dedicated Touch board cable
step are implemented. Existing progress IDs and checkbox-only completion are
preserved. The new board-link step has its own completion ID.

The photograph problem had two causes: small prior PDF exports and an image-sizing
rule that could crop larger photos at narrow widths. Higher-resolution matching
crops recover available source detail, and native-size caps now also respect the
container width. CAD stills retain the existing 1800 × 1400 supersampled renderer.
A browser-composited review confirmed their edges were smooth; the jagged silhouette
seen in a raw transparent-image preview was not a defect in the displayed render.

The new cleanup renders show the bare carpal outlets. The older screw-cleanup photo
is retained only as a comparison with its unconfirmed tool size stated explicitly.
Touch connection close-ups use the current STEP board/socket geometry. The teal
board cable is schematic and is labeled as such, rather than claiming an unmeasured
installed cable path.

## Verification record

- Existing Python suite: 106 passed. Only existing FastAPI/WebSocket deprecation
  warnings; no hardware operations were performed.
- Content audit: 48 combinations of side, version, motor, audience and flashing
  method; unique steps, expected Touch filtering/order, tool coverage and valid
  instruction/image assignments. Primary and alternate image requests resolve.
- Walkthrough audit: all 70 Touch/internal/Console steps load their images and
  instruction-local content with no horizontal overflow or JavaScript errors.
  First-viewport contact sheets were visually inspected.
- Navigation: all eight hand regions select/highlight the intended chapter.
  Visiting steps leaves completion at zero; explicitly checking the new Touch step
  persists its completion and selected page through reload. Tablet navigation
  collapses correctly.
- Responsive detail review: 1440, 800 and 390 pixel widths across wrist routing,
  spooling, the Touch board link, OH board photographs and sensor photographs.
  Photo containment and lightboxes pass. The wrist route position survives reload.
- Wrist geometry: Base/Touch × left/right × whole/close-up × first/middle/last
  selection = 24 paired views. Both labels agree and remain inside their frames.
  The data audit checks all 32 outlets, unique coverage and unchanged within-row
  receiving-channel order.
- Spool assembly: the slider retains one scale, recenters the assembly and avoids
  overlapping numbered badges when assembled. Selecting a group highlights it.

Temporary screenshots and executable audit scripts are under
`/tmp/orca-guide-oct17/` on the authoring machine. They are review evidence, not
runtime dependencies. Use a mock backend and a separate progress file when
recreating these checks; never overwrite the owner's real assembly progress.

## Mechanical facts still requiring confirmation

These were already unresolved in the source and previous handover. Do not fill
these gaps by inferring a plausible mechanical procedure from a render.

1. **Bottom versus top tendon:** the joint pairs/motor IDs are known, but the
   per-joint bottom/top assignment and winding direction have not been confirmed
   for current left/right and motor configurations. The new overview resolves
   the positional meaning of the spool names; it does not establish this mapping.
2. **Thumb AP routing:** the source comments explicitly say the routing is reversed,
   but do not identify the corrected four-channel assignment. A verified annotated
   photo or channel table is required.
3. **Hardware differences:** the earlier fan instruction specifies M3×14 while
   the current CAD contains M3×12; top-spool instructions say M2×8 while CAD has
   M2.5×8. Confirm the supplied kit. The carpal cleanup screw size is unspecified.
4. **Other versions and optional processes:** Full-specific geometry/procedure,
   separate FeeTech wrist geometry, the Touch long-cable wrap offset, Touch casting
   specification and arm-mount kit details remain limited by available references.
   Base/Touch Dynamixel are the four complete measured CAD configurations used for
   the new wrist views; the other selections are labeled as reference geometry.

The clarification request for items 1 and 2 is pending. The guide has not been
physically assembled or electrically tested as part of this software review.

Final packaged verification: `npm --prefix frontend run build` passed, with the
existing large JavaScript chunk warning. A browser opened the guide through Setup
on the packaged mock server and verified tools, reopening the current chapter from
the hand, the cleanup render, both board socket views, wrist routing, the spool
slider and the high-resolution comparison lightbox. It also fetched 258 distinct
packaged image references and the new GLB successfully, with no JavaScript errors.
The final full content audit resolves 420 image references across its 48 combinations.
`git diff --check` passes. The pre-existing `pyproject.toml` and `uv.lock` hashes are
unchanged. No commit, push or hardware action was performed.

## Follow-up image review

The thumb pin/bearing stills used the whole thumb and its loose ends when computing
the camera frame. They now frame the local TP joint and hardware, with clearer
colored strands. The measured geometry and paths are unchanged. All eight stills
(two views × four Base/Touch hand configurations) were regenerated.

The OH board component metadata reveals another source limitation: USB-C, the
power jack/switch and the fan sockets are absent from the STEP component set.
Using that model alone for the complete port identification would be incorrect.
The port step now uses the original 864 × 1152 photograph, extracted without
resampling, with the original page rotation applied in SVG. Eight selectable,
numbered labels replace the crowded red arrows. The current motor output is
selected by default. Enlargement and keyboard-accessible selection are supported.
All socket highlights were visually compared with the original labeled board
picture; the two fan ports remain one named item with two highlight regions.
This improves the guide but does not resolve the missing CAD geometry. Fully
replacing every electronics photograph with a faithful render requires a more
complete source board model.

Follow-up validation: production build passed. The packaged UI port map was tested
at 1440, 800 and 390 pixels; all eight selectors and enlarged selection work, and
both Dynamixel and FeeTech default to their matching output. The eight regenerated
thumb stills were reviewed together on the actual mint background. The full content
check now resolves 418 gallery/alternate references; the new port-map JPEG is a
separately loaded SVG image and was checked through the packaged browser view.
No JavaScript errors or horizontal overflow were found in these checks.

## Completion assessment

| Requirement | Current evidence / status |
| --- | --- |
| Build-wide and per-step tools | Implemented; explicit coverage of every supported step and build/method combination. Exact supplied driver-head standards remain unspecified. |
| Clear chapters and clickable hand | Implemented; eight regions, current chapter expansion/highlighting, keyboard activation and checkbox-only completion tested. |
| Left-to-right paired wrist routing | Implemented and verified against the four measured Base/Touch CAD configurations. Other geometry is explicitly a reference. |
| Clear bottom/top spooling | Positional meaning and assembly sequence improved. Exact tendon assignment and winding direction remain unconfirmed. |
| Touch board-to-OH cable | Dedicated step and both actual sockets implemented; cable path is explicitly schematic, with physical clearance/slack checks. |
| Clean, faithful pictures throughout | Resolution and framing improved, but complete faithful renders cannot replace all photos: the board CAD omits important connectors; Touch cable/plug details still depend on photographs. |
| Guide fully verified for a first-time assembly | Not established. The unresolved mechanical specifications above and a physical walkthrough remain necessary. |

The latest two goal turns made independent UI/content progress while the same
request for authoritative mechanical mappings remained unanswered. The goal is
still active; this record does not claim the guide is fully verified or complete.

## Third blocker audit

The previous turn made concrete progress (joint-detail framing and the interactive
board port map). This audit rechecked the local assembly addendum, the available
STEP/electronics files, the downloaded spool-testing core archive, and the official
current hardware documentation. No confirmed current bottom/top tendon table or
corrected thumb AP channel assignment was found. The core archive's clockwise
ratchet-tightening instruction does not identify the tendon on each spool.

The [official V2 addendum](https://github.com/orcahand/orcahand_hardware/blob/main/orca_v2/base/ASSEMBLY_ADDENDUM.md)
still describes dimensional spool changes rather than the missing per-joint mapping.
The [legacy spooling guide](https://orca.ethz.ch/assembly/Orca%20Hand_step26.html)
uses older hardware and different knot allowance/fasteners, so it cannot establish
current-build assignments. No separate complete OH-board CAD was found in the
local electronics directories. The previews remain live; no render/build/audit
process is still running or awaiting completion.

The same authoritative-information dependency has now persisted through three
consecutive goal turns. Independent implementation and verification are finished;
remaining completion requires the confirmed mechanical mappings, resolution of
kit discrepancies, complete source geometry for faithful remaining renders, and
physical assembly validation. Further cosmetic edits would not resolve these
requirements. The goal must not be reported as complete.
