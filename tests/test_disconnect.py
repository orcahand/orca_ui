"""Letting go of the hardware on purpose.

The connect ladder is relentless by design — a hand that was off, or briefly
unplugged, comes back on its own. ``disconnect()`` is the exception: it
closes the session and *stays* closed, so the ports are free for a power
cycle, a cable move, or an orca_core script on the same bus.
"""

import time

import pytest
from fastapi.testclient import TestClient

from orca_ui.hand.states import HandState
from orca_ui.hand.supervisor import HandBusyError
from orca_ui.mock import materialize_mock_model
from orca_ui.server import create_app
from orca_ui.settings import UiSettings

from test_model_detection import build


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


def test_torque_is_off_after_a_disconnect(client):
    client.post("/api/torque/enable")
    assert _wait_for(lambda: client.get("/api/status").json()["torque_enabled"])

    client.post("/api/disconnect")
    assert client.get("/api/status").json()["torque_enabled"] is False


def test_hardware_calls_are_refused_while_released(client):
    client.post("/api/disconnect")
    assert _wait_for(lambda: client.get("/api/status").json()["released"])
    # No session, so the service's own capability gate answers — the browser
    # gets a clean "hand not connected", not a traceback.
    response = client.post("/api/torque/enable")
    assert response.status_code == 503
    assert response.json()["detail"] == "hand not connected"
