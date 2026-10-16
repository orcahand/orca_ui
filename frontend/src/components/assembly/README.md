# Assembly workspace

## Model distribution

The four complete Base/Touch assembly GLBs are distributed in
[`orca_ui/models/assembly/`](../../../../orca_ui/models/assembly/README.md) as ZIPs.
The backend restores both packaged and source assets automatically at startup;
extracted GLBs are ignored by Git. Manual recovery from the repository root:
`uv run python -m orca_ui.assembly_assets`. The opening model viewer shows the
selected archive's exact path and a retry action if loading fails.

After regenerating source models, run `python scripts/package_assembly_models.py`
before restarting the backend. Startup treats the ZIPs as authoritative. This
changes distribution only; the measured geometry and runtime asset URLs are unchanged.

## Workspace

Setup opens a lazy-loaded native modal in the existing app and origin. There is
no assembly entry point, browser launch, PDF viewer, or source-document UI.
The guide is available while disconnected. It never starts a hand operation;
existing Setup performs tensioning and calibration. The existing emergency stop
remains available in the modal whenever the hand is engaged.

## Content

`guide.ts` contains stable step IDs and chapter order. `buildContent.ts` supplies
configuration-specific instructions, photos, parts, commands and step filtering.
Base builds omit connector-board programming. Left/right changes mapping images;
FeeTech replaces Dynamixel cabling and hides incompatible motor video excerpts.
`pages` in the data is an internal media index, never a displayed page number.
The provided V2.1 document describes base mechanical assembly; sensor installation
for Touch/Full is not fully documented by it. The version selector currently
adapts the skin appearance, component list and connector-board programming.

`PartsExplorer.tsx` loads tessellated complete STEP assemblies independently of
telemetry and the existing live 3D view. Base and Touch have separate left/right
Dynamixel assets. Complete Full and FeeTech exports were not present in the supplied
archives; those configurations deliberately show an unavailable state, never a
substituted model. The walkthrough remains accessible for every configuration.

The CAD importer keeps every modeled assembly component, treating purchased motors
and populated PCBs as units. It removes coincident repeated motor subassemblies
before counting fasteners and spools. Finer tessellation and exported vertex normals
support the high-DPI viewer. Touch uses black structural parts and skins.

`scripts/refine_assembly_boards.py` restores the OH board's individual component
colors from each current STEP while keeping its single inventory identity and
assembly placement. The PCB is black; the modeled connectors retain their light
plastic finish. `board-components.json` records the source hash and 26 component
meshes. The supplied OH model omits the USB-C port, power switch/input and fan
connectors, so it cannot replace the connector-identification and wiring photos.
Those photos remain the connection reference. The rear-hull instructions specify
the upper motor/connector-board exit and lower fan exit, viewed from inside the hull.

The slider moves components into Fingers & thumb, Carpals, Wrist and Tower areas.
Thumb and finger stock share one area: 32 tendon ends and 10 AP liners.
The explorer groups matching labels, displays explicit quantities, and excludes
the internal `orcahand` and `Ratchet_Main` CAD solids from separate parts lists;
those solids remain visible in the assembled hand.
Carpal covers are supplemental parts because the complete exports omit them.
Their left/right STL downloads and mesh-derived SVG previews come from the
Touch `02_Carpals/Coav-L.stl` and `Coav-R.stl` hardware sources.
Supplemental cheese-head screws use a screw illustration rather than the cable fallback.
Standard hardware collapses into one kit icon in each area. Area-title dialogs include the complete kit. “Standard components” shows only
fasteners, bearings and pins; Tendons/PTFE/Cables each show only that section’s stock.
The modeled tower tendon spans collapse into the two counted material groups
(eight thumb ends and twenty-four finger ends), not an asserted identity map of
those otherwise unnamed CAD solids. Ownership comes from the STEP
assembly hierarchy, with nearest-component assignment for loose top-level hardware.
Tendon geometry is global; illustrated routing supplies show the relevant materials,
not invented cable routes. The same passing tendons/cables are counted only once in
the BOM. `assemblyParts.ts` adds cut stock, tubing, cabling, covers and equipment from
the walkthrough. The rear-hull board fixings are also absent from all four CAD
inventories: two M3 nuts, one M3×14 screw and one M2×8 cable-cover screw. The BOM
merges these into the existing hardware rows, and the Tower kit includes them;
the model's node counts remain unchanged. Cable harnesses without specified individual lengths are explicitly
listed as a matching set. The exports have asymmetric hardware/board content and
are not independently verified procurement BOMs. Both updated Touch exports contain
the OH board and separate front and rear hull covers. Optional arm mounting parts are marked.

Regenerate models in a separate environment with CadQuery, trimesh, NumPy and Pillow:

```sh
python scripts/build_assembly_parts.py /path/Orcahand_BaseV2_Right.step base-right-dynamixel
```

Use corresponding keys for the other three supplied assemblies. Files are written
to `frontend/public/assembly/parts/<key>/`. Original archives are never modified.
After serving these assets, generate the smooth 1040 × 840 transparent illustrations
with Playwright installed in a separate tooling directory (Chrome must be available):

```sh
node scripts/render_assembly_thumbnails.mjs /path/to/playwright-tooling http://127.0.0.1:5002
```

`HandLabels.tsx` supplies the Fundamentals lesson: selectable parts, left/right
palmar and dorsal views, fingers, movement directions and tendon-name interpretation.
`JointLesson.tsx` adds colored bearing-axis markers and selectable PIP/DIP, MCP,
ABD, CMC and wrist movements using the assembly pivots. ABD labels distinguish
movement direction from the printed AP part name.
It uses the existing stable `p23` ID and replaces the old preparation reference step.
Completion remains explicit: browsing or advancing never marks a step complete.

Media components have distinct keys (`motion:` / `video:`); sharing a key lets React
retain stale media across navigation. Videos are memoized and preload their local
bounded clip. Images blend their white backgrounds into the light assembly surface.

