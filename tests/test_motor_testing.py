"""Bench excitation tests: the chirp itself, the torque translation, and a
run against a stand-in hand that records what was commanded and restores the
motor afterwards.
"""

import csv
import json
import pathlib
import math
import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest

from orca_ui.hand import motor_models
from orca_ui.hand import motor_testing as mt
from orca_ui.hand.motor_testing import ChirpSpec, MotorTestError


def _spec(**over):
    base = dict(motor_id=1, mode="position", amplitude=0.5, f0_hz=1.0, f1_hz=10.0,
                duration_s=2.0, taper_s=0.25)
    base.update(over)
    return ChirpSpec(**base)


class TestSignal:
    def test_a_linear_sweep_ends_at_f1(self):
        spec = _spec()
        T = spec.duration_s
        dt = 1e-4
        f_end = (mt.chirp_phase(spec, T) - mt.chirp_phase(spec, T - dt)) / (2 * math.pi * dt)
        assert f_end == pytest.approx(spec.f1_hz, rel=1e-2)

    def test_an_exponential_sweep_ends_at_f1(self):
        spec = _spec(sweep="exponential")
        T = spec.duration_s
        dt = 1e-4
        f_end = (mt.chirp_phase(spec, T) - mt.chirp_phase(spec, T - dt)) / (2 * math.pi * dt)
        assert f_end == pytest.approx(spec.f1_hz, rel=1e-2)
        f_start = mt.chirp_phase(spec, dt) / (2 * math.pi * dt)
        assert f_start == pytest.approx(spec.f0_hz, rel=1e-2)

    def test_the_cosine_ramp_starts_and_ends_at_zero(self):
        spec = _spec()
        assert mt.envelope(spec, 0.0) == 0.0
        assert mt.envelope(spec, spec.duration_s) == pytest.approx(0.0)
        assert mt.envelope(spec, spec.taper_s / 2) == pytest.approx(0.5)
        assert mt.envelope(spec, spec.duration_s / 2) == 1.0
        assert abs(mt.chirp_value(spec, 0.0)) == 0.0

    def test_no_taper_is_full_amplitude_from_the_first_sample(self):
        spec = _spec(taper="none")
        assert mt.envelope(spec, 0.0) == 1.0

    def test_the_spec_rejects_what_the_runner_cannot_do(self):
        for bad in (dict(mode="velocity"), dict(amplitude=0.0), dict(f0_hz=-1.0),
                    dict(rate_hz=5.0), dict(taper_s=1.5), dict(sweep="log"),
                    dict(torque_unit="lbf"), dict(sweep="exponential", f1_hz=1.0),
                    dict(duration_s=float("nan"))):
            with pytest.raises(MotorTestError):
                _spec(**bad).validate()
        _spec().validate()


class TestTorqueToCurrent:
    def test_the_fit_is_inverted_within_its_range(self):
        model = motor_models.get("xc330-t288")
        for torque in (0.2, 0.4, 0.6):
            current_a, extrapolated = mt.current_a_for_torque(model, torque)
            assert not extrapolated
            assert model.torque_nm(current_a) == pytest.approx(torque, abs=1e-6)

    def test_the_sign_is_the_direction(self):
        model = motor_models.get("xc330-t288")
        plus, _ = mt.current_a_for_torque(model, 0.4)
        minus, _ = mt.current_a_for_torque(model, -0.4)
        assert minus == pytest.approx(-plus)

    def test_beyond_the_curve_is_clamped_and_flagged(self):
        model = motor_models.get("xc330-t288")
        lo, hi = model.torque_poly_current_range_a
        current_a, extrapolated = mt.current_a_for_torque(model, 5.0)
        assert current_a == pytest.approx(hi) and extrapolated
        current_a, extrapolated = mt.current_a_for_torque(model, 0.001)
        assert 0 < current_a < lo and extrapolated

    def test_a_model_with_no_curve_is_refused(self):
        model = motor_models.get(None)
        with pytest.raises(MotorTestError):
            mt.current_a_for_torque(model, 0.3)


class _Client:
    """Stand-in for the motor client: one motor that tracks its command."""

    def __init__(self, motor_ids, model_number=1220, mode=3, ceiling=500.0):
        self.motor_ids = list(motor_ids)
        self._model_numbers = {mid: model_number for mid in motor_ids}
        self._mode = {mid: mode for mid in motor_ids}
        self.ceiling = ceiling
        self.pos = {mid: 0.0 for mid in motor_ids}
        self.signed = []
        self.mode_writes = []
        self.last_read_ok = True
        self.fail_reads = 0

    def supports_current_control(self, mid):
        return self._model_numbers[mid] != 1080

    def operating_mode(self, mid):
        return self._mode[mid]

    def set_operating_mode(self, ids, value):
        for mid in ids:
            self._mode[mid] = value
        self.mode_writes.append((tuple(ids), value))

    def read_current_limits(self):
        return {mid: self.ceiling for mid in self.motor_ids}

    def write_desired_pos(self, ids, values):
        for mid, v in zip(ids, values):
            self.pos[mid] = float(v)

    def write_goal_current_signed(self, ids, values):
        assert all(self._mode[mid] == 0 for mid in ids)
        self.signed.append(float(values[0]))

    def read_position_velocity_current(self):
        if self.fail_reads:
            self.fail_reads -= 1
            self.last_read_ok = False
        else:
            self.last_read_ok = True
        pos = np.array([self.pos[mid] for mid in self.motor_ids])
        return SimpleNamespace(position=pos, velocity=np.zeros_like(pos),
                               current=np.full_like(pos, 42.0))


