# ORCA assembly guide — handover

Updated: 18 October 2026. Intended for the next Astra/Codex instance and human maintainers.

## Start here

The assembly guide is implemented in this checkout. Open **Setup → Open assembly guide**. It runs as a modal inside the existing application, on the same origin and port, and restores the builder's configuration, position and checklist progress.

The goal is a self-contained guide that makes building the hand straightforward without needing to consult the teaching PDF or ask for missing instructions. The current version is substantial and reviewable, but some mechanical specifications and procedures remain unresolved. Do not describe it as a physically validated, independently complete assembly manual yet.

Read this document first, then [the assembly implementation notes](frontend/src/components/assembly/README.md), [DEVELOPMENT.md](DEVELOPMENT.md) and [CLAUDE.md](CLAUDE.md). The assembly README contains detailed historical development notes; some early statements are superseded. In particular, its opening statement that the guide never starts a hand operation predates the explicitly enabled connected-hand test described below.

## Direct editing and fixed hand navigation · 18 October

The hand navigator is a fixed panel above an independently scrolling table of
contents (`AssemblyNavigation.tsx`). Selecting a hand region expands its chapter
and reveals the active timeline entry; the same behavior applies when reopening
the mobile navigation. The hand does not move when the contents are scrolled.

Guide prose now uses `GuideText` fields: step titles, instructions, notes, parts,
tools, checklists, captions, glossary entries and lesson text. Titles update in
the timeline and search uses edited step titles/instructions. Operational status,
errors, control buttons and labels baked into image/3D assets remain outside this
text editor. Fields grow with the text and have per-field restore controls.

`GuideEditing.tsx` stores drafts separately from build progress in browser
localStorage (`orca-ui.assembly.editor.v1`). Text edits are scoped to configuration
and retain the original text alongside the replacement. A changed source does
not silently inherit an old override. Dynamic lesson cues retain separate edits
for each original cue. Starting a new build does not delete editorial drafts.
**These are local review edits, not writes to repository content or changes shared
with other browsers.** Export edits downloads `orca-assembly-edits.json` with text,
background overrides and saved colors for a maintainer to apply to source.

The Background colors panel supports page/sidebar/hand/contents shortcuts and
Pick an area for individual cards and model backgrounds.
The picker targets the visible image/model surface, not only its outer wrapper.
Earlier saved wrapper colors also apply to the nested media surfaces. Overrides
remove background gradients and restore them on undo; more specific nested
surface choices take precedence. Opening the picker selects Page by default,
and its controls stay reachable while scrolling to an area. A hue/saturation wheel,
brightness slider, native picker, hex field, presets and saved swatches apply
changes immediately. Global surfaces persist across steps; individual card colors
are scoped by configuration, step and component occurrence. Restore background
removes an override. Colors change the surfaces behind media; they do not repaint
pixels inside photographs or materials on the 3D parts. The editor is confined
to the assembly guide and does not change hardware operations or completion.

Validation: production build and browser checks of fixed navigation and chapter
reveal on desktop/mobile; title/instruction/checklist editing without checkbox
activation; wheel, brightness, presets, saved colors, background selection, export,
reload persistence and per-field undo. No permanent tests added.

## Thumb cable-channel method and Touch skin order · 18 October

This update supersedes the earlier skin timing described below. Touch fingers and
thumb remain completely bare during mechanical preparation and tests. `buildSteps`
inserts Touch sensor preparation, routing, connection and fastening immediately
after `thumb-test`, followed by the new `touch-skins` step. The connector-board
mount/connect/link steps stay later, once the carpals, flashed board and OH board
are available. Cable tails remain free until carpal installation. Base skin timing
is unchanged. The navigation phases are Prepare → Build the fingers → Build the
hand (carpals, wrist and tower) → Complete the hand.

Thumb preparation now reuses the Ashley lesson, its local video, the tendon
measurement diagram and single-knot reinforcement lesson. Of the ten 2 m lengths,
nine are preknotted; the thumb PP length stays unknotted. Its sequence is top entry
→ cable-channel access → tie outside → return through the same channel → seat
stoppers and tuck the loop. Existing 10 mm ±5 mm spacing and one reinforcing
single knot per stopper are retained. `ThumbPpThreading.tsx` pairs the selected
CAD PP with a three-stage **schematic**, not a measured internal cable-channel
trajectory. The DP feed/seat/tuck renders use the actual Thumb DP and existing
thumb tendon route data for all four Base/Touch × left/right configurations.
Regenerate these `thumb-*` assets through `render_assembly_illustrations.mjs`.

`p49` now includes AP threading, three-knot reinforcement, settling, trimming and
tucking; `p52` is removed. All five relevant AP illustrations remain at their
matching instruction. `guide:thumb-cables=oct18-v1` redirects old `p52` positions
to `p49`, preserves merged completion only if both former steps were checked,
and clears changed thumb-PP, tendon-preparation and sleeve checks once. Touch
skin completion does not transfer to the newly placed skin step. Progress remains
checkbox-driven; navigation alone never completes a step.

PTFE screw sleeves are now ID 2.7 / OD 4 mm in instructions, parts lists, BOM,
supplemental geometry and belt-clearance calculation. **Open specification issue:**
the listed/STEP screws are still M4, which conflicts with a 2.7 mm sleeve bore.
The user supplied the tube dimensions; do not silently change screw sizes or
claim this interface has been physically validated. The thumb PP cable-channel
method and later Touch skin fitting also need a physical build check.