`KnotLesson.tsx` supplies eleven manually selectable photographs and optional
playback. `ThreadingAnimation.tsx` presents one scrub-able, three-phase lesson per applicable step;
bearing checks add rotation and an explicitly exaggerated axial-play demonstration.
`channelRoutes.json` contains sampled DP-to-PP paths for the Index example in all
four supplied Base/Touch assemblies. The seated paths and rendered cord surfaces
were checked against their STEP solids; polyline interpolation preserves the bends.
The separated view bridges the moving DP and fixed PP paths, and the transparent
view exposes the channels. Other joint views illustrate exposed tendon spans;
the labeled routing photographs remain authoritative for their hidden channels.
Tendons are hidden during bearing inspection rather than depicting a false loaded
cord path. `WristOutletView.tsx` isolates the wrist without its motor; numbered
outlets use the CAD tube-cap centers and the hand-side mapping. An enlarged modal
shows all 32 numbers. Skin-fitting sliders run from separated to fitted, with DP
skins entering over the tip and PP skins entering from the base.

## Media maintenance

`tubePullScene.ts` uses white cord, short naming labels and a fine contour on
the exposed strands. Its three views distinguish passing the cord through the
tube, feeding the part's channel, and pulling the liner into place.

`groupStandardParts` combines identically named standard hardware for the BOM,
CSV and area dialogs while retaining every source node. The left Touch model's
two M1.4×4 screw definitions appear once as eleven screws: two in Thumb, eight
in Fingers and one in Tower. It does not alter CAD assemblies or their counts.

`cadWristCrossing.ts` supplies the side-view reference using all 32 measured
carpal/wrist paths, colored by row. `cadSpoolPreparation.ts` supplies the current
tower overview without the later top spools, and a close-up of the bottom-spool
anchor passage with an 80 mm free end. Both use the selected Base/Touch and hand
side. A fine projected contour keeps the exposed white cord legible without
changing its channel geometry. The original matching images remain available
in the enlarged comparison. These views do not assign joint tendons to top or
bottom spools; that assignment still requires confirmation.

All walkthrough media is local in `frontend/public/assembly/`. No full PDF or
whole assembly video is shipped. The main video is cut into bounded MP4 files
and played with native video controls. Replace these assets and update
`local-clips.json` / `media-catalog.json` as cleaner media becomes available.

Developer provenance (not part of the walkthrough):

- Extracted images: supplied `Assembly Instructions.pdf`, 157-page V2.1 guide.
- Main recording: https://www.youtube.com/watch?v=TgIz7HiyaoU
- Knot frames: https://www.animatedknots.com/ashley-stopper-knot
- Original knot reference: https://thebearessentials.com/blogs/knot-tying/how-to-tie-the-ashley-stopper-knot
- FeeTech text and photos: https://docs.google.com/document/d/1jl1ykqcGcivIByqJ4UAhxwjG-LbnCoo4hg-1kP5PHfY/edit
- FeeTech videos: https://drive.google.com/drive/folders/1zJ66szPaDstYEfPWc6_vOO3Nb49yK0Xc
- Mechanical checks: https://docs.google.com/document/d/1X0Yv5jg4dj2S1WFEUEBJfblSNmE5DGL1WJxbYD14ARg/edit
- Mounting illustrations: https://www.orcahand.com/getting-started#mounting

The older tensioning document was superseded by the existing Setup workflow.
The recording predates some parts and the OH board; video measurements do not
supersede current written instructions. Motor programming commands are supplied
as copyable text, never executed by the guide.

Rebuild imported PDF panels (requires reviewing crops if the PDF changes).
Both importers default to 300 DPI and lossless PNG output; `--dpi` can override
the rasterization resolution. This avoids another JPEG encode but cannot recover
detail already missing from embedded source photos. Existing extracted assets
require the source PDF to regenerate. Photo views retain intrinsic dimensions
when the available crop is smaller than the image container:

```sh
uv run --no-project --with pymupdf --with pillow python scripts/import_assembly_guide.py '/path/Assembly Instructions.pdf'
uv run --no-project --with pymupdf python scripts/refine_assembly_panels.py '/path/Assembly Instructions.pdf'
```

Create the reviewed video excerpts from a locally available copy:

```sh
python scripts/import_assembly_clips.py /path/to/TgIz7HiyaoU.mp4
```

Build without deleting unrelated local files from the packaged web UI:

```sh
npm run build --prefix frontend -- --outDir /tmp/orca-assembly-build
cp -R /tmp/orca-assembly-build/. orca_ui/webui/
```

## Persistence

`/api/assembly/progress` stores one build in `~/.orca_ui/assembly-progress-v2.json`,
using validation and atomic replacement. It never reads or writes hand config.
The browser also keeps `orca-ui.assembly.v2.1` as a fallback. Server storage is
necessary because the desktop launcher discards its browser profile on exit.
The two introductory checks are invalidated when configuration changes. Legacy
intro completion requires both new checks before it is counted.
The current step, configuration, completion checks, 32 tendon checks, and selected
photo survive closing the popup and starting a new browser session. Writes are
serialized across popup mounts. “Start a new build” resets only assembly progress.

Validation: TypeScript production build, frontend lint, pytest, and Chromium
interaction checks against an isolated mock backend with temporary progress.

Walkthrough presentation conventions:

