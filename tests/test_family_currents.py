"""Current defaults remain unknown until the motor family is identified."""

from types import SimpleNamespace

import pytest

from orca_core.hand_config import _resolve_config_path
from orca_core.hardware.motor_factory import mock_motor_client_class
from orca_ui.hand.operations.calibrate import validate_calibrate_params
from orca_ui.hand.service import ServiceError
from orca_ui.server import create_app
from orca_ui.settings import UiSettings


@pytest.fixture
def service(tmp_path):
    # Construct the real app without starting its hardware lifecycle.
    settings = UiSettings(
        config_path=_resolve_config_path(None, model_version="v2",
                                         model_name="orcahand-right"),
        library_dir=str(tmp_path), open_browser=False, teleop_enabled=False,
    )
    return create_app(settings).state.service


def test_startup_and_model_change_before_motor_detection(service):
    for _ in range(2):
        state = service.control_state()
        assert state["max_current"] is None
        assert state["config_max_current"] is None
        assert state["max_current_floor"] is None
        calibration = service.hand_info()["calibration"]
        assert calibration["calibration_current"] is None
        assert calibration["wrist_calibration_current"] is None
        service._model_changed(service.supervisor.config)


def _connect(service, family):
    config = service.supervisor.config.with_family_currents(
        mock_motor_client_class(family))
    writes = []
    session = SimpleNamespace(
        hand=SimpleNamespace(config=config, set_max_current=writes.append),
        caps=SimpleNamespace(motors=True, tactile=False, feedback_loop=False),
        tactile_configuration=lambda: None,
    )
    service.supervisor._session = session
    service._session_ready(session)
    return session, writes


@pytest.mark.parametrize("family", ["dynamixel", "feetech"])
def test_connected_family_supplies_current_limits(service, family):
    session, writes = _connect(service, family)
    config = session.hand.config
    state = service.control_state()
    assert state["max_current"] == config.max_current
    assert state["config_max_current"] == config.max_current
    assert state["max_current_floor"] == config.calibration_current
    assert service.hand_info()["calibration"]["calibration_current"] == config.calibration_current

    service._apply_current_ceiling(session)
    assert writes == [config.max_current]
    with pytest.raises(ServiceError, match="at least"):
        service.set_max_current(config.calibration_current - 1)
    assert writes == [config.max_current]

    service.set_max_current(config.calibration_current)
    assert writes[-1] == config.calibration_current
    # The numeric config belongs to the session; the model file still says default.
    assert service.supervisor.config.max_current == "default"
    validated = validate_calibrate_params(service, {
        "calibration_current": config.calibration_current,
    })
    assert validated["calibration_current"] == config.calibration_current

    _connect(service, family)
    assert service.control_state()["max_current"] == config.calibration_current
    assert service.control_state()["config_max_current"] == config.max_current


def test_reconnecting_to_another_family_replaces_previous_current(service):
    session, _ = _connect(service, "dynamixel")
    service.set_max_current(session.hand.config.calibration_current)
    session, writes = _connect(service, "feetech")
    service._apply_current_ceiling(session)
    assert writes == [session.hand.config.max_current]