Validation: TypeScript and production Vite build; data/order/migration checks
across 48 configuration/access/flashing combinations; packaged-UI browser review
of thumb visuals, PP sequence controls, Touch order, mobile layout and saved
checkboxes. New stills are 1800 × 1400 transparent WebP, with generated production
copies under `orca_ui/webui`.

## Navigation and PTFE hints · 18 October

The chapter labels are **Your ORCA hand** and **Glossary**. Glossary opens with
**Hand anatomy**, followed by **Ashley stopper knot**. Existing step IDs and saved
checks are preserved. The mobile chapter label uses the same display names.

The PTFE tips (`p20`, `p22`) have `hint: true`: indented HINT entries, no step
number or completion checkbox, and excluded from progress and chapter totals.
Previous/Next skips hints; the two liner steps also link to them directly.
Hints remember the originating step and offer Return to assembly.
Their content remains searchable and the saved current page can still be a hint.

The sidebar now uses small transparent CAD renders (`assembly/navigation`) with
invisible SVG hit regions, instead of drawn part outlines. Base and Touch have
separate assets; the left-hand view mirrors the right. Regenerate using
`scripts/render_navigation_hand.py` with Python Playwright, Chrome and Vite.
The UI loads only the small images and hit-region JSON, not a GLB for navigation.

AP, carpal and wrist PTFE liner images use white backgrounds and opaque parts.
The optional tube-pulling illustrations also use solid parts on white. Gallery
cards with a matching assembly photo have a translucent right-arrow button to
switch views inline; enlarging opens the currently visible view.

The index-finger chapter uses `AssemblyStep.section`: Preparation (tendons and
printed parts), DP, PP, AP, then Assembly (join DP/PP, join PP/AP, skins, whole
finger test). PP skin and bearings are prepared before closing the PP/AP joint;
the final skin step fits the DP skin where used and seats the existing PP skin.
`pp-ready` is new. `p35` now tests all six index tendons; its former upper-pin
instruction and images are part of `p33`. Changed completion meanings (`p31`,
`p33`, `p35`, `finishing-pp`) are cleared once by `guide:finger-layout` migration;
unaffected checks remain saved. Navigation still never completes a step.
The generic bearing-hammer note and hammer/support-block tool entries are removed.

## Thumb structure and reduced visual repetition · 18 October

The thumb chapter now follows the finger chapter: Preparation, DP, PP, AP, TP,
then Assembly. Two preparation steps identify the existing tendon pair and the
printed parts. DP/PP preparation, PP skin/bearings and TP pins have dedicated CAD
views; AP/TP anchor instructions retain their original measurements and knot
reinforcement. Assembly keeps the hand-side routing, joins the prepared parts,
seats the skins and ends with an explicit eight-tendon check.

The sidebar thumb target opens `thumb-tendons`. Existing `p46`, `p59` and `p62`
IDs remain, but their preparation/testing content has moved to dedicated steps;
`guide:thumb-layout` clears just those three completion marks once. Anchor-step
checks remain saved. The unresolved AP routing note is retained.

The redundant seated DP/PP still (`panel-034-6`) is excluded from that step's
image gallery. The numbered phase bar is removed from joint animations; play,
scrubbing, routing selection and the current explanatory cue remain. Knot lesson
controls are separate and unchanged.

Validation: production build; all 48 build/access/flashing combinations; all 15
thumb pages; left/right Base/Touch preparation part counts; browser navigation,
scrubbing, saved checks and mobile layout. The thumb AP route remains subject to
the existing physical verification described below.

## Current review edition

The latest feedback revision is in `orca_ui_assembly_review`, branch
`feature/assembly-feedback-touch`. See [the feedback review](docs/assembly-feedback-review.md)
for current layout behavior, validation and unresolved mechanical specifications.
All numbered instructions are visible together; media follow their matching
instruction; supplementary video comes after the checklist and navigation. Review
notes are kept in documentation rather than shown inside the build flow. The PP
preparation now has its own step before joining PP to DP. Joint demonstrations
cover the bundled model's full ROM; live hardware test limits are unchanged.

### Reproducible installation

This branch pins the published `orca_core==0.6.0` in `pyproject.toml` and
`uv.lock`. No local core source override belongs in the shared branch. The
current-default compatibility fixes and frontend build are included. Follow the
README's assembly quick start (`uv run orca-ui --mock --host 127.0.0.1 --port 5005`).
The four model ZIPs extract at startup; Node and a separate core repo are not
required. CI tests the assembly branch against the locked release, including on
push, rather than substituting a local core checkout.

The repository observations below describe the earlier handover, not the latest
review worktree or current remote state.

## Repository state at original handover

- Working checkout: `/Users/kaistewart/Documents/Projects/orca/orca_ui`.
- Local branch: `feature/better_stat_logging`.
- Assembly implementation commit: `0b5af9f` (`clean assembly guide in the ui`), including the latest darker mint background.
- The user reported pushing to main. A subsequent check of `git@github.com:orcahand/orca_ui.git` found remote main at `fbfdaab`, without the assembly implementation, and the remote feature branch at `e052e3a`. **Recheck before assuming the guide is available from main.** This is a dated observation, not a permanent branch instruction.
- `pyproject.toml` and `uv.lock` contain pre-existing local changes. Preserve them; check the repository rules for local `orca_core` overrides before staging anything.
- This handover is a documentation addition after the implementation commit. No commit or push is performed as part of writing it.

