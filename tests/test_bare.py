"""Bare motor mode: a bus scan, and a config describing only what answered.

The point of bare mode is bringing up motors that are not in a hand, so the
tests here care about two things: that the scan asks the cheap question first,
and that the config it synthesises is one orca_core will actually accept.
"""

import threading
from types import SimpleNamespace

import pytest

from orca_ui.hand import bare


def _found(motor_id: int, baud: int = 1_000_000, model: str = "STS3215"):
    return {"id": motor_id, "baud_rate": baud, "model_name": model}


class TestScanOrder:
    def test_the_rate_the_hands_use_is_tried_first(self, monkeypatch):
        """A scan that started at the bottom of the baud list would cost a
        minute before reaching the rate every packaged hand runs at."""
        asked: list[tuple[str, int]] = []

        def fake_scan(motor_type, port, baud, id_range):
            asked.append((motor_type, baud))
            return []

        monkeypatch.setattr(bare, "scan_motors", fake_scan)
        bare.scan_bus("/dev/cu.usbmodemXXXX")

        assert asked, "nothing was scanned"
        assert {baud for _, baud in asked} == {bare.PREFERRED_BAUD}

    def test_the_default_scan_stays_in_the_low_id_range(self, monkeypatch):
        ranges: list[tuple[int, int]] = []
        monkeypatch.setattr(
            bare, "scan_motors",
            lambda t, p, b, id_range: ranges.append(id_range) or [])
        bare.scan_bus("/dev/cu.usbmodemXXXX")

        assert set(ranges) == {bare.DEFAULT_ID_RANGE}
        assert bare.DEFAULT_ID_RANGE[1] < bare.FULL_ID_RANGE[1]

    def test_a_hit_stops_the_scan(self, monkeypatch):
        """Motors on one bus share a rate and a protocol, so a hit settles both
        questions; carrying on could only cost time."""
        asked: list[tuple[str, int]] = []

        def fake_scan(motor_type, port, baud, id_range):
            asked.append((motor_type, baud))
            return [_found(3)] if len(asked) == 1 else [_found(9)]

        monkeypatch.setattr(bare, "scan_motors", fake_scan)
        scan = bare.scan_bus("/dev/cu.usbmodemXXXX", all_rates=True)

        assert len(asked) == 1
        assert scan.motor_ids == [3]

    def test_a_failing_family_does_not_abort_the_sweep(self, monkeypatch):
        """One family's driver raising (missing SDK, port refused at a rate)
        must not hide a motor the other family would have found."""
        def fake_scan(motor_type, port, baud, id_range):
            if motor_type == "dynamixel":
                raise OSError("no such device")
            return [_found(1)]

        monkeypatch.setattr(bare, "scan_motors", fake_scan)
        scan = bare.scan_bus("/dev/cu.usbmodemXXXX")

        assert scan.motor_ids == [1]
        assert scan.motor_type == "feetech"

    def test_rates_never_exceed_the_bus_we_run(self):
        """Both families advertise rates far above what any hand uses, and
        scanning one costs the same as scanning a real one."""
        for family in ("dynamixel", "feetech"):
            assert all(rate <= bare.PREFERRED_BAUD
                       for rate in bare._rates_for(family, True))

    def test_a_full_sweep_asks_for_more_rates_than_the_default(self):
        assert (len(bare._rates_for("feetech", True))
                > len(bare._rates_for("feetech", False)))


class TestSynthesizedConfig:
    def _scan(self, ids=(1, 7)):
        scan = bare.BareScan(port="/dev/cu.usbmodemXXXX")
        scan.motors = [bare.FoundMotor(i, 1_000_000, "STS3215", "feetech")
                       for i in ids]
        return scan

    def test_orca_core_accepts_it(self):
        """The invariant that motor, joint and map counts agree is what makes a
        motor subset impossible in a real config; one pseudo-joint per motor is
        how bare mode satisfies it without inventing a hand."""
        from orca_core.hand_factory import load_hand

        path = bare.synthesize_config(self._scan())
        hand = load_hand(config_path=path)
        hand.config.validate_config()

        assert hand.config.motor_ids == [1, 7]
        assert hand.config.joint_ids == ["motor_01", "motor_07"]
        assert hand.config.joint_to_motor_map == {"motor_01": 1, "motor_07": 7}

    def test_the_scan_result_is_pinned_not_left_to_autodetection(self):
        """Re-probing at connect could land on a different adapter than the one
        the operator was shown at startup."""
        from orca_core.hand_factory import load_hand

        hand = load_hand(config_path=bare.synthesize_config(self._scan()))

        assert hand.config.port == "/dev/cu.usbmodemXXXX"
        assert hand.config.motor_type == "feetech"
        assert hand.config.baudrate == 1_000_000

    def test_current_starts_capped(self):
        """Nothing is known about what a bare motor is attached to, and there
        is no calibration or range of motion to stop it winding into a stop."""
        from orca_core.hand_factory import load_hand

        hand = load_hand(config_path=bare.synthesize_config(self._scan()))

        assert hand.config.max_current == bare.BARE_MAX_CURRENT_MA
        assert bare.BARE_MAX_CURRENT_MA < 300

    def test_nothing_to_calibrate(self):
        from orca_core.hand_factory import load_hand

        hand = load_hand(config_path=bare.synthesize_config(self._scan()))

        assert hand.config.calibration_sequence == []
        assert not hand.config.has_joint_encoders

    def test_an_empty_scan_cannot_make_a_config(self):
        """Falling back to a packaged model would drive seventeen motors that
        are not there."""
        with pytest.raises(ValueError):
            bare.synthesize_config(bare.BareScan(port="/dev/cu.usbmodemXXXX"))

    def test_pseudo_joints_cannot_be_mistaken_for_real_ones(self):
        """Real joints are ``{finger}_{joint_type}``; anything reading these
        should be obviously in motor space."""
        name = bare.pseudo_joint(4)
        assert name == "motor_04"
        assert not any(name.startswith(f) for f in
                       ("thumb", "index", "middle", "ring", "pinky", "wrist"))


