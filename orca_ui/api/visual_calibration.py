"""Visual calibration: the turntable motor, sessions of photos of the turning
rig, tile detection, and the solves (1a camera, 1b rotation).

The code is orca_core's self-contained experiment
``experiments/visual_calibration/`` (its README), not the orca_core package: it
is put on sys.path from $ORCA_VISUAL_CALIBRATION, else ``../orca_core/experiments/visual_calibration``.

Photos are sent as the raw image bytes (PNG/JPEG body), the stop and the camera
(`cam`: a, b; config.yaml `cameras:`) as query parameters. A camera is known by its USB
serial, never by the browser's or OpenCV's device order: /camera/identify compares a
browser frame with a still of each camera taken by serial (uvc.camera_index + the
process's one SharedCamera per camera), and a photo posted with verify=true is checked
the same way before it is stored. Sessions live in ``~/.orca_ui/visual_calibration/<id>/``
(visual_calibration.session). The plate is turned by the rig's Dynamixel
(visual_calibration.turntable; the mock one under --mock); the page drives the
sweep: move, then grab a frame and post it.
CPU-bound handlers are plain ``def`` so FastAPI runs them off the event loop.
"""
from __future__ import annotations

import asyncio
import os
import sys
import threading
import time
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel


class NewSession(BaseModel):
    step: Literal["camera", "rotation", "hand"] = "camera"
    hand_turned: bool = False                      # True: the plate was turned by hand to the stops
    hold: bool = False                             # rotation: keep the applied lenses and tiles (the quick re-check)


class Connect(BaseModel):
    port: str | None = None
    motor_id: int | None = None
    torque: bool = False                           # False: read the angle only, the plate stays free


class Move(BaseModel):
    angle: float
    hold: bool = False                             # a sweep's stop: the torque stays on (for HOLD_LEASE_S)


class Home(BaseModel):
    hold: bool = False


class StudyMapSwitch(BaseModel):
    enabled: bool | None = None
    mode: str | None = None                        # "off" or a map of the connected hand


class LutCommand(BaseModel):
    angles: dict[str, float]                       # the true joint angles wanted (deg)
    use_lut: bool = True                           # False: send them as they are (orca_core's linear map)


CAMERA = Query("a", pattern=r"^[a-z]$", description="the rig camera (config.yaml cameras:)")
CAMERA_ROTATION = {"a": 270, "b": 90}   # clockwise display turn of the portrait BRIOs: A rolled -90°, B +90°
IDENTIFY_MIN = 0.8                       # a browser frame is a camera's view at this similarity or above
IDENTIFY_MARGIN = 0.15                   # ... and this far ahead of every other camera
INDEX_TTL_S = 10.0                       # serial -> OpenCV index lookups (system_profiler) are reused this long
CAPTURE_IDLE_S = 60.0                    # a camera the backend opened is let go after this long unused
HOLD_LEASE_S = 20.0    # a held plate (a sweep between stops) drops the torque this long after its last move
RIG_POLL_S = 3.0       # the rig watcher's period (lists ports; probes a new board once)
RIG_PAUSE_S = 8.0      # after an explicit release the watcher leaves the board alone this long


EXPERIMENT = Path(os.environ.get("ORCA_VISUAL_CALIBRATION")
                  or Path(__file__).resolve().parents[3] / "orca_core" / "experiments" / "visual_calibration")


RIG_PATH = os.environ.get("ORCA_RIG_PATH")      # a rig directory instead of the experiment's newest camera-rig


def _experiment_on_path() -> None:
    if str(EXPERIMENT) not in sys.path:
        sys.path.insert(0, str(EXPERIMENT))


def load_rig():
    """The rig config (config.yaml under its local.yaml), loaded afresh."""
    _experiment_on_path()
    from visual_calibration.rig_config import RigConfig
    return RigConfig.load(path=RIG_PATH) if RIG_PATH else RigConfig.load()


def cad_only(rig):
    """The rig as if nothing were calibrated: every reader of calibration.yaml sees it empty (the
    nominal mount pose and lens, the CAD tile seats), for the setup's placement ghost."""
    import copy
    cad = copy.copy(rig)
    cad.load_calibration = lambda: {}
    return cad


