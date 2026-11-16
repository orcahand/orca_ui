"""Motors an operation could not switch off: the console keeps warning about them
whatever else fails, and switches them off again once it has a working connection."""

import time

import pytest
from fastapi.testclient import TestClient

from orca_ui.hand.operations.base import Operation
from orca_ui.mock import materialize_mock_model
from orca_ui.server import create_app
from orca_ui.settings import UiSettings


def _wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


class _DropsTheLinkOp(Operation):
    """Lets go with motors 3 and 7 unconfirmed, then fails like a USB drop."""

    kind = "drops_the_link"

    def run(self, ctx):
        ctx.torque_off_failed({"motors": [3, 7], "joints": ["index_mcp", "ring_mcp"]})
        raise OSError("read failed: [Errno 6] Device not configured")


@pytest.fixture()
def client():
    settings = UiSettings(config_path=materialize_mock_model(), mock=True, open_browser=False)
    app = create_app(settings)
    app.state.operations.register(_DropsTheLinkOp)
    with TestClient(app) as test_client:
        assert _wait_for(lambda: test_client.get("/api/status").json()["state"] == "connected")
        yield test_client


def _holding(client):
    held = client.app.state.service.control_state()["motors_holding"]
    return held and {k: v for k, v in held.items() if k != "hand_id"}


def _flag_3_and_7(service, monkeypatch):
    """Raise the warning while the console's own connection can't switch them off either."""
    with monkeypatch.context() as m:
        m.setattr(service.session.hand, "disable_torque", lambda ids=None: list(ids or []))
        service.motors_may_hold({"motors": [3, 7], "joints": ["index_mcp", "ring_mcp"]})


def test_a_failed_run_still_warns_until_the_motors_are_confirmed_off(client, monkeypatch):
    service = client.app.state.service
    # The console's own connection is dead too, as right after a USB drop.
    monkeypatch.setattr(service.session.hand, "disable_torque", lambda ids=None: list(ids or []))
    assert client.post("/api/operation/drops_the_link/start", json={}).status_code == 200
    assert _wait_for(lambda: (client.app.state.operations.snapshot() or {}).get("state") == "error")
    assert _wait_for(lambda: _holding(client) is not None)
    assert _holding(client) == {"motors": [3, 7], "joints": ["index_mcp", "ring_mcp"], "confirmed": False}


def test_a_working_connection_confirms_the_motors_off(client):
    service = client.app.state.service
    calls = []
    real = service.session.hand.disable_torque
    service.session.hand.disable_torque = lambda ids=None: calls.append(ids) or real(ids)
    service.motors_may_hold({"motors": [3, 7], "joints": ["index_mcp", "ring_mcp"]})
    assert calls == [[3, 7]]
    assert _holding(client) == {"motors": [], "joints": [], "confirmed": True}
    assert client.post("/api/motors-holding/dismiss").json() == {"ok": True}
    assert _holding(client) is None


def test_a_motor_that_does_not_acknowledge_stays_in_the_warning(client, monkeypatch):
    service = client.app.state.service
    monkeypatch.setattr(service.session.hand, "disable_torque", lambda ids=None: [7])
    service.motors_may_hold({"motors": [3, 7], "joints": ["index_mcp", "ring_mcp"]})
    assert _holding(client) == {"motors": [7], "joints": ["ring_mcp"], "confirmed": False}
    # The torque flag is never raised by the re-check.
    assert service.control_state()["torque_enabled"] is False


def test_a_motor_that_never_answered_is_not_confirmed_off(client, monkeypatch):
    service = client.app.state.service
    # Motor 7 missed the connect ping: the client skips it and reports no failure for it.
    monkeypatch.setattr(service.session.hand.motor_client, "absent_motor_ids", lambda: [7])
    service.motors_may_hold({"motors": [3, 7], "joints": ["index_mcp", "ring_mcp"]})
    assert _holding(client) == {"motors": [7], "joints": ["ring_mcp"], "confirmed": False}
    assert service.estop()["torque_disabled"] is True
    assert _holding(client) == {"motors": [7], "joints": ["ring_mcp"], "confirmed": False}


def test_a_reconnect_confirms_the_motors_off_once_nothing_holds_the_hand(client, monkeypatch):
    service = client.app.state.service
    _flag_3_and_7(service, monkeypatch)
    with monkeypatch.context() as m:
        m.setattr(service._operation_manager, "active", lambda: True)
        service._session_ready(service.session)
    assert _holding(client) == {"motors": [3, 7], "joints": ["index_mcp", "ring_mcp"], "confirmed": False}
    with monkeypatch.context() as m:
        m.setattr(service.session.hand.motor_client, "absent_motor_ids", lambda: [7])
        service._session_ready(service.session)
    assert _holding(client) == {"motors": [7], "joints": ["ring_mcp"], "confirmed": False}
    service._session_ready(service.session)
    assert _holding(client) == {"motors": [], "joints": [], "confirmed": True}


def test_another_hand_cannot_confirm_the_warning(client, monkeypatch):
    service = client.app.state.service
    monkeypatch.setattr(service, "_last_hand_id", "hand-a")
    _flag_3_and_7(service, monkeypatch)
    service._session_ready(service.session)
    service.estop()
    held = service.control_state()["motors_holding"]
    assert held == {"hand_id": "hand-a", "motors": [3, 7], "joints": ["index_mcp", "ring_mcp"],
                    "confirmed": False}