class TestMixedBaud:
    def test_two_rates_on_one_bus_is_reported(self):
        """Physically impossible on a shared line, so it means the scan was
        confused rather than that the bus is really split."""
        scan = bare.BareScan(port="/dev/cu.usbmodemXXXX")
        scan.motors = [
            bare.FoundMotor(1, 1_000_000, "STS3215", "feetech"),
            bare.FoundMotor(2, 500_000, "STS3215", "feetech"),
        ]
        assert scan.mixed_baud

    def test_one_rate_is_not(self):
        scan = bare.BareScan(port="/dev/cu.usbmodemXXXX")
        scan.motors = [bare.FoundMotor(i, 1_000_000, "STS3215", "feetech")
                       for i in (1, 2)]
        assert not scan.mixed_baud


class TestReport:
    def test_an_empty_scan_says_what_was_asked(self):
        """"Nothing found" has to distinguish a full sweep from a glance at one
        rate, or the operator cannot tell whether --scan-all is worth it."""
        scan = bare.BareScan(port="/dev/cu.usbmodemXXXX", id_range=(0, 25))
        scan.probed = [("feetech", 1_000_000)]

        text = bare.describe(scan)

        assert "no motors" in text and "0-25" in text and "1000k" in text

    def test_a_hit_names_the_motors_and_the_bus(self):
        scan = bare.BareScan(port="/dev/cu.usbmodemXXXX")
        scan.motors = [bare.FoundMotor(7, 1_000_000, "STS3215", "feetech")]

        text = bare.describe(scan)

        assert "7" in text and "feetech" in text and "STS3215" in text

    def test_the_payload_carries_every_motor(self):
        scan = bare.BareScan(port="/dev/cu.usbmodemXXXX")
        scan.motors = [bare.FoundMotor(i, 1_000_000, "STS3215", "feetech")
                       for i in (1, 2, 3)]

        payload = scan.as_dict()

        assert [m["id"] for m in payload["motors"]] == [1, 2, 3]
        assert payload["motor_type"] == "feetech"
        assert payload["mixed_baud"] is False


class TestBarePresence:
    def test_presence_comes_from_the_config_not_a_probe(self):
        """The startup scan already resolved the port; probing again at connect
        could only wander onto another adapter and contradict what the operator
        was shown."""
        from test_model_detection import build

        sup, _ = build("orcahand-right", pinned=True)
        object.__setattr__(sup.config, "port", "/dev/cu.usbmodemXXXX")

        presence = sup._bare_presence()

        assert presence.motor_port == "/dev/cu.usbmodemXXXX"
        assert presence.sensing.tactile is None
        assert presence.sensing.encoder is None


