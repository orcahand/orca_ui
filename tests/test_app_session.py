"""App sessions (orca_ui/hand/app): the contract an app speaks, and the safety
rules the console applies to what it sends.

Most tests drive the session directly with a fake link and a fake clock, so
every rule is checked without sleeps. The handshake goes over the real
``/ws/app`` socket, and the process tests start real child processes.
"""

import os
import sys
import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from orca_ui.mock import materialize_mock_model
from orca_ui.server import create_app
from orca_ui.settings import UiSettings
from orca_ui.streaming import topics as T
from orca_ui.streaming.hub import _envelope

LIVE = {"key": "speed", "type": "number", "minimum": 0, "maximum": 1, "live": True}
LOCKED = {"key": "camera", "type": "enum", "choices": [{"value": "0"}, {"value": "1"}]}


def _wait_for(predicate, timeout=8.0, interval=0.02):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    return predicate()


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class FakeLink:
    def __init__(self):
        self.sent = []
        self.closed = False

    def send_json(self, message):
        self.sent.append(message)

    def close(self):
        self.closed = True

    def of_type(self, kind):
        return [m["data"] for m in self.sent if m["type"] == kind]


@pytest.fixture()
def client(tmp_path):
    settings = UiSettings(
        config_path=materialize_mock_model(), mock=True, open_browser=False,
        apps_dir=str(tmp_path / "apps"),
        app_hold_after_ms=250, app_disengage_after_s=10.0, app_browser_grace_s=2.0,
    )
    app = create_app(settings)
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as test_client:
        test_client.app_state = app.state
        assert _wait_for(lambda: test_client.get("/api/status").json()["state"] == "connected")
        app.state.apps.clock = FakeClock()
        yield test_client
        test_client.post("/api/app/stop")


def _apps(client):
    return client.app_state.apps


def _hub(client, topic):
    entry = client.app_state.hub.latest(topic)
    return entry[2] if entry else None


def _control(client):
    return client.get("/api/hand/info").json()["control"]


def _torque(client):
    return client.get("/api/status").json()["torque_enabled"]


def _connected(client, schema=None):
    """An external session in preview, linked to a FakeLink."""
    token = client.post("/api/app/start", json={"app": "teleop", "mode": "external"}).json()["token"]
    link = FakeLink()
    reply = _apps(client).on_hello({"token": token, "proto": 2, "app": "fake"}, link)
    if schema is not None:
        _apps(client).on_message(link, "settings", {"schema": schema, "values": {}})
    return link, reply


def _pose(reply, fraction=0.5):
    """A pose part-way up every joint's range."""
    return {j: lo + fraction * (hi - lo) for j, (lo, hi) in reply["hand"]["ranges"].items()}


def _targets(client, link, pose):
    _apps(client).on_message(link, "targets", {"angles": pose})


def _engaged(client, ramp_s=0.5):
    link, reply = _connected(client)
    assert client.post("/api/torque/enable").status_code == 200
    _targets(client, link, _pose(reply))
    response = client.post("/api/app/engage", json={"ramp_s": ramp_s})
    assert response.status_code == 200, response.text
    return link, reply


def _commanded(client):
    return _hub(client, T.JOINTS_TARGET)["angles"]


def _later(client, seconds):
    _apps(client).clock.now += seconds
    _apps(client).tick()


# ----- the contract ---------------------------------------------------------------


def test_hello_checks_token_and_protocol_then_sends_the_hand(client):
    token = client.post("/api/app/start", json={"app": "teleop", "mode": "external"}).json()["token"]

    for hello, code in (({"token": "nope", "proto": 2}, 4001),
                        ({"token": token, "proto": 1}, 4002)):
        with client.websocket_connect("/ws/app") as ws:
            ws.send_json({"type": "hello", "data": hello})
            with pytest.raises(WebSocketDisconnect) as refused:
                ws.receive_json()
            assert refused.value.code == code
    assert client.get("/api/app/state").json()["session"]["state"] == "starting"

    with client.websocket_connect("/ws/app") as ws:
        ws.send_json({"type": "hello", "data": {"token": token, "proto": 2, "app": "fake"}})
        reply = ws.receive_json()
        assert reply["type"] == "hello_ok"
        hand = reply["data"]["hand"]
        info = client.get("/api/hand/info").json()
        assert hand["side"] == info["side"] and hand["model"] == info["model_name"]
        assert hand["joints"] == [j["id"] for j in info["joints"]]
        assert hand["ranges"] == {j["id"]: j["rom"] for j in info["joints"]}
        assert "hardware_version" in hand
        session = client.get("/api/app/state").json()["session"]
        assert (session["state"], session["app"], session["process"]["connected"]) == \
            ("preview", "teleop", True)


