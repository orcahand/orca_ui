"""Trajectory recording: sample measured joints while the hand is posed by hand.

Torque is disabled at start and NEVER re-enabled by this operation (the
"torque is never auto-enabled" rule). The op owns the control source so a
second client can't enable torque or write targets mid-recording — motors
must not fight the person posing the hand.

Ending semantics: "stop & save" arrives as operation *input* (handled by the
``handle_input`` hook / waypoint prompt); a plain /api/operation/stop or
e-stop ABORTS without saving.
"""

from __future__ import annotations

import time

from orca_ui.hand.operations.base import OpContext, Operation
from orca_ui.hand.states import ControlSource
from orca_ui.library import CONTINUOUS, WAYPOINTS, LibraryError

DEFAULT_FREQUENCY_HZ = 50.0
MAX_FREQUENCY_HZ = 60.0   # the encoder read path is fresh well past this
MAX_FRAMES = 30_000       # 10 min @ 50 Hz
SAVE_VALUES = {"save", "stop & save", "stop_and_save"}


class RecordOperation(Operation):
    kind = "record"
    control_source = ControlSource.OPERATION

    def __init__(self, params: dict):
        super().__init__(params)
        self._save_requested = False

    @classmethod
    def validate(cls, service, params: dict) -> dict:
        from orca_ui.hand.service import ServiceError

        session = service.session
        if session is None:
            raise ServiceError("hand not connected", status_code=503)
        if not session.caps.encoders:
            raise ServiceError(
                "recording needs joint encoders (measured joint angles)",
                status_code=409)

        mode = params.get("mode", "continuous")
        if mode not in ("continuous", "waypoints"):
            raise ServiceError("mode must be 'continuous' or 'waypoints'")
        frequency = float(params.get("frequency", DEFAULT_FREQUENCY_HZ))
        if not 1.0 <= frequency <= MAX_FREQUENCY_HZ:
            raise ServiceError(
                f"frequency must be 1..{MAX_FREQUENCY_HZ:g} Hz")
        name = str(params.get("name") or "")
        try:
            if service.library.trajectory_exists(name):
                raise ServiceError(f"trajectory {name!r} already exists",
                                   status_code=409)
        except LibraryError as e:
            raise ServiceError(str(e), status_code=e.status_code)
        return {
            "mode": mode,
            "frequency": frequency,
            "name": name,
            # False only for mock tests, where the sweeper must keep driving
            # motion through the torque gate while we record it.
            "disable_torque": bool(params.get("disable_torque", True)),
        }

    def run(self, ctx: OpContext) -> dict:
        from orca_ui.hand.service import ServiceError

        service = ctx.service
        session = service.session
        if session is None:
            raise ServiceError("hand not connected", status_code=503)

        if self.params["disable_torque"]:
            try:
                service.disable_torque()
                ctx.log("torque disabled — pose the hand by hand")
            except ServiceError:
                pass  # sensors-only session: nothing to disable

        config = service.supervisor.config
        joint_ids = list(config.joint_ids)
        metadata = {
            "created_at": time.strftime("%Y%m%d_%H%M%S"),
            "joint_ids": joint_ids,
            "hand_type": config.type,
        }

        def sample() -> list[float]:
            measured = session.measured_joints() or {}
            return [float(measured.get(j, 0.0)) for j in joint_ids]

        if self.params["mode"] == "waypoints":
            return self._record_waypoints(ctx, metadata, sample)
        return self._record_continuous(ctx, metadata, sample)

    def _record_waypoints(self, ctx: OpContext, metadata: dict,
                          sample) -> dict:
        metadata["type"] = WAYPOINTS
        waypoints: list[list[float]] = []
        ctx.set_phase("recording", detail="0 waypoints")
        while True:
            choice = ctx.wait_input(
                f"{len(waypoints)} waypoint(s) captured — pose the hand, "
                "then capture", ["Capture", "Stop & save"])
            if choice.lower() in SAVE_VALUES:
                break
            waypoints.append(sample())
            ctx.set_detail(f"{len(waypoints)} waypoints")
            ctx.log(f"waypoint #{len(waypoints)} captured")
        return self._save(ctx, metadata, "waypoints", waypoints)

    def _record_continuous(self, ctx: OpContext, metadata: dict,
                           sample) -> dict:
        frequency = self.params["frequency"]
        metadata["type"] = CONTINUOUS
        metadata["sampling_frequency_hz"] = frequency
        frames: list[list[float]] = []
        dt = 1.0 / frequency
        ctx.set_phase("recording",
                      detail=f"0 frames @ {frequency:g} Hz — stop & save when done")
        ctx.log(f"recording continuously at {frequency:g} Hz")
        next_t = time.monotonic()
        while not self._save_requested:
            ctx.check_stop()
            frames.append(sample())
            if len(frames) % max(int(frequency / 2), 1) == 0:
                ctx.set_detail(
                    f"{len(frames)} frames · {len(frames) / frequency:.1f}s")
            if len(frames) >= MAX_FRAMES:
                ctx.log(f"frame cap reached ({MAX_FRAMES}) — saving")
                break
            next_t += dt
            delay = next_t - time.monotonic()
            if delay > 0:
                ctx.sleep(delay)
        return self._save(ctx, metadata, "angles", frames)

    def _save(self, ctx: OpContext, metadata: dict, key: str,
              rows: list[list[float]]) -> dict:
        from orca_ui.hand.service import ServiceError

        if not rows:
            raise ServiceError("nothing recorded — no frames captured")
        name = self.params["name"]
        ctx.service.library.save_trajectory(
            name, {"metadata": metadata, key: rows})
        duration = (
            len(rows) / metadata["sampling_frequency_hz"]
            if metadata["type"] == CONTINUOUS else None
        )
        ctx.log(f"saved {name}: {len(rows)} {key}")
        return {"name": name, "frames": len(rows),
                "type": metadata["type"], "duration_s": duration}

    def handle_input(self, value: str) -> bool:
        # Continuous mode ends via input on the hook (the sampling loop isn't
        # waiting on the queue); waypoint mode uses the queue path.
        if self.params["mode"] == "continuous" and \
                value.lower() in SAVE_VALUES:
            self._save_requested = True
            return True
        return False
