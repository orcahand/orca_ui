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


def _console() -> TestClient:
    settings = UiSettings(config_path=materialize_mock_model(), mock=True, open_browser=False, port=_free_port())
    return TestClient(create_app(settings))


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("ORCA_RIG_AUTODETECT", "0")
    monkeypatch.setenv("ORCA_FIRMWARE_REPO", str(tmp_path / "no-firmware"))
    with _console() as c:
        assert _wait_for(lambda: c.get("/api/status").json()["state"] == "connected")
        yield c


def _gone(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


SLEEPER = [sys.executable, "-c", "import time; time.sleep(60)", "hand_study"]   # a run that never ends


def _fake_run(tmp_path, name: str, state: dict | None, fit: dict | None, exit_code: int = 0, say: str = "") -> list:
    """A command standing in for run_hand: announces a run folder holding `state` and `fit`, then exits."""
    import json
    run = tmp_path / name
    (run / "night").mkdir(parents=True)
    (run / "night" / "t.json").write_text(json.dumps({"tag": "t", "steps": [
        {"name": "preflight", "kind": "preflight", "minutes": 1}, {"name": "N07-short", "kind": "ranges", "minutes": 1}]}))
    if state is not None:
        (run / "night" / "t.state.json").write_text(json.dumps(state))
    if fit is not None:
        (run / "proposed").mkdir()
        (run / "proposed" / "hardstops.json").write_text(json.dumps(fit))
    return [sys.executable, "-c", f"import sys; print('run {run}'); print({say!r}); sys.exit({exit_code})"]


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
    assert client.get(f"{VC}/hand-run/results").json() == {"hand": hand_id, "latest": run["run"], "results": None}
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
    assert op["result"]["written"] and op["result"]["confirmed"] and op["result"]["hand"] == hand.hand_id
    assert op["result"]["board"]["ranges"] == ["index_mcp"] and op["result"]["board"]["sequence"] == 4
    assert _wait_for(lambda: client.get("/api/status").json()["state"] == "connected")


def test_a_run_is_done_only_when_it_recorded_the_ranges(client, tmp_path, monkeypatch):
    """Done: the night finished and this run's fit recorded the ranges; then the hand reconnects so
    they are in force. Anything else is failed, with why, and the hand stays as it is."""
    hand_run = client.app.state.visual.hand_run
    reconnects = []
    monkeypatch.setattr(client.app.state.service, "reconnect", lambda: reconnects.append(1))

    def ended(command) -> dict:
        hand_run.start("ser-0001", command=command)
        assert _wait_for(lambda: client.get(f"{VC}/hand-run").json()["state"] != "running")
        assert _wait_for(lambda: not hand_run.alive())
        return client.get(f"{VC}/hand-run").json()

    record = {"stops": {}, "joint_ranges": {"path": "/h/joint_ranges.yaml", "recorded": ["wrist"], "rejected": {},
                                            "gone": []}}
    done = ended(_fake_run(tmp_path, "done", {"state": "done", "done": {}}, record))
    assert (done["state"], done["reason"]) == ("done", None)
    assert _wait_for(lambda: reconnects == [1])
    nothing = {"stops": {}, "joint_ranges": {"path": None, "recorded": [], "rejected": {}, "gone": []}}
    none_measured = ended(_fake_run(tmp_path, "none", {"state": "done", "done": {}}, nothing, 1))
    assert none_measured["state"] == "failed" and "without recording" in none_measured["reason"]
    # The ranges recorded, then the accuracy check died: failed, and it says the ranges are on file.
    late = ended(_fake_run(tmp_path, "late", {"state": "aborted", "done": {}, "error": "Abort('a solve worker died')"},
                           record, 1))
    assert late["state"] == "failed" and late["progress"]["recorded"] and "worker died" in late["reason"]
    cut = ended(_fake_run(tmp_path, "cut", {"state": "done", "done": {}, "cut_short": "N07-short"}, None, 1))
    assert cut["state"] == "failed" and cut["reason"] == "the run reached its deadline before N07-short"
    unrecorded = ended(_fake_run(tmp_path, "unrecorded", {"state": "done", "done": {}}, {"stops": {}}, 1))
    assert unrecorded["state"] == "failed" and "without recording" in unrecorded["reason"]
    died = ended(_fake_run(tmp_path, "died", None, None, 3, say="ImportError: no torch"))
    assert (died["state"], died["reason"]) == ("failed", "ImportError: no torch")
    assert reconnects == [1]


def test_stop_ends_the_run_and_the_rig_steps_wait_for_it(client):
    hand_run = client.app.state.visual.hand_run
    hand_run.start("ser-0001", command=SLEEPER)
    pid = hand_run.status()["pid"]
    for path in ("/sessions", "/turntable/park", "/turntable/calibrate", "/live-fit/reset"):
        r = client.post(VC + path, json={})
        assert r.status_code == 409 and "hand run is measuring" in r.json()["detail"], path
    run = client.post(f"{VC}/hand-run/stop").json()
    assert (run["state"], run["stopped"]) == ("stopped", "stopped") and _wait_for(lambda: _gone(pid))
    assert client.post(f"{VC}/sessions", json={}).status_code != 409


def test_the_console_ends_its_run_when_it_shuts_down_and_kills_one_left_behind(monkeypatch, tmp_path):
    """Shut down: the run dies with the console. Crashed: the next console kills the group it recorded."""
    import json
    import subprocess
    from orca_ui.home import ui_home
    monkeypatch.setenv("ORCA_RIG_AUTODETECT", "0")
    with _console() as c:
        c.app.state.visual.hand_run.start("ser-0001", command=SLEEPER)
        pid = c.app.state.visual.hand_run.status()["pid"]
        record = ui_home() / "visual_calibration" / "hand_runs" / "active.json"
        assert json.loads(record.read_text())["pgid"] == pid
    assert _wait_for(lambda: _gone(pid)) and not record.exists()

    left = subprocess.Popen(SLEEPER, start_new_session=True)
    entry = {"pgid": left.pid, "hand": "ser-0001", "command": SLEEPER, "started": time.time(), "console": pid}
    record.write_text(json.dumps(entry))
    with _console():
        assert left.wait(timeout=5) == -9 and not record.exists()


def test_a_starting_console_leaves_a_run_alone_that_is_not_its_to_end(monkeypatch):
    """A second console on the same ORCA_HOME while the first still measures; a record whose group is
    now another program (its command or start time differ); a malformed record: nothing is killed and
    the console starts."""
    import json
    import subprocess
    from orca_ui.home import ui_home
    monkeypatch.setenv("ORCA_RIG_AUTODETECT", "0")
    record = ui_home() / "visual_calibration" / "hand_runs" / "active.json"
    record.parent.mkdir(parents=True, exist_ok=True)
    console = subprocess.Popen(SLEEPER)                           # the first console, still running
    run = subprocess.Popen(SLEEPER, start_new_session=True)
    try:
        record.write_text(json.dumps({"pgid": run.pid, "command": SLEEPER, "started": time.time(),
                                      "console": console.pid}))
        with _console():
            assert run.poll() is None and record.exists()
        console.kill()
        console.wait()
        for entry in ({"pgid": run.pid, "command": SLEEPER, "started": time.time() - 3600},   # started earlier
                      {"pgid": run.pid, "command": ["python", "-m", "other"], "started": time.time()}):
            record.write_text(json.dumps(entry))
            with _console():
                assert run.poll() is None and not record.exists()
        record.write_text("{not json")
        with _console() as c:
            assert c.get(f"{VC}/hand-run").json()["state"] == "idle" and run.poll() is None
    finally:
        for p in (console, run):
            p.kill()
            p.wait()


def test_a_stop_during_the_camera_check_cancels_the_start(client, monkeypatch):
    _experiment_on_path()
    from visual_calibration.rig_cameras import RigCameras
    _hand_on_file(client)
    assert client.post(f"{VC}/turntable/connect", json={}).status_code == 200

    def preflight(cams, detector=None, write=True):
        client.app.state.service.estop()                          # E-STOP pressed while the cameras are checked
        return {"indices": {"a": 0, "b": 1}}
    monkeypatch.setattr(RigCameras, "preflight", preflight)
    r = client.post(f"{VC}/hand-run/start", json={"dry": True})
    assert r.status_code == 409 and "was not started" in r.json()["detail"]
    assert client.get(f"{VC}/hand-run").json()["state"] == "idle"


def test_results_name_their_run(client):
    """The newest measured run of the connected hand, named, beside the newest run at all."""
    import json
    _experiment_on_path()
    from hand_study import paths, run_hand
    hand_id = _hand_on_file(client)
    assert client.get(f"{VC}/hand-run/results").json() == {"hand": hand_id, "latest": None, "results": None}
    measured = paths.new_run(run_hand.the_rig(), hand_id, protocol="night_quick")
    (measured / "proposed").mkdir()
    stops = {"index_mcp": {"old": [-20.0, 100.0], "new": [-15.0, 95.0], "n": 70, "dropped": 2, "t_span": [0.0, 1.0],
                           "identifiable": True, "fit": [-15.0, 95.0], "rms": 1.2},
             "wrist": {"old": [-30.0, 30.0], "new": [-30.0, 30.0], "n": 70, "dropped": 0, "t_span": [0.4, 0.5],
                       "identifiable": False, "fit": [-28.0, 33.0], "rms": 0.9}}
    (measured / "proposed" / "hardstops.json").write_text(json.dumps({
        "run": "q1", "n": 70, "min_span": 0.4, "stops": stops,
        "joint_ranges": {"path": "/h/joint_ranges.yaml", "recorded": ["index_mcp"], "rejected": {}, "gone": ["ring_mcp"]}}))
    newer = paths.new_run(run_hand.the_rig(), hand_id, protocol="night_quick")
    r = client.get(f"{VC}/hand-run/results").json()
    assert r["latest"] == str(newer) and r["results"]["run"] == str(measured)
    joints = r["results"]["joints"]
    assert joints["index_mcp"]["measured"] and not joints["wrist"]["measured"] and r["results"]["gone"] == ["ring_mcp"]


def test_no_board_write_with_an_orca_core_that_cannot_keep_the_ranges(client, monkeypatch, tmp_path):
    from orca_core import board_push
    monkeypatch.setattr(board_push, "firmware_tool", lambda: tmp_path / "cal_store.py")
    monkeypatch.delattr(board_push, "board_contents")
    writer = client.get(f"{VC}/board-write").json()
    assert writer["available"] is False and "can't keep the measured ranges on the board" in writer["reason"]
