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
        steps = [{j: d for j, d in step.items() if j in wanted} for step in steps]
        steps = [step for step in steps if step]
    return steps


def simulate_calibration(
    ctx: OpContext,
    config,
    joints: list[str] | None,
    step_s: float,
    phase: str = "calibrating",
    detail_prefix: str = "",
) -> dict:
    """Lease-free simulated calibration body (shared with the sim wizard)."""
    steps = _calibration_steps(config, joints)
    total = len(steps)
    involved = sorted({j for step in steps for j in step})
    ctx.set_phase(phase, progress=0.0, detail=f"{detail_prefix}{total} steps")
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
    _snapshot_mock(ctx, config, manual=False, partial=joints is not None)
    return {
        "steps_done": total,
        "joints_calibrated": calibrated,
        "calibrated": True,
    }


def simulate_manual_calibration(
    ctx: OpContext, config, joints: list[str] | None
) -> dict:
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
        return {
            m: 180.0 + drift[m] + 10 * math.sin(time.monotonic() + m) for m in motors
        }

    motor_of = lambda joint: abs(config.joint_to_motor_map.get(joint, 0))  # noqa: E731
    capture = ManualCapture(ctx, plan, motor_of, read_deg)
    ctx.log(f"manual calibration started: {len(plan)} hardstops in {len(steps)} steps")
    recorded: dict[str, set] = {}
    index = 0
    while index < len(steps):
        step = steps[index]
        first = next(iter(step))
        motors = {j: motor_of(j) for j in step}
        drift.clear()
        answer = capture.prompt(
            {
                "joint": first,
                "direction": step[first],
                "motor": motors[first],
                "joints": step,
                "motors": motors,
                "step_index": index,
                "can_back": index > 0,
            }
        )
        if answer == "back":
            index -= 1
            capture.on_event(
                {
                    "event": "manual_capture_back",
                    "index": index,
                    "joints": dict(steps[index]),
                }
            )
            ctx.log(f"back to step {index + 1}")
            continue
        index += 1
        for joint, direction in step.items():
            if answer == "record":
                capture.on_event(
                    {
                        "event": "limit_recorded",
                        "joint": joint,
                        "limit": math.radians(read_deg([motors[joint]])[motors[joint]]),
                    }
                )
                recorded.setdefault(joint, set()).add(direction)
            else:
                capture.on_event({"event": "manual_capture_skipped", "joint": joint})
        ctx.log(
            f"{', '.join(step)} {step[first]}: {'recorded' if answer == 'record' else 'skipped'}"
        )
    ctx.log("manual calibration complete")
    calibrated = [j for j, d in recorded.items() if d == {"flex", "extend"}]
    _snapshot_mock(ctx, config, manual=True, partial=joints is not None)
    return {
        "steps_done": len(steps),
        "joints_calibrated": calibrated,
        "calibrated": True,
    }


def _snapshot_mock(ctx: OpContext, config, manual: bool, partial: bool = False) -> None:
    """The mock writes no calibration, so snapshot the model's shipped one — the
    console exercises the same promote/activate path as on hardware."""
    from orca_ui.hand import baselines

    try:
        name = baselines.snapshot_from_file(
            config,
            config.calibration_path,
            source="manual" if manual else "auto",
            hand_key=ctx.service.supervisor.hand_id,
            partial=partial,
        )
        ctx.log(f"travel snapshot saved as {name}")
    except Exception as e:
        ctx.log(f"travel snapshot not saved: {e}")


def simulate_tension(
    ctx: OpContext,
    move_motors: bool,
    step_s: float,
    detail_prefix: str = "",
    offset_deg: float | None = None,
) -> None:
    """Lease-free simulated tension body: winds, then parks in
    awaiting_input until released (queue path — nothing is blocked)."""
    if move_motors:
        ctx.set_phase("winding", detail=f"{detail_prefix}pre-conditioning tendons")
        ctx.log("winding tendons until the motors stall")
        for wind_pass in (1, 2):
            ctx.set_detail(f"{detail_prefix}winding pass {wind_pass}/2")
            ctx.sleep(step_s)
        ctx.set_phase("ramp", detail=f"{detail_prefix}releasing wind-in current")
        ctx.log("ramping current down before the hold")
        ctx.sleep(step_s)
    ctx.set_phase(
        "holding", detail=f"{detail_prefix}motors holding — tension the spools"
    )
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
    ctx.set_phase(
        "released", detail=f"{detail_prefix}torque off, control mode restored"
    )
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
                return simulate_manual_calibration(
                    ctx, supervisor.config, self.params["joints"]
                )
            return simulate_calibration(
                ctx,
                supervisor.config,
                self.params["joints"],
                self.params["step_duration_s"],
            )
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
            simulate_tension(
                ctx,
                self.params["move_motors"],
                self.params["step_duration_s"],
                offset_deg=self.params.get("offset_deg", DEFAULT_TENSION_OFFSET_DEG),
            )
            hand_ops.record_hold_tension(supervisor.config)
            return {"released": True}
        finally:
            supervisor.exit_maintenance()


def simulate_slack_test(ctx: OpContext, config, params: dict, hold, progress) -> dict:
    """Lease-free simulated slack test: each joint is held on prompt and turns a
    few degrees, the joints named in ``params["unspool"]`` past half a turn."""
    import dataclasses
    import random

    from orca_core.maintenance.slack_test import FAIL, SlackResult, SlackTestSettings

    settings = SlackTestSettings(**(params.get("settings") or {}))
    joints = [j for j in config.joint_ids if j != "wrist" and j in config.joint_to_motor_map]
    if params.get("joints") is not None:
        joints = [j for j in joints if j in set(params["joints"])]
    motors = [int(config.joint_to_motor_map[j]) for j in joints]
    rng = random.Random(3)
    slack = {j: rng.uniform(0.0, 6.0) for j in joints}
    for j in params.get("unspool") or []:
        slack[j] = settings.max_free_deg
    progress({"event": "slack_plan", "joints": joints, "motors": motors})
    step_s = params["step_duration_s"]
    out = []
    for n, (j, m) in enumerate(zip(joints, motors)):
        r = SlackResult(j, m)
        progress({"event": "slack_joint", "joint": j, "motor": m, "index": n})
        if not hold(j):
            r.skipped = True
        else:
            for direction, sense in ((1, "flex"), (-1, "extend")):
                progress({"event": "slack_phase", "joint": j, "direction": direction, "sense": sense})
                for k in range(1, 4):
                    ctx.check_stop()
                    progress({"event": "slack_sample", "joint": j, "direction": direction,
                              "deg": round(slack[j] * k / 3, 2)})
                    ctx.sleep(step_s / 6)
                # Like the real test, never wind past the half turn in total.
                budget = settings.max_free_deg + 5.0 - r.plus_deg
                if direction > 0:
                    r.plus_deg, r.plus_sense = min(slack[j], budget), sense
                else:
                    r.minus_deg, r.minus_sense = min(slack[j] * 0.8, budget), sense
        out.append(r.to_dict(settings))
        progress({"event": "slack_joint_done", "result": out[-1]})
    return {"joints": joints, "results": out, "blocked": any(r["status"] == FAIL for r in out),
            "settings": dataclasses.asdict(settings)}
