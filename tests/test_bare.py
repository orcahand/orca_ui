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
        sampler._last_bench_temp = float("-inf")
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

            def get_motor_temp(self, as_dict=False):
                return {1: 31.0, 2: 32.0}

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
        # test in the run. Playback also asks it whether torque is on.
        service.supervisor = SimpleNamespace(
            session=session,
            status=lambda: SimpleNamespace(torque_enabled=True),
        )
        return service, writes, torque

    def test_points_are_recorded_and_returned(self):
        service, _, _ = self._service()

        result = service.set_motor_points(1, [-3.0, -2.0, -1.0])

        assert result["points"] == [-3.0, -2.0, -1.0]
        assert service._bench_points[1] == [-3.0, -2.0, -1.0]

    def test_a_point_outside_the_found_range_is_still_recorded(self):
        """Recording happens by hand: a point is somewhere the motor was
        physically put, so it is reachable whatever the slider's range says.
        Refusing the set threw away a recording the operator had just made."""
        service, _, _ = self._service()
        service.set_motor_range(1, -4.0, -2.0)

        result = service.set_motor_points(1, [-3.0, -1.0])

        assert result["points"] == [-3.0, -1.0]

    def test_a_point_outside_the_motor_travel_is_still_refused(self):
        """Travel is physics, not preference."""
        from orca_ui.hand.service import ServiceError

        service, _, _ = self._service()
        service._require_motors().hand.motor_client.position_range_rad = (
            -6.2816513263917, 0.0)

        with pytest.raises(ServiceError) as caught:
            service.set_motor_points(1, [-3.0, 2.0])
        assert "outside this motor's travel" in str(caught.value)

    def test_a_typed_target_is_still_bounded_by_the_range(self):
        """The found range still governs what may be commanded by hand."""
        from orca_ui.hand.service import ServiceError

        service, _, _ = self._service()
        service.set_motor_range(1, -4.0, -2.0)

        with pytest.raises(ServiceError) as caught:
            service.set_motor_position(1, -1.0)
        assert "outside the range found" in str(caught.value)

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


class TestFeetechIdentification:
    """Read off a real chain: the wrist reports 4106 and the finger motors
    6922, so Feetech declarations can be cross-checked after all."""

    def test_the_wrist_number_identifies_its_model(self):
        from orca_ui.hand import motor_models

        assert motor_models.for_model_number(4106).key == "hls3930m"

    def test_the_finger_number_identifies_something(self):
        from orca_ui.hand import motor_models

        assert motor_models.for_model_number(6922) is not None

    def test_the_finger_number_identifies_the_confirmed_model(self):
        """6922 is the HLS2915M, confirmed against the hand. The datasheet
        does not print the number, so only that confirmation justifies it."""
        from orca_ui.hand import motor_models

        assert motor_models.for_model_number(6922).key == "hls2915m"
        assert motor_models.get("hls2915m").verifiable is True

    def test_the_generic_entry_claims_no_number(self):
        """It stands for a family, so identifying a servo as it would be a
        claim nothing supports."""
        from orca_ui.hand import motor_models

        assert motor_models.get("feetech-hls").model_numbers == ()
        assert motor_models.get("feetech-hls").verifiable is False

    def test_the_protection_register_is_never_used_as_a_ceiling(self):
        """Register 28 reads 450 raw (2925 mA) on a motor that stalls at
        1.5 A: it is a trip point, not a rating. Every catalogued ceiling has
        to sit below the motor's own stall figure."""
        from orca_ui.hand import motor_models

        for model in motor_models.catalogue():
            if model.ceiling_ma and model.stall_current_ma:
                assert model.ceiling_ma <= model.stall_current_ma, model.key