def test_remembered_command_and_settings_reach_the_next_start(client):
    assert client.post("/api/app/start", json={"app": "rl"}).status_code == 409  # no command
    # The command runs on this machine: a remote caller or a rebound Host can't set it.
    remote = TestClient(client.app, client=("192.168.1.20", 50000))  # no second lifespan
    assert remote.put("/api/app/rl/command", json={"command": "x"}).status_code == 403
    assert client.put("/api/app/rl/command", json={"command": "x"},
                      headers={"host": "evil.example:5001"}).status_code == 403
    apps = client.put("/api/app/rl/command", json={"command": "  run-rl --fast  "}).json()["apps"]
    assert next(a for a in apps if a["id"] == "rl")["command"] == "run-rl --fast"

    link, _ = _connected(client, schema=[LIVE, LOCKED])
    # Malformed entries from the app are cleaned, never passed on to break the tab.
    odd = [{"key": "bad", "type": "enum", "choices": [None]},
           {"key": "named", "type": "string", "title": {"x": 1}}]
    _apps(client).on_message(link, "settings", {"schema": [LIVE, LOCKED, *odd],
                                                "values": {"speed": 0.5, "camera": "1"}})
    client.post("/api/app/stop")
    listed = next(a for a in client.get("/api/app/list").json()["apps"] if a["id"] == "teleop")
    assert listed["values"] == {"speed": 0.5, "camera": "1"}
    assert [s["key"] for s in listed["schema"]] == ["speed", "camera", "named"]
    assert listed["schema"][2]["title"] == "{'x': 1}"

    # Changed while no app runs: remembered, and handed to the next app.
    assert client.post("/api/app/teleop/settings", json={"values": {"camera": "0"}}).status_code == 200
    assert client.post("/api/app/teleop/settings", json={"values": {"bogus": 1}}).status_code == 400
    _, reply = _connected(client)
    assert reply["values"] == {"speed": 0.5, "camera": "0"}


def test_infinity_or_nan_from_an_app_never_breaks_the_tab_or_the_next_start(client):
    link, _ = _connected(client)
    inf, nan = float("inf"), float("nan")  # Python's json reads both
    _apps(client).on_message(link, "settings", {
        "schema": [{"key": "gain", "type": "number", "maximum": inf, "default": nan},
                   {"key": "mode", "type": "enum", "choices": [{"value": inf}, {"value": 1}]}],
        "values": {"gain": inf, "mode": 1}})
    _envelope(T.APP_STATE, 1, 0.0, _hub(client, T.APP_STATE))  # strict JSON, as /ws sends it
    assert client.get("/api/app/state").json()["session"]["settings"]["values"] == {"mode": 1}
    client.post("/api/app/stop")

    # A stored file holding Infinity (hand-edited, or from an older console).
    stored = _apps(client)._store._root / "teleop.json"
    stored.write_text('{"command": "", "schema": [], "values": {"gain": Infinity, "mode": 1}}')
    assert client.get("/api/app/list").status_code == 200
    response = client.post("/api/app/start", json={"app": "teleop", "mode": "external"})
    assert response.status_code == 200 and response.json()["session"]["state"] == "starting"


# ----- preview -------------------------------------------------------------------------