class TestBareSettings:
    """``--bare`` has to survive the trip through the CLI, not just the scan."""

    def test_the_flag_reaches_the_settings(self, monkeypatch, tmp_path):
        from orca_ui import cli

        config = tmp_path / "config.yaml"
        config.write_text("port: /dev/null\n")
        monkeypatch.setattr(cli, "_resolve_bare_config", lambda args: str(config))

        settings = cli.build_settings(["--bare", "--no-browser"])

        assert settings is not None, "build_settings returned nothing"
        assert settings.bare is True
        assert settings.config_path == str(config)

    def test_a_normal_start_is_not_bare(self, monkeypatch, tmp_path):
        from orca_ui import cli

        config = tmp_path / "config.yaml"
        config.write_text("port: mock\n")
        monkeypatch.setattr(cli, "resolve_config_path",
                            lambda args: (str(config), True))

        settings = cli.build_settings(["--no-browser"])

        assert settings.bare is False

    def test_the_scan_range_follows_scan_all(self, monkeypatch):
        """--scan-all is the difference between a second and two minutes, so
        the flag has to actually widen the range."""
        from orca_ui import cli

        seen = {}

        def fake_scan(port, *, id_range, all_rates, progress=None):
            seen["id_range"] = id_range
            seen["all_rates"] = all_rates
            scan = bare.BareScan(port=port, id_range=id_range)
            scan.motors = [bare.FoundMotor(1, 1_000_000, "STS3215", "feetech")]
            return scan

        monkeypatch.setattr(bare, "scan_bus", fake_scan)
        monkeypatch.setattr("orca_core.maintenance.motor_chain.resolve_port",
                            lambda port: "/dev/cu.usbmodemXXXX")

        cli._resolve_bare_config(cli.parse_args(["--bare"]))
        assert seen == {"id_range": bare.DEFAULT_ID_RANGE, "all_rates": False}

        cli._resolve_bare_config(cli.parse_args(["--bare", "--scan-all"]))
        assert seen == {"id_range": bare.FULL_ID_RANGE, "all_rates": True}

    def test_an_empty_bus_fails_loudly(self, monkeypatch):
        """Falling through to a packaged model would put seventeen motors on
        screen for a bus with none."""
        import pytest as _pytest

        from orca_ui import cli

        monkeypatch.setattr(
            bare, "scan_bus",
            lambda port, **kw: bare.BareScan(port=port))
        monkeypatch.setattr("orca_core.maintenance.motor_chain.resolve_port",
                            lambda port: "/dev/cu.usbmodemXXXX")

        with _pytest.raises(SystemExit) as caught:
            cli._resolve_bare_config(cli.parse_args(["--bare"]))
        assert "--scan-all" in str(caught.value)

    def test_no_adapter_says_so(self, monkeypatch):
        import pytest as _pytest

        from orca_ui import cli

        monkeypatch.setattr("orca_core.maintenance.motor_chain.resolve_port",
                            lambda port: None)

        with _pytest.raises(SystemExit) as caught:
            cli._resolve_bare_config(cli.parse_args(["--bare"]))
        assert "no serial adapter" in str(caught.value)


class TestReachableSpan:
    """A pseudo-joint range the motor cannot reach is not cosmetic: the raw
    count falls outside the servo's counts, clamps to one end of travel, and a
    torque-enabled motor drives into its stop."""

    def test_the_span_comes_from_the_client(self):
        from orca_core.hardware.motor_factory import motor_client_class

        for family in ("feetech", "dynamixel"):
            lo, hi = bare.travel_span_deg(family)
            declared = motor_client_class(family).position_range_rad
            assert lo < hi
            if declared is not None:
                import math
                assert lo == pytest.approx(math.degrees(declared[0]), abs=0.01)
                assert hi == pytest.approx(math.degrees(declared[1]), abs=0.01)

    def test_a_single_turn_family_gets_its_own_sign(self):
        """Feetech's whole travel is negative radians. A range symmetric about
        zero would put half of every command out of reach."""
        lo, hi = bare.travel_span_deg("feetech")
        assert hi <= 0 and lo < 0
        assert 359 <= (hi - lo) <= 361

    def test_the_synthesised_range_is_reachable(self):
        from orca_core.hardware.motor_factory import motor_client_class
        from orca_core.hand_factory import load_hand
        import math

        scan = bare.BareScan(port="/dev/cu.usbmodemXXXX")
        scan.motors = [bare.FoundMotor(1, 1_000_000, "STS3215", "feetech")]
        hand = load_hand(config_path=bare.synthesize_config(scan))

        lo_deg, hi_deg = hand.config.joint_roms_dict["motor_01"]
        lo_rad, hi_rad = motor_client_class("feetech").position_range_rad
        assert math.radians(lo_deg) >= lo_rad - 1e-3
        assert math.radians(hi_deg) <= hi_rad + 1e-3

    def test_neutral_is_mid_travel_not_an_end_stop(self):
        from orca_core.hand_factory import load_hand

        scan = bare.BareScan(port="/dev/cu.usbmodemXXXX")
        scan.motors = [bare.FoundMotor(1, 1_000_000, "STS3215", "feetech")]
        hand = load_hand(config_path=bare.synthesize_config(scan))

        lo, hi = hand.config.joint_roms_dict["motor_01"]
        assert hand.config.neutral_position["motor_01"] == pytest.approx(
            (lo + hi) / 2, abs=0.01)


