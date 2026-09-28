"""The HTML endurance report: built on stop, rebuilt on demand, served, deleted with the test."""

import json
import os
import re
import time

import pytest
import yaml
from fastapi.testclient import TestClient

from orca_ui.hand import endurance_report as rp
from orca_ui.mock import materialize_mock_model
from orca_ui.server import create_app
from orca_ui.settings import UiSettings


def _wait_for(predicate, timeout=20.0, interval=0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


@pytest.fixture()
def client(tmp_path):
    settings = UiSettings(config_path=materialize_mock_model(), mock=True,
                          open_browser=False, library_dir=str(tmp_path))
    app = create_app(settings)
    with TestClient(app) as test_client:
        assert _wait_for(
            lambda: test_client.get("/api/status").json()["state"] == "connected")
        yield test_client


def test_report_built_on_stop_rebuilt_on_demand_and_removed_with_the_test(client):
    started = client.post("/api/endurance/tests", json={"label": "rig soak"})
    assert started.status_code == 200
    test_id = started.json()["id"]
    assert started.json()["report"] is None
    assert client.get(f"/api/endurance/tests/{test_id}/report.html").status_code == 404
    assert client.post(f"/api/endurance/tests/{test_id}/note",
                       json={"text": "swapped the thumb tendon"}).status_code == 200

    # stop → the report is built in the background and shows up on the summary
    assert client.post(f"/api/endurance/tests/{test_id}/stop").status_code == 200
    def built():
        tests = client.get("/api/endurance").json()["tests"]
        return next(t for t in tests if t["id"] == test_id)["report"]
    assert _wait_for(lambda: built() is not None), "report not built after stop"
    info = built()
    assert info["file"].startswith("endurance-rig-soak-") and info["bytes"] > 10_000
    recorder = client.app.state.telemetry.endurance_recorder()
    path = os.path.join(recorder.reports_dir(), info["file"])
    assert os.path.isfile(path) and os.path.getsize(path) == info["bytes"]

    page = client.get(f"/api/endurance/tests/{test_id}/report.html")
    assert page.status_code == 200 and page.headers["content-type"].startswith("text/html")
    match = re.search(r"const D = (\{.*?\});\n", page.text, re.DOTALL)
    assert match, "report data not embedded"
    data = json.loads(match.group(1).replace("<\\/", "</"))
    assert data["meta"]["label"] == "rig soak" and data["meta"]["id"] == test_id
    assert any(e["detail"] == "swapped the thumb tendon" for e in data["events"])
    assert data["joints"] and data["motors"]

    # rebuild on demand: same file name, newer stamp
    time.sleep(1.1)
    rebuilt = client.post(f"/api/endurance/tests/{test_id}/report")
    assert rebuilt.status_code == 200
    again = rebuilt.json()["report"]
    assert again["file"] == info["file"] and again["built_at"] > info["built_at"]
    assert client.post("/api/endurance/tests/nope/report").status_code == 404

    # deleting the test removes its report file too
    assert client.delete(f"/api/endurance/tests/{test_id}").status_code == 200
    assert not os.path.exists(path)


def test_folder_mode_builds_the_same_page_from_exported_files(tmp_path):
    config_path = materialize_mock_model()
    with open(config_path) as f:
        config = yaml.safe_load(f)
    joints = list(config["joint_ids"])[:3]
    motors = [1, 2, 3]
    test = {
        "id": "e0000000000001", "label": "export", "started_at": "2026-09-25T20:46:47+02:00",
        "ended_at": "2026-09-25T22:46:47+02:00", "t0": 0.0, "joints": joints,
        "motors": motors, "motor_joint": {str(m): j for m, j in zip(motors, joints)},
        "fingers": ["thumb", "index"], "samples": 4, "cycles_total": 2,
        "closed_cycles": 2, "bucket_s": 10.0,
        "buckets": [{"t0": 0.0, "t1": 10.0, "n": 4, "c0": 0, "c1": 2,
                     "angle": {j: [0.0, 20.0] for j in joints},
                     "current": {str(m): [100.0, 150.0] for m in motors},
                     "force": {"thumb": [0.1, 0.2], "index": [0.0, 0.0]}}],
        "runs": [], "runs_dropped": 0,
        "events": [{"t": 1.0, "cycle": 0, "leg": 0, "kind": "note", "subject": "operator",
                    "detail": "hello", "severity": "info"}],
        "events_dropped": 0, "checkpoints": [], "checkpoints_dropped": 0, "latest": None,
    }
    (tmp_path / "endurance.json").write_text(json.dumps(
        {"schema": 1, "created_at": "x", "updated_at": None, "active_id": None,
         "tests": [test], "test_seq": 1}))
    (tmp_path / "config.yaml").write_text(yaml.safe_dump(config))
    (tmp_path / "endurance-export-samples.csv").write_text(
        "t_s,run_id,cycle,cycle_total,leg," + ",".join(f"angle_deg:{j}" for j in joints)
        + ",force_n:thumb,force_n:index\n"
        + "1.0,r,1,1,0," + ",".join("0.0" for _ in joints) + ",0.1,0.0\n"
        + "2.0,r,1,1,1," + ",".join("20.0" for _ in joints) + ",0.1,0.0\n")
    out = tmp_path / "out.html"
    assert rp.main([str(tmp_path), str(out)]) == 0
    html = out.read_text()
    assert '"label":"export"' in html and '"has_csv":true' in html
    assert rp.report_filename(test) == "endurance-export-20260925.html"


def _export_folder(tmp_path, config, label="export"):
    joints = list(config["joint_ids"])[:3]
    motors = [1, 2, 3]
    test = {
        "id": "e0000000000002", "label": label, "started_at": "2026-09-25T20:46:47+02:00",
        "ended_at": "2026-09-25T22:46:47+02:00", "t0": 0.0, "joints": joints,
        "motors": motors, "motor_joint": {str(m): j for m, j in zip(motors, joints)},
        "fingers": ["thumb", "index"], "samples": 2, "cycles_total": 2,
        "closed_cycles": 2, "bucket_s": 10.0,
        "buckets": [{"t0": 0.0, "t1": 10.0, "n": 2, "c0": 0, "c1": 2,
                     "angle": {j: [0.0, 20.0] for j in joints},
                     "current": {str(m): [100.0, 150.0] for m in motors},
                     "force": {"thumb": [0.1, 0.2], "index": [0.0, 0.0]}}],
        "runs": [], "runs_dropped": 0, "events": [], "events_dropped": 0,
        "checkpoints": [], "checkpoints_dropped": 0, "latest": None,
    }
    folder = tmp_path / "download"
    folder.mkdir()
    (folder / "endurance.json").write_text(json.dumps(
        {"schema": 1, "created_at": "x", "updated_at": None, "active_id": None,
         "tests": [test], "test_seq": 7}))
    (folder / "config.yaml").write_text(yaml.safe_dump(config))
    (folder / f"endurance-{label}-samples.csv").write_text(
        "t_s,run_id,cycle,cycle_total,leg," + ",".join(f"angle_deg:{j}" for j in joints)
        + ",force_n:thumb,force_n:index\n"
        + "1.0,r,1,1,0," + ",".join("0.0" for _ in joints) + ",0.1,0.0\n"
        + "2.0,r,1,1,1," + ",".join("20.0" for _ in joints) + ",0.1,0.0\n")
    (folder / "calibration_history.jsonl").write_text(
        json.dumps({"started_at": "2026-09-25T17:12:50+02:00", "finished_at": None,
                    "problems": [], "travel_deg": {}}) + "\n")
    return folder, test


def test_import_makes_an_exported_test_a_console_test(tmp_path):
    config_path = materialize_mock_model()
    config_dir = os.path.dirname(config_path)
    with open(config_path) as f:
        config = yaml.safe_load(f)
    folder, test = _export_folder(tmp_path, config)

    first = rp.import_export(folder, config_dir)
    assert first["added"] == [test["id"]] and first["tests"] == 1
    assert os.path.exists(os.path.join(config_dir, "endurance", f"{test['id']}.csv"))
    assert os.path.exists(os.path.join(config_dir, "calibration_history.jsonl"))
    assert rp.import_export(folder, config_dir)["added"] == []  # idempotent

    settings = UiSettings(config_path=config_path, mock=True, open_browser=False,
                          library_dir=str(tmp_path))
    with TestClient(create_app(settings)) as client:
        assert _wait_for(lambda: client.get("/api/status").json()["state"] == "connected")
        tests = client.get("/api/endurance").json()["tests"]
        assert [t["id"] for t in tests] == [test["id"]]
        assert tests[0]["report"]["file"] == "endurance-export-20260925.html"
        page = client.get(f"/api/endurance/tests/{test['id']}/report.html")
        assert page.status_code == 200 and '"label":"export"' in page.text
        # the console can rebuild it from the imported samples
        rebuilt = client.post(f"/api/endurance/tests/{test['id']}/report").json()["report"]
        assert rebuilt["file"] == "endurance-export-20260925.html"
        assert '"has_csv":true' in client.get(
            f"/api/endurance/tests/{test['id']}/report.html").text


def test_endurance_snapshot_lists_who_is_watching(client):
    assert client.get("/api/endurance").json()["watchers"] == []
    headers = {"X-Endurance-Watcher": "endurance-slack", "X-Endurance-Poll": "900"}
    (bot,) = client.get("/api/endurance", headers=headers).json()["watchers"]
    assert bot["name"] == "endurance-slack" and bot["poll_s"] == 900 and bot["live"]
    assert bot["ago_s"] == 0
    # anonymous callers do not register, but still see the watcher list
    (again,) = client.get("/api/endurance").json()["watchers"]
    assert again["name"] == "endurance-slack"