class TestBenchTemperature:
    """The loopless hand's ordinary telemetry is held to one read every ten
    seconds, which on a bench reads as a temperature that only moves when
    something is clicked."""

    def test_temperature_rides_the_bench_tick(self):
        sampler, session, published = TestBenchTelemetry()._sampler(True)

        sampler._bench_tick(session)

        _topic, payload = published[0]
        assert payload["temps"] == {1: 31.0, 2: 32.0}

    def test_it_is_read_far_slower_than_current(self):
        """A bus round trip of its own, for a quantity that moves over
        minutes."""
        from orca_ui.hand.telemetry import BENCH_TELEMETRY_HZ, BENCH_TEMP_HZ

        assert BENCH_TEMP_HZ < BENCH_TELEMETRY_HZ

    def test_a_temperature_read_failure_does_not_lose_the_rest(self):
        """Position and current are the reason the tick exists."""
        sampler, session, published = TestBenchTelemetry()._sampler(True)

        def boom(as_dict=False):
            raise OSError("bus")

        session.hand.get_motor_temp = boom
        sampler._bench_tick(session)

        _topic, payload = published[0]
        assert payload["positions"] and payload["currents"]


class TestPlaybackStops:
    """Playback writes goal positions on its own timer, so anything meaning
    "stop moving" has to reach it. Torque off and e-stop both did not, which
    left a sequence writing into a limp motor and snapping it to the next
    point the moment torque came back."""

    def _service(self, torque=True):
        from orca_ui.hand.service import HandService
        from orca_ui.settings import UiSettings

        writes: list = []

        class _Hand:
            motor_client = SimpleNamespace(position_range_rad=None)
            config = SimpleNamespace(motor_ids=[1])

            def get_motor_pos(self, as_dict=False):
                return {1: -3.0}

            def write_motor_pos(self, ids, values):
                writes.append(float(values[0]))

            def disable_torque(self, ids=None):
                pass

        service = HandService.__new__(HandService)
        service.settings = UiSettings(config_path="/nowhere/config.yaml", bare=True)
        service._state_lock = threading.Lock()
        service._bench_points = {1: [-3.0, -2.0]}
        service._bench_playing = {1: 0}
        service._bench_ranges = {}
        session = SimpleNamespace(hand=_Hand(),
                                  caps=SimpleNamespace(motors=True))
        service.supervisor = SimpleNamespace(
            session=session,
            status=lambda: SimpleNamespace(torque_enabled=torque),
            set_torque_flag=lambda v: None,
        )
        return service, writes

    def test_a_step_with_torque_off_writes_nothing(self):
        service, writes = self._service(torque=False)

        assert service._bench_step() is False
        assert writes == []

    def test_torque_off_leaves_nothing_playing(self):
        """Otherwise it resumes the instant torque comes back."""
        service, _ = self._service(torque=False)

        service._bench_step()

        assert service._bench_playing == {}

    def test_stop_all_reports_what_it_stopped(self):
        service, _ = self._service()

        assert service.stop_all_playback() == 1
        assert service.stop_all_playback() == 0

    def test_a_step_with_torque_on_still_writes(self):
        """The guard must not stop ordinary playback."""
        service, writes = self._service(torque=True)

        assert service._bench_step() is True
        assert writes == [-3.0]


class TestAppendingPoints:
    """Building a sequence by driving to each spot, rather than posing the
    motor by hand. The browser appends to what is already stored, so the
    backend has to accept a growing set without losing order."""

    def test_points_keep_the_order_they_were_added_in(self):
        """A cycle runs them in order, so appending must not sort or dedupe."""
        service, _, _ = TestRecordedPoints()._service()

        service.set_motor_points(1, [-3.0])
        service.set_motor_points(1, [-3.0, -1.0])
        result = service.set_motor_points(1, [-3.0, -1.0, -2.0])

        assert result["points"] == [-3.0, -1.0, -2.0]

    def test_the_same_position_twice_is_kept(self):
        """Returning to a spot mid-cycle is a legitimate thing to record."""
        service, _, _ = TestRecordedPoints()._service()

        result = service.set_motor_points(1, [-3.0, -1.0, -3.0])

        assert result["points"] == [-3.0, -1.0, -3.0]

    def test_appending_past_the_travel_is_still_refused(self):
        from orca_ui.hand.service import ServiceError

        service, _, _ = TestRecordedPoints()._service()
        service._require_motors().hand.motor_client.position_range_rad = (
            -6.2816513263917, 0.0)

        with pytest.raises(ServiceError):
            service.set_motor_points(1, [-3.0, 1.0])


