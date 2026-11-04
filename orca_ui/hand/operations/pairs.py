"""Finding out which bench motors are coupled to which, by moving them.

Every motor is released, then each one in turn is held and turned by the
step one way and the other (15° unless asked otherwise — far enough that
backlash and a soft coupling do not swallow it) while every other shaft is
read. A released shaft that
follows belongs to the mover's partner; the sign it follows with says
whether the same command turns both shafts the same way (then the pair must
be driven opposed to load each other) or opposite ways (then the same sign
already opposes). The result replaces the thermal page's pairs — saved
beside the bench config — with each found pair marked as checked now.

Runs as an operation so it owns the bus like any run, honours the e-stop and
leaves every motor released when it is done, found or not.
"""

from __future__ import annotations

import math
import time
from datetime import datetime, timezone

import numpy as np

from orca_ui.bench import assignments_of
from orca_ui.hand.operations.base import OpContext, Operation
from orca_ui.hand.states import ControlSource

DEFAULT_STEP_DEG = 15.0
MIN_STEP_DEG, MAX_STEP_DEG = 1.0, 45.0   # the cap is the direct-move step limit
SETTLE_S = 0.6
# A shaft counts as following when it moved this share of the step (at
# least 0.6°): backlash takes its bite, a rigid coupling gives nearly all.
FOLLOW_SHARE = 0.3
FOLLOW_MIN_DEG = 0.6


def _deg(rad: float) -> float:
    return math.degrees(float(rad))


