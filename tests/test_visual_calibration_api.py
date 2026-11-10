import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

cv2 = pytest.importorskip("cv2")

from orca_ui.api.visual_calibration import EXPERIMENT, build_router

if not (EXPERIMENT / "visual_calibration").is_dir():
    pytest.skip(f"no visual calibration experiment at {EXPERIMENT}", allow_module_level=True)


def client_for(path, mock=False):
    app = FastAPI()
    app.include_router(build_router(path, mock=mock))
    return TestClient(app)


def tile_png(first_marker=0):
    """One rendered tile (tile_r0_s0's markers) on a white page, PNG bytes."""
    board = cv2.aruco.CharucoBoard((5, 5), 14.0, 10.5, cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_250),
                                   np.arange(first_marker, first_marker + 12))
    page = np.full((1000, 1400), 255, np.uint8)
    page[150:850, 350:1050] = board.generateImage((700, 700), marginSize=0)
    return cv2.imencode(".png", page)[1].tobytes()


def test_session_photo_detect_and_solve_errors(tmp_path):
    c = client_for(tmp_path)
    rig = c.get("/api/visual-calibration/rig").json()
    assert rig["stops"][0] == 0 and "tile_r0_s0" in rig["tiles"]
    assert rig["mountings"] == [0.0, 90.0, 180.0, 270.0] and rig["coverage_warnings"] == []
    assert 0 < rig["swap_angle"] < rig["travel"] and rig["rig_board"]["usb_serial"]

    sid = c.post("/api/visual-calibration/sessions", json={"step": "camera"}).json()["id"]
    r = c.post(f"/api/visual-calibration/sessions/{sid}/photos?stop=0", content=tile_png()).json()
    assert r["photo"]["corners"] == 16 and r["detections"][0]["tile"] == "tile_r0_s0" and r["size"] == [1400, 1000]
    assert c.get(f"/api/visual-calibration/sessions/{sid}").json()["photos"][0]["stop_deg"] == 0
    assert c.get("/api/visual-calibration/sessions").json()[0]["photos"] == 1

    live = c.post("/api/visual-calibration/detect", content=tile_png()).json()
    assert len(live["detections"]) == 1 and len(live["detections"][0]["uv"]) == 16

    assert c.post(f"/api/visual-calibration/sessions/{sid}/solve").status_code == 400     # one photo is not enough
    assert c.post(f"/api/visual-calibration/sessions/{sid}/apply").status_code == 400     # nothing solved
    assert c.post(f"/api/visual-calibration/sessions/{sid}/photos?stop=15", content=b"").status_code == 400
    assert c.get("/api/visual-calibration/sessions/nope").status_code == 404


def test_turntable_mock_home_and_move(tmp_path):
    c = client_for(tmp_path, mock=True)
    assert c.get("/api/visual-calibration/turntable").json()["connected"] is False
    assert c.post("/api/visual-calibration/turntable/home").status_code == 409            # not connected
    assert c.post("/api/visual-calibration/turntable/connect", json={}).json()["mock"] is True
    assert c.post("/api/visual-calibration/turntable/move", json={"angle": 30}).status_code == 409   # not homed
    assert c.post("/api/visual-calibration/turntable/home").json()["homed"] is True
    assert abs(c.post("/api/visual-calibration/turntable/move", json={"angle": 45}).json()["angle"] - 45) < 0.1
    cal = c.post("/api/visual-calibration/turntable/calibrate").json()
    assert cal["zero_from"] == "calibration" and abs(cal["calibration"]["travel_deg"] - 320) < 1
    off = c.post("/api/visual-calibration/turntable/torque-off").json()
    assert off["connected"] and not off["torque"] and off["angle"] is not None          # free, still read
    assert c.post("/api/visual-calibration/turntable/release").json()["connected"] is False


