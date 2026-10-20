"""config.yaml may leave the current limits to the motor family (orca_core 0.4.2)."""

import time

import pytest
import yaml
from orca_core.hand_config import OrcaHandConfig

from orca_ui.hand.service import HandService
from orca_ui.mock import materialize_mock_model
from orca_ui.settings import UiSettings

pytestmark = pytest.mark.skipif(
    not hasattr(OrcaHandConfig, "with_family_currents"),
    reason="this orca_core has no family current defaults",
)


def _wait_for(predicate, timeout=5.0, interval=0.02):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def _config_left_to_the_family(motor_type=None):
    path = materialize_mock_model()
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    raw["max_current"] = "default"
    raw["calibration_current"] = "default"
    raw.pop("wrist_calibration_current", None)
    if motor_type is None:
        raw.pop("motor_type", None)
    else:
        raw["motor_type"] = motor_type
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(raw, f)
    return path


def _service(config_path):
    settings = UiSettings(config_path=config_path, mock=True, open_browser=False)
    return HandService(settings, publish_status=lambda s: None, publish_error=lambda e: None)


def _connected(svc):
    svc.start()
    assert _wait_for(lambda: svc.status()["state"] == "connected"), svc.status()
    return svc


def test_service_starts_without_a_family_and_learns_the_limit_on_connect():
    svc = _service(_config_left_to_the_family())
    try:
        assert svc.control_state()["max_current"] is None
        _connected(svc)
        resolved = svc.session.hand.config.max_current
        assert isinstance(resolved, int)
        assert _wait_for(lambda: svc.control_state()["max_current"] == resolved)
    finally:
        svc.stop()


def test_a_yaml_that_names_the_family_resolves_before_connect():
    # Never started, so nothing to stop: the values are known at construction.
    svc = _service(_config_left_to_the_family(motor_type="feetech"))
    assert svc.control_state()["max_current"] == 900
    assert svc.supervisor.config.calibration_current == 900


def test_a_ceiling_below_the_familys_calibration_current_is_accepted():
    """The family's two defaults are equal, and calibration follows the
    ceiling, so lowering it is not a configuration clash."""
    svc = _connected(_service(_config_left_to_the_family()))
    try:
        lower = svc.session.hand.config.calibration_current - 1
        svc.set_max_current(lower)
        assert svc.session.hand.config.max_current == lower
        assert svc.session.hand.config.calibration_current == lower
        assert svc.control_state()["max_current"] == lower
    finally:
        svc.stop()


def test_the_v21_group_table_does_not_outrank_the_ceiling_the_console_sets():
    """A model shipping a calibration current per joint group drives some
    groups above ``max_current`` — nothing validates the two against each
    other. A ceiling typed into the console replaces the table outright, so
    every joint is driven onto its hardstops at the figure the operator chose."""
    path = _config_left_to_the_family(motor_type="dynamixel")
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    raw["hardware_version"] = 21
    raw["calibration_current_v21"] = {"dynamixel": {"abd": 300, "mcp": 500, "pip": 500}}
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(raw, f)

    svc = _connected(_service(path))
    try:
        config = svc.session.hand.config
        assert config.calibration_group_currents == {"abd": 300, "mcp": 500, "pip": 500}
        assert config.calibration_current_for("index_mcp") == 500

        svc.set_max_current(420)
        config = svc.session.hand.config
        assert config.calibration_group_currents == {}
        assert all(config.calibration_current_for(joint) == 420
                   for joint in ("index_abd", "index_mcp", "index_pip", "wrist"))
    finally:
        svc.stop()
