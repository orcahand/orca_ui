"""Re-programming servo IDs (and baud rates) on the bench bus.

Each change is ``{id, new_id}`` plus the rate the motor answers at now and
the rate it should answer at after (both default to the bench's 1 M baud),
so a factory motor at 57,600 is moved onto the bench's rate in the same
step. A change is written only when the motor answers at its old address
and nothing answers at the new one, and it counts only once the motor
answers at its new address — a write to an ID two motors share renames
both, and the collision then shows up as silence there.

Runs under the maintenance lease like the bus scan: the session is closed
and torque is off for the duration. Afterwards everything stored beside the
bench config follows the moved motors (their numbers, thermal pairs, finger
tendons) and the bench reconnects on the new IDs.
"""

from __future__ import annotations

from orca_ui.bench import is_bench_config, remap_bench_ids
from orca_ui.hand.operations import hand_ops
from orca_ui.hand.operations.base import OpContext, Operation
from orca_ui.hand.operations.scan import DEFAULT_BAUD, MAX_ID

# EEPROM writes take a moment before the motor answers at its new address.
SETTLE_S = 0.15
MAX_CHANGES = 64


def _validate(service, params: dict) -> dict:
    from orca_ui.hand.service import ServiceError

    config = service.supervisor.config
    if not is_bench_config(config):
        raise ServiceError("servo IDs are re-programmed from the bench only — a "
                           "hand's IDs belong to its chain configuration", status_code=409)
    family = config.motor_type or "dynamixel"
    rates = hand_ops.baud_rates(family)
    raw = params.get("changes")
    if not isinstance(raw, list) or not raw:
        raise ServiceError("changes must be a non-empty list")
    if len(raw) > MAX_CHANGES:
        raise ServiceError(f"at most {MAX_CHANGES} changes at a time")
    changes: list[dict] = []
    try:
        for entry in raw:
            change = {
                "id": int(entry["id"]),
                "new_id": int(entry["new_id"]),
                "baud_rate": int(entry.get("baud_rate") or DEFAULT_BAUD),
                "new_baud": int(entry.get("new_baud") or DEFAULT_BAUD),
            }
            changes.append(change)
    except (TypeError, ValueError, KeyError, AttributeError):
        raise ServiceError("each change needs integer id and new_id")
    for c in changes:
        if not 0 <= c["id"] <= MAX_ID or not 1 <= c["new_id"] <= MAX_ID:
            raise ServiceError(f"IDs are 0..{MAX_ID} now and 1..{MAX_ID} after")
        for rate in (c["baud_rate"], c["new_baud"]):
            if rate not in rates:
                raise ServiceError(f"{rate} is not a {family} baud rate ({rates})")
        if c["new_id"] == c["id"] and c["new_baud"] == c["baud_rate"]:
            raise ServiceError(f"ID {c['id']}: nothing to change")
    sources = {(c["id"], c["baud_rate"]) for c in changes}
    if len(sources) != len(changes):
        raise ServiceError("a motor is listed twice")
    targets = [c["new_id"] for c in changes]
    if len(set(targets)) != len(targets):
        raise ServiceError("two motors would get the same ID")
    moving = {c["id"] for c in changes}
    staying = {int(m) for m in config.motor_ids} - moving
    clash = sorted(set(targets) & (staying | {c["id"] for c in changes if c["new_id"] != c["id"]}))
    if clash:
        raise ServiceError(f"ID {clash[0]} is in use on the bench — pick IDs no motor has now")
    return {"changes": changes}