class TestBenchFrames:
    """The bench follows the trajectory player's rules: commands per segment
    with a floor of one, and a sync point only where a frame is a recorded
    point. Pure arithmetic, so it is checked without a bus."""

    def _target(self, points, frame, steps):
        from orca_ui.hand.service import HandService

        return HandService._bench_target(points, frame, steps)

    def test_one_step_walks_the_points_directly(self):
        """What "no interpolation" has to mean: the only command issued for a
        segment is its endpoint, and the servo does the travelling."""
        points = [0.0, 1.0, 2.0]
        got = [self._target(points, f, 1) for f in range(4)]

        assert [round(v, 3) for v, _ in got] == [0.0, 1.0, 2.0, 0.0]
        assert all(arrives for _, arrives in got)

    def test_interpolation_lands_only_on_the_last_step(self):
        """Waiting at an intermediate step would make a glide stutter, so
        only the recorded point counts as arrival."""
        points = [0.0, 1.0]
        got = [self._target(points, f, 4) for f in range(5)]

        assert [round(v, 3) for v, _ in got] == [0.0, 0.25, 0.5, 0.75, 1.0]
        assert [a for _, a in got] == [True, False, False, False, True]

    def test_a_single_point_is_a_hold(self):
        """One point is somewhere to stay, so every frame restates it and a
        motor pushed off target comes back."""
        for steps in (1, 5):
            for frame in (0, 3, 11):
                value, _ = self._target([0.7], frame, steps)
                assert value == pytest.approx(0.7)

    def test_points_cycle_rather_than_running_once(self):
        points = [0.0, 1.0]
        values = [round(self._target(points, f, 1)[0], 3) for f in range(5)]

        assert values == [0.0, 1.0, 0.0, 1.0, 0.0]

    def test_interpolation_spans_the_wrap_back_to_the_first_point(self):
        """The closing segment is a segment like any other; leaving it
        uninterpolated would snap the motor home at full speed."""
        points = [0.0, 2.0]
        got = [self._target(points, f, 2) for f in range(5)]

        assert [round(v, 3) for v, _ in got] == [0.0, 1.0, 2.0, 1.0, 0.0]
        assert [a for _, a in got] == [True, False, True, False, True]


    def test_the_first_frame_is_an_approach_to_the_first_point(self):
        """A motor is wherever the operator left it when playback starts, so
        the opening point is somewhere to reach, not somewhere to leave."""
        for steps in (1, 4):
            value, arrives = self._target([-3.0, -2.0], 0, steps)
            assert value == pytest.approx(-3.0)
            assert arrives, "the approach is a sync point like any other"