class PairDiscoveryOperation(Operation):
    kind = "pair_discovery"
    control_source = ControlSource.OPERATION

    @classmethod
    def validate(cls, service, params: dict) -> dict:
        from orca_ui.hand.service import ServiceError

        session = service.session
        if session is None:
            raise ServiceError("hand not connected", status_code=503)
        if not session.caps.motors:
            raise ServiceError("no motor bus in this session", status_code=409)
        known = [int(m) for m in session.hand.config.motor_ids]
        if len(known) < 2:
            raise ServiceError("two motors at least are needed to find a pair")
        raw = params.get("motors")
        if raw is None:
            motors = known
        else:
            try:
                motors = [int(m) for m in raw]
            except (TypeError, ValueError):
                raise ServiceError("motors must be a list of integer ids")
            unknown = [m for m in motors if m not in known]
            if unknown:
                raise ServiceError(f"unknown motor(s) {unknown}")
        try:
            step = float(params.get("step_deg", DEFAULT_STEP_DEG))
        except (TypeError, ValueError):
            raise ServiceError("step_deg must be a number")
        if not MIN_STEP_DEG <= step <= MAX_STEP_DEG:
            raise ServiceError(f"step_deg must be {MIN_STEP_DEG:g}..{MAX_STEP_DEG:g}")
        return {"motors": motors, "step_deg": step}

    def run(self, ctx: OpContext) -> dict:
        from orca_ui.hand.operations.thermal import save_setup
        from orca_ui.hand.service import ServiceError

        service = ctx.service
        session = service.session
        if session is None:
            raise ServiceError("hand not connected", status_code=503)
        hand = session.hand
        motors: list[int] = list(self.params["motors"])
        numbers = assignments_of(hand.config)
        label = lambda m: f"M{numbers.get(m, m)}"  # noqa: E731
        found: list[dict] = []
        partner_of: dict[int, int] = {}
        ambiguous: list[dict] = []
        self._step = float(self.params["step_deg"])
        self._follow_min = max(FOLLOW_MIN_DEG, FOLLOW_SHARE * self._step)

        ctx.log(f"finding pairs among {len(motors)} motors: each is held and turned "
                f"±{self._step:g}° in turn while the others are released")
        service.set_direct_motor_mode(True, from_operation=True)
        try:
            # Everyone released, so a coupled shaft is free to follow.
            service.disable_torque()
            ctx.sleep(0.2)
            for i, mover in enumerate(motors):
                ctx.check_stop()
                if mover in partner_of:
                    continue
                ctx.set_phase("probing", detail=f"turning {label(mover)}",
                              progress=i / len(motors))
                self._publish(ctx, found, ambiguous, mover, label)
                hand.enable_torque([mover])
                try:
                    follows = self._wiggle(ctx, hand, mover, motors)
                finally:
                    hand.disable_torque([mover])
                followers = {m: d for m, d in follows.items()
                             if m not in partner_of and self._followed(d)}
                if len(followers) == 1:
                    (partner, legs), = followers.items()
                    mean = sum(legs) / len(legs)
                    sense = 1 if mean > 0 else -1
                    found.append({"a": mover, "b": partner, "opposed": sense > 0,
                                  "followed_deg": round(abs(mean), 2),
                                  "checked": {"at": datetime.now(timezone.utc).isoformat(
                                      timespec="seconds"), "sense": sense}})
                    partner_of[mover] = partner
                    partner_of[partner] = mover
                    ctx.log(f"  {label(mover)} ↔ {label(partner)}: followed "
                            f"{abs(mean):.1f}° of {self._step:g}°, "
                            + ("same direction → drive opposed" if sense > 0
                               else "opposite directions → same sign opposes"))
                elif len(followers) > 1:
                    names = ", ".join(label(m) for m in followers)
                    ambiguous.append({"motor": mover, "followers": sorted(followers)})
                    ctx.log(f"  {label(mover)}: {names} all followed — more than two "
                            "coupled together? left unpaired")
                else:
                    ctx.log(f"  {label(mover)}: nothing followed")
        finally:
            try:
                service.disable_torque()
            except Exception:
                pass
            service.set_direct_motor_mode(False, from_operation=True)

        unpaired = [m for m in motors if m not in partner_of]
        pairs = [{k: v for k, v in p.items() if k != "followed_deg"} for p in found]
        if found:
            save_setup(ctx.settings, {"pairs": pairs})
        ctx.log(f"found {len(found)} pair(s)"
                + (f"; without a partner: {', '.join(label(m) for m in unpaired)}"
                   if unpaired else "")
                + (" — saved as the thermal page's pairs" if found
                   else " — the saved pairs are left as they were"))
        ctx.set_phase("done", detail=f"{len(found)} pair(s) found", progress=1.0)
        self._publish(ctx, found, ambiguous, None, label)
        return {"pairs": found, "unpaired": unpaired, "ambiguous": ambiguous}

    # ----- moving -----------------------------------------------------------------

    def _positions(self, hand, motors: list[int]) -> dict[int, float]:
        positions = hand.get_motor_pos(as_dict=True)
        return {m: _deg(positions[m]) for m in motors}

    def _wiggle(self, ctx: OpContext, hand, mover: int,
                motors: list[int]) -> dict[int, list[float]]:
        """±STEP_DEG and back; returns every other motor's movement per leg,
        signed relative to the mover's actual movement."""
        follows: dict[int, list[float]] = {m: [] for m in motors if m != mover}
        start = self._positions(hand, motors)
        for sign in (1, -1):
            ctx.check_stop()
            before = self._positions(hand, motors)
            hand.write_motor_pos([mover], np.asarray(
                [math.radians(start[mover] + sign * self._step)], dtype=float))
            ctx.sleep(SETTLE_S)
            after = self._positions(hand, motors)
            moved = after[mover] - before[mover]
            ref = math.copysign(1.0, moved) if abs(moved) > 1e-6 else float(sign)
            for m in follows:
                follows[m].append((after[m] - before[m]) * ref)
            hand.write_motor_pos([mover], np.asarray([math.radians(start[mover])],
                                                      dtype=float))
            ctx.sleep(SETTLE_S)
        return follows

    def _followed(self, legs: list[float]) -> bool:
        return bool(legs) and all(abs(d) >= self._follow_min for d in legs) \
            and len({math.copysign(1, d) for d in legs}) == 1

    def _publish(self, ctx: OpContext, found, ambiguous, mover, label) -> None:
        ctx.set_extra({
            "mover": mover,
            "step_deg": self._step,
            "pairs": [{"a": p["a"], "b": p["b"], "opposed": p["opposed"],
                       "followed_deg": p["followed_deg"]} for p in found],
            "ambiguous": ambiguous,
        })