- Use the matching Base or Touch CAD hand for anatomy lessons and the matching CAD components for assembly motion. Keep the selected part opaque and fade its surroundings. Use conceptual drawings only for cord/knot measurements, not as a substitute for an available hand model.
- Put numbered instructions before the large image panels. Each panel has its own enlarge action and an explicit instruction number. Preserve functional routing numbers; omit decorative part-location badges and their yellow outlines.
- `refine_assembly_panels.py` re-extracts clipped photo panels from the local teaching document. It does not ship that document. Read PDF image clipping rectangles when splitting montages; the image bounds alone include hidden portions of other panels.
- Knot convention: joint anchors use Ashley + one single knot on top, except thumb ABD/AP and CMC/TP, which use three reinforcing single knots. Spools use Ashley with three turns, or Ashley + two single knots as the short-tendon fallback. Instruction text takes precedence over the older demonstration clips.
- Ten 2 m lengths make the DP/PP anchors for all five fingers. The BOM counts cord once; Thumb/Fingers kits show their respective tendon groups. Each assembly exposes its passing tendon ends; the BOM still counts the original cut stock once.
- The BOM is collapsed on entry. Cable-holder A/B and rear-board cable-cover STL files are copied from the supplied V2 Base files, with actual mesh previews. Other consumables use vector illustrations. Programming probes are not included in the assembly BOM; magnet adhesive belongs to the tool kit.
- `FingerMotion` uses the selected STEP assembly and its measured bearing pivots. It never reads or sends live poses. Completion requires explicit checks; one explicit checkbox covers all six movements for each finger. All four marks complete p45. Legacy six-per-finger checks migrate once, then their old keys are removed so unchecking a finger stays unchecked.

Current walkthrough refinements:

- Configuration chips appear only on `p1`. Every other step uses that saved build.
- Compact picture grids span the content width and use no more than two rows at desktop widths. Images retain their complete aspect ratio and enlarge independently. `InstructionSequence` highlights text and its matching panels; playback never changes completion.
- PDF image clipping bounds must be captured before redaction removes invisible clipping scaffolds. Test overlap with a small tolerance for PDF floating-point transforms.
- `assemblyMotions.ts` defines the step-specific CAD joining sequences. Dynamixel-specific motor lessons are hidden for FeeTech. `TendonRouting` traces the supplied TP diagram and presents entry/exit highlights beside the joining model. AP and carpal views use endpoint highlights without speculative overlay curves. `WristRouting` counts row positions, explicitly distinct from the 32 tendon identity numbers.
- `jointFrames.json` was measured from the supplied STEP PP joint cylinders. `assemblyStrands` shows exposed spans across the opening joint; it is an instructional illustration, not a full simulation of the hidden channel paths. The annotated close-ups specify the holes. `tendonTails` shows the selected end being drawn while the antagonist remains slack. Selecting a movement starts a fresh, single replay.
- `KnotReinforcement` keeps the Ashley compact and shows the added ordinary overhand separately before snugging it onto the stopper.

Content review findings (for the next media revision):

- Finger instructions specify 4 mm-thick bearings, while the supplied CAD calls them 4×8×3. Do not silently substitute a thickness; the build owner needs to confirm the intended hardware.
- Carpal and wrist PTFE lengths are fit-to-channel, plus about 1 mm at each end; AP liners are approximately 8–10 mm. No unsupported universal cut length is supplied.
- The TP diagram calls its passing outside pair “TP abduction/adduction”; the rest of the guide and tendon map call that pair AP toward thumb/pinky. The interactive guide uses the latter, with TP flex/ext reserved for its two anchor ends. This naming interpretation was flagged to the build owner for confirmation.
- The thumb-to-carpals prose said six tendons although six pass through TP and two more anchor there. The walkthrough explicitly accounts for all eight.
- Carpal-opening cleanup now precedes installing the liners. Its photo shows the cleanup itself; completed liners are shown in the next step.
- Only a right-hand physical motor-layout photo is supplied. The merged interactive page replaces that photo with the actual CAD motor columns and uses each side’s checked local configuration for joint-to-motor identity. Configuration commands include the selected model’s actual config path.
- Touch/Full sensor installation, hardware-kit procurement completeness, and exact lengths for some supplied cable harnesses are not fully documented by the teaching material. Full/FeeTech complete CAD assemblies remain unavailable.

## Assembly refinement: routing, motors and guide editions

- The first-page `audience` selector persists through the assembly-only API. External
  mode hides both flashing chapters; it does not change the connected hand.
- Motors now starts with variant selection and spool preparation. The ID, column
  and chain pages share `p115`; old progress only migrates a completed chain when
  all three original steps were checked. The `assembly-v3` revision marker avoids
  treating the former ID-identification checkbox as a completed motor installation.
- Wrist routing ends at the wrist. Spooling adds the joint/motor association view.
  Each joint has one checkbox covering both tendons. Source channel numbers remain
  visible beside the CAD trace. The colored trace illustrates connectivity; it is
  not a measurement of hidden bore geometry. Motion spans likewise show the exposed
  cords between parts, with the routing diagrams identifying the actual holes.
- `driveMap.ts` uses the absolute motor IDs in the local left/right v2 model configs.
  Negative signs in those configs specify rotation conventions, not different IDs.
  The four physical motor columns retain their common ID positions; the assigned
  joints change with hand side. These views do not drive or detect hardware.
- `cadGeometry.json` records actual component centers, PCA hardware axes and STEP
  bearing-parent paths. Regenerate with `scripts/build_assembly_motion_metadata.py`.
  A joint carries its already-installed bearings; newly added bearings and screws
  have their own insertion stages. The spool-preparation scene contains exactly
  one motor, bottom spool, M2 nut, three M2×4 screws and ratchet.
- Both thumb diagrams use pixel traces of their existing colored tendons. Carpal
  routing shows its two contextual views once, without the duplicate magnification.
- The board diagram preserves all connector labels and arrow tips. Console flashing
  is a six-phase walkthrough with expandable images. The firmware alternative was
  checked against local `orca_firmware/README.md` and its flash scripts, including
  setup, explicit side/version flags, and removing the OH-board probe before USB
  upload. The connector-board probe remains seated during its own SWD flash.
- The STEP hierarchy further distinguishes Touch PP/AP bearings (4×8×2) from DP
  bearings (4×8×3). Base uses 4×8×3. This conflicts with the written “4 mm thick”
  instruction. The top-spool CAD screw is M2.5×8, versus written M2×8. These size
  discrepancies require hardware-owner confirmation; no silent substitution was made.

