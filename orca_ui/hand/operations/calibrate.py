"""Calibration as a maintenance operation.

The supervisor lends the hardware (MAINTENANCE lease), the op builds its own
motor-only hand + UI-owned encoder client — the scripts/calibrate.py pattern,
which sidesteps orca_core's refusal to calibrate while the feedback loop runs.

``run_calibrate`` is deliberately lease-free so the wizard (M6) can compose
tension + calibrate rounds under one lease.
"""

from __future__ import annotations

from pathlib import Path

import math
import threading

from orca_ui.hand.operations import hand_ops
from orca_ui.hand.operations.base import OpContext, Operation


MIN_CALIBRATION_CURRENT_MA = 20.0
CALIBRATION_GROUPS = ("abd", "mcp", "pip")
RECORD = "Record"
SKIP = "Skip"
BACK = "Back"
LIVE_PERIOD_S = 0.2


def calibration_current_info(service) -> dict | None:
    """The connected hand's calibration current, its per-group currents (v2.1
    hands whose model sets them, else None), and the ceiling its motors allow, in mA."""
    session = service.session
    if session is None:
        return None
    config = session.hand.config
    current = getattr(config, "calibration_current", None)
    client = getattr(session.hand, "motor_client", None)
    ceiling = (
        getattr(type(client), "max_current_ma", None) if client is not None else None
    )
    if not isinstance(current, (int, float)):
        return None
    groups = getattr(config, "calibration_group_currents", None) or {}
    return {
        "default": float(current),
        "groups": {g: float(groups.get(g, current)) for g in CALIBRATION_GROUPS}
        if groups
        else None,
        "max": float(ceiling) if ceiling else None,
    }


def _checked_current(value, info: dict, name: str) -> float:
    from orca_ui.hand.service import ServiceError

    try:
        current = float(value)
    except (TypeError, ValueError):
        raise ServiceError(f"{name} must be a number of mA", status_code=422)
    ceiling = info.get("max")
    if current < MIN_CALIBRATION_CURRENT_MA or (ceiling and current > ceiling):
        raise ServiceError(
            f"{name} must be between {MIN_CALIBRATION_CURRENT_MA:.0f} and {ceiling:.0f} mA"
            if ceiling
            else f"{name} must be at least {MIN_CALIBRATION_CURRENT_MA:.0f} mA",
            status_code=422,
        )
    return current


def validate_calibrate_params(service, params: dict) -> dict:
    from orca_ui.hand.service import ServiceError

    config = service.supervisor.config
    joints = params.get("joints")
    if joints is not None:
        if (
            not isinstance(joints, list)
            or not joints
            or not all(isinstance(j, str) for j in joints)
        ):
            raise ServiceError(
                "joints must be a non-empty list of joint names, or null "
                "for a full calibration"
            )
        unknown = set(joints) - set(config.joint_ids)
        if unknown:
            raise ServiceError(f"unknown joints: {sorted(unknown)}")
        joints = list(dict.fromkeys(joints))
    session = service.session
    if session is None:
        raise ServiceError("hand not connected", status_code=503)
    if not session.caps.motors:
        raise ServiceError("no motor bus — calibration needs motors", status_code=409)
    # The newest slack test on this hand decides: a motor that turned half a
    # turn freely would unspool under the calibration drive.
    if not params.get("ignore_slack_test"):
        from orca_ui.hand import slack_tests

        block = slack_tests.calibration_block(config, service.supervisor.hand_id)
        if block:
            raise ServiceError(block, status_code=409)
    clean = {
        "joints": joints,
        "force_wrist": bool(params.get("force_wrist", False)),
        "manual": bool(params.get("manual", False)),
        "calibration_current": None,
        "calibration_currents": None,
    }
    info = calibration_current_info(service) or {}
    if params.get("calibration_current") is not None:
        clean["calibration_current"] = _checked_current(
            params["calibration_current"], info, "calibration_current"
        )
    groups = params.get("calibration_currents")
    if groups is not None:
        if not info.get("groups"):
            raise ServiceError(
                "this hand calibrates every joint at one current; "
                "set calibration_current instead",
                status_code=422,
            )
        if not isinstance(groups, dict) or not set(groups) <= set(CALIBRATION_GROUPS):
            raise ServiceError(
                f"calibration_currents must map {', '.join(CALIBRATION_GROUPS)} "
                "to a current in mA",
                status_code=422,
            )
        clean["calibration_currents"] = {
            g: _checked_current(v, info, f"calibration_currents.{g}")
            for g, v in groups.items()
        }
    return clean


