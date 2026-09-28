"""Sampler threads: hardware state → StreamHub topics.

Three cadences: fast (encoder-measured joints + tactile, in-memory reads),
mid (loop trim, and the motor estimate on hands without a loop), slow (motor
telemetry, stream stats). All rates come from settings and are decoupled from
the hardware rates — orca_core's clients buffer the latest frame internally.

Motor-bus reads share the servo bus with the joint loop's writes, so with a
loop running they are confined to the slow tick, one per tick, and skipped
entirely while the hand is being driven.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from typing import Callable

from orca_ui.streaming import topics as T
from orca_ui.streaming.hub import StreamHub

logger = logging.getLogger(__name__)

# How long motor telemetry may go unread while the hand keeps moving before a
# read is forced through anyway.
MAX_TELEMETRY_STALENESS_S = 30.0


def _clean_angles(angles: dict | None) -> dict | None:
    """Drop None/NaN entries and round for the wire."""
    if not angles:
        return None
    out = {}
    for joint, value in angles.items():
        if value is None:
            continue
        value = float(value)
        if math.isnan(value):
            continue
        out[joint] = round(value, 2)
    return out or None


class _Sampler(threading.Thread):
    def __init__(self, name: str, period_s: float, tick: Callable[[], None]):
        super().__init__(name=name, daemon=True)
        self._period = period_s
        self._tick = tick
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        while not self._stop_event.is_set():
            started = time.monotonic()
            try:
                self._tick()
            except Exception:
                # Session may vanish mid-read during reconnects; the
                # supervisor owns recovery, samplers just keep sampling.
                logger.debug("sampler tick failed", exc_info=True)
            elapsed = time.monotonic() - started
            self._stop_event.wait(timeout=max(0.0, self._period - elapsed))


class TelemetryService:
    def __init__(self, service, hub: StreamHub, settings):
        self._service = service
        self._hub = hub
        self._samplers = [
            _Sampler("telemetry-fast", 1.0 / settings.fast_hz, self._fast_tick),
            _Sampler("telemetry-mid", 1.0 / settings.mid_hz, self._mid_tick),
            _Sampler("telemetry-slow", 1.0 / settings.slow_hz, self._slow_tick),
        ]
        self._bus_reads = ("state", "temps")
        self._bus_read_index = 0
        # Start the staleness window now, so a hand already moving at startup
        # isn't read immediately on a "never read" technicality.
        self._last_bus_read = time.monotonic()
        self._motor_health: dict[str, dict] = {"temps": {}, "currents": {}}

    def start(self) -> None:
        for sampler in self._samplers:
            sampler.start()

    def stop(self) -> None:
        for sampler in self._samplers:
            sampler.stop()

    # ----- ticks ---------------------------------------------------------------

    def _fast_tick(self) -> None:
        session = self._service.session
        if session is None:
            return

        if session.caps.encoders:
            measured = _clean_angles(session.measured_joints())
            if measured:
                self._hub.publish(T.JOINTS_MEASURED, {"angles": measured})

        if session.caps.tactile:
            reading = session.tactile_data()
            if reading is not None:
                forces = getattr(reading.forces, "forces", None)
                if forces:
                    self._hub.publish(T.TACTILE_FORCES, {"forces": forces})
                taxels = getattr(reading.taxels, "taxels", None)
                if taxels:
                    self._hub.publish(T.TACTILE_TAXELS, {"taxels": taxels})

    def _mid_tick(self) -> None:
        session = self._service.session
        if session is None:
            return

        # The estimate costs a bus round trip, so with a loop running it rides
        # the slow tick instead; without one there is no motion to stall.
        if session.caps.motors and not session.caps.feedback_loop:
            self._publish_estimate(session)

        if session.caps.feedback_loop:
            trim = _clean_angles(session.loop_correction())
            if trim is not None:
                self._hub.publish(T.JOINTS_CORRECTION, {"trim": trim})

    def _slow_tick(self) -> None:
        session = self._service.session
        if session is None:
            return

        if session.caps.motors:
            if not session.caps.feedback_loop:
                self._publish_motor_health(session)
            elif not self._hand_is_driven() or self._telemetry_is_stale():
                self._bus_read_tick(session)

        self._hub.publish(T.STATS, self._service.stats())

    # ----- motor-bus reads -----------------------------------------------------
    #
    # A bulk read holds the bus for a round trip per motor (~15 ms for 17), so
    # one landing mid-motion freezes the hand for more than a loop cycle.

    def _hand_is_driven(self) -> bool:
        """True while something is actively commanding motion."""
        try:
            if self._service.worker.stats().get("ramping"):
                return True
        except Exception:
            pass
        manager = self._service.operation_manager
        try:
            return bool(manager and manager.active())
        except Exception:
            return False

    def _telemetry_is_stale(self) -> bool:
        """True once telemetry is old enough to be worth one hitch, so a long
        replay or teleop session cannot hide an overheating motor."""
        return (time.monotonic() - self._last_bus_read) > MAX_TELEMETRY_STALENESS_S

    def _bus_read_tick(self, session) -> None:
        """One read per tick: position and current share a register block,
        temperature needs its own."""
        which = self._bus_reads[self._bus_read_index % len(self._bus_reads)]
        self._bus_read_index += 1
        self._last_bus_read = time.monotonic()
        if which == "state":
            self._publish_motor_state(session)
        else:
            self._publish_motor_health(session, currents=False)

    def _publish_motor_state(self, session) -> None:
        """Joint estimate and currents, from one read."""
        try:
            estimate, currents = session.motor_snapshot()
        except Exception:
            logger.debug("motor state read failed", exc_info=True)
            return
        angles = _clean_angles(estimate)
        if angles:
            self._hub.publish(T.JOINTS_ESTIMATE, {"angles": angles})
        if currents:
            self._motor_health["currents"] = {
                int(k): round(float(v), 1) for k, v in currents.items()}
            self._hub.publish(T.MOTORS_TELEMETRY, dict(self._motor_health))

    def _publish_estimate(self, session) -> None:
        estimate = _clean_angles(session.estimate_joints())
        if estimate:
            self._hub.publish(T.JOINTS_ESTIMATE, {"angles": estimate})

    def _publish_motor_health(self, session, temps: bool = True,
                              currents: bool = True) -> None:
        """Publish temps/currents, keeping the half this tick didn't read so the
        payload always carries a complete table."""
        try:
            if temps:
                self._motor_health["temps"] = {
                    int(k): round(float(v), 1)
                    for k, v in session.hand.get_motor_temp(as_dict=True).items()}
            if currents:
                self._motor_health["currents"] = {
                    int(k): round(float(v), 1)
                    for k, v in session.hand.get_motor_current(as_dict=True).items()}
        except Exception:
            logger.debug("motor telemetry read failed", exc_info=True)
            return
        self._hub.publish(T.MOTORS_TELEMETRY, dict(self._motor_health))
