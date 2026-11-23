"""Visual calibration: the turntable motor, sessions of photos of the turning
rig, tile detection, and the solves (1a camera, 1b rotation).

The code is orca_core's self-contained experiment
``experiments/visual_calibration/`` (its README), not the orca_core package: it
is put on sys.path from $ORCA_VISUAL_CALIBRATION, else ``../orca_core/experiments/visual_calibration``.

The backend owns the rig's cameras (visual_calibration.rig_cameras: every enabled
camera opened once, told apart by serial, its controls locked): a sweep's photos are
its own stills from every camera (``/sessions/{id}/capture``), the page only shows a
preview (``/cameras/{cam}/preview.jpg``), and the hand run takes its stills from
``/cameras/stills``. Nothing is captured before ``/cameras/preflight`` passed. The assemblers'
"Measure joint ranges" starts that run for the connected hand as a child process
(``/hand-run``, orca_ui.hand.hand_run); ``/board-write`` says whether this computer can then
write the hand's board (the ``board_write`` operation).
Sessions live in the rig's folder, ``<ORCA_HOME>/rigs/<rig id>/sessions/<id>/``,
beside its calibrations (visual_calibration.session, visual_calibration.rig_home); the rig id
comes from the board the watcher found, else from the USB serial turntable.yaml pins. The
plate is turned by the rig's Dynamixel (visual_calibration.turntable; the mock one under
--mock); the page drives the sweep: move, then ask for the photos.
CPU-bound handlers are plain ``def`` so FastAPI runs them off the event loop.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import threading
import time
from functools import lru_cache
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from orca_ui import research


class NewSession(BaseModel):
    step: Literal["camera", "rotation", "hand"] = "camera"
    hand_turned: bool = False                      # True: the plate was turned by hand to the stops


class Connect(BaseModel):
    port: str | None = None
    motor_id: int | None = None
    torque: bool = False                           # False: read the angle only, the plate stays free


class Move(BaseModel):
    angle: float
    hold: bool = False                             # a sweep's stop: the torque stays on (for HOLD_LEASE_S)


class Home(BaseModel):
    hold: bool = False


class Preflight(BaseModel):
    tiles: bool = True                             # the tower is on the plate: each camera's height from its tiles too
    write: bool = True                             # False: check the controls, never set them


class MeasureStart(BaseModel):
    dry: bool = False                              # build the hand run and list its steps; nothing moves
    limit: int | None = None                       # poses per block: a short trial


class StudyMapSwitch(BaseModel):
    enabled: bool | None = None
    mode: str | None = None                        # "off" or a map of the connected hand


class LutCommand(BaseModel):
    angles: dict[str, float]                       # the true joint angles wanted (deg)
    use_lut: bool = True                           # False: send them as they are (orca_core's linear map)


logger = logging.getLogger(__name__)
RESEARCH = [Depends(research.require)]     # the study's research extras: 404 without --research-ui
HOLD_LEASE_S = 20.0    # a held plate (a sweep between stops) drops the torque this long after its last move
RIG_POLL_S = 3.0       # the rig watcher's period (lists ports; probes a new board once)
RIG_PAUSE_S = 8.0      # after an explicit release the watcher leaves the board alone this long


EXPERIMENT = Path(os.environ.get("ORCA_VISUAL_CALIBRATION")
                  or Path(__file__).resolve().parents[3] / "orca_core" / "experiments" / "visual_calibration")


def _experiment_on_path() -> None:
    if str(EXPERIMENT) not in sys.path:
        sys.path.insert(0, str(EXPERIMENT))


_rig_yaml_cache: dict = {}


def rig_yaml() -> list[dict]:
    """The rig's turntable.yaml section and its motor calibration (cached 30 s): the rig board's pins."""
    now = time.monotonic()
    if now - _rig_yaml_cache.get("t", -1e9) > 30.0:
        _experiment_on_path()
        from orca_core.utils.utils import read_yaml
        from visual_calibration.rig_config import RigConfig
        r = RigConfig.load()
        _rig_yaml_cache.update(t=now, v=[r.raw["turntable"], read_yaml(r.turntable_calibration_path) or {}])
    return _rig_yaml_cache["v"]


def _plain(x):
    import numpy as np
    if isinstance(x, dict):
        return {str(k): _plain(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_plain(v) for v in x]
    return x.item() if isinstance(x, np.generic) else x


def _detections(dets) -> list[dict]:
    return [{"tile": d.tile, "ids": d.ids.tolist(), "uv": d.uv.round(2).tolist(), "markers": d.markers} for d in dets]


def _orientation(obj, dets) -> dict | None:
    """Which clockwise display turn puts the tower up (visual_calibration.detect.display_rotation)."""
    from visual_calibration.detect import display_rotation
    return display_rotation(obj, dets)


class StudyNote(BaseModel):
    text: str
    who: str = "agent"


def build_router(base: Path | None = None, mock: bool = False, cameras=None) -> APIRouter:
    """`base`: the sessions folder (tests); by default the rig's own. `cameras`: the rig's
    camera service (default: a RigCameras of the rig config, made on first use)."""
    router = APIRouter(prefix="/api/visual-calibration", tags=["visual-calibration"])
    lock = threading.Lock()                        # one solve / photo write at a time
    table: dict = {}                               # "t": the open Turntable, "hold_until": the hold's lease

    def release_turntable(close: bool = False) -> bool:
        """Torque off (E-STOP, shutdown, a dropped hold); close: also let go of the board."""
        t = table.get("t")
        if t is None:
            return False
        try:
            if close:
                table.pop("t", None)
                t.close()
            else:
                t.release()
        except Exception:
            return False
        return True

    def watchdog() -> None:
        """The torque is on only while the plate turns, or while a sweep holds it between stops and
        keeps moving: a page that stops sending (closed, crashed, offline) drops it."""
        while True:
            time.sleep(1.0)
            t = table.get("t")
            if t is None or not t.torque or t.lock.locked():
                continue
            if time.monotonic() > table.get("hold_until", 0.0) and t.lock.acquire(blocking=False):
                try:
                    if t.torque:
                        t.release()
                finally:
                    t.lock.release()

    router.release_turntable = release_turntable

    # The rig on the dashboard (docs/rig-dashboard.md): found by the watcher, never the hand's board.
    hand = {"ports": lambda: set(), "blocker": lambda: None, "service": None}
    presence: dict = {"present": False, "connected": False, "port": None, "usb_serial": None, "reason": "",
                      "model": None, "identity_claim": None, "warnings": [], "autodetect": False}
    probed: set = set()                            # (device, usb serial) whose identity was asked: once per plug-in
    connect_lock = threading.Lock()

    def attach_hand(ports, blocker) -> None:
        """ports(): every device path of the hand; blocker(): why the plate may not turn now."""
        hand["ports"], hand["blocker"] = ports, blocker

    def plate_motion_guard() -> str | None:
        t = table.get("t")
        return "the rig's plate is turning: the hand waits until it stops" if t is not None and table.get("moving") else None

    router.attach_hand = attach_hand
    router.plate_motion_guard = plate_motion_guard

    def find_rig() -> dict | None:
        """The rig's board: a known USB serial first, else a free non-hand board whose identity
        carries the rig flag (each board asked once per plug-in). Its motors are never scanned."""
        import serial.tools.list_ports
        from orca_core.constants import KNOWN_VIDS
        from orca_core.hardware.sensing.serial_discovery import port_in_use, probe_orca_info
        from orca_ui.hand.rig_detect import classify, hand_ports, rig_serials
        known = rig_serials(*rig_yaml())
        mine = hand_ports(hand["ports"](), None)
        ports = [p for p in sorted(serial.tools.list_ports.comports(), key=lambda p: p.device) if p.device not in mine]
        rig = [p for p in ports if p.serial_number in known]
        if rig:
            # Both CDCs of the board share the serial: the motor one is the port (else the turntable picks).
            infos = {p.device: None if port_in_use(p.device) else probe_orca_info(p.device) for p in rig}
            motor_cdc = [d for d, i in infos.items() if i is not None and i.role == "motor"]
            info = next((i for i in infos.values() if i is not None), None)
            v = classify(rig[0].serial_number, info, serials=known)
            return {"port": motor_cdc[0] if len(motor_cdc) == 1 else (rig[0].device if len(rig) == 1 else None),
                    "usb_serial": rig[0].serial_number, "reason": v.reason,
                    "identity_claim": getattr(info, "serial", None), "warnings": v.warnings}
        mine_serials = {p.serial_number for p in serial.tools.list_ports.comports() if p.device in mine}
        for p in ports:
            key = (p.device, p.serial_number)
            if key in probed or p.serial_number in mine_serials or p.vid not in KNOWN_VIDS["oh_board"] \
                    or port_in_use(p.device):
                continue
            probed.add(key)
            info = probe_orca_info(p.device)
            if info is None or info.role != "motor":
                continue
            v = classify(p.serial_number, info, serials=known)
            if v.rig:
                return {"port": p.device, "usb_serial": p.serial_number, "reason": v.reason,
                        "identity_claim": getattr(info, "serial", None), "warnings": v.warnings}
        return None

    def connect_rig(found: dict | None) -> None:
        """Open the rig read-only (torque off): the plate angle for the dashboard."""
        from orca_ui.hand.rig_detect import check_model
        _experiment_on_path()
        from visual_calibration.rig_config import RigConfigError
        from visual_calibration.turntable import Turntable, TurntableError
        with connect_lock:
            if "t" not in table:
                if found:
                    note_rig(found.get("usb_serial"), found.get("identity_claim"))
                r = rig_config()
                try:
                    table["t"] = Turntable.open(r.raw["turntable"], mock=mock, port=(found or {}).get("port"),
                                                torque=False, **turntable_files(r))
                except (TurntableError, OSError, RigConfigError) as e:
                    presence.update(present=found is not None, connected=False, warnings=[f"turntable: {e}"])
                    return
            t = table["t"]
            model = getattr(t.bus, "model", None) if t.bus else ("mock" if mock else None)
            configured = (rig_config().raw["turntable"].get("motor") or {}).get("model")
            presence.update(present=True, connected=True, port=getattr(t.client, "port_name", None),
                            usb_serial=getattr(t.bus, "usb_serial", None), model=model,
                            reason=(found or {}).get("reason") or ("mock turntable" if mock else "connected"),
                            identity_claim=(found or {}).get("identity_claim"),
                            warnings=[*(found or {}).get("warnings", []), *([] if mock else check_model(model, configured))])

    def rig_tick() -> None:
        if "t" in table:
            port = getattr(table["t"].client, "port_name", None)
            if not mock and port and not os.path.exists(port) and not table["t"].lock.locked():
                release_turntable(close=True)          # unplugged: let go, look again
                presence.update(present=False, connected=False, port=None, warnings=["the rig board was unplugged"])
                return
            presence.update(present=True, connected=True)
            return
        if time.monotonic() < table.get("rig_pause_until", 0.0):
            return
        presence.update(connected=False, port=None)
        if mock:
            connect_rig(None)
            return
        found = find_rig()
        presence.update(present=found is not None)
        if found is not None:
            connect_rig(found)

    def rig_watcher() -> None:
        while not table.get("stop_watcher"):
            try:
                rig_tick()
            except Exception as e:                 # never dies: a flaky port must not end the watch
                presence["warnings"] = [f"rig watcher: {e}"]
            time.sleep(RIG_POLL_S)

    def start_rig_watcher() -> bool:
        """From the app's lifespan: off with ORCA_RIG_AUTODETECT=0, under --mock only with ORCA_MOCK_RIG=1."""
        on = os.environ.get("ORCA_RIG_AUTODETECT", "1") != "0" and (not mock or os.environ.get("ORCA_MOCK_RIG") == "1")
        presence["autodetect"] = on
        if on and "rig_watcher" not in table:
            table["rig_watcher"] = threading.Thread(target=rig_watcher, daemon=True, name="rig-watcher")
            table["rig_watcher"].start()
        return on

    router.start_rig_watcher = start_rig_watcher
    router.stop_rig_watcher = lambda: table.__setitem__("stop_watcher", True)

    def note_rig(usb_serial: str | None, identity: str | None) -> None:
        """The connected rig's id (visual_calibration.rig_home): its files are that rig's."""
        from visual_calibration import rig_home
        try:
            table["rig_id"] = rig_home.remember(usb_serial, identity) if usb_serial else None
        except rig_home.RigIdError:
            table["rig_id"] = None

    def rig_config():
        """The rig's config, its own files those of the rig connected (else of the board turntable.yaml pins)."""
        _experiment_on_path()
        from visual_calibration.rig_config import RigConfig
        return RigConfig.load(rig_id=table.get("rig_id"))

    def sessions_dir() -> Path:
        if base is not None:
            return base
        _experiment_on_path()
        from visual_calibration.rig_config import RigConfigError
        try:
            return Path(rig_config().own_file("sessions"))
        except RigConfigError as e:
            raise HTTPException(409, str(e)) from e

    def turntable_files(r) -> dict:
        """Where the turntable reads its motor calibration and saves a new one: the rig's folder,
        never the checkout (RigConfigError when the rig has no id)."""
        from visual_calibration.rig_config import TURNTABLE_CALIBRATION_FILE
        return {"calibration_path": r.turntable_calibration_path,
                "save_path": r.own_file(TURNTABLE_CALIBRATION_FILE)}

    def turntable():
        if "t" not in table:
            raise HTTPException(409, "connect the turntable first")
        return table["t"]

    def motor(fn, moves: bool = True):
        """moves: the plate turns, so the hand must be still (and stays still: joint targets wait)."""
        _experiment_on_path()
        from visual_calibration.turntable import TurntableError
        t = turntable()
        if t.lock.locked():
            raise HTTPException(409, "the turntable is busy")
        if moves and (reason := hand["blocker"]()):
            raise HTTPException(409, reason)
        table["moving"] = moves
        try:
            return fn(t).as_dict()
        except TurntableError as e:
            raise HTTPException(409, str(e)) from e
        finally:
            table["moving"] = False

    def vc():
        _experiment_on_path()
        try:
            from visual_calibration import session
            from visual_calibration.detect import read_image
        except ImportError as e:
            raise HTTPException(503, f"visual calibration experiment not found at {EXPERIMENT} ({e})") from e
        return session, read_image

    @lru_cache(maxsize=1)
    def preview_detector():
        _experiment_on_path()
        from visual_calibration.calibration_object import CalibrationObject
        from visual_calibration.detect import TileDetector
        from visual_calibration.rig_config import RigConfig
        return TileDetector(CalibrationObject.from_config(RigConfig.load().raw["calibration_object"]))

    def open_session(sid: str):
        session, _ = vc()
        root = sessions_dir() / sid
        if "/" in sid or ".." in sid or not (root / "session.yaml").is_file():
            raise HTTPException(404, f"no session {sid}")
        return session.Session(root)

    @router.get("/rig")
    def rig() -> dict:
        vc()
        from visual_calibration.mounting import config_mountings, coverage
        r = rig_config()
        obj = r.raw["calibration_object"]
        found = r.load_calibration().get("mounting")
        cover = coverage(preview_detector().obj, r.stops.angles, config_mountings(obj))
        return {"rig": r.name, "version": r.version, "stops": r.stops.angles, "travel": r.travel,
                "side0_stop": (found or {}).get("side0_stop", obj.get("side0_stop")), "mounting": found,
                "mountings": config_mountings(obj), "coverage_warnings": cover["warnings"],
                "tiles": sorted(preview_detector().obj.tiles),
                "reference_tile": obj.get("reference_tile"), "camera_mount": r.raw["camera"].get("mount"),
                "cameras": r.active_cameras,
                "letters": obj.get("letters") or {},
                "swap_angle": float(r.raw["turntable"].get("swap_angle", 180.0)),
                "rig_board": rig_board(r),
                "mock_turntable": mock}

    def rig_board(r) -> dict:
        """The turntable's board: its pinned USB serial and the ports it has now (never the hand's)."""
        serial_no = (r.raw["turntable"].get("board") or {}).get("usb_serial")
        if not serial_no:
            from orca_core.utils.utils import read_yaml
            serial_no = ((read_yaml(r.turntable_calibration_path) or {}).get("board") or {}).get("usb_serial")
        devices = []
        if serial_no and not mock:
            import serial.tools.list_ports
            devices = sorted(p.device for p in serial.tools.list_ports.comports() if p.serial_number == serial_no)
        return {"usb_serial": serial_no, "devices": devices}

    camera_service = {"cameras": cameras}

    def rig_cameras():
        """The rig's cameras, made on first use and kept for the app's life; each preflight rereads the config."""
        _experiment_on_path()
        if camera_service["cameras"] is None:
            from visual_calibration.rig_cameras import RigCameras
            camera_service["cameras"] = RigCameras(rig_config, mock=mock)
        return camera_service["cameras"]

    def close_cameras() -> None:
        if camera_service["cameras"] is not None:
            camera_service["cameras"].close()

    router.close_cameras = close_cameras

    def camera_call(fn):
        """fn(the camera service). An unknown camera: 404; a camera missing, unidentified or not
        checked, uvcc or the device listing failing: 409; a key missing in config.yaml: 409 saying so."""
        import subprocess
        cams = rig_cameras()
        from visual_calibration.rig_cameras import UnknownCamera
        from visual_calibration.uvc import CameraSettingsError
        try:
            return fn(cams)
        except UnknownCamera as e:
            raise HTTPException(404, f"no camera {e}") from e
        except KeyError as e:
            raise HTTPException(409, f"rig config.yaml: missing {e} in a camera's block") from e
        except (CameraSettingsError, RuntimeError, OSError, subprocess.SubprocessError, ValueError) as e:
            raise HTTPException(409, str(e)) from e

    def image_response(img, fmt: str, quality: int) -> Response:
        from visual_calibration.rig_cameras import encode
        return Response(encode(img, fmt, quality), media_type="image/png" if fmt == "png" else "image/jpeg",
                        headers={"Cache-Control": "no-store"})

    def uvc_state(write: bool) -> dict:
        """Every camera's UVC controls against config.yaml cameras.<c>.uvc (visual_calibration.uvc)."""
        r = camera_call(lambda c: c.lock_controls(write))
        if not r:
            return {"ok": True, "configured": False}
        a = r.get("a") or next(iter(r.values()))
        return {"ok": True, "configured": True, "set": a["set"], "controls": a["after"],
                "cameras": {c: {"set": v["set"], "controls": v["after"]} for c, v in r.items()}}

    @router.get("/camera/uvc")
    def camera_uvc() -> dict:
        """Read only: 409 when a control differs from the config."""
        return {"ok": True} if mock else uvc_state(write=False)

    @router.post("/camera/uvc")
    def camera_uvc_set() -> dict:
        """Set the controls that differ, read them back; 409 if they still differ (before a sweep)."""
        return {"ok": True} if mock else uvc_state(write=True)

    @router.get("/cameras")
    def cameras_state() -> dict:
        """The enabled cameras, their indices and whether a preflight passed (opens nothing)."""
        return _plain(rig_cameras().status())

    @router.post("/cameras/preflight")
    def cameras_preflight(body: Preflight | None = None) -> dict:
        """Open every camera, lock its controls and prove which stream is which (409 if not)."""
        body = body or Preflight()
        detector = preview_detector() if body.tiles else None
        return _plain(camera_call(lambda c: c.preflight(detector, write=body.write)))

    @router.get("/cameras/{cam}/preview.jpg")
    def camera_preview(cam: str, max_side: int = Query(1600, ge=160, le=3840)) -> Response:
        """The newest frame, scaled down: the page's live view (no preflight needed)."""
        return image_response(camera_call(lambda c: c.preview(cam, max_side)), "jpg", 80)

    @router.get("/cameras/stills")
    def camera_stills(format: Literal["png", "jpg"] = "jpg", quality: int = Query(95, ge=50, le=100)) -> dict:
        """Every camera's full-resolution frame, all captured after this request: {camera: base64}
        (409 before a preflight). The hand run's photos of a stop."""
        import base64
        from visual_calibration.rig_cameras import encode
        frames = camera_call(lambda c: c.stills(after=time.monotonic()))
        return {"format": format, "cameras": {c: base64.b64encode(encode(img, format, quality)).decode()
                                              for c, img in frames.items()}}

    @router.get("/cameras/{cam}/still")
    def camera_still(cam: str, format: Literal["png", "jpg"] = "png", quality: int = Query(95, ge=50, le=100)) -> Response:
        """A full-resolution frame captured after this request (409 before a preflight)."""
        return image_response(camera_call(lambda c: c.still(cam, after=time.monotonic())), format, quality)

    @router.get("/turntable")
    def turntable_state() -> dict:
        if "t" not in table:
            return {"connected": False, "mock": mock, "homed": False, "angle": None, "busy": False,
                    "port": None, "motor_id": None, "calibrated": False, "zero_from": None, "torque": False}
        return table["t"].state().as_dict()

    @router.post("/turntable/connect")
    def turntable_connect(body: Connect) -> dict:
        vc()
        from visual_calibration.rig_config import RigConfigError
        from visual_calibration.turntable import Turntable, TurntableError
        if "t" in table:
            return table["t"].state().as_dict()
        try:
            r = rig_config()
            table["t"] = Turntable.open(r.raw["turntable"], mock=mock, port=body.port, motor_id=body.motor_id,
                                        torque=body.torque, **turntable_files(r))
        except (TurntableError, OSError, RigConfigError) as e:
            raise HTTPException(409, f"turntable: {e}") from e
        note_rig(getattr(table["t"].bus, "usb_serial", None), None)
        return table["t"].state().as_dict()

    def lease(hold: bool) -> None:
        table["hold_until"] = time.monotonic() + HOLD_LEASE_S if hold else 0.0
        if hold and "watchdog" not in table:
            table["watchdog"] = threading.Thread(target=watchdog, daemon=True, name="turntable-hold")
            table["watchdog"].start()

    @router.post("/turntable/home")
    def turntable_home(body: Home | None = None) -> dict:
        hold = bool(body and body.hold)
        lease(hold)
        return motor(lambda t: t.home(hold=hold))

    @router.post("/turntable/move")
    def turntable_move(body: Move) -> dict:
        settle = rig_config().stops.settle_s
        lease(body.hold)
        return motor(lambda t: t.move(body.angle, settle, hold=body.hold))

    @router.post("/turntable/calibrate")
    def turntable_calibrate() -> dict:
        """The motor calibration: hard stop, travel, every stop's motor position
        (turntable_calibration.yaml; not saved for the mock motor)."""
        result: dict = {}
        def run(t):
            result.update(t.calibrate(save=not t.mock))
            return t.state()
        return {**motor(run), "calibration": result}

    @router.post("/turntable/torque-off")
    def turntable_torque_off() -> dict:
        """Torque off, still connected: the plate turns by hand and its angle is still read."""
        def off(t):
            t.release()
            return t.state()
        table["hold_until"] = 0.0
        if "t" in table and table["t"].lock.locked():
            return table["t"].state().as_dict()        # a move is running: it ends with the torque off
        return motor(off, moves=False)

    @router.post("/turntable/park")
    def turntable_park() -> dict:
        """To the swap angle (object <-> hand), torque off after."""
        swap = float(rig_config().raw["turntable"].get("swap_angle", 180.0))
        lease(False)
        return motor(lambda t: t.move(swap, 0.0, hold=False))

    @router.get("/rig/presence")
    def rig_presence() -> dict:
        """The rig as the watcher found it (cached, no bus access) and the turntable's state."""
        return {**presence, "turntable": turntable_state(), "hand_blocker": hand["blocker"]()}

    @router.post("/rig/scan")
    def rig_scan() -> dict:
        """Look for the rig now, asking every free board's identity again (never the hand's ports)."""
        probed.clear()
        table["rig_pause_until"] = 0.0
        rig_tick()
        return rig_presence()

    @router.post("/turntable/release")
    def turntable_release() -> dict:
        table["rig_pause_until"] = time.monotonic() + RIG_PAUSE_S
        t = table.pop("t", None)
        if t is not None:
            t.close()
        return turntable_state()

    @router.get("/overlay")
    def model_overlay(angle: float | None = Query(None, ge=-360, le=360), rotation: float = Query(270.0),
                      camera: str = Query("a")) -> dict:
        """What the rig model expects `camera` to see at a plate angle (default: the turntable's),
        tiles projected into the raw image + the transforms for drawing the hand."""
        vc()
        from visual_calibration.overlay import overlay
        r = rig_config()
        if camera not in r.cameras:
            raise HTTPException(404, f"no camera {camera}")
        if angle is None:
            t = table.get("t")
            angle = t.angle() if t is not None and t.zero is not None else 0.0
        return overlay(r, float(angle), rotation, camera)

    @router.get("/status")
    def status() -> dict:
        """Per step (motor calibration, 1a, 1b, 2): status, time, key numbers, structured warnings."""
        vc()
        from visual_calibration.status import calibration_status
        return {**calibration_status(rig_config(), sessions_dir()), "turntable": turntable_state()}

    @router.get("/twin")
    def twin() -> dict:
        """Shea's twin.json (orca_files calibration_rig/twin/), meshes under /twin/files/<name>."""
        vc()
        from visual_calibration.twin import twin_dir, twin_info
        info = twin_info()
        if info is None:
            raise HTTPException(404, f"no twin at {twin_dir()}")
        return {**info, "files": sorted(p.name for p in twin_dir().glob("*.glb"))}

    @router.get("/twin/files/{name}")
    def twin_file(name: str):
        vc()
        from visual_calibration.twin import twin_dir
        path = twin_dir() / name
        if "/" in name or ".." in name or path.suffix not in (".glb", ".json") or not path.is_file():
            raise HTTPException(404, f"no twin file {name}")
        return FileResponse(path, media_type="model/gltf-binary" if path.suffix == ".glb" else "application/json")

    @router.get("/twin/state")
    def twin_state(angle: float | None = Query(None, ge=-360, le=360)) -> dict:
        """Live pose of the twin: the plate angle (the turntable's unless given), the found
        mounting, CAD and solved camera, axis and tower (rig frame, mm)."""
        vc()
        from visual_calibration.twin import twin_state as state
        source = "query" if angle is not None else "none"
        t = table.get("t")
        if angle is None and t is not None and t.zero is not None:
            angle, source = t.peek_angle(), "turntable"
        from visual_calibration.overlay import hand_in_plate, plate_in_rig
        r = rig_config()
        return {**state(r, angle), "angle_source": source,
                "hand": {"plate_from_hand": hand_in_plate(r).matrix.round(6).tolist(),
                         "rig_from_hand": (plate_in_rig(r, float(angle or 0.0)) @ hand_in_plate(r)).matrix.round(6).tolist()},
                "swap_angle": float(r.raw["turntable"].get("swap_angle", 180.0)), "travel": r.travel}

    @router.get("/twin/tiles/{name}.png")
    def twin_tile(name: str):
        """A tile's ChArUco face (its own marker ids, its letter in the margin), for the twin's tower."""
        from fastapi.responses import Response
        tile_png = tile_image(name)
        if tile_png is None:
            raise HTTPException(404, f"no tile {name}")
        return Response(tile_png, media_type="image/png", headers={"Cache-Control": "max-age=3600"})

    @lru_cache(maxsize=16)
    def tile_image(name: str) -> bytes | None:
        import cv2
        import numpy as np
        obj = preview_detector().obj
        t = obj.tiles.get(name)
        if t is None:
            return None
        s, k = obj.spec, 8                         # px per mm
        board = cv2.aruco.CharucoBoard(s.squares, s.square_size, s.marker_size,
                                       cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, s.dictionary)),
                                       t.marker_ids(s))
        n = int(round(s.squares[0] * s.square_size * k))
        page = np.full((int(round(s.size[1] * k)), int(round(s.size[0] * k))), 255, np.uint8)
        m = int(round(s.margin * k))
        page[m:m + n, m:m + n] = board.generateImage((n, n), marginSize=0)
        letter = (rig_config().raw["calibration_object"].get("letters") or {}).get(name)
        if letter:
            cv2.putText(page, str(letter), (page.shape[1] - 3 * m, page.shape[0] - m // 3),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.9, 0, 2, cv2.LINE_AA)
        return cv2.imencode(".png", page)[1].tobytes()

    @router.get("/sessions")
    def sessions() -> list[dict]:
        session, _ = vc()
        return [{"id": s.id, "step": s.meta["step"], "created": s.meta["created"], "photos": len(s.meta["photos"]),
                 "solved": s.result() is not None} for s in session.Session.list(sessions_dir())]

    @router.post("/sessions")
    def create(body: NewSession) -> dict:
        session, _ = vc()
        return session.Session.create(sessions_dir(), body.step, hand_turned=body.hand_turned).summary()

    @router.get("/sessions/{sid}")
    def get(sid: str) -> dict:
        return open_session(sid).summary()

    def plate_at(s, stop: float, plate: float | None) -> float | None:
        """The plate's angle for a photo: given, else the turntable's read-back; 409 off the stop."""
        t = table.get("t")
        if plate is None and t is not None and t.zero is not None and not s.meta.get("hand_turned"):
            plate = t.peek_angle()
        if plate is not None and abs(plate - stop) > 2.0:
            raise HTTPException(409, f"the plate is at {plate:.1f}°, not at the stop {stop:g}°")
        return plate

    @router.post("/sessions/{sid}/photos")
    async def add_photo(sid: str, request: Request, stop: float = Query(..., ge=-360, le=360),
                        plate: float | None = Query(None, ge=-360, le=360), camera: str = Query("a")) -> dict:
        """A photo taken elsewhere (an import; a sweep uses /capture). `plate`: the plate's angle when
        the photo was taken; by default the turntable's read-back (the solves use it instead of the
        nominal stop)."""
        data = await request.body()
        if not data:
            raise HTTPException(400, "send the image as the request body")
        s = open_session(sid)
        if camera not in s.rig.cameras:
            raise HTTPException(404, f"no camera {camera}")
        plate = plate_at(s, stop, plate)

        def work():
            with lock:
                return s.add_photo(data, stop, "jpg" if data[:2] == b"\xff\xd8" else "png", plate_deg=plate, camera=camera)
        try:
            entry, dets = await asyncio.to_thread(work)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        return {"photo": entry, "size": s.meta["image_size"], "detections": _detections(dets),
                "orientation": _orientation(s.object, dets)}

    @router.post("/sessions/{sid}/capture")
    def capture(sid: str, stop: float = Query(..., ge=-360, le=360),
                plate: float | None = Query(None, ge=-360, le=360)) -> dict:
        """A photo from every camera at this stop: the backend's own full-resolution stills (PNG),
        each stored tagged by its camera. 409 before a camera preflight passed."""
        s = open_session(sid)
        plate = plate_at(s, stop, plate)
        frames = camera_call(lambda c: c.stills())
        out = {}
        with lock:
            for cam, img in frames.items():
                try:
                    entry, dets = s.add_photo(img, stop, plate_deg=plate, camera=cam)
                except ValueError as e:
                    raise HTTPException(400, f"camera {cam}: {e}") from e
                out[cam] = {"photo": entry, "detections": _detections(dets), "orientation": _orientation(s.object, dets)}
        return {"stop": stop, "size": s.meta["image_size"], "cameras": out}

    fit_lock = threading.Lock()

    def live_fit():
        if "fit" not in table:
            _experiment_on_path()
            from visual_calibration.live_fit import LiveHandFit
            table["fit"] = LiveHandFit(rig_config())
        return table["fit"]

    @router.post("/live-fit/frame")
    async def live_fit_frame(request: Request, angle: float | None = Query(None, ge=-360, le=360),
                             joints: str | None = Query(None), source: str = Query("zeros"),
                             iters: int = Query(2, ge=1, le=20), solve_joints: bool = Query(False),
                             search: bool = Query(False)) -> dict:
        """A few iterations of the hand's pose fit on this frame (raw camera image, any size),
        warm-started: the mount, and with solve_joints the joints too (camera only), else the
        joints given. The plate angle is the turntable's read-back when connected."""
        import json as _json
        data = await request.body()
        if not data:
            raise HTTPException(400, "send the frame as the request body")
        t = table.get("t")
        at = t.peek_angle() if t is not None and t.zero is not None else angle
        if at is None:
            raise HTTPException(409, "no plate angle: connect the turntable or send angle")
        q = _json.loads(joints) if joints else {}

        def work():
            import cv2
            import numpy as np
            img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                raise ValueError("not an image")
            with fit_lock:
                f = live_fit()
                t0 = __import__("time").perf_counter()
                r = f.step(img, float(at), q, iters, solve_joints=solve_joints, search=search)
                known = set(f.model.movable)
                f.frame = data
                f.last.update({"joints_source": "camera" if solve_joints else source, "joints_used": sorted(k for k in q if k in known),
                               "joints_unknown": sorted(k for k in q if k not in known), "joints": q,
                               "seconds": round(__import__("time").perf_counter() - t0, 3)})
                return {k: v for k, v in r.items()}
        try:
            return await asyncio.to_thread(work)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e

    @router.post("/live-fit/reset")
    def live_fit_reset() -> dict:
        if "fit" in table:
            table["fit"].reset()
        return {"ok": True}

    @router.post("/live-fit/keep-view")
    def live_fit_keep_view() -> dict:
        """Keep the last frame as an extra view of the same pose (another plate angle)."""
        f = table.get("fit")
        if f is None:
            raise HTTPException(409, "no fit yet")
        try:
            with fit_lock:
                return {"views": f.keep_view()}
        except ValueError as e:
            raise HTTPException(409, str(e)) from e

    @router.post("/live-fit/clear-views")
    def live_fit_clear_views() -> dict:
        if "fit" in table:
            with fit_lock:
                table["fit"].clear_views()
        return {"views": 0}

    @router.post("/live-fit/freeze")
    def live_fit_freeze() -> dict:
        """Save the current fit and its frame for offline debugging."""
        import datetime
        import yaml
        f = table.get("fit")
        if f is None or not getattr(f, "frame", None):
            raise HTTPException(409, "no fit yet")
        out = sessions_dir() / "live_fit" / datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        out.mkdir(parents=True, exist_ok=True)
        (out / ("frame.jpg" if f.frame[:2] == b"\xff\xd8" else "frame.png")).write_bytes(f.frame)
        keep = {k: v for k, v in f.last.items() if k not in ("outlines", "segmentation")}
        (out / "fit.yaml").write_text(yaml.safe_dump(_plain(keep), sort_keys=False))
        return {"path": str(out)}

    @router.post("/detect")
    async def detect(request: Request) -> dict:
        """Tiles in a preview frame, for the live overlay (nothing is stored)."""
        _, read_image = vc()
        data = await request.body()
        try:
            img = read_image(data)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        dets = await asyncio.to_thread(preview_detector().detect, img)
        return {"size": [int(img.shape[1]), int(img.shape[0])], "detections": _detections(dets),
                "orientation": _orientation(preview_detector().obj, dets)}

    @router.post("/sessions/{sid}/solve")
    def solve(sid: str) -> dict:
        s = open_session(sid)
        with lock:
            try:
                s.solve()
            except (ValueError, NotImplementedError) as e:
                raise HTTPException(400, str(e)) from e
            except Exception as e:                 # a bad photo set must not end in a bare 500
                raise HTTPException(500, f"solve failed: {type(e).__name__}: {e}") from e
        return s.summary()

    def lut_model():
        """The hand study's lookup table (experiment hand_study), reloaded when refitted."""
        _experiment_on_path()
        from hand_study import lut as L
        path = L.STUDY / "lut_model.json"
        if not path.exists():
            return None
        if table.get("lut_mtime") != path.stat().st_mtime:
            table["lut"], table["lut_mtime"] = L.Lut.load(path), path.stat().st_mtime
        return table["lut"]

    @router.get("/study-map", dependencies=RESEARCH)
    def study_map_state() -> dict:
        """The study's per-joint map (command -> true, orca_core estimate -> true) and whether
        manual joint commands go through it."""
        from orca_ui.hand import overlays
        from orca_ui.hand.study_map import STUDY_MAP
        return {**STUDY_MAP.state(), "overlays": overlays.catalog()}

    @router.post("/study-map", dependencies=RESEARCH)
    def study_map_switch(body: StudyMapSwitch) -> dict:
        """On: the next manual commands go through the map. Nothing is sent now."""
        from orca_ui.hand.study_map import STUDY_MAP
        try:
            if body.mode is not None:
                STUDY_MAP.set_mode(body.mode)
            else:
                STUDY_MAP.set_enabled(bool(body.enabled))
        except ValueError as e:
            raise HTTPException(409, str(e)) from e
        from orca_ui.hand import overlays
        return {**STUDY_MAP.state(), "overlays": overlays.catalog()}

    @router.get("/lut", dependencies=RESEARCH)
    def lut_state() -> dict:
        """Whether the study's lookup table exists, its held-out accuracy, and the touch poses."""
        import json as _json
        _experiment_on_path()
        from hand_study import lut as L
        rep = L.STUDY / "lut.json"
        touch = L.STUDY / "touch_poses.json"
        report = _json.loads(rep.read_text()) if rep.exists() else None
        mount = None
        if report and report.get("mount"):
            import numpy as np
            from orca_core.kinematics.transforms import Transform
            from visual_calibration.live_fit import delta
            from visual_calibration.overlay import hand_in_plate
            R, t = delta(np.array(report["mount"], float))
            b = hand_in_plate(rig_config())
            mount = Transform.from_rotation_translation(R @ b.rotation, b.translation + t).matrix.round(6).tolist()
        return {"available": lut_model() is not None, "mount": mount,
                "summary": report and report.get("summary"), "heldout": report and report.get("heldout"),
                "tips": report and report.get("tips"),
                "touch": {f: t["q"] for f, t in _json.loads(touch.read_text()).items()} if touch.exists() else {}}

    @router.post("/lut/command", dependencies=RESEARCH)
    def lut_command(body: LutCommand) -> dict:
        """The joint command for the wanted true angles (the table's inverse), and the angles the
        hand will really reach with that command (its forward map). Nothing is sent to the hand."""
        model = lut_model()
        if model is None:
            if body.use_lut:
                raise HTTPException(409, "no lookup table yet: run the hand study's lut fit")
            return {"command": body.angles, "reached": None}
        joints = list(model.tables)
        want = {j: float(body.angles.get(j, 0.0)) for j in joints}
        cmd = model.inverse(want) if body.use_lut else want
        return {"command": {j: round(v, 2) for j, v in cmd.items()},
                "reached": {j: round(v, 2) for j, v in model.forward(cmd).items()}}

    @router.post("/sessions/{sid}/apply")
    def apply(sid: str) -> dict:
        s = open_session(sid)
        try:
            return {"path": s.apply()}
        except ValueError as e:
            raise HTTPException(400, str(e)) from e

    STUDY_URL = os.environ.get("ORCA_STUDY_URL", "http://127.0.0.1:5010")

    def _study(path: str):
        import json as _json
        import urllib.error
        import urllib.request
        try:
            with urllib.request.urlopen(STUDY_URL + path, timeout=8) as r:
                return _json.load(r)
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise HTTPException(503, f"study server not reachable at {STUDY_URL} ({e})") from e

    @router.get("/study/protocols", dependencies=RESEARCH)
    def study_protocols() -> list:
        """The study's protocol nights (hand_study/server.py on :5010)."""
        return _study("/api/protocols")

    @router.get("/study/protocol/{tag}", dependencies=RESEARCH)
    def study_protocol(tag: str) -> dict:
        """One night's phases, steps, ETAs, faults and results, as the study server reports them."""
        if "/" in tag or ".." in tag:
            raise HTTPException(400, "bad tag")
        return _study(f"/api/protocol/{tag}")

    from orca_ui.hand.study_map import study_dir
    NOTES = study_dir() / "protocol"

    def _notes_path(tag: str) -> Path:
        if "/" in tag or ".." in tag:
            raise HTTPException(400, "bad tag")
        return NOTES / tag / "notes.jsonl"

    @router.get("/study/notes/{tag}", dependencies=RESEARCH)
    def study_notes(tag: str, limit: int = 20) -> list:
        """The status feed of a protocol night, newest first."""
        import json as _json
        path = _notes_path(tag)
        if not path.exists():
            return []
        rows = [_json.loads(x) for x in path.read_text().splitlines() if x.strip()]
        return rows[::-1][:limit]

    @router.post("/study/notes/{tag}", dependencies=RESEARCH)
    def study_note_add(tag: str, body: StudyNote) -> dict:
        """Post a status line to the night's feed (agents: curl -d '{"text": ...}')."""
        import json as _json
        path = _notes_path(tag)
        path.parent.mkdir(parents=True, exist_ok=True)
        row = {"t": time.time(), "who": body.who[:40], "text": body.text[:500]}
        with path.open("a") as f:
            f.write(_json.dumps(row) + "\n")
        return row

    # ---- Measure joint ranges (the assemblers' hand steps): hand_study.run_hand as the console's
    # child process (orca_ui.hand.hand_run), followed from its run folder (run_hand.progress, .results).
    measure: dict = {"run": None}

    def attach_service(service, ui_url: str) -> None:
        """The hand service (the hand to measure, its torque) and the URL the run drives the console at."""
        from orca_ui.hand.hand_run import HandRun
        from orca_ui.home import ui_home
        hand["service"] = service
        measure["run"] = router.hand_run = HandRun(EXPERIMENT, ui_url, lambda: ui_home() / "visual_calibration" / "hand_runs",
                                                   safe_off=run_safe_off, on_end=run_ended)

    def stop_hand_run(why: str = "stopped", release: bool = True) -> bool:
        return measure["run"] is not None and measure["run"].stop(why, release)

    router.attach_service = attach_service
    router.stop_hand_run = stop_hand_run
    router.hand_run_active = lambda: measure["run"] is not None and measure["run"].alive()

    def run_safe_off() -> None:
        """Hand and plate torque off after a run (night.py does it too; a killed run cannot)."""
        try:
            hand["service"].disable_torque()
        except Exception as e:                     # no hand session: nothing holds
            logger.warning("hand run: hand torque off: %s", e)
        release_turntable()

    def runner():
        if measure["run"] is None:
            raise HTTPException(409, "this console has no hand to measure")
        return measure["run"]

    def run_hand_module():
        _experiment_on_path()
        from hand_study import run_hand
        return run_hand

    def run_view(status: dict) -> dict:
        """The process, the run's progress from its files and, once it ended, how: done (the night
        finished), failed, stopped or ended (a dry run lists its steps only)."""
        progress = run_hand_module().progress(Path(status["run"])) if status.get("run") else None
        night = (progress or {}).get("state")
        state = status["state"]
        if state == "ended":
            state = "done" if night == "done" else "failed" if status.get("returncode") or night == "aborted" else "ended"
        return {**status, "state": state, "progress": progress}

    def run_ended(status: dict) -> None:
        """A finished run recorded the hand's ranges: the hand reconnects, so they are in force now."""
        if not status.get("dry") and run_view(status)["state"] == "done":
            hand["service"].reconnect()

    def hand_to_measure() -> str:
        service = hand["service"]
        if service is None:
            raise HTTPException(409, "this console has no hand to measure")
        session = service.session
        hand_id = getattr(session.hand, "hand_id", None) if session is not None and session.caps.motors else None
        if service.supervisor.status().state.value != "connected" or not hand_id:
            raise HTTPException(409, "connect the hand first")
        return hand_id

    @router.get("/hand-run")
    def hand_run_state() -> dict:
        return run_view(runner().status())

    @router.post("/hand-run/start")
    def hand_run_start(body: MeasureStart | None = None) -> dict:
        """Measure the connected hand (~65 min): both cameras proven first, the plate connected, no
        operation running. The run turns the plate and moves the hand, never both at once."""
        body = body or MeasureStart()
        run = runner()
        hand_id = hand_to_measure()
        manager = hand["service"].operation_manager
        if manager is not None and manager.active():
            raise HTTPException(409, "an operation is running: wait for it or stop it")
        if run.alive():
            raise HTTPException(409, "a hand run is already running")
        if "t" not in table:
            raise HTTPException(409, "the rig's plate is not connected")
        camera_call(lambda c: c.preflight(None, write=True))
        try:
            return run_view(run.start(hand_id, dry=body.dry, limit=body.limit))
        except (RuntimeError, OSError) as e:
            raise HTTPException(409, str(e)) from e

    @router.post("/hand-run/stop")
    def hand_run_stop() -> dict:
        """End the run now (its processes killed), hand and plate torque off."""
        runner().stop("stopped")
        return hand_run_state()

    @router.get("/hand-run/photo/{cam}.jpg")
    def hand_run_photo(cam: str) -> FileResponse:
        """The run's newest photo from camera `cam`, as taken."""
        status = runner().status()
        run = Path(status["run"]) if status.get("run") else None
        rh = run_hand_module()
        rel = rh.last_photos(run, rh.night_files(run)[0]).get(cam) if run else None
        if not rel:
            raise HTTPException(404, f"no photo from camera {cam} yet")
        return FileResponse(run / rel, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @router.get("/hand-run/results")
    def hand_run_results() -> dict:
        """The connected hand's newest measured run on this rig: per joint the range in force before
        and the measured one, which joints were measured, the accuracy before and after."""
        from visual_calibration.rig_config import RigConfigError
        hand_id = hand_to_measure()
        rh = run_hand_module()
        try:
            run = rh.latest_run(hand_id, with_results=True)
        except RigConfigError as e:
            raise HTTPException(409, str(e)) from e
        return {"hand": hand_id, "results": _plain(rh.results(run)) if run else None}

    @router.get("/board-write")
    def board_write_state() -> dict:
        """Whether this computer can write a hand's board (an orca_firmware checkout), and why not."""
        from orca_ui.hand.operations.board_write import board_writer
        return board_writer()

    return router
