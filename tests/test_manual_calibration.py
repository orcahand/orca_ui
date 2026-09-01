"""Manual joint-sensor calibration endpoint + the calibrate op's
joint-sensor option."""

import time

import pytest
from fastapi.testclient import TestClient

from orca_ui.mock import materialize_mock_model
from orca_ui.server import create_app
from orca_ui.settings import UiSettings


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
            lambda: test_client.get("/api/status").json()["state"] == "connected")
        yield test_client


def test_manual_calibration_rejects_bad_requests(client):
    response = client.post("/api/joints/calibrate",
                           json={"joint": "not_a_joint", "angle_deg": 0.0})
    assert response.status_code == 400
    assert "no joint encoder" in response.json()["detail"]

    response = client.post("/api/joints/calibrate",
                           json={"joint": "index_mcp", "angle_deg": 720.0})
    assert response.status_code == 400
    assert "outside the ROM" in response.json()["detail"]
