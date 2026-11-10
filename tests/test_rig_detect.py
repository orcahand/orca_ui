"""The calibration rig: found by serial / identity / one rig motor, never the hand's board;
the dashboard's rig API under --mock; the hand and the plate never move together."""
from types import SimpleNamespace

import pytest

from orca_ui.hand import boards
from orca_ui.hand.rig_detect import KNOWN_RIG_SERIALS, check_model, classify, rig_serials
from orca_ui.hand.service import HandService, ServiceError
from orca_ui.mock import materialize_mock_model
from orca_ui.settings import UiSettings

RIG = next(iter(KNOWN_RIG_SERIALS))


def info(serial=None, config=None, role="motor"):
    return SimpleNamespace(serial=serial, config=config, role=role)


def test_classify():
    v = classify(RIG, info("ser-3526"))
    assert v.rig and "serial" in v.reason and "ser-3526" in v.warnings[0]     # today's board claims a hand
    assert classify("other", info("rig-1")).rig and classify("other", info("x", "RIG")).rig
    assert classify("other", info("ser-4485")).rig is False
    assert classify("other", None, [{"id": 1, "model_name": "XC330-T288-T"}]).rig
    assert classify("other", None, [{"id": 1, "model_name": "XC430-T240BB-T"}]).rig
    assert not classify("other", None, [{"id": 1, "model_name": "XL330-M288-T"}]).rig
    assert not classify("other", None, [{"id": i, "model_name": "XC330-T288-T"} for i in range(17)]).rig
    assert not classify(None, None, []).rig
    assert "pinned" in rig_serials({"board": {"usb_serial": "pinned"}}, None)


def test_check_model():
    assert check_model("XC330-T288-T", "auto") == []
    assert check_model("XC430-T240BB-T", "XC430-T240BB-T") == []
    assert "control table" in check_model("XC330-T288-T", "XC430-T240BB-T")[0]
    assert "not a known rig model" in check_model("XM430-W350", None)[0]


def test_a_rig_board_is_never_a_hand(monkeypatch):
    monkeypatch.setattr(boards, "_usb_serials", lambda: {"/dev/rig": RIG, "/dev/hand": "HANDSERIAL"})
    monkeypatch.setattr(boards, "_rig_yaml", lambda: [])
    assert boards.is_rig_board("/dev/rig") and boards.is_rig_board("/dev/hand") is None
    assert boards.detect_pinned_board("/dev/rig") is None
    e = boards._with_role(boards.BoardEntry("/dev/rig", "oh_board", None, None, "ser-3526", None, None,
                                            ("/dev/rig",), False), info("ser-3526"))
    assert e.role == "rig" and e.as_dict()["role"] == "rig"

    svc = HandService(UiSettings(config_path=materialize_mock_model(), mock=True, open_browser=False),
                      publish_status=lambda s: None, publish_error=lambda e: None)
    with pytest.raises(ServiceError) as exc:
        svc.select_board("/dev/rig")
    assert exc.value.status_code == 409 and "rig" in str(exc.value)


def test_hand_waits_for_the_plate_and_the_plate_for_the_hand():
    svc = HandService(UiSettings(config_path=materialize_mock_model(), mock=True, open_browser=False),
                      publish_status=lambda s: None, publish_error=lambda e: None)
    assert svc.hand_motion_blocker() is None
    svc._note_motion(5.0)
    assert "moving" in svc.hand_motion_blocker()
    svc.plate_motion_guard = lambda: "the rig's plate is turning"
    with pytest.raises(ServiceError) as exc:
        svc._refuse_while_plate_moves()
    assert exc.value.status_code == 409


cv2 = pytest.importorskip("cv2")


def test_rig_presence_park_tiles_and_interlock(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from orca_ui.api.visual_calibration import EXPERIMENT, build_router
    if not (EXPERIMENT / "visual_calibration").is_dir():
        pytest.skip("no visual calibration experiment")
    router = build_router(tmp_path, mock=True)
    app = FastAPI()
    app.include_router(router)
    c = TestClient(app)
    base = "/api/visual-calibration"
    assert c.get(f"{base}/rig/presence").json()["connected"] is False
    monkeypatch.delenv("ORCA_MOCK_RIG", raising=False)
    assert router.start_rig_watcher() is False                     # mock: only with ORCA_MOCK_RIG=1
    p = c.post(f"{base}/rig/scan").json()
    assert p["connected"] and p["model"] == "mock" and p["turntable"]["connected"]

    blocker = {"why": None}
    router.attach_hand(lambda: set(), lambda: blocker["why"])
    c.post(f"{base}/turntable/home")
    blocker["why"] = "the hand is moving"
    r = c.post(f"{base}/turntable/move", json={"angle": 30})
    assert r.status_code == 409 and "hand" in r.json()["detail"]
    assert c.post(f"{base}/turntable/torque-off").status_code == 200   # never blocked
    blocker["why"] = None
    seen = []
    import visual_calibration.turntable as T
    move = T.Turntable.move
    monkeypatch.setattr(T.Turntable, "move", lambda self, *a, **k: (seen.append(router.plate_motion_guard()),
                                                                     move(self, *a, **k))[1])
    st = c.post(f"{base}/turntable/park").json()
    swap = c.get(f"{base}/rig").json()["swap_angle"]
    assert abs(st["angle"] - swap) < 0.2 and st["torque"] is False
    assert seen and "plate" in seen[0] and router.plate_motion_guard() is None

    tw = c.get(f"{base}/twin/state").json()
    assert len(tw["hand"]["rig_from_hand"]) == 4 and tw["swap_angle"] == swap
    png = c.get(f"{base}/twin/tiles/tile_r1_s0.png")
    assert png.status_code == 200 and png.content[:4] == b"\x89PNG"
    assert c.get(f"{base}/twin/tiles/nope.png").status_code == 404
