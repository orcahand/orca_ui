"""Simulated maintenance operations for --mock.

The mock serial link doesn't emulate motor stalls, so the real
calibrate()/tension() would never terminate against it. These emit the same
snapshot/log sequence as the real operations on a timer — and they still take
the REAL maintenance lease, so the supervisor FSM path (session teardown →
MAINTENANCE → reconnect) is exercised end-to-end.
"""

from __future__ import annotations

from orca_ui.hand.operations.base import OpContext, Operation
from orca_ui.hand.operations.calibrate import validate_calibrate_params
from orca_ui.hand.operations.tension import RELEASE_PROMPT, validate_tension_params

DEFAULT_STEP_S = 0.3


def _sim_step_duration(params: dict) -> float:
    try:
        value = float(params.get("step_duration_s", DEFAULT_STEP_S))
    except (TypeError, ValueError):
        value = DEFAULT_STEP_S
    return min(max(value, 0.02), 2.0)


def _calibration_steps(config, joints: list[str] | None) -> list[dict]:
    """The step plan the real _calibrate would run (joints filter applied)."""
    steps = [dict(step["joints"]) for step in config.calibration_sequence]
    if not any("wrist" in step for step in steps):
        steps.append({"wrist": "flex"})
        steps.append({"wrist": "extend"})
    if joints is not None:
        wanted = set(joints)
        steps = [
            {j: d for j, d in step.items() if j in wanted}
            for step in steps
        ]
        steps = [step for step in steps if step]
    return steps


class SimulatedCalibrateOperation(Operation):
    kind = "calibrate"

    @classmethod
    def validate(cls, service, params: dict) -> dict:
        clean = validate_calibrate_params(service, params)
        clean["step_duration_s"] = _sim_step_duration(params)
        return clean

    def run(self, ctx: OpContext) -> dict:
        supervisor = ctx.service.supervisor
        ctx.set_phase("acquiring", detail="taking the hand into maintenance")
        supervisor.enter_maintenance(self.kind)
        try:
            ctx.set_phase("connecting", detail="opening motor-only connection")
            ctx.sleep(self.params["step_duration_s"])

            steps = _calibration_steps(supervisor.config, self.params["joints"])
            total = len(steps)
            involved = sorted({j for step in steps for j in step})
            ctx.set_phase("calibrating", progress=0.0, detail=f"{total} steps")
            ctx.log(f"calibration started: {total} steps ({', '.join(involved)})")

            directions_seen: dict[str, set] = {}
            calibrated: list[str] = []
            for index, step in enumerate(steps):
                step_joints = ", ".join(f"{j} {d}" for j, d in step.items())
                ctx.set_detail(f"step {index + 1}/{total}: {step_joints}")
                ctx.log(f"step {index + 1}/{total}: {step_joints}")
                ctx.sleep(self.params["step_duration_s"])
                for joint, direction in step.items():
                    seen = directions_seen.setdefault(joint, set())
                    seen.add(direction)
                    if seen == {"flex", "extend"}:
                        calibrated.append(joint)
                        ctx.log(f"joint calibrated: {joint} (ratio 0.0500)")
                ctx.set_progress((index + 1) / max(total, 1))
            ctx.log("calibration complete")
            return {
                "steps_done": total,
                "joints_calibrated": calibrated,
                "calibrated": True,
            }
        finally:
            supervisor.exit_maintenance()


class SimulatedTensionOperation(Operation):
    kind = "tension"

    @classmethod
    def validate(cls, service, params: dict) -> dict:
        clean = validate_tension_params(service, params)
        clean["step_duration_s"] = _sim_step_duration(params)
        return clean

    def run(self, ctx: OpContext) -> dict:
        supervisor = ctx.service.supervisor
        ctx.set_phase("acquiring", detail="taking the hand into maintenance")
        supervisor.enter_maintenance(self.kind)
        try:
            ctx.set_phase("connecting", detail="opening motor-only connection")
            ctx.sleep(self.params["step_duration_s"])
            if self.params["move_motors"]:
                ctx.set_phase("winding", detail="pre-conditioning tendons")
                ctx.log("winding tendons until the motors stall")
                for wind_pass in (1, 2):
                    ctx.set_detail(f"winding pass {wind_pass}/2")
                    ctx.sleep(self.params["step_duration_s"])
                ctx.set_phase("ramp", detail="releasing wind-in current")
                ctx.log("ramping current down before the hold")
                ctx.sleep(self.params["step_duration_s"])
            ctx.set_phase("holding", detail="motors holding — tension the spools")
            ctx.log("holding — tension the spools, then click Release")
            ctx.wait_input(RELEASE_PROMPT, ["Release"])
            ctx.set_phase("released", detail="torque off, control mode restored")
            ctx.log("hold released — torque off, control mode restored")
            return {"released": True}
        finally:
            supervisor.exit_maintenance()