_rig_yaml_cache: dict = {}


def rig_yaml() -> list[dict]:
    """The rig's turntable.yaml section and its motor calibration (cached 30 s): the rig board's pins."""
    now = time.monotonic()
    if now - _rig_yaml_cache.get("t", -1e9) > 30.0:
        _experiment_on_path()
        from orca_core.utils.utils import read_yaml
        r = load_rig()
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


_captures: dict = {}          # serial -> {"cam": SharedCamera, "index", "size", "opens", "t": last used}
_indices: dict = {}           # serial -> (OpenCV index, when looked up)
_capture_lock = threading.Lock()
_reaper: dict = {}            # "thread": closes the idle captures
_usb: dict = {}               # the last USB listing: "devices", "t"
USB_TTL_S = 4.0
USB2_SIZE = (1920, 1080)      # what a BRIO sends over a USB 2 link


def usb_devices(fresh: bool = False) -> list[dict]:
    """uvc.usb_devices (ioreg: opens nothing), reused for USB_TTL_S."""
    if fresh or time.monotonic() - _usb.get("t", -1e9) > USB_TTL_S:
        _experiment_on_path()
        from visual_calibration.uvc import usb_devices as listing
        _usb.update(devices=listing(), t=time.monotonic())
    return _usb["devices"]


def link_size(cfg: dict) -> tuple[int, int]:
    """The capture size the camera's link allows: its config resolution, 1920x1080 on USB 2."""
    size = tuple(cfg.get("resolution") or (3840, 2160))
    serial = ((cfg.get("uvc") or {}).get("device") or {}).get("serial")
    dev = next((d for d in usb_devices() if serial is not None and str(d.get("serial")) == str(serial)), None)
    link = (dev or {}).get("link_bps")
    return USB2_SIZE if link is not None and link < 5e9 and size[0] > USB2_SIZE[0] else size


def _camera_index(cfg: dict, fresh: bool = False) -> int:
    from visual_calibration.uvc import camera_index
    serial = ((cfg.get("uvc") or {}).get("device") or {}).get("serial")
    hit = _indices.get(serial)
    if serial and hit and not fresh and time.monotonic() - hit[1] < INDEX_TTL_S:
        return hit[0]
    index = camera_index(cfg)
    if serial:
        _indices[serial] = (index, time.monotonic())
    return index


def _reap_captures() -> None:
    while True:
        time.sleep(5.0)
        now = time.monotonic()
        with _capture_lock:
            idle = [c for c, h in _captures.items()
                    if now - h["t"] > CAPTURE_IDLE_S and h.get("lit_until", 0.0) <= now]
            held = [_captures.pop(c)["cam"] for c in idle]
        for cam in held:
            cam.close()


def _hold(key: str, cfg: dict, owner: str) -> dict:
    """The registry's capture of this camera, opened (by `owner`) if there is none; under _capture_lock."""
    from visual_calibration.capture import SharedCamera
    size = link_size(cfg)
    index = _camera_index(cfg)
    held = _captures.get(key)
    if held is not None and (held["index"] != index or held["size"] != size or held["cam"].stats()["open"] is False):
        held["cam"].close()
        held = None
    if held is None:
        shared_before = (index, size) in getattr(SharedCamera, "_cams", {})
        shared = SharedCamera.get(index, size)
        held = _captures[key] = {"cam": shared, "index": index, "size": size, "opens": shared.opens,
                                 "owner": "other" if shared_before else owner}
        if "thread" not in _reaper:
            _reaper["thread"] = threading.Thread(target=_reap_captures, daemon=True, name="camera-reaper")
            _reaper["thread"].start()
    held["t"] = time.monotonic()
    return held