Keep changes scoped to the guide unless explicitly asked otherwise. The user specifically requested that unrelated ORCA UI functionality remain unaffected.

## Current experience

- Native modal launched from Setup; no new browser window or duplicate UI instance.
- Configuration chips beneath the opening title select hand side, motors and **version**. Use “version”, not “sensing”. The saved configuration controls subsequent content.
- Complete STEP-derived Base/Touch × left/right Dynamixel assemblies. Touch structural parts and skins are black.
- Slider-controlled explosion into Thumb, Fingers, Carpals, Wrist and Tower areas. Standard hardware is grouped into kit icons with expandable detail. Tendons, PTFE and cables are represented in the relevant inventories.
- Consolidated BOM and CSV export. Identically named standard components are grouped with quantities, including the left Touch M1.4×4 screws, shown once as eleven screws.
- Fundamentals cover the Ashley stopper knot and hand terminology, including palmar/dorsal views and movement names. Checks and fitting instructions appear where the builder needs them rather than being front-loaded into fundamentals.
- Step-specific CAD illustrations, joining/routing animations, enlarged views and local video excerpts. There is no PDF viewer or source-document navigation in the walkthrough.
- Selected original photographs remain when they explain information absent from CAD or provide a useful enlarged comparison. **Not every photograph has been replaced.** Board connector identification, for example, still needs photographs because those details are missing from the supplied OH model.
- Explicit checklists drive completion in the left timeline. Browsing, animation playback and pressing Next never complete a step automatically.
- A 17-motor mechanical review and an explicitly enabled connected-hand joint test are available. The latter can issue hardware commands; do not mistake it for a passive illustration.

Full and FeeTech have adapted walkthrough content, but complete matching CAD assemblies were not supplied. They must not silently display a substituted Base/Dynamixel model.

## Design language to preserve

The visual direction is a quiet, practical assembly workspace: clear hierarchy, generous spacing and precise illustrations, with minimal decoration.

| Element | Current choice | Purpose |
| --- | --- | --- |
| Light page surface | Warm off-white `#f6f5f1` | Comfortable reading and a continuous workspace |
| Illustration surface | Muted mint `#91a89a` | Contrast for white tendons and PTFE |
| Illustration labels | Dark green `#24533f` | Readable, restrained annotations |
| Light-theme action accent | Teal `#0f6f78` | Navigation and interactive states |
| Headings/body | System sans-serif; large, tightly spaced headings | Clear reading hierarchy |
| Small metadata | Space Mono | Step numbers, compact labels and technical context |
| Panels | Thin borders, modest rounding, minimal shadow | Group content without visual clutter |

The user explicitly requested progressively darker illustration backgrounds so white tendons remain visible. The latest value is `--assembly-image-bg: #91a89a` in `assembly.css`; do not revert to the earlier pale mint. Routing diagram masking strokes use the same variable. Some baked label backplates retain a lighter mint, which helps separate their text from the illustration.

Presentation conventions:

- Put concise, numbered instructions before their image panels. Link each illustration to the action it explains.
- Preserve the complete image aspect ratio; provide an enlarge action instead of cropping away useful geometry.
- Use short naming labels on images. Keep explanatory sentences in the instructions.
- Use white tendons with fine outlines where necessary; use color only where it communicates an actual mapping or distinction.
- Keep the relevant component opaque and fade surrounding geometry. Transparent housings can reveal internal paths.
- Prefer measured CAD geometry and configuration-correct parts. Do not invent hidden routes to make an illustration look convincing.
- Use a single useful, controllable animation at the relevant step instead of repeating generic animations.
- Blend illustrations into their panel surface; avoid unnecessary white rectangular photo backgrounds.
- Use local, bounded clips with native video controls, not a full YouTube player or the entire recording.
- Keep source provenance in developer documentation, not the builder-facing workflow.

## Code and asset map

Paths below are relative to the repository root.

| Location | Responsibility |
| --- | --- |
| `frontend/src/components/assembly/AssemblyCard.tsx` | Setup launcher, native dialog, loading/error boundary, emergency-stop access |
| `frontend/src/components/assembly/AssemblyGuide.tsx` | Main guide composition and navigation |
| `frontend/src/components/assembly/guide.ts` | Stable step IDs and chapter structure |
| `frontend/src/components/assembly/buildContent.ts` | Configuration-specific instructions, filtering, parts and caveats |
| `frontend/src/components/assembly/assembly.css` | Scoped guide styling and illustration color tokens |
| `frontend/src/components/assembly/PartsExplorer.tsx` | Exploded assembly, area dialogs and BOM presentation |
| `frontend/src/components/assembly/assemblyParts.ts` | Supplemental inventory and standard-part grouping |
| `frontend/src/components/assembly/cadIllustrations.ts` and `cadIllustrationScene.ts` | Illustration recipes and scene dispatch |
| `frontend/src/components/assembly/cad*.ts`, route JSON and scene modules | CAD assembly scenes, measured routes and placements |
| `frontend/src/components/assembly/local-clips.json` and `media-catalog.json` | Local media selection and metadata |
| `frontend/src/components/assembly/progress.ts` and `useAssemblyProgress.ts` | Progress validation, migration and serialized persistence |
| `frontend/src/components/assembly/LiveJointTest.tsx` and `jointTestControl.ts` | Explicit connected-hand test and eligibility/command gates |
| `frontend/src/components/assembly/liveHandPoseScene.ts` and `livePoseTelemetry.ts` | CAD pose display and telemetry selection |
| `orca_ui/api/assembly.py` | Assembly-only progress API |
| `frontend/public/assembly/` | Source static assets: models, renders, images and clips |
| `scripts/build_assembly_parts.py` | STEP import and assembly inventory generation |
| `scripts/render_assembly_illustrations.mjs` | Walkthrough render generation from the shared CAD scenes |
| `scripts/import_assembly_guide.py`, `refine_assembly_panels.py`, `import_assembly_clips.py` | Teaching-document and recording import tools |
| `orca_ui/webui/` | Packaged frontend served by the Python application |

