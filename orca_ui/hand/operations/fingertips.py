"""Fingertip numbering as a maintenance operation.

A tactile fingertip's module number decides which finger its data appears as,
and fresh fingertips all share one number. This op asks the connector board
to renumber one fingertip, has the operator power-cycle the hand, and checks
the result. The others may stay connected as long as no two share a number;
the target number must be free, and module 5 (the spare) holds a fingertip
while others are swapped. It drives ``orca_core.maintenance.fingertip_numbering``
through the hand_ops seam.

Modes: ``detect`` (read-only scan) and ``number`` (scan, confirm, write,
power-cycle, verify). Scanning and confirming run over the live session's
sensor link, so the hand stays connected; only the write and the power cycle
hold the supervisor MAINTENANCE lease, so nothing else uses the sensor port.
The scan result is published as the snapshot ``extra``:
``{"finger", "target_module", "current_module", "result", "found",
"garbled_modules", "targeted", "verified"}``. ``found`` lists each answering
fingertip as ``{"module", "finger", "part", "fits"}``, ``fits`` being the
modules whose finger takes that fingertip model.
"""

from __future__ import annotations

from orca_ui.hand.operations import hand_ops
from orca_ui.hand.operations.base import OpContext, Operation

FINGERS = ("thumb", "index", "middle", "ring", "pinky")
SPARE = "spare"
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
    from orca_ui.hand.models import describe
    from orca_ui.hand.service import ServiceError

    if not describe(service.supervisor.config.config_path)[1]:
        raise ServiceError("this hand model has no tactile fingertips", status_code=409)
    numbering = hand_ops.fingertip_numbering()
    mode = params.get("mode", "detect")
    if mode not in ("detect", "number"):
        raise ServiceError(f"unknown mode {mode!r} (detect | number)")
    finger = params.get("finger")
    if finger not in (*FINGERS, SPARE) and (mode == "number" or finger is not None):
        raise ServiceError(f"finger must be one of {', '.join((*FINGERS, SPARE))}")
    current = params.get("current_module")
    if current is not None and (not isinstance(current, int) or not 0 <= current <= numbering.NUMBERING_MAX_MODULE):
        raise ServiceError(f"current_module must be 0..{numbering.NUMBERING_MAX_MODULE}")
    if finger == SPARE:
        target = numbering.NUMBERING_SPARE_MODULE
    else:
        target = finger_modules(service)[finger] if finger else None
    return {"finger": finger, "mode": mode, "target_module": target, "current_module": current}