class TestJointCommandsAreRefused:
    """Bare mode's joints stand in for motors and have no calibration behind
    them, so a joint target maps to whatever the mapping guesses. Hiding the
    sliders is not enough — the command path has to refuse."""

    def _service(self, bare_mode: bool):
        from orca_ui.hand.service import HandService
        from orca_ui.settings import UiSettings

        service = HandService.__new__(HandService)
        service.settings = UiSettings(config_path="/nowhere/config.yaml",
                                      bare=bare_mode)
        return service

    def test_bare_mode_refuses_a_joint_target(self, monkeypatch):
        from orca_ui.hand.service import ServiceError

        service = self._service(True)
        monkeypatch.setattr(type(service), "_require_torque",
                            lambda self: object(), raising=False)

        with pytest.raises(ServiceError) as caught:
            service.set_targets({"motor_01": 0.0})

        assert "bare motor mode" in str(caught.value)
        assert "direct motor control" in str(caught.value)

    def test_a_normal_hand_still_accepts_them(self, monkeypatch):
        """The guard must key on bare mode, not on the hand being uncalibrated:
        a real uncalibrated hand still has joints worth commanding."""
        service = self._service(False)
        monkeypatch.setattr(type(service), "_require_torque",
                            lambda self: object(), raising=False)

        # Past the bare guard it fails for its own reasons (no session state),
        # which is enough: the refusal is not the bare-mode one.
        with pytest.raises(Exception) as caught:
            service.set_targets({"index_mcp": 0.0})
        assert "bare motor mode" not in str(caught.value)


class TestBenchWrites:
    """Direct writes on a bench: the whole travel in one move, and a refusal
    rather than a clamp for anything outside it."""

    def _service(self, bare_mode: bool, position: float = -3.0):
        from orca_ui.hand.service import HandService
        from orca_ui.settings import UiSettings

        class _Client:
            position_range_rad = (-6.2816513263917, 0.0)

        writes: list = []

        class _Hand:
            motor_client = _Client()
            config = SimpleNamespace(motor_ids=[1])

            def get_motor_pos(self, as_dict=False):
                return {1: position}

            def write_motor_pos(self, ids, values):
                writes.append((list(ids), [float(v) for v in values]))

        service = HandService.__new__(HandService)
        service.settings = UiSettings(config_path="/nowhere/config.yaml",
                                      bare=bare_mode)
        service._state_lock = threading.Lock()
        service._direct_motor_mode = True
        service._bench_ranges = {}
        service._bench_points = {}
        service._bench_playing = {}
        session = SimpleNamespace(hand=_Hand())
        service._require_torque = lambda: session
        service._require_manual_control = lambda: None
        return service, writes

    def test_a_bench_move_may_cross_the_whole_travel(self):
        """The 0.8 rad cap exists so a slider cannot yank a tendon. A loose
        motor has no tendon, and a load test needs the far end."""
        service, writes = self._service(True, position=-3.0)

        service.set_motor_position(1, -0.1)

        assert writes == [([1], [-0.1])]

    def test_a_hand_still_gets_the_cap(self):
        from orca_ui.hand.service import ServiceError

        service, writes = self._service(False, position=-3.0)

        with pytest.raises(ServiceError) as caught:
            service.set_motor_position(1, -0.1)

        assert "capped" in str(caught.value)
        assert writes == []

    def test_a_target_outside_the_travel_is_refused_not_clamped(self):
        """The servo does not reject an out-of-range count, it clamps to the
        nearer end — so an unreachable target would drive into a stop."""
        from orca_ui.hand.service import ServiceError

        service, writes = self._service(True, position=-3.0)

        with pytest.raises(ServiceError) as caught:
            service.set_motor_position(1, 1.5)

        assert "outside this motor's travel" in str(caught.value)
        assert writes == []

    def test_both_ends_of_the_travel_are_reachable(self):
        for target in (-6.28, 0.0):
            service, writes = self._service(True, position=-3.0)
            service.set_motor_position(1, target)
            assert writes and writes[0][1] == [target]


