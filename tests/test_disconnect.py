"""Letting go of the hardware on purpose.

The connect ladder is relentless by design — a hand that was off, or briefly
unplugged, comes back on its own. ``disconnect()`` is the exception: it
closes the session and *stays* closed, so the ports are free for a power
cycle, a cable move, or an orca_core script on the same bus.
"""

import time

import pytest
from fastapi.testclient import TestClient

import orca_ui.hand.supervisor as supervisor_mod
from orca_ui.hand.states import HandState
from orca_ui.hand.supervisor import HandBusyError
from orca_ui.mock import materialize_mock_model
from orca_ui.server import create_app
from orca_ui.settings import UiSettings

from test_model_detection import build


class _FakeSession:
    def __init__(self):
        self.closed = False
        self.caps = type("Caps", (), {"motors": False, "degraded": False})()
        self.tier = "fake"
        self.message = "fake"
        self.ports = {}

    def close(self):
        self.closed = True


def test_a_disconnect_during_a_connect_in_flight_wins(monkeypatch):
    """On hardware a connect takes seconds. A disconnect that lands in that
    window must not be undone by the session the connect then installs."""
    from test_model_detection import build

    sup, _ = build("orcahand-right")
    fake = _FakeSession()

    def connect_and_release(settings, config, presence=None):
        sup.disconnect()
        return fake

    monkeypatch.setattr(supervisor_mod, "run_detection", lambda config, force=False: None)
    monkeypatch.setattr(supervisor_mod, "presence_from_detection",
                        lambda config, detection, **kw: None)
    monkeypatch.setattr(supervisor_mod, "connect_session", connect_and_release)

    sup._try_connect()

    assert fake.closed
    assert sup.session is None
    status = sup.status()
    assert status.released and status.state == HandState.DISCONNECTED


def test_a_released_hand_refuses_a_maintenance_lease():
    from test_model_detection import build

    sup, _ = build("orcahand-right")
    sup.disconnect()
    with pytest.raises(RuntimeError, match="released"):
        sup.enter_maintenance("calibrate", timeout=0.2)


def test_selecting_a_model_lifts_the_hold():
    from test_model_detection import build

    sup, _ = build("orcahand-right")
    sup.disconnect()
    sup.select_model("orcahand-left")
    assert not sup.status().released


def _wait_for(predicate, timeout=10.0, interval=0.05):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    return predicate()


# ----- the supervisor's hold ------------------------------------------------


def test_disconnect_releases_and_publishes_the_hold():
    sup, _ = build("orcahand-right")
    sup.disconnect()

    status = sup.status()
    assert status.state is HandState.DISCONNECTED
    assert status.released is True
    assert status.torque_enabled is False
    assert status.ports == {}


def test_reconnect_lifts_the_hold():
    sup, _ = build("orcahand-right")
    sup.disconnect()
    sup.request_reconnect()
    assert sup.status().released is False


def test_an_operation_holding_the_hand_blocks_a_disconnect():
    sup, _ = build("orcahand-right")
    sup._in_maintenance = True
    with pytest.raises(HandBusyError):
        sup.disconnect()
    assert sup.status().released is False


# ----- over the API, against the mock hand ----------------------------------


@pytest.fixture()
def client():
    settings = UiSettings(config_path=materialize_mock_model(), mock=True,
                          open_browser=False)
    app = create_app(settings)
    with TestClient(app) as test_client:
        assert _wait_for(
            lambda: test_client.get("/api/status").json()["state"] == "connected")
        yield test_client


def test_disconnect_stays_disconnected(client):
    body = client.post("/api/disconnect").json()
    assert body["ok"] is True
    assert body["status"]["state"] == "disconnected"
    assert body["status"]["released"] is True

    # The point of the hold: the ladder does not climb back on its own. Long
    # enough to cover several detection passes.
    time.sleep(2.0)
    status = client.get("/api/status").json()
    assert status["state"] == "disconnected"
    assert status["released"] is True
    assert status["capabilities"] is None


def test_reconnect_brings_it_back(client):
    client.post("/api/disconnect")
    assert _wait_for(lambda: client.get("/api/status").json()["released"])

    client.post("/api/reconnect")
    status = _wait_for(
        lambda: (s := client.get("/api/status").json())["state"] == "connected"
        and s)
    assert status["released"] is False
    assert status["capabilities"]["motors"] is True


def test_torque_is_off_after_a_disconnect(client):
    client.post("/api/torque/enable")
    assert _wait_for(lambda: client.get("/api/status").json()["torque_enabled"])

    client.post("/api/disconnect")
    assert client.get("/api/status").json()["torque_enabled"] is False


def test_disconnect_is_idempotent(client):
    client.post("/api/disconnect")
    assert client.post("/api/disconnect").json()["status"]["released"] is True


def test_hardware_calls_are_refused_while_released(client):
    client.post("/api/disconnect")
    assert _wait_for(lambda: client.get("/api/status").json()["released"])
    # No session, so the service's own capability gate answers — the browser
    # gets a clean "hand not connected", not a traceback.
    response = client.post("/api/torque/enable")
    assert response.status_code == 503
    assert response.json()["detail"] == "hand not connected"
