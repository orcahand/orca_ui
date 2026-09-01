"""Motor fault accounting: log-derived bus errors and command adherence.

The bus monitor is fed the exact messages orca_core's motor clients emit, so
these break if the upstream wording changes — which is the point: parsing is
the contract.
"""

import logging
from types import SimpleNamespace

from orca_ui.hand.faults import (
    TRACKING_GRACE_S,
    BusErrorMonitor,
    TrackingMonitor,
    classify_hw_error,
)


def _record(message: str, level=logging.ERROR, name="root"):
    return logging.LogRecord(name, level, __file__, 0, message, None, None)


class TestBusErrorMonitor:
    def test_motor_id_write_errors_counted_per_motor(self):
        monitor = BusErrorMonitor()
        for _ in range(3):
            monitor.emit(_record(
                "> write_byte: [Motor ID: 3] [TxRxResult] Port is in use!"))
        monitor.emit(_record(
            "> write_byte: [Motor ID: 4] [TxRxResult] There is no status packet!"))
        snap = monitor.snapshot()
        assert snap["motors"][3]["errors"] == 3
        assert snap["motors"][3]["last_error"] == "Port is in use!"
        assert snap["motors"][4]["errors"] == 1
        assert snap["motors"][4]["last_error"] == "There is no status packet!"
        assert snap["bus"]["errors"] == 4

class TestTrackingMonitor:
    def test_deviation_needs_grace_before_stall(self):
        monitor = TrackingMonitor()
        monitor.update({"j": 90.0}, {"j": 0.0}, now=0.0)
        assert monitor.snapshot(now=0.0)["j"]["following"] is True
        monitor.update({"j": 90.0}, {"j": 0.0}, now=TRACKING_GRACE_S + 0.1)
        snap = monitor.snapshot(now=TRACKING_GRACE_S + 0.1)
        assert snap["j"]["following"] is False
        assert snap["j"]["stalls"] == 1
        assert snap["j"]["stall_s"] > TRACKING_GRACE_S

    def test_stalled_time_accumulates_and_recovery_clears(self):
        monitor = TrackingMonitor()
        monitor.update({"j": 90.0}, {"j": 0.0}, now=0.0)
        monitor.update({"j": 90.0}, {"j": 0.0}, now=2.0)
        monitor.update({"j": 90.0}, {"j": 0.0}, now=3.0)
        snap = monitor.snapshot(now=3.0)
        assert snap["j"]["stalled_total_s"] == 1.0  # 2.0 -> 3.0, post-stall
        monitor.update({"j": 90.0}, {"j": 89.0}, now=4.0)
        snap = monitor.snapshot(now=4.0)
        assert snap["j"]["following"] is True
        assert snap["j"]["stall_s"] == 0.0
        # History survives recovery — that is the "how often" record.
        assert snap["j"]["stalls"] == 1
        assert snap["j"]["stalled_total_s"] == 1.0


class TestHardwareErrorClassification:
    """What a latched Hardware Error Status tells the operator to do.

    Every latched bit disables the power stage identically, so the *kind* is
    the only actionable part: a thermal latch is waited out, a power latch
    re-latches on the next command until the supply or wiring is fixed.
    """

    def test_overheating_is_a_thermal_fault_that_wants_cooling(self):
        info = classify_hw_error(["overheating"], motor=3, joint="index_mcp",
                                 temperature_c=71.0)

        assert info["kind"] == "thermal"
        assert info["needs_cooling"] is True
        assert info["disabled"] is True
        assert "71 °C" in info["headline"]
        assert "cool" in info["advice"].lower()

    def test_power_outranks_thermal_when_both_are_latched(self):
        """Cooling clears the thermal bit and changes nothing about the fault."""
        info = classify_hw_error(["overheating", "input_voltage"], motor=5)

        assert info["kind"] == "power"
        # Waiting is still part of the job, but it is not the job.
        assert info["needs_cooling"] is True
        assert "Cooling will not help" in info["advice"]

    def test_nothing_latched_is_not_a_fault(self):
        assert classify_hw_error([]) is None
        assert classify_hw_error(None) is None


class _SweepClient:
    """Motor client stand-in whose latched flags the test controls."""

    def __init__(self, flags_by_motor):
        self.flags_by_motor = flags_by_motor
        self.reads = 0

    def read_hardware_error(self, motor_id):
        self.reads += 1
        return motor_id

    def decode_hardware_error(self, value):
        return self.flags_by_motor.get(value, [])


class TestHardwareErrorSweep:
    def _sampler(self, flags_by_motor, motor_ids=(1, 2)):
        from orca_ui.hand.telemetry import TelemetryService

        sampler = TelemetryService.__new__(TelemetryService)
        sampler._hw_errors = {}
        sampler._hw_error_info = {}
        sampler._hw_errors_warned = set()
        sampler._last_hw_error_sweep = 0.0
        sampler._motor_health = {}

        client = _SweepClient(flags_by_motor)
        config = SimpleNamespace(
            motor_ids=list(motor_ids),
            motor_to_joint_dict={1: "index_mcp", 2: "middle_mcp"},
        )
        session = SimpleNamespace(
            hand=SimpleNamespace(motor_client=client, config=config))
        return sampler, session, client

    def test_sweep_records_latched_flags(self):
        sampler, session, _ = self._sampler({1: ["overheating"], 2: []})

        sampler._last_hw_error_sweep = -1e6  # force the interval open
        sampler._sweep_hardware_errors(session)

        assert sampler._hw_errors == {1: ["overheating"]}
        assert sampler._hw_error_info[1]["kind"] == "thermal"
        assert 2 not in sampler._hw_errors

    def test_sweep_is_rate_limited(self):
        """The sweep costs a bus read per motor; it must not run every tick."""
        sampler, session, client = self._sampler({1: ["overload"], 2: []})

        sampler._last_hw_error_sweep = -1e6
        sampler._sweep_hardware_errors(session)
        first = client.reads
        sampler._sweep_hardware_errors(session)  # immediately again

        assert client.reads == first
