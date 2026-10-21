"""Bus scan: which motors are actually on the wire, by ID, model and baud.

A testbench grows and shrinks — two motors today, five next month — and a
config that names the wrong IDs connects to nothing. The scan answers the
question the config is guessing at: it pings IDs 0 to 50 at 1 M baud — the
hand's rate, and the range any bench motor is programmed into — and reports
what answered. ``baud_rate`` and ``id_max`` widen that for a motor that was
left at the factory 57,600 or a stray high ID. The bench page then offers to
adopt the found set into the bench config.

The scan needs the port to itself, so it runs under the supervisor's
maintenance lease like chain configuration does: the session (if any) is
closed, torque is off, and the connect ladder resumes when the scan ends.
It works with no session at all, which is exactly when it is needed most.
Progress is published in ID chunks so a 253-ID sweep at several baud rates
reads as a moving bar rather than a stall.
"""

from __future__ import annotations

from orca_ui.hand.operations import hand_ops
from orca_ui.hand.operations.base import OpContext, Operation

SCAN_ID_RANGE = (0, 50)
MAX_ID = 252
DEFAULT_BAUD = 1_000_000
SCAN_CHUNK = 16
SIMULATED_MODEL = "XC330-M288-T"
SIMULATED_PORT = "/dev/orca-mock"


def _id_range(id_max: int | None) -> tuple[int, int]:
    return (SCAN_ID_RANGE[0], SCAN_ID_RANGE[1] if id_max is None else int(id_max))


def _validate(service, params: dict) -> dict:
    from orca_ui.hand.service import ServiceError

    motor_type = params.get("motor_type")
    if motor_type is not None and motor_type not in hand_ops.known_motor_types():
        raise ServiceError(f"unknown motor_type {motor_type!r}")
    baud = params.get("baud_rate")
    if baud is not None:
        try:
            baud = int(baud)
        except (TypeError, ValueError):
            raise ServiceError("baud_rate must be an integer")
        if baud <= 0:
            raise ServiceError("baud_rate must be positive")
    id_max = params.get("id_max")
    if id_max is not None:
        try:
            id_max = int(id_max)
        except (TypeError, ValueError):
            raise ServiceError("id_max must be an integer")
        if not SCAN_ID_RANGE[0] <= id_max <= MAX_ID:
            raise ServiceError(f"id_max must be {SCAN_ID_RANGE[0]}..{MAX_ID}")
    return {"motor_type": motor_type, "baud_rate": baud, "id_max": id_max}


class _Found:
    def __init__(self, configured: list[int], id_range: tuple[int, int]):
        self.configured = [int(m) for m in configured]
        self.id_range = id_range
        self.motors: list[dict] = []
        self.port: str | None = None
        self.motor_type: str | None = None
        self.baud_rate: int | None = None
        self.scanned_to: int = -1

    def add(self, rows: list[dict]) -> None:
        known = {(m["id"], m["baud_rate"]) for m in self.motors}
        for row in rows:
            key = (int(row["id"]), int(row["baud_rate"]))
            if key in known:
                continue
            known.add(key)
            self.motors.append({
                "id": int(row["id"]),
                "model_name": str(row.get("model_name") or "?"),
                "baud_rate": int(row["baud_rate"]),
            })
        self.motors.sort(key=lambda m: (m["id"], m["baud_rate"]))

    def extra(self, done: bool = False) -> dict:
        return {
            "port": self.port,
            "motor_type": self.motor_type,
            "baud_rate": self.baud_rate,
            "scanned_to": self.scanned_to,
            "id_range": list(self.id_range),
            "motors": list(self.motors),
            "configured": list(self.configured),
            "done": done,
        }

    def result(self) -> dict:
        ids = sorted({m["id"] for m in self.motors})
        rates = sorted({m["baud_rate"] for m in self.motors})
        return {
            "port": self.port,
            "motor_type": self.motor_type,
            "motors": list(self.motors),
            "motor_ids": ids,
            "configured": list(self.configured),
            "missing": [m for m in self.configured if m not in ids],
            "unconfigured": [m for m in ids if m not in self.configured],
            # One bus runs at one rate: a mixed answer means a motor that
            # must be re-programmed before the set can connect together.
            "mixed_baud": len(rates) > 1,
            "baud_rates": rates,
        }


