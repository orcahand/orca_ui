"""Direct current control on the bare bench: one motor under a signed goal
current, held until the next write, and always handed back to position
control by anything that stops the bench."""

import threading
from types import SimpleNamespace

import pytest

from orca_core.constants import MODE_MAP


class _Client:
    def __init__(self, ids, model=1220, mode=5, ceiling=910.0):
        self.ids = list(ids)
        self._model = {m: model for m in ids}
        self.mode = {m: mode for m in ids}
        self.ceiling = ceiling
        self.signed = []

    def supports_current_control(self, mid):
        return self._model[mid] != 1080

    def operating_mode(self, mid):
        return self.mode[mid]

    def set_operating_mode(self, ids, value):
        for m in ids:
            self.mode[m] = value

    def read_current_limits(self):
        return {m: self.ceiling for m in self.ids}

    def write_goal_current_signed(self, ids, values):
        assert all(self.mode[m] == 0 for m in ids), "signed current needs current mode"
        self.signed.append((tuple(ids), float(values[0])))

    def write_desired_pos(self, ids, values):
        pass


class _Hand:
    def __init__(self, client):
        self.motor_client = client
        self.config = SimpleNamespace(motor_ids=list(client.ids), control_mode="current_based_position")
        self._motor_lock = threading.RLock()
        self.torque_off = False

    def set_control_mode(self, mode, ids=None):
        self.motor_client.set_operating_mode(ids or self.config.motor_ids, MODE_MAP[mode])

    def get_motor_pos(self, as_dict=False):
        return {m: 0.0 for m in self.config.motor_ids}

    def write_motor_pos(self, ids, values):
        pass

    def disable_torque(self, ids=None):
        self.torque_off = True


def _service(bare=True):
    from orca_ui.hand.service import HandService
    from orca_ui.settings import UiSettings

    service = HandService.__new__(HandService)
    service.settings = UiSettings(config_path="/nowhere/config.yaml", bare=bare)
    service._state_lock = threading.Lock()
    service._direct_motor_mode = True
    service._bench_ranges = {}
    service._bench_points = {}
    service._bench_playing = {}
    service._bench_current_mode = {}
    client = _Client([5, 2])
    client._model[2] = 1080
    session = SimpleNamespace(hand=_Hand(client))
    service.supervisor = SimpleNamespace(session=session, model_name="bare")
    service._require_motors = lambda: session
    service._require_torque = lambda: session
    service._require_manual_control = lambda: None
    return service, client, session.hand


def test_entering_current_control_switches_the_mode_and_commands_zero():
    service, client, _ = _service()
    out = service.set_motor_control(5, "current")
    assert client.mode[5] == 0
    assert client.signed == [((5,), 0.0)]
    assert out["control"] == "current" and out["commanded_ma"] == 0.0 and out["ceiling_ma"] == 910.0


def test_a_current_is_held_and_clamped_to_the_ceiling():
    service, client, _ = _service()
    service.set_motor_control(5, "current")
    assert service.set_motor_current(5, 150.0)["ma"] == 150.0
    assert service.set_motor_current(5, -2000.0)["ma"] == -910.0
    assert client.signed[-1] == ((5,), -910.0)
    assert service._bench_current_mode[5]["ma"] == -910.0


def test_leaving_current_control_zeroes_and_restores_the_previous_mode():
    service, client, _ = _service()
    service.set_motor_control(5, "current")
    service.set_motor_current(5, 300.0)
    out = service.set_motor_control(5, "position")
    assert client.signed[-1] == ((5,), 0.0)
    assert client.mode[5] == 5
    assert out["control"] == "position" and out["commanded_ma"] is None


def test_a_position_write_is_refused_under_current_control():
    from orca_ui.hand.service import ServiceError
    service, _, _ = _service()
    service.set_motor_control(5, "current")
    with pytest.raises(ServiceError) as caught:
        service.set_motor_position(5, 0.5)
    assert caught.value.status_code == 409


def test_a_current_write_needs_current_control_first():
    from orca_ui.hand.service import ServiceError
    service, _, _ = _service()
    with pytest.raises(ServiceError) as caught:
        service.set_motor_current(5, 100.0)
    assert "switch it to current" in str(caught.value)


def test_a_motor_without_current_control_is_refused():
    from orca_ui.hand.service import ServiceError
    service, _, _ = _service()
    with pytest.raises(ServiceError):
        service.set_motor_control(2, "current")


def test_an_assembled_hand_has_no_direct_current_control():
    from orca_ui.hand.service import ServiceError
    service, _, _ = _service(bare=False)
    with pytest.raises(ServiceError) as caught:
        service.set_motor_control(5, "current")
    assert caught.value.status_code == 409


def test_everything_that_stops_the_bench_restores_position_control():
    service, client, hand = _service()
    service.set_motor_control(5, "current")
    service.set_motor_current(5, 200.0)
    service._leave_direct_current_control()
    assert client.mode[5] == 5
    assert client.signed[-1] == ((5,), 0.0)
    assert service._bench_current_mode == {}
    # idempotent with nothing under current control
    service._leave_direct_current_control()
