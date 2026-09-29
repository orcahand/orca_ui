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
    def __init__(self, **kwargs):
        self.caps = _Caps(**kwargs)


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
