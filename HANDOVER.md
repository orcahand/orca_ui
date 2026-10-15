# ORCA assembly guide — handover

Updated: 13 October 2026. Intended for the next Astra/Codex instance and human maintainers.

## Start here

The assembly guide is implemented in this checkout. Open **Setup → Open assembly guide**. It runs as a modal inside the existing application, on the same origin and port, and restores the builder's configuration, position and checklist progress.

The goal is a self-contained guide that makes building the hand straightforward without needing to consult the teaching PDF or ask for missing instructions. The current version is substantial and reviewable, but some mechanical specifications and procedures remain unresolved. Do not describe it as a physically validated, independently complete assembly manual yet.

Read this document first, then [the assembly implementation notes](frontend/src/components/assembly/README.md), [DEVELOPMENT.md](DEVELOPMENT.md) and [CLAUDE.md](CLAUDE.md). The assembly README contains detailed historical development notes; some early statements are superseded. In particular, its opening statement that the guide never starts a hand operation predates the explicitly enabled connected-hand test described below.

## Repository state at handover

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
| Illustration surface | Muted mint `#b8cebf` | Contrast for white tendons and PTFE |
| Illustration labels | Dark green `#24533f` | Readable, restrained annotations |
| Light-theme action accent | Teal `#0f6f78` | Navigation and interactive states |
| Headings/body | System sans-serif; large, tightly spaced headings | Clear reading hierarchy |
| Small metadata | Space Mono | Step numbers, compact labels and technical context |
| Panels | Thin borders, modest rounding, minimal shadow | Group content without visual clutter |

The user explicitly requested progressively darker illustration backgrounds so white tendons remain visible. The latest value is `--assembly-image-bg: #b8cebf` in `assembly.css`; do not revert to the earlier pale mint. Routing diagram masking strokes use the same variable. Some baked label backplates retain a lighter mint, which helps separate their text from the illustration.

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
Several mechanical facts are still unconfirmed: thumb pin diameter/position,
the reversed thumb AP channel assignment, long Touch cable wrapping/allocation,
and discrepancies between fastener lists and CAD. These are explicitly visible
in the affected steps. Do not replace them with inferred dimensions.

Every step includes a removable Structure / Content / Images review box. Users can
toggle them in the header. Maintainers can set `SHOW_ASSEMBLY_REVIEW_NOTES = false`
in `ReviewChanges.tsx` to remove the entire review layer. Assembly cautions remain
separate. Touch content lives in `touchGuide.ts`; the original guide IDs and explicit
completion behavior remain intact. The `oct15-v1` feedback marker resets only the
affected mechanical completion checks once.

The standalone comparison above records the earlier tendon-visibility sweep;
it is not a complete before/after report for this feedback edition. The new review
boxes and analysis document describe the additional changes, including the two
Touch bearing-image label corrections.