## Clarity review · October 10

- Fundamentals contains the Ashley lesson and hand terminology. Routing, bearing
  seating and friction checks appear at the joints where builders use them.
- Internal builders select Console or firmware-terminal flashing. The selected
  method alone appears in the timeline and completion count; the choice persists.
  External builds contain neither flashing method. Chapter numbers stay sequential.
- Bottom-spool checks cover anchoring, winding and the free antagonist. Top-spool
  checks cover the completed pair and a gentle manual check with board power off.
- Changing hand side or version clears configuration-dependent checks. Loading old
  progress cannot mark tendon or final-checklist steps complete without their checks.
- Motor bridges are 14→13 and 6→5 at the column bottoms, plus 10→9 at the top,
  as shown by the motor-ID diagrams. Preparing motors means sixteen spool motors;
  the wrist motor uses its separate carrier.
- Video excerpts were reviewed against the local recording. DP/PP/AP clips now
  stop at the correct task boundaries. Wrist seating has its own clip. Top-spool
  clips include bearing and screw installation. The outdated board-installation
  clip is omitted; current OH-board photos remain. `import_assembly_clips.py`
  records the revised cut points.
- Anatomy and preparation previews use Touch parts when selected. Connector-board
  photos filter to the selected version. Full geometry and sensor-installation gaps
  are explicit. Tendons appear in all five exploded areas and are counted once.

Unresolved assembly information:

- The numbered tendon diagrams establish joint pairs and motor identity, but do
  not explicitly specify bottom/top spool assignment and winding for every build.
  This needs confirmation before builders cut and anchor their tendons.
- Bearing thickness, top-spool screw size and AP/TP naming discrepancies are listed
  above. The guide does not silently choose a conflicting hardware size.
- Touch/Full sensor installation, some harness lengths and complete Full/FeeTech
  assembly exports remain missing. These configurations cannot yet be treated as
  independently complete build instructions.
- Silicone notes do not identify the material product or demolding time, and their
  skin quantities describe Base. The appendix now states these limits explicitly.

## Motor verification and CAD visual review · October 11

- Finish includes a saved 17-motor mechanical check. Each motor has a synchronized
  output/spool and joint preview, a scrubber, and its own physical-check checkbox.
  The step cannot complete until all 17 checks are marked. Unchecking a motor or
  changing the hand, motor type or version invalidates completion.
- `motorCheckScene.ts` derives pivots from each joint's two STEP bearing centers.
  Downstream segments, skins, Touch modules and hardware travel together. The wrist
  uses the two carpal bearings. Motor IDs match the absolute IDs in the six local
  Base/Touch/Full left/right v2 configurations. Rotation sign, excursion and ratio
  are illustrative; this pairing lesson does not specify spool winding direction.
  It sends no hardware commands and does not claim a powered hand has been tested.
- Six CAD detail views cover skins/bearings, carpal finishing, connector PCBs,
  spool holders, tower/wrist magnets and the completed hand. Parts can be separated,
  rotated, zoomed and highlighted by name, with grouped quantities. Existing motor
  preparation and side-plate animations replace their redundant still pictures.
- Base and Touch load their actual selected-side geometry. Touch uses its fingertip
  module instead of a Base DP skin and shows the CAD PP bearing size. Full retains
  its explicit Base-reference note; FeeTech-specific hardware views retain photos
  when a matching complete assembly export is unavailable. The motor verification
  view identifies its Dynamixel drive reference for FeeTech builds.
- Channel-entrance, knot and cable-routing photos remain where they carry information
  not established by the available geometry. CAD fitting previews show component
  locations and do not replace the written order or missing sensor procedures.
- The CAD review found reversed middle/ring labels in Base-right and Touch-left.
  Their repeated M subassemblies are now identified by physical position relative
  to the index finger, rather than STEP instance order. Inventories, thumbnails,
  bearing ownership and the importer agree on the corrected anatomy. The motor
  preview audit checks anatomical order as well as electrical motor IDs.
- Verified: six motor maps, 136 motor/joint scenes across four CAD configurations,
  all six detail scenes per configuration, 48 existing assembly scenes, 56 external
  mobile steps, completion/persistence/configuration invalidation, and playback.


## Still-image review · October 11

- Twenty-four mechanical gallery panels now use 1800 × 1400 transparent WebP
  renders for each supplied Base/Touch and left/right STEP assembly (96 assets).
  These cover lined carpals/wrists, DP bearings, PP pins and joining stages,
  thumb assembly, wrist hardware, tower nuts, the wrist motor/pulley, top spools
  and hull magnet seats. Instruction numbers and enlarge controls are preserved.
- The BOM and preparation gallery use 307 regenerated 1040 × 840 transparent
  part thumbnails. The offline renderers use environment lighting and crease-aware
  normals. Existing interactive geometry and hardware-control code are unchanged.
- Rebuild stills with `scripts/render_assembly_illustrations.mjs`, pointing it at
  a Playwright tooling directory and the Vite origin. Recipes are in
  `cadIllustrations.ts`; scene construction is in `cadIllustrationScene.ts`.
  `scripts/render_assembly_thumbnails.mjs` refreshes the inventory previews.
- Full keeps its existing reference images because no matching complete STEP
  export was supplied. FeeTech keeps its motor-specific images; generic mechanical
  panels may use the matching Base/Touch hand geometry.
- Retained imagery carries information missing from an unannotated assembly:
  Ashley and reinforcing-knot topology; stopper seating and tucked tails; rough
  versus finished printed surfaces; screw/tool technique at channel openings;
  pulling tubes; numbered AP/TP/carpal and wrist routing; crossed-tendon examples;
  belt tension and screw sleeves; cable slots and connector orientation; OH-board
  connector labels and probe placement; flashing screens; and the arm mounting
  sequence. These need verified new technical diagrams or new process photography
  before replacement. Video poster frames remain paired with their actual clips.