def apply_calibration_current(
    hand, current: float | None, groups: dict | None, ctx: OpContext
) -> None:
    """Calibrate this run at ``current`` (a wrist that followed the fingers'
    current follows it) and/or at the per-group ``groups`` currents."""
    config = hand.config
    if current is not None:
        current = int(round(current))
        if config.wrist_calibration_current == config.calibration_current:
            object.__setattr__(config, "wrist_calibration_current", current)
        object.__setattr__(config, "calibration_current", current)
        ctx.log(f"calibrating at {current} mA")
    if groups:
        merged = {
            **config.calibration_group_currents,
            **{g: int(round(v)) for g, v in groups.items()},
        }
        object.__setattr__(
            config,
            "calibration_current_v21_dict",
            {**config.calibration_current_v21_dict, str(config.motor_type): merged},
        )
        ctx.log("calibrating at " + ", ".join(f"{g} {c} mA" for g, c in merged.items()))


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
    line = (
        f"{event['joint']}: travel {event['travel_deg']:.0f}° of "
        f"{event['expected_deg']:.0f}° — {note}"
    )
    if "current" in event and "attempt" in event:
        line += f" (attempt {event['attempt']}, {event['current']:.0f} mA)"
    return line


def manual_capture_steps(config, joints: list[str] | None) -> list[dict]:
    """The steps a manual run asks for, in order; one answer records a whole step.
    The wrist is always included; absent motors are trimmed by ManualCapture."""
    sequence = (
        getattr(config, "manual_calibration_sequence", None)
        or config.calibration_sequence
    )
    steps = [dict(step["joints"]) for step in sequence]
    if not any("wrist" in step for step in steps) and "wrist" in config.joint_ids:
        steps += [{"wrist": "flex"}, {"wrist": "extend"}]
    wanted = set(joints) if joints is not None else None
    steps = [
        {j: d for j, d in step.items() if wanted is None or j in wanted}
        for step in steps
    ]
    return [step for step in steps if step]


def manual_capture_plan(steps: list[dict]) -> list[dict]:
    return [{"joint": j, "direction": d} for step in steps for j, d in step.items()]


class ManualCapture:
    """Publishes the manual run (the hardstop asked for, the live motor positions,
    what was captured) and asks the operator to record or skip each step's hardstops."""

    def __init__(self, ctx: OpContext, plan: list[dict], motor_of, read_deg=None):
        self._ctx = ctx
        self._motor_of = motor_of
        self._read_deg = read_deg
        self._lock = threading.Lock()
        self.extra = {
            "manual": True,
            "plan": plan,
            "index": 0,
            "total": len(plan),
            "current": None,
            "position_deg": {},
            "start_deg": {},
            "captured": [],
        }

    def _publish(self) -> None:
        with self._lock:
            self._ctx.set_extra(
                {
                    **self.extra,
                    "captured": list(self.extra["captured"]),
                    "position_deg": dict(self.extra["position_deg"]),
                    "start_deg": dict(self.extra["start_deg"]),
                }
            )

    def on_event(self, event: dict) -> None:
        kind = event.get("event")
        if kind in ("wrist_skipped", "joints_skipped"):
            gone = {"wrist"} if kind == "wrist_skipped" else set(event["joints"])
            self.extra["plan"] = [
                c for c in self.extra["plan"] if c["joint"] not in gone
            ]
            self.extra["total"] = len(self.extra["plan"])
            self._publish()
        elif kind == "limit_recorded":
            self._captured(event["joint"], "recorded", event["limit"])
        elif kind == "manual_capture_skipped":
            self._captured(event["joint"], "skipped", None)
        elif kind == "manual_capture_back":
            # The previous step is asked again: forget what it captured.
            undone = {(j, d) for j, d in event["joints"].items()}
            self.extra["captured"] = [
                c
                for c in self.extra["captured"]
                if (c["joint"], c["direction"]) not in undone
            ]
            self._publish()

    def _captured(self, joint: str, outcome: str, limit) -> None:
        current = self.extra["current"] or {}
        self.extra["captured"].append(
            {
                "joint": joint,
                "direction": current.get("direction"),
                "outcome": outcome,
                "position_deg": None if limit is None else math.degrees(limit),
            }
        )
        self._publish()

    def prompt(self, prompt: dict) -> str:
        step = prompt.get("joints") or {prompt["joint"]: prompt["direction"]}
        joints, direction = list(step), prompt["direction"]
        motors = {j: abs(int(m)) for j, m in (prompt.get("motors") or {}).items()} or {
            j: abs(int(self._motor_of(j))) for j in joints
        }
        index = next(
            (
                i
                for i, c in enumerate(self.extra["plan"])
                if c["joint"] == joints[0] and c["direction"] == direction
            ),
            self.extra["index"],
        )
        self.extra.update(
            index=index,
            prompt_seq=self.extra.get("prompt_seq", 0) + 1,
            position_deg={},
            start_deg={},
            current={
                "joint": joints[0],
                "joints": joints,
                "motor": prompt["motor"],
                "motors": motors,
                "direction": direction,
            },
        )
        self._ctx.set_phase(
            "capturing",
            progress=index / max(self.extra["total"], 1),
            detail=f"{', '.join(joints)} {direction}",
        )
        self._publish()
        what = ", ".join(j.replace("_", " ") for j in joints)
        done = threading.Event()
        live = threading.Thread(target=self._follow, args=(motors, done), daemon=True)
        live.start()
        options = [RECORD, SKIP] + ([BACK] if prompt.get("can_back") else [])
        try:
            answer = self._ctx.wait_input(
                f"Hold {what} on the {direction} end stop, then record", options
            )
        finally:
            done.set()
            live.join()
        return {RECORD: "record", BACK: "back"}.get(answer, "skip")

    def _follow(self, motors: dict[str, int], done: threading.Event) -> None:
        """Streams the asked motors' positions while the operator moves the joints."""
        if self._read_deg is None:
            return
        while not done.is_set():
            try:
                degs = self._read_deg(list(motors.values()))
            except Exception:
                degs = None
            if degs is not None and not done.is_set():
                for joint, motor in motors.items():
                    self.extra["start_deg"].setdefault(joint, degs[motor])
                    self.extra["position_deg"][joint] = degs[motor]
                self._publish()
            done.wait(LIVE_PERIOD_S)


