"""Fingertip numbering as a maintenance operation.

A tactile fingertip's module number decides which finger its data appears as,
and fresh fingertips all share one number. With only one finger's fingertip
plugged in, this op asks the connector board to renumber it for that finger,
has the operator power-cycle the hand, and checks the result. It drives
``orca_core.maintenance.fingertip_numbering`` through the hand_ops seam.

Modes: ``detect`` (read-only scan) and ``number`` (scan, confirm, write,
power-cycle, verify). Scanning and confirming run over the live session's
sensor link, so the hand stays connected; only the write and the power cycle
hold the supervisor MAINTENANCE lease, so nothing else uses the sensor port. The scan result is published as the snapshot ``extra``:
``{"finger", "target_module", "expected_part", "result", "found_modules",
"found_finger", "fits", "identity", "part", "verified"}``; ``fits`` lists the
``[module, finger]`` pairs whose fingertip model matches the one found.
"""

from __future__ import annotations

from orca_ui.hand.operations import hand_ops
from orca_ui.hand.operations.base import OpContext, Operation

FINGERS = ("thumb", "index", "middle", "ring", "pinky")
CONFIRM = "Set"
CANCEL = "Cancel"
POWER_CYCLED = "Power-cycled"
REOPEN_RETRY_S = 30.0


def finger_modules(service) -> dict[str, int]:
    """Module number each finger reads its fingertip from, per the hand config."""
    mapping = getattr(service.supervisor.config, "finger_to_sensor_id", None) or {}
    numbering = hand_ops.fingertip_numbering()
    return {f: int(mapping.get(f, numbering.default_module(f))) for f in FINGERS}


def validate_fingertip_params(service, params: dict) -> dict:
    from orca_ui.hand.service import ServiceError

    mode = params.get("mode", "detect")
    if mode not in ("detect", "number"):
        raise ServiceError(f"unknown mode {mode!r} (detect | number)")
    finger = params.get("finger")
    if finger not in FINGERS and (mode == "number" or finger is not None):
        raise ServiceError(f"finger must be one of {', '.join(FINGERS)}")
    target = finger_modules(service)[finger] if finger else None
    return {"finger": finger, "mode": mode, "target_module": target}


class NumberFingertipOperation(Operation):
    kind = "number_fingertip"

    @classmethod
    def validate(cls, service, params: dict) -> dict:
        return validate_fingertip_params(service, params)

    def run(self, ctx: OpContext) -> dict:
        numbering = hand_ops.fingertip_numbering()
        finger = self.params["finger"]
        target = self.params["target_module"]
        mock = bool(getattr(ctx.settings, "mock", False))
        modules = finger_modules(ctx.service)
        extra = {
            "finger": finger,
            "target_module": target,
            "expected_part": numbering.FINGER_SENSOR_PART.get(finger) if finger else None,
            "result": None,
            "found_modules": [],
            "found_finger": None,
            "fits": [],
            "identity": "",
            "part": None,
            "verified": None,
        }
        # Scan and confirm without taking the hand offline; only the write and
        # the power cycle hold the maintenance lease.
        client, link = self._connected_link(ctx, mock)
        scan = None
        try:
            if client is not None:
                scan = self._scan(ctx, numbering, client, extra, modules)
                if self.params["mode"] == "detect" or not self._confirm(ctx, scan, extra):
                    return dict(extra)
        finally:
            if link is not None:
                hand_ops.close_tactile_link(client, link)

        supervisor = ctx.service.supervisor
        ctx.set_phase("acquiring", detail="taking the sensor port into maintenance")
        lease = supervisor.enter_maintenance(self.kind)
        client = link = None
        try:
            client, link = hand_ops.open_tactile_link(lease.presence, mock=mock)
            if scan is None:
                scan = self._scan(ctx, numbering, client, extra, modules)
                if self.params["mode"] == "detect" or not self._confirm(ctx, scan, extra):
                    return dict(extra)

            ctx.set_phase("numbering", detail=f"module {scan.single_module} → {target}")
            done = numbering.set_fingertip_module(
                client, target, expected_current=scan.single_module)
            if done.acknowledged:
                ctx.log(f"fingertip acknowledged module {done.new_module}; "
                        "it applies after a power cycle")
            else:
                ctx.log("the fingertip sent no confirmation; the check after the "
                        f"power cycle shows whether module {done.new_module} took")
            hand_ops.close_tactile_link(client, link)
            client = link = None

            ctx.set_phase("power_cycle")
            ctx.wait_input(
                "Power-cycle the hand, then continue.", [POWER_CYCLED])
            if mock:
                hand_ops.simulate_power_cycle()

            ctx.set_phase("verifying", detail="looking for the fingertip at its new number")
            client, link = hand_ops.open_tactile_link(
                None, mock=mock, retry_s=REOPEN_RETRY_S, stop_event=ctx.stop_event)
            scan = self._scan(ctx, numbering, client, extra, modules)
            extra["verified"] = scan.single_module == target
            ctx.set_extra(extra)
            if not extra["verified"]:
                raise RuntimeError(
                    f"after the power cycle the fingertip answers as {list(scan.modules) or 'nothing'}, "
                    f"not module {target}")
            ctx.log(f"{finger} fingertip verified at module {target}")
            return dict(extra)
        finally:
            hand_ops.close_tactile_link(client, link)
            supervisor.exit_maintenance()

    @staticmethod
    def _connected_link(ctx: OpContext, mock: bool):
        """(client, link) that leaves the hand connected: the simulated board in
        mock mode, else the live session's sensor link (link None, not ours to
        close); (None, None) when the session has no sensor link."""
        if mock:
            return hand_ops.open_tactile_link(None, mock=True)
        session = ctx.service.session
        return (session.tactile_client if session else None), None

    def _confirm(self, ctx: OpContext, scan, extra: dict) -> bool:
        """Ask before writing; False when there is nothing to write or the
        operator cancels. A scan that found no single fingertip refuses here."""
        finger, target = self.params["finger"], self.params["target_module"]
        if scan.single_module is None:
            ctx.log(f"not written: {scan.result}")
            return False
        if scan.single_module == target:
            ctx.log(f"the fingertip is already module {target} — nothing to do")
            extra["verified"] = True
            ctx.set_extra(dict(extra))
            return False
        prompt = f"Renumber the fingertip from module {scan.single_module} to module {target} ({finger})?"
        if extra["part"] and extra["expected_part"] and extra["part"] != extra["expected_part"]:
            prompt += f" It is a {extra['part']}; the {finger} takes a {extra['expected_part']}."
        if ctx.wait_input(prompt, [CONFIRM, CANCEL]) != CONFIRM:
            ctx.log("cancelled — the fingertip was not changed")
            return False
        return True

    @staticmethod
    def _scan(ctx: OpContext, numbering, client, extra: dict, modules: dict):
        ctx.set_phase("detecting", detail="asking which fingertip answers")
        scan = numbering.scan_fingertips(client)
        parts = numbering.FINGER_SENSOR_PART
        extra.update(
            result=scan.result,
            found_modules=list(scan.modules),
            found_finger=next((f for f, m in modules.items() if m == scan.single_module), None),
            fits=sorted([m, f] for f, m in modules.items() if scan.part and parts.get(f) == scan.part),
            identity=scan.identity,
            part=scan.part,
        )
        ctx.set_extra(dict(extra))
        found = ", ".join(str(m) for m in scan.modules) or "none"
        ctx.log(f"scan: {scan.result}, module(s) {found}"
                + (f", {scan.identity!r}" if scan.identity else ""))
        return scan
