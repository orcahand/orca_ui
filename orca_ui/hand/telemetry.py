"""Sampler threads: hardware state → StreamHub topics.

Three cadences: fast (encoder-measured joints + tactile, in-memory reads),
mid (motor-derived joint estimate + loop trim, one bus read), slow (temps,
currents, stream stats). All rates come from settings and are decoupled from
the hardware rates — orca_core's clients buffer the latest frame internally.
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

        if session.caps.motors:
            estimate = _clean_angles(session.estimate_joints())
            if estimate:
                self._hub.publish(T.JOINTS_ESTIMATE, {"angles": estimate})

        if session.caps.feedback_loop:
            trim = _clean_angles(session.loop_correction())
            if trim is not None:
                self._hub.publish(T.JOINTS_CORRECTION, {"trim": trim})

    def _slow_tick(self) -> None:
        session = self._service.session
        if session is None:
            return

        if session.caps.motors:
            try:
                temps = session.hand.get_motor_temp(as_dict=True)
                currents = session.hand.get_motor_current(as_dict=True)
                self._hub.publish(T.MOTORS_TELEMETRY, {
                    "temps": {int(k): round(float(v), 1) for k, v in temps.items()},
                    "currents": {int(k): round(float(v), 1) for k, v in currents.items()},
                })
            except Exception:
                logger.debug("motor telemetry read failed", exc_info=True)

        self._hub.publish(T.STATS, self._service.stats())
