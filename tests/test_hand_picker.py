"""The hand menu: which hand this console is looking at.

A hand's calibration is filed under the hand, so the console has to know which
one. A board names itself; a hand with no board cannot, and nothing can tell
one board-less hand from another, so the operator says — and can add a name, or
forget one along with the calibration filed under it.
"""

import dataclasses
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


class TestAddingAHandPicksIt:
    """A name is made for the hand plugged in now.

    Leaving the choice on auto after adding one would resolve to whichever
    name sorts first -- which, on a bench with two board-less hands, is the
    other one, and would file this hand's calibration under it.
    """

    def test_the_new_name_is_the_one_in_force(self, client):
        hand_ids.add_id("alpha", client.calibrations)
        body = client.post("/api/hands/add", json={"name": "zeta"}).json()
        assert body["selected"] == "zeta"
        assert body["in_use"] == "zeta"
        assert body["auto"] == "alpha"

    def test_forgetting_the_chosen_one_hands_the_choice_back(self, client):
        client.post("/api/hands/add", json={"name": "zeta"})
        body = client.post("/api/hands/delete", json={"name": "zeta"}).json()
        assert body["selected"] is None


class TestWhichBoardTheIdComesFrom:
    """The session's own hand, never the machine.

    With two hands plugged in, the console can be driving a board-less one
    while an OH board sits on another port. Reporting that board's id here
    would offer another hand's calibration as this one's default.
    """

    def test_a_board_less_session_reports_no_board(self, client):
        """The mock hand has no board, so nothing may be claimed for it."""
        body = client.get("/api/hands").json()
        assert body["from_board"] is None

    def test_a_stale_machine_wide_id_is_not_used_for_a_named_hand(self, client,
                                                                 monkeypatch):
        service = client.app.state.service
        monkeypatch.setattr(type(service.supervisor), "hand_id",
                            property(lambda self: "ser-0001"))
        body = client.get("/api/hands").json()
        assert body["from_board"] is None, "took the machine's id, not the hand's"
        assert body["auto"] != "ser-0001"


class TestAutoIsActuallyInForce:
    """What the picker shows is what a calibration is filed under.

    A board-less hand on auto used to be left unnamed: the menu showed the
    first name this machine knows while the hand itself had none, so a
    calibration run wrote to the model directory instead of that hand's file.
    """

    def test_a_board_less_hand_on_auto_is_named_after_it(self, client, monkeypatch):
        """Driven as a real session: mock mode deliberately opts out below."""
        hand_ids.add_id("alpha", client.calibrations)
        service = client.app.state.service
        monkeypatch.setattr(service, "settings",
                            dataclasses.replace(service.settings, mock=False))
        service._session_ready(service.session)
        body = client.get("/api/hands").json()
        assert body["auto"] == "alpha"
        assert body["in_use"] == "alpha", "shown as alpha but not in force"

    def test_a_mock_hand_is_never_handed_a_real_hand_s_calibration(self, client):
        """It synthesises its own, and that one never reaches disk either.

        Naming it would load whatever this machine last calibrated, which is
        another hand's calibration in a session that has no hand at all.
        """
        hand_ids.add_id("alpha", client.calibrations)
        service = client.app.state.service
        service._session_ready(service.session)
        assert service.session.hand.hand_id is None

    def test_with_nothing_registered_there_is_nothing_to_be(self, client):
        body = client.get("/api/hands").json()
        assert body["auto"] is None and body["in_use"] is None

    def test_a_choice_still_beats_auto(self, client):
        hand_ids.add_id("alpha", client.calibrations)
        hand_ids.add_id("zeta", client.calibrations)
        body = client.post("/api/hands/select", json={"name": "zeta"}).json()
        assert body["auto"] == "alpha" and body["in_use"] == "zeta"


class TestAPickDoesNotFollowOntoAnotherHand:
    """A name is picked for the hand in front of you, not for the console.

    With two hands on one bench, a name chosen for the board-less one would
    otherwise still be in force after switching to a hand that names itself --
    and that hand's calibration would be filed under the other one's name.
    """

    def test_a_pick_is_dropped_when_a_different_hand_appears(self, client,
                                                             monkeypatch):
        hand_ids.add_id("bench-left", client.calibrations)
        client.post("/api/hands/select", json={"name": "bench-left"})
        assert client.get("/api/hands").json()["selected"] == "bench-left"

        service = client.app.state.service
        hand = service.session.hand
        monkeypatch.setattr(service, "settings",
                            dataclasses.replace(service.settings, mock=False))
        # The next session is a hand that names itself: another hand entirely.
        monkeypatch.setattr(type(hand), "board_hand_id",
                            property(lambda self: "ser-0001"))
        service._session_ready(service.session)

        assert client.get("/api/hands").json()["selected"] is None

    def test_a_pick_survives_a_reconnect_of_the_same_hand(self, client,
                                                          monkeypatch):
        hand_ids.add_id("bench-left", client.calibrations)
        hand_ids.add_id("bench-right", client.calibrations)
        client.post("/api/hands/select", json={"name": "bench-right"})
        service = client.app.state.service
        monkeypatch.setattr(service, "settings",
                            dataclasses.replace(service.settings, mock=False))
        service._session_ready(service.session)
        body = client.get("/api/hands").json()
        assert body["selected"] == "bench-right"
        assert body["in_use"] == "bench-right"
