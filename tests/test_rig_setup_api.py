"""The visual-calibration page's 0 · Setup step (orca_ui/api/rig_setup.py): its REST shapes, that
cameras are told apart by serial and pose (never saved over a disagreement without a confirm),
and that its long jobs never leave the torque on (E-STOP stops the tile tour). No hardware: fake
USB listings, fake UVC controls, and stills rendered from the rig's CAD (each camera's nominal
mount pose and lens), written to a copy of the rig directory."""
import shutil
import time

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

cv2 = pytest.importorskip("cv2")

from orca_ui.api import rig_setup
from orca_ui.api import visual_calibration as vc

if not (vc.EXPERIMENT / "visual_calibration" / "setup.py").is_file():
    pytest.skip(f"no visual calibration setup at {vc.EXPERIMENT}", allow_module_level=True)

API = "/api/visual-calibration"
BRIO = {"vendor": 1133, "product": 2142}
SERIALS = {"a": "SERIAL_A", "b": "SERIAL_B"}


class FakeUvcc:
    def __init__(self):
        self.state: dict = {}

    def export(self) -> dict:
        return dict(self.state)

    def set(self, key, value) -> None:
        self.state[key] = value


@pytest.fixture
def rig(tmp_path, monkeypatch):
    """A copy of the rig (no local.yaml: a newly built one), two BRIOs on USB, cam B on USB 2."""
    vc._experiment_on_path()
    from visual_calibration.rig_config import get_rig_path
    from visual_calibration.uvc import unique_id
    path = tmp_path / "camera-rig"
    shutil.copytree(get_rig_path(), path, ignore=shutil.ignore_patterns("local.yaml", "rig_machine"))
    monkeypatch.setattr(vc, "RIG_PATH", str(path))
    devices = [{**BRIO, "name": "Logitech BRIO", "serial": SERIALS["a"], "location": 0x01100000, "address": 1,
                "link_bps": 5_000_000_000},
               {**BRIO, "name": "Logitech BRIO", "serial": SERIALS["b"], "location": 0x02100000, "address": 1,
                "link_bps": 480_000_000}]
    monkeypatch.setattr(vc, "usb_devices", lambda fresh=False: devices)
    monkeypatch.setattr(rig_setup, "_av_ids", lambda fresh=False: [unique_id(d) for d in devices])
    monkeypatch.setattr(rig_setup, "SETTLE_S", {"exposure": 0.0, "focus": 0.0, "tour": 0.0})
    return path


def client(mock=False):
    router = vc.build_router(mock=mock)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app), router


def render(c, cam: str, angle: float = 90.0) -> np.ndarray:
    """What camera `cam` sees of the tower at its CAD pose: the tiles warped onto their outlines."""
    o = c.get(f"{API}/overlay?angle={angle}&cam={cam}&source=cad&rotation={270 if cam == 'a' else 90}").json()
    W, H = o["lens"]["size"]
    img = np.full((H, W), 140, np.uint8)
    for t in o["tiles"]:
        if not t["facing"]:
            continue
        page = cv2.imdecode(np.frombuffer(c.get(f"{API}/twin/tiles/{t['tile']}.png").content, np.uint8), 0)
        h, w = page.shape
        M = cv2.getPerspectiveTransform(np.float32([[0, 0], [w, 0], [w, h], [0, h]]), np.float32(t["outline"]))
        mask = cv2.warpPerspective(np.full_like(page, 255), M, (W, H)) > 0
        img[mask] = cv2.warpPerspective(page, M, (W, H))[mask]
    return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)


def wait(c, job: dict, timeout: float = 120.0) -> dict:
    end = time.monotonic() + timeout
    while job["state"] == "running" and time.monotonic() < end:
        time.sleep(0.05)
        job = c.get(f"{API}/setup/jobs/{job['id']}").json()
    return job


def serial_of(cfg) -> str:
    return cfg["uvc"]["device"]["serial"]