def test_overlay_before_calibration(tmp_path, monkeypatch):
    c = client_for(tmp_path)
    c.get("/api/visual-calibration/rig")                                           # puts the experiment on sys.path
    from visual_calibration.rig_config import RigConfig
    monkeypatch.setattr(RigConfig, "load_calibration", lambda self: {})          # the real rig may be calibrated
    o = c.get("/api/visual-calibration/overlay?angle=180&rotation=90").json()
    assert o["source"]["camera"] == "nominal" and len(o["camera_from_plate"]) == 4
    assert any(t["facing"] and t["tile"] == "tile_r1_s0" for t in o["tiles"])


def test_status_twin_and_orientation(tmp_path, monkeypatch):
    c = client_for(tmp_path, mock=True)
    assert c.post("/api/visual-calibration/camera/uvc").json()["ok"] is True       # no camera to set in mock mode
    s = c.get("/api/visual-calibration/status").json()
    assert [x["id"] for x in s["steps"]] == ["motor", "camera", "rotation", "hand"] and s["turntable"]["connected"] is False

    live = c.post("/api/visual-calibration/detect", content=tile_png()).json()
    assert live["orientation"]["rotation"] == 0
    turned = cv2.imencode(".png", np.rot90(cv2.imdecode(np.frombuffer(tile_png(), np.uint8), 0)))[1].tobytes()
    assert c.post("/api/visual-calibration/detect", content=turned).json()["orientation"]["rotation"] == 90

    assert c.get("/api/visual-calibration/twin/state").json()["angle_source"] == "none"
    c.post("/api/visual-calibration/turntable/connect", json={})
    c.post("/api/visual-calibration/turntable/home")
    c.post("/api/visual-calibration/turntable/move", json={"angle": 45})
    st = c.get("/api/visual-calibration/twin/state").json()
    assert st["angle_source"] == "turntable" and abs(st["angle"] - 45) < 0.2 and len(st["groups"]["rotor"]) == 4
    assert c.get("/api/visual-calibration/twin/state?angle=90").json()["angle"] == 90

    twin = tmp_path / "twin"
    twin.mkdir()
    (twin / "twin.json").write_text('{"groups": {"rotor": "Rz"}}')
    (twin / "rig_plate.glb").write_bytes(b"glTF")
    monkeypatch.setenv("ORCA_RIG_TWIN", str(twin))
    t = c.get("/api/visual-calibration/twin").json()
    assert t["groups"]["rotor"] == "Rz" and t["files"] == ["rig_plate.glb"]
    assert c.get("/api/visual-calibration/twin/files/rig_plate.glb").content == b"glTF"
    assert c.get("/api/visual-calibration/twin/files/..%2Fsecret.glb").status_code == 404
    monkeypatch.setenv("ORCA_RIG_TWIN", str(tmp_path / "nothing"))
    assert c.get("/api/visual-calibration/twin").status_code == 404


def test_photos_take_the_turntables_read_back_angle(tmp_path):
    c = client_for(tmp_path, mock=True)
    sid = c.post("/api/visual-calibration/sessions", json={"step": "camera"}).json()["id"]
    c.post("/api/visual-calibration/turntable/connect", json={})
    c.post("/api/visual-calibration/turntable/home")
    at = c.post("/api/visual-calibration/turntable/move", json={"angle": 15}).json()["angle"]
    r = c.post(f"/api/visual-calibration/sessions/{sid}/photos?stop=15", content=tile_png()).json()
    assert r["photo"]["stop_deg"] == 15 and abs(r["photo"]["plate_deg"] - at) < 0.01
    assert c.post(f"/api/visual-calibration/sessions/{sid}/photos?stop=90", content=tile_png()).status_code == 409
    r = c.post(f"/api/visual-calibration/sessions/{sid}/photos?stop=30&plate=30.2", content=tile_png()).json()
    assert r["photo"]["plate_deg"] == 30.2


