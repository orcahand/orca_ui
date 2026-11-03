"""Temporary per-hand folders: a plain start locks onto the first hand that
identifies itself, keeps its files in that hand's folder, and refuses any other
hand until the console restarts."""

import os

from orca_core import HandDetection
from orca_core.hand_config import _resolve_config_path
from orca_core.hardware.sensing.serial_discovery import OrcaBoardInfo

from orca_ui.cli import build_settings
from orca_ui.hand import supervisor as supervisor_module
from orca_ui.hand.states import HandState
from orca_ui.hand.supervisor import HandSupervisor
from orca_ui.settings import UiSettings


def detected(serial, model="orcahand-left", side="left", tactile=False):
    identity = OrcaBoardInfo(role="motor", side=side, serial=serial) if serial else None
    return HandDetection(model_name=model, side=side, has_tactile=tactile, has_encoders=False,
                         motor_port="/dev/motor", identity=identity)


def build(*, hand_folders=True):
    settings = UiSettings(config_path=_resolve_config_path(None, model_name="orcahand-right"),
                          model_pinned=not hand_folders, hand_folders=hand_folders,
                          mock=False, open_browser=False)
    return HandSupervisor(settings)


def folder(*parts):
    return os.path.join(os.environ["ORCA_HAND_FOLDERS"], *parts)


def test_a_hand_gets_its_own_folder_named_after_its_model():
    sup = build()
    assert sup._adopt_model(detected("ser-0000")) is True
    assert sup.config.config_path == folder("ser-0000", "orcahand-left", "config.yaml")
    assert sup.model_name == "orcahand-left"


def test_a_right_hand_on_the_starting_model_still_moves_to_its_folder():
    sup = build()
    assert sup._adopt_model(detected("ser-0000", "orcahand-right", "right")) is True
    assert sup.config.config_path == folder("ser-0000", "orcahand-right", "config.yaml")


def test_a_second_run_reuses_the_folder_and_keeps_its_files():
    build()._adopt_model(detected("ser-0000"))
    calibration = folder("ser-0000", "orcahand-left", "calibration.yaml")
    with open(calibration, "w") as f:
        f.write("marker: kept\n")
    sup = build()
    sup._adopt_model(detected("ser-0000"))
    assert sup.config.config_path == folder("ser-0000", "orcahand-left", "config.yaml")
    with open(calibration) as f:
        assert f.read() == "marker: kept\n"


def test_files_from_a_hand_set_up_by_hand_are_copied_in_and_left_in_place():
    os.makedirs(folder("ser-0000"))
    packaged = _resolve_config_path(None, model_name="orcahand-left")
    with open(packaged) as src, open(folder("ser-0000", "config.yaml"), "w") as dst:
        dst.write(src.read())
    with open(folder("ser-0000", "calibration.yaml"), "w") as f:
        f.write("marker: kept\n")

    sup = build()
    sup._adopt_model(detected("ser-0000"))

    with open(folder("ser-0000", "orcahand-left", "calibration.yaml")) as f:
        assert f.read() == "marker: kept\n"
    assert os.path.exists(folder("ser-0000", "calibration.yaml"))
    assert sup.config.config_path == folder("ser-0000", "orcahand-left", "config.yaml")


def test_another_hand_is_refused_until_the_console_restarts(monkeypatch):
    sup = build()
    sup._adopt_model(detected("ser-0000"))
    in_force = sup.config.config_path
    other = detected("ser-0001", "orcahand-right", "right")

    assert sup._adopt_model(other) is False
    assert sup.config.config_path == in_force

    monkeypatch.setattr(supervisor_module, "run_detection", lambda config, force=False: other)
    monkeypatch.setattr(sup, "_board_motor_bus_unresolved", lambda detection: False)
    monkeypatch.setattr(supervisor_module, "connect_session",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not connect")))
    assert sup._try_connect() > 0
    status = sup.status()
    assert status.state == HandState.DETECTING
    assert "ser-0001" in status.message and "Restart" in status.message
    assert sup.config.config_path == in_force


def test_a_locked_run_refuses_a_hand_with_no_identity_rather_than_sharing_its_folder():
    sup = build()
    sup._adopt_model(detected("ser-0000"))
    assert sup._is_other_hand(detected(None)) is True


def test_a_hand_with_no_serial_stays_on_the_packaged_model():
    sup = build()
    sup._adopt_model(detected(None, "orcahand-right", "right"))
    assert sup.config.config_path == _resolve_config_path(None, model_name="orcahand-right")
    assert sup._hand_folder_id is None


def test_nothing_plugged_in_locks_nothing():
    sup = build()
    nothing = HandDetection(model_name="orcahand-right", side="right", has_tactile=False, has_encoders=False)
    assert sup._adopt_model(nothing) is False
    assert sup._hand_folder_id is None


def test_a_model_named_on_the_command_line_uses_no_hand_folder():
    sup = build(hand_folders=False)
    packaged = sup.config.config_path
    assert sup._adopt_model(detected("ser-0000")) is False
    assert sup.config.config_path == packaged


def test_only_a_start_that_names_no_model_turns_hand_folders_on(monkeypatch, tmp_path):
    import orca_core.hand_factory as factory

    monkeypatch.setattr(factory, "detect_hand", lambda: detected("ser-0000"))
    config = tmp_path / "config.yaml"
    config.write_text("")
    assert build_settings([]).hand_folders is True
    assert build_settings(["--config", str(config)]).hand_folders is False
    assert build_settings(["--model", "orcahand-left"]).hand_folders is False
    assert build_settings(["--mock"]).hand_folders is False


def test_a_later_model_choice_stays_in_the_hands_folder():
    sup = build()
    sup._adopt_model(detected("ser-0000"))
    sup.select_model("orcahand-touch-left")
    assert sup.config.config_path == folder("ser-0000", "orcahand-touch-left", "config.yaml")


def test_a_model_chosen_before_the_hand_identifies_itself_moves_to_its_folder():
    sup = build()
    sup.select_model("orcahand-touch-left")
    assert sup._adopt_model(detected("ser-0000")) is True
    assert sup.config.config_path == folder("ser-0000", "orcahand-touch-left", "config.yaml")


def test_more_hardware_on_the_same_hand_stays_in_its_folder():
    sup = build()
    sup._adopt_model(detected("ser-0000"))
    assert sup._adopt_model(detected("ser-0000", "orcahand-touch-left", tactile=True), upgrade_only=True) is True
    assert sup.config.config_path == folder("ser-0000", "orcahand-touch-left", "config.yaml")
