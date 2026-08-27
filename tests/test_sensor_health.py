"""sensors.health payload tests: encoder verdicts, tactile state, link stats.

The monitor is a windowed accumulator: frames fed between two ``payload``
calls decide that window's verdicts, and each ``payload`` closes the window.
Verdict mapping mirrors orca_core's monitor_sensors.py: healthy -> live,
parity beats chip error, a rail-stuck slot reads as "no encoder", and a
window with no frames at all reads "no frames".
"""

import numpy as np
from orca_core.hardware.hand_serial_link import LinkStats
from orca_core.hardware.sensing.constants import (
    AUTO_ENC_ANGLE_MASK,
    AUTO_ENC_NUM_JOINTS,
    ENCODER_LSB_DEG,
    JOINT_TO_ENCODER_SLOT,
)
from orca_core.hardware.sensing.types import EncoderReading, LinkHealth

from orca_ui.hand.telemetry import SensorHealthMonitor


def _reading(ts: float, counts=None, parity_ok=None, angle_error=None):
    n = AUTO_ENC_NUM_JOINTS
    return EncoderReading(
        raw_counts=np.asarray(counts if counts is not None else [0x2000] * n,
                              dtype=np.uint16),
        parity_ok=np.asarray(parity_ok if parity_ok is not None else [True] * n),
        angle_error=np.asarray(angle_error if angle_error is not None
                               else [False] * n),
        error_byte=0,
        timestamp=ts,
    )


class _Caps:
    def __init__(self, encoders=True, tactile=False):
        self.encoders = encoders
        self.tactile = tactile
        self.motors = False
        self.feedback_loop = False


class _Session:
    def __init__(self, encoders=True, tactile=False):
        self.caps = _Caps(encoders, tactile)


def test_healthy_slots_read_live_with_decoded_angles():
    monitor = SensorHealthMonitor()
    counts = [0x2000] * AUTO_ENC_NUM_JOINTS
    for i in range(5):
        monitor.feed(_reading(float(i), counts))
    payload = monitor.payload(_Session())

    enc = payload["encoders"]
    assert enc["present"] and enc["live"] == AUTO_ENC_NUM_JOINTS
    joint, slot = next(iter(JOINT_TO_ENCODER_SLOT.items()))
    entry = enc["joints"][joint]
    assert entry["verdict"] == "live"
    assert entry["deg"] == round((0x2000 & AUTO_ENC_ANGLE_MASK) * ENCODER_LSB_DEG, 2)
    assert entry["slot"] == slot


def test_parity_chip_error_and_rail_verdicts():
    monitor = SensorHealthMonitor()
    parity_ok = [True] * AUTO_ENC_NUM_JOINTS
    angle_err = [False] * AUTO_ENC_NUM_JOINTS
    counts = [0x2000] * AUTO_ENC_NUM_JOINTS
    parity_ok[0] = False   # slot 0: parity errors
    angle_err[1] = True    # slot 1: chip angle-error flag
    counts[2] = 0x0000     # slot 2: stuck at a rail -> no encoder chip there
    for i in range(10):
        monitor.feed(_reading(float(i), counts, parity_ok, angle_err))
    joints = monitor.payload(_Session())["encoders"]["joints"]

    by_slot = {j["slot"]: j["verdict"] for j in joints.values()}
    assert by_slot[0] == "parity"
    assert by_slot[1] == "chip error"
    assert by_slot[2] == "no encoder"
    assert by_slot[3] == "live"


def test_window_with_no_frames_reads_no_frames():
    monitor = SensorHealthMonitor()
    monitor.feed(_reading(1.0))
    monitor.payload(_Session())  # closes the fed window

    # get_latest keeps returning the same stale frame; same timestamp must
    # not count as new data.
    monitor.feed(_reading(1.0))
    joints = monitor.payload(_Session())["encoders"]["joints"]
    assert all(j["verdict"] == "no frames" for j in joints.values())


def test_tactile_and_link_sections():
    class _Cfg:
        connected = {"thumb": True, "index": False}
        num_taxels = {"thumb": 16}

    class _TacStats:
        frames_ok = 100
        stream_rearms = 2

    session = _Session(encoders=False, tactile=True)
    stats = LinkStats()
    stats.bad_header_resyncs = 3
    stats.frames_bad_lrc["0xA9"] = 4
    session.tactile_configuration = lambda: _Cfg()
    session.tactile_stats = lambda: _TacStats()
    session.sensing_link_health = lambda: {
        "tactile": LinkHealth(connected=True, port_dead=False,
                              port_error=None, stats=stats),
    }

    payload = SensorHealthMonitor().payload(session)
    assert payload["encoders"] is None
    tac = payload["tactile"]
    assert tac["fingers"] == {
        "thumb": {"connected": True, "taxels": 16},
        "index": {"connected": False, "taxels": 0},
    }
    assert tac["stream_rearms"] == 2
    assert payload["links"]["tactile"] == {
        "connected": True, "port_dead": False, "port_error": None,
        "resyncs": 3, "bad_lrc": 4,
    }


def test_duck_typed_session_without_accessors_survives():
    payload = SensorHealthMonitor().payload(_Session(encoders=True, tactile=True))
    assert payload["encoders"]["hz"] == 0.0
    assert payload["tactile"]["fingers"] == {}
    assert payload["links"] == {}
