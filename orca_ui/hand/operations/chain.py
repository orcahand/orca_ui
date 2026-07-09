"""Motor-chain configuration as a maintenance operation.

Drives ``orca_core.maintenance.motor_chain`` (through the hand_ops seam):
fresh motors ship at factory defaults, get plugged onto the chain one at a
time, and are re-programmed to their target ID descending from the highest
(wrist last, at ID 1). Runs under the supervisor MAINTENANCE lease — no hand
session exists during assembly, and the bus must be exclusively ours.

Modes:
- ``configure``: the guided per-motor flow. orca_core polls the bus for a
  factory-default motor, programs it, verifies the chain, and reports every
  step through its progress callback, which this op maps onto the snapshot.
- ``reset``: DESTRUCTIVE — reverts every configured motor found back to
  factory defaults (looping passes until stopped, so motors can be connected
  one at a time). Guarded by an explicit ``confirm`` param; the UI
  double-confirms on top, because a reset means redoing the whole ID'ing
  process.

The per-motor grid for the Motors-tab visualization is published through the
snapshot's ``extra`` field: ``{"mode", "motor_type", "target_baud", "chain":
[{"id", "model", "role", "state"}], "resets": [...]}`` with state one of
``pending | expected | configured | invalid | reset``.
"""

from __future__ import annotations

from orca_ui.hand.operations import hand_ops
from orca_ui.hand.operations.base import OpContext, Operation
from orca_ui.hand.operations.events import OperationStopped

RESET_PASS_PERIOD_S = 1.0

# The Feetech assembly flow needs the operator prompt for its USB power-cycle
# dance (wired below via ctx.wait_input), but orca_core's
# FeetechClient.connect() still retries torque-enable forever on an absent
# motor — that would wedge the operation thread with the maintenance lease
# held. Until that retry is bounded, Feetech chains stay on the CLI script.
_FEETECH_UNSUPPORTED = (
    "feetech chain configuration isn't supported from the UI yet — use "
    "orca_core/scripts/configure_motor_chain.py (it walks the required USB "
    "power-cycle procedure)")


def validate_chain_params(service, params: dict) -> dict:
    from orca_ui.hand.service import ServiceError

    mode = params.get("mode", "configure")
    if mode not in ("configure", "reset"):
        raise ServiceError(f"unknown mode {mode!r} (configure | reset)")
    if mode == "reset" and params.get("confirm") is not True:
        # Deliberate friction: a reset reverts motors to factory ID 1 and
        # forces the whole re-ID process. Nothing may trigger it implicitly.
        raise ServiceError(
            "motor reset requires explicit confirmation "
            "(params.confirm = true)", status_code=400)
    config = service.supervisor.config
    if not config.motor_ids:
        raise ServiceError("this hand config declares no motor_ids",
                           status_code=409)
    # None = unpinned: the real op probes the family at factory defaults on
    # the bus (orca_core's detect_motor_type).
    motor_type = params.get("motor_type") or config.motor_type
    if motor_type is not None and motor_type not in hand_ops.known_motor_types():
        raise ServiceError(f"unknown motor_type {motor_type!r}")
    if motor_type == "feetech":
        raise ServiceError(_FEETECH_UNSUPPORTED, status_code=409)
    # No session requirement: chain configuration happens at assembly time,
    # when the supervisor typically sits in DETECTING with no connectable hand.
    return {"mode": mode, "motor_type": motor_type}


class _ChainGrid:
    """UI-side per-motor state, published as the snapshot ``extra`` grid."""

    def __init__(self, plan):
        self._plan = plan
        self.order: list[int] = list(plan.all_target_ids)
        self.states: dict[int, str] = {m: "pending" for m in self.order}
        self.resets: list[int] = []

    def mark(self, motor_id: int, state: str) -> None:
        if motor_id in self.states:
            self.states[motor_id] = state

    def extra(self, mode: str) -> dict:
        plan = self._plan
        return {
            "mode": mode,
            "motor_type": plan.motor_type,
            "target_baud": plan.target_baud,
            "chain": [
                {
                    "id": m,
                    "model": plan.model_for(m),
                    "role": "wrist" if m == plan.wrist_id else "finger",
                    "state": self.states[m],
                }
                for m in self.order
            ],
            "resets": list(self.resets),
        }


