"""The rig's cameras behind the console (a fake camera service, no cv2): nothing full-resolution
leaves the backend before the camera preflight passed; the preview needs none. A rig dependency
this Python lacks is said, never a bare 500."""
import sys

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from orca_ui.api.visual_calibration import EXPERIMENT, build_router

if not (EXPERIMENT / "visual_calibration" / "rig_cameras.py").is_file():
    pytest.skip(f"no rig camera service at {EXPERIMENT}", allow_module_level=True)


class FakeCameras:
    def __init__(self):
        self.checked, self.refuse = False, "camera b: dimming it (serial SB) darkened no stream"

    def _error(self, msg):
        from visual_calibration.rig_cameras import CameraIdentityError
        return CameraIdentityError(msg)

    def status(self):
        return {"cameras": [{"name": "a", "index": 1}, {"name": "b", "index": 0}], "checked": self.checked}

    def preflight(self, detector=None, write=True):
        if self.refuse:
            raise self._error(self.refuse)
        self.checked = True
        return {"indices": {"a": 1, "b": 0}, "identified_by": "serial"}

    def lock_controls(self, write=True):
        return {c: {"set": {"gain": 0} if write else {}, "after": {"gain": 0}} for c in "ab"}

    def preview(self, cam, max_side=1600):
        from visual_calibration.rig_cameras import UnknownCamera
        if cam == "c":
            raise KeyError("uvc")                                               # a camera block without uvc:
        if cam not in "ab":
            raise UnknownCamera(cam)
        return np.zeros((9, 16, 3), np.uint8)

    def still(self, cam, after=None):
        if not self.checked:
            raise self._error("the cameras are not checked: run the camera preflight")
        return self.preview(cam)

    def stills(self, after=None):
        return {c: self.still(c, after) for c in "ab"}


def test_stills_only_after_the_camera_preflight(tmp_path, monkeypatch):
    cams = FakeCameras()
    app = FastAPI()
    app.include_router(build_router(tmp_path, cameras=cams))
    c = TestClient(app)
    api = "/api/visual-calibration/cameras"
    assert [x["name"] for x in c.get(api).json()["cameras"]] == ["a", "b"]        # puts the experiment on sys.path
    from visual_calibration import rig_cameras
    monkeypatch.setattr(rig_cameras, "encode", lambda img, fmt="png", quality=95: b"\xff\xd8" + fmt.encode())
    assert c.get(f"{api}/a/still?format=jpg").status_code == 409                  # not checked yet
    r = c.post(f"{api}/preflight", json={"tiles": False})
    assert r.status_code == 409 and "darkened no stream" in r.text
    assert c.get(f"{api}/b/still").status_code == 409
    p = c.get(f"{api}/b/preview.jpg")                                            # the operator aims by it
    assert p.status_code == 200 and p.headers["content-type"] == "image/jpeg" and p.headers["cache-control"] == "no-store"
    assert c.get(f"{api}/z/preview.jpg").status_code == 404
    bad = c.get(f"{api}/c/preview.jpg")
    assert bad.status_code == 409 and "config.yaml" in bad.text
    assert c.get(f"{api}/stills").status_code == 409

    cams.refuse = None
    assert c.post(f"{api}/preflight", json={"tiles": False}).json()["indices"] == {"a": 1, "b": 0}
    s = c.get(f"{api}/b/still?format=jpg&quality=95")
    assert s.status_code == 200 and s.content == b"\xff\xd8jpg" and s.headers["content-type"] == "image/jpeg"
    assert c.get(f"{api}/a/still").headers["content-type"] == "image/png"
    both = c.get(f"{api}/stills?format=jpg").json()
    assert both["format"] == "jpg" and set(both["cameras"]) == {"a", "b"}
    u = c.post("/api/visual-calibration/camera/uvc").json()                     # every camera's controls
    assert u["configured"] and set(u["cameras"]) == {"a", "b"} and u["set"] == {"gain": 0}


def test_a_missing_rig_dependency_is_a_503_naming_it_and_the_fix(tmp_path, monkeypatch):
    """Without OpenCV the page is told what is missing and how to get it (its module in the header
    the page shows it from once), whichever endpoint runs into it."""
    monkeypatch.setitem(sys.modules, "cv2", None)
    app = FastAPI()
    app.include_router(build_router(tmp_path, cameras=FakeCameras()))
    c = TestClient(app, raise_server_exceptions=False)
    for r in (c.get("/api/visual-calibration/rig"), c.post("/api/visual-calibration/detect", content=b"\x89PNG")):
        assert r.status_code == 503 and r.headers["x-orca-missing"] == "cv2", r.text
        assert "OpenCV" in r.json()["detail"] and "rig extra" in r.json()["detail"]


def test_the_doctor_reports_each_check_and_degrades_without_one(tmp_path, monkeypatch):
    """GET /doctor (no --research-ui): the doctor's rows as the page reads them, run off the event
    loop; with an orca_core that has no visual_calibration/doctor.py, a 404 saying so."""
    import asyncio
    import types
    seen = {}

    def run(checks=None):
        try:
            asyncio.get_running_loop()
            seen["in_loop"] = True
        except RuntimeError:
            seen["in_loop"] = False
        seen["checks"] = checks
        return [{"name": "opencv", "status": "ok", "detail": "4.13"},
                {"name": "cameras", "status": "error", "detail": "1 of 2 UVC cameras", "fix": "plug in camera B"},
                {"name": "uvcc", "status": "odd", "detail": "npx missing"}]
    monkeypatch.setitem(sys.modules, "visual_calibration.doctor", types.SimpleNamespace(run=run))
    app = FastAPI()
    app.include_router(build_router(tmp_path, cameras=FakeCameras()))
    c = TestClient(app)
    r = c.get("/api/visual-calibration/doctor?checks=cameras&checks=opencv").json()
    assert seen == {"in_loop": False, "checks": ["cameras", "opencv"]} and r["ok"] is False
    assert r["checks"][1] == {"name": "cameras", "status": "error", "detail": "1 of 2 UVC cameras",
                              "fix": "plug in camera B"}
    assert r["checks"][0]["fix"] is None and r["checks"][2]["status"] == "warn"
    monkeypatch.setitem(sys.modules, "visual_calibration.doctor", None)
    r = c.get("/api/visual-calibration/doctor")
    assert r.status_code == 404 and "doctor not available" in r.json()["detail"]
