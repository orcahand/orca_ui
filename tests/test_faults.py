"""Motor fault accounting: log-derived bus errors and command adherence.

The bus monitor is fed the exact messages orca_core's motor clients emit, so
these break if the upstream wording changes — which is the point: parsing is
the contract.
"""

import logging

from orca_ui.hand.faults import (
    TRACKING_GRACE_S,
    BusErrorMonitor,
    TrackingMonitor,
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

    def test_overload_warning_counted(self):
        monitor = BusErrorMonitor()
        monitor.emit(_record(
            "Motor 16 overload detected (error=0x20), rebooting...",
            level=logging.WARNING))
        snap = monitor.snapshot()
        assert snap["motors"][16]["overloads"] == 1
        assert snap["motors"][16]["last_error"] == "overload"

    def test_id_list_messages_fan_out(self):
        monitor = BusErrorMonitor()
        monitor.emit(_record("Sync write failed for: [16, 17]"))
        monitor.emit(_record(
            "Could not set torque disabled for IDs: [1, 2, 3]"))
        snap = monitor.snapshot()
        assert snap["motors"][16]["errors"] == 1
        assert snap["motors"][17]["errors"] == 1
        assert snap["motors"][1]["errors"] == 1
        assert snap["bus"]["errors"] == 5

    def test_non_bus_loggers_ignored(self):
        monitor = BusErrorMonitor()
        monitor.emit(_record("[Motor ID: 3] nope", name="orca_ui.hand.service"))
        assert monitor.snapshot()["bus"]["errors"] == 0

    def test_ordinary_warnings_ignored(self):
        monitor = BusErrorMonitor()
        monitor.emit(_record("something unrelated", level=logging.WARNING))
        monitor.emit(_record("also unrelated"))
        assert monitor.snapshot() == {
            "motors": {},
            "bus": {"errors": 0, "last_error": None, "last_error_age_s": None},
        }

    def test_reset(self):
        monitor = BusErrorMonitor()
        monitor.emit(_record("> write_byte: [Motor ID: 3] boom"))
        monitor.reset()
        assert monitor.snapshot()["bus"]["errors"] == 0


class TestTrackingMonitor:
    def test_within_tolerance_is_following(self):
        monitor = TrackingMonitor()
        monitor.update({"index_mcp": 10.0}, {"index_mcp": 8.0}, now=0.0)
        snap = monitor.snapshot(now=0.0)
        assert snap["index_mcp"]["following"] is True
        assert snap["index_mcp"]["deviation_deg"] == 2.0

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

    def test_second_stall_counts_again(self):
        monitor = TrackingMonitor()
        monitor.update({"j": 90.0}, {"j": 0.0}, now=0.0)
        monitor.update({"j": 90.0}, {"j": 0.0}, now=2.0)
        monitor.update({"j": 90.0}, {"j": 89.0}, now=3.0)
        monitor.update({"j": 90.0}, {"j": 0.0}, now=4.0)
        monitor.update({"j": 90.0}, {"j": 0.0}, now=6.0)
        assert monitor.snapshot(now=6.0)["j"]["stalls"] == 2

    def test_idle_clears_live_state_keeps_totals(self):
        monitor = TrackingMonitor()
        monitor.update({"j": 90.0}, {"j": 0.0}, now=0.0)
        monitor.update({"j": 90.0}, {"j": 0.0}, now=2.0)
        monitor.idle()
        snap = monitor.snapshot(now=3.0)
        assert snap["j"]["following"] is True
        assert snap["j"]["deviation_deg"] is None
        assert snap["j"]["stalls"] == 1

    def test_missing_actual_joint_is_skipped(self):
        monitor = TrackingMonitor()
        monitor.update({"j": 90.0}, {}, now=0.0)
        assert monitor.snapshot(now=0.0) == {}
