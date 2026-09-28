"""The guided bring-up wizard: (tension → calibrate) × rounds.

Mirrors orca_core's scripts/setup.py under ONE maintenance lease: a single
motor-only hand (+ encoder client) is reused across rounds, composing the
lease-free run_tension / run_calibrate bodies. Confirm gates between rounds
park in ``awaiting_input``.

Input routing: "Release" ends a tension hold (the op thread is blocked
inside orca_core — consumed by the handle_input hook via the hand's
task-stop event); every other value (Continue / Finish) feeds the queue for
the blocking round-gate wait_input.
"""

from __future__ import annotations

from orca_ui.hand.operations import hand_ops
from orca_ui.hand.operations.base import OpContext, Operation
from orca_ui.hand.operations.calibrate import run_calibrate
from orca_ui.hand.operations.tension import run_tension, validate_tension_params

MAX_ROUNDS = 5
DEFAULT_ROUNDS = 3


def validate_wizard_params(service, params: dict) -> dict:
    from orca_ui.hand.service import ServiceError

    validate_tension_params(service, {})   # session + motors preconditions
    try:
        rounds = int(params.get("rounds", DEFAULT_ROUNDS))
    except (TypeError, ValueError):
        raise ServiceError("rounds must be an integer")
    if not 1 <= rounds <= MAX_ROUNDS:
        raise ServiceError(f"rounds must be between 1 and {MAX_ROUNDS}")
    return {"rounds": rounds}


class WizardOperation(Operation):
    kind = "wizard"

    def __init__(self, params: dict):
        super().__init__(params)
        self._hand = None

    @classmethod
    def validate(cls, service, params: dict) -> dict:
        return validate_wizard_params(service, params)

    def run(self, ctx: OpContext) -> dict:
        supervisor = ctx.service.supervisor
        rounds = self.params["rounds"]
        ctx.set_phase("acquiring", detail="taking the hand into maintenance")
        lease = supervisor.enter_maintenance(self.kind)
        hand = None
        encoder_client = None
        encoder_link = None
        rounds_completed = 0
        try:
            ctx.check_stop()
            ctx.set_phase("connecting", detail="opening motor-only connection")
            hand = hand_ops.build_maintenance_hand(
                supervisor.config.config_path, ctx.stop_event)
            self._hand = hand
            try:
                encoder_client, encoder_link = hand_ops.open_encoder_client(
                    supervisor.config, lease.presence)
            except Exception as e:
                ctx.log(f"encoder client unavailable — skipping anchor pass: {e}")

            for round_index in range(1, rounds + 1):
                prefix = f"round {round_index}/{rounds}: "
                ctx.log(f"— wizard round {round_index}/{rounds}: tension —")
                run_tension(hand, ctx, move_motors=True)
                ctx.check_stop()

                ctx.log(f"— wizard round {round_index}/{rounds}: calibrate —")
                ctx.set_phase("calibrating", detail=prefix + "starting")
                run_calibrate(hand, encoder_client, ctx,
                              joints=None, force_wrist=False)
                ctx.check_stop()
                rounds_completed = round_index

                if round_index < rounds:
                    choice = ctx.wait_input(
                        f"Round {round_index}/{rounds} complete — run "
                        f"another tension + calibration round?",
                        ["Continue", "Finish"])
                    if choice == "Finish":
                        ctx.log("wizard finished early by user")
                        break
            return {"rounds_completed": rounds_completed,
                    "calibrated": bool(hand.calibrated)}
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

    def handle_input(self, value: str) -> bool:
        # Only the tension hold's Release is consumed here (the op thread is
        # blocked inside orca_core then); round-gate answers use the queue.
        if value == "Release":
            hand = self._hand
            if hand is not None:
                hand_ops.request_stop(hand)
            return True
        return False


class SimulatedWizardOperation(Operation):
    kind = "wizard"

    @classmethod
    def validate(cls, service, params: dict) -> dict:
        from orca_ui.hand.operations.simulated import _sim_step_duration

        clean = validate_wizard_params(service, params)
        clean["step_duration_s"] = _sim_step_duration(params)
        return clean

    def run(self, ctx: OpContext) -> dict:
        from orca_ui.hand.operations.simulated import (
            simulate_calibration,
            simulate_tension,
        )

        supervisor = ctx.service.supervisor
        rounds = self.params["rounds"]
        step_s = self.params["step_duration_s"]
        ctx.set_phase("acquiring", detail="taking the hand into maintenance")
        supervisor.enter_maintenance(self.kind)
        rounds_completed = 0
        try:
            ctx.set_phase("connecting", detail="opening motor-only connection")
            ctx.sleep(step_s)
            for round_index in range(1, rounds + 1):
                prefix = f"round {round_index}/{rounds}: "
                ctx.log(f"— wizard round {round_index}/{rounds}: tension —")
                simulate_tension(ctx, True, step_s, detail_prefix=prefix)
                ctx.log(f"— wizard round {round_index}/{rounds}: calibrate —")
                simulate_calibration(ctx, supervisor.config, None, step_s,
                                     detail_prefix=prefix)
                rounds_completed = round_index
                if round_index < rounds:
                    choice = ctx.wait_input(
                        f"Round {round_index}/{rounds} complete — run "
                        f"another tension + calibration round?",
                        ["Continue", "Finish"])
                    if choice == "Finish":
                        ctx.log("wizard finished early by user")
                        break
            return {"rounds_completed": rounds_completed, "calibrated": True}
        finally:
            supervisor.exit_maintenance()