class _Hand:
    def __init__(self, client):
        self.motor_client = client
        self.config = SimpleNamespace(motor_ids=list(client.motor_ids), control_mode="position")
        self._motor_lock = threading.RLock()

    def get_motor_pos(self, as_dict=False):
        return dict(self.motor_client.pos)

    def write_motor_pos(self, ids, values):
        self.motor_client.write_desired_pos(ids, values)

    def set_control_mode(self, mode, ids=None):
        from orca_core.constants import MODE_MAP
        self.motor_client.set_operating_mode(ids or self.config.motor_ids, MODE_MAP[mode])


class _Service:
    def __init__(self, client):
        self.session = SimpleNamespace(hand=_Hand(client))
        self.published = []
        self.paused = []
        self.playback_stops = 0
        self._bench_ranges = {}
        self._bench_declared = {}

    def _require_torque(self):
        return self.session

    def _publish_topic(self, topic, payload):
        self.published.append((topic, payload))

    def pause_bench_telemetry(self, paused):
        self.paused.append(bool(paused))

    def stop_all_playback(self):
        self.playback_stops += 1
        return True

    def _reported_model_number(self, session, mid):
        return session.hand.motor_client._model_numbers.get(mid)


def _runner(tmp_path, client=None):
    client = client or _Client([1])
    service = _Service(client)
    runner = mt.ChirpRunner(service, tmp_path / "motortestingdata" / "bare")
    return runner, service, client


def _finish(runner):
    runner.join(timeout=10.0)
    state = runner.state()
    assert state["status"] != "running", state
    return state


class TestPositionRun:
    def test_a_run_records_what_it_commanded_and_saves_it(self, tmp_path):
        runner, service, client = _runner(tmp_path)
        client.pos[1] = -2.0
        spec = _spec(duration_s=0.3, taper_s=0.05, rate_hz=100.0, amplitude=0.4)

        runner.start(spec)
        state = _finish(runner)

        assert state["status"] == "done", state
        assert state["samples"] >= 20
        assert state["achieved_rate_hz"] > 50
        assert service.paused == [True, False]
        assert service.playback_stops == 1

        meta = json.loads((tmp_path / "motortestingdata" / "bare" / f"{state['run_id']}.json").read_text())
        assert meta["centre"] == -2.0
        assert meta["model"] == "xc330-t288"
        with (tmp_path / "motortestingdata" / "bare" / f"{state['run_id']}.csv").open() as f:
            rows = list(csv.reader(f))
        assert rows[0][1] == "command_rad"
        commands = [float(r[1]) for r in rows[1:]]
        assert all(-2.4 - 1e-9 <= c <= -1.6 + 1e-9 for c in commands)
        assert abs(commands[0] + 2.0) < 0.05, "a cosine ramp starts at the centre"
        assert runner.list_runs()[0]["run_id"] == state["run_id"]

        traces = [p for t, p in service.published if t == "testing.trace"]
        assert traces and traces[-1]["run_id"] == state["run_id"]

    def test_the_recorded_range_bounds_the_chirp(self, tmp_path):
        runner, service, client = _runner(tmp_path)
        service._bench_ranges[1] = (-4.0, -2.0)
        client.pos[1] = -2.2
        with pytest.raises(MotorTestError) as caught:
            runner.start(_spec(amplitude=0.5, duration_s=0.3, taper_s=0.1))
        assert "recorded range" in str(caught.value)

    def test_a_stop_ends_the_run_early(self, tmp_path):
        runner, service, client = _runner(tmp_path)
        runner.start(_spec(duration_s=30.0, taper_s=1.0, rate_hz=100.0))
        time.sleep(0.15)
        assert runner.stop()
        state = _finish(runner)
        assert state["status"] == "stopped"
        assert service.paused == [True, False]

    def test_two_runs_cannot_overlap(self, tmp_path):
        runner, _, _ = _runner(tmp_path)
        runner.start(_spec(duration_s=5.0, taper_s=0.5, rate_hz=50.0))
        with pytest.raises(MotorTestError):
            runner.start(_spec(duration_s=0.2, taper_s=0.05))
        runner.stop()
        _finish(runner)

    def test_lost_reads_abort_and_still_restore(self, tmp_path):
        client = _Client([1])
        client.fail_reads = 100
        runner, service, _ = _runner(tmp_path, client)
        runner.start(_spec(duration_s=5.0, taper_s=0.5, rate_hz=200.0))
        state = _finish(runner)
        assert state["status"] == "error"
        assert "read failures" in state["detail"]
        assert service.paused == [True, False]