def test_preview_clamps_targets_and_never_moves_the_hand(client):
    link, reply = _connected(client)
    joint, (lo, hi) = next(iter(reply["hand"]["ranges"].items()))
    _targets(client, link, {joint: hi + 1000.0, "not_a_joint": 1.0,
                            reply["hand"]["joints"][1]: float("nan")})
    ghost = _hub(client, T.APP_TARGETS)
    assert ghost["angles"] == {joint: hi}
    assert _hub(client, T.JOINTS_TARGET) is None
    assert _control(client)["control_source"] == "manual"


# ----- engage ----------------------------------------------------------------------------


def test_engage_needs_torque_and_locks_manual_control_until_disengage(client):
    link, reply = _connected(client)
    _targets(client, link, _pose(reply))
    response = client.post("/api/app/engage", json={})
    assert response.status_code == 409 and "torque" in response.json()["detail"]

    assert client.post("/api/torque/enable").status_code == 200
    assert client.post("/api/app/engage", json={"ramp_s": 0}).status_code == 422  # no instant engage
    assert client.post("/api/app/engage", json={"ramp_s": 0.5}).status_code == 200
    assert link.of_type("engaged") == [{"engaged": True}]
    assert _control(client)["control_source"] == "app"
    joint = reply["hand"]["joints"][0]
    assert client.post("/api/joints/target", json={"angles": {joint: 0.0}}).status_code == 409
    assert client.post("/api/operation/demo/start", json={}).status_code == 409

    assert client.post("/api/app/disengage").status_code == 200
    assert _control(client)["control_source"] == "manual"
    assert _torque(client) is True  # disengage holds the pose
    assert client.post("/api/joints/target", json={"angles": {joint: 0.0}}).status_code == 200


def test_engage_ramps_in_from_the_current_pose(client):
    link, reply = _connected(client)
    client.post("/api/torque/enable")
    start = client.app_state.service.current_pose()
    assert client.post("/api/app/engage", json={"ramp_s": 2.0}).status_code == 200
    target = _pose(reply, 0.9)
    joint = max(target, key=lambda j: abs(target[j] - start[j]))

    _targets(client, link, target)  # the ramp's clock starts with the first target
    assert _commanded(client)[joint] == pytest.approx(start[joint])
    _apps(client).clock.now += 1.0
    _targets(client, link, target)
    assert _commanded(client)[joint] == pytest.approx((start[joint] + target[joint]) / 2)
    _apps(client).clock.now += 1.0
    _targets(client, link, target)
    assert _commanded(client)[joint] == pytest.approx(target[joint])


def test_a_joint_first_sent_late_ramps_in_too(client):
    link, reply = _connected(client)
    client.post("/api/torque/enable")
    start = client.app_state.service.current_pose()
    assert client.post("/api/app/engage", json={"ramp_s": 1.0}).status_code == 200
    target = _pose(reply, 0.9)
    late = max(target, key=lambda j: abs(target[j] - start[j]))
    early = {j: v for j, v in target.items() if j != late}

    _targets(client, link, early)
    _apps(client).clock.now += 2.0
    _targets(client, link, early)  # the others' ramps are done
    _targets(client, link, target)
    assert _commanded(client)[late] == pytest.approx(start[late])
    _apps(client).clock.now += 1.0
    _targets(client, link, target)
    assert _commanded(client)[late] == pytest.approx(target[late])


def test_engage_after_a_long_hold_keeps_its_ramp_and_stays_engaged(client):
    link, reply = _connected(client)
    client.post("/api/torque/enable")
    start = client.app_state.service.current_pose()
    _later(client, 15.0)  # no targets for 15 s in preview
    assert client.post("/api/app/engage", json={"ramp_s": 4.0}).status_code == 200
    _apps(client).tick()
    assert client.get("/api/app/state").json()["session"]["state"] == "engaged"

    target = _pose(reply, 0.9)
    joint = max(target, key=lambda j: abs(target[j] - start[j]))
    _targets(client, link, target)
    _apps(client).clock.now += 2.0
    _targets(client, link, target)
    assert _commanded(client)[joint] == pytest.approx((start[joint] + target[joint]) / 2)