- The models do not settle the existing bearing-thickness, top-spool screw-size,
  missing Full/FeeTech assembly, sensor-installation or spool-winding questions.
  Keep their current instruction notes; a render is not evidence resolving them.
- Remaining visual limitation: some carpal exterior surfaces still show faceting
  at enlarged scale. The channel close-up improves inspection, but this pass does
  not claim to have repaired the underlying surface tessellation.
- Verified this pass: all 237 unique gallery images across 12 build selections
  decode; instruction references are valid; unsupported Full/FeeTech renders are
  not substituted; packaged 1800 px enlargement, variant switching, mobile sizing,
  saved place, explicit completion and uninterrupted video playback pass. All 96
  packaged render assets match the generated source files.

## STEP refresh · October 12

- Touch assets now come from `orca_v2/touch/TouchV2_Assembly_Right.step.zip` and
  `TouchV2_Assembly_Left.step.zip`. Each generated inventory records the extracted
  STEP filename and SHA-256. The archives remain read-only. Both new exports include
  separate rear hull covers, and the left export now includes the OH control board.
- The left hand's finger/carpal assembly moved +1.85 mm along X while the wrist
  stayed fixed. `update_assembly_route_frames.py` verifies unchanged part surfaces
  before translating each part's channel coordinates, connector ports and joint
  origins. Do not copy old world-space routes onto a new export without checking.
  It rejects changed topology or surfaces; those need fresh channel extraction.
- Import into a staging folder with `build_assembly_parts.py --out ... --brep-dir ...`.
  Rebuild ownership/axis metadata with `build_assembly_motion_metadata.py --version
  touch --parts-root ... --source-pattern 'TouchV2_Assembly_{side}.step' --output ...`.
  Review the staged data together before replacing the served Touch assets.
- `cad_render_mesh.py` meshes in absolute millimetres and obtains per-face normals
  from the CAD surfaces. Both image renderers preserve these normals. The earlier
  faceting limitation has been addressed; stills render at 3600 × 2800 and downsample
  to 1800 × 1400, with transparency.
- Current recipes produce 148 images across Base/Touch and both hand sides. AP
  liners and tube pulling have CAD process views. AP/carpal routing, the PP tendon
  pair and the carpal underside use camera-projected CAD coordinates, with matching
  version selection. The wrist arrows show receiving sides, not physical free-span
  curves. Row counts remain separate from global tendon identity numbers.
- This is still a partial replacement: knot photographs, some TP/routing diagrams,
  electronics/mounting photos and other process images remain. Full and FeeTech
  still need complete matching assembly exports.

## PP preparation and movement renders

- The PP cleanup and pin-check pages now use the selected Base/Touch and hand-side
  CAD model. Cleanup highlights the actual curved profile without fabricating print
  defects. Pin insertion and the transparent seated close-up use the two STEP
  2 × 6 pins; the other middle 2 × 8 pin remains seated.
- The previous DP-to-PP paths cleared the printed body but intersected a PP pin.
  `repair_assembly_pin_paths.py` plans through the space between the two short pins,
  checking the printed PP, all three installed pins and the other cord. It writes
  a staging JSON for review. Current 0.14 mm-radius illustrations also pass dense
  segment checks against the DP/PP solids. Touch DP entrance clearance was refined
  by 0.025 mm. The original part surfaces are unchanged.
- `CadFingerMovement` animates the actual selected STEP parts around their measured
  bearing axes. The initial DP check shows bare DP/PP, before PP skins and bearings
  are fitted. The six-movement lesson carries downstream parts together and derives
  sideways direction from index-to-pinky geometry. It uses no live hardware state.
- Current still recipes produce 164 images. Remaining photos have not all been
  replaced. In particular, the OH PCB in the updated Touch STEP has no USB-C jack,
  power jack, switch or fan connectors. A complete board export is needed to replace
  its connection diagram without inventing missing geometry.
- Reviewed: 48 CAD finger/joint scenes across four configurations; 16 new PP images;
  all 24 finger controls, enlargement, mobile sizing and explicit completion;
  sampled cord-radius clearance against printed DP/PP solids and all PP pins.

## Wrist and tower preparation renders

- Four additional views cover the two wrist screw sleeves, belt placement, the
  fan nut pockets and fitted fans. Each is rendered from the selected Base/Touch
  assembly and hand side; the tower views retain the photo for FeeTech and Full.
- PTFE sleeves are supplemental geometry using the guide's 4 mm inner / 6 mm
  outer diameters. Their lengths follow the exposed STEP screw shafts up to the
  square nuts. The faded wrist provides context for these close-ups.
- Fan fixing positions follow the STEP nuts and screws. The guide specifies
  M3×14, but both supplied assembly versions contain M3×12 at those fixings.
  The checklist step now calls out that discrepancy before fitting. Wiring
  photographs remain until the cable routes can be accurately illustrated.
- Current recipes produce 180 configuration-specific stills; the full photo
  replacement remains incomplete.

## DP anchor preparation

- All four pictures in Prepare the DP now use the selected Base/Touch geometry
  and hand side. The first three distinguish feeding the prepared tendon,
  seating its reinforced stoppers and tucking the connecting loop. The last
  picture shows the existing bearing installation render. Cords are supplemental
  geometry; compact stopper markers locate the prepared knots without claiming
  to teach Ashley topology.
- The Touch flex-tendon illustration previously began above the common DP knot
  housing. `repair_assembly_dp_anchors.py` plans from that housing around the
  actual DP and seated PP solids, avoiding the other illustrated tendon. Current
  routes also pass dense 0.14 mm cord-radius checks against both solids and the
  DP bearing envelopes. The two feed legs stay separate at the housing.
- The preparation loops and free ends pass the same cord-radius clearance check
  against the selected DP. Dependent Touch DP/PP stills have been regenerated.
- Current recipes produce 192 stills. PP/AP/TP anchor photos and the remaining
  electronics, cable-routing and knot teaching images are still being replaced.

