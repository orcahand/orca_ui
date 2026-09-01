"""Calibration as a maintenance operation.

The supervisor lends the hardware (MAINTENANCE lease), the op builds its own
motor-only hand + UI-owned encoder client — the scripts/calibrate.py pattern,
which sidesteps orca_core's refusal to calibrate while the feedback loop runs.

``run_calibrate`` is deliberately lease-free so the wizard (M6) can compose
tension + calibrate rounds under one lease.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from orca_ui.hand import calibration_log
from orca_ui.hand.operations import hand_ops
from orca_ui.hand.faults import classify_hw_error
from orca_ui.hand.operations.base import OpContext, Operation


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _magnets(event: dict) -> str:
    """Hardstop magnet counts, when the event carries them."""
    flex, extend = event.get("flex_count"), event.get("extend_count")
    if flex is None or extend is None:
        return ""
    return f" · magnets flex@{flex} extend@{extend}"


# Floor for per-run calibration-current overrides: below this the motors
# stall on cable friction before ever reaching a hardstop, and the sweep
# records false limits. The ceiling is the config's max_current.
MIN_CALIBRATION_CURRENT_MA = 50


def _current_override(params: dict, key: str, config) -> int | None:
    from orca_ui.hand.service import ServiceError

    value = params.get(key)
    if value is None:
        return None
    try:
        value = int(value)
    except (TypeError, ValueError):
        raise ServiceError(f"{key} must be a whole number of mA")
    ceiling = int(getattr(config, "max_current", 0) or 0) or 2000
    if not MIN_CALIBRATION_CURRENT_MA <= value <= ceiling:
        raise ServiceError(
            f"{key} must be {MIN_CALIBRATION_CURRENT_MA}..{ceiling} mA "
            "(the configured max_current caps it)")
    return value


def validate_calibrate_params(service, params: dict) -> dict:
    from orca_ui.hand.service import ServiceError

    config = service.supervisor.config
    joints = params.get("joints")
    if joints is not None:
        if not isinstance(joints, list) or not joints or \
                not all(isinstance(j, str) for j in joints):
            raise ServiceError(
                "joints must be a non-empty list of joint names, or null "
                "for a full calibration")
        unknown = set(joints) - set(config.joint_ids)
        if unknown:
            raise ServiceError(f"unknown joints: {sorted(unknown)}")
        joints = list(dict.fromkeys(joints))
    session = service.session
    if session is None:
        raise ServiceError("hand not connected", status_code=503)
    if not session.caps.motors:
        raise ServiceError("no motor bus — calibration needs motors",
                           status_code=409)
    # None = auto: run the joint-sensor (encoder anchor) pass only when a
    # selected encoder-backed joint has no anchor yet — i.e. the first time.
    sensors = params.get("calibrate_joint_sensors")
    if sensors is not None and not isinstance(sensors, bool):
        raise ServiceError("calibrate_joint_sensors must be a boolean or null")
    return {"joints": joints,
            "force_wrist": bool(params.get("force_wrist", False)),
            # Hands-on capture: torque stays off and the operator holds each
            # joint on its hardstop. The only path for a joint whose motor
            # cannot reach its own stop.
            "manual": bool(params.get("manual", False)),
            "calibrate_joint_sensors": sensors,
            # Per-run current overrides; None = the config.yaml values.
            "calibration_current":
                _current_override(params, "calibration_current", config),
            "wrist_calibration_current":
                _current_override(params, "wrist_calibration_current", config)}


def run_calibrate(hand, encoder_client, ctx: OpContext,
                  joints: list[str] | None, force_wrist: bool,
                  manual: bool = False) -> dict:
    """Blocking calibration with progress mapped onto the op snapshot.

    Every progress event is also archived (with a timestamp) to the
    calibration history next to calibration.yaml, so hardstop magnet
    positions can be compared across runs for drift.
    """
    progress = {"steps_done": 0, "total": 0, "joints_calibrated": [],
                "anchors_recorded": [], "anchors_dead": []}
    events: list[dict] = []
    # Anything the operator has to act on, surfaced on the snapshot as it
    # happens rather than only in the log: a joint whose motor never moved
    # scrolls past in milliseconds otherwise.
    problems: list[dict] = []

    def problem(kind: str, joint: str, severity: str, headline: str,
                advice: str, **fields) -> None:
        entry = {"kind": kind, "joint": joint, "severity": severity,
                 "headline": headline, "advice": advice, **fields}
        # One entry per joint per kind: a re-run of the same step replaces it.
        for index, existing in enumerate(problems):
            if existing["joint"] == joint and existing["kind"] == kind:
                problems[index] = entry
                break
        else:
            problems.append(entry)
        ctx.set_extra({"problems": list(problems)})
        ctx.log(f"{'ERROR' if severity == 'error' else 'WARNING'}: {headline}")

    def on_event(event: dict) -> None:
        events.append({"t": round(time.time(), 3), **event})
        kind = event.get("event")
        if kind == "encoder_anchor_recorded":
            progress["anchors_recorded"].append(event["joint"])
            ctx.log(f"encoder anchor recorded: {event['joint']} "
                    f"(count {event['anchor_count']} at "
                    f"{event['anchor_angle_deg']:.1f}°)")
        elif kind == "encoder_anchor_failed":
            reason = str(event.get("error", ""))
            # A slot that doesn't move with the sweep is dead or unwired —
            # a hardware fault, not a retryable sampling glitch.
            if "did not track the sweep" in reason:
                progress["anchors_dead"].append(event["joint"])
                ctx.log(f"encoder DEAD on {event['joint']}: {reason}. Check "
                        "its wiring at the connector board; the joint stays "
                        "open-loop until the encoder reads.")
            else:
                ctx.log(f"encoder anchor not captured for {event['joint']}: "
                        f"{reason} — it keeps its previous anchor")
        elif kind == "measured_rom_recorded":
            rom = event["rom"]
            ctx.log(f"measured ROM for {event['joint']}: "
                    f"[{rom[0]:.1f}, {rom[1]:.1f}]° "
                    f"(Δ {event['deviation_deg']:+.1f}° vs config)"
                    f"{_magnets(event)}")
        elif kind == "measured_rom_rejected":
            ctx.log(f"measured ROM REJECTED for {event['joint']}: the "
                    f"{event['span_deg']:.1f}° measured travel puts its lower "
                    f"hardstop {event['deviation_deg']:+.1f}° from the config "
                    "value — beyond the sanity limit, so the config range is "
                    "kept and its Δ is shown as rejected. Check the joint's "
                    "hardstops or fix its joint_roms entry in config.yaml."
                    f"{_magnets(event)}")
        elif kind == "sweep_no_motion":
            problem(
                "no_motion", event["joint"], "error",
                f"{event['joint']} did not move during its "
                f"{event['direction']} sweep "
                f"({event['moved_deg']:.1f}° of motor travel)",
                "Its recorded hardstop is just where the joint was resting. "
                "Check the tendon is connected, that nothing blocks the "
                "joint, and that the motor is not latched off.",
                motor=event["motor"], direction=event["direction"],
                moved_deg=event["moved_deg"])
        elif kind == "travel_checked" and not event["within_margin"]:
            short = event["travel_deg"] < event["expected_deg"]
            pct = abs(event["deviation"]) * 100
            problem(
                "travel", event["joint"], "warn",
                f"{event['joint']} swept {event['travel_deg']:.1f}° of "
                f"motor travel, {pct:.0f}% "
                f"{'short of' if short else 'past'} its "
                f"{event['expected_deg']:.1f}° baseline",
                "The range recorded for this joint is too small, so every "
                "angle derived from it is wrong. Re-tension the tendon and "
                "calibrate this joint again."
                if short else
                "More travel than the baseline allows: check the tendon for "
                "slip, or re-measure the baseline with measure_travel.py.",
                motor=event["motor"], travel_deg=event["travel_deg"],
                expected_deg=event["expected_deg"])
        elif kind == "limits_rejected":
            problem(
                "rejected", event["joint"], "error",
                f"{event['joint']} was not calibrated: its two hardstops came "
                f"out {event['travel_deg']:.1f}° apart",
                "Two limits this close are not two hardstops. The joint keeps "
                "the calibration it already had.",
                motor=event["motor"], travel_deg=event["travel_deg"])
        elif kind == "drive_step_timeout":
            problem(
                "timeout", event["joint"], "error",
                f"{event['joint']} never settled onto a hardstop",
                "It kept moving until the step gave up — a disconnected "
                "tendon spins freely. No limit was recorded for that end.",
                motor=event["motor"])
        elif kind == "manual_capture_skipped":
            ctx.log(f"skipped {event['joint']} {event['direction']} — no "
                    "limit recorded for that end")
        elif kind == "motor_faulted":
            temp = event.get("temperature_c")
            flags = event.get("flags") or []
            progress.setdefault("faulted_motors", []).append(event["joint"])
            # Advice per fault kind: "let it cool" is right for a thermal
            # latch and actively misleading for an electrical one.
            info = classify_hw_error(
                flags or ["unknown"], motor=event["motor"],
                joint=event["joint"], temperature_c=temp)
            problem(
                "faulted", event["joint"], "error",
                info["headline"],
                f"{info['disabled_note']} {info['advice']} Its steps were "
                "skipped, so it keeps its previous calibration.",
                motor=event["motor"], flags=flags,
                temperature_c=temp, fault_kind=info["kind"],
                needs_cooling=info["needs_cooling"])
            ctx.log(f"MOTOR FAULT: {info['headline']}. "
                    f"{info['disabled_note']} {info['advice']} Its steps are "
                    "skipped, so it keeps its previous calibration.")
        elif kind == "wrist_skipped":
            ctx.log("wrist already calibrated (motor limits and encoder "
                    "anchor) — skipping its steps; force wrist to re-run")
        elif kind == "calibration_started":
            progress["total"] = event["steps"]
            ctx.set_phase("calibrating", progress=0.0,
                          detail=f"{event['steps']} steps")
            ctx.log(f"calibration started: {event['steps']} steps "
                    f"({', '.join(event['joints'])})")
        elif kind == "step_started":
            step_joints = ", ".join(
                f"{j} {d}" for j, d in event["joints"].items())
            ctx.set_detail(
                f"step {event['index'] + 1}/{event['total']}: {step_joints}")
            ctx.log(f"step {event['index'] + 1}/{event['total']}: {step_joints}")
        elif kind == "step_done":
            progress["steps_done"] += 1
            ctx.set_progress((event["index"] + 1) / max(event["total"], 1))
        elif kind == "joint_calibrated":
            progress["joints_calibrated"].append(event["joint"])
            ctx.log(f"joint calibrated: {event['joint']} "
                    f"(ratio {event['ratio']:.4f})")
        elif kind == "calibration_done":
            ctx.log("calibration complete")
        elif kind == "calibration_aborted":
            ctx.log("calibration aborted — completed steps are persisted")

    def on_prompt(request: dict) -> str:
        """Park the op in awaiting_input until the operator answers."""
        joint, direction = request["joint"], request["direction"]
        end = "closed" if direction == "flex" else "open"
        answer = ctx.wait_input(
            f"Move {joint} all the way {end} ({direction}) by hand, hold it "
            f"against the stop, then record.",
            ["record", "skip", "abort"])
        if answer == "record":
            ctx.log(f"recording {joint} {direction} limit")
        return answer

    if manual:
        ctx.log("MANUAL calibration: torque stays off for the whole run. "
                "Move each joint to the end it names, hold it against the "
                "hardstop, and press record.")

    # calibrate() clears orca_core's stop event at entry: a stop that landed
    # while we were connecting would be swallowed. Check ours first.
    ctx.check_stop()
    started_at = _now_iso()
    error: str | None = None
    try:
        hand_ops.calibrate(
            hand,
            joints=joints,
            force_wrist=force_wrist,
            joint_encoder_client=encoder_client,
            progress_callback=on_event,
            manual=manual,
            prompt_callback=on_prompt if manual else None,
        )
    except BaseException as e:
        error = str(e) or type(e).__name__
        raise
    finally:
        path = calibration_log.append_run(hand.config.calibration_path, {
            "started_at": started_at,
            "finished_at": _now_iso(),
            "joints": joints,
            "force_wrist": force_wrist,
            "manual": manual,
            "problems": problems,
            "anchor_pass": encoder_client is not None,
            "completed": error is None,
            "error": error,
            "events": events,
        })
        if path is not None:
            ctx.log(f"calibration events archived to {path}")
    ctx.check_stop()
    return {
        "problems": problems,
        "steps_done": progress["steps_done"],
        "joints_calibrated": progress["joints_calibrated"],
        "anchors_recorded": progress["anchors_recorded"],
        "anchors_dead": progress["anchors_dead"],
        "calibrated": bool(hand.calibrated),
    }


class CalibrateOperation(Operation):
    kind = "calibrate"

    def __init__(self, params: dict):
        super().__init__(params)
        self._hand = None

    @classmethod
    def validate(cls, service, params: dict) -> dict:
        return validate_calibrate_params(service, params)

    def _want_joint_sensors(self, ctx: OpContext, hand) -> bool:
        """Whether this run also (re-)calibrates the joint sensors.

        Explicit param wins; the auto default re-anchors only joints that were
        never anchored, so a routine motor recalibration keeps the existing
        encoder anchors untouched.
        """
        choice = self.params.get("calibrate_joint_sensors")
        if choice is False:
            ctx.log("joint sensors: keeping existing encoder anchors "
                    "(calibrate_joint_sensors=false)")
            return False
        if choice is True:
            ctx.log("joint sensors: re-anchoring during this run")
            return True
        missing = hand_ops.missing_encoder_anchors(hand)
        joints = self.params.get("joints")
        if joints is not None:
            missing = [j for j in missing if j in joints]
        if missing:
            ctx.log("joint sensors: anchoring for the first time "
                    f"({', '.join(missing)} have no anchor)")
            return True
        if hand_ops.encoder_backed_joints(hand):
            ctx.log("joint sensors: already anchored — keeping existing "
                    "anchors (enable the joint-sensor option to redo them)")
        return False

    def run(self, ctx: OpContext) -> dict:
        supervisor = ctx.service.supervisor
        ctx.set_phase("acquiring", detail="taking the hand into maintenance")
        lease = supervisor.enter_maintenance(self.kind)
        hand = None
        encoder_client = None
        encoder_link = None
        try:
            ctx.check_stop()
            ctx.set_phase("connecting", detail="opening motor-only connection")
            overrides = {
                key: self.params[key]
                for key in ("calibration_current", "wrist_calibration_current")
                if self.params.get(key) is not None
            }
            hand = hand_ops.build_maintenance_hand(
                supervisor.config.config_path, ctx.stop_event,
                config_overrides=overrides or None)
            self._hand = hand
            for key, value in overrides.items():
                default = getattr(supervisor.config, key, None)
                ctx.log(f"{key} for this run: {value} mA"
                        + (f" (config default: {default} mA)"
                           if default is not None else ""))
            if self._want_joint_sensors(ctx, hand):
                try:
                    encoder_client, encoder_link = hand_ops.open_encoder_client(
                        supervisor.config, lease.presence)
                except Exception as e:
                    # Motor calibration still works without the anchor pass.
                    ctx.log(f"encoder client unavailable — skipping anchor pass: {e}")
                if encoder_client is not None:
                    ctx.log("encoder client attached for the anchor pass")
            return run_calibrate(
                hand, encoder_client, ctx,
                joints=self.params["joints"],
                force_wrist=self.params["force_wrist"],
                manual=self.params["manual"],
            )
        finally:
            self._hand = None
            hand_ops.close_encoder_client(encoder_client, encoder_link)
            if hand is not None:
                hand_ops.disconnect(hand)
            supervisor.exit_maintenance()

    def request_stop(self, ctx: OpContext) -> None:
        hand = self._hand
        if hand is not None:
            hand_ops.request_stop(hand)