The current render library contains 328 CAD illustrations. Before the final color-only adjustments, source/package asset equality and source fingerprints were checked. The background adjustments changed CSS, not geometry or the render library.

Current complete STEP source archives on the development machine (the extracted files are not currently present beside them):

```text
../orca_files/orca_v2/base/Orcahand_BaseV2_Left.zip       → Base_Left.step
../orca_files/orca_v2/base/Orcahand_BaseV2_Right.zip      → Base_Right.step
../orca_files/orca_v2/touch/TouchV2_Assembly_Left.step.zip  → TouchV2_Assembly_Left.step
../orca_files/orca_v2/touch/TouchV2_Assembly_Right.step.zip → TouchV2_Assembly_Right.step
```

Do not regenerate from older Touch archives. Generation includes downstream mesh refinements, measured routes and scene metadata; read the assembly README before rerunning the importer. A base import alone is not the entire refinement pipeline.

## Model archive update — 13 October

The user subsequently requested zipped model distribution and automatic extraction.
The four complete assembly GLBs are now packaged separately under
`orca_ui/models/assembly/` as `base-left-dynamixel.zip`, `base-right-dynamixel.zip`,
`touch-left-dynamixel.zip` and `touch-right-dynamixel.zip` (approximately 47–51 MiB
each). Their full local copies remain at the existing source/package asset paths,
are ignored by Git, and have been removed from the Git index without deleting them.

`orca_ui/assembly_assets.py` restores the models during backend startup. It checks
existing copies, skips unchanged outputs and atomically restores missing or changed
ones. Failures are logged and do not prevent the console starting. The opening
viewer offers recovery instructions naming the selected ZIP and a Retry model
button. Unsupported Full/FeeTech configurations retain their separate unavailable
message. Runtime model URLs and geometry are unchanged.

`python scripts/package_assembly_models.py` rebuilds the ZIPs from source assets;
run it after intentional geometry changes and before restarting the backend, which
treats the archives as authoritative. `uv run python -m orca_ui.assembly_assets`
performs manual restoration. See [the archive README](orca_ui/models/assembly/README.md).
The Python build artifact configuration excludes unpacked web UI models and their
validation markers so packages distribute the ZIPs rather than duplicate full GLBs.

Verification covered clean extraction, unchanged startup, deleted/corrupt outputs,
changed archives and failure isolation. All four real ZIPs passed integrity checks.
Wheel and source-distribution file enumeration each included four archives and no
unpacked models/markers. The production build and three progress API tests passed;
lint retained only the existing warnings. Chromium verified all four archive names,
the separate unsupported-configuration state and successful model retry. A fresh
mock backend launched from `/tmp` served the restored GLB successfully.

This solves storage distribution, not browser memory or download size: browsers
still load the full restored models. The lighter geometry pipeline proposed below
remains future work. Earlier Git commits still contain large binaries; no history
rewrite or push was performed. Removal from the index alone does not fix an oversized
object already present in unpublished history.

## Persistence and compatibility

`GET/PUT /api/assembly/progress` stores one build at `~/.orca_ui/assembly-progress-v2.json`, with validation and atomic replacement. Browser storage under `orca-ui.assembly.v2.1` provides fallback. Server persistence matters because the desktop shell can discard its browser profile.

Saved state includes the current step, build configuration, completed steps, checklists, tendon checks and selected views. Writes are serialized across modal mounts. Preserve stable step IDs and migrate incompatible state explicitly. Configuration changes invalidate relevant checks; do not allow completion for one configuration to imply verification of another.

The progress API is independent of hand configuration. Never reset the user's progress as part of a smoke test.

## Validation and local development

The latest background-only change passed the TypeScript/Vite production build and a Chromium check against the packaged mock UI. Its computed illustration background was verified as `rgb(184, 206, 191)` and the PTFE lesson was visually inspected.

Earlier work included browser checks across configurations, content/media audits, BOM grouping checks, progress persistence checks and CAD geometry/pose checks. These are software checks, not a physical build sign-off. Existing frontend lint reported five unrelated `react(only-export-components)` warnings in `CalibrationRomChart.tsx`; the large assembly JavaScript chunk also produces a build-size warning.

Useful commands from the repository root:

```sh
npm --prefix frontend run lint
uv run pytest tests/test_assembly_progress.py
npm --prefix frontend run build -- --outDir /tmp/orca-assembly-handover-build
cp -R /tmp/orca-assembly-handover-build/. orca_ui/webui/
```

Use a fresh temporary output directory when needed. The overlay build preserves unrelated local files in the packaged UI. It also leaves historical hashed bundles behind; treat any future cleanup as a separate reviewed task. Static assets belong in `frontend/public/`, not only in `orca_ui/webui/`.

For behavioral changes, select appropriate tests under the repository's deliberately small test-suite policy. A documentation or simple color edit does not require a new permanent test. Do not run a full render regeneration for a CSS-only change.

Session-local services and tooling at handover (check that they still exist before reuse):

- `http://localhost:5003`: user's preview. Do not reset its saved progress.
- `http://127.0.0.1:5002`: isolated mock backend, using `/tmp/orca-test-progress.json` via `/tmp/orca_test_server.py`.
- `http://127.0.0.1:5180`: Vite frontend explicitly proxied to mock port 5002, configured in `/tmp/orca-objective-oct12/vite.mock.config.mjs`.
- Do not assume any other Vite port is isolated. In this session, port 5178 could proxy to the real-hand backend on 5001.
- `/tmp/orca-assembly-browser/`: Playwright tooling and ad hoc review scripts; Chrome was used for browser checks.
- `/tmp/orca-objective-oct13/library-review/`: render-library and UI audit artifacts.
- `/tmp/orca-objective-oct13/spool-source-review/`: investigation of unresolved spool assignments.

These temporary files are convenience artifacts, not portable dependencies. On a new machine, recreate an isolated mock setup using [DEVELOPMENT.md](DEVELOPMENT.md), explicitly checking both API and WebSocket proxy destinations and isolating the progress file.

## Unresolved assembly information

Do not guess these details or infer installation specifications solely from a plausible-looking CAD view.

| Issue | Current limit / required confirmation |
| --- | --- |
| Bottom/top spool mapping | Joint pairs and motor identities are available, but per-joint bottom/top assignment and winding direction are not confirmed for the current builds. Older official instructions use different hardware and cannot settle this. |
| Fan fasteners | Written instructions specify M3×14; current Base/Touch CAD contains M3×12. Confirm the supplied kit and clearance. |
| Top-spool fasteners | Written instructions specify M2×8; current CAD contains M2.5×8. Confirm the supplied part. |
| Finger bearings | Some instructions describe 4 mm thickness; supplied CAD identifies 4×8×3 bearings. Confirm the intended hardware. |
| Arm mounting | Written securing-screw count is three; an older illustration and current bore count suggest four. The old rod specification and current 80 mm rod geometry also differ. Confirm the kit's count, length and thread. |
| Sensor installation | Touch/Full installation procedures are not fully documented by the supplied teaching material. |
| Other configurations | Complete Full/FeeTech assemblies are missing; some harness lengths are unspecified. |
| Silicone appendix | Material product and demolding time are unspecified; documented quantities describe Base skins. |
| Physical validation | Complete a real build and verify alignment, routing, friction, holding strength and powered movement. Mock or geometric checks do not establish these. |

The connected-hand test includes explicit enable, mapping/eligibility checks, bounded joint travel and release behavior. Preserve those gates. Existing Setup remains responsible for tensioning and calibration. Never claim hardware has been tested based on a mock session.

The previous broad implementation effort stopped at unresolved information, not because these issues were completed. Continue independent improvements when requested, but obtain authoritative specifications before implementing dependent mechanical instructions.

## Proposed next phase — requested concepts, not implemented features

### A slide-based authoring workflow

Make the guide easy to maintain as a sequence of slides or instruction pages. A contributor should be able to add a step, replace a picture or revise a caption without editing React layout code, while the UI automatically applies the established design language.

A PDF or presentation should remain a convenient input and review format. The recommended implementation direction is a structured, slide-like content model behind it: stable step ID, title, instructions, configuration applicability, media, annotations and checklist. Shared UI templates would render this content consistently. An import/review workflow could turn new presentation pages and images into those records; a PDF export could support offline review.

This is a proposed direction, not an agreed file format. Evaluate PDF/presentation import versus a simple structured authoring format with the team. Avoid making a flattened PDF the only source of truth: it cannot express interactive routing, variants and saved checklist state reliably. Keep stable IDs so adding or reordering slides does not invalidate existing progress.

### A lighter CAD and asset pipeline

Replace the current dependence on large monolithic GLB exports from STEP. The user has identified asset size as an obstacle to pushing and sharing the project through Git. The pipeline should make normal development, distribution and review practical without sacrificing the clarity of small parts or tendon routes.

Separate engineering source files from delivery assets. Investigate reusable component meshes, instancing of repeated hardware, compression, levels of detail and loading only the geometry required by the current lesson. Static illustrations can serve steps that do not require interactive 3D. Large source and release assets could live in versioned artifact storage, with small manifests and checksums in Git.

Measure transfer size, load time and visual quality before choosing the approach. Preserve part identity, counts, coordinate frames, configuration provenance and annotation anchors. Do not indiscriminately decimate thin channels, small fasteners or surfaces that explain tendon routing. Storage changes must account for the desktop/package distribution and any intended offline use; do not introduce an unnoticed network requirement.