def _motor_reader(hand):
    from orca_core.maintenance.motor_reads import read_motor_pos_checked

    def read_deg(motors: list[int]) -> dict[int, float]:
        pos = read_motor_pos_checked(hand)
        idx = hand.config.motor_id_to_idx_dict
        return {m: math.degrees(float(pos[idx[m]])) for m in motors}

    return read_deg


def run_calibrate(
    hand,
    encoder_client,
    ctx: OpContext,
    joints: list[str] | None,
    force_wrist: bool,
    manual: bool = False,
) -> dict:
    """Blocking calibration with progress mapped onto the op snapshot."""
    progress = {
        "steps_done": 0,
        "total": 0,
        "joints_calibrated": [],
        "anchors_recorded": [],
        "anchors_dead": [],
        "travel_logged": False,
        "aborted": False,
    }

    plan = manual_capture_plan(manual_capture_steps(hand.config, joints))
    capture = (
        ManualCapture(
            ctx, plan, hand.config.joint_to_motor_map.get, _motor_reader(hand)
        )
        if manual
        else None
    )

    def on_event(event: dict) -> None:
        kind = event.get("event")
        if capture is not None:
            capture.on_event(event)
        if kind == "encoder_anchor_recorded":
            progress["anchors_recorded"].append(event["joint"])
            ctx.log(
                f"encoder anchor recorded: {event['joint']} "
                f"(count {event['anchor_count']} at "
                f"{event['anchor_angle_deg']:.1f}°)"
            )
        elif kind == "encoder_anchor_failed":
            reason = str(event.get("error", ""))
            # A slot that doesn't move with the sweep is dead or unwired —
            # a hardware fault, not a retryable sampling glitch.
            if "did not track the sweep" in reason:
                progress["anchors_dead"].append(event["joint"])
                ctx.log(
                    f"encoder DEAD on {event['joint']}: {reason}. Check "
                    "its wiring at the connector board; the joint stays "
                    "open-loop until the encoder reads."
                )
            else:
                ctx.log(
                    f"encoder anchor not captured for {event['joint']}: "
                    f"{reason} — it keeps its previous anchor"
                )
        elif kind == "wrist_skipped":
            ctx.log(
                "wrist already calibrated (motor limits and encoder "
                "anchor) — skipping its steps; force wrist to re-run"
            )
        elif kind == "calibration_started":
            progress["total"] = event["steps"]
            ctx.set_phase("calibrating", progress=0.0, detail=f"{event['steps']} steps")
            ctx.log(
                f"calibration started: {event['steps']} steps "
                f"({', '.join(event['joints'])})"
            )
        elif kind == "step_started":
            step_joints = ", ".join(f"{j} {d}" for j, d in event["joints"].items())
            ctx.set_detail(f"step {event['index'] + 1}/{event['total']}: {step_joints}")
            ctx.log(f"step {event['index'] + 1}/{event['total']}: {step_joints}")
        elif kind == "step_done":
            progress["steps_done"] += 1
            ctx.set_progress((event["index"] + 1) / max(event["total"], 1))
        elif kind == "joint_calibrated":
            progress["joints_calibrated"].append(event["joint"])
            ctx.log(f"joint calibrated: {event['joint']} (ratio {event['ratio']:.4f})")
        elif kind == "calibration_done":
            ctx.log("calibration complete")
            # What the numbers above mean, so the log reads on its own.
            ctx.log(
                "ratio: motor radians per joint degree — the motor travel between the two "
                "hardstops found, divided by the joint's range of motion"
            )
            if progress["travel_logged"]:
                ctx.log(
                    "travel: motor-shaft travel between the hardstops in degrees, against the "
                    "hand's joint_motor_travel baseline; mA: the current the joint was driven "
                    "onto its hardstops with"
                )
        elif kind == "calibration_aborted":
            progress["aborted"] = True
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
            ctx.log(
                f"{event['joint']}: turned {event['travel_deg']:.0f}° past its "
                f"{event['limit_deg']:.0f}° limit without meeting a stop — the belt is "
                f"poorly set (slipping); driving again at {100 * event['pwm_fraction']:.0f}% "
                f"output (attempt {event['attempt']})"
            )
        elif kind == "hardstop_not_found":
            ctx.log(
                f"{event['joint']}: no hardstop within {event['limit_deg']:.0f}° — given up, "
                "limit not recorded. The belt or tendon is slack or broken: tension it and "
                "calibrate again"
            )
        elif kind == "drive_step_timeout":
            ctx.log(
                f"{event['joint']}: never settled on a hardstop — given up, limit not recorded"
            )

    # calibrate() clears orca_core's stop event at entry: a stop that landed
    # while we were connecting would be swallowed. Check ours first.
    ctx.check_stop()
    hand_ops.calibrate(
        hand,
        joints=joints,
        force_wrist=force_wrist,
        joint_encoder_client=encoder_client,
        progress_callback=on_event,
        prompt_callback=capture.prompt if capture is not None else None,
    )
    ctx.check_stop()
    finger_joints = [j for j in hand.config.joint_ids if j != "wrist" and j in hand.config.joint_to_motor_map]
    partial = progress["aborted"] or joints is not None or \
        not set(finger_joints) <= set(progress["joints_calibrated"])
    _snapshot_run(ctx, hand.config, hand.calibration, manual,
                  joints=list(progress["joints_calibrated"]), partial=partial)
    return {
        "steps_done": progress["steps_done"],
        "joints_calibrated": progress["joints_calibrated"],
        "anchors_recorded": progress["anchors_recorded"],
        "anchors_dead": progress["anchors_dead"],
        "calibrated": bool(hand.calibrated),
    }