class TestBenchDwellMatchesThePlayer:
    """A dwell the operator cannot shorten outlasts any settle cap they set,
    which makes the cap look broken when it is working exactly as asked."""

    def _service(self):
        from orca_ui.hand.service import HandService

        return HandService.__new__(HandService)

    def test_the_dwell_is_settable_rather_than_a_constant(self):
        s = self._service()
        s._state_lock = threading.RLock()
        result = s.set_bench_pacing(1, 50, 250)

        assert result["period_ms"] == 250
        assert s._bench_period_s == pytest.approx(0.25)

    def test_the_default_dwell_matches_the_trajectory_player(self):
        """Same control under a different panel, so an operator who has set
        one should find the other already familiar."""
        from orca_ui.hand import service as svc
        from orca_ui.hand.operations import player as pl

        assert svc.BENCH_DWELL_S == pytest.approx(pl.INTERP_STEP_PERIOD_S)

    def test_a_cap_shorter_than_the_dwell_is_the_case_that_matters(self):
        """The reported bug: a 50 ms cap under a 1.5 s dwell can never be
        observed, because the motor finishes during the dwell either way."""
        from orca_ui.hand import service as svc

        s = self._service()
        s._state_lock = threading.RLock()
        s.set_bench_pacing(1, 50, 100)

        assert s._bench_max_settle_ms / 1000.0 < s._bench_period_s
        assert s._bench_period_s <= svc.BENCH_MAX_PERIOD_S

    def test_the_bounds_match_the_trajectory_player(self):
        from orca_ui.hand import service as svc
        from orca_ui.hand.operations import player as pl

        assert svc.BENCH_MIN_PERIOD_S == pl.MIN_STEP_PERIOD_S
        assert svc.BENCH_MAX_PERIOD_S == pl.MAX_STEP_PERIOD_S

    def test_an_out_of_range_dwell_is_refused(self):
        from orca_ui.hand.service import ServiceError

        s = self._service()
        s._state_lock = threading.RLock()
        with pytest.raises(ServiceError):
            s.set_bench_pacing(1, None, 10)
        with pytest.raises(ServiceError):
            s.set_bench_pacing(1, None, 6000)

    def test_omitting_the_dwell_keeps_the_current_one(self):
        s = self._service()
        s._state_lock = threading.RLock()
        s.set_bench_pacing(1, None, 250)
        s.set_bench_pacing(4, None, None)

        assert s._bench_period_s == pytest.approx(0.25)
        assert s._bench_interp_steps == 4