def test_stop_during_engage_gives_the_hand_back(client, monkeypatch):
    link, reply = _connected(client)
    _targets(client, link, _pose(reply))
    client.post("/api/torque/enable")
    service = client.app_state.service
    real_pose = service.current_pose

    def stop_meanwhile():
        _apps(client).stop()
        return real_pose()

    monkeypatch.setattr(service, "current_pose", stop_meanwhile)
    assert client.post("/api/app/engage", json={}).status_code == 409
    assert _control(client)["control_source"] == "manual"
    assert client.get("/api/app/state").json()["session"]["state"] == "idle"


def test_settings_are_locked_while_engaged_unless_live(client):
    link, reply = _connected(client, schema=[LIVE, LOCKED])
    client.post("/api/torque/enable")
    _targets(client, link, _pose(reply))
    client.post("/api/app/engage", json={})

    response = client.post("/api/app/teleop/settings", json={"values": {"camera": "1"}})
    assert response.status_code == 409 and "disengage" in response.json()["detail"]
    assert client.post("/api/app/teleop/settings", json={"values": {"speed": 0.2}}).json()["sent"]
    assert link.of_type("set") == [{"speed": 0.2}]


# ----- holds and automatic disengage --------------------------------------------------------


def test_no_targets_holds_then_auto_disengages(client):
    link, _ = _engaged(client)
    _later(client, 0.3)
    assert client.get("/api/app/state").json()["session"]["tracking"] == "lost"
    assert client.get("/api/app/state").json()["session"]["state"] == "engaged"
    _later(client, 10.5)
    session = client.get("/api/app/state").json()["session"]
    assert session["state"] == "preview" and "auto-disengaged" in session["notice"]
    assert _control(client)["control_source"] == "manual"
    assert _torque(client) is True


def test_app_reporting_no_tracking_holds_even_while_targets_arrive(client):
    link, reply = _engaged(client)
    held = dict(_commanded(client))
    _apps(client).on_message(link, "status", {"tracking": False})
    for _ in range(3):
        _apps(client).clock.now += 4.0
        _targets(client, link, _pose(reply, 0.1))
        _apps(client).tick()
    assert _commanded(client) == held
    assert client.get("/api/app/state").json()["session"]["state"] == "preview"


def test_targets_after_a_hold_ramp_in_again(client):
    link, reply = _engaged(client, ramp_s=2.0)
    first = _pose(reply, 0.5)
    _targets(client, link, first)
    _apps(client).clock.now += 2.0
    _targets(client, link, first)
    assert _commanded(client) == pytest.approx(first)

    _later(client, 0.3)  # held
    moved = _pose(reply, 0.9)
    _targets(client, link, moved)
    joint = reply["hand"]["joints"][0]
    assert _commanded(client)[joint] == pytest.approx(first[joint])  # no jump


def test_a_hold_during_a_slow_engage_keeps_its_speed(client):
    link, reply = _connected(client)
    client.post("/api/torque/enable")
    start = client.app_state.service.current_pose()
    assert client.post("/api/app/engage", json={"ramp_s": 10.0}).status_code == 200
    target = _pose(reply, 0.9)
    joint = max(target, key=lambda j: abs(target[j] - start[j]))

    _targets(client, link, target)
    _apps(client).clock.now += 2.0
    _targets(client, link, target)  # 20% of the way
    _later(client, 0.3)  # held
    _targets(client, link, target)
    _apps(client).clock.now += 1.0
    _targets(client, link, target)
    done = (_commanded(client)[joint] - start[joint]) / (target[joint] - start[joint])
    assert done == pytest.approx(0.2 + 0.8 / 7.7, abs=0.01)  # the 7.7 s left, not 1 s


def test_torque_off_auto_disengages(client):
    _engaged(client)
    client.post("/api/torque/disable")
    _apps(client).tick()
    assert client.get("/api/app/state").json()["session"]["state"] == "preview"
    assert _control(client)["control_source"] == "manual"


def test_closing_the_last_browser_tab_disengages(client):
    browsers = [1]
    _apps(client)._browsers = lambda: browsers[0]
    _engaged(client)
    _later(client, 0.0)
    browsers[0] = 0
    _later(client, 0.1)
    _later(client, 1.5)
    assert client.get("/api/app/state").json()["session"]["state"] == "engaged"  # a reload
    _later(client, 0.6)
    assert client.get("/api/app/state").json()["session"]["state"] == "preview"