class NumberFingertipOperation(Operation):
    kind = "number_fingertip"

    @classmethod
    def validate(cls, service, params: dict) -> dict:
        return validate_fingertip_params(service, params)

    def run(self, ctx: OpContext) -> dict:
        numbering = hand_ops.fingertip_numbering()
        target = self.params["target_module"]
        mock = bool(getattr(ctx.settings, "mock", False))
        names = {m: f for f, m in finger_modules(ctx.service).items()}
        names.setdefault(numbering.NUMBERING_SPARE_MODULE, SPARE)
        extra = {
            "finger": self.params["finger"],
            "target_module": target,
            "current_module": self.params["current_module"],
            "result": None,
            "found": [],
            "garbled_modules": [],
            "targeted": False,
            "verified": None,
        }
        # Scan and confirm over the live link when there is one, so the hand
        # stays connected; the write and the power cycle hold the lease.
        supervisor = ctx.service.supervisor
        probe = None if mock else (lambda: getattr(supervisor._probe_hardware(), "sensing", None))
        client, link = self._connected_link(ctx, mock)
        lease = None
        try:
            if client is None:
                lease = self._enter(ctx, supervisor)
                client, link = hand_ops.open_tactile_link(
                    lease.presence, mock=mock, stop_event=ctx.stop_event, probe=probe)
            scan = self._scan(ctx, numbering, client, extra, names)
            if self.params["mode"] == "detect":
                return dict(extra)
            current = self._confirm(ctx, scan, extra, names)
            if current is None:
                return dict(extra)
            if lease is None:
                if link is not None:
                    hand_ops.close_tactile_link(client, link)
                client = link = None
                lease = self._enter(ctx, supervisor)
                client, link = hand_ops.open_tactile_link(
                    lease.presence, mock=mock, stop_event=ctx.stop_event, probe=probe)

            ctx.set_phase("numbering", detail=f"module {current} → {target}")
            done = numbering.set_fingertip_module(client, target, current=current)
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
                None, mock=mock, retry_s=REOPEN_RETRY_S, stop_event=ctx.stop_event, probe=probe)
            scan = self._scan(ctx, numbering, client, extra, names)
            extra["verified"] = target in scan.modules and current not in scan.modules
            ctx.set_extra(extra)
            if not extra["verified"]:
                raise RuntimeError(
                    f"after the power cycle the fingertips answer as {list(scan.modules) or 'nothing'}, "
                    f"so module {current} did not become {target}")
            ctx.log(f"verified: the fingertip that was module {current} is now module {target}")
            return dict(extra)
        finally:
            if link is not None:
                hand_ops.close_tactile_link(client, link)
            if lease is not None:
                supervisor.exit_maintenance()

    def _enter(self, ctx: OpContext, supervisor):
        ctx.set_phase("acquiring", detail="taking the sensor port into maintenance")
        return supervisor.enter_maintenance(self.kind)

    @staticmethod
    def _connected_link(ctx: OpContext, mock: bool):
        """(client, link) that leaves the hand connected: the simulated board in
        mock mode, else the live session's sensor link (link None, not ours to
        close); (None, None) when the session has no sensor link."""
        if mock:
            return hand_ops.open_tactile_link(None, mock=True)
        session = ctx.service.session
        return (session.tactile_client if session else None), None

    def _confirm(self, ctx: OpContext, scan, extra: dict, names: dict) -> int | None:
        """Ask before writing; the module to renumber, or None when there is
        nothing to write or the operator cancels. Raises on a request the
        scan contradicts."""
        target = self.params["target_module"]
        current = self.params["current_module"]
        found = scan.modules
        if scan.garbled or not found:
            ctx.log(f"not written: {scan.result}")
            return None
        if current is None:
            if len(found) > 1:
                raise RuntimeError("several fingertips are connected; pick the one to renumber")
            current = found[0]
        if current not in found:
            raise RuntimeError(f"no fingertip answers at module {current}")
        if current == target:
            ctx.log(f"the fingertip is already module {target} — nothing to do")
            extra["verified"] = True
            ctx.set_extra(dict(extra))
            return None
        if target in found:
            raise RuntimeError(f"module {target} is taken; move that fingertip to the spare first")
        if len(found) > 1 and not extra["targeted"]:
            raise RuntimeError("this connector-board firmware renumbers only a lone fingertip; "
                               "update it, or unplug the others")
        prompt = (f"Renumber module {current} ({names.get(current, '?')}) "
                  f"to module {target} ({names.get(target, '?')})?")
        tip = next(t for t in extra["found"] if t["module"] == current)
        if tip["part"] and target in names and names[target] != SPARE and target not in tip["fits"]:
            prompt += f" It is a {tip['part']}, which the {names[target]} doesn't take."
        if ctx.wait_input(prompt, [CONFIRM, CANCEL]) != CONFIRM:
            ctx.log("cancelled — the fingertip was not changed")
            return None
        extra["current_module"] = current
        return current

    @staticmethod
    def _scan(ctx: OpContext, numbering, client, extra: dict, names: dict):
        ctx.set_phase("detecting", detail="asking which fingertips answer")
        caps = numbering.read_extension_caps(client)
        scan = numbering.scan_fingertips(client)
        parts = {m: numbering.sensor_part(scan.identity) for m in scan.modules[:1] if scan.identity}
        if len(scan.modules) > 1:
            try:
                identities = numbering.read_slot_identities(client)
            except numbering.FingertipNumberingUnsupported:
                identities = {}
            parts = {m: numbering.sensor_part(identities.get(names.get(m), "")) for m in scan.modules}
        takes = numbering.FINGER_SENSOR_PART
        extra.update(
            result=scan.result,
            found=[{
                "module": m,
                "finger": names.get(m),
                "part": parts.get(m),
                "fits": sorted(n for n, f in names.items() if parts.get(m) and takes.get(f) == parts[m]),
            } for m in scan.modules],
            garbled_modules=list(scan.garbled_modules),
            targeted=bool(caps & numbering.EXT_CAP_NUMBERING_SET_AT),
        )
        ctx.set_extra(dict(extra))
        found = ", ".join(str(m) for m in scan.modules) or "none"
        ctx.log(f"scan: {scan.result}, module(s) {found}"
                + (f", {scan.identity!r}" if scan.identity else ""))
        return scan
