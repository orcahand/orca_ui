"""The hand menu: which hand this console is looking at.

A hand's calibration is filed under the hand, so the console has to know which
one. A board names itself; a hand with no board cannot, and nothing can tell
one board-less hand from another, so the operator says — and can add a name, or
forget one along with the calibration filed under it.
"""

import time

import pytest
from fastapi.testclient import TestClient

from orca_core import hand_ids
from orca_ui.mock import materialize_mock_model
from orca_ui.server import create_app
from orca_ui.settings import UiSettings


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from orca_core import board_store

    monkeypatch.setenv(board_store.CALIBRATIONS_DIR_ENV, str(tmp_path))
    settings = UiSettings(config_path=materialize_mock_model(), mock=True,
                          open_browser=False)
    with TestClient(create_app(settings)) as test_client:
        test_client.calibrations = tmp_path
        # A session has to exist before a choice can reach a hand.
        deadline = time.time() + 5.0
        while time.time() < deadline:
            if test_client.get("/api/status").json()["state"] == "connected":
                break
            time.sleep(0.05)
        yield test_client


class TestTheMenu:
    def test_a_machine_that_knows_no_hands_offers_nothing_to_pick(self, client):
        body = client.get("/api/hands").json()
        assert body["known"] == []
        assert body["selected"] is None

    def test_names_somebody_gave_are_listed(self, client):
        hand_ids.add_id("bench-left", client.calibrations)
        hand_ids.add_id("bench-right", client.calibrations)
        assert client.get("/api/hands").json()["known"] == ["bench-left", "bench-right"]

    def test_a_serial_or_board_id_is_not_offered(self, client):
        """Detected, not chosen: offering it invites picking the hand you have."""
        (client.calibrations / "ser-0001.yaml").write_text("calibrated: true\n")
        (client.calibrations / "0123456789ABCDEF.bin").write_bytes(b"")
        assert client.get("/api/hands").json()["known"] == []

    def test_auto_falls_back_to_the_first_name_given(self, client):
        """With no board to ask, the first is the only stable default."""
        hand_ids.add_id("zeta", client.calibrations)
        hand_ids.add_id("alpha", client.calibrations)
        assert client.get("/api/hands").json()["auto"] == "alpha"


class TestAdding:
    def test_a_name_can_be_added(self, client):
        body = client.post("/api/hands/add", json={"name": "new-hand"}).json()
        assert body["known"] == ["new-hand"]

    def test_adding_is_how_a_second_boardless_hand_is_told_apart(self, client):
        client.post("/api/hands/add", json={"name": "bench-1"})
        body = client.post("/api/hands/add", json={"name": "bench-2"}).json()
        assert body["known"] == ["bench-1", "bench-2"]

    def test_a_name_that_cannot_be_one_is_refused_with_the_rule(self, client):
        response = client.post("/api/hands/add", json={"name": "has space"})
        assert response.status_code == 400
        assert "1-20 characters" in response.json()["detail"]

    def test_adding_the_same_name_twice_is_not_an_error(self, client):
        client.post("/api/hands/add", json={"name": "bench"})
        assert client.post("/api/hands/add", json={"name": "bench"}).status_code == 200


class TestChoosing:
    def test_a_name_can_be_chosen(self, client):
        client.post("/api/hands/add", json={"name": "bench"})
        assert client.post("/api/hands/select",
                           json={"name": "bench"}).json()["selected"] == "bench"

    def test_null_hands_it_back_to_auto(self, client):
        client.post("/api/hands/add", json={"name": "bench"})
        client.post("/api/hands/select", json={"name": "bench"})
        assert client.post("/api/hands/select",
                           json={"name": None}).json()["selected"] is None

    def test_a_name_this_machine_does_not_know_is_refused(self, client):
        response = client.post("/api/hands/select", json={"name": "ghost"})
        assert response.status_code == 404

    def test_a_choice_reaches_the_connected_hand(self, client):
        """So what it reads and writes follows without a reconnect."""
        client.post("/api/hands/add", json={"name": "bench"})
        client.post("/api/hands/select", json={"name": "bench"})
        assert client.get("/api/hands").json()["in_use"] == "bench"

    def test_the_choice_is_not_remembered_across_a_console(self, client, tmp_path):
        """Deliberate for now: auto resolves again next launch."""
        client.post("/api/hands/add", json={"name": "bench"})
        client.post("/api/hands/select", json={"name": "bench"})
        settings = UiSettings(config_path=materialize_mock_model(), mock=True,
                              open_browser=False)
        with TestClient(create_app(settings)) as fresh:
            assert fresh.get("/api/hands").json()["selected"] is None


class TestForgetting:
    def test_a_name_and_its_calibration_go(self, client):
        client.post("/api/hands/add", json={"name": "doomed"})
        (client.calibrations / "doomed.yaml").write_text("calibrated: true\n")
        body = client.post("/api/hands/delete", json={"name": "doomed"}).json()
        assert body["known"] == []
        assert not (client.calibrations / "doomed.yaml").exists()

    def test_other_hands_are_left_alone(self, client):
        client.post("/api/hands/add", json={"name": "keep"})
        client.post("/api/hands/add", json={"name": "drop"})
        body = client.post("/api/hands/delete", json={"name": "drop"}).json()
        assert body["known"] == ["keep"]

    def test_one_that_is_not_there_is_refused(self, client):
        assert client.post("/api/hands/delete",
                           json={"name": "ghost"}).status_code == 404

    def test_forgetting_the_chosen_one_hands_the_choice_back_to_auto(self, client):
        client.post("/api/hands/add", json={"name": "doomed"})
        client.post("/api/hands/select", json={"name": "doomed"})
        assert client.post("/api/hands/delete",
                           json={"name": "doomed"}).json()["selected"] is None
