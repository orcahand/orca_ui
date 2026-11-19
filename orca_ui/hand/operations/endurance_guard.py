"""Unattended endurance runs: clear latched motors and wait out heat, then go on.

Checked once per cycle from the published telemetry, so it never reads the bus
while the hand moves. A latched motor is cleared the way the console's reboot
button clears it (``service.reboot_motor``) and the run continues; the latch's
classification and message are untouched, so a power fault is still reported
as one. Only a clear that does not take, after a few tries, ends the run. Every
clear and every heat pause goes into the run's record.
"""

from __future__ import annotations

import time

from orca_ui.streaming import topics as T

# All the limits of an unattended run.
HEAT_PAUSE_C = 60.0  # hottest motor at this: torque off until it cools
HEAT_RESUME_C = 50.0  # ...back under this, then the run goes on
HEAT_POLL_S = 10.0
THERMAL_MARGIN_C = (
    10.0  # an overheated motor cools this far below its limit before a clear
)
CLEAR_ATTEMPTS = 3  # tries per latch before the run ends
CLEAR_RETRY_S = 10.0  # between them
SETTLE_S = 2.0  # after a clear, before the run reads the motors again


class HardStop(Exception):
    """A latch that would not clear: the hand cannot run on."""


class EnduranceGuard:
    def __init__(self, ctx, record):
        self._ctx = ctx
        self._record = record
        self._service = ctx.service

    def after_cycle(self, cycle: int) -> bool:
        """True when the hand was let go of and must glide back to the start."""
        let_go = self._heat(cycle)
        motors = self._motors()
        latched = {
            mid: m
            for mid, m in motors.items()
            if m.get("hw_error_flags") and not (m.get("recovery") or {}).get("cooling")
        }
        for mid, motor in latched.items():
            self._clear(cycle, mid, motor)
        return let_go or bool(latched)

    def _motors(self) -> dict:
        return self._record.payload(T.MOTORS_FAULTS).get("motors") or {}

    def _temps(self) -> dict:
        temps = self._record.payload(T.MOTORS_TELEMETRY).get("temps") or {}
        return {k: v for k, v in temps.items() if v is not None}

    def _event(self, cycle, mid, joint, flags, outcome) -> None:
        self._record.record_clear(
            {
                "at": time.time(),
                "cycle": cycle,
                "motor": int(mid),
                "joint": joint,
                "flags": flags,
                "temp_c": self._temps().get(int(mid)),
                "outcome": outcome,
            }
        )

    def _heat(self, cycle: int) -> bool:
        temps = self._temps()
        if not temps or max(temps.values()) < HEAT_PAUSE_C:
            return False
        hot = max(temps, key=temps.get)
        joint = (self._motors().get(hot) or {}).get("joint")
        ctx = self._ctx
        ctx.log(
            f"motor {hot} ({joint}) at {temps[hot]:.0f} °C: torque off until it is "
            f"under {HEAT_RESUME_C:g} °C"
        )
        self._service.disable_torque()
        start = time.monotonic()
        while max(self._temps().values(), default=0.0) >= HEAT_RESUME_C:
            ctx.sleep(HEAT_POLL_S)
        self._torque_on(cycle, hot, joint, ["heat"])
        self._event(
            cycle,
            hot,
            joint,
            [f"{temps[hot]:.0f} °C"],
            f"paused {time.monotonic() - start:.0f} s to cool; run continues",
        )
        ctx.log("cooled; back to the start, the run continues")
        return True

    def _clear(self, cycle: int, mid: str, motor: dict) -> None:
        ctx, service = self._ctx, self._service
        joint, flags = motor.get("joint"), list(motor["hw_error_flags"])
        info = motor.get("hw_error") or {}
        ctx.log(
            f"motor {mid} ({joint}) latched {', '.join(flags)} ({info.get('kind')} fault): "
            "clearing it and going on"
        )
        if info.get("kind") == "thermal":
            # Rebooted hot, it latches again on the next command.
            service.disable_torque()
            limit = (
                self._record.payload(T.MOTORS_TELEMETRY).get("shutdown_temps") or {}
            ).get(mid)
            cool = HEAT_RESUME_C if limit is None else limit - THERMAL_MARGIN_C
            while self._temps().get(mid, 0.0) > cool:
                ctx.sleep(HEAT_POLL_S)
        problem = None
        for attempt in range(1, CLEAR_ATTEMPTS + 1):
            if attempt > 1:
                ctx.log(
                    f"motor {mid} clear try {attempt - 1} failed ({problem}); again in "
                    f"{CLEAR_RETRY_S:g} s"
                )
                ctx.sleep(CLEAR_RETRY_S)
            problem = self._try_clear(mid)
            if problem is None:
                break
        else:
            self._event(
                cycle,
                mid,
                joint,
                flags,
                f"not cleared after {CLEAR_ATTEMPTS} tries: {problem}",
            )
            raise HardStop(f"motor {mid} ({joint}) {', '.join(flags)}: {problem}")
        self._torque_on(cycle, mid, joint, flags)
        self._event(
            cycle,
            mid,
            joint,
            flags,
            "cleared; run continues" + (f" (try {attempt})" if attempt > 1 else ""),
        )

    def _try_clear(self, mid) -> str | None:
        """The console's reboot button: cleared only when the motor answers unflagged."""
        try:
            result = self._service.reboot_motor(int(mid), from_operation=True)
        except Exception as e:
            return f"reboot failed: {e}"
        if result.get("cleared") is None:
            return "no answer after the reboot"
        if result.get("cleared") is not True:
            return f"still latched ({', '.join(result.get('hw_error_flags') or [])})"
        # Lets the faults report catch up before the next cycle reads it.
        self._ctx.sleep(SETTLE_S)
        return None

    def _torque_on(self, cycle, mid, joint, flags) -> None:
        try:
            self._service.enable_torque(from_operation=True)
        except Exception as e:
            self._event(cycle, mid, joint, flags, f"torque would not come back on: {e}")
            raise HardStop(f"torque would not come back on: {e}") from e