class ReprogramIdsOperation(Operation):
    kind = "motor_reprogram"

    @classmethod
    def validate(cls, service, params: dict) -> dict:
        return _validate(service, params)

    def run(self, ctx: OpContext) -> dict:
        supervisor = ctx.service.supervisor
        config = supervisor.config
        family = config.motor_type or "dynamixel"
        changes: list[dict] = self.params["changes"]
        moved: dict[int, int] = {}
        failed: list[dict] = []
        ctx.set_phase("acquiring", detail="taking the bus into maintenance")
        lease = supervisor.enter_maintenance(self.kind)
        try:
            port = hand_ops.resolve_motor_port(config, lease.presence)
            if not port:
                raise RuntimeError("no motor bus port found — check the USB adapter "
                                   "and the motors' power (and close Dynamixel Wizard)")
            ctx.log(f"re-programming {len(changes)} motor(s) on {port}")
            for i, c in enumerate(changes):
                ctx.check_stop()
                ctx.set_phase("programming", detail=f"ID {c['id']} → {c['new_id']}",
                              progress=i / len(changes))
                renamed, problem = self._program(ctx, family, port, c)
                if renamed:
                    moved[c["id"]] = c["new_id"]
                if problem:
                    failed.append({**c, "error": problem})
                    ctx.log(f"  ID {c['id']}: {problem}")
                else:
                    ctx.log(f"  ID {c['id']} → {c['new_id']}"
                            + (f" at {c['new_baud']:,} baud" if c["new_baud"] != c["baud_rate"] else ""))
            if moved:
                remap_bench_ids(config.config_path, moved)
        finally:
            supervisor.exit_maintenance()
        return self._finish(ctx, moved, failed)

    def _program(self, ctx: OpContext, family: str, port: str, c: dict) -> tuple[bool, str | None]:
        """(whether the ID was written, what went wrong)."""
        old, new, rate, to = c["id"], c["new_id"], c["baud_rate"], c["new_baud"]
        if not hand_ops.scan_bus(family, port, rate, (old, old)):
            return False, f"does not answer at {rate:,} baud — not changed"
        for r in {rate, to}:
            if new != old and hand_ops.scan_bus(family, port, r, (new, new)):
                return False, f"ID {new} already answers at {r:,} baud — not changed"
        renamed = False
        if new != old:
            if not hand_ops.change_motor_id(family, port, rate, old, new):
                return False, "the motor refused the ID write"
            renamed = True
            ctx.sleep(SETTLE_S)
        if to != rate:
            if not hand_ops.change_motor_baud(family, port, rate, new, to):
                return renamed, f"now ID {new}, but it refused the baud write (still {rate:,})"
            ctx.sleep(SETTLE_S)
        if not hand_ops.scan_bus(family, port, to, (new, new)):
            return renamed, (f"written, but nothing answers at ID {new} — "
                             f"two motors may have shared ID {old}")
        return renamed, None

    @staticmethod
    def _finish(ctx: OpContext, moved: dict[int, int], failed: list[dict]) -> dict:
        from orca_ui.hand.supervisor import HandBusyError

        if moved:
            try:
                ctx.service.supervisor.reload_config()
            except HandBusyError as e:
                ctx.log(f"bench config updated; reconnect pending: {e}")
        ctx.log(f"{len(moved)} motor(s) re-programmed"
                + (f", {len(failed)} not" if failed else ""))
        ctx.set_phase("done", detail=f"{len(moved)} re-programmed", progress=1.0)
        return {"moved": {str(k): v for k, v in moved.items()}, "failed": failed}


class SimulatedReprogramIdsOperation(ReprogramIdsOperation):
    """Mock-mode stand-in: every change succeeds; the config follows."""

    def run(self, ctx: OpContext) -> dict:
        supervisor = ctx.service.supervisor
        moved = {c["id"]: c["new_id"] for c in self.params["changes"]}
        ctx.set_phase("acquiring", detail="taking the bus into maintenance")
        supervisor.enter_maintenance(self.kind)
        try:
            ctx.sleep(0.05 * len(moved))
            for old, new in moved.items():
                ctx.log(f"  ID {old} → {new} [simulated]")
            remap_bench_ids(supervisor.config.config_path, moved)
        finally:
            supervisor.exit_maintenance()
        return self._finish(ctx, moved, [])
