"""sensors.health payload tests: encoder verdicts, tactile state, link stats.

The monitor is a windowed accumulator: frames fed between two ``payload``
calls decide that window's verdicts, and each ``payload`` closes the window.
Verdict mapping mirrors orca_core's monitor_sensors.py: healthy -> live,
parity beats chip error, a rail-stuck slot reads as "no encoder", and a
window with no frames at all reads "no frames".
"""

import numpy as np
from orca_core.hardware.sensing.constants import (
    AUTO_ENC_ANGLE_MASK,
    AUTO_ENC_NUM_JOINTS,
    ENCODER_LSB_DEG,
    JOINT_TO_ENCODER_SLOT,
)
from orca_core.hardware.sensing.types import EncoderReading

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
