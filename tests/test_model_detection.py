"""Model re-detection: the hand config follows the hardware, not startup.

The supervisor derives the model from what the boards report on every
detection pass, so a hand that was powered off when the UI started — or a
different hand plugged in later — is adopted rather than forced into the
guess the CLI made against an empty bus.
"""

from orca_core import HandDetection
from orca_core.hand_config import _resolve_config_path
from orca_core.hardware.sensing.serial_discovery import OrcaBoardInfo

from orca_ui.hand.supervisor import HandSupervisor
from orca_ui.settings import UiSettings

MOTOR_BOARD = OrcaBoardInfo(role="motor", side="left", serial="SN-1")


def detection(model: str, side: str, *, tactile: bool, encoders: bool,
              identity=MOTOR_BOARD) -> HandDetection:
    """A detection result as detect_hand() would return it."""
    return HandDetection(
        model_name=model,
        side=side,
        has_tactile=tactile,
        has_encoders=encoders,
        motor_port="/dev/motor" if identity is not None else None,
        sensing_port="/dev/oh" if (tactile or encoders) else None,
        identity=identity,
    )


NOTHING_PLUGGED_IN = detection("orcahand-right", "right", tactile=False,
                               encoders=False, identity=None)
FULL_LEFT = detection("orcahand-full-left", "left", tactile=True, encoders=True)
PLAIN_LEFT = detection("orcahand-left", "left", tactile=False, encoders=False)


def build(model: str = "orcahand-right", *, pinned: bool = False):
    """An unstarted supervisor on ``model``, plus the models it adopts."""
    adopted = []
    settings = UiSettings(
        config_path=_resolve_config_path(None, model_name=model),
        model_pinned=pinned, mock=False, open_browser=False)
    sup = HandSupervisor(
        settings, on_model_changed=lambda config: adopted.append(config))
    return sup, adopted


# ----- adoption rules -------------------------------------------------------


def test_adopts_the_model_the_boards_report():
    """The startup guess against a powered-off hand is revised, not kept."""
    sup, adopted = build("orcahand-right")

    assert sup._adopt_model(FULL_LEFT) is True

    assert sup.model_name == "orcahand-full-left"
    assert sup.config.type == "left"
    assert sup._declared["tactile"] and sup._declared["encoders"]
    assert [c.config_path for c in adopted] == [sup.config.config_path]


def test_a_pinned_model_is_never_revised():
    sup, adopted = build("orcahand-right", pinned=True)

    assert sup._adopt_model(FULL_LEFT) is False
    assert sup.model_name == "orcahand-right"
    assert adopted == []


# ----- adoption while a session holds ports ---------------------------------


# ----- the probe that drives them -------------------------------------------


# ----- one probe, two configs -----------------------------------------------


# ----- the connect path ------------------------------------------------------
