"""Tensioning as a maintenance operation: wind → ramp → hold → release.

orca_core's tension() runs BLOCKING on the op thread (the background-task
path has a lost-stop race and an unbounded join). While it holds, the op
parks in ``awaiting_input`` via ctx.announce_input; the Release answer (and
stop/e-stop) interrupts the hold by setting the hand's task-stop event from
the caller thread — orca_core's finally restores control mode and disables
torque.

``run_tension`` is lease-free for wizard composition (M6).
"""

from __future__ import annotations

import threading

from orca_ui.hand.operations import hand_ops
from orca_ui.hand.operations.base import OpContext, Operation

RELEASE_PROMPT = "Motors holding — tension the spools, then release"
RELEASE = "Release"
PULL_MORE = "Pull more"  # turns the finger motors further counterclockwise; the hold goes on
# Matching orca_core's TENSION_OFFSET_DEG / TENSION_EXTRA_DEG: the slow pull, and what one Pull more adds.
# 0 holds the motors still, as tensioning did before the guided rework. A pull
# leaves a standing position error, which saturates the goal current and takes
# away the headroom the motor needs to resist the ratchet.
DEFAULT_TENSION_OFFSET_DEG = 0.0
EXTRA_DEG = 15.0
OFFSET_BOUNDS_DEG = (0.0, 45.0)


def validate_tension_params(service, params: dict) -> dict:
    from orca_ui.hand.service import ServiceError

    session = service.session
    if session is None:
        raise ServiceError("hand not connected", status_code=503)
    if not session.caps.motors:
        raise ServiceError("no motor bus — tensioning needs motors",
                           status_code=409)
    clean = {"move_motors": bool(params.get("move_motors", True))}
    if params.get("offset_deg") is not None:
        try:
            offset = float(params["offset_deg"])
        except (TypeError, ValueError):
            raise ServiceError("offset_deg must be a number of degrees", status_code=422)
        low, high = OFFSET_BOUNDS_DEG
        if not low <= offset <= high:
            raise ServiceError(f"offset_deg must be between {low:.0f} and {high:.0f}°",
                               status_code=422)
        clean["offset_deg"] = offset
    return clean


def run_tension(hand, ctx: OpContext, move_motors: bool, offset_deg: float | None = None,
                pull_more=None) -> None:
    def on_event(event: dict) -> None:
        kind = event.get("event")
        if kind == "phase":
            phase = event["phase"]
            if phase == "winding":
                ctx.set_phase("winding", detail="pre-conditioning tendons")
                ctx.log("winding tendons until the motors stall")
            elif phase == "ramp":
                ctx.set_phase("ramp", detail="releasing wind-in current")
                ctx.log("ramping current down before the hold")
            elif phase == "holding":
                ctx.set_phase("holding",
                              detail="motors holding — tension the spools")
                ctx.log("holding — tension the spools, then click Release")
                ctx.announce_input(RELEASE_PROMPT, [RELEASE] + ([PULL_MORE] if pull_more else []))
            elif phase == "released":
                ctx.log("hold released — torque off, control mode restored")
        elif kind == "pulled":
            ctx.set_extra({"pulled_deg": event["total_deg"]})
            ctx.log(f"finger motors turned {event['total_deg']:g}° counterclockwise")
        elif kind == "winding_progress":
            ctx.set_detail(
                f"winding pass {event['stage']}/{event['stages']}")

    hand_ops.tension(hand, move_motors=move_motors, progress_callback=on_event,
                     offset_deg=offset_deg, pull_more=pull_more)
    ctx.resume_running()
    ctx.set_phase("released", detail="torque off, control mode restored")


class TensionOperation(Operation):
    kind = "tension"

    def __init__(self, params: dict):
        super().__init__(params)
        self._hand = None
        self._pull = threading.Event()

    def _pull_requested(self) -> bool:
        requested = self._pull.is_set()
        self._pull.clear()
        return requested

    @classmethod
    def validate(cls, service, params: dict) -> dict:
        return validate_tension_params(service, params)

    def run(self, ctx: OpContext) -> dict:
        supervisor = ctx.service.supervisor
        ctx.set_phase("acquiring", detail="taking the hand into maintenance")
        lease = supervisor.enter_maintenance(self.kind)
        hand = None
        try:
            ctx.check_stop()
            ctx.set_phase("connecting", detail="opening motor-only connection")
            hand = hand_ops.build_maintenance_hand(
                supervisor.config, ctx.stop_event,
                motor_port=lease.presence.motor_port if lease.presence else None)
            self._hand = hand
            run_tension(hand, ctx, move_motors=self.params["move_motors"],
                        offset_deg=self.params.get("offset_deg"),
                        pull_more=self._pull_requested)
            ctx.check_stop()
            hand_ops.record_hold_tension(supervisor.config)
            return {"released": True}
        finally:
            self._hand = None
            if hand is not None:
                hand_ops.disconnect(hand)
            supervisor.exit_maintenance()

    def request_stop(self, ctx: OpContext) -> None:
        hand = self._hand
        if hand is not None:
            hand_ops.request_stop(hand)

    def handle_input(self, value: str) -> bool:
        if value == PULL_MORE:
            self._pull.set()
            return True
        # Release: end the hold as a *successful* completion. The op thread
        # is blocked inside tension(); interrupt it via the hand stop event
        # (ctx.stop_event stays clear, so run() finishes normally).
        hand = self._hand
        if hand is not None:
            hand_ops.request_stop(hand)
        return True