### Repair and component replacement walkthroughs

Extend the guide with dedicated service procedures for replacing or repairing fingers, tendons and cables. These should be accessible directly by component or problem, rather than requiring the user to replay the full assembly sequence.

Each procedure should identify symptoms and prerequisites, required parts/tools, access and disassembly, replacement, reassembly, and a final functional checklist. Include isolation of power where required, tendon routing/tension restoration and any recalibration that the procedure actually needs. Reuse existing illustrations and shared steps where appropriate, but write service-specific sequences: removal is not always assembly in reverse.

Apply the same configuration filtering, visual language and explicit completion behavior. Define how service progress relates to the original build record so a repair does not silently overwrite assembly completion. Validate each procedure against the physical hand before treating it as complete.

## Suggested pickup order

1. Verify the checkout and remote state; open the existing guide before changing anything.
2. Confirm the user's next priority among content authoring, asset size and repair workflows. These are proposed projects, not permission to rewrite all three at once.
3. Review a representative Base and Touch configuration, including the opening explorer, PTFE lesson, routing views and BOM.
4. Resolve the outstanding hardware specifications with the build owner and record the authoritative decisions next to the relevant content.
5. Make focused changes, preserve the design tokens and stable progress IDs, rebuild the packaged UI and verify against an isolated mock backend.
6. Arrange a physical walkthrough for assembly and service procedures. Record remaining uncertainties explicitly rather than hiding them with polished visuals.

## Tendon visibility fixes — 14 October 2026

These changes are local and uncommitted. The packaged frontend has been rebuilt.
The issue had two causes: cameras fitted the part bodies without accounting for
the complete tendon paths, and the thumb finishing stills omitted DP/PP bodies
while drawing their tendons. No measured routing coordinates or model archives
were changed.

Use the titles below to locate the steps; timeline numbers vary with configuration.
The `p…` identifiers are stable internal IDs, not displayed step numbers.

| Step | Visible change to verify |
| --- | --- |
| Fingers → Check the PP joint (`p35`) | The pin-clearance illustration now includes the complete DP/PP bodies and tendon ends (`panel-036-2`). |
| Fingers → Prepare and seat the AP tendons (`p37`) | The tucked-tail illustration includes the full free tendon end instead of framing only the AP housing (`panel-041-5`). |
| Thumb → Seat the thumb AP knots (`p52`) | The tucked-tail illustration uses the same complete tendon framing (`panel-053-5`). |
| Thumb → Finish the thumb (`p62`) | Both guide-pin and bearing illustrations now show translucent DP/PP bodies around the previously floating routes and fit the complete thumb paths (`panel-063-1`, `panel-063-2`). Its interactive view also fits the current canvas. |
| Wrist & routing → Inspect every tendon path (`p80`) | All three inspection tabs fit the full model and tendon paths to both canvas dimensions, including the enlarged inspection zoom. |
| Wrist & routing → Verify all 32 tendon identities (`p83`) | Selecting a tendon now recenters and fits its complete view, including narrow canvases where thumb, middle-PP and pinky selections were clipped. |

The same responsive animation framing applies to **Join DP and PP** (`p33`),
**Assemble the AP** (`p42`), **Assemble thumb DP and PP** (`p46`),
**Assemble the thumb AP** (`p54`), **Attach the four fingers** (`p64`),
**Attach the thumb** (`p68`), **Seat the hand in the wrist** (`p89`),
**Thread the bottom spools** (`p123`) and **Fit the top spools** (`p126`).
The two spooling steps also use the corrected tendon-selection viewer.
Framing updates on slider changes and resizing. Manual orbit, pan and zoom remain
available; deliberately zooming or panning outside the model is not prevented.

Twenty stills were regenerated: five illustrations for each of Base/Touch ×
left/right Dynamixel. Source and packaged copies match. Existing colors, labels,
checklists and saved progress are preserved.

Verification: the production build and frontend lint pass (five pre-existing
CalibrationRomChart export warnings). A scene audit found no clipped sampled tube vertices
in 208 tendon-containing stills across the four configurations. Runtime checks
covered 624 animation/inspection states at multiple canvas sizes and 256 tendon
selections (all 32 identities × four configurations × wrist/spool views), with no
clipped sampled tendon vertices. Six affected steps were opened in the packaged
UI on an isolated mock backend and screenshots reviewed. This verifies rendering,
not physical routing or assembly correctness. Full/FeeTech do not gain new CAD
coverage from this change.

Temporary review evidence is under `/tmp/orca-tendon-review-oct14/`, including
`after-scenes.json`, `motions-verified.json`, `drive-verified.json`,
`packaged-review.json` and screenshots. These are development artifacts and are
not required to run the guide. The user's preview progress was not modified.

### Second sweep and standalone comparison

A second sweep on 14 October reviewed all 328 current illustrations across the
four complete CAD configurations. No further image or route edits were needed.
The audit now checks every tube vertex and reproduces the renderer's special
carpal-exit crop. This corrects a limitation of the first audit: `panel-017-1`
intentionally clips internal PTFE lengths in all four configurations while keeping
all 128 exits fully inside the frame. The other 204 tendon/PTFE-containing stills
are fully framed. All 512 published overlay coordinates agree with projections
from the current scene geometry.