class TestBenchTelemetry:
    """A bench watches the current while a motor pushes, so the usual pacing
    (one read per ten seconds on a loopless hand) is useless here."""

    def _sampler(self, bare_mode: bool):
        from orca_ui.hand.telemetry import TelemetryService

        published: list = []
        sampler = TelemetryService.__new__(TelemetryService)
        sampler._motor_health = {}
        sampler._last_bench_read = float("-inf")
        sampler._hub = SimpleNamespace(
            publish=lambda topic, payload: published.append((topic, payload)))
        sampler._service = SimpleNamespace(
            settings=SimpleNamespace(bare=bare_mode))

        class _Hand:
            motor_client = SimpleNamespace(max_operating_temp_c=70.0)

            def get_motor_pos(self, as_dict=False):
                return {1: -3.0, 2: -1.5}

            def get_motor_current(self, as_dict=False):
                return {1: 120.0, 2: 45.0}

        session = SimpleNamespace(hand=_Hand(),
                                  caps=SimpleNamespace(motors=True))
        return sampler, session, published

    def test_position_and_current_are_published_together(self):
        """Position alone cannot tell a motor pushing at its ceiling from one
        that has given up."""
        sampler, session, published = self._sampler(True)

        sampler._bench_tick(session)

        assert len(published) == 1
        _topic, payload = published[0]
        assert payload["positions"] == {1: -3.0, 2: -1.5}
        assert payload["currents"] == {1: 120.0, 2: 45.0}

    def test_the_rate_is_capped(self):
        """Back-to-back fast ticks must not turn into a bus read each."""
        from orca_ui.hand.telemetry import BENCH_TELEMETRY_HZ

        sampler, session, published = self._sampler(True)
        sampler._bench_tick(session)
        sampler._bench_tick(session)  # immediately again

        assert len(published) == 1
        assert BENCH_TELEMETRY_HZ >= 10

    def test_a_read_failure_is_survivable(self):
        sampler, session, published = self._sampler(True)

        def boom(as_dict=False):
            raise OSError("bus")

        session.hand.get_motor_current = boom
        sampler._bench_tick(session)

        assert published == []


class TestFoundRange:
    """A range the operator found by hand is the only meaningful frame for a
    motor bolted to something: the servo's full turn is not what it can travel."""

    def _service(self, position=-3.0):
        from orca_ui.hand.service import HandService
        from orca_ui.settings import UiSettings

        torque: list = []
        writes: list = []

        class _Client:
            position_range_rad = (-6.2816513263917, 0.0)

        class _Hand:
            motor_client = _Client()
            config = SimpleNamespace(motor_ids=[1, 2])

            def get_motor_pos(self, as_dict=False):
                return {1: position, 2: position}

            def write_motor_pos(self, ids, values):
                writes.append([float(v) for v in values])

            def enable_torque(self, ids=None):
                torque.append((tuple(ids or ()), True))

            def disable_torque(self, ids=None):
                torque.append((tuple(ids or ()), False))

        service = HandService.__new__(HandService)
        service.settings = UiSettings(config_path="/nowhere/config.yaml", bare=True)
        service._state_lock = threading.Lock()
        service._direct_motor_mode = True
        service._bench_ranges = {}
        service._bench_points = {}
        service._bench_playing = {}
        session = SimpleNamespace(hand=_Hand())
        service._require_motors = lambda: session
        service._require_torque = lambda: session
        service._require_manual_control = lambda: None
        return service, torque, writes

    def test_one_motor_can_be_loosened_alone(self):
        """Range finding needs this motor limp while its neighbours stay put,
        which whole-hand torque cannot express."""
        service, torque, _ = self._service()

        service.set_motor_torque(2, False)

        assert torque == [((2,), False)]

    def test_a_recorded_range_bounds_later_commands(self):
        service, _, writes = self._service()
        service.set_motor_range(1, -4.0, -2.0)

        service.set_motor_position(1, -3.0)
        assert writes == [[-3.0]]

        from orca_ui.hand.service import ServiceError
        with pytest.raises(ServiceError) as caught:
            service.set_motor_position(1, -1.0)
        assert "outside the range found" in str(caught.value)
        assert writes == [[-3.0]]

    def test_limits_may_be_given_in_either_order(self):
        """The operator sets whichever end they reach first."""
        service, _, _ = self._service()

        result = service.set_motor_range(1, -2.0, -4.0)

        assert result["range_rad"] == [-4.0, -2.0]

    def test_clearing_puts_the_motor_back_on_its_full_travel(self):
        service, _, writes = self._service()
        service.set_motor_range(1, -4.0, -2.0)

        service.set_motor_range(1, None, None)
        service.set_motor_position(1, -1.0)

        assert writes == [[-1.0]]

    def test_two_limits_at_the_same_place_are_refused(self):
        """A zero-width range would make the slider meaningless."""
        from orca_ui.hand.service import ServiceError

        service, _, _ = self._service()
        with pytest.raises(ServiceError) as caught:
            service.set_motor_range(1, -3.0, -3.0)
        assert "same position" in str(caught.value)

    def test_a_range_outside_the_travel_is_refused(self):
        from orca_ui.hand.service import ServiceError

        service, _, _ = self._service()
        with pytest.raises(ServiceError) as caught:
            service.set_motor_range(1, -8.0, -2.0)
        assert "outside the motor's travel" in str(caught.value)

    def test_the_range_rides_along_in_the_snapshot(self):
        service, _, _ = self._service()
        service.set_motor_range(1, -4.0, -2.0)

        assert service._bench_ranges[1] == (-4.0, -2.0)
        assert 2 not in service._bench_ranges

    def test_per_motor_torque_is_bare_mode_only(self):
        """On a hand, loosening one motor mid-chain is not a bench convenience,
        it drops a tendon."""
        from orca_ui.hand.service import ServiceError
        from orca_ui.settings import UiSettings

        service, _, _ = self._service()
        service.settings = UiSettings(config_path="/nowhere/config.yaml",
                                      bare=False)
        with pytest.raises(ServiceError):
            service.set_motor_torque(1, False)