def serial_still(name: str, cfg: dict):
    """A fresh frame of the camera a config block names by its USB serial (cameras.<name>, or
    any {uvc: {device}} block), at the size its link allows (link_size), from the process's one
    long-lived SharedCamera of it (never a capture per request); let go when idle."""
    _experiment_on_path()
    key = str(((cfg.get("uvc") or {}).get("device") or {}).get("serial") or name)
    with _capture_lock:
        held = _hold(key, cfg, "still")
    img = held["cam"].still()
    if held["cam"].opens != held["opens"]:          # it reopened by index (a replug): who is at that index now?
        if _camera_index(cfg, fresh=True) != held["index"]:
            with _capture_lock:
                _captures.pop(key, None)
            held["cam"].close()
            raise RuntimeError("its OpenCV index changed (replugged?): try again")
        held["opens"] = held["cam"].opens
    return img


def light_up(name: str, cfg: dict, seconds: float) -> float:
    """Stream the camera (its white LED lights) for `seconds`, then let it go, unless something
    else used that capture meanwhile or held it before (the idle reaper closes it later then).
    Returns at once; the time it goes dark (time.monotonic())."""
    _experiment_on_path()
    key = str(((cfg.get("uvc") or {}).get("device") or {}).get("serial") or name)
    with _capture_lock:
        held = _hold(key, cfg, "light")
        started = held["t"]
        until = held["lit_until"] = max(held.get("lit_until", 0.0), started + seconds)

    def off() -> None:
        time.sleep(max(0.0, until - time.monotonic()))
        with _capture_lock:
            if (_captures.get(key) is not held or held["owner"] != "light" or held["t"] > started
                    or held.get("lit_until", 0.0) > until):
                return                             # another user needs it, or a later light extends it
            _captures.pop(key)
        held["cam"].close()
    threading.Thread(target=off, daemon=True, name=f"camera-light-{key}").start()
    return until


def _thumb(img):
    import cv2
    import numpy as np
    gray = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    t = cv2.GaussianBlur(cv2.resize(gray, (64, 36), interpolation=cv2.INTER_AREA).astype(float), (3, 3), 0)
    t -= t.mean()
    n = np.linalg.norm(t)
    return t / n if n > 0 else t


def similarity(a, b) -> float:
    """Normalised correlation of two raw frames at 64x36 (1: the same view)."""
    return float((_thumb(a) * _thumb(b)).sum())


def identity(scores: dict[str, float]) -> str | None:
    """The camera whose view a frame is: clearly the most similar, else None."""
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    if not ranked or ranked[0][1] < IDENTIFY_MIN:
        return None
    if len(ranked) > 1 and ranked[0][1] - ranked[1][1] < IDENTIFY_MARGIN:
        return None
    return ranked[0][0]


class StudyNote(BaseModel):
    text: str
    who: str = "agent"