## PP and AP tendon-anchor pictures

- The two PP anchor pictures now show the actual shared side pocket for the
  selected Base/Touch and hand side. `build_assembly_pp_anchors.py` locates its
  cylindrical CAD face, then plans both cords while checking the PP, neighboring
  AP, three PP pins and existing DP tendons. The left exit illustrations needed
  a 0.1 mm clearance adjustment. These paths are separate from live hardware.
- `build_assembly_ap_anchors.py` extracts the two curved anchor holes from
  transverse CAD sections. These are distinct from the four PTFE-lined channels.
  Both holes and their illustrated free ends pass 0.14 mm cord-radius checks
  against the selected AP.
- AP preparation and knot seating now use five render states: threading,
  reinforcing, settling, trimming and tucking. The 5 mm tail dimension is
  measured from the illustrated stopper's edge. Knot symbols indicate placement,
  with an accent wrap around the stopper; they are not Ashley topology lessons.
  Two redundant intermediate photos are omitted in Base/Touch because their
  meaning is covered by these states. Full retains its existing images.
- Current still recipes produce 220 images across the four available assemblies.
  The replacement is still incomplete, including Thumb AP/TP anchor pictures,
  some routing and electronics images, and the knot-teaching photographs.

## Spool winding geometry

- `spoolPaths.json` contains local paths measured from the current BaseSpool and
  SpoolCover solids. The winding radius of each CAD groove is 9 mm. The inner
  Ratchet_Main component is not the top winding surface.
- `spoolWinding.ts` follows those anchor passages, shows three wraps and traces
  a 5 mm return tail. Bottom wraps separate at the anchor mouth to accommodate
  the stopper and returning tail. The top cord follows the cover during fitting;
  the bearing and screw enter after winding and tucking.
- `stopperGeometry.ts` uses the continuous path in `spoolStopperShape.json` for
  spool-knot placement. Its endpoints match the winding and five-millimetre
  return tail. Nonadjacent strands remain separated by at least 0.259 mm for
  the illustrated 0.25 mm cord diameter. The Fundamentals photographs remain
  the tying instructions; this shape illustrates placement, not knot strength.
- The spool lessons support transparent inspection, scrubbing and comparison
  with the matching assembly photographs. Four spool stills are generated for
  each Base/Touch and left/right configuration. Per-joint bottom/top tendon
  assignments remain unconfirmed.

## Thumb DP/PP channel routing

- `thumbChannelRoutes.json` contains four separate tendon paths per Base/Touch
  and hand-side configuration, checked against the current DP/PP solids and all
  three PP pins. The scene shows the two prefitted pins, insertion of the upper
  pin, and 14 mm of each loose end. Transparent inspection reveals hidden paths.
- Sampled clearance checks cover all four cords at six assembly separations for
  each configuration (96 cases). The rendered cord diameter is 0.28 mm; the
  smallest sampled inter-cord separation is 0.341 mm. This check covers this
  joint assembly, not the later thumb AP/TP and palm routing.
- Finger and thumb framing includes the loose ends. Twelve dependent finger
  stills have been regenerated; the full manifest remains 248 images.

## Thumb PP/AP assembly

- `thumbApChannelRoutes.json` continues the four DP/PP paths into the selected
  AP channels. Each configuration has its own checked connections. In the right
  Touch assembly, the AP is rotated relative to the PP; its channel entrances
  therefore differ from those of the other configurations.
- `apStrands.ts` shows the complete passing paths, their loose ends and
  the two white AP anchor ends. The passing ends curve around the AP guide pins.
  The model includes the three prefitted PP pins and insertion of both AP pins
  before the AP bearings. Transparent inspection reveals the internal paths.
- Sampled checks cover DP/PP/AP solids at six joint separations, five guide pins
  and three AP-pin insertion positions. The minimum inter-cord distance is
  0.319 mm with 0.28 mm diameter rendered cords. These checks do not validate
  the later AP/TP routes or every bearing surface.
- This step uses the interactive model without a duplicate still gallery.
  Its original pictures remain available in the enlarged model/photo comparison.
  The still-image manifest remains at 248 images.

## Thumb AP/TP assembly

- `thumbTpChannelRoutes.json` carries all six passing paths from DP/PP/AP through
  the TP slot, plus the two TP anchor channels and their loose ends. Passing order
  follows the hand-side assembly diagrams. Colored paths retain their identity;
  the two TP anchor ends are white.
- The scene includes three PP pins, two AP pins and both 2×30 TP guide pins. The
  first five travel with the upper thumb while the joint closes. Pins also follow
  their owning part during bearing inspection; tendons are hidden in that mode.
- Sampled checks cover all eight cords against DP/PP/AP/TP solids, seven pins and
  one another at six separations for all four configurations (192 cases). No
  sampled collisions were found; minimum inter-cord spacing is 0.319 mm against
  a 0.28 mm rendered diameter. Bearings and skin envelopes are not covered by
  this clearance check.
- TP entry/exit views show the actual shared slot and six ordered cords. Their
  numbered markers use projected CAD coordinates, and enlarged views retain
  the matching original assembly photographs. The photo-only traced overlay
  is omitted for CAD views. The render manifest contains 264 images.


## Finger PP/AP assembly and flashing images

- `fingerApChannelRoutes.json` connects the checked DP and PP paths to the four
  Index AP channels. The PP extension loose end curves around the AP guide pins.
  `apStrands.ts` shares the rendering logic with the thumb AP lesson, retaining
  each configuration’s independent paths and two white AP anchor ends.
- The finger scene carries its three PP pins and inserts both 2×8 AP pins before
  seating the bearings. Its transparent view and framing include all six cords.
  Sampled checks cover DP/PP/AP, five pins and mutual spacing at six separations
  across four configurations (144 cases), plus 72 pin-insertion cases. Minimum
  inter-cord spacing is 0.831 mm against the rendered 0.28 mm diameter. Two mesh
  ray-test hits in the left Touch DP were rejected by exact solid classification;
  the nearest surface was more than 0.2 mm from the centerline. Bearings/skins
  are not covered by these cord-clearance checks.
