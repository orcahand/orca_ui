"""config.yaml may leave the current limits to the motor family (orca_core 0.4.2)."""

import time

import pytest
import yaml
from orca_core.hand_config import OrcaHandConfig

from orca_ui.hand.service import HandService, ServiceError
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


def test_a_ceiling_below_the_calibration_current_is_refused_before_the_write():
    svc = _connected(_service(_config_left_to_the_family()))
    try:
        before = svc.session.hand.config.max_current
        floor = svc.session.hand.config.calibration_current
        with pytest.raises(ServiceError):
            svc.set_max_current(floor - 1)
        assert svc.session.hand.config.max_current == before
        assert svc.control_state()["max_current"] == before
    finally:
        svc.stop()
