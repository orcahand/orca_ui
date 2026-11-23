"""Measure joint ranges: the rig's hand run as the console's child process (orca_ui.hand.hand_run),
over the mock hand and the mock rig. E-STOP must kill the whole run, not only its first process."""

import os
import socket
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orca_ui.api.visual_calibration import EXPERIMENT, _experiment_on_path
from orca_ui.mock import materialize_mock_model
from orca_ui.server import create_app
from orca_ui.settings import UiSettings

if not (EXPERIMENT / "hand_study" / "run_hand.py").is_file():
    pytest.skip(f"no hand study at {EXPERIMENT}", allow_module_level=True)

VC = "/api/visual-calibration"


def _wait_for(predicate, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


def _free_port() -> int:
    """A port nothing listens on: the run must never reach a console other than this test's."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("ORCA_RIG_AUTODETECT", "0")
    monkeypatch.setenv("ORCA_FIRMWARE_REPO", str(tmp_path / "no-firmware"))
    settings = UiSettings(config_path=materialize_mock_model(), mock=True, open_browser=False, port=_free_port())
    with TestClient(create_app(settings)) as c:
        assert _wait_for(lambda: c.get("/api/status").json()["state"] == "connected")
        yield c


def _hand_on_file(client) -> str:
    """The mock hand's folder in the run's hand store (orca_core keeps mock hands elsewhere)."""
    from orca_core import hand_store
    hand_id = client.get("/api/hand/info").json()["hand"]["id"]
    folder = hand_store.hand_dir(hand_id)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "hand.yaml").write_text(f"schema: 1\nid: {hand_id}\nmodel: orcahand-right\n")
    return hand_id


def test_measure_builds_the_run_for_the_connected_hand(client):
    """run_hand --dry through the console: the plate must be connected and both cameras proven first;
    the run is planned over the hand's ranges and lists its steps, nothing moves. No firmware
    checkout: no board write offered or accepted."""
    _experiment_on_path()
    from visual_calibration.hand_model import description_root
    if description_root() is None:
        pytest.skip("the run plans need orcahand_description (ORCAHAND_DESCRIPTION)")
    hand_id = _hand_on_file(client)
    assert client.get(f"{VC}/hand-run").json()["state"] == "idle"
    assert client.post(f"{VC}/hand-run/start", json={"dry": True}).status_code == 409      # no plate
    assert client.post(f"{VC}/turntable/connect", json={}).json()["mock"] is True
    started = client.post(f"{VC}/hand-run/start", json={"dry": True, "limit": 2}).json()
    assert started["state"] == "running" and started["hand"] == hand_id
    assert _wait_for(lambda: client.get(f"{VC}/hand-run").json()["state"] != "running", timeout=60)
    run = client.get(f"{VC}/hand-run").json()
    assert run["state"] == "ended", run["log_tail"]
    steps = [s["name"] for s in run["progress"]["steps"]]
    assert steps[:2] == ["preflight", "snapshot"] and steps[-3:] == ["N08-V", "ranges", "accuracy"]
    assert all(s["state"] == "todo" for s in run["progress"]["steps"]) and run["progress"]["eta_s"] > 0
    assert f"/runs/{hand_id}/" in run["run"] and run["run"].startswith(os.environ["ORCA_HOME"])
    assert client.get(f"{VC}/hand-run/results").json() == {"hand": hand_id, "results": None}
    assert client.get(f"{VC}/hand-run/photo/b.jpg").status_code == 404
    pose = next(Path(run["run"]).glob("sessions/*-N00-baseline")) / "configs" / "zero"
    pose.mkdir(parents=True)
    (pose / "v180_b.jpg").write_bytes(b"\xff\xd8 a photo")
    assert client.get(f"{VC}/hand-run").json()["progress"]["photos"] == {"b": str((pose / "v180_b.jpg").relative_to(run["run"]))}
    assert client.get(f"{VC}/hand-run/photo/b.jpg").content == b"\xff\xd8 a photo"

    writer = client.get(f"{VC}/board-write").json()
    assert writer["available"] is False and "orca_firmware" in writer["reason"]
    assert client.post("/api/operation/board_write/start", json={"params": {}}).status_code == 409


def test_estop_kills_the_whole_hand_run_and_operations_wait_for_it(client, tmp_path):
    from orca_core import hand_store
    hand_run = client.app.state.visual.hand_run
    child = tmp_path / "child.pid"
    script = ("import os, subprocess, sys, time; "
              "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
              f"open({str(child)!r}, 'w').write(' '.join([str(p.pid), os.environ['ORCA_HOME'], os.environ['ORCA_UI']])); "
              "time.sleep(60)")
    hand_run.start("ser-0001", command=[sys.executable, "-c", script])
    assert _wait_for(lambda: child.exists() and child.read_text())
    pid, orca_home, ui = child.read_text().split()
    grandchild = int(pid)
    # The run's environment: this ORCA_HOME, absolute (hand_study.run_hand.run_env), and this console.
    assert orca_home == str(hand_store.orca_home()) and os.path.isabs(orca_home)
    assert ui == f"http://127.0.0.1:{client.app.state.settings.port}"
    assert client.post(f"{VC}/hand-run/start", json={"dry": True}).status_code == 409
    # The run drives the hand: no operation may take it meanwhile.
    r = client.post("/api/operation/calibrate/start", json={"params": {}})
    assert r.status_code == 409 and "hand run" in r.json()["detail"]

    report = client.post("/api/estop").json()["report"]
    assert report["hand_run_stopped"] is True and report["torque_disabled"] is True
    assert not hand_run.alive()
    run = client.get(f"{VC}/hand-run").json()
    assert (run["state"], run["stopped"]) == ("stopped", "e-stop")

    def gone(pid):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        return False
    assert _wait_for(lambda: gone(grandchild), timeout=5)


def test_write_to_board_releases_the_port_writes_and_reads_back(client, monkeypatch, tmp_path):
    """With a firmware checkout: the hand lets go of its port, orca_core packs and writes, the board is
    read back, the hand reconnects. A refused push comes back with orca_core's reason."""
    from orca_core import board_push, hand_store
    from orca_core.board_store import BoardIdentity
    hand = client.app.state.service.session.hand
    monkeypatch.setattr(type(hand), "board_hand_id", property(lambda self: "ser-0001"))
    monkeypatch.setattr(board_push, "firmware_tool", lambda: tmp_path / "cal_store.py")
    hand_store.write_joint_ranges(hand.hand_dir, {"index_mcp": [-12.0, 95.5]}, source="camera rig")
    states = []

    def push(h):
        states.append(client.get("/api/status").json()["state"])
        return board_push.PushResult(False, "the joint ranges on the board were measured later")
    monkeypatch.setattr(board_push, "push_for_hand", push)

    def write() -> dict:
        assert client.post("/api/operation/board_write/start", json={"params": {}}).status_code == 200
        assert _wait_for(lambda: client.get("/api/operation").json()["operation"]["state"] in ("done", "error"))
        return client.get("/api/operation").json()["operation"]

    assert client.get(f"{VC}/board-write").json()["available"] is True
    op = write()
    assert op["result"]["written"] is False and "measured later" in op["result"]["reason"]
    assert states == ["maintenance"]
    assert _wait_for(lambda: client.get("/api/status").json()["state"] == "connected")

    monkeypatch.setattr(board_push, "push_for_hand", lambda h: board_push.PushResult(True, sequence=4, size=300))
    held = board_push.BoardContents(BoardIdentity(side="right", hw_version=2, config=1, serial="ser-0001"), 4,
                                    {"measured_at": "2026-11-23T20:00:00", "joint_roms": {"index_mcp": [-12.0, 95.5]}})
    monkeypatch.setattr(board_push, "board_contents", lambda port: held)
    op = write()
    assert op["result"]["written"] and op["result"]["confirmed"]
    assert op["result"]["board"]["ranges"] == ["index_mcp"] and op["result"]["board"]["sequence"] == 4
    assert _wait_for(lambda: client.get("/api/status").json()["state"] == "connected")
