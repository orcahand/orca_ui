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

from orca_ui.hand.operations import hand_ops
from orca_ui.hand.operations.base import OpContext, Operation

RELEASE_PROMPT = "Motors holding — tension the spools, then release"


def validate_tension_params(service, params: dict) -> dict:
    from orca_ui.hand.service import ServiceError

    session = service.session
    if session is None:
        raise ServiceError("hand not connected", status_code=503)
    if not session.caps.motors:
        raise ServiceError("no motor bus — tensioning needs motors",
                           status_code=409)
    return {"move_motors": bool(params.get("move_motors", True))}


def run_tension(hand, ctx: OpContext, move_motors: bool) -> None:
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
                ctx.announce_input(RELEASE_PROMPT, ["Release"])
            elif phase == "released":
                ctx.log("hold released — torque off, control mode restored")
        elif kind == "winding_progress":
            ctx.set_detail(
                f"winding pass {event['stage']}/{event['stages']}")

    hand_ops.tension(hand, move_motors=move_motors, progress_callback=on_event)
    ctx.resume_running()
    ctx.set_phase("released", detail="torque off, control mode restored")


class TensionOperation(Operation):
    kind = "tension"

    def __init__(self, params: dict):
        super().__init__(params)
        self._hand = None

    @classmethod
    def validate(cls, service, params: dict) -> dict:
        return validate_tension_params(service, params)

    def run(self, ctx: OpContext) -> dict:
        supervisor = ctx.service.supervisor
        ctx.set_phase("acquiring", detail="taking the hand into maintenance")
        supervisor.enter_maintenance(self.kind)
        hand = None
        try:
            ctx.check_stop()
            ctx.set_phase("connecting", detail="opening motor-only connection")
            hand = hand_ops.build_maintenance_hand(
                supervisor.config.config_path, ctx.stop_event)
            self._hand = hand
            run_tension(hand, ctx, move_motors=self.params["move_motors"])
            ctx.check_stop()
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
        # Release: end the hold as a *successful* completion. The op thread
        # is blocked inside tension(); interrupt it via the hand stop event
        # (ctx.stop_event stays clear, so run() finishes normally).
        hand = self._hand
        if hand is not None:
            hand_ops.request_stop(hand)
        return True