def _snapshot_run(ctx: OpContext, config, calibration, manual: bool,
                  joints: list[str] | None = None, partial: bool = False) -> None:
    """Keep this run's travel table: calibration.yaml alone is overwritten by the
    next run. A partial run (subset, abort) is kept but marked: the other joints'
    values are the previous run's."""
    from orca_ui.hand import baselines

    try:
        name = baselines.snapshot_calibration(
            config,
            calibration,
            source="manual" if manual else "auto",
            hand_key=ctx.service.supervisor.hand_id,
            joints=joints,
            partial=partial,
        )
        ctx.log(
            f"travel snapshot saved as {name} — promote it to a baseline from the Setup tab"
        )
    except Exception as e:
        ctx.log(f"travel snapshot not saved: {e}")
    # calibration.yaml is overwritten by whichever run comes next; the last
    # manual and the last automatic run are also kept each in its own file.
    try:
        import shutil

        source = Path(config.calibration_path)
        kept = source.with_name(f"calibration_{'manual' if manual else 'auto'}.yaml")
        shutil.copyfile(source, kept)
        ctx.log(f"calibration also kept as {kept.name}")
    except Exception as e:
        ctx.log(f"calibration copy not kept: {e}")


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
                supervisor.config,
                ctx.stop_event,
                motor_port=lease.presence.motor_port if lease.presence else None,
            )
            self._hand = hand
            apply_calibration_current(
                hand,
                self.params.get("calibration_current"),
                self.params.get("calibration_currents"),
                ctx,
            )
            try:
                encoder_client, encoder_link = hand_ops.open_encoder_client(
                    supervisor.config, lease.presence
                )
            except Exception as e:
                # Motor calibration still works without the anchor pass.
                ctx.log(f"encoder client unavailable — skipping anchor pass: {e}")
            if encoder_client is not None:
                ctx.log("encoder client attached for the anchor pass")
            return run_calibrate(
                hand,
                encoder_client,
                ctx,
                joints=self.params["joints"],
                force_wrist=self.params["force_wrist"],
                manual=self.params.get("manual", False),
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
