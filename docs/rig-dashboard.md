# Calibration rig on the dashboard (plan, 2026-11-08)

Clemens's request: orca-ui finds the calibration rig (turntable) on its own and the
dashboard shows the rig and the hand together, with plate controls and the camera.

## 1. Rig auto-detect

Backend `orca_ui/hand/rig_detect.py`, watcher thread in `api/visual_calibration.py`.

A board is the **rig** when any of these holds (in order):
1. its USB serial is a known rig serial: `turntable.yaml` `board.usb_serial`,
   `turntable_calibration.yaml` `board.usb_serial`, built-in `FC9578875154393741202020FF012940…`;
2. its ORCA identity carries a rig flag: config code `RIG`, or serial `rig-…`;
3. a bus scan (only on a free, non-hand board) finds exactly one motor of a known
   rig model (XC430-T240BB-T, XC430-W240-T, XC330-T288-T, read from the control table).

A board with 2+ motors, the pinned hand board, any port of the hand session, and any
port sharing the hand board's USB serial is **never** a rig candidate. A rig board is
**never** a hand: `select_board` refuses it (409), the board menu labels it `rig`, and
unpinned hand detection drops a detection that landed on a rig port.

Today's rig board answers `ORCA_ID?` with hand serial `ser-3526` (stale). Rule 1 wins
over the identity, and presence reports `identity_claim: ser-3526` with a warning.
Proposal (not done): write a rig identity to the board (config code `RIG`, serial
`rig-<n>`) with the board provisioning tool, after which rule 2 covers new rigs
without a serial list.

Motor: the model read at the scan is reported; a config `motor.model` that differs
(not `auto`) is a warning, not an error. XC330-T288-T: same operating mode 4, PWM
cap, `gear_ratio: 1.0` (+1) in its `turntable.yaml`.

Connect: the watcher opens the rig read-only (torque off) when it appears, polls
nothing else; `GET /api/visual-calibration/rig/presence` returns the cached state.
Off with `ORCA_RIG_AUTODETECT=0`; under `--mock` only with `ORCA_MOCK_RIG=1`.

## 2. Rig dashboard

When presence says `connected`, the dashboard's 3D view switches to the rig scene:
- the twin (orca_files `calibration_rig/twin/`: base, plate, tower, camera mast;
  groups static / rotor / object / camera from `twin.json`);
- the tower's ChArUco tiles as textures (`/twin/tiles/<tile>.png`, rendered from the
  rig config with their letters);
- the hand on the plate at the found mounting (`overlay.hand_in_plate`, served as
  `plate_from_hand` and `hand_in_rig` in `/twin/state`);
- the live plate angle (`/twin/state`, 5 Hz) turns plate, tower and hand.
- the tower is off by default (tick "tower"): the hand sits on the same connector rods
  (`reference.hand_mount`), so with the hand mounted the tower is not on the plate.

Rig controls panel: plate angle readout, go to angle, park/swap (`swap_angle`),
home, torque off. The backend keeps the safety rules: the configured slow speed,
torque off after every stop (`hold_after_move: false`), E-STOP drops the plate too,
and the hand and the plate never move together: a plate move is refused while the
hand's joint targets changed in the last 0.5 s, and joint targets are refused (409)
while the plate turns.

## 3. Cameras on the dashboard

Tick "camera": every enabled rig camera's live stream side by side (getUserMedia at 4K,
the visual-calibration page's device choice and turn per camera: cam A 270°, cam B 90°;
a camera with `enabled: false` in config.yaml is not shown). Tick "overlay": the hand
(live pose, study-corrected when the study map is on) and the tower tiles from
`/overlay?cam=<c>`, each camera from its own solved (or CAD) pose, using `HandOverlay` and
the tile drawing of the visual-calibration page. Both off by default. Placed under the 3D
view; click a camera to enlarge it, Esc to close. Do not tick it while a runner holds the
cameras. The twin marks each enabled camera with a frustum: green at its solved pose
(`/twin/state` `cameras.<c>.solved`), amber at its CAD pose until 1b has solved it.

### Which browser device is which camera

The two BRIOs report the same label, and neither the browser's nor OpenCV's device order is
identity; the USB serial in config.yaml (`cameras.<c>.uvc.device.serial`) is. Each stream
(`useRigCameras`) is checked once it plays: the page posts a downscaled frame to
`POST /camera/identify`, which takes a still of every enabled camera by its serial
(`uvc.camera_index` + the process's one `SharedCamera` per camera, let go after 60 s
unused) and compares them at 64×36 (normalised correlation; a match needs ≥ 0.8 and a
0.15 lead). A stream that shows the other camera swaps the two device assignments; one it
cannot place is marked unknown, and the calibration page stores no photo from it. Every
photo is posted with `verify=true`, so the server compares it with a fresh still of that
camera again before storing it (`stop_<deg>` for cam A, `stop_<deg>_b` for cam B).
`GET /camera/still?cam=<c>` serves such a still as JPEG. Under `--mock` nothing is checked.
The serials themselves come from the visual-calibration page's 0 · Setup step
([rig-setup.md](rig-setup.md)), which also shows a banner here when a camera runs on USB 2.

## 4. Going live

Built and tested without restarting orca-ui. After the overnight study:
torque off, restart orca-ui with the hand board pinned (`--board /dev/cu.usbmodem1101`),
check the board menu labels the rig board `rig`, the dashboard shows the rig.
