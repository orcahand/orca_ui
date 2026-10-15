"""Simulated maintenance operations for --mock.

The mock serial link doesn't emulate motor stalls, so the real
calibrate()/tension() would never terminate against it. These emit the same
snapshot/log sequence as the real operations on a timer — and they still take
the REAL maintenance lease, so the supervisor FSM path (session teardown →
MAINTENANCE → reconnect) is exercised end-to-end.
"""

from __future__ import annotations

from orca_ui.hand.operations import hand_ops
from orca_ui.hand.operations.base import OpContext, Operation
from orca_ui.hand.operations.calibrate import (
    ManualCapture,
    manual_capture_plan,
    manual_capture_steps,
    validate_calibrate_params,
)
from orca_ui.hand.operations.tension import (
    DEFAULT_TENSION_OFFSET_DEG,
    EXTRA_DEG,
    PULL_MORE,
    RELEASE,
    RELEASE_PROMPT,
    validate_tension_params,
)

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


def simulate_calibration(ctx: OpContext, config, joints: list[str] | None,
                         step_s: float, phase: str = "calibrating",
                         detail_prefix: str = "") -> dict:
    """Lease-free simulated calibration body (shared with the sim wizard)."""
    steps = _calibration_steps(config, joints)
    total = len(steps)
    involved = sorted({j for step in steps for j in step})
    ctx.set_phase(phase, progress=0.0,
                  detail=f"{detail_prefix}{total} steps")
    ctx.log(f"calibration started: {total} steps ({', '.join(involved)})")

    directions_seen: dict[str, set] = {}
    calibrated: list[str] = []
    for index, step in enumerate(steps):
        step_joints = ", ".join(f"{j} {d}" for j, d in step.items())
        ctx.set_detail(f"{detail_prefix}step {index + 1}/{total}: {step_joints}")
        ctx.log(f"step {index + 1}/{total}: {step_joints}")
        ctx.sleep(step_s)
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


def simulate_manual_calibration(ctx: OpContext, config, joints: list[str] | None) -> dict:
    """Simulated manual run: asks for every hardstop; the motor drifts while it waits."""
    import math
    import random
    import time

    steps = manual_capture_steps(config, joints)
    plan = manual_capture_plan(steps)
    drift: dict[int, float] = {}

    def read_deg(motors: list[int]) -> dict[int, float]:
        for m in motors:
            drift[m] = drift.get(m, 0.0) + random.uniform(-3, 6)
        return {m: 180.0 + drift[m] + 10 * math.sin(time.monotonic() + m) for m in motors}

    motor_of = lambda joint: abs(config.joint_to_motor_map.get(joint, 0))  # noqa: E731
    capture = ManualCapture(ctx, plan, motor_of, read_deg)
    ctx.log(f"manual calibration started: {len(plan)} hardstops in {len(steps)} steps")
    recorded: dict[str, set] = {}
    for step in steps:
        first = next(iter(step))
        motors = {j: motor_of(j) for j in step}
        drift.clear()
        answer = capture.prompt({"joint": first, "direction": step[first], "motor": motors[first],
                                 "joints": step, "motors": motors})
        for joint, direction in step.items():
            if answer == "record":
                capture.on_event({"event": "limit_recorded", "joint": joint,
                                  "limit": math.radians(read_deg([motors[joint]])[motors[joint]])})
                recorded.setdefault(joint, set()).add(direction)
            else:
                capture.on_event({"event": "manual_capture_skipped", "joint": joint})
        ctx.log(f"{', '.join(step)} {step[first]}: {'recorded' if answer == 'record' else 'skipped'}")
    ctx.log("manual calibration complete")
    calibrated = [j for j, d in recorded.items() if d == {"flex", "extend"}]
    return {"steps_done": len(steps), "joints_calibrated": calibrated, "calibrated": True}


def simulate_tension(ctx: OpContext, move_motors: bool, step_s: float,
                     detail_prefix: str = "", offset_deg: float | None = None) -> None:
    """Lease-free simulated tension body: winds, then parks in
    awaiting_input until released (queue path — nothing is blocked)."""
    if move_motors:
        ctx.set_phase("winding",
                      detail=f"{detail_prefix}pre-conditioning tendons")
        ctx.log("winding tendons until the motors stall")
        for wind_pass in (1, 2):
            ctx.set_detail(f"{detail_prefix}winding pass {wind_pass}/2")
            ctx.sleep(step_s)
        ctx.set_phase("ramp", detail=f"{detail_prefix}releasing wind-in current")
        ctx.log("ramping current down before the hold")
        ctx.sleep(step_s)
    ctx.set_phase("holding",
                  detail=f"{detail_prefix}motors holding — tension the spools")
    ctx.log("holding — tension the spools, then click Release")
    # The wizard's hold (no offset) only releases; the tension step can also pull more.
    options = [RELEASE] if offset_deg is None else [RELEASE, PULL_MORE]
    pulled = offset_deg or 0.0
    if offset_deg is not None:
        ctx.set_extra({"pulled_deg": pulled})
    while ctx.wait_input(RELEASE_PROMPT, options) == PULL_MORE:
        pulled += EXTRA_DEG
        ctx.set_extra({"pulled_deg": pulled})
        ctx.log(f"finger motors turned {pulled:g}° counterclockwise")
    ctx.set_phase("released",
                  detail=f"{detail_prefix}torque off, control mode restored")
    ctx.log("hold released — torque off, control mode restored")


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
            if self.params.get("manual"):
                return simulate_manual_calibration(ctx, supervisor.config, self.params["joints"])
            return simulate_calibration(
                ctx, supervisor.config, self.params["joints"],
                self.params["step_duration_s"])
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
            simulate_tension(ctx, self.params["move_motors"],
                             self.params["step_duration_s"],
                             offset_deg=self.params.get("offset_deg", DEFAULT_TENSION_OFFSET_DEG))
            hand_ops.record_hold_tension(supervisor.config)
            return {"released": True}
        finally:
            supervisor.exit_maintenance()
