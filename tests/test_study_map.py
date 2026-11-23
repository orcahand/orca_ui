import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from orca_ui import research
from orca_ui.hand.study_map import StudyMap


@pytest.fixture(autouse=True)
def _research_ui(monkeypatch):
    """The maps themselves are tested as the research console runs them (--research-ui)."""
    monkeypatch.setattr(research, "_enabled", True)


def _map(tmp_path):
    p = tmp_path / "joint_map.json"
    p.write_text(json.dumps({"joints": {
        "index_abd": {"applied": True, "cmd_knots": [-30, 0, 30], "cmd_true": [-22, 1, 21]},
        "thumb_dip": {"applied": False, "cmd_knots": [0, 90], "cmd_true": [5, 80]},
    }}))
    return StudyMap(p)


def test_off_by_default_is_identity(tmp_path):
    m = _map(tmp_path)
    assert not m.enabled
    assert m.command({"index_abd": 10.0}) == {"index_abd": 10.0}


def test_inverse_clamp_and_unapplied(tmp_path):
    m = _map(tmp_path)
    m.set_enabled(True)
    out = m.command({"index_abd": 1.0, "thumb_dip": 40.0, "wrist": 3.0})
    assert abs(out["index_abd"]) < 1e-9
    assert out["thumb_dip"] == 40.0 and out["wrist"] == 3.0
    assert m.command({"index_abd": 28.0})["index_abd"] == 30.0


def test_cannot_enable_without_map(tmp_path):
    m = StudyMap(tmp_path / "missing.json")
    try:
        m.set_enabled(True)
        raise AssertionError
    except ValueError:
        pass
    assert m.state()["available"] is False


def _hand_maps(tmp_path):
    root = tmp_path / "maps"
    (root / "ser-7577").mkdir(parents=True)
    joint = {"applied": True, "cmd_knots": [-10, 0, 100], "cmd_true": [-8, 2, 95], "assumed_knots": [-10, 0, 100],
             "assumed_true": [-8, 2, 95], "reach": [-8, 95]}
    (root / "ser-7577" / "curve.json").write_text(json.dumps({"joints": {"index_mcp": joint}}))
    own = [-10.0, 45.0, 100.0]
    coupled = {"joints": {"index_mcp": joint, "index_pip": {**joint}},
               "coupled": {"own": {"index_mcp": own, "index_pip": own}, "pk": {"index_mcp": own, "index_pip": own},
                           "parts": {"index_mcp": ["index_pip"], "index_pip": []},
                           "w": {"index_mcp": [2, 2, -5, 0, 5, 10], "index_pip": [2, 2, -5]}}}
    (root / "ser-7577" / "lut.json").write_text(json.dumps(coupled))
    m = StudyMap(tmp_path / "joint_map.json", root)
    m.hand_source = lambda: "ser-7577"
    return m


def test_maps_are_per_hand(tmp_path):
    m = _hand_maps(tmp_path)
    assert [o["name"] for o in m.state()["options"]] == ["curve", "lut"]
    m.hand_source = lambda: "ser-9999"
    assert not m.state()["available"]


def test_coupled_inverse_reaches_the_goal(tmp_path):
    m = _hand_maps(tmp_path)
    m.set_mode("lut")
    cmd = m.command({"index_mcp": 50.0}, {"index_pip": 80.0})
    got = m._forward_coupled(m.data("lut"), cmd)
    assert abs(got["index_mcp"] - 50.0) < 0.1 and abs(got["index_pip"] - 80.0) < 0.1


def test_advanced_inverse_reaches_the_goal_from_either_side(tmp_path):
    root = tmp_path / "maps"
    (root / "ser-7577").mkdir(parents=True)
    joint = {"applied": True, "cmd_knots": [-20, 100], "cmd_true": [-20, 100], "assumed_knots": [-20, 100],
             "assumed_true": [-20, 100], "reach": [-20, 100]}
    adv = {"rom": {"wrist": [-50, 40], "index_mcp": [-20, 100]}, "parts": {"wrist": [], "index_mcp": ["wrist"]},
           "a": {"wrist": [1.0, 0.5, 0, 0], "index_mcp": [-1.0, 2.0, 1.0, -0.5]},
           "c": {"wrist": [], "index_mcp": [-0.1]}, "k_per_a": {"wrist": 0.0, "index_mcp": -2.0},
           "beta": {"wrist": 0.0, "index_mcp": -1.5}, "u_clip": 1.1}
    (root / "ser-7577" / "advanced.json").write_text(json.dumps(
        {"joints": {"wrist": {**joint, "reach": [-50, 40]}, "index_mcp": joint}, "advanced": adv}))
    m = StudyMap(tmp_path / "joint_map.json", root)
    m.hand_source = lambda: "ser-7577"
    m.set_mode("advanced")
    up = m.command({"index_mcp": 40.0, "wrist": 20.0}, {"index_mcp": 0.0, "wrist": 0.0})
    got = StudyMap._forward_advanced(m.data(), up, {"index_mcp": 1.0, "wrist": 1.0})
    assert abs(got["index_mcp"] - 40.0) < 0.05 and abs(got["wrist"] - 20.0) < 0.05
    down = m.command({"index_mcp": 40.0}, {"index_mcp": 60.0, "wrist": 20.0})
    assert m._dir["index_mcp"] == -1.0
    back = StudyMap._forward_advanced(m.data(), down, {"index_mcp": -1.0, "wrist": 1.0})
    assert abs(back["index_mcp"] - 40.0) < 0.05
    assert 2.0 < up["index_mcp"] - down["index_mcp"] < 4.0          # about the play, 2 |beta|


def test_without_research_ui_no_map_is_ever_applied(tmp_path, monkeypatch):
    # A map rewrites every joint target before orca_core: an assembler's console must never apply one,
    # not even a selection stored by an earlier research run.
    m = _hand_maps(tmp_path)
    m.set_mode("curve")
    monkeypatch.setattr(research, "_enabled", False)
    assert m.mode == "off" and not m.enabled
    assert m.command({"index_mcp": 50.0}) == {"index_mcp": 50.0}
    assert m.estimate({"index_mcp": 50.0}) == {"index_mcp": 50.0}
    with pytest.raises(ValueError):
        m.set_mode("lut")
    with pytest.raises(ValueError):
        m.set_enabled(True)
    monkeypatch.setattr(research, "_enabled", True)
    assert m.mode == "curve"                                     # kept for when it is switched back on


def test_without_research_ui_the_research_endpoints_answer_404(monkeypatch):
    from orca_ui.api.visual_calibration import build_router
    from orca_ui.cli import parse_args
    from orca_ui.hand import study_map

    app = FastAPI()
    app.include_router(build_router())
    c = TestClient(app)
    research.configure(parse_args([]).research_ui)                # off unless asked for
    monkeypatch.setattr(study_map.STUDY_MAP, "set_mode", lambda mode: pytest.fail("selection reached the map"))
    api = "/api/visual-calibration"
    assert c.post(f"{api}/study-map", json={"mode": "curve"}).status_code == 404
    assert c.post(f"{api}/study-map", json={"enabled": True}).status_code == 404
    assert c.get(f"{api}/study-map").status_code == 404
    assert c.post(f"{api}/lut/command", json={"angles": {"index_mcp": 10}}).status_code == 404
    assert c.get(f"{api}/study/protocols").status_code == 404
