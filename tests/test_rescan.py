"""Probing for declared hardware that did not turn up.

A hand can connect short-handed for reasons looking again will never fix — an
encoder pass that was never calibrated, an unplugged sensor chain. The
supervisor tries a few times and then stops, because the alternative is
opening serial ports every ten seconds for the life of the session. An
operator who has just fixed the cause asks for another look explicitly.
"""

from types import SimpleNamespace

import pytest

import orca_ui.hand.supervisor as supervisor_mod
from orca_ui.hand.supervisor import UPGRADE_PROBE_ATTEMPTS

from test_model_detection import build


class _Caps:
    def __init__(self, tactile=False, encoders=False, degraded=True):
        self.motors = True
        self.tactile = tactile
        self.encoders = encoders
        self.feedback_loop = encoders
        self.degraded = degraded
        self.declared = {"motors": True, "tactile": True, "encoders": True,
                         "feedback_loop": True}


class _Session:
    def __init__(self, refused=(), **kwargs):
        self.caps = _Caps(**kwargs)
        self.refused = tuple(refused)


@pytest.fixture()
def supervisor(monkeypatch):
    """Unstarted supervisor on a full-featured model, so tactile and encoders
    are both declared, with detection stubbed to find nothing new."""
    sup, _ = build("orcahand-full-right", pinned=True)
    probes = []
    monkeypatch.setattr(supervisor_mod, "run_detection",
                        lambda config, force=False: probes.append("probe"))
    # Nothing new on the bus: the probe completes and finds no upgrade.
    absent = SimpleNamespace(motor_port="/dev/motor",
                             sensing=SimpleNamespace(tactile=None, encoder=None))
    monkeypatch.setattr(supervisor_mod, "presence_from_detection",
                        lambda *a, **k: absent)
    return sup, probes


def test_probing_stops_after_a_few_tries(supervisor, caplog):
    sup, probes = supervisor
    session = _Session()
    sup._upgrade_probes_left = UPGRADE_PROBE_ATTEMPTS

    import logging
    with caplog.at_level(logging.WARNING, logger="orca_ui.hand.supervisor"):
        for _ in range(UPGRADE_PROBE_ATTEMPTS + 5):
            sup._rescan(session)

    assert len(probes) == UPGRADE_PROBE_ATTEMPTS
    assert sup._upgrade_probes_left == 0
    # Said once, at a level the console actually prints (it configures
    # logging at WARNING), naming what is missing and whose move it is.
    gave_up = [r for r in caplog.records if "no longer looking" in r.getMessage()]
    assert len(gave_up) == 1
    assert "tactile, encoders" in gave_up[0].getMessage()


def test_a_rescan_request_looks_again_without_dropping_the_session(supervisor):
    sup, probes = supervisor
    session = _Session()
    sup._upgrade_probes_left = 0
    sup._rescan(session)
    assert probes == []

    sup.request_rescan()
    assert sup._upgrade_probes_left == UPGRADE_PROBE_ATTEMPTS
    # The next tick probes rather than waiting out the period.
    assert sup._last_upgrade_probe == 0.0
    sup._rescan(session)
    assert len(probes) == 1


def test_a_healthy_session_is_never_probed_for_missing_hardware(supervisor):
    sup, probes = supervisor
    sup._upgrade_probes_left = UPGRADE_PROBE_ATTEMPTS

    for _ in range(3):
        sup._rescan(_Session(tactile=True, encoders=True, degraded=False))

    assert probes == []
    assert sup._upgrade_probes_left == UPGRADE_PROBE_ATTEMPTS


def test_status_names_what_is_missing_and_whether_it_is_still_looking(supervisor):
    sup, _ = supervisor
    sup._session = _Session()

    sup._upgrade_probes_left = UPGRADE_PROBE_ATTEMPTS
    status = sup.status()
    assert status.missing == ("tactile", "encoders")
    assert status.rescanning is True
    assert status.as_dict()["missing"] == ["tactile", "encoders"]

    sup._upgrade_probes_left = 0
    assert sup.status().rescanning is False

    # A session that got everything reports nothing missing.
    sup._session = _Session(tactile=True, encoders=True, degraded=False)
    assert sup.status().missing == ()


def test_the_health_tick_stops_probing_once_the_allowance_is_spent(supervisor,
                                                                   monkeypatch):
    """The gate is on the tick, not just inside _rescan: an exhausted session
    must not even reach the probe, which is what was opening ports every ten
    seconds for the life of the session."""
    sup, probes = supervisor
    sup._settings = SimpleNamespace(**{**sup._settings.__dict__, "mock": False})
    session = _Session()
    sup._session = session
    monkeypatch.setattr(sup, "_check_health", lambda s: None)

    sup._upgrade_probes_left = 1
    sup._last_upgrade_probe = 0.0
    sup._health_tick()
    assert len(probes) == 1

    # Allowance spent: later ticks do not probe however long they wait.
    sup._last_upgrade_probe = 0.0
    sup._health_tick()
    sup._last_upgrade_probe = 0.0
    sup._health_tick()
    assert len(probes) == 1

    # And the operator's request brings it back.
    sup.request_rescan()
    sup._health_tick()
    assert len(probes) == 2