class BusScanOperation(Operation):
    kind = "bus_scan"

    @classmethod
    def validate(cls, service, params: dict) -> dict:
        return _validate(service, params)

    def run(self, ctx: OpContext) -> dict:
        supervisor = ctx.service.supervisor
        config = supervisor.config
        id_range = _id_range(self.params["id_max"])
        found = _Found(list(config.motor_ids), id_range)
        ctx.set_phase("acquiring", detail="taking the bus into maintenance")
        lease = supervisor.enter_maintenance(self.kind)
        try:
            ctx.check_stop()
            port = hand_ops.resolve_motor_port(config, lease.presence)
            if not port:
                raise RuntimeError(
                    "no motor bus port found — check the USB adapter and "
                    "the motors' power")
            found.port = port
            families = [self.params["motor_type"] or config.motor_type] \
                if (self.params["motor_type"] or config.motor_type) \
                else hand_ops.known_motor_types()
            rate = int(self.params["baud_rate"] or DEFAULT_BAUD)
            lo, hi = id_range
            ctx.log(f"scanning {port} for {' / '.join(families)} motors, "
                    f"IDs {lo}–{hi} at {rate:,} baud")
            steps = [(family, rate) for family in families]
            chunks = list(range(lo, hi + 1, SCAN_CHUNK))
            total = len(steps) * len(chunks)
            done = 0
            for family, rate in steps:
                found.motor_type = family
                found.baud_rate = rate
                found.scanned_to = -1
                ctx.set_phase("scanning",
                              detail=f"{family} @ {rate:,} baud",
                              progress=done / total)
                before = len(found.motors)
                for start in chunks:
                    ctx.check_stop()
                    end = min(start + SCAN_CHUNK - 1, hi)
                    try:
                        rows = hand_ops.scan_bus(family, port, rate, (start, end))
                    except Exception as e:
                        raise RuntimeError(f"scan failed on {port}: {e}") from e
                    found.add(rows)
                    found.scanned_to = end
                    done += 1
                    ctx.set_progress(done / total)
                    ctx.set_extra(found.extra())
                new = found.motors[before:]
                if new:
                    ctx.log(f"  {rate:,} baud: " + ", ".join(
                        f"ID {m['id']} ({m['model_name']})" for m in new))
            ctx.set_extra(found.extra(done=True))
            result = found.result()
            self._log_result(ctx, result)
            return result
        finally:
            supervisor.exit_maintenance()

    @staticmethod
    def _log_result(ctx: OpContext, result: dict) -> None:
        ids = result["motor_ids"]
        ctx.log(f"{len(ids)} motor(s) on the bus: {ids}" if ids
                else "no motors answered — check power and the data cable")
        if result["missing"]:
            ctx.log(f"configured but not found: {result['missing']}")
        if result["unconfigured"]:
            ctx.log(f"on the bus but not in the config: {result['unconfigured']}")
        if result["mixed_baud"]:
            ctx.log(f"motors answer at different baud rates "
                    f"{result['baud_rates']} — one bus needs one rate; "
                    "re-program the odd one out before adopting the set")


class SimulatedBusScanOperation(Operation):
    """Mock-mode stand-in: the simulated bus holds the config's motors
    (or ``simulate_ids``), reported with the real op's pacing and shapes.
    Takes the real maintenance lease like every simulated maintenance op."""

    kind = "bus_scan"
    CHUNK_S = 0.03

    @classmethod
    def validate(cls, service, params: dict) -> dict:
        clean = _validate(service, params)
        ids = params.get("simulate_ids")
        clean["simulate_ids"] = (
            sorted({int(m) for m in ids}) if isinstance(ids, (list, tuple)) else None)
        return clean

    def run(self, ctx: OpContext) -> dict:
        supervisor = ctx.service.supervisor
        config = supervisor.config
        id_range = _id_range(self.params["id_max"])
        found = _Found(list(config.motor_ids), id_range)
        on_bus = self.params["simulate_ids"]
        if on_bus is None:
            on_bus = sorted(int(m) for m in config.motor_ids)
        ctx.set_phase("acquiring", detail="taking the bus into maintenance")
        supervisor.enter_maintenance(self.kind)
        try:
            found.port = SIMULATED_PORT
            found.motor_type = config.motor_type or "dynamixel"
            found.baud_rate = int(self.params["baud_rate"] or DEFAULT_BAUD)
            ctx.log(f"scanning {SIMULATED_PORT} [simulated]")
            lo, hi = id_range
            chunks = list(range(lo, hi + 1, SCAN_CHUNK))
            ctx.set_phase("scanning", detail=f"{found.motor_type} @ "
                                             f"{found.baud_rate:,} baud", progress=0.0)
            for index, start in enumerate(chunks, 1):
                ctx.sleep(self.CHUNK_S)
                end = min(start + SCAN_CHUNK - 1, hi)
                found.add([{"id": m, "model_name": SIMULATED_MODEL,
                            "baud_rate": found.baud_rate}
                           for m in on_bus if start <= m <= end])
                found.scanned_to = end
                ctx.set_progress(index / len(chunks))
                ctx.set_extra(found.extra())
            ctx.set_extra(found.extra(done=True))
            result = found.result()
            result["simulated"] = True
            BusScanOperation._log_result(ctx, result)
            return result
        finally:
            supervisor.exit_maintenance()