def test_setup_usb_identify_and_align(rig, monkeypatch):
    c, _ = client()
    views = {SERIALS["a"]: render(c, "a"), SERIALS["b"]: render(c, "b")}
    monkeypatch.setattr(vc, "serial_still", lambda name, cfg: views[serial_of(cfg)])

    usb = c.get(f"{API}/setup/usb").json()
    assert usb["status"] == "error" and [w["values"]["serial"] for w in usb["banner"]] == [SERIALS["b"]]
    assert {x["serial"]: x["usb3"] for x in usb["cameras"]} == {SERIALS["a"]: True, SERIALS["b"]: False}
    assert vc.link_size({"resolution": [3840, 2160], "uvc": {"device": {"serial": SERIALS["b"]}}}) == (1920, 1080)

    s = c.get(f"{API}/setup").json()
    assert not s["ready"] and s["items"]["identify"]["status"] in ("not run", "error") and s["blockers"]

    # Which BRIO is which by eye: its LED, by serial before serials are saved; capped, never held.
    lit = []
    monkeypatch.setattr(vc, "light_up", lambda name, cfg, seconds: lit.append((serial_of(cfg), seconds)) or time.monotonic() + seconds)
    assert c.post(f"{API}/setup/light?cam=a").status_code == 409                          # no serial yet
    assert c.post(f"{API}/setup/light?serial=NOPE").status_code == 404
    assert c.post(f"{API}/setup/light?serial={SERIALS['b']}&seconds=99").json()["seconds"] == 30

    # A new rig, both cameras clearly told apart by their poses: saved at once.
    r = c.post(f"{API}/setup/identify").json()
    assert r["identify"]["assignment"] == SERIALS and r["identify"]["confident"] and r["saved"]
    assert vc.load_rig().cameras["b"]["uvc"]["device"]["serial"] == SERIALS["b"]                # local.yaml
    assert all(x["image"] and x["pose"]["corners"] >= 12 for x in r["cameras"])

    # The cameras swapped on the rig: shown, never saved over the old serials without a confirm.
    views = {SERIALS["a"]: views[SERIALS["b"]], SERIALS["b"]: views[SERIALS["a"]]}
    r = c.post(f"{API}/setup/identify").json()
    assert r["disagree"] and not r["saved"] and r["status"] == "warn"
    assert vc.load_rig().cameras["a"]["uvc"]["device"]["serial"] == SERIALS["a"]
    swapped = {"a": SERIALS["b"], "b": SERIALS["a"]}
    assert c.post(f"{API}/setup/identify/save", json={"assignment": {"a": "NOPE", "b": SERIALS["a"]}}).status_code == 400
    assert c.post(f"{API}/setup/identify/save", json={"assignment": swapped}).json()["status"] == "ok"
    assert vc.load_rig().cameras["a"]["uvc"]["device"]["serial"] == SERIALS["b"]

    # Each camera at its CAD mount: in tolerance, green only after the check once locked.
    assert c.post(f"{API}/setup/light?cam=a&seconds=5").json()["serial"] == SERIALS["b"]
    assert lit == [(SERIALS["b"], 30.0), (SERIALS["b"], 5.0)]
    a = c.get(f"{API}/setup/align?cam=a").json()
    assert a["ok"] and a["placement"]["lock"] and a["pose"]["tiles"]
    assert c.post(f"{API}/setup/align/check?cam=b").json()["status"] == "warn"                 # not locked yet
    assert c.post(f"{API}/setup/align/check?cam=b&locked=true").json()["status"] == "ok"
    s = c.get(f"{API}/setup").json()
    assert s["items"]["align"]["cameras"]["b"]["status"] == "ok" and s["items"]["identify"]["status"] == "ok"

    assert c.post(f"{API}/setup/mount", json={"cam": "a", "key": "height", "value": 260.0}).json()["ok"]
    assert vc.load_rig().cameras["a"]["mount"]["height"] == 260.0
    assert c.post(f"{API}/setup/mount", json={"cam": "a", "key": "height", "value": 263.0}).status_code == 400
    assert vc.load_rig().cameras["a"]["mount"]["height"] == 260.0                         # not a hole: undone

    # Records the setup CLI writes (python -m visual_calibration.setup all --save) read the same.
    from visual_calibration import setup
    r = vc.load_rig()
    setup.record(r, "align", {"a": {"status": "warn", "locked": False, "found": {"distance": 260.0}}})
    setup.record(r, "focus", {"a": {"status": "ok", "focus": 52, "worst": 0.9, "mean": 0.95}})
    setup.record(r, "tour", {"status": "ok", "seen": {}, "missing": [], "stops": [], "warnings": []})
    s = c.get(f"{API}/setup").json()["items"]
    assert s["align"]["cameras"]["a"]["status"] == "warn" and s["focus"]["cameras"]["a"]["focus"] == 52
    assert s["tour"]["status"] == "ok"