- Console screenshots use the available width; the two Bench Helper states are
  stacked and captioned. Probe photos remain beside one another. The connector
  flashing screenshot spans the gallery, and all enlarged images retain their
  original colors. The terminal’s fixed right/Base example screenshot is omitted;
  the existing commands state the saved build’s side and version explicitly.


## Finger/carpal and carpal/wrist routing

- `fingerApAnchorRoutes.json` records both named side-anchor paths and their
  actual channel-mouth markers for every finger/configuration. Underside labels
  sit outside the opening with a leader; the p64 outlet diagrams use the same
  coordinates. Anchor identities preserve the documented pinky/thumb movement.
- `fingerCarpalRoutes.json` carries 24 complete AP-to-carpal paths per
  configuration, including both AP side anchors, the four passing channels,
  and 12 mm loose ends below the carpals. `carpalStrands.ts` splits each
  connector at a checked free span so it follows both parts during assembly.
  The full-hand tendon explorer reuses these seated paths.
- Sampled checks cover the four AP solids, carpal body/core, nearby guide pins,
  and mutual cord spacing at six separations for all four configurations
  (576 cord cases, 0.195 mm sampled offsets versus 0.18 mm rendered radius).
  The checks exclude all skin and bearing envelopes. The scene carries fitted
  finger pins during assembly and bearing inspection.
- The wrist scene follows all 32 continuous carpal/wrist paths to 12 mm loose
  ends. Full seated paths, wrist extensions, and six closing positions were
  checked against carpal body/core and wrist-frame solids. These checks do not
  establish clearance to every bearing, screw or belt. Transparent palm/wrist
  views draw the cords over the faded parts to expose otherwise hidden routes.
- Eight p64 channel images were regenerated from the current STEP assemblies;
  the manifest remains at 264 images. Original photos remain in the comparison.


## Thumb/carpal assembly

- `thumbCarpalRoutes.json` connects the six checked DP/PP/AP routes through TP
  and its two anchor paths to the eight corresponding carpal channels. Both
  TP anchor identities follow the measured hinge torque toward/away from the
  palm; this geometric identification still needs physical build verification.
  All eight paths end with 12 mm loose ends below the carpals.
- `carpalStrands.ts` serves the finger and thumb assembly views with independent
  path data. The thumb view carries all seven fitted guide pins, exposes the
  routes in its transparent view, and hides cords during bearing inspection.
  `handTendonPath` reuses the checked connections for all 32 tendon identities.
- Sampled thumb checks cover DP/PP/AP/TP, carpal body/core, adjacent finger APs,
  guide pins and mutual spacing at six separations across four configurations
  (192 cases, 0.155 mm sampled offsets versus 0.14 mm rendered radius). They
  exclude bearing and skin envelopes. A separate seated check of all 32 cords
  found no mutual intersections; the smallest centerline distance is 0.319 mm
  between two thumb cords (0.28 mm combined diameter).
- Eight thumb/carpal still assets were regenerated to keep the render library
  consistent. The walkthrough retains its interactive view without a duplicate
  still gallery, and offers the original photos in the enlarged comparison.

## Anchor and knot illustrations

- `anchorStopper.ts` uses the white, continuous cord paths in
  `anchorKnotShapes.json`. The shapes illustrate a dressed Ashley stopper with
  one or three overhand reinforcements surrounding it. The original eleven
  knot photographs remain the tying lesson. The packed paths were sampled for
  self-intersection; connecting strands were checked separately.
- DP/PP feeding views show two reinforced cord knots instead of colored balls.
  AP reinforcement and trimming views connect the actual anchor channel to the
  illustrated knot and show a measured 5 mm tail. The DP/PP framing includes the
  complete part; tucked-pocket views use naming leaders without a colored ring.
- `cadTpAnchorPreparation.ts` adds both TP anchor preparation views using the
  current STEP body and checked TP anchor channels. Each side has its own white
  cord and, in the reinforcement view, three reinforcing knots. Original images
  remain accessible through the enlarged comparison.
- Sampled checks cover 52 anchor scenes across the four configurations, including
  their cord radii against the owning printed part and connecting-strand spacing.
  The TP views reuse the previously checked loose-end paths. The knot shapes are
  illustrations, not a model of how a physical knot compresses inside its pocket.
- Forty-four anchor illustrations cover DP, PP, AP and TP preparation across
  the four configurations.

## Later assembly views

- `cadThumbFinishing.ts` uses the current TP/AP solids, both 2×30 guide pins,
  the two AP bearings, and the existing checked thumb routing. The pin view
  shows the shared slot; the bearing view labels the actual bearing parts.
  Touch AP bearings are 4×8×2 mm, whereas Base uses 4×8×3 mm. The preparation
  list and thumb-finishing instructions follow that configuration too.
- The carpal-row illustration marks all 32 measured outlets, with separate
  labels for the palmar and dorsal groups. The marks identify openings; they
  do not invent free tendon paths.
- Wrist-drive stills use the existing assembly sequence, hiding the tower
  mounting screws until their later fitting step. Rear-hull stills use the
  current cover and black OH board for each selected configuration. Connection
  and cable-handling photographs remain where the CAD lacks that detail.
- Seven additional views per configuration bring the render manifest to 300
  images. The original images remain in each enlarged comparison.
- `RoutingInspection.tsx` replaces the eight-image inspection gallery with one
  rotatable view selected between finger AP, thumb TP, and carpal/wrist routing.
  It reuses the checked assembly scenes at their seated position. Each view's
  enlarged comparison contains only its corresponding original photographs,
  including wrong/correct examples. Three small schematics explain clear,
  single-crossed, and double-crossed strands; they are conceptual examples,
  not replacements for a selected hand's channel mapping.