def _progress_mapper(ctx: OpContext, grid: _ChainGrid, mode: str):
    """orca_core motor_chain events -> snapshot phase/detail/progress/extra."""
    total = len(grid.order)

    def on_event(event: dict) -> None:
        kind = event.get("event")
        if kind == "prescan_done":
            for motor_id in event.get("already_configured", []):
                grid.mark(motor_id, "configured")
            if event.get("already_configured"):
                ctx.log("already configured: "
                        f"{sorted(event['already_configured'], reverse=True)}")
            ctx.set_extra(grid.extra(mode))
        elif kind == "step_started":
            grid.mark(event["target_id"], "expected")
            ctx.set_phase(
                "configuring",
                detail=f"step {event['step']}/{event['total']}: "
                       f"{event['message']} — it becomes ID "
                       f"{event['target_id']}",
                progress=(event["step"] - 1) / max(event["total"], 1))
            ctx.set_extra(grid.extra(mode))
            ctx.log(f"waiting for a factory-default {event['expected_model']} "
                    f"(→ ID {event['target_id']})")
        elif kind == "motor_configured":
            grid.mark(event["target_id"], "configured")
            ctx.set_extra(grid.extra(mode))
            ctx.set_progress(len(event["configured_ids"]) / max(total, 1))
            ctx.log(f"configured ID {event['target_id']} @ "
                    f"{event['baudrate']:,} bps")
        elif kind == "chain_verified":
            ctx.log(f"chain verified: {sorted(event['configured_ids'])}")
        elif kind == "chain_done":
            ctx.set_progress(
                1.0, detail="all motors configured — ready for operation")
        elif kind == "waiting_for_port":
            ctx.set_detail("unplug the USB cable" if event.get("present") is False
                           else "plug the USB cable back in")
        elif kind == "motor_updated":
            motor = event["motor"]
            grid.mark(motor["id"], "reset")
            grid.resets.append(motor["id"])
            ctx.set_extra(grid.extra(mode))
            ctx.log(f"reset ID {motor['id']} ({motor['model_name']}) → "
                    "factory defaults")
        elif kind == "motor_update_failed":
            ctx.log(f"failed on ID {event['motor']['id']}: {event['error']}")
        elif kind in ("probing_motor_type", "motor_type_detected"):
            ctx.log(f"{kind.replace('_', ' ')}: "
                    f"{event.get('motor_type', '?')}")

    return on_event


class ConfigureChainOperation(Operation):
    kind = "configure_chain"

    @classmethod
    def validate(cls, service, params: dict) -> dict:
        return validate_chain_params(service, params)

    def run(self, ctx: OpContext) -> dict:
        supervisor = ctx.service.supervisor
        mode = self.params["mode"]
        ctx.set_phase("acquiring", detail="taking the bus into maintenance")
        lease = supervisor.enter_maintenance(self.kind)
        try:
            ctx.check_stop()
            port = hand_ops.resolve_motor_port(supervisor.config,
                                               lease.presence)
            if not port:
                raise RuntimeError(
                    "no motor bus port found — check the USB connection "
                    "(the OH board must be powered and plugged in)")
            motor_type = self.params["motor_type"]
            if motor_type is None:
                ctx.set_phase("detecting",
                              detail="probing the motor family at factory "
                                     "defaults")
                motor_type = hand_ops.detect_motor_type(port)
                if motor_type is None:
                    raise RuntimeError(
                        "could not detect the motor family (nothing at "
                        "factory defaults on the bus) — set motor_type in "
                        "the hand config.yaml or pass it explicitly")
                ctx.log(f"detected {motor_type} motors")
                if motor_type == "feetech":
                    raise RuntimeError(_FEETECH_UNSUPPORTED)

            plan = hand_ops.build_chain_plan(supervisor.config, port,
                                             motor_type)
            grid = _ChainGrid(plan)
            ctx.set_extra(grid.extra(mode))
            ctx.log(f"motor bus on {port} ({motor_type}, target "
                    f"{plan.target_baud:,} bps)")

            on_event = _progress_mapper(ctx, grid, mode)
            # Blocking operator prompt (Feetech power-cycle dance); answered
            # from the transport bar / Motors tab like any awaiting_input.
            prompt = (lambda p: ctx.wait_input(
                p.get("message", "connect the motor"), ["Connected"]))
            chain_error, chain_aborted = hand_ops.chain_error_types()

            try:
                if mode == "reset":
                    return self._run_reset(ctx, plan, grid, on_event, prompt)
                configured = hand_ops.run_chain_configure(
                    plan, progress_callback=on_event, prompt_callback=prompt,
                    should_stop=ctx.stop_event.is_set)
                return {"configured": configured}
            except chain_aborted as e:
                for motor_id in e.invalid_ids:
                    grid.mark(motor_id, "invalid")
                ctx.set_extra(grid.extra(mode))
                raise RuntimeError(str(e)) from e
            except chain_error as e:
                # the library's should_stop cancellation surfaces as a
                # MotorChainError — map it back to a clean stop
                ctx.check_stop()
                raise RuntimeError(str(e)) from e
        finally:
            supervisor.exit_maintenance()

    def _run_reset(self, ctx: OpContext, plan, grid: _ChainGrid,
                   on_event, prompt) -> dict:
        """Looping reset passes until stopped (hot-swap workflow: connect a
        motor, watch it revert, connect the next)."""
        chain_error, _ = hand_ops.chain_error_types()
        ctx.set_phase(
            "resetting",
            detail=f"reverting motors to factory defaults (ID "
                   f"{plan.default_id}, {plan.default_baud:,} bps) — connect "
                   "motors, stop when done")
        while True:
            ctx.check_stop()
            try:
                hand_ops.reset_motors_once(
                    plan, progress_callback=on_event, prompt_callback=prompt,
                    should_stop=ctx.stop_event.is_set)
            except OperationStopped:
                raise
            except chain_error:
                ctx.check_stop()
                raise
            except Exception as e:
                # Hot-swapping makes transient bus errors normal here — log
                # and retry rather than killing the op and bouncing the lease.
                ctx.log(f"bus error while resetting — retrying: {e}")
            if grid.resets:
                ctx.set_detail(f"{len(grid.resets)} motor(s) reset — connect "
                               "the next one, or stop when done")
            ctx.sleep(RESET_PASS_PERIOD_S)