Repeated runtime checks passed for 624 animation/inspection states and 384 tendon
selections, now explicitly including both bottom- and top-spool viewers. Assembly
scene bounds and detached-geometry candidates were also inspected at 21 slider
positions (840 states). Pulled-out knots, free working ends and the spool's 8 cm
measurement are intentional; these were reviewed rather than moved arbitrarily.
Evidence is in `/tmp/orca-tendon-sweep2/`.

Open [the standalone image comparison](tendon-image-comparison.html) directly in a
browser. It defaults to the 20 before/after pairs and offers a full-sweep view of
all 328 current illustrations. Unchanged images appear once. Configuration and
step/image search filters, enlarged views, and the review summary work offline;
all images are embedded. The original baseline remains commit `3985b50`, before
the first tendon-visibility pass. This is a still-image comparison, not an embedded
interactive CAD viewer.

The comparison can be regenerated without Node or CAD software:

```sh
python3 scripts/build_tendon_comparison.py --review-report docs/assembly-tendon-review.json
```

The JSON report records this completed sweep; update it after a new review rather
than assuming that regenerated images have been reviewed. The generator embeds
the actual current renders and the saved Git originals, deduplicating unchanged
images. No ORCA runtime behavior was changed during this second sweep.

### Feedback and Touch review branch · 15 October 2026

The recent rendering improvements above are preserved on
`feature/assembly-feedback-touch`, starting with commit `d89768b`. The original
`feature/better_stat_logging` worktree's assembly guide was restored to `3985b50`;
its existing dependency development overrides were left untouched.

This review edition integrates the two newly supplied PDFs without replacing the
guide's design. It adds eleven Touch-only steps, instruction-local media and
commands, a single Parts box, collapsible desktop navigation, named thumb-to-carpal
routes, bearing-first top-spool assembly, and mold/skin references. Touch bench
flashing happens before connector-board installation and palm closure. Normal
Setup and hardware operations retain their existing implementations.

Read [the feedback analysis and implementation map](docs/assembly-feedback-review.md)
before editing. It records each concern, source discrepancies and verification.
Several mechanical facts are still unconfirmed: the reversed thumb AP channel
assignment, long Touch cable wrapping/allocation,
and discrepancies between fastener lists and CAD. These are explicitly visible
in the affected steps. Do not replace them with inferred dimensions.

The Structure / Content / Images review boxes are disabled by
`SHOW_ASSEMBLY_REVIEW_NOTES = false` in `ReviewChanges.tsx`. Assembly cautions
remain separate. Touch content lives in `touchGuide.ts`; the original guide IDs and explicit
completion behavior remain intact. The `oct15-v1` feedback marker resets only the
affected mechanical completion checks once.

The standalone comparison above records the earlier tendon-visibility sweep;
it is not a complete before/after report for this feedback edition. The new review
boxes and analysis document describe the additional changes, including the two
Touch bearing-image label corrections.

### 16 October walkthrough refinements

The viewer keeps a fixed 1:0.68 aspect ratio throughout the explosion slider.
Joint checks live under the later fitting/checking instruction, independently of
assembly animation playback. `JointInspection.tsx` owns these demonstrations;
connected-hand test limits are unchanged. `p59` has its own interactive TP routing
view. Palmar/dorsal selectors share colors and use an underline for selection.

White image surfaces are restored where no white material needs contrast;
`Figure.contrast` and the motion card's `data-contrast` select mint where needed.
Colored-tendon joint and routing windows, including AP and TP, use white; short
ancillary anchor tails do not make the entire routing window mint. Spooling views
with white cord and the sleeved wrist assembly retain mint.
Touch photographs stay photographs, with concise text and their critical dimensions.
The owner resolved thumb DP/PP pin sizes: Ø2×8 mm middle and Ø2×6 mm lower/upper,
as on the fingers. The earlier 5 mm warning is superseded.

`beltGuideGeometry.ts` adjusts only the displayed belt waist to pass between both
sleeved screws. Keep runtime scenes and regenerated stills consistent when changing
this geometry. The original archives are not modified. Added video cuts are listed
in `scripts/import_assembly_clips.py`; playback uses local native MP4 elements.
The earlier tutorial has no Touch installation or current board-flashing footage.

The standalone `orca-assembly-image-comparison.html` embeds original guide panels
and current renders for offline review. It also compares against revision `3985b50`.
It is a review artifact, not a UI dependency. See the feedback document for the
complete change map and remaining source uncertainties.

### 17 October: wrist routing, spools, Touch board link and navigation

The assembly-only refinement is implemented on `feature/assembly-feedback-touch`,
from baseline `59a6686`. It does not change hand control, motor limits, firmware,
configuration, or the Setup tensioning/calibration behavior.

- `AssemblyNavigation.tsx` replaces the flat chapter list with Prepare, Build the
  hand, Complete the hand and Optional groups. Its keyboard-accessible hand opens
  the relevant chapter and highlights the selected region. Chapter names use a
  consistent action structure; stored step IDs remain unchanged. Navigation
  never completes a step: completion still comes from its checklist.
- `assemblyTools.ts` explicitly lists tools for each step, including steps done
  by hand. The opening page collects the tools for the selected build and flashing
  method, with optional casting/arm equipment separate. Each subsequent step has
  a compact Parts / Tools strip. Consumables such as glue and copper wire remain
  with parts; cutters, drivers, marking tools and software equipment appear under
  tools. Driver bit sizes are not guessed where the supplied screw-head standard
  is unspecified.