def test_live_hand_fit_debug(tmp_path):
    c = client_for(tmp_path, mock=True)
    assert c.post("/api/visual-calibration/live-fit/freeze").status_code == 409                # nothing yet
    frame = cv2.imencode(".jpg", np.full((540, 960), 90, np.uint8))[1].tobytes()
    r = c.post("/api/visual-calibration/live-fit/frame?angle=180&source=zeros&iters=1", content=frame)
    if r.status_code == 500 and "orcahand_description" in r.text:
        pytest.skip("orcahand_description checkout not found")
    r = r.json()
    assert set(r["delta"]) == {"rotation_deg", "translation_mm"} and r["outlines"]["cad"] and r["joints_source"] == "zeros"
    assert c.post("/api/visual-calibration/live-fit/freeze").json()["path"].startswith(str(tmp_path))
    # camera only: the joints too, a kept view, and what the fit sees
    r = c.post("/api/visual-calibration/live-fit/frame?angle=180&iters=1&solve_joints=true&search=true", content=frame).json()
    assert r["joints_source"] == "camera" and len(r["joint_table"]) == 17 and r["segmentation"]["png"]
    assert c.post("/api/visual-calibration/live-fit/keep-view").json() == {"views": 1}
    assert c.post("/api/visual-calibration/live-fit/clear-views").json() == {"views": 0}


def test_the_turntable_torque_is_off_whenever_it_stops(tmp_path, monkeypatch):
    from orca_ui.api import visual_calibration as vc
    monkeypatch.setattr(vc, "HOLD_LEASE_S", 0.5)
    router = build_router(tmp_path, mock=True)
    app = FastAPI()
    app.include_router(router)
    c = TestClient(app)
    api = "/api/visual-calibration/turntable"
    assert not c.post(f"{api}/connect", json={}).json()["torque"]
    assert not c.post(f"{api}/home", json={}).json()["torque"]
    assert not c.post(f"{api}/move", json={"angle": 30}).json()["torque"]
    assert c.post(f"{api}/move", json={"angle": 45, "hold": True}).json()["torque"]          # a sweep's stop
    assert not c.post(f"{api}/torque-off").json()["torque"]                                  # the sweep's end
    assert c.post(f"{api}/move", json={"angle": 60, "hold": True}).json()["torque"]
    import time
    time.sleep(2.5)                                                     # no next move: the page went away
    assert not c.get(api).json()["torque"]
    c.post(f"{api}/move", json={"angle": 70, "hold": True})
    assert router.release_turntable() and not c.get(api).json()["torque"]                   # E-STOP


def test_lookup_table_command(tmp_path, monkeypatch):
    import json
    import sys
    sys.path.insert(0, str(EXPERIMENT))
    from hand_study import lut as L
    from hand_study.configs import JOINTS, ROM
    monkeypatch.setattr(L, "STUDY", tmp_path)
    c = client_for(tmp_path / "vc")
    assert c.get("/api/visual-calibration/lut").json()["available"] is False
    assert c.post("/api/visual-calibration/lut/command", json={"angles": {"index_mcp": 10}}).status_code == 409
    rng = np.random.default_rng(0)
    C = {j: rng.uniform(*ROM[j], 80) for j in JOINTS}
    tables = {}
    for j in JOINTS:
        t = L.JointTable(j, [])
        t.fit(C, 0.9 * C[j] + 2.0)
        tables[j] = t
    (tmp_path / "lut_model.json").write_text(json.dumps(L.Lut(tables).to_json()))
    assert c.get("/api/visual-calibration/lut").json()["available"] is True
    r = c.post("/api/visual-calibration/lut/command", json={"angles": {"index_mcp": 20.0}}).json()
    assert abs(r["command"]["index_mcp"] - (20.0 - 2.0) / 0.9) < 0.5
    assert abs(r["reached"]["index_mcp"] - 20.0) < 0.3
    r = c.post("/api/visual-calibration/lut/command", json={"angles": {"index_mcp": 40.0}, "use_lut": False}).json()
    assert r["command"]["index_mcp"] == 40.0 and abs(r["reached"]["index_mcp"] - 38.0) < 0.3
