"""configure_chain operation: validation guards (especially the reset
confirmation), the simulated assembly walk with its ``extra`` chain grid,
and the reset loop's stop flow — all over the real manager + mock stack."""

import time

import pytest
from fastapi.testclient import TestClient

from orca_ui.mock import materialize_mock_model
from orca_ui.server import create_app
from orca_ui.settings import UiSettings

FAST = {"step_duration_s": 0.02}


def _wait_for(predicate, timeout=5.0, interval=0.02):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    return predicate()


@pytest.fixture()
def client():
    config_path = materialize_mock_model()
    settings = UiSettings(config_path=config_path, mock=True,
                          open_browser=False)
    app = create_app(settings)
    with TestClient(app) as test_client:
        test_client.app_state = app.state
        assert _wait_for(
            lambda: test_client.get("/api/status").json()["state"]
            == "connected")
        yield test_client


def _operation(client):
    return client.get("/api/operation").json()["operation"]


def _wait_state(client, state, timeout=10.0):
    assert _wait_for(
        lambda: (_operation(client) or {}).get("state") == state,
        timeout=timeout,
    ), f"never reached {state}: {_operation(client)}"
    return _operation(client)


def test_reset_requires_explicit_confirmation(client):
    response = client.post("/api/operation/configure_chain/start",
                           json={"params": {"mode": "reset"}})
    assert response.status_code == 400
    assert "confirmation" in response.json()["detail"]

    # confirm must be the literal true — truthy strings don't count
    response = client.post(
        "/api/operation/configure_chain/start",
        json={"params": {"mode": "reset", "confirm": "yes"}})
    assert response.status_code == 400


def test_unknown_mode_rejected(client):
    response = client.post("/api/operation/configure_chain/start",
                           json={"params": {"mode": "explode"}})
    assert response.status_code == 400


def test_either_family_can_be_configured(client):
    """Chain configuration is family-agnostic: orca_core's routine carries no
    per-family branch, and the one real difference -- whether the bus can be
    hot-plugged -- is a client attribute the plan exposes."""
    for motor_type in ("dynamixel", "feetech"):
        response = client.post(
            "/api/operation/configure_chain/start",
            json={"params": {"mode": "configure", "motor_type": motor_type,
                             **FAST}})
        assert response.status_code == 200, f"{motor_type}: {response.text}"
        client.post("/api/operation/stop")
        _wait_for(lambda: _operation(client) is None
                  or _operation(client)["state"] in ("done", "error",
                                                     "stopped"))


def test_a_family_that_cannot_be_hot_plugged_asks_for_the_power_cycle(client):
    """The one real difference between the families. Feetech cannot be plugged
    onto a live bus, so each step waits for the board to go off and come back;
    the operator has to be there, which is why the run blocks on input."""
    response = client.post(
        "/api/operation/configure_chain/start",
        json={"params": {"mode": "configure", "motor_type": "feetech", **FAST}})
    assert response.status_code == 200, response.text

    snapshot = _wait_state(client, "awaiting_input")
    assert "turn the board back on" in snapshot["awaiting"]["prompt"]
    assert snapshot["awaiting"]["options"] == ["Connected"]

    client.post("/api/operation/stop")
    _wait_for(lambda: (_operation(client) or {}).get("state")
              in ("done", "error", "stopped"))


def test_a_hot_pluggable_family_never_waits_on_the_operator(client):
    """Dynamixel is hot-pluggable, so orca_core polls the bus instead of
    prompting and assembly stays headless. A prompt here would mean the family
    attribute had stopped being consulted."""
    response = client.post(
        "/api/operation/configure_chain/start",
        json={"params": {"mode": "configure", "motor_type": "dynamixel",
                         **FAST}})
    assert response.status_code == 200, response.text

    snapshot = _wait_state(client, "done")
    assert snapshot["result"]["configured"]
    states = {m["state"] for m in snapshot["extra"]["chain"]}
    assert states == {"configured"}