- `WristRouting.tsx` shows the actual carpal underside and wrist entrance together.
  It sorts the 32 existing measured carpal outlets from screen-left to screen-right,
  interleaving the two rows while preserving their existing receiving-channel
  correspondence. Both views highlight the same tendon ID. Threading sequence
  numbers are separate from tendon IDs; do not conflate them. The selected sequence
  position is saved under `views['p77:route']`. Both cameras share screen-left =
  world +X, but look into opposing faces; keep those orientations together.
- `SpoolOverview.tsx` explains bottom = nearest the motor and top = farther out on
  the same shaft, with an exploded CAD slider, selectable groups and a three-stage
  sequence. The bottom/top instructions separate tying allowance, winding, tucked
  tail, bearing-first preparation and final paired movement check. FeeTech uses
  a labeled position diagram rather than a falsely identified Dynamixel motor.
- `touch-board-link` is a new, separately checked step after the five finger plugs
  and before sensor testing. `TouchBoardConnection.tsx` shows the actual four-pin
  sockets on the Touch and OH boards, with selectable close-ups and the cable
  linking them. The teal cable is a connection schematic, not a measured installed
  route or wire-color/pinout diagram. The text covers routing, wrist/cover slack
  and clearance. Existing completion of `touch-board-connect` does not complete
  this new operation.

The visual language stays warm off-white, charcoal text, muted teal controls,
compact monospace eyebrows and thin rounded borders. White diagram surfaces are
used where colored tendons or dark parts remain legible; mint contrast remains
for white cord, PTFE and pale skins. Touch anatomy and colored-tendon inspection
views use white. Short captions sit with images, and numbered actions keep their
media alongside the relevant instruction. No PDF/source link is added to the UI.

Image quality changes recover detail from the original PDFs, rather than enlarging
previously small PNG crops. `photoResolutionMap.json` resolves 166 original panel
paths to matching high-resolution WebPs after CAD substitution and source filtering.
SVG routing coordinates stay in their original coordinate system, with matching
crop aspect ratios. The map also applies in enlarged comparison/routing views.
Twenty-one Touch photographs use new WebPs, up to 2200 pixels on their longest edge.
Photos stay within both their native pixel size and the available display width.
The original PNGs remain available for authoring/comparison. Native source detail
still limits genuinely blurry photographs; these exports do not invent detail.
Four new carpal-cleanup renders show the openings being inspected instead of
suggesting an unconfirmed screw-based cleaning tool.

The Touch connection diagram uses a separate ~6.6 MiB board-detail GLB with 12
components from the current right Touch STEP, checked against the inventory's
source SHA-256. Its board/socket materials are separated for readability. This
small asset does not replace or modify the complete assembly archives. The same
physical boards are used as the socket-identification reference for either hand.

Rebuild the authoring assets from the repository root (paths are inputs, not
runtime dependencies):

```sh
python scripts/refine_assembly_panels.py '/path/Assembly Instructions.pdf' --dpi 600 --output-root /path/staging
python scripts/promote_assembly_photos.py /path/staging
python scripts/import_touch_photos.py '/path/Touch Assembly Instructions.pdf'
python scripts/build_touch_board_detail.py /path/TouchV2_Assembly_Right.step
```

The photo scripts require PyMuPDF and Pillow; the STEP exporter requires CadQuery
and trimesh plus the existing `cad_render_mesh.py` helper. These are authoring
requirements only; guide users do not need them. The existing illustration renderer
can regenerate only the new cleanup views by passing `panel-019-4` as its file
prefix. Run the production frontend build after changing assets or source.

See [the October 17 review record](docs/assembly-oct17-review.md) for validation
and unresolved mechanical requirements. A browser/data audit is not a physical
assembly validation. In particular, bottom/top tendon assignments and the corrected
thumb AP channel order still require authoritative confirmation before the guide
can be described as fully verified for a first-time builder.

The follow-up image pass adds `BoardIdentification.tsx`: an eight-item selectable
port map using the unmodified native-resolution OH-board photo. It defaults to
and labels the selected motor output, supports keyboard selection and enlargement,
and covers the board link, both motor types, both fan sockets, USB-C, 12 V, switch
and programming pads. The original PDF image is extracted with
`scripts/import_control_board_photo.py`; rotation and annotations are code-native
SVG, with no labels baked into the photo. This replaces the redundant incomplete
CAD thumbnail plus red-arrow photograph on `p101`.

**Important CAD limit:** the OH-board STEP component set omits the USB-C, power
jack, power switch and two fan connector bodies. Do not replace the complete port
identification photo with a render of that incomplete geometry. The three top
board/motor connectors are present and support the separate Touch cable diagram.
A complete electronic board model is needed before those remaining physical
features can be represented accurately in CAD renders.

`cadThumbFinishing.ts` now frames only the TP joint, pins and bearings. It no longer
uses the distant fingertip or free tendon ends to set the scale of these details;
measured paths stay unchanged, with clearer static tendon contrast. Regenerate
`panel-063-1` and `panel-063-2` for all four measured configurations after changing
this scene. The renderer uses `frameObjects` to fit the actual surfaces rather
than the projected corners of a large world-axis bounding box.
