"""Pinning the console to one board — two consoles, two hands, one machine.

The pin's contract is ownership: a pinned supervisor probes and opens only
the pinned board's ports. The dangerous failure is silent fallback — the
pinned board is unplugged or held, a global probe finds the *other*
console's hand, and this console connects to (or hands an operation) a hand
it does not own.
"""

from orca_ui.hand import supervisor as supervisor_mod

from test_model_detection import build


def test_a_maintenance_hand_connects_on_the_leased_port(monkeypatch):
    """The lease resolved the motor port (scoped to a pinned board); the
    maintenance hand must not re-resolve it machine-wide."""
    import threading
    from types import SimpleNamespace

    import orca_core

    from orca_ui.hand.operations import hand_ops

    class FakeHand:
        def __init__(self, config_path):
            self.config = SimpleNamespace(port="auto")

        def connect(self, interactive=False):
            return True, "ok"

    monkeypatch.setattr(orca_core, "OrcaHand", FakeHand)
    hand = hand_ops.build_maintenance_hand("unused.yaml", threading.Event(),
                                           motor_port="/dev/cu.usbmodemPINNED")
    assert hand.config.port == "/dev/cu.usbmodemPINNED"


def test_a_pinned_board_never_falls_back_to_another_hand(monkeypatch):
    sup, _ = build("orcahand-right")
    sup.select_board("/dev/cu.usbmodemPINNED")
    assert sup.status().board_pinned == "/dev/cu.usbmodemPINNED"

    # The pinned board is gone; every machine-global probe is a trap.
    monkeypatch.setattr(supervisor_mod, "detect_pinned_board",
                        lambda pin: None)

    def forbidden(*args, **kwargs):
        raise AssertionError("machine-global probe while a board is pinned")

    monkeypatch.setattr(supervisor_mod, "run_detection", forbidden)
    monkeypatch.setattr(supervisor_mod, "probe_hardware", forbidden)
    monkeypatch.setattr("orca_ui.hand.detection.auto_detect_port", forbidden)

    # Connect ladder: wait for the pinned board, never take another hand.
    delay = sup._try_connect()
    assert sup.session is None
    assert delay > 0

    # Maintenance lease probe: an operation gets the pinned hand or nothing.
    presence = sup._probe_hardware()
    assert presence.motor_port is None
    assert presence.sensing.tactile is None
    assert presence.sensing.encoder is None