# ----- ends -------------------------------------------------------------------------------


def test_ending_an_engaged_session_turns_torque_off_and_clears_the_ghost(client):
    link, _ = _engaged(client)
    _apps(client).on_message(link, "frame", {"stream": "camera", "jpeg": "AAAA"})
    assert _hub(client, T.APP_FRAMES)["streams"]

    _apps(client).on_link_closed(link)
    assert _wait_for(lambda: client.get("/api/app/state").json()["session"]["state"] == "error")
    assert _torque(client) is False
    assert _control(client)["control_source"] == "manual"
    assert _hub(client, T.APP_TARGETS)["angles"] == {}
    assert _hub(client, T.APP_FRAMES)["streams"] == {}


def test_hand_change_ends_the_session(client):
    link, _ = _connected(client)
    supervisor = client.app_state.service.supervisor
    other = 20 if supervisor.config.hardware_version != 20 else 21
    supervisor.config = supervisor.config.with_hardware_version(other)
    _apps(client).tick()
    assert _wait_for(lambda: client.get("/api/app/state").json()["session"]["state"] == "error")
    assert "hand changed" in client.get("/api/app/state").json()["session"]["error"]
    assert link.of_type("stop") == [{}]


# ----- app processes --------------------------------------------------------------------------

STUBBORN_APP = """
import signal, subprocess, sys, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
open(sys.argv[1], "w").write(f"{child.pid}\\n" + " ".join(sys.argv[2:]))
print("stubborn app up", flush=True)
time.sleep(60)
"""

QUITTING_APP = """
import subprocess, sys
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
open(sys.argv[1], "w").write(f"{child.pid}\\n" + " ".join(sys.argv[2:]))
print("quitting app up", flush=True)
sys.exit(3)
"""


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _start_script(client, tmp_path, source):
    script, record = tmp_path / "app.py", tmp_path / "app.txt"
    script.write_text(source)
    client.put("/api/app/teleop/command", json={"command": f"{sys.executable} {script} {record}"})
    assert client.post("/api/app/start", json={"app": "teleop"}).status_code == 200
    assert _wait_for(lambda: record.exists() and "\n" in record.read_text())
    pid, argv = record.read_text().split("\n")
    return int(pid), argv


def test_estop_cuts_torque_at_once_and_the_app_is_really_gone(client, tmp_path):
    grandchild, _ = _start_script(client, tmp_path, STUBBORN_APP)
    link = FakeLink()
    reply = _apps(client).on_hello({"token": _apps(client)._token, "proto": 2}, link)
    client.post("/api/torque/enable")
    _targets(client, link, _pose(reply))
    assert client.post("/api/app/engage", json={}).status_code == 200

    began = time.monotonic()
    report = client.post("/api/estop").json()["report"]
    assert time.monotonic() - began < 1.0  # doesn't wait for the app, which ignores SIGTERM
    assert report["torque_disabled"] is True and report["app_stopped"] is True
    assert _torque(client) is False
    assert _wait_for(lambda: _control(client)["control_source"] == "manual")
    assert _wait_for(lambda: not _alive(grandchild))
    assert _wait_for(lambda: client.get("/api/app/state").json()["session"]["state"] == "idle")


def test_app_exit_ends_the_session_and_takes_what_it_started(client, tmp_path):
    grandchild, argv = _start_script(client, tmp_path, QUITTING_APP)
    assert argv.startswith("--connect ws://127.0.0.1:") and "/ws/app --token " in argv
    _apps(client).tick()
    assert _wait_for(lambda: (_apps(client).tick(), client.get("/api/app/state").json()
                              ["session"]["state"] == "error")[1])
    assert "exited (code 3)" in client.get("/api/app/state").json()["session"]["error"]
    assert _wait_for(lambda: not _alive(grandchild))
    lines = [line["line"] for line in client.get("/api/app/log").json()["lines"]]
    assert any("quitting app up" in line for line in lines)
    assert not any(argv.split("--token ")[1] in line for line in lines)