def test_a_refused_device_is_never_called_reappeared(supervisor, monkeypatch):
    """The port of a refused device is right where it always was. Treating
    finding it as "the hardware appeared" tore the session down and rebuilt
    it every probe period, which is the reconnect loop this guards against."""
    sup, probes = supervisor
    present = SimpleNamespace(
        motor_port="/dev/motor",
        sensing=SimpleNamespace(tactile="/dev/oh", encoder="/dev/oh"))
    monkeypatch.setattr(supervisor_mod, "presence_from_detection",
                        lambda *a, **k: present)

    # Refused by the hand: the ports answer, the devices did not.
    sup._upgrade_probes_left = UPGRADE_PROBE_ATTEMPTS
    assert sup._rescan(_Session(refused=("tactile", "encoders"))) is None

    # Genuinely absent before and present now: that is a real upgrade.
    sup._upgrade_probes_left = UPGRADE_PROBE_ATTEMPTS
    assert sup._rescan(_Session()) == "missing hardware appeared — upgrading"


def test_nothing_probeable_means_nothing_is_probed(supervisor):
    """A hand whose every missing device was refused gets no allowance at all,
    so it never opens a port looking for what it has already been told."""
    sup, probes = supervisor
    sup._upgrade_probes_left = 0
    assert sup._probeable_devices(_Session(refused=("tactile", "encoders"))) == ()
    assert sup._probeable_devices(_Session(refused=("tactile",))) == ("encoders",)
    assert sup._probeable_devices(_Session()) == ("tactile", "encoders")


def test_a_rescan_on_refused_hardware_re_attempts_the_connection(supervisor):
    """A probe cannot undo a refusal; only connecting again can. The request
    therefore drops the session instead of scanning ports."""
    sup, _ = supervisor
    sup._session = _Session(refused=("encoders",))
    torn = []
    sup._teardown_session = lambda reason: torn.append(reason)

    sup.request_rescan()

    assert torn and "encoders" in torn[0]


def test_a_rescan_for_an_absent_device_only_re_arms_the_probes(supervisor):
    sup, _ = supervisor
    sup._session = _Session()
    torn = []
    sup._teardown_session = lambda reason: torn.append(reason)

    sup.request_rescan()

    assert torn == []
    assert sup._upgrade_probes_left == UPGRADE_PROBE_ATTEMPTS


def _ladder_refusals(monkeypatch, error):
    """Run the real connect ladder against fake hands whose sensing tiers all
    fail with ``error``, and report what it recorded as refused."""
    from orca_core.hand_config import _resolve_config_path

    from orca_ui.hand import sessions
    from orca_ui.hand.supervisor import load_config
    from orca_ui.settings import UiSettings

    class FakeHand:
        def __init__(self, sensing):
            self.config = SimpleNamespace(port="/dev/motor")
            self._sensing = sensing

        def connect(self, interactive=False):
            if self._sensing:
                raise error
            return True, "motors up"

        def is_connected(self):
            return True

        def disconnect(self):
            return True, "closed"

    monkeypatch.setattr(
        sessions, "_build_hand",
        lambda settings, config, feedback, tactile: FakeHand(feedback or tactile))
    config = load_config(_resolve_config_path(None, model_name="orcahand-full-right"))
    presence = SimpleNamespace(
        motor_port="/dev/motor",
        sensing=SimpleNamespace(tactile="/dev/oh", encoder="/dev/oh",
                                tactile_baudrate=None))
    declared = sessions.declared_capabilities(config, True, motors_enabled=True)
    session = sessions._connect_with_motors(
        UiSettings(config_path=config.config_path, open_browser=False),
        config, declared, presence)
    return session.refused


def test_a_stale_encoder_stream_counts_as_refused_too(monkeypatch):
    """orca_core raises a plain RuntimeError when the stream is there but too
    stale or chip-flagged to anchor against, and the typed error only when the
    anchors are missing. Keying on the type left the common case looking like
    absent hardware, which rebuilt the session every probe period."""
    from orca_core import JointFeedbackConnectError

    for error in (RuntimeError("stale stream"),
                  JointFeedbackConnectError("no anchors")):
        refused = _ladder_refusals(monkeypatch, error)
        assert "encoders" in refused and "tactile" in refused, error