def test_configure_walks_the_chain_with_extra_grid(client):
    response = client.post(
        "/api/operation/configure_chain/start",
        json={"params": {"mode": "configure", **FAST}})
    assert response.status_code == 200, response.text

    snapshot = _wait_state(client, "done")
    assert snapshot["result"]["simulated"] is True
    configured = snapshot["result"]["configured"]
    assert len(configured) == 17
    # assembly order: highest finger ID first, wrist (ID 1) last
    assert configured[0] == 17
    assert configured[-1] == 1

    extra = snapshot["extra"]
    assert extra["mode"] == "configure"
    assert len(extra["chain"]) == 17
    assert all(slot["state"] == "configured" for slot in extra["chain"])
    wrist = [s for s in extra["chain"] if s["role"] == "wrist"]
    assert [s["id"] for s in wrist] == [1]

    # maintenance lease released -> the mock reconnects
    assert _wait_for(
        lambda: client.get("/api/status").json()["state"] == "connected")


def test_reset_runs_until_stopped(client):
    response = client.post(
        "/api/operation/configure_chain/start",
        json={"params": {"mode": "reset", "confirm": True, **FAST}})
    assert response.status_code == 200, response.text

    # the simulated reset walks all motors then parks until stopped
    assert _wait_for(
        lambda: len(((_operation(client) or {}).get("extra") or {})
                    .get("resets", [])) == 17, timeout=10.0)
    assert (_operation(client) or {}).get("state") == "running"

    client.post("/api/operation/stop")
    snapshot = _wait_state(client, "done")
    assert snapshot["detail"] == "stopped"
    assert _wait_for(
        lambda: client.get("/api/status").json()["state"] == "connected")


def test_configure_chain_blocked_while_operation_runs(client):
    # slow steps so the first op is guaranteed still running
    assert client.post(
        "/api/operation/configure_chain/start",
        json={"params": {"mode": "configure",
                         "step_duration_s": 0.5}}).status_code == 200
    response = client.post(
        "/api/operation/configure_chain/start",
        json={"params": {"mode": "configure", **FAST}})
    assert response.status_code == 409
    client.post("/api/operation/stop")
    _wait_state(client, "done")


def test_every_event_orca_core_emits_is_surfaced():
    """The failure this guards against: orca_core grew chain events and the
    console quietly dropped eight of them, including the one that says it is
    scanning for your motor. The poll it runs is silent and unbounded by
    design, so a dropped event turns a correct wait into something
    indistinguishable from a hang.

    Read off orca_core rather than listed here, so an event added there fails
    this test instead of going unnoticed.
    """
    import inspect
    import re

    from orca_core.maintenance import motor_chain

    from orca_ui.hand.operations import chain

    emitted = set(re.findall(r'_emit\(progress_callback,\s*"([a-z_]+)"',
                             inspect.getsource(motor_chain)))
    assert emitted, "found no progress events in orca_core — check the pattern"

    mapper = inspect.getsource(chain._progress_mapper)
    unhandled = sorted(name for name in emitted if f'"{name}"' not in mapper)
    assert unhandled == [], (
        f"orca_core emits these but the console says nothing: {unhandled}")


def test_a_resumed_chain_takes_the_family_from_the_connected_bus(client):
    """Factory-default probing cannot identify a resumed chain: every motor
    already programmed has moved off the default ID, so nothing answers. The
    packaged configs leave the family on auto, so without this the browser's
    plain {"mode": "configure"} fails on exactly the hand you are part-way
    through building."""
    from orca_ui.hand.operations.chain import validate_chain_params

    service = client.app_state.service
    assert service.supervisor.config.motor_type in (None, "", "auto")

    clean = validate_chain_params(service, {"mode": "configure"})

    assert clean["motor_type"] is not None, (
        "resolved nothing, so the run would fall through to factory-default "
        "probing and fail on a part-built chain")


def test_assembly_time_still_defers_to_probing(client):
    """With no session there is nothing to ask, and that is correct: a chain
    being built from scratch does answer the factory-default probe."""
    import types

    from orca_ui.hand.operations.chain import _family_of_connected_bus

    assert _family_of_connected_bus(types.SimpleNamespace(session=None)) is None


def test_an_already_complete_chain_finishes_in_a_sane_phase(client):
    """A chain with nothing left to do returns before the first step, so the
    phase never advances on its own. Finishing while still reporting
    "acquiring" reads as a run that stalled taking the bus."""
    response = client.post(
        "/api/operation/configure_chain/start",
        json={"params": {"mode": "configure", "motor_type": "dynamixel",
                         **FAST}})
    assert response.status_code == 200, response.text

    snapshot = _wait_state(client, "done")
    assert snapshot["phase"] != "acquiring"
    assert snapshot["progress"] == 1.0