class TestRecordedPoints:
    """Points captured by hand, then replayed: one is a place to hold, two or
    more is a cycle worth leaving running."""

    def _service(self, position=-3.0):
        from orca_ui.hand.service import HandService
        from orca_ui.settings import UiSettings

        writes: list = []
        torque: list = []

        class _Client:
            position_range_rad = (-6.2816513263917, 0.0)

        class _Hand:
            motor_client = _Client()
            config = SimpleNamespace(motor_ids=[1, 2])

            def get_motor_pos(self, as_dict=False):
                return {1: position, 2: position}

            def write_motor_pos(self, ids, values):
                writes.append((int(ids[0]), float(values[0])))

            def enable_torque(self, ids=None):
                torque.append((tuple(ids or ()), True))

            def disable_torque(self, ids=None):
                torque.append((tuple(ids or ()), False))

        service = HandService.__new__(HandService)
        service.settings = UiSettings(config_path="/nowhere/config.yaml", bare=True)
        service._state_lock = threading.Lock()
        service._direct_motor_mode = True
        service._bench_ranges = {}
        service._bench_points = {}
        service._bench_playing = {}
        service._bench_thread = None
        service._bench_stop = threading.Event()
        session = SimpleNamespace(hand=_Hand(),
                                  caps=SimpleNamespace(motors=True))
        service._require_motors = lambda: session
        service._require_torque = lambda: session
        service._require_manual_control = lambda: None
        # `session` is a property reading through the supervisor; give it one
        # rather than patching the class, which would leak into every other
        # test in the run.
        service.supervisor = SimpleNamespace(session=session)
        return service, writes, torque

    def test_points_are_recorded_and_returned(self):
        service, _, _ = self._service()

        result = service.set_motor_points(1, [-3.0, -2.0, -1.0])

        assert result["points"] == [-3.0, -2.0, -1.0]
        assert service._bench_points[1] == [-3.0, -2.0, -1.0]

    def test_a_point_outside_the_found_range_is_refused(self):
        """Recording happens by hand, so a point can land outside a range set
        earlier; catching it here beats discovering it mid-cycle."""
        from orca_ui.hand.service import ServiceError

        service, _, _ = self._service()
        service.set_motor_range(1, -4.0, -2.0)

        with pytest.raises(ServiceError) as caught:
            service.set_motor_points(1, [-3.0, -1.0])
        assert "outside the range found" in str(caught.value)
        assert 1 not in service._bench_points

    def test_playing_needs_points(self):
        from orca_ui.hand.service import ServiceError

        service, _, _ = self._service()
        with pytest.raises(ServiceError) as caught:
            service.set_motor_playback(1, True)
        assert "no recorded points" in str(caught.value)

    def test_a_cycle_advances_through_its_points(self):
        service, writes, _ = self._service()
        service.set_motor_points(1, [-3.0, -2.0])
        service._bench_playing[1] = 0

        service._bench_step()

        assert writes == [(1, -3.0)]
        assert service._bench_playing[1] == 1

    def test_a_single_point_keeps_being_written(self):
        """A motor pushed off a held point has to be driven back to it."""
        service, writes, _ = self._service()
        service.set_motor_points(1, [-3.0])
        service._bench_playing[1] = 7   # any index

        service._bench_step()

        assert writes == [(1, -3.0)]

    def test_clearing_points_stops_playback(self):
        service, _, _ = self._service()
        service.set_motor_points(1, [-3.0, -2.0])
        service._bench_playing[1] = 0

        service.set_motor_points(1, None)

        assert 1 not in service._bench_playing
        assert 1 not in service._bench_points

    def test_a_hand_on_the_slider_stops_the_sequence(self):
        """Otherwise the player fights the operator for the motor a second and
        a half later."""
        service, _, _ = self._service()
        service.set_motor_points(1, [-3.0, -2.0])
        service._bench_playing[1] = 0

        service.set_motor_position(1, -2.5)

        assert 1 not in service._bench_playing

    def test_playback_is_bare_mode_only(self):
        from orca_ui.hand.service import ServiceError
        from orca_ui.settings import UiSettings

        service, _, _ = self._service()
        service.set_motor_points(1, [-3.0])
        service.settings = UiSettings(config_path="/nowhere/config.yaml",
                                      bare=False)
        with pytest.raises(ServiceError):
            service.set_motor_playback(1, True)


