"""Model re-detection: the hand config follows the hardware, not startup.

The supervisor derives the model from what the boards report on every
detection pass, so a hand that was powered off when the UI started — or a
different hand plugged in later — is adopted rather than forced into the
guess the CLI made against an empty bus.
"""

import pytest
from orca_core import HandDetection
from orca_core.hand_config import _resolve_config_path
from orca_core.hardware.sensing.serial_discovery import OrcaBoardInfo

import orca_ui.hand.supervisor as supervisor_mod
from orca_ui.hand.detection import presence_from_detection
from orca_ui.hand.supervisor import HandSupervisor, load_config
from orca_ui.settings import UiSettings

MOTOR_BOARD = OrcaBoardInfo(role="motor", side="left", serial="SN-1")


def model_config(name: str):
    return load_config(_resolve_config_path(None, model_name=name))


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


def test_swapping_hands_switches_sides():
    sup, _ = build("orcahand-full-left")
    right = detection("orcahand-full-right", "right", tactile=True, encoders=True)

    assert sup._adopt_model(right) is True
    assert sup.model_name == "orcahand-full-right"


def test_empty_bus_keeps_the_last_known_hand():
    """detect_hand() degrades to the plain right model when nothing answers;
    unplugging a left hand must not silently make the UI a right hand."""
    sup, adopted = build("orcahand-full-left")

    assert sup._adopt_model(NOTHING_PLUGGED_IN) is False

    assert sup.model_name == "orcahand-full-left"
    assert adopted == []


def test_a_legacy_hand_is_adopted_despite_having_no_identity():
    """A legacy hand predates ORCA_ID?/ORCA_INFO? and so never has an
    identity, but its motor bus still resolves — that alone must be enough
    to tell it apart from an empty bus, or an unpinned legacy hand never
    gets its real (e.g. touch) model adopted at all."""
    sup, adopted = build("orcahand-right")
    legacy_touch = HandDetection(
        model_name="orcahand-touch-right", side="right",
        has_tactile=True, has_encoders=False,
        motor_port="/dev/cu.feetech", sensing_port=None, identity=None,
    )

    assert sup._adopt_model(legacy_touch) is True

    assert sup.model_name == "orcahand-touch-right"
    assert [c.config_path for c in adopted] == [sup.config.config_path]


def test_a_pinned_model_is_never_revised():
    sup, adopted = build("orcahand-right", pinned=True)

    assert sup._adopt_model(FULL_LEFT) is False
    assert sup.model_name == "orcahand-right"
    assert adopted == []


def test_same_model_is_not_re_adopted():
    sup, adopted = build("orcahand-full-left")
    assert sup._adopt_model(FULL_LEFT) is False
    assert adopted == []


# ----- adoption while a session holds ports ---------------------------------


def test_upgrade_only_accepts_a_richer_model():
    """Motors answered before the encoder stream was flowing: the model
    understates the hand and the later probe corrects it."""
    sup, _ = build("orcahand-left")
    assert sup._adopt_model(FULL_LEFT, upgrade_only=True) is True
    assert sup.model_name == "orcahand-full-left"


def test_upgrade_only_refuses_a_poorer_model():
    """Our own session holds the sensing link, so the probe reads it as
    absent. That says nothing about the hardware — never downgrade on it."""
    sup, adopted = build("orcahand-full-left")
    assert sup._adopt_model(PLAIN_LEFT, upgrade_only=True) is False
    assert sup.model_name == "orcahand-full-left"
    assert adopted == []


def test_upgrade_only_refuses_a_side_change():
    sup, _ = build("orcahand-left")
    right = detection("orcahand-full-right", "right", tactile=True, encoders=True)
    assert sup._adopt_model(right, upgrade_only=True) is False


# ----- the probe that drives them -------------------------------------------


class FakeSession:
    def __init__(self, degraded=False):
        self.caps = type("Caps", (), {"degraded": degraded})()


def test_rescan_confirms_the_model_then_stops(monkeypatch):
    """A bounded number of post-connect re-checks: enough to catch a
    capability that came up late, not an endless serial probe."""
    sup, _ = build("orcahand-left")
    calls = []
    monkeypatch.setattr(supervisor_mod, "run_detection",
                        lambda config, force=False: calls.append(force) or None)

    sup._model_probes_left = 2
    for _ in range(4):
        assert sup._rescan(FakeSession()) is None
    assert calls == [True, True]           # ran twice, then stopped probing


def test_rescan_reconnects_when_the_hand_reports_more(monkeypatch):
    sup, _ = build("orcahand-left")
    monkeypatch.setattr(supervisor_mod, "run_detection",
                        lambda config, force=False: FULL_LEFT)
    sup._model_probes_left = 1

    reason = sup._rescan(FakeSession())

    assert reason and "orcahand-full-left" in reason
    assert sup.model_name == "orcahand-full-left"


def test_rescan_is_idle_for_a_healthy_maximal_model(monkeypatch):
    """Nothing declared is missing and no richer model exists — don't probe."""
    sup, _ = build("orcahand-full-left")
    monkeypatch.setattr(supervisor_mod, "run_detection",
                        lambda config, force=False: pytest.fail("probed"))
    assert sup._model_is_maximal() is True
    assert sup._rescan(FakeSession()) is None


# ----- one probe, two configs -----------------------------------------------


def test_presence_is_re_read_against_the_adopted_config():
    """Adopting a model must not need a second trip to the serial bus: the
    same detection, read against the new config, yields its ports."""
    plain = model_config("orcahand-right")
    full = model_config("orcahand-full-left")

    # A plain config declares no sensing, so it discards the sensing ports...
    assert presence_from_detection(plain, FULL_LEFT).sensing.encoder is None
    # ...while the model the hardware actually named picks them up.
    rich = presence_from_detection(full, FULL_LEFT)
    assert rich.motor_port == "/dev/motor"
    assert rich.sensing.encoder == "/dev/oh"
    assert rich.sensing.tactile == "/dev/oh"


# ----- the connect path ------------------------------------------------------


def test_connect_derives_the_model_before_connecting(monkeypatch):
    """The hand is turned on after the UI started: the connect attempt that
    finds it also decides which hand it is."""
    sup, adopted = build("orcahand-right")
    seen = {}

    monkeypatch.setattr(supervisor_mod, "run_detection",
                        lambda config, force=False: FULL_LEFT)

    def fake_connect(settings, config, presence=None):
        seen["model"] = supervisor_mod.model_name_of(config)
        seen["encoder_port"] = presence.sensing.encoder
        raise supervisor_mod.SessionConnectError("not today")

    monkeypatch.setattr(supervisor_mod, "connect_session", fake_connect)

    sup._try_connect()

    assert seen == {"model": "orcahand-full-left", "encoder_port": "/dev/oh"}
    assert sup.model_name == "orcahand-full-left"
    assert len(adopted) == 1
