"""Calibration as a maintenance operation.

The supervisor lends the hardware (MAINTENANCE lease), the op builds its own
motor-only hand + UI-owned encoder client — the scripts/calibrate.py pattern,
which sidesteps orca_core's refusal to calibrate while the feedback loop runs.

``run_calibrate`` is deliberately lease-free so the wizard (M6) can compose
tension + calibrate rounds under one lease.
"""

from __future__ import annotations

from orca_ui.hand.operations import hand_ops
from orca_ui.hand.operations.base import OpContext, Operation


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
    return {"joints": joints, "force_wrist": bool(params.get("force_wrist", False))}


def apply_calibration_current(hand, current: float | None, ctx: OpContext) -> None:
    """Drive every joint onto its hardstops at ``current`` — the ceiling the
    console is set to. A per-group table shipped with the model is dropped, so
    the figure logged here is the one every joint is driven at."""
    if current is None:
        return
    config = hand.config
    current = int(round(current))
    if config.wrist_calibration_current == config.calibration_current:
        object.__setattr__(config, "wrist_calibration_current", current)
    object.__setattr__(config, "calibration_current", current)
    groups = {family: table for family, table in config.calibration_current_v21_dict.items()
              if family != str(config.motor_type)}
    object.__setattr__(config, "calibration_current_v21_dict", groups)
    ctx.log("driving the hardstops at each motor's full available current; "
            f"wrist at {current} mA")


def _drive_current_cell(now, before) -> str:
    """One direction's mean current, with its change since the previous run."""
    if now is None:
        return "--"
    if before in (None, 0):
        return f"{now:.0f}"
    delta = now - before
    return f"{now:.0f} ({delta:+.0f}, {100 * delta / before:+.0f}%)"


def _drive_current_lines(measured: dict, previous: dict | None = None) -> list[str]:
    """The mean current each joint drew onto its stops, as log lines.

    Informational: a joint well above its siblings, or one that has climbed
    since the last run, is the signature of an over-tensioned tendon.
    """
    if not measured:
        return []
    previous = previous or {}
    lines = ["mean current onto the hardstops, flex / extend (mA, change "
             "since the previous run):"]
    for joint, per_direction in measured.items():
        was = previous.get(joint, {})
        lines.append(
            f"  {joint}: "
            f"{_drive_current_cell(per_direction.get('flex'), was.get('flex'))}"
            f" / {_drive_current_cell(per_direction.get('extend'), was.get('extend'))}")
    return lines


# The v2.1 travel check: how calibration answered a joint whose motor travel
# fell short of (or beyond) its baseline.
_TRAVEL_NOTE = {
    "travel_excess": "beyond the baseline — check the tendon for slip",
    "travel_retry_started": "short — re-driving at a higher current",
    "travel_retry_succeeded": "reached on a re-drive",
    "travel_retry_exhausted": "still short after every re-drive — calibrated over a shortened range",
    "travel_retry_skipped": "did not move — not re-driven",
    "travel_retry_unavailable": "short, and its control mode ignores the current cap",
    "travel_retry_disabled": "short — re-drive disabled",
}


def _travel_line(event: dict, note: str) -> str:
    line = (f"{event['joint']}: travel {event['travel_deg']:.0f}° of "
            f"{event['expected_deg']:.0f}° — {note}")
    if "current" in event and "attempt" in event:
        line += f" (attempt {event['attempt']}, {event['current']:.0f} mA)"
    return line


def run_calibrate(hand, encoder_client, ctx: OpContext,
                  joints: list[str] | None, force_wrist: bool) -> dict:
    """Blocking calibration with progress mapped onto the op snapshot."""
    progress = {"steps_done": 0, "total": 0, "joints_calibrated": [],
                "anchors_recorded": [], "anchors_dead": [], "travel_logged": False}

    def on_event(event: dict) -> None:
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
            # What the numbers above mean, so the log reads on its own.
            ctx.log("ratio: motor radians per joint degree — the motor travel between the two "
                    "hardstops found, divided by the joint's range of motion")
            if progress["travel_logged"]:
                ctx.log("travel: motor-shaft travel between the hardstops in degrees, against the "
                        "hand's joint_motor_travel baseline; mA: the current the joint was driven "
                        "onto its hardstops with")
            for line in _drive_current_lines(
                    event.get("drive_current_ma") or {},
                    event.get("drive_current_previous_ma") or {}):
                ctx.log(line)
        elif kind == "calibration_aborted":
            ctx.log("calibration aborted — completed steps are persisted")
        elif kind == "joints_skipped":
            ctx.log(f"skipping {', '.join(event['joints'])}: {event['reason']}")
        elif kind == "travel_checked":
            if not event["within_margin"]:
                progress["travel_logged"] = True
                ctx.log(_travel_line(event, "outside the margin"))
        elif kind.startswith("travel_") and kind != "travel_baseline_missing":
            progress["travel_logged"] = True
            ctx.log(_travel_line(event, _TRAVEL_NOTE.get(kind, kind)))
        elif kind == "overrun_retry":
            ctx.log(f"{event['joint']}: turned {event['travel_deg']:.0f}° past its "
                    f"{event['limit_deg']:.0f}° limit without meeting a stop — the belt is "
                    f"poorly set (slipping); driving again at {100 * event['pwm_fraction']:.0f}% "
                    f"output (attempt {event['attempt']})")
        elif kind == "hardstop_not_found":
            ctx.log(f"{event['joint']}: no hardstop within {event['limit_deg']:.0f}° — given up, "
                    "limit not recorded. The belt or tendon is slack or broken: tension it and "
                    "calibrate again")
        elif kind == "drive_step_timeout":
            ctx.log(f"{event['joint']}: never settled on a hardstop — given up, limit not recorded")

    # calibrate() clears orca_core's stop event at entry: a stop that landed
    # while we were connecting would be swallowed. Check ours first.
    ctx.check_stop()
    hand_ops.calibrate(
        hand,
        joints=joints,
        force_wrist=force_wrist,
        joint_encoder_client=encoder_client,
        progress_callback=on_event,
    )
    ctx.check_stop()
    return {
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
            hand = hand_ops.build_maintenance_hand(
                supervisor.config, ctx.stop_event,
                motor_port=lease.presence.motor_port if lease.presence else None)
            self._hand = hand
            apply_calibration_current(hand, ctx.service.max_current, ctx)
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