class TestMultiTurnFamilies:
    """A multi-turn family declares no travel, which range finding does not
    need: the range comes from what the operator does by hand either way."""

    def test_a_family_with_no_declared_travel_still_gets_a_fallback_span(self):
        """The synthesised config still needs joint ranges, so a family with no
        single-turn limit gets one revolution rather than nothing."""
        lo, hi = bare.travel_span_deg("dynamixel")
        assert (lo, hi) == bare.FALLBACK_ROM_DEG
        assert hi - lo == 360

    def test_a_range_is_accepted_without_a_declared_travel(self, monkeypatch):
        """Nothing to validate against means the operator's limits stand."""
        from orca_ui.hand.service import HandService
        from orca_ui.settings import UiSettings

        class _Client:
            position_range_rad = None      # multi-turn

        class _Hand:
            motor_client = _Client()
            config = SimpleNamespace(motor_ids=[5])

        service = HandService.__new__(HandService)
        service.settings = UiSettings(config_path="/nowhere/config.yaml", bare=True)
        service._state_lock = threading.Lock()
        service._bench_ranges = {}
        service._bench_points = {}
        service._bench_playing = {}
        service._require_motors = lambda: SimpleNamespace(hand=_Hand())

        # Well outside any single turn, which is legitimate on a multi-turn bus.
        result = service.set_motor_range(5, 8.0, 12.0)

        assert result["range_rad"] == [8.0, 12.0]


class TestMotorDeclarations:
    """A servo answers a read of Goal Current with a plain zero whether or not
    the register exists, so nothing on the bus can say it is safe to write.
    The operator declares the model, and the servo's reported number checks it."""

    def _service(self, reported=None):
        from orca_ui.hand.service import HandService
        from orca_ui.settings import UiSettings

        written: list = []

        class _Client:
            position_range_rad = None
            _model_numbers = dict(reported or {})

            def write_desired_current(self, ids, values):
                written.append((list(ids), [float(v) for v in values]))

        class _Hand:
            motor_client = _Client()
            config = SimpleNamespace(motor_ids=[1, 2])

        service = HandService.__new__(HandService)
        service.settings = UiSettings(config_path="/nowhere/config.yaml", bare=True)
        service._state_lock = threading.Lock()
        service._bench_declared = {}
        session = SimpleNamespace(hand=_Hand())
        service._require_motors = lambda: session
        return service, session, written

    def test_an_undeclared_motor_gets_no_current_write(self):
        """Fail closed: the motor keeps whatever ceiling it powered up with."""
        service, session, written = self._service()

        service._apply_declared_ceiling(session, 150.0)

        assert written == []

    def test_a_declared_current_motor_is_written(self):
        service, session, written = self._service()
        service.declare_motor(1, "xc330-t288", "index")

        service._apply_declared_ceiling(session, 150.0)

        assert written == [([1], [150.0])]

    def test_a_model_without_the_register_is_left_alone(self):
        service, session, written = self._service()
        service.declare_motor(1, "dxl-1080", "wrist")
        service.declare_motor(2, "xc330-t288", "index")

        service._apply_declared_ceiling(session, 150.0)

        assert written == [([2], [150.0])]

    def test_the_ceiling_is_capped_by_the_model(self):
        service, session, written = self._service()
        service.declare_motor(1, "xc330-t288", "")

        service._apply_declared_ceiling(session, 5000.0)

        # 800 mA, its stall figure — not the 910 its Current Limit accepts.
        assert written == [([1], [800.0])]

    def test_a_declaration_the_servo_contradicts_is_flagged(self):
        """Only a human can say whether the label or the wiring is wrong, so
        the disagreement is reported rather than resolved."""
        service, _, _ = self._service(reported={1: 1080})

        result = service.declare_motor(1, "xc330-t288", "index")

        assert result["mismatch"] is True
        assert result["reported_model_number"] == 1080
        assert result["identified"]["key"] == "dxl-1080"

    def test_a_declaration_the_servo_agrees_with_is_not_flagged(self):
        service, _, _ = self._service(reported={1: 1220})

        result = service.declare_motor(1, "xc330-t288", "index")

        assert result["mismatch"] is False

    def test_an_unrecognised_number_cannot_contradict_anything(self):
        """A model nobody has added to the table is not evidence against the
        operator, it is just silence."""
        service, _, _ = self._service(reported={1: 4242})

        result = service.declare_motor(1, "xc330-t288", "index")

        assert result["mismatch"] is False
        assert result["identified"] is None

    def test_nicknames_survive_a_model_change(self):
        service, _, _ = self._service()
        service.declare_motor(1, "xc330-t288", "thumb spool")

        result = service.declare_motor(1, "dxl-1080", "thumb spool")

        assert result["nickname"] == "thumb spool"

    def test_an_unknown_model_key_is_refused(self):
        from orca_ui.hand.service import ServiceError

        service, _, _ = self._service()
        with pytest.raises(ServiceError):
            service.declare_motor(1, "not-a-model", "")

    def test_every_catalogue_entry_says_where_its_numbers_came_from(self):
        """A wrong entry writes to a register the motor may not have, so each
        one has to be auditable."""
        from orca_ui.hand import motor_models

        for model in motor_models.catalogue():
            assert model.source
            if model.has_current_control:
                assert model.max_current_ma and model.current_scale_ma

    def test_the_unknown_entry_claims_nothing(self):
        from orca_ui.hand import motor_models

        assert motor_models.UNKNOWN.has_current_control is False
        assert motor_models.get(None) is motor_models.UNKNOWN
        assert motor_models.get("nonsense") is motor_models.UNKNOWN


