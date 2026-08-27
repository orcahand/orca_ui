"""Simulated maintenance operations for --mock.

The mock serial link doesn't emulate motor stalls, so the real
calibrate()/tension() would never terminate against it. These emit the same
snapshot/log sequence as the real operations on a timer — and they still take
the REAL maintenance lease, so the supervisor FSM path (session teardown →
MAINTENANCE → reconnect) is exercised end-to-end.
"""

from __future__ import annotations

import time

from orca_ui.hand import calibration_log
from orca_ui.hand.operations.base import OpContext, Operation
from orca_ui.hand.operations.calibrate import _now_iso, validate_calibrate_params
from orca_ui.hand.operations.tension import RELEASE_PROMPT, validate_tension_params

DEFAULT_STEP_S = 0.3
_SIM_COUNTS_PER_REV = 16384
_SIM_LSB_DEG = 360.0 / _SIM_COUNTS_PER_REV


def _sim_count(joint: str) -> int:
    """Deterministic fake magnet count — stable across runs (zero drift)."""
    value = 7919
    for ch in joint:
        value = (value * 131 + ord(ch)) % _SIM_COUNTS_PER_REV
    return value


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
                         detail_prefix: str = "",
                         force_wrist: bool = False) -> dict:
    """Lease-free simulated calibration body (shared with the sim wizard).

    Mirrors the real run's event stream — including synthetic (drift-free)
    hardstop magnet counts for encoder-backed joints — and archives it to the
    calibration history, so the mock exercises the same log the hardware
    writes.
    """
    from orca_ui.hand.service import _encoder_sensed_joints

    steps = _calibration_steps(config, joints)
    total = len(steps)
    involved = sorted({j for step in steps for j in step})
    encoder_backed = set(_encoder_sensed_joints(config))
    events: list[dict] = []

    def record(kind: str, **fields) -> None:
        events.append({"t": round(time.time(), 3), "event": kind, **fields})

    ctx.set_phase(phase, progress=0.0,
                  detail=f"{detail_prefix}{total} steps")
    ctx.log(f"calibration started: {total} steps ({', '.join(involved)})")
    record("calibration_started", steps=total, joints=involved)

    started_at = _now_iso()
    directions_seen: dict[str, set] = {}
    calibrated: list[str] = []
    try:
        for index, step in enumerate(steps):
            step_joints = ", ".join(f"{j} {d}" for j, d in step.items())
            ctx.set_detail(
                f"{detail_prefix}step {index + 1}/{total}: {step_joints}")
            ctx.log(f"step {index + 1}/{total}: {step_joints}")
            record("step_started", index=index, total=total,
                   joints=dict(step))
            ctx.sleep(step_s)
            for joint, direction in step.items():
                seen = directions_seen.setdefault(joint, set())
                seen.add(direction)
                if seen == {"flex", "extend"}:
                    calibrated.append(joint)
                    ctx.log(f"joint calibrated: {joint} (ratio 0.0500)")
                    record("joint_calibrated", joint=joint, ratio=0.05)
                    if joint in encoder_backed:
                        lower, upper = config.joint_roms_dict[joint]
                        flex = _sim_count(joint)
                        span = round((float(upper) - float(lower))
                                     / _SIM_LSB_DEG)
                        extend = (flex - span) % _SIM_COUNTS_PER_REV
                        record("encoder_anchor_recorded", joint=joint,
                               anchor_count=flex,
                               anchor_angle_deg=float(upper))
                        record("measured_rom_recorded", joint=joint,
                               rom=[float(lower), float(upper)],
                               deviation_deg=0.0,
                               flex_count=flex, extend_count=extend)
                        ctx.log(f"measured ROM for {joint}: "
                                f"[{lower:.1f}, {upper:.1f}]° (Δ +0.0° vs "
                                f"config) · magnets flex@{flex} "
                                f"extend@{extend}")
            ctx.set_progress((index + 1) / max(total, 1))
        ctx.log("calibration complete")
        record("calibration_done")
    finally:
        calibration_log.append_run(config.calibration_path, {
            "started_at": started_at,
            "finished_at": _now_iso(),
            "joints": joints,
            "force_wrist": force_wrist,
            "anchor_pass": bool(encoder_backed),
            "completed": len(calibrated) > 0 and events[-1].get("event")
            == "calibration_done",
            "error": None,
            "simulated": True,
            "events": events,
        })
    return {
        "steps_done": total,
        "joints_calibrated": calibrated,
        "calibrated": True,
    }


def simulate_tension(ctx: OpContext, move_motors: bool, step_s: float,
                     detail_prefix: str = "") -> None:
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
    ctx.wait_input(RELEASE_PROMPT, ["Release"])
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
            return simulate_calibration(
                ctx, supervisor.config, self.params["joints"],
                self.params["step_duration_s"],
                force_wrist=self.params["force_wrist"])
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
                             self.params["step_duration_s"])
            return {"released": True}
        finally:
            supervisor.exit_maintenance()
