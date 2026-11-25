# Rig hand measurement: handover

The handover for testing the rig's hand measurement (setup, what changed, the test, what to report)
lives with the rig code: `experiments/visual_calibration/HANDOVER.md` in orca_core, branch
`internal/rig-calibration`.

The console must run on that orca_core with its `rig` extra installed (OpenCV, torch, transformers
and the rest the rig needs). `./dev local <orca_core checkout>` alone is not enough: it brings
orca_core's own dependencies, not its extras. orca_core's `experiments/visual_calibration/` has the
scripts for it:

- `setup_rig.sh`: sets this computer up for the rig.
- `rig-console.sh`: starts the console on that orca_core.

Setup › Visual calibration opens with "Check this computer" (orca_core's rig doctor). A dependency
the console's Python lacks is named at the top of the page, with its fix.