class TestCurrentRun:
    def test_the_motor_is_switched_to_current_mode_and_back(self, tmp_path):
        runner, service, client = _runner(tmp_path)
        spec = _spec(mode="current", amplitude=200.0, duration_s=0.3, taper_s=0.05,
                     rate_hz=100.0, offset=50.0)
        runner.start(spec)
        state = _finish(runner)

        assert state["status"] == "done", state
        assert client.mode_writes == [((1,), 0), ((1,), 3)]
        assert client.signed[-1] == 0.0, "the run ends with the motor unloaded"
        peak = max(abs(v - 50.0) for v in client.signed)
        assert 150.0 < peak <= 200.0 + 1e-9
        assert state["spec"]["amplitude_ma"] == 200.0

    def test_torque_in_nm_goes_through_the_fitted_curve(self, tmp_path):
        runner, service, client = _runner(tmp_path)
        model = motor_models.get("xc330-t288")
        spec = _spec(mode="current", amplitude=0.4, torque_unit="nm", duration_s=0.2,
                     taper_s=0.05, rate_hz=100.0)
        state = runner.start(spec)
        expected_a, _ = mt.current_a_for_torque(model, 0.4)
        assert state["spec"]["amplitude_ma"] == pytest.approx(expected_a * 1000.0)
        assert state["spec"]["torque_extrapolated"] is False
        _finish(runner)

    def test_a_motor_without_current_control_is_refused(self, tmp_path):
        runner, _, _ = _runner(tmp_path, _Client([1], model_number=1080))
        with pytest.raises(MotorTestError) as caught:
            runner.start(_spec(mode="current", amplitude=100.0))
        assert "current control" in str(caught.value)

    def test_the_ceiling_is_respected_before_the_run_starts(self, tmp_path):
        runner, _, _ = _runner(tmp_path, _Client([1], ceiling=300.0))
        with pytest.raises(MotorTestError) as caught:
            runner.start(_spec(mode="current", amplitude=250.0, offset=100.0))
        assert "ceiling" in str(caught.value)

    def test_a_runaway_motor_aborts_the_run(self, tmp_path):
        client = _Client([1])
        runner, service, _ = _runner(tmp_path, client)

        original = client.read_position_velocity_current

        def drifting():
            client.pos[1] += 0.2
            return original()

        client.read_position_velocity_current = drifting
        runner.start(_spec(mode="current", amplitude=100.0, duration_s=5.0, taper_s=0.5,
                           rate_hz=200.0, position_envelope_rad=1.0))
        state = _finish(runner)
        assert state["status"] == "error"
        assert "envelope" in state["detail"]
        assert client.signed[-1] == 0.0
        assert client.mode_writes[-1] == ((1,), 3)


class TestService:
    def _service(self, bare=True, tmp_path=None):
        from orca_ui.hand.service import HandService
        from orca_ui.settings import UiSettings

        service = HandService.__new__(HandService)
        service.settings = UiSettings(config_path="/nowhere/config.yaml", bare=bare)
        service._bench_ranges = {1: (-3.0, -1.0)}
        service._bench_declared = {}
        service._motor_testing = None
        service._library_root = tmp_path or pathlib.Path('/nowhere')
        service.supervisor = SimpleNamespace(model_name='bare')
        client = _Client([1, 2])
        client._model_numbers[2] = 1080
        session = SimpleNamespace(hand=_Hand(client))
        service._require_motors = lambda: session
        service._require_torque = lambda: session
        return service, client

    def test_an_assembled_hand_cannot_run_an_excitation(self):
        from orca_ui.hand.service import ServiceError
        service, _ = self._service(bare=False)
        with pytest.raises(ServiceError) as caught:
            service.motor_test_candidates()
        assert caught.value.status_code == 409

    def test_candidates_say_what_each_motor_can_do(self):
        service, _ = self._service()
        motors = service.motor_test_candidates()
        by_id = {m["id"]: m for m in motors}
        assert by_id[1]["current_control"] and by_id[1]["torque_curve"]
        assert by_id[1]["range_rad"] == [-3.0, -1.0]
        assert not by_id[2]["current_control"]
        assert by_id[1]["ceiling_ma"] == 500.0

    def test_a_bad_request_is_a_service_error(self):
        from orca_ui.hand.service import ServiceError
        service, _ = self._service()
        with pytest.raises(ServiceError):
            service.start_motor_test({"motor_id": 1, "mode": "position", "amplitude": -1.0,
                                      "f0_hz": 1.0, "f1_hz": 2.0, "duration_s": 1.0})
        with pytest.raises(ServiceError):
            service.start_motor_test({"motor_id": 1, "nonsense": 3})

    def test_stopping_with_nothing_running_is_harmless(self):
        service, _ = self._service()
        assert service.stop_motor_test() is False