def test_setup_jobs_save_and_lock_and_the_tour_stops_on_estop(rig, monkeypatch):
    c, router = client(mock=True)
    base = cv2.resize(render(c, "b"), (1920, 1080), interpolation=cv2.INTER_AREA)
    cams = {s: FakeUvcc() for s in SERIALS.values()}
    monkeypatch.setattr(rig_setup, "_uvcc", lambda uvc: cams[uvc["device"]["serial"]])
    slow = {"s": 0.0}

    def still(name, cfg):                          # brightness from the exposure, blur from the focus
        time.sleep(slow["s"])
        st = cams[serial_of(cfg)].state
        img = np.clip(base.astype(float) * st.get("absolute_exposure_time", 100) / 400, 0, 255).astype(np.uint8)
        sigma = abs(st.get("absolute_focus", 0) - 44) / 10
        return cv2.GaussianBlur(img, (0, 0), sigma) if sigma else img
    monkeypatch.setattr(vc, "serial_still", still)
    vc.load_rig().save_local({"cameras": {k: {"uvc": {"device": {"serial": s}}} for k, s in SERIALS.items()}})

    e = wait(c, c.post(f"{API}/setup/exposure?cam=b").json())
    exposure = e["result"]["exposure"]                                                     # whole 10 ms flicker periods
    assert e["state"] == "done" and exposure % 100 == 0 and not e["result"]["dim"] and e["progress"] > 0
    assert c.post(f"{API}/setup/focus?cam=b").json()["state"] == "running"
    assert c.post(f"{API}/setup/exposure?cam=a").status_code == 409                        # one job at a time
    f = wait(c, c.get(f"{API}/setup").json()["jobs"][-1])
    assert f["state"] == "done" and abs(f["result"]["focus"] - 44) <= 2 and f["result"]["curve"]
    uvc = vc.load_rig().cameras["b"]["uvc"]
    assert (uvc["absolute_exposure_time"], uvc["absolute_focus"]) == (exposure, f["result"]["focus"])   # local.yaml
    assert cams[SERIALS["b"]].state["absolute_focus"] == f["result"]["focus"]                       # and locked
    s = c.get(f"{API}/setup").json()["items"]
    assert s["exposure"]["cameras"]["b"]["exposure"] == exposure and s["focus"]["cameras"]["b"]["status"] in ("ok", "warn")

    assert c.post(f"{API}/setup/tour").status_code == 409                                  # not homed
    c.post(f"{API}/turntable/connect", json={})
    c.post(f"{API}/turntable/home")
    t = wait(c, c.post(f"{API}/setup/tour").json())
    assert t["state"] == "done" and len(t["result"]["stops"]) == 8 and t["result"]["missing"]
    assert t["result"]["status"] == "error" and not c.get(f"{API}/turntable").json()["torque"]

    slow["s"] = 0.3
    t = c.post(f"{API}/setup/tour").json()
    time.sleep(0.5)
    router.release_turntable()                                                               # E-STOP
    t = wait(c, t, timeout=20)
    assert t["state"] == "cancelled" and not c.get(f"{API}/turntable").json()["torque"]


def test_a_lit_camera_is_let_go_unless_another_user_needs_it(monkeypatch):
    vc._experiment_on_path()
    from visual_calibration import capture

    class FakeShared:
        opened: list = []

        def __init__(self):
            self.opens, self.closed = 1, False
            FakeShared.opened.append(self)

        def stats(self):
            return {"open": not self.closed}

        def still(self):
            return np.zeros((4, 4, 3), np.uint8)

        def close(self):
            self.closed = True
    monkeypatch.setattr(capture.SharedCamera, "get", classmethod(lambda cls, index, size: FakeShared()))
    monkeypatch.setattr(vc, "_camera_index", lambda cfg, fresh=False: 7)
    monkeypatch.setattr(vc, "link_size", lambda cfg: (1920, 1080))
    monkeypatch.setattr(vc, "_captures", {})
    cfg = {"uvc": {"device": {"serial": "SERIAL_X"}}}
    vc.light_up("x", cfg, 0.2)
    lit = FakeShared.opened[-1]
    time.sleep(0.5)
    assert lit.closed and "SERIAL_X" not in vc._captures                                  # dark again, let go
    vc.light_up("x", cfg, 0.2)
    vc.serial_still("x", cfg)                                                               # a still needs it now
    time.sleep(0.5)
    assert not FakeShared.opened[-1].closed and "SERIAL_X" in vc._captures
