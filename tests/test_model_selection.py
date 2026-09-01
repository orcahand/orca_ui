"""Choosing the hand config by hand, from the browser.

Detection names the model off the controller board's identity reply. A hand
without one — a legacy build, or a hand on someone else's electronics —
answers nothing, so every such hand resolves to orca_core's default model
whatever it really is. These cover the way out: naming the model over the
API pins it, exactly as ``--model`` would have.
"""

import time

import pytest
from fastapi.testclient import TestClient

from orca_ui.hand.supervisor import (
    HandBusyError,
    ModelSelectError,
)
from orca_ui.mock import materialize_mock_model
from orca_ui.server import create_app
from orca_ui.settings import UiSettings

from test_model_detection import build


# ----- the catalogue --------------------------------------------------------


# ----- selection on the supervisor ------------------------------------------


def test_selecting_a_model_swaps_the_config_and_pins_it():
    sup, adopted = build("orcahand-right")
    assert sup.status().model_pinned is False

    assert sup.select_model("orcahand-full-left") == "orcahand-full-left"

    assert sup.model_name == "orcahand-full-left"
    assert sup.config.type == "left"
    assert [c.config_path for c in adopted] == [sup.config.config_path]
    status = sup.status()
    assert status.model == "orcahand-full-left"
    assert status.model_pinned is True


def test_an_unknown_model_is_refused_and_leaves_the_config_alone():
    sup, adopted = build("orcahand-right")
    with pytest.raises(ModelSelectError):
        sup.select_model("orcahand-nonexistent")
    assert sup.model_name == "orcahand-right"
    assert adopted == []


def test_an_operation_holding_the_hand_blocks_a_model_change():
    sup, _ = build("orcahand-right")
    sup._in_maintenance = True
    with pytest.raises(HandBusyError):
        sup.select_model("orcahand-full-left")
    assert sup.model_name == "orcahand-right"


# ----- over the API, against the mock hand ----------------------------------


def _wait_for(predicate, timeout=10.0, interval=0.05):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    return predicate()


@pytest.fixture()
def client():
    settings = UiSettings(config_path=materialize_mock_model(), mock=True,
                          open_browser=False)
    app = create_app(settings)
    with TestClient(app) as test_client:
        assert _wait_for(
            lambda: test_client.get("/api/status").json()["state"] == "connected")
        yield test_client