class SimulatedConfigureChainOperation(Operation):
    """Mock-mode stand-in: same states, extra grid, and pacing — the Motors
    tab visualization can be exercised without a single motor. Takes the
    REAL maintenance lease like every simulated maintenance op."""

    kind = "configure_chain"

    DEFAULT_STEP_S = 1.2

    @classmethod
    def validate(cls, service, params: dict) -> dict:
        clean = validate_chain_params(service, params)
        step = params.get("step_duration_s", cls.DEFAULT_STEP_S)
        clean["step_duration_s"] = min(max(float(step), 0.02), 5.0)
        return clean

    def run(self, ctx: OpContext) -> dict:
        supervisor = ctx.service.supervisor
        # No bus to probe in mock mode: an unpinned family simulates dynamixel.
        motor_type = self.params["motor_type"] or "dynamixel"
        plan = hand_ops.build_chain_plan(supervisor.config, "/dev/orca-mock",
                                         motor_type)
        grid = _ChainGrid(plan)
        step_s = self.params["step_duration_s"]
        mode = self.params["mode"]
        ctx.set_extra(grid.extra(mode))
        ctx.set_phase("acquiring", detail="taking the bus into maintenance")
        supervisor.enter_maintenance(self.kind)
        try:
            if mode == "reset":
                return self._run_reset(ctx, plan, grid, step_s)
            return self._run_configure(ctx, plan, grid, step_s)
        finally:
            supervisor.exit_maintenance()

    def _run_configure(self, ctx: OpContext, plan, grid: _ChainGrid,
                       step_s: float) -> dict:
        configured: list[int] = []
        total = len(grid.order)
        for step, target_id in enumerate(grid.order, 1):
            grid.mark(target_id, "expected")
            model = plan.model_for(target_id)
            location = ("the board" if target_id == max(grid.order)
                        else f"motor ID {target_id + 1}")
            ctx.set_phase(
                "configuring",
                detail=f"step {step}/{total}: connect a factory-fresh "
                       f"{model} to {location} — it becomes ID {target_id}",
                progress=len(configured) / total)
            ctx.set_extra(grid.extra("configure"))
            ctx.sleep(step_s)
            configured.append(target_id)
            grid.mark(target_id, "configured")
            ctx.set_extra(grid.extra("configure"))
            ctx.log(f"configured ID {target_id} ({model}) [simulated]")
        ctx.set_progress(1.0,
                         detail="all motors configured — ready for operation")
        return {"configured": configured, "simulated": True}

    def _run_reset(self, ctx: OpContext, plan, grid: _ChainGrid,
                   step_s: float) -> dict:
        ctx.set_phase("resetting",
                      detail="reverting motors to factory defaults "
                             "[simulated] — stop when done")
        for motor_id in grid.order:
            ctx.sleep(step_s)
            grid.mark(motor_id, "reset")
            grid.resets.append(motor_id)
            ctx.set_extra(grid.extra("reset"))
            ctx.log(f"reset ID {motor_id} → factory defaults [simulated]")
        # Real reset loops until stopped; the simulation parks the same way
        # so the stop flow is exercised too.
        while True:
            ctx.sleep(1.0)
