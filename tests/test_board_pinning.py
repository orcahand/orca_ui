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
        def __init__(self, config):
            self.config = config

        def connect(self, interactive=False):
            return True, "ok"

    monkeypatch.setattr(orca_core, "OrcaHand", FakeHand)
    supervisor_config = SimpleNamespace(port="auto")
    hand = hand_ops.build_maintenance_hand(supervisor_config, threading.Event(),
                                           motor_port="/dev/cu.usbmodemPINNED")
    assert hand.config.port == "/dev/cu.usbmodemPINNED"
    assert supervisor_config.port == "auto"


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



def test_a_held_pin_is_re_detected_from_its_known_identity(monkeypatch):
    """Once the session holds the pinned motor CDC it cannot be probed, so a
    sensing port that was busy at connect is found from the board's identity."""
    from orca_core.hardware.sensing.serial_discovery import OrcaBoardInfo

    from orca_ui.hand import boards

    pin, mate = "/dev/cu.usbmodemAAA1", "/dev/cu.usbmodemAAA3"
    motor = OrcaBoardInfo(role="motor", side="right", hw_version=21, fw_version=2,
                          serial=None, board_id="0123456789ABCDEF", config=2000)
    sensor = OrcaBoardInfo(role="sensor", side="right", hw_version=21, fw_version=2,
                           serial=None, board_id="0123456789ABCDEF", config=2000)
    monkeypatch.setattr(boards, "oh_board_ports", lambda: [pin, mate])
    monkeypatch.setattr(boards, "probe_orca_info", lambda port: sensor if port == mate else None)
    monkeypatch.setattr(boards, "port_in_use", lambda port: port == pin)
    monkeypatch.setattr(boards, "detect_encoder_stream", lambda port: False)
    monkeypatch.setattr(boards, "_tactile_responds_at", lambda port, baud: True)

    assert boards.detect_pinned_board(pin) is None, "nothing known: a held pin stays unresolved"
    detection = boards.detect_pinned_board(pin, identity=motor)
    assert detection is not None
    assert detection.motor_port == pin and detection.sensing_port == mate
    assert detection.has_tactile and detection.probed_tactile



def test_a_pinned_console_starts_on_the_pinned_boards_model_not_another_hands(monkeypatch, tmp_path):
    """With two hands attached, the global probe answers with whichever board
    it meets first; a console pinned to one board must ask that board alone."""
    from types import SimpleNamespace

    from orca_ui import cli
    from orca_ui.hand import boards

    asked = []
    monkeypatch.setattr(boards, "detect_pinned_board",
                        lambda pin: asked.append(pin) or SimpleNamespace(model_name="orcahand-right"))
    import orca_core.hand_factory as factory
    monkeypatch.setattr(factory, "detect_hand",
                        lambda: (_ for _ in ()).throw(AssertionError("global detection must not run")))
    args = SimpleNamespace(config=None, bare=False, mock=False, model=None, side=None,
                           model_version=None, board="/dev/cu.usbmodemXXXX")
    path, pinned = cli.resolve_config_path(args)
    assert asked == ["/dev/cu.usbmodemXXXX"]
    assert path.endswith("orcahand-right/config.yaml") and not pinned
