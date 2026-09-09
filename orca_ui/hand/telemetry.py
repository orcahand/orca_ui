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

from orca_core.hardware.sensing.constants import (
    AUTO_ENC_ANGLE_MASK,
    AUTO_ENC_NUM_JOINTS,
    ENCODER_LSB_DEG,
    JOINT_TO_ENCODER_SLOT,
)
from orca_core.hardware.sensing.health import EncoderStreamHealth

from orca_ui.hand import usage_stats
from orca_ui.hand.faults import (
    BusErrorMonitor,
    TrackingMonitor,
    classify_hw_error,
)
from orca_ui.streaming import topics as T
from orca_ui.streaming.hub import StreamHub

logger = logging.getLogger(__name__)

# How often the latched Hardware Error Status registers are swept. One
# transaction where the motor family can read the register from every motor at
# once, one read per motor otherwise.
HW_ERROR_SWEEP_S = 10.0

# Minimum gap between motor-bus telemetry reads on a hand with no joint loop.
# There is no loop to contend with, but the bus is half-duplex: every read
# blocks commands for its whole round trip, and temperature moves over minutes,
# so reading faster than this buys nothing.
MOTOR_TELEMETRY_MIN_INTERVAL_S = 10.0

# How long motor telemetry may go unread while the hand keeps moving before a
# read is forced through anyway.
MAX_TELEMETRY_STALENESS_S = 30.0

# Measured-stream fallback hysteresis: a joint is dropped from the published
# measured stream the moment its encoder health window is unhealthy, and
# readmitted only after this many consecutive healthy windows (~1 s each).
# Without the hysteresis a flapping sensor leaks a burst of noise into the
# 3D model every time one window happens to pass clean.
ENCODER_RESTORE_WINDOWS = 5


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


class SensorHealthMonitor:
    """Rolls encoder frames into windowed per-joint health verdicts and
    assembles the ``sensors.health`` payload — the browser twin of
    orca_core's ``scripts/monitor_sensors.py`` electrical monitor.

    ``feed`` runs on the fast tick (in-memory read, no bus traffic);
    ``payload`` runs on the slow tick and closes the accumulation window, so
    verdicts cover roughly the last second of frames.
    """

    def __init__(self):
        self._health = EncoderStreamHealth()
        self._last_ts: float | None = None
        self._last_reading = None
        self._prev_rates: dict[str, tuple[float, int]] = {}  # name -> (t, frames)

    def feed(self, reading) -> None:
        if reading is None:
            return
        if reading.timestamp != self._last_ts:
            self._health.update(reading)
            self._last_ts = reading.timestamp
        self._last_reading = reading

    @staticmethod
    def _verdict(report) -> str:
        if report.healthy:
            return "live"
        if report.frames == 0:
            return "no frames"
        if report.parity_errors:
            return "parity"
        if report.angle_error_flags:
            return "chip error"
        return "no encoder"  # stuck/floating bus: no chip answering this slot

    def _rate(self, name: str, frames_ok: int | None) -> float:
        if frames_ok is None:
            self._prev_rates.pop(name, None)
            return 0.0
        now = time.monotonic()
        prev = self._prev_rates.get(name)
        self._prev_rates[name] = (now, frames_ok)
        if prev is None or now <= prev[0]:
            return 0.0
        return max(0.0, (frames_ok - prev[1]) / (now - prev[0]))

    def _encoder_section(self, session) -> dict:
        stats = _call(session, "encoder_stats")
        reading = self._last_reading
        health, self._health = self._health, EncoderStreamHealth()
        joints = {}
        for joint, slot in JOINT_TO_ENCODER_SLOT.items():
            report = health.report(slot)
            deg = None
            if reading is not None:
                deg = round((int(reading.raw_counts[slot]) & AUTO_ENC_ANGLE_MASK)
                            * ENCODER_LSB_DEG, 2)
            joints[joint] = {
                "slot": slot,
                "deg": deg,
                "verdict": self._verdict(report),
                "reason": report.reason,
            }
        live = sum(1 for j in joints.values() if j["verdict"] == "live")
        out = {
            "present": True,
            "hz": round(self._rate("enc", getattr(stats, "frames_ok", None)), 1),
            "error_byte": reading.error_byte if reading is not None else None,
            "joints": joints,
            "live": live,
            "total": AUTO_ENC_NUM_JOINTS,
        }
        if stats is not None:
            freshness = stats.last_freshness_ms
            out["fresh_ms"] = None if math.isinf(freshness) else round(freshness, 0)
        return out

    def _tactile_section(self, session) -> dict:
        cfg = _call(session, "tactile_configuration")
        stats = _call(session, "tactile_stats")
        fingers = {}
        if cfg is not None:
            for finger, connected in cfg.connected.items():
                fingers[finger] = {
                    "connected": bool(connected),
                    "taxels": int(cfg.num_taxels.get(finger, 0)),
                }
        return {
            "present": True,
            "hz": round(self._rate("tac", getattr(stats, "frames_ok", None)), 1),
            "stream_rearms": getattr(stats, "stream_rearms", None),
            "fingers": fingers,
        }

    def payload(self, session) -> dict:
        out: dict = {"encoders": None, "tactile": None, "links": {}}
        if session.caps.encoders:
            out["encoders"] = self._encoder_section(session)
        else:
            self._health = EncoderStreamHealth()
            self._last_reading = None
        if session.caps.tactile:
            out["tactile"] = self._tactile_section(session)
        link_health = _call(session, "sensing_link_health") or {}
        for name, health in link_health.items():
            out["links"][name] = {
                "connected": health.connected,
                "port_dead": health.port_dead,
                "port_error": health.port_error,
                "resyncs": health.stats.bad_header_resyncs,
                "bad_lrc": sum(health.stats.frames_bad_lrc.values()),
            }
        return out


