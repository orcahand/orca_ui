# Visual calibration · 0 · Setup

The first step of Setup › Visual calibration (`frontend/src/components/visual/RigSetup.tsx`),
before 1 · Rig. It runs, in order, what a newly built rig needs once — or again after a camera,
cable or motor was swapped. Each card shows its status (ok, warn, error, not run), what it
found and the fix. Every card can run again safely: it measures afresh and overwrites its own
results. A rig set up before shows green from what its `local.yaml` already holds.

The logic is the experiment's `visual_calibration/setup.py` (orca_core
`experiments/visual_calibration/`, the same functions as `python -m visual_calibration.setup`);
`orca_ui/api/rig_setup.py` serves it under `/api/visual-calibration/setup/…`. Everything it
finds goes to the rig's gitignored `local.yaml` (`RigConfig.save_local`, laid over
`config.yaml` on every load), never to `config.yaml`; the results go under `setup:` there, so
the page shows them after a reload.

| # | Card | Endpoint | What it does |
|---|------|----------|--------------|
| | summary | `GET /setup` | every item's last result, the live USB check, running jobs; all green = ready for 1 · Rig, else the blockers |
| 1 | USB | `GET /setup/usb` (cached, opens nothing) · `POST` (fresh) | `cameras_on_usb` + `usb_warnings`: serial, mount, link speed, OpenCV index. USB 2 is an error with the cable fix |
| 2 | Turntable | `POST /setup/turntable` | the rig board (found as on the dashboard, never the hand's ports), connected read-only; `turntable_status`: is `turntable_calibration.yaml` this board's and motor's. If not: **Calibrate motor** (`POST /turntable/calibrate`: three times into the hard stop, then the travel) |
| 3 | Identify cameras | `POST /setup/identify` · `POST /setup/identify/save` | the tower on the plate (parked at `sweep.REFERENCE_STOP` when the motor is calibrated); a still of every BRIO by serial, `single_view_pose`, `identify`. Saved at once only when confident and no serial was set; else shown (images, distance/height/tilt against the mounts) to confirm, swap, or choose between the old and the new |
| 4 | Align cameras | `GET /setup/align?cam=` (every 2 s) · `POST /setup/align/check?cam=&locked=true` · `POST /setup/mount` | live view with the CAD ghost (`/overlay?source=cad`: the nominal mount pose and lens, even when calibrated) and the tiles found; `placement` advice; "keep it here" writes the mount hole to `local.yaml`; when in tolerance: **Lock it now**, then **Check again after locking** — green only after a passing check once locked |
| 5 | Exposure | `POST /setup/exposure?cam=` (job) | `uvc.ensure` first, then `setup.tune_exposure` (whole flicker periods); saved, then locked with `ensure` |
| 6 | Focus | `POST /setup/focus?cam=` (job) | after exposure: `setup.focus_coarse_fine` (every 8, then every 2); the curve of worst/mean per focus; saved and locked |
| 7 | Tile tour | `POST /setup/tour` (job) | `setup.tour` over 8 stops, 45° apart: the letters each camera saw; every tile seen by some camera passes |

**Light up** (USB and Identify cards, `POST /setup/light?cam=` or `?serial=`, `seconds` up to 30):
the server streams that camera by serial so its white LED shows which BRIO it is, then lets it
go, unless something else uses that capture meanwhile (the idle reaper closes it later then).

Jobs run on their own thread, one at a time (`GET /setup/jobs/<id>`: state, progress, note,
result; `POST /setup/jobs/<id>/cancel`). The page follows a running job across a reload.

## Safety

- The tour moves the plate only through the turntable's own move (its lock, the configured slow
  speed), with `hold=False`: the torque is off after every stop, and off when the tour ends or fails.
- The plate waits for the hand: each move checks the hand's motion blocker and marks the plate as
  moving, so joint targets wait (the same rules as everywhere on the page).
- E-STOP (`release_turntable`) first stops every running setup job, then drops the torque, so no
  next stop turns it back on.
- The browser never sets focus or exposure: "Lock focus & exposure" on the camera step runs
  `uvc.ensure` on the server with the values in `config.yaml` + `local.yaml`.

## USB 2

A BRIO on a USB 2 link sends 1080p at most. The backend's stills by serial (`serial_still`)
then capture at 1920×1080, so setup still works; 1a, 1b, the sweeps and the hand captures need
the config resolution and refuse photos of another size. A banner on every step of the page
and on the dashboard camera says so, from `GET /setup/usb` polled every 5 s (cached `ioreg` and
`system_profiler` listings: no camera is opened).