class TestConfigRegisters:
    """The control table is a bare-bench control, and a write has to say what
    actually stuck rather than what was asked for."""

    def test_it_is_refused_on_an_assembled_hand(self, monkeypatch):
        """An id change there orphans a joint from joint_to_motor_map, and the
        hand loses it until the config is edited to match.

        monkeypatch, not a direct class assignment: HandService.session is a
        real property, so overwriting and deleting it strips the attribute
        from every test that runs afterwards.
        """
        from types import SimpleNamespace

        from orca_core.hardware.motor_factory import mock_motor_client_class
        from orca_ui.hand.service import HandService, ServiceError

        client = mock_motor_client_class("dynamixel")([1])
        client.connect()
        session = SimpleNamespace(
            hand=SimpleNamespace(motor_client=client),
            caps=SimpleNamespace(motors=True))
        service = HandService.__new__(HandService)
        service.settings = SimpleNamespace(bare=False)
        monkeypatch.setattr(HandService, "session",
                            property(lambda self: session))

        with pytest.raises(ServiceError, match="bare-bench"):
            service._config_client()

    def test_a_bare_bench_is_allowed(self, monkeypatch):
        from types import SimpleNamespace

        from orca_core.hardware.motor_factory import mock_motor_client_class
        from orca_ui.hand.service import HandService

        client = mock_motor_client_class("dynamixel")([1])
        client.connect()
        session = SimpleNamespace(
            hand=SimpleNamespace(motor_client=client),
            caps=SimpleNamespace(motors=True))
        service = HandService.__new__(HandService)
        service.settings = SimpleNamespace(bare=True)
        monkeypatch.setattr(HandService, "session",
                            property(lambda self: session))

        _, resolved = service._config_client()
        assert resolved is client

    def test_the_schema_is_what_the_family_declares(self):
        """Not a list the browser holds: a family without a setting sends no
        row for it."""
        from orca_core.hardware.motor_factory import motor_client_class

        dxl = {r.key for r in motor_client_class("dynamixel").config_registers}
        fee = {r.key for r in motor_client_class("feetech").config_registers}
        assert "return_delay_time" in dxl
        assert "return_delay_time" not in fee

    def test_the_rescan_reaches_every_id_a_change_can_use(self):
        """The startup scan stops at 25 to keep launch quick. A re-scan after
        an id change cannot: a motor sent to 30 writes fine, answers fine, and
        would be reported missing by a scan that never looks there."""
        from orca_ui.hand import bare as bare_mode

        assert bare_mode.FULL_ID_RANGE[1] > bare_mode.DEFAULT_ID_RANGE[1]
        assert bare_mode.FULL_ID_RANGE[1] >= 253

    def test_the_offered_ids_are_the_ids_a_rescan_can_find(self, monkeypatch):
        """Otherwise the dropdown offers a value that loses the motor."""
        from types import SimpleNamespace

        from orca_core.hardware.motor_factory import mock_motor_client_class
        from orca_ui.hand import bare as bare_mode
        from orca_ui.hand.service import HandService

        client = mock_motor_client_class("feetech")([1])
        client.connect()
        session = SimpleNamespace(
            hand=SimpleNamespace(motor_client=client),
            caps=SimpleNamespace(motors=True))
        service = HandService.__new__(HandService)
        service.settings = SimpleNamespace(bare=True)
        monkeypatch.setattr(HandService, "session",
                            property(lambda self: session))

        assert service.reachable_id_range() == bare_mode.FULL_ID_RANGE
        assert service.motor_config_schema()["id_range"] == list(
            bare_mode.FULL_ID_RANGE)

    def test_an_id_change_is_followed_without_a_bus_scan(self, tmp_path):
        """The write is already confirmed by a read-back at the new id, so
        rediscovering the motor would mean sweeping 254 ids at a bus timeout
        each -- ten seconds of maintenance to learn what is already known."""
        import yaml

        from orca_ui.hand import bare as bare_mode

        path = tmp_path / "config.yaml"
        path.write_text(yaml.safe_dump({
            "port": "/dev/cu.usbmodemXXXX", "motor_type": "feetech",
            "baudrate": 1_000_000, "motor_ids": [1, 2, 16],
            "joint_ids": ["motor_01", "motor_02", "motor_16"],
            "joint_to_motor_map": {"motor_01": 1, "motor_02": 2, "motor_16": 16},
            "joint_roms": {"motor_01": [0, 1], "motor_02": [0, 1],
                           "motor_16": [0, 1]},
            "neutral_position": {"motor_01": 0.5, "motor_02": 0.5,
                                 "motor_16": 0.5},
        }))

        out = yaml.safe_load(
            open(bare_mode.config_with_motor_id_changed(str(path), 16, 30)))

        assert out["motor_ids"] == [1, 2, 30]
        assert out["joint_ids"] == ["motor_01", "motor_02", "motor_30"]
        assert out["joint_to_motor_map"] == {"motor_01": 1, "motor_02": 2,
                                             "motor_30": 30}
        assert "motor_16" not in out["joint_roms"]
        assert out["joint_roms"]["motor_30"] == [0, 1]

    def test_what_the_scan_resolved_is_carried_across(self, tmp_path):
        """Port, family and baud were settled at startup; an id change says
        nothing about them and must not disturb them."""
        import yaml

        from orca_ui.hand import bare as bare_mode

        path = tmp_path / "config.yaml"
        path.write_text(yaml.safe_dump({
            "port": "/dev/cu.usbmodemXXXX", "motor_type": "feetech",
            "baudrate": 1_000_000, "motor_ids": [5],
            "joint_ids": ["motor_05"],
            "joint_to_motor_map": {"motor_05": 5},
        }))

        out = yaml.safe_load(
            open(bare_mode.config_with_motor_id_changed(str(path), 5, 9)))

        assert out["port"] == "/dev/cu.usbmodemXXXX"
        assert out["motor_type"] == "feetech"
        assert out["baudrate"] == 1_000_000
