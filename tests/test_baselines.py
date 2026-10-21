"""Travel baselines: the contract guided tensioning's scoring rests on.

A calibration run must leave a snapshot behind, a snapshot promoted to a
named baseline becomes the active one, and the override that guided
tensioning scores against follows the active name — a wrong baseline makes
the console certify a slack finger as tensioned.
"""

import time

import pytest
from fastapi.testclient import TestClient

from orca_ui.hand import baselines
from orca_ui.mock import materialize_mock_model
from orca_ui.server import create_app
from orca_ui.settings import UiSettings

FAST = {"step_duration_s": 0.02}


def _wait_for(predicate, timeout=10.0, interval=0.02):
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
    settings = UiSettings(config_path=config_path, mock=True, open_browser=False)
    app = create_app(settings)
    with TestClient(app) as test_client:
        assert _wait_for(
            lambda: test_client.get("/api/status").json()["state"] == "connected"
        )
        yield test_client


def test_calibration_leaves_a_snapshot_that_can_become_the_active_baseline(client):
    assert client.get("/api/baselines").json() == {
        "active": None,
        "shared": client.get("/api/baselines").json()["shared"],
        "baselines": {},
        "snapshots": {},
    }

    client.post("/api/operation/calibrate/start", json={"params": FAST})
    assert _wait_for(
        lambda: (
            (client.get("/api/operation").json()["operation"] or {}).get("state")
            == "done"
        )
    )
    state = client.get("/api/baselines").json()
    ((name, snapshot),) = state["snapshots"].items()
    assert name.startswith("auto_")
    assert snapshot["travel"]["index_pip"] > 0
    assert client.get("/api/hand/info").json()["travel_baseline"] is None

    response = client.post(
        "/api/baselines/promote",
        json={"snapshot": name, "name": "GT_01", "note": "clean hand"},
    )
    assert response.status_code == 200
    state = client.get("/api/baselines").json()
    assert state["active"] == "GT_01"
    assert state["baselines"]["GT_01"]["travel"] == snapshot["travel"]
    assert client.get("/api/hand/info").json()["travel_baseline"]["name"] == "GT_01"

    # Baselines are history: a second GT_01 is refused rather than overwritten.
    assert (
        client.post(
            "/api/baselines/promote", json={"snapshot": name, "name": "GT_01"}
        ).status_code
        == 409
    )
    assert (
        client.post("/api/baselines/activate", json={"name": "GT_99"}).status_code
        == 404
    )
    assert (
        client.post("/api/baselines/activate", json={"name": None}).status_code == 200
    )
    assert client.get("/api/baselines").json()["active"] is None

    config = client.app.state.service.supervisor.config
    baselines.activate(config, "GT_01")
    assert baselines.active_travel(config) == snapshot["travel"]


def test_guided_tensioning_scores_against_the_active_baseline(client):
    config = client.app.state.service.supervisor.config
    baselines.import_travel(config, "GT_01", {"index_pip": 50.0}, source="manual")
    baselines.activate(config, "GT_01")

    # The mock is not v2.1 hardware; any_hardware is how the console forces guided.
    response = client.post(
        "/api/operation/guided_tension/start",
        json={"params": {"any_hardware": True, "scoring": "slack"}},
    )
    assert response.status_code == 200, response.text

    def scored():
        op = client.get("/api/operation").json()["operation"] or {}
        extra = op.get("extra") or {}
        return extra if extra.get("motors") and extra.get("baseline") else None

    try:
        # Pose → Continue puts the first stage in its range check, where spreads stream.
        assert _wait_for(
            lambda: (
                (client.get("/api/operation").json()["operation"] or {}).get("state")
                == "awaiting_input"
            )
        )
        client.post("/api/operation/input", json={"value": "Continue"})
        extra = _wait_for(scored)
        assert extra["baseline"]["name"] == "GT_01"
        by_joint = {m["joint"]: m for m in extra["motors"]}
        assert by_joint["index_pip"]["expected_deg"] == 50.0
        # A joint the baseline lacks keeps the config's own figure (none in the mock).
        assert by_joint["middle_pip"]["expected_deg"] != 50.0
    finally:
        client.post("/api/operation/stop")
        _wait_for(
            lambda: (
                (client.get("/api/operation").json()["operation"] or {}).get("state")
                in ("done", "error")
            )
        )