class TestDatasheetCeilings:
    """A bench holds a motor against a load, which is exactly where stall
    current cooks it. The continuous rating is the number to hand it."""

    def test_the_ceiling_is_the_continuous_rating_not_the_stall(self):
        from orca_ui.hand import motor_models

        hls2915 = motor_models.get("hls2915m")
        assert hls2915.rated_current_ma == 500.0
        assert hls2915.stall_current_ma == 1500.0
        assert hls2915.ceiling_ma == 500.0

    def test_a_model_with_no_published_rating_falls_back_to_stall(self):
        """ROBOTIS publishes no continuous rating for the XC330, so stall is
        the only thermal number available — and it is below what the Current
        Limit register would accept."""
        from orca_ui.hand import motor_models

        xc330 = motor_models.get("xc330-t288")
        assert xc330.rated_current_ma is None
        assert xc330.ceiling_ma == xc330.stall_current_ma
        assert xc330.ceiling_ma < xc330.max_current_ma

    def test_the_generic_hls_entry_is_the_most_conservative(self):
        """Without a model there is no datasheet, so it must not hand out more
        than the weakest catalogued HLS motor tolerates."""
        from orca_ui.hand import motor_models

        generic = motor_models.get("feetech-hls")
        named = [m for m in motor_models.catalogue()
                 if m.family == motor_models.FEETECH and m.key != "feetech-hls"]
        assert named
        assert generic.ceiling_ma == min(m.ceiling_ma for m in named)

    def test_no_entry_offers_the_bare_register_maximum(self):
        """2047 units at 6.5 mA is 13.3 A, which belongs to no motor here."""
        from orca_ui.hand import motor_models

        for model in motor_models.catalogue():
            if model.ceiling_ma is not None:
                assert model.ceiling_ma < 3000

    def test_the_declared_ceiling_clamps_to_the_rating(self):
        service, session, written = TestMotorDeclarations()._service()
        service.declare_motor(1, "hls2915m", "index")

        service._apply_declared_ceiling(session, 900.0)

        assert written == [([1], [500.0])]


class TestControlTableFacts:
    """Numbers taken from the manufacturers' control tables, kept honest about
    which kind of number each one is."""

    def test_the_register_limit_is_not_treated_as_a_thermal_limit(self):
        """The XC330's Current Limit accepts 910 mA but the motor stalls at
        800. An HLS register accepts 13.3 A and no motor here survives it."""
        from orca_ui.hand import motor_models

        xc330 = motor_models.get("xc330-t288")
        assert xc330.max_current_ma == 910.0
        assert xc330.stall_current_ma == 800.0
        assert xc330.ceiling_ma == 800.0

        hls = motor_models.get("hls2915m")
        assert hls.max_current_ma > 13000
        assert hls.ceiling_ma == 500.0

    def test_a_motor_without_the_register_offers_no_ceiling(self):
        """Its stall current is a real number, but there is nothing to write
        it to."""
        from orca_ui.hand import motor_models

        wrist = motor_models.get("dxl-1080")
        assert wrist.stall_current_ma == 1400.0
        assert wrist.has_current_control is False
        assert wrist.ceiling_ma is None

    def test_the_wrist_does_not_accept_current_based_position(self):
        """Its Operating Mode takes only 1, 3, 4 and 16. Writing 5 would put
        an unsupported value into EEPROM."""
        from orca_ui.hand import motor_models

        assert motor_models.get("dxl-1080").supports_mode(5) is False
        assert motor_models.get("dxl-1080").supports_mode(4) is True
        assert motor_models.get("xc330-t288").supports_mode(5) is True

    def test_unrecorded_modes_are_not_permission(self):
        from orca_ui.hand import motor_models

        assert motor_models.UNKNOWN.supports_mode(5) is None

    def test_every_catalogued_model_records_its_modes(self):
        from orca_ui.hand import motor_models

        for model in motor_models.catalogue():
            if model.key != motor_models.UNKNOWN_KEY:
                assert model.operating_modes, model.key