## Connected-hand pose

- `liveHandPoseScene.ts` poses all seventeen joints using the current STEP
  meshes. Parent transforms carry their downstream joints and attached parts;
  the wrist frame stays fixed. The selected joint remains visually emphasized.
- `livePoseFrames.json` records the saved CAD pose, actual bearing pivots, axis
  directions and parent relationships for each configuration. The saved poses
  were registered to the UI's canonical joint reference using pivot lines and
  hinge axes. Native DP/PP occurrence frames coincide at their terminal joint
  zero; terminal angles are not inferred from the different Base/Touch skins.
  `livePoseProvenance.json` records the STEP and kinematic-reference hashes.
- Across 104 reference poses (1,768 joint comparisons), the maximum difference
  from the canonical kinematics was 0.60 degrees in hinge direction and 0.88 mm
  perpendicular to a pivot line. These are model-registration checks, not
  measurements of a physical hand.
- `livePoseTelemetry.ts` selects encoder measurements or the active commanded /
  estimated pose, with the same units as the console and per-joint ROM bounds.
  A disconnected, mismatched or uncalibrated hand shows the assembly reference.
  Missing angles are marked as incomplete telemetry, not silently called live.
- The control slider still starts at zero offset from the angle returned when
  enabling torque. Updating the display sends no commands. The existing
  explicit-enable, one-joint, ROM, ownership and release-on-close behavior is
  retained. Physical-hand alignment and motion still require hardware review.

## Optional arm mounting

- `cadArmMount.ts` renders the adapter and rods, separated hull covers, and a
  translucent tower alignment view from each current STEP configuration. The
  alignment view hides drive components to expose the rods. The rear cover
  and its board move together; cable slack must be checked on the physical hand.
- The appendix orders the images by operation: adapter, covers, alignment,
  securing hardware, then cables. Enlarged CAD images retain their matching
  original illustrations. FeeTech and Full retain the original mounting images
  because these CAD scenes describe the supplied Base/Touch Dynamixel models.
- Mounting hardware is optional in the BOM and CSV. Four M6×8 screws are listed
  separately; additional M3×14 mounting screws share the existing fastener row,
  with an explicitly unconfirmed optional count. Required hand-build quantities
  remain separate: 8 M3 nuts, 5 M3×14 screws and 5 M2×8 screws for these models.
- The mounting references conflict: written instructions say 3 M3×14 securing
  screws; the older illustration says 4, and the supplied adapter has 4 radial
  bores. The old image specifies M5×100 rods; current rod geometry is 80 mm long.
  The rod thread and mounting screw count require confirmation from the kit.
  Neither bore count nor the older illustration is treated as an installation
  specification. The guide flags these details before mounting.

## Seated AP stoppers

- `seatedApKnots.json` places the existing continuous knot geometry in both
  Index and Thumb AP housings for all four current assemblies. Each placement
  keeps the illustrated cord diameter and reinforcement count unchanged.
  Each tucked tail follows a five-millimetre return path beside its stopper.
- `cadApAnchorPreparation.ts` uses those poses for the settling and tucked
  views. Settling shows one stopper and its untrimmed working end; the final
  view shows both stoppers and tucked tails through a transparent AP. The
  measured tendon passages and the two PTFE liners remain in the scene.
- Sampled cord envelopes clear the owning AP solid in all sixteen scenes.
  Separate checks cover cord-to-cord and cord-to-liner spacing; the latter's
  minimum centreline distance is 2.43 mm. These checks establish illustration
  clearance, not physical knot compression or holding strength. The matching
  photographs and the Ashley tying lesson remain available.
- Thumb seating has three instructions: settle, trim to five millimetres,
  then reseat and tuck. Each figure and its original photo correspond to the
  appropriate instruction. The completed-step checkbox remains manual.

## Tower cable openings

- `cadTowerWiring.ts` illustrates the upper motor-cable slot and lower fan-cable
  slot with short cable segments. It uses the actual tower and two fans from
  the selected assembly; it does not depict cable connectors or cut lengths.
- Seven curves show the three motor-lead wires and two red/black fan pairs.
  Their sampled envelopes clear the current tower and fan solids with a
  0.46 mm checking radius, compared with the illustrated 0.4 mm wire radius.
  The minimum separation between different wire centrelines is 1.2 mm.
  Native tower and fan mesh positions match across all four supplied models.
- The FeeTech kit names its board-to-motor adapter lead instead of the
  Dynamixel 180 mm 3-pin cable. FeeTech and Full retain the original reference
  photographs; the Dynamixel-only tower render is not shown for those builds.
  The three M4 nut picture is linked to the final instruction in this step.

## Touch DP flexion through PP

- The Join DP and PP viewer uses the Touch PP's internal flexion passage. Its
  depth changes near the entrance; the previous constant-depth route went around
  the outside of the body. Both Touch hand sides now follow the measured passage.
- `scripts/repair_assembly_touch_pp_routes.py` recreates the route from the Base
  path in joint coordinates, adjusts its depth against the actual Touch mesh,
  and plans the short entrance bend around both seated DP and PP surfaces.
  It requires NumPy and writes a staging JSON via `--output`.
- Dense samples of the 0.16 mm checking envelope clear DP, PP and the installed
  pins; the viewer's cord radius is 0.14 mm. The Base and extension paths retain
  their existing coordinates. These are illustration checks against CAD meshes.

## Touch sensor fitting order

- Touch DPs have no skins. Early finger/thumb assembly fits PP skins and
  bearings only; the fitting and movement viewers leave fingertip sensors off.
- The complete Touch section follows hand, tower and hull assembly: sensor kit
  preparation, IDs, cable preparation/routing, sensor fitting, connector-board
  mounting and harness connection, then sensor testing. Board flashing remains
  with the electronics steps after Tower.
- Review the completed hand after sensor installation, then continue to
  tensioning in Setup.
  Stable step IDs preserve saved progress while navigation follows this order.
