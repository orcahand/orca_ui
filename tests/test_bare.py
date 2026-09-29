"""Bare motor mode: a bus scan, and a config describing only what answered.

The point of bare mode is bringing up motors that are not in a hand, so the
tests here care about two things: that the scan asks the cheap question first,
and that the config it synthesises is one orca_core will actually accept.
"""

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
