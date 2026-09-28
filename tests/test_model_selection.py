"""Choosing the hand config by hand, from the browser.

Detection names the model off the controller board's identity reply. A hand
without one — a legacy build, or a hand on someone else's electronics —
answers nothing, so every such hand resolves to orca_core's default model
whatever it really is. These cover the way out: naming the model over the
API pins it, exactly as ``--model`` would have.
"""

import pathlib
import time

import pytest
from fastapi.testclient import TestClient
from orca_core.hand_config import _resolve_config_path

from orca_ui.hand.models import available_models
from orca_ui.hand.supervisor import (
    HandBusyError,
    HandSupervisor,
    ModelSelectError,
    load_config,
)
from orca_ui.mock import materialize_mock_model
from orca_ui.server import create_app
from orca_ui.settings import UiSettings

from test_model_detection import FULL_LEFT, build


# ----- the catalogue --------------------------------------------------------


def test_lists_the_newest_version_of_every_bundled_model():
    entries = available_models()
    names = [entry.name for entry in entries]
    assert "orcahand-touch-left" in names
    assert "orcahand-full-right" in names
    # One entry per name: orcahand-right exists at v1 and v2, and the menu
    # offers what `--model orcahand-right` would actually resolve to.
    assert len(names) == len(set(names))
    for entry in entries:
        if entry.name == "orcahand-right":
            assert entry.version == "v2"


def test_a_pinned_version_lists_that_version_only():
    entries = available_models("v1")
    assert entries and {entry.version for entry in entries} == {"v1"}


def test_capabilities_come_off_the_config():
    by_name = {entry.name: entry for entry in available_models()}
    plain = by_name["orcahand-right"]
    assert plain.side == "right" and not plain.tactile and not plain.encoders
    full = by_name["orcahand-full-left"]
    assert full.side == "left" and full.tactile and full.encoders
    assert by_name["orcahand-touch-right"].tactile
    assert not by_name["orcahand-touch-right"].encoders
    assert by_name["orcahand-joint-right"].encoders
    assert not by_name["orcahand-joint-right"].tactile


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


def test_a_selected_model_survives_a_detection_that_disagrees():
    """The whole point: a board that cannot name the hand must not overwrite
    the operator who did."""
    sup, _ = build("orcahand-right")
    sup.select_model("orcahand-touch-left")

    assert sup._adopt_model(FULL_LEFT) is False
    assert sup.model_name == "orcahand-touch-left"


def test_handing_the_choice_back_reopens_it_to_detection():
    sup, _ = build("orcahand-right")
    sup.select_model("orcahand-touch-left")

    assert sup.select_model(None) == "orcahand-touch-left"
    assert sup.status().model_pinned is False
    # Detection is authoritative again.
    assert sup._adopt_model(FULL_LEFT) is True
    assert sup.model_name == "orcahand-full-left"


def test_reselecting_the_pinned_model_changes_nothing():
    sup, adopted = build("orcahand-full-left", pinned=True)
    sup.select_model("orcahand-full-left")
    assert adopted == []  # no config swap, so nothing was repointed


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


def test_models_endpoint_offers_the_catalogue_plus_what_is_running(client):
    body = client.get("/api/models").json()
    names = [model["name"] for model in body["models"]]
    assert "orcahand-full-right" in names
    # The mock model is not one of orca_core's, but it is what is running.
    assert body["selected"] == "orcahand-mock"
    assert body["selected"] in names
    assert body["pinned"] is True
    # No bus in mock mode, so there is nothing for auto-detection to ask.
    assert body["auto_available"] is False


def test_selecting_a_model_reconnects_the_mock_onto_it(client):
    body = client.post("/api/model/select",
                       json={"name": "orcahand-touch-left"}).json()
    assert body["selected"] == "orcahand-touch-left"

    status = _wait_for(
        lambda: (s := client.get("/api/status").json())["state"] == "connected"
        and s)
    assert status["model"] == "orcahand-touch-left"
    assert status["side"] == "left"
    assert status["model_pinned"] is True
    # The session really was rebuilt on the new config: a touch model has no
    # joint encoders, so the encoder capability has to be gone.
    assert status["capabilities"]["tactile"] is True
    assert status["capabilities"]["encoders"] is False
    assert client.get("/api/hand/info").json()["side"] == "left"


def test_the_mock_model_stays_on_offer_after_switching_away(client):
    """It is not one of orca_core's models, so nothing would resolve it back
    — the supervisor re-materializes it by name instead."""
    client.post("/api/model/select", json={"name": "orcahand-full-left"})
    assert _wait_for(
        lambda: client.get("/api/status").json()["model"] == "orcahand-full-left")

    body = client.get("/api/models").json()
    mock = next(m for m in body["models"] if m["name"] == "orcahand-mock")
    assert mock["selectable"] is True

    client.post("/api/model/select", json={"name": "orcahand-mock"})
    assert _wait_for(
        lambda: (s := client.get("/api/status").json())["state"] == "connected"
        and s["model"] == "orcahand-mock" and s)


def test_a_config_outside_the_bundle_shows_but_cannot_be_repicked(tmp_path):
    """--config names a file, not a model. The picker must still say what is
    running; it just cannot offer it as a choice."""
    import shutil

    from orca_ui.mock import MOCK_MODEL_CONFIG

    model_dir = tmp_path / "bench-rig"
    model_dir.mkdir()
    shutil.copy(MOCK_MODEL_CONFIG, model_dir / "config.yaml")
    shutil.copy(pathlib.Path(MOCK_MODEL_CONFIG).parent / "calibration.yaml",
                model_dir / "calibration.yaml")

    settings = UiSettings(config_path=str(model_dir / "config.yaml"),
                          mock=True, open_browser=False)
    app = create_app(settings)
    with TestClient(app) as test_client:
        body = test_client.get("/api/models").json()
        assert body["selected"] == "bench-rig"
        entry = next(m for m in body["models"] if m["name"] == "bench-rig")
        assert entry["selectable"] is False
        assert entry["version"] == ""


def test_auto_is_refused_in_mock_mode(client):
    response = client.post("/api/model/select", json={"name": None})
    assert response.status_code == 409
    assert "mock" in response.json()["detail"]


def test_an_unknown_model_is_a_409_not_a_crash(client):
    response = client.post("/api/model/select", json={"name": "no-such-hand"})
    assert response.status_code == 409
    assert client.get("/api/models").json()["selected"] == "orcahand-mock"