def build_router(base: Path | None = None, mock: bool = False) -> APIRouter:
    base = base or Path.home() / ".orca_ui" / "visual_calibration"
    router = APIRouter(prefix="/api/visual-calibration", tags=["visual-calibration"])
    lock = threading.Lock()                        # one solve / photo write at a time
    table: dict = {}                               # "t": the open Turntable, "hold_until": the hold's lease

    def release_turntable(close: bool = False) -> bool:
        """Torque off (E-STOP, shutdown, a dropped hold); close: also let go of the board. Running
        setup jobs (the tile tour) are stopped first, so no next move turns the torque back on."""
        for stop in table.get("on_release", []):
            stop()
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
    hand = {"ports": lambda: set(), "blocker": lambda: None}
    presence: dict = {"present": False, "connected": False, "port": None, "usb_serial": None, "reason": "",
                      "model": None, "identity_claim": None, "warnings": [], "autodetect": False}
    probed: set = set()                            # (device, usb serial) already bus-scanned: once per plug-in
    connect_lock = threading.Lock()

    def attach_hand(ports, blocker) -> None:
        """ports(): every device path of the hand; blocker(): why the plate may not turn now."""
        hand["ports"], hand["blocker"] = ports, blocker

    def plate_motion_guard() -> str | None:
        t = table.get("t")
        return "the rig's plate is turning: the hand waits until it stops" if t is not None and table.get("moving") else None

    router.attach_hand = attach_hand
    router.plate_motion_guard = plate_motion_guard

    def find_rig(scan_unknown: bool) -> dict | None:
        """The rig's board: a known serial first; with scan_unknown, a free non-hand board whose
        bus has exactly one motor of a rig model (each board once per plug-in)."""
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
        if not scan_unknown:
            return None
        _experiment_on_path()
        from visual_calibration.turntable import TurntableError, find_rig_bus
        mine_serials = {p.serial_number for p in serial.tools.list_ports.comports() if p.device in mine}
        for p in ports:
            key = (p.device, p.serial_number)
            if key in probed or p.serial_number in mine_serials or port_in_use(p.device):
                continue
            if p.vid not in KNOWN_VIDS["oh_board"] and p.vid not in KNOWN_VIDS.get("dynamixel", []):
                continue
            probed.add(key)
            info = probe_orca_info(p.device) if p.vid in KNOWN_VIDS["oh_board"] else None
            if p.vid in KNOWN_VIDS["oh_board"] and (info is None or info.role != "motor"):
                continue
            try:
                bus = find_rig_bus({**rig_yaml()[0], "board": {**(rig_yaml()[0].get("board") or {}), "usb_serial": None}},
                                   port=p.device)
            except (TurntableError, OSError):
                continue
            v = classify(p.serial_number, info, [{"id": bus.motor_id, "model_name": bus.model}], known)
            if v.rig:
                return {"port": p.device, "usb_serial": p.serial_number, "reason": v.reason,
                        "identity_claim": getattr(info, "serial", None), "warnings": v.warnings}
        return None

    def connect_rig(found: dict | None) -> None:
        """Open the rig read-only (torque off): the plate angle for the dashboard."""
        from orca_ui.hand.rig_detect import check_model
        _experiment_on_path()
        from visual_calibration.turntable import Turntable, TurntableError
        with connect_lock:
            if "t" not in table:
                r = rig_config()
                try:
                    table["t"] = Turntable.open(r.raw["turntable"], mock=mock, port=(found or {}).get("port"),
                                                calibration_path=r.turntable_calibration_path, torque=False)
                except (TurntableError, OSError) as e:
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

    def rig_tick(scan_unknown: bool) -> None:
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
        found = find_rig(scan_unknown)
        presence.update(present=found is not None)
        if found is not None:
            connect_rig(found)

    def rig_watcher() -> None:
        while not table.get("stop_watcher"):
            try:
                rig_tick(scan_unknown=True)
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

    def rig_config():
        return load_rig()

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
        return TileDetector(CalibrationObject.from_config(load_rig().raw["calibration_object"]))

    def open_session(sid: str):
        session, _ = vc()
        root = base / sid
        if "/" in sid or ".." in sid or not (root / "session.yaml").is_file():
            raise HTTPException(404, f"no session {sid}")
        return session.Session(root)

    @router.get("/rig")
    def rig() -> dict:
        vc()
        from visual_calibration.mounting import config_mountings, coverage
        r = load_rig()
        obj = r.raw["calibration_object"]
        found = r.load_calibration().get("mounting")
        cover = coverage(preview_detector().obj, r.stops.angles, config_mountings(obj))
        return {"rig": r.name, "version": r.version, "stops": r.stops.angles, "travel": r.travel,
                "side0_stop": (found or {}).get("side0_stop", obj.get("side0_stop")), "mounting": found,
                "mountings": config_mountings(obj), "coverage_warnings": cover["warnings"],
                "tiles": sorted(preview_detector().obj.tiles),
                "reference_tile": obj.get("reference_tile"), "camera_mount": r.raw["camera"].get("mount"),
                "cameras": cameras_info(r), "active_cameras": r.active_cameras,
                "letters": obj.get("letters") or {},
                "swap_angle": float(r.raw["turntable"].get("swap_angle", 180.0)),
                "rig_board": rig_board(r),
                "mock_turntable": mock}

    def camera_cfg(r, cam: str, enabled: bool = False) -> dict:
        """cameras.<cam> of the rig config; 404 if there is none, 409 if `enabled` and it is off."""
        cfg = r.cameras.get(cam)
        if cfg is None:
            raise HTTPException(404, f"no camera {cam!r} in the rig config (cameras: {', '.join(r.cameras)})")
        if enabled and not cfg.get("enabled", True):
            raise HTTPException(409, f"camera {cam} is disabled in the rig config (enabled: false)")
        return cfg

    def display_rotation(r, cam: str) -> int:
        """The clockwise turn that shows the rig's up as up: config `display_rotation`, else from the
        solved pose (the rig's z in the image), else the BRIO mounts' (CAMERA_ROTATION)."""
        import numpy as np
        from visual_calibration.rig_calibration import camera_from_calibration
        cfg = r.cameras.get(cam) or {}
        if cfg.get("display_rotation") is not None:
            return int(cfg["display_rotation"])
        pose = camera_from_calibration(r.load_calibration(), cam)
        if pose is None:
            return CAMERA_ROTATION.get(cam, 270)
        up = (pose.rotation.T @ [0.0, 0.0, 1.0])[:2]

        def screen_up(k: int) -> float:
            a = np.radians(k)
            return float(-(np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]]) @ up)[1])
        return max((0, 90, 180, 270), key=screen_up)

    def cameras_info(r) -> dict:
        """Every configured camera: enabled, mount, CAD pose, azimuth, serial, display turn, solved."""
        from visual_calibration.rig_calibration import camera_block
        cal = r.load_calibration()
        return {c: {"enabled": bool(cfg.get("enabled", True)), "mount": cfg.get("mount"),
                    "nominal": r.nominal_of(c), "azimuth": round(r.camera_azimuth(c), 3),
                    "resolution": cfg.get("resolution"),
                    "serial": ((cfg.get("uvc") or {}).get("device") or {}).get("serial"),
                    "rotation": display_rotation(r, c),
                    "calibrated": {"lens": bool(camera_block(cal, c).get("lens")),
                                   "pose": bool(camera_block(cal, c).get("camera"))}}
                for c, cfg in r.cameras.items()}

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

    def uvc_state(cam: str, write: bool) -> dict:
        """Camera `cam`'s UVC controls against config.yaml cameras.<cam>.uvc (visual_calibration.uvc)."""
        _experiment_on_path()
        from visual_calibration.uvc import CameraSettingsError, Uvcc, ensure
        cfg = camera_cfg(rig_config(), cam, enabled=True).get("uvc")
        if not cfg:
            return {"ok": True, "camera": cam, "configured": False}
        try:
            r = ensure(Uvcc.from_config(cfg), cfg, write=write)
        except (CameraSettingsError, OSError) as e:
            raise HTTPException(409, f"camera {cam}: {e}") from e
        return {"ok": True, "camera": cam, "configured": True, "set": r["set"], "controls": r["after"]}

    def uvc_cameras(cam: str, write: bool) -> dict:
        """One camera, or with cam=all every active one (409 naming each camera that differs)."""
        if mock:
            return {"ok": True}
        if cam != "all":
            return uvc_state(cam, write)
        out, errors = {}, []
        for c in rig_config().active_cameras:
            try:
                out[c] = uvc_state(c, write)
            except HTTPException as e:
                errors.append(str(e.detail))
        if errors:
            raise HTTPException(409, "; ".join(errors))
        return {"ok": True, "cameras": out}

    @router.get("/camera/uvc")
    def camera_uvc(cam: str = Query("a", pattern=r"^([a-z]|all)$")) -> dict:
        """Read only: 409 when a control differs from the config."""
        return uvc_cameras(cam, write=False)

    @router.post("/camera/uvc")
    def camera_uvc_set(cam: str = Query("a", pattern=r"^([a-z]|all)$")) -> dict:
        """Set the controls that differ, read them back; 409 if they still differ (before a sweep)."""
        return uvc_cameras(cam, write=True)

    def camera_still(cam: str):
        """A fresh frame of camera `cam`, found by its USB serial (409 when it cannot be read)."""
        cfg = camera_cfg(rig_config(), cam, enabled=True)
        _experiment_on_path()
        from visual_calibration.uvc import CameraSettingsError
        try:
            return serial_still(cam, cfg)
        except (CameraSettingsError, RuntimeError, OSError, KeyError, ValueError) as e:
            raise HTTPException(409, f"camera {cam}: {e}") from e

    @router.get("/camera/still")
    def camera_still_jpeg(cam: str = CAMERA, max_side: int = Query(960, ge=64, le=3840)):
        """A still of the camera by its serial, as JPEG, its long side at most max_side (raw, unturned)."""
        import cv2
        from fastapi.responses import Response
        img = camera_still(cam)
        k = min(1.0, max_side / max(img.shape[:2]))
        if k < 1.0:
            img = cv2.resize(img, (round(img.shape[1] * k), round(img.shape[0] * k)), interpolation=cv2.INTER_AREA)
        return Response(cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tobytes(),
                        media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    def identify(img, claim: str | None = None) -> dict:
        """Which active camera's view `img` is (a still of each by serial, compared at 64x36)."""
        if mock:
            return {"camera": claim, "claim": claim, "scores": {}, "errors": {}, "verified": False, "mock": True}
        scores, errors = {}, {}
        for c in rig_config().active_cameras:
            try:
                scores[c] = round(similarity(img, camera_still(c)), 3)
            except HTTPException as e:
                errors[c] = str(e.detail)
        found = identity(scores)
        return {"camera": found, "claim": claim, "scores": scores, "errors": errors, "verified": found is not None}

    @router.post("/camera/identify")
    async def camera_identify(request: Request, claim: str | None = Query(None, pattern=r"^[a-z]$")) -> dict:
        """Which rig camera a browser frame (raw, any size) shows: the browser's device order and
        labels (two BRIOs read alike) say nothing; the serials do. `camera` is None when unsure."""
        _, read_image = vc()
        data = await request.body()
        try:
            img = read_image(data)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        return await asyncio.to_thread(identify, img, claim)

    @router.get("/turntable")
    def turntable_state() -> dict:
        if "t" not in table:
            return {"connected": False, "mock": mock, "homed": False, "angle": None, "busy": False,
                    "port": None, "motor_id": None, "calibrated": False, "zero_from": None, "torque": False}
        return table["t"].state().as_dict()

    @router.post("/turntable/connect")
    def turntable_connect(body: Connect) -> dict:
        vc()
        from visual_calibration.turntable import Turntable, TurntableError
        if "t" in table:
            return table["t"].state().as_dict()
        try:
            r = rig_config()
            table["t"] = Turntable.open(r.raw["turntable"], mock=mock, port=body.port, motor_id=body.motor_id,
                                        calibration_path=r.turntable_calibration_path, torque=body.torque)
        except (TurntableError, OSError) as e:
            raise HTTPException(409, f"turntable: {e}") from e
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
        """Look for the rig now, a new board's bus included (never the hand's ports)."""
        probed.clear()
        table["rig_pause_until"] = 0.0
        rig_tick(scan_unknown=True)
        return rig_presence()

    @router.post("/turntable/release")
    def turntable_release() -> dict:
        table["rig_pause_until"] = time.monotonic() + RIG_PAUSE_S
        t = table.pop("t", None)
        if t is not None:
            t.close()
        return turntable_state()

    @router.get("/overlay")
    def model_overlay(angle: float | None = Query(None, ge=-360, le=360), rotation: float | None = Query(None),
                      cam: str = CAMERA, source: Literal["auto", "cad"] = Query("auto")) -> dict:
        """What camera `cam` should see at a plate angle (default: the turntable's): tiles projected
        into its raw image + the transforms for drawing the hand. rotation: the page's display turn
        (default the camera's), which rolls an uncalibrated camera's CAD pose. source=cad: the
        nominal mount pose and lens and the CAD tiles even when calibration.yaml has solved ones."""
        vc()
        from visual_calibration.overlay import overlay
        r = rig_config()
        camera_cfg(r, cam)
        if source == "cad":
            r = cad_only(r)
        if angle is None:
            t = table.get("t")
            angle = t.angle() if t is not None and t.zero is not None else 0.0
        return {"camera": cam, **overlay(r, float(angle), display_rotation(r, cam) if rotation is None else rotation, cam)}

    @router.get("/status")
    def status() -> dict:
        """Per step (motor calibration, 1a, 1b, 2): status, time, key numbers, structured warnings."""
        vc()
        from visual_calibration.status import calibration_status
        return {**calibration_status(rig_config(), base), "turntable": turntable_state()}

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
        from visual_calibration.rig_calibration import camera_from_calibration
        r = rig_config()
        cal = r.load_calibration()
        cameras = {}
        for c, cfg in r.cameras.items():
            solved = camera_from_calibration(cal, c)
            cameras[c] = {"enabled": bool(cfg.get("enabled", True)), "cad": r.nominal_of(c),
                          "solved": None if solved is None else solved.matrix.round(6).tolist()}
        return {**state(r, angle), "angle_source": source, "cameras": cameras,
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
                 "solved": s.result() is not None} for s in session.Session.list(base)]

    @router.post("/sessions")
    def create(body: NewSession) -> dict:
        session, _ = vc()
        if body.hold and body.step != "rotation":
            raise HTTPException(400, "hold is for a rotation session (the quick re-check)")
        return session.Session.create(base, body.step, hand_turned=body.hand_turned, hold=body.hold).summary()

    @router.get("/sessions/{sid}")
    def get(sid: str) -> dict:
        return open_session(sid).summary()

    @router.post("/sessions/{sid}/photos")
    async def add_photo(sid: str, request: Request, stop: float = Query(..., ge=-360, le=360),
                        plate: float | None = Query(None, ge=-360, le=360), cam: str = CAMERA,
                        verify: bool = Query(False)) -> dict:
        """Camera `cam`'s photo (stop_<deg> for a, stop_<deg>_<cam> for the others). `plate`: the
        plate's angle when it was taken; by default the turntable's read-back (the solves use it
        instead of the nominal stop). verify: refused (409) unless a still of `cam`, taken by its
        serial, shows the same view (a browser stream bound to the wrong camera)."""
        data = await request.body()
        if not data:
            raise HTTPException(400, "send the image as the request body")
        s = open_session(sid)
        camera_cfg(s.rig, cam, enabled=True)
        if verify and not mock:
            _, read_image = vc()
            try:
                img = read_image(data)
            except ValueError as e:
                raise HTTPException(400, str(e)) from e
            who = await asyncio.to_thread(identify, img, cam)
            if who["camera"] != cam:
                raise HTTPException(409, f"this photo is not camera {cam}'s view (it looks like "
                                         f"{who['camera'] or 'no camera for sure'}: {who['scores']}"
                                         f"{'; ' + '; '.join(who['errors'].values()) if who['errors'] else ''})")
        t = table.get("t")
        if plate is None and t is not None and t.zero is not None and not s.meta.get("hand_turned"):
            plate = t.peek_angle()
        if plate is not None and abs(plate - stop) > 2.0:
            raise HTTPException(409, f"the plate is at {plate:.1f}°, not at the stop {stop:g}°")

        def work():
            with lock:
                return s.add_photo(data, stop, "jpg" if data[:2] == b"\xff\xd8" else "png", plate_deg=plate, camera=cam)
        try:
            entry, dets = await asyncio.to_thread(work)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        return {"photo": entry, "camera": cam, "size": s.meta["image_size"], "detections": _detections(dets),
                "orientation": _orientation(s.object, dets)}

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
                             search: bool = Query(False), cam: str = CAMERA) -> dict:
        """A few iterations of the hand's pose fit on this frame (raw camera image, any size),
        warm-started: the mount, and with solve_joints the joints too (camera only), else the
        joints given. The plate angle is the turntable's read-back when connected. Camera `cam`:
        a, or another camera once 1b has solved its pose (its views join the same fit)."""
        import json as _json
        data = await request.body()
        if not data:
            raise HTTPException(400, "send the frame as the request body")
        if cam != "a":
            r = rig_config()
            from visual_calibration.rig_calibration import camera_block
            camera_cfg(r, cam, enabled=True)
            if not camera_block(r.load_calibration(), cam).get("camera"):
                raise HTTPException(409, f"camera {cam} has no solved pose yet: the hand fit uses calibrated cameras only (run 1b)")
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
                if cam not in f.cameras:                   # calibrated since the fit started: a new fit has it
                    table.pop("fit", None)
                    f = live_fit()
                if cam not in f.cameras:
                    raise HTTPException(409, f"camera {cam} is not calibrated: the hand fit leaves it out")
                t0 = __import__("time").perf_counter()
                r = f.step(img, float(at), q, iters, solve_joints=solve_joints, search=search, cam=cam)
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
        out = base / "live_fit" / datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        out.mkdir(parents=True, exist_ok=True)
        (out / ("frame.jpg" if f.frame[:2] == b"\xff\xd8" else "frame.png")).write_bytes(f.frame)
        keep = {k: v for k, v in f.last.items() if k not in ("outlines", "segmentation")}
        (out / "fit.yaml").write_text(yaml.safe_dump(_plain(keep), sort_keys=False))
        return {"path": str(out)}

    @router.post("/detect")
    async def detect(request: Request, cam: str = CAMERA) -> dict:
        """Tiles in camera `cam`'s preview frame, for the live overlay (nothing is stored)."""
        _, read_image = vc()
        data = await request.body()
        try:
            img = read_image(data)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        dets = await asyncio.to_thread(preview_detector().detect, img)
        return {"camera": cam, "size": [int(img.shape[1]), int(img.shape[0])], "detections": _detections(dets),
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

    @router.get("/study-map")
    def study_map_state() -> dict:
        """The study's per-joint map (command -> true, orca_core estimate -> true) and whether
        manual joint commands go through it."""
        from orca_ui.hand import overlays
        from orca_ui.hand.study_map import STUDY_MAP
        return {**STUDY_MAP.state(), "overlays": overlays.catalog()}

    @router.post("/study-map")
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

    @router.get("/lut")
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

    @router.post("/lut/command")
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

    from orca_ui.api.rig_setup import add_setup_routes
    add_setup_routes(router, SimpleNamespace(
        rig_config=rig_config, camera_cfg=camera_cfg, table=table, hand=hand, mock=mock, vc=vc,
        detector=preview_detector, motor=motor, find_rig=find_rig, connect_rig=connect_rig, presence=presence))

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

    @router.get("/study/protocols")
    def study_protocols() -> list:
        """The study's protocol nights (hand_study/server.py on :5010)."""
        return _study("/api/protocols")

    @router.get("/study/protocol/{tag}")
    def study_protocol(tag: str) -> dict:
        """One night's phases, steps, ETAs, faults and results, as the study server reports them."""
        if "/" in tag or ".." in tag:
            raise HTTPException(400, "bad tag")
        return _study(f"/api/protocol/{tag}")

    NOTES = Path.home() / ".orca_ui" / "visual_calibration" / "hand_study" / "protocol"

    def _notes_path(tag: str) -> Path:
        if "/" in tag or ".." in tag:
            raise HTTPException(400, "bad tag")
        return NOTES / tag / "notes.jsonl"

    @router.get("/study/notes/{tag}")
    def study_notes(tag: str, limit: int = 20) -> list:
        """The status feed of a protocol night, newest first."""
        import json as _json
        path = _notes_path(tag)
        if not path.exists():
            return []
        rows = [_json.loads(x) for x in path.read_text().splitlines() if x.strip()]
        return rows[::-1][:limit]

    @router.post("/study/notes/{tag}")
    def study_note_add(tag: str, body: StudyNote) -> dict:
        """Post a status line to the night's feed (agents: curl -d '{"text": ...}')."""
        import json as _json
        path = _notes_path(tag)
        path.parent.mkdir(parents=True, exist_ok=True)
        row = {"t": time.time(), "who": body.who[:40], "text": body.text[:500]}
        with path.open("a") as f:
            f.write(_json.dumps(row) + "\n")
        return row

    return router