def _call(obj, name: str):
    """Optional-accessor call: None when absent or failing (sessions are
    duck-typed; reads may race a reconnect tearing the link down)."""
    fn = getattr(obj, name, None)
    if fn is None:
        return None
    try:
        return fn()
    except Exception:
        return None


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
        # Negative infinity so the first slow tick publishes straight away:
        # the panel should not sit empty for a whole interval after connect.
        self._last_motor_telemetry = float("-inf")
        self._motor_health: dict[str, dict] = {"temps": {}, "currents": {}}
        self._sensor_health = SensorHealthMonitor()
        self._usage: usage_stats.JointUsageTracker | None = None
        self._usage_path: str | None = None
        # Joints whose encoder is currently distrusted (joint -> "verdict:
        # reason"). Written on the slow tick, read on the fast tick — always
        # replaced wholesale, never mutated in place.
        self._enc_suppressed: dict[str, str] = {}
        self._enc_healthy_streak: dict[str, int] = {}
        # Per-motor fault accounting (bus errors + command adherence),
        # counters scoped to the current session.
        self._bus_errors = BusErrorMonitor()
        self._tracking = TrackingMonitor()
        self._faults_session_key: int | None = None
        # Latched Hardware Error Status per motor, swept rarely: a latched
        # motor answers the bus and acks torque enable but never energizes,
        # so nothing else in the telemetry notices it has stopped moving.
        self._hw_errors: dict[int, list[str]] = {}
        # Classified form of the same, keyed by motor id.
        self._hw_error_info: dict[int, dict] = {}
        self._hw_errors_warned: set[int] = set()
        self._last_hw_error_sweep = 0.0

    def start(self) -> None:
        self._bus_errors.attach()
        for sampler in self._samplers:
            sampler.start()

    def stop(self) -> None:
        self._bus_errors.detach()
        for sampler in self._samplers:
            sampler.stop()
        usage = self._usage
        if usage is not None:
            usage.save()

    # ----- usage stats ---------------------------------------------------------

    def usage_tracker(self) -> usage_stats.JointUsageTracker | None:
        """Lifetime joint-usage accumulator for the current hand.

        Keyed off the calibration path so a model swap on reconnect rolls
        over to that hand's own stats file. None when the service has no
        supervisor/config (duck-typed test stubs).
        """
        supervisor = getattr(self._service, "supervisor", None)
        config = getattr(supervisor, "config", None)
        calibration_path = getattr(config, "calibration_path", None)
        if calibration_path is None:
            return None
        path = usage_stats.stats_path(calibration_path)
        if self._usage is None or self._usage_path != path:
            if self._usage is not None:
                self._usage.save()
            self._usage = usage_stats.JointUsageTracker(
                path, dict(config.joint_roms_dict))
            self._usage_path = path
        return self._usage

    def _feed_usage(self, angles: dict | None) -> None:
        if not angles:
            return
        tracker = self.usage_tracker()
        if tracker is not None:
            tracker.feed(angles)

    # ----- ticks ---------------------------------------------------------------

    def _fast_tick(self) -> None:
        session = self._service.session
        if session is None:
            return

        if session.caps.encoders:
            measured = _clean_angles(session.measured_joints())
            suppressed = self._enc_suppressed
            if measured and suppressed:
                # Distrusted sensors fall back: their joints leave the
                # measured stream entirely, so every consumer (3D model,
                # sparklines, usage stats) rides the motor estimate instead
                # of the noise. The payload names them so clients drop any
                # stale value they already hold.
                measured = {j: v for j, v in measured.items()
                            if j not in suppressed}
            if measured or suppressed:
                payload: dict = {"angles": measured or {}}
                if suppressed:
                    payload["suppressed"] = sorted(suppressed)
                self._hub.publish(T.JOINTS_MEASURED, payload)
            if measured:
                self._feed_usage(measured)
            self._sensor_health.feed(_call(session, "encoder_reading"))

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
            self._tracking.idle()
            return

        # The estimate costs a bus round trip, so with a loop running it rides
        # the slow tick instead. Without one it is gated on the pose source:
        # in "auto" that means reading the motors while they are limp and
        # stopping once torque is on, so streamed commands are not competing
        # with reads for a half-duplex bus.
        estimate = None
        if (session.caps.motors and not session.caps.feedback_loop
                and self._estimate_is_wanted()):
            estimate = self._publish_estimate(session)

        if session.caps.feedback_loop:
            trim = _clean_angles(session.loop_correction())
            if trim is not None:
                self._hub.publish(T.JOINTS_CORRECTION, {"trim": trim})

        if session.caps.motors:
            self._feed_tracking(session, estimate)

    def _slow_tick(self) -> None:
        session = self._service.session
        # Faults publish with or without a session: bus errors during a failed
        # connect are exactly what the panel needs to show.
        self._publish_motor_faults(session)
        if session is None:
            return

        if session.caps.motors:
            self._sweep_hardware_errors(session)
            if not session.caps.feedback_loop:
                if self._motor_telemetry_is_due():
                    self._last_motor_telemetry = time.monotonic()
                    self._publish_motor_health(session)
            elif not self._hand_is_driven() or self._telemetry_is_stale():
                self._bus_read_tick(session)

        self._hub.publish(T.STATS, self._service.stats())
        health = self._sensor_health.payload(session)
        self._update_encoder_suppression(health)
        self._hub.publish(T.SENSORS_HEALTH, health)
        # Health is tracked whenever connected — dropouts matter while the
        # hand is idle too (motion stats, by contrast, gate on real motion).
        tracker = self.usage_tracker()
        if tracker is not None:
            tracker.feed_health(health, session.caps)

    def _update_encoder_suppression(self, health: dict) -> None:
        """Distrust noisy encoders (fast to condemn, slow to forgive).

        Runs each health window (~1 s): an unhealthy verdict suppresses the
        joint's measured stream immediately; only ``ENCODER_RESTORE_WINDOWS``
        consecutive clean windows restore it. The health payload is annotated
        with the suppression set so the UI can log and explain it.
        """
        encoders = health.get("encoders")
        if not encoders:
            if self._enc_suppressed:
                logger.info("encoder stream gone — clearing %d suppressed "
                            "joint(s)", len(self._enc_suppressed))
            self._enc_suppressed = {}
            self._enc_healthy_streak = {}
            return
        suppressed = dict(self._enc_suppressed)
        for joint, info in (encoders.get("joints") or {}).items():
            verdict = info.get("verdict")
            if verdict != "live":
                detail = f"{verdict}: {info.get('reason')}"
                if joint not in suppressed:
                    logger.warning(
                        "joint %s encoder unhealthy (%s) — dropping it from "
                        "the measured stream; the 3D model and joint streams "
                        "fall back to the motor estimate until it reads "
                        "clean for %ds", joint, detail,
                        ENCODER_RESTORE_WINDOWS)
                suppressed[joint] = detail
                self._enc_healthy_streak.pop(joint, None)
            elif joint in suppressed:
                streak = self._enc_healthy_streak.get(joint, 0) + 1
                if streak >= ENCODER_RESTORE_WINDOWS:
                    del suppressed[joint]
                    self._enc_healthy_streak.pop(joint, None)
                    logger.info("joint %s encoder healthy for %d windows — "
                                "measured stream restored", joint, streak)
                else:
                    self._enc_healthy_streak[joint] = streak
        self._enc_suppressed = suppressed
        encoders["suppressed"] = dict(suppressed)
        encoders["restore_after_s"] = ENCODER_RESTORE_WINDOWS

    # ----- motor-bus reads -----------------------------------------------------
    #
    # A group read holds the bus for a round trip per motor, so one landing
    # mid-motion freezes the hand for more than a loop cycle.

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

    def _estimate_is_wanted(self) -> bool:
        """True while the model is following the motor estimate.

        Command-adherence tracking needs the estimate too, so it goes quiet on
        a motor-only hand whenever the estimate does; pinning the pose source
        to "estimate" is how an operator gets it back during motion.
        """
        try:
            return self._service.effective_pose_source() == "estimate"
        except Exception:
            return True

    def _motor_telemetry_is_due(self) -> bool:
        """True once the loopless hand's telemetry has aged out its rate limit."""
        return ((time.monotonic() - self._last_motor_telemetry)
                >= MOTOR_TELEMETRY_MIN_INTERVAL_S)

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

    def _motor_health_payload(self, session) -> dict:
        """temps/currents plus the family's rated max operating temperature
        (same source as scripts/stress_test.py's monitor)."""
        payload = dict(self._motor_health)
        max_temp = getattr(getattr(session, "hand", None), "motor_client",
                           None)
        max_temp = getattr(max_temp, "max_operating_temp_c", None)
        if max_temp is not None:
            payload["max_temp_c"] = float(max_temp)
        return payload

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
            if not session.caps.encoders:
                self._feed_usage(angles)
        if currents:
            self._motor_health["currents"] = {
                int(k): round(float(v), 1) for k, v in currents.items()}
            self._hub.publish(T.MOTORS_TELEMETRY,
                              self._motor_health_payload(session))

    def _publish_estimate(self, session) -> dict | None:
        estimate = _clean_angles(session.estimate_joints())
        if estimate:
            self._hub.publish(T.JOINTS_ESTIMATE, {"angles": estimate})
            # Encoder hands are already fed from the fast tick's measured
            # angles; estimate-only hands accumulate usage from here.
            if not session.caps.encoders:
                self._feed_usage(estimate)
        return estimate

    # ----- motor faults --------------------------------------------------------

    def _feed_tracking(self, session, estimate: dict | None) -> None:
        """Command-adherence sample: last written targets vs sampled pose.

        Gated off (state cleared, totals kept) whenever nothing is actually
        commanding the joints — torque disabled, direct motor mode (replay
        writes motor space, so joint targets are stale), or no data.
        """
        torque_on = False
        try:
            torque_on = bool(self._service.supervisor.status().torque_enabled)
        except Exception:
            pass
        direct = bool(getattr(self._service, "_direct_motor_mode", False))
        targets: dict = {}
        try:
            targets = self._service.worker.applied_targets()
        except Exception:
            pass
        actual: dict | None
        if session.caps.encoders:
            actual = _clean_angles(session.measured_joints())
            if actual and self._enc_suppressed:
                # A distrusted encoder reads garbage — comparing against it
                # would flag a healthy motor as not following.
                actual = {j: v for j, v in actual.items()
                          if j not in self._enc_suppressed}
        else:
            actual = estimate
        if torque_on and not direct and targets and actual:
            self._tracking.update(targets, actual)
        else:
            self._tracking.idle()

    def forget_hw_error(self, motor_id: int) -> None:
        """Drop a motor's cached latch after a reboot cleared it, so the
        dashboard updates on the reply instead of waiting out the sweep. A
        fault that is still there comes straight back on the next sweep."""
        mid = int(motor_id)
        self._hw_errors.pop(mid, None)
        self._hw_error_info.pop(mid, None)
        self._hw_errors_warned.discard(mid)

    def _sweep_hardware_errors(self, session) -> None:
        """Refresh the latched-error table, warning once per newly latched motor."""
        hand = getattr(session, "hand", None)
        client = getattr(hand, "motor_client", None)
        # Free: the reads that already happened carried each motor's error
        # byte. A motor that faulted since the last sweep is confirmed on the
        # next tick rather than waiting out the interval.
        alerted = self._drain_alerts(client)
        now = time.monotonic()
        if not alerted and now - self._last_hw_error_sweep < HW_ERROR_SWEEP_S:
            return
        self._last_hw_error_sweep = now
        raw = self._read_hardware_errors(client, hand)
        if raw is None:
            return
        motor_to_joint = hand.config.motor_to_joint_dict
        found: dict[int, list[str]] = {}
        classified: dict[int, dict] = {}
        for mid in hand.config.motor_ids:
            try:
                flags = client.decode_hardware_error(raw[int(mid)])
            except Exception:
                continue
            if not flags:
                self._hw_errors_warned.discard(int(mid))
                continue
            info = classify_hw_error(
                flags, motor=mid, joint=motor_to_joint.get(mid),
                temperature_c=(self._motor_health.get("temps") or {}).get(int(mid)))
            found[int(mid)] = flags
            classified[int(mid)] = info
            if int(mid) in self._hw_errors_warned:
                continue
            self._hw_errors_warned.add(int(mid))
            # Advice that matches the fault: a power latch at 32 °C must not
            # be met with "let it cool", which is what a single templated
            # message for every bit used to say.
            message = (
                f"{info['headline']}: {info['disabled_note']} "
                f"{info['advice']}"
            )
            logger.warning(message)
            # orca_ui installs no log handler that prints, and a motor that
            # has stopped moving has to reach the operator, not just the
            # stream — same yellow the core's warnings use.
            print(f"\033[93mWarning: {message}\033[0m")
        self._hw_errors = found
        self._hw_error_info = classified

    @staticmethod
    def _drain_alerts(client) -> dict:
        """Motors whose status packets carried the Alert bit since last asked.

        A hint about when to sweep, not a diagnosis: the sweep reads the error
        register itself, and rebooting is the operator's call.
        """
        take = getattr(client, "take_hardware_alerts", None)
        if take is None:
            return {}
        try:
            return take() or {}
        except Exception:
            logger.debug("hardware-alert drain failed", exc_info=True)
            return {}

    @staticmethod
    def _read_hardware_errors(client, hand) -> dict | None:
        """Every motor's latched error in one transaction where the family
        supports it, falling back to one read each. ``None`` if unreadable."""
        read_all = getattr(client, "read_hardware_errors", None)
        read_one = getattr(client, "read_hardware_error", None)
        try:
            if read_all is not None:
                return read_all(hand.config.motor_ids)
            if read_one is not None:
                return {int(mid): read_one(mid) for mid in hand.config.motor_ids}
        except Exception:
            logger.debug("hardware-error sweep failed", exc_info=True)
        return None

    def _publish_motor_faults(self, session) -> None:
        if session is not None:
            key = id(session)
            if key != self._faults_session_key:
                # New session: last connect's counters would misattribute old
                # faults to fresh hardware.
                self._faults_session_key = key
                self._bus_errors.reset()
                self._tracking.reset()
        bus = self._bus_errors.snapshot()
        tracking = self._tracking.snapshot()
        config = getattr(getattr(self._service, "supervisor", None),
                         "config", None)
        motor_ids = [int(m) for m in (getattr(config, "motor_ids", None) or [])]
        motor_to_joint = {
            int(k): str(v)
            for k, v in (getattr(config, "motor_to_joint_dict", None)
                         or {}).items()}
        motors = {}
        for mid in sorted(set(motor_ids) | set(bus["motors"])):
            entry = bus["motors"].get(mid) or {
                "errors": 0, "overloads": 0,
                "last_error": None, "last_error_age_s": None,
            }
            joint = motor_to_joint.get(mid)
            entry["joint"] = joint
            entry["tracking"] = tracking.get(joint) if joint else None
            entry["hw_error_flags"] = self._hw_errors.get(mid) or []
            # Classified: which kind of latch, and what to do about it. The
            # dashboard needs this to tell a power latch from a hot motor.
            entry["hw_error"] = self._hw_error_info.get(mid)
            motors[mid] = entry
        self._hub.publish(T.MOTORS_FAULTS,
                          {"motors": motors, "bus": bus["bus"]})

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
        self._hub.publish(T.MOTORS_TELEMETRY,
                          self._motor_health_payload(session))
