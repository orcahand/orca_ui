"""The tool catalog: 22 ``orca_*`` tools wrapping the backend's REST/WS API.

Registration order matters only for the first entry: orca_estop is
registered first so clients that list tools in order show it at the top.
With ``read_only`` only the read tools (plus e-stop) are registered, so the
catalog stays honest instead of returning a wall of refusals.
"""

from __future__ import annotations

import asyncio
import base64
import time
from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP, Image
from mcp.types import ToolAnnotations
from pydantic import Field

from orca_ui.mcp import telemetry
from orca_ui.mcp.client import BackendError
from orca_ui.mcp.server import (ServerState, confirm_gate, mock_gate,
                                refusal, with_state)

NAME_PATTERN = r"^[a-zA-Z0-9_-]{1,64}$"

ACTIVE_OP_STATES = {"starting", "running", "paused", "awaiting_input",
                    "stopping"}

# Topics an agent can sample. Deliberately excluded: operation.log /
# teleop.log (covered by orca_get_operation), teleop.preview (image tool),
# error (translated passthrough).
Topic = Literal[
    "joints.measured", "joints.estimate", "joints.target",
    "joints.correction", "tactile.forces", "tactile.taxels",
    "motors.telemetry", "stats", "status", "control.state",
    "operation.state", "teleop.state", "teleop.targets",
]

CALIBRATE_WHAT = (
    "What this does: drives EVERY joint to its mechanical hard stops to find "
    "range limits — several minutes of autonomous motion; the normal session "
    "is torn down for the duration (maintenance mode). Before confirming: "
    "the hand must be securely mounted with nothing in its workspace.")

TENSION_WHAT = (
    "What this does: winds the motors against the tendons (wind → ramp → "
    "hold → release) so an operator can tension the spools — motors stall "
    "deliberately. Before confirming: this is a bench maintenance procedure; "
    "a human should be at the hand.")

ENGAGE_WHAT = (
    "What this does: the physical hand starts mirroring live tracked "
    "human-hand motion immediately (ramped in). The motion source is "
    "external and unpredictable. Before confirming: verify the preview "
    "(orca_get_camera_preview), ensure the workspace is clear, and confirm "
    "the user asked for this.")


def _ann(title: str, *, read_only: bool = False, destructive: bool = False,
         idempotent: bool = False) -> ToolAnnotations:
    return ToolAnnotations(title=title, readOnlyHint=read_only,
                           destructiveHint=destructive,
                           idempotentHint=idempotent, openWorldHint=False)


def register_tools(mcp: FastMCP, state: ServerState) -> None:   # noqa: C901
    backend = state.backend

    # ----- e-stop (always registered, always first) ---------------------------

    @mcp.tool(annotations=_ann("EMERGENCY STOP", idempotent=True))
    async def orca_estop() -> dict:
        """EMERGENCY STOP — immediately stops teleop, aborts any running
        operation, and disables torque on all motors. Always safe to call;
        never requires confirmation; use whenever anything looks wrong.

        Note: aborts an in-progress recording WITHOUT saving. This is a
        de-energize-everything button, not a way to take control."""
        result = await backend.estop()
        report = result.get("report", {})
        return {
            "ok": True,
            "summary": (
                f"teleop stopped={report.get('teleop_stopped', 'n/a')}, "
                f"operation stopped={report.get('operation_stopped', 'n/a')}, "
                f"torque disabled={report.get('torque_disabled', 'n/a')}"),
            "report": report,
        }

    # ----- reads ---------------------------------------------------------------

    @mcp.tool(annotations=_ann("Hand status overview", read_only=True,
                               idempotent=True))
    async def orca_get_status() -> dict:
        """One-call situational overview: torque, real-vs-mock, connection
        state/capabilities, control owner, active operation, teleop session,
        frame health. Call this first — motion tools need torque enabled AND
        control_owner 'manual'."""
        status = await backend.get("/api/status")
        torque = bool(status.get("torque_enabled"))
        out: dict = {
            "torque": ("ENABLED — hand is energized" if torque
                       else "disabled — hand is limp"),
        }
        try:
            summary = await state.hand_summary()
            out["hand"] = (
                "mock (simulated)" if summary["mock"] else
                f"REAL HARDWARE ({summary['model_name']}, {summary['side']})")
        except BackendError:
            out["hand"] = "unknown — treat as REAL"
        out["connection"] = {
            k: status.get(k)
            for k in ("state", "capabilities", "message", "ports", "since")}
        try:
            control = (await backend.get("/api/hand/info")).get("control", {})
            out["control_owner"] = control.get("control_owner")
            out["max_current_ma"] = control.get("max_current")
            out["tactile_mode"] = control.get("tactile_mode")
        except BackendError:
            pass
        try:
            op = (await backend.get("/api/operation")).get("operation")
            out["operation"] = op and {
                k: op.get(k)
                for k in ("kind", "state", "phase", "progress", "awaiting")}
        except BackendError:
            out["operation"] = None
        try:
            session = (await backend.get("/api/teleop/state")).get("session")
            active = bool(session and session.get("state") != "idle")
            out["teleop"] = session and {
                "active": active, "state": session.get("state"),
                "source": session.get("source"),
                "engaged": session.get("engaged")}
        except BackendError:
            out["teleop"] = None
        try:
            out["frame_health"] = await backend.get("/api/stats")
        except BackendError:
            pass
        return out

    @mcp.tool(annotations=_ann("Hand model info", read_only=True,
                               idempotent=True))
    async def orca_get_hand_info() -> dict:
        """Static hand description: every joint with its ROM [lo, hi] in
        DEGREES, neutral angle, and encoder status, plus tactile sensor
        layout. Static per connection — call once and remember; live values
        come from orca_read_telemetry, current control state from
        orca_get_status."""
        info = await backend.get("/api/hand/info")
        info.pop("control", None)
        return info

    @mcp.tool(annotations=_ann("Read live telemetry", read_only=True,
                               idempotent=True))
    async def orca_read_telemetry(
        topics: Annotated[list[Topic], Field(
            min_length=1,
            description="WS topics to read (angles in degrees, forces in "
                        "Newtons, temps in °C, currents in mA)")],
        duration_s: Annotated[float, Field(
            ge=0, le=15,
            description="0 = instant snapshot (latest value per topic); "
                        ">0 = sample a window, e.g. to watch a motion or a "
                        "grasp")] = 0,
        sample_hz: Annotated[float, Field(
            ge=1, le=20,
            description="sampling rate for windowed reads (budget: 150 "
                        "samples/topic — long windows are auto-decimated to "
                        "fit)")] = 5,
    ) -> dict:
        """Live values snapshot or short time-series (these exist only on
        the WebSocket stream, not in REST). joints.measured = encoder truth;
        joints.target = last command; tactile.forces = per-finger resultant
        Newtons; motors.telemetry = temps/currents. Prefer the built-in
        verify of orca_set_joints / orca_apply_pose for move-and-check.

        Windowed reads (duration_s > 0) return only the frames that MOVED:
        frames within a small per-quantity deadband of the previous kept
        frame are dropped and counted under `dropped_unchanged`, and the
        first and last frame of the window always survive. A still hand
        therefore costs two frames, not a hundred. Sample `t` values are
        real capture times, so gaps mean nothing moved."""
        return await telemetry.ws_snapshot(
            backend.url, list(topics), duration_s=duration_s,
            sample_hz=sample_hz)

    @mcp.tool(annotations=_ann("Teleop camera preview", read_only=True,
                               idempotent=True))
    async def orca_get_camera_preview() -> Image:
        """Grab a FRESH teleop camera frame (with hand-tracking overlay) as
        an image — use it to verify the camera sees the operator's hand
        before orca_teleop_engage. Requires an active teleop session
        (orca_teleop_start) with source='mediapipe' (the only source that
        publishes camera frames); frame publishing is enabled automatically
        if the session doesn't have it on."""
        session = (await backend.get("/api/teleop/state")).get("session")
        active = bool(session
                      and session.get("state") not in (None, "idle", "error"))
        if not active:
            raise BackendError(
                "no active teleop session — orca_teleop_start first (only "
                "source='mediapipe' publishes camera preview frames).")
        if not (session.get("config") or {}).get("preview"):
            # The streamer only publishes frames while config.preview is on
            # (normally toggled by the browser panel).
            await backend.post("/api/teleop/config",
                               {"config": {"preview": True}})
        # Windowed read + age check: the hub replays the last-EVER frame on
        # subscribe, which may be from an ended session — only a frame
        # captured within the window (10 Hz ceiling) counts as live.
        snap = await telemetry.ws_snapshot(backend.url, ["teleop.preview"],
                                           duration_s=2.0, sample_hz=10)
        topic = (snap.get("topics") or {}).get("teleop.preview") or {}
        samples = topic.get("samples") or []
        jpeg = (samples[-1]["data"] or {}).get("jpeg") if samples else None
        age_ms = (snap.get("age_ms") or {}).get("teleop.preview")
        if not jpeg or age_ms is None or age_ms > 2500:
            raise BackendError(
                "no fresh camera preview frame (the only available frame is "
                "stale or absent) — the session's source may not support "
                "preview (only 'mediapipe' does), or the streamer is still "
                "starting; retry in a moment or check orca_get_status.")
        return Image(data=base64.b64decode(jpeg), format="jpeg")

    @mcp.tool(annotations=_ann("List poses/trajectories/demos",
                               read_only=True, idempotent=True))
    async def orca_list_library() -> dict:
        """Everything applyable or replayable: poses (builtin + user),
        recorded trajectories, demo sequences. Pose names feed
        orca_apply_pose; trajectory names feed
        orca_start_operation(kind='replay'); demo names feed kind='demo'."""
        poses = (await backend.get("/api/poses"))["poses"]
        trajectories = (await backend.get("/api/trajectories"))["trajectories"]
        demos = (await backend.get("/api/demos"))["demos"]
        return {
            "poses": {
                "builtin": [p["name"] for p in poses if p.get("builtin")],
                "user": [{"name": p["name"], "saved_at": p.get("saved_at")}
                         for p in poses if not p.get("builtin")],
            },
            "trajectories": trajectories,
            "demos": demos,
        }

    @mcp.tool(annotations=_ann("Operation status / wait", read_only=True,
                               idempotent=True))
    async def orca_get_operation(
        wait_s: Annotated[float, Field(
            ge=0, le=300,
            description="0 = return immediately; >0 = poll until the "
                        "operation reaches done/error/awaiting_input or the "
                        "wait times out")] = 0,
        log_lines: Annotated[int, Field(ge=0, le=200)] = 20,
    ) -> dict:
        """Current/last operation snapshot plus a log tail. If state is
        'awaiting_input', answer awaiting.prompt via
        orca_send_operation_input. A timed-out wait is NOT a failure — call
        again with a longer wait_s; calibration takes minutes."""
        op = (await backend.get("/api/operation")).get("operation")
        timed_out = False
        if wait_s > 0:
            deadline = time.monotonic() + wait_s
            while (op and op.get("state") in
                   {"starting", "running", "paused", "stopping"}):
                if time.monotonic() >= deadline:
                    timed_out = True
                    break
                await asyncio.sleep(0.5)
                op = (await backend.get("/api/operation")).get("operation")
        log = None
        if log_lines > 0:
            try:
                payload = await backend.get("/api/operation/log")
                log = [entry.get("line", "") if isinstance(entry, dict)
                       else str(entry)
                       for entry in (payload.get("lines") or [])[-log_lines:]]
            except BackendError:
                log = None
        return {"operation": op, "log": log, "timed_out": timed_out}

    if state.settings.read_only:
        return

    # ----- connection & safety --------------------------------------------------

    @mcp.tool(annotations=_ann("Reconnect hardware", idempotent=True))
    async def orca_reconnect() -> dict:
        """Tear down and re-run the hardware connect ladder (torque comes
        back DISABLED; no motion). Use after cable/power changes or when
        orca_get_status shows a degraded/disconnected state."""
        gate = await mock_gate(state)
        if gate:
            return gate
        await backend.post("/api/reconnect")
        state.invalidate_hand_summary()
        ports = await backend.get("/api/ports")
        status = await backend.get("/api/status")
        return {
            "ok": True, "state": status.get("state"), "ports": ports,
            "note": ("reconnect is asynchronous — poll orca_get_status; "
                     "expect DETECTING → CONNECTING → CONNECTED"),
        }

    @mcp.tool(annotations=_ann("Enable/disable motor torque",
                               destructive=True, idempotent=True))
    async def orca_set_torque(
        enabled: Annotated[bool, Field(
            description="true energizes the motors (hand becomes stiff and "
                        "acts on targets); false makes the hand limp")],
        confirm: Annotated[bool, Field(
            description="required once per server session for the FIRST "
                        "enable on real hardware; ignored on mock")] = False,
    ) -> dict:
        """The master consent gate for all motion: nothing in this server
        ever enables torque implicitly. Enabling re-anchors the control loop
        first, so it never lurches. Disable (or orca_park) before a human
        handles the hand."""
        if enabled:
            gate = await mock_gate(state)
            if gate:
                return gate
            if not state.torque_acknowledged:
                gate = await confirm_gate(state, confirm, (
                    "What this does: energizes all motors — the hand becomes "
                    "stiff, holds its pose, and will act on any subsequent "
                    "target command. This acknowledgment is needed once per "
                    "MCP server session (first enable only)."))
                if gate:
                    return gate
                # Latch only when the gate was actually enforced: a pass on
                # a mock backend must not pre-acknowledge a later mock→real
                # backend swap at the same URL.
                if await state.is_real():
                    state.torque_acknowledged = True
            result = await backend.post("/api/torque/enable")
            payload = {"ok": True, "torque_enabled": True,
                       "seed_pose": result.get("seed")}
        else:
            await backend.post("/api/torque/disable")
            payload = {"ok": True, "torque_enabled": False}
        return await with_state(state, payload)

    @mcp.tool(annotations=_ann("Set motor current limit", destructive=True,
                               idempotent=True))
    async def orca_set_max_current(
        ma: Annotated[int, Field(
            gt=0, le=2000,
            description="motor current ceiling in mA — LOWER is safer "
                        "(150–300 mA suits gentle grasp experiments)")],
        confirm: Annotated[bool, Field(
            description="required when RAISING the limit on real hardware; "
                        "lowering never needs it")] = False,
    ) -> dict:
        """Cap motor current — the primary force/safety envelope knob.
        Raising it increases stall force and heat (motor temperatures are
        only reported, never enforced), hence the asymmetric confirm."""
        gate = await mock_gate(state)
        if gate:
            return gate
        current = None
        try:
            control = (await backend.get("/api/hand/info")).get("control", {})
            current = control.get("max_current")
        except BackendError:
            pass
        # Fail closed: an unknown baseline is treated as a raise.
        if current is None or ma > int(current):
            baseline = (f"{current} mA" if current is not None
                        else "an UNKNOWN baseline (hand info unreadable)")
            gate = await confirm_gate(state, confirm, (
                f"What this does: raises the motor current ceiling from "
                f"{baseline} to {ma} mA — more stall force, more heat; "
                "temperatures are telemetered (1 Hz) but not enforced as a "
                "cutoff. Lowering below a known baseline never needs "
                "confirmation."))
            if gate:
                return gate
        result = await backend.post("/api/control/max_current", {"ma": ma})
        return await with_state(
            state, {"ok": True, "control": result.get("control")})

    @mcp.tool(annotations=_ann("Park the hand (neutral + torque off)",
                               idempotent=True))
    async def orca_park(
        neutral: Annotated[bool, Field(
            description="move to the neutral pose before de-energizing; "
                        "false = just disable torque where it stands")] = True,
    ) -> dict:
        """Leave the hand safe: neutral pose, dwell for the move, then
        disable torque. The standard way to end a motion session. Refuses to
        yank control from a running operation or an engaged teleop session —
        stop those first."""
        try:
            op = (await backend.get("/api/operation")).get("operation")
        except BackendError:
            op = None
        if op and op.get("state") in ACTIVE_OP_STATES:
            return refusal(
                f"operation '{op.get('kind')}' is active "
                f"(state={op.get('state')}) — parking would fight it. Stop "
                "it (orca_control_operation(action='stop')) or wait "
                "(orca_get_operation(wait_s=...)) first.")
        try:
            session = (await backend.get("/api/teleop/state")).get("session")
        except BackendError:
            session = None
        if session and session.get("engaged"):
            return refusal(
                "teleop is engaged — most likely a human operator. If the "
                "user wants to park, orca_teleop_stop first.")
        status = await backend.get("/api/status")
        if not status.get("torque_enabled"):
            return await with_state(state, {
                "ok": True, "already_parked": True,
                "note": "torque is already off — the hand is limp."})
        moved = False
        note = None
        if neutral:
            # The torque-off half of park is de-escalation and always runs;
            # the neutral MOVE must not escape --require-mock on real
            # hardware (torque may have been enabled by a human in the UI).
            real = True
            try:
                real = await state.is_real()
            except BackendError:
                pass
            if state.settings.require_mock and real:
                note = ("--require-mock: skipped the neutral move on REAL "
                        "hardware; disabling torque in place (call with "
                        "neutral=false to silence this note)")
            else:
                await backend.post("/api/joints/neutral")
                moved = True
                # The interpolated move's completion isn't observable over
                # REST; a fixed dwell covers the ~0.5 s motion with margin.
                await asyncio.sleep(1.5)
        await backend.post("/api/torque/disable")
        out = {"ok": True, "neutral": moved, "torque_disabled": True}
        if note:
            out["note"] = note
        # Park is the tool whose claim most needs proving: with_state re-reads
        # torque from the backend, so `state.torque_enabled: false` is
        # observed rather than asserted (and it adds no reminder once off).
        return await with_state(state, out)

    # ----- motion ----------------------------------------------------------------

    @mcp.tool(annotations=_ann("Set joint targets", destructive=True,
                               idempotent=True))
    async def orca_set_joints(
        angles: Annotated[dict[str, float], Field(
            min_length=1,
            description="joint name → target angle in DEGREES (joint names "
                        "and ROMs from orca_get_hand_info)")],
        clamp: Annotated[bool, Field(
            description="true: clamp out-of-ROM values and report; false: "
                        "reject the call instead. Raw out-of-ROM values are "
                        "never forwarded")] = True,
        verify: Annotated[bool, Field(
            description="watch joints.measured until converged")] = True,
        verify_timeout_s: Annotated[float, Field(ge=0.5, le=10)] = 2.0,
        tolerance_deg: Annotated[float, Field(ge=0.5, le=20)] = 3.0,
    ) -> dict:
        """Move individual joints (requires torque enabled + manual
        control). The backend does NOT range-check, so this tool clamps to
        each joint's ROM. For whole-hand poses prefer orca_apply_pose; for
        trajectories use orca_start_operation(kind='replay')."""
        gate = await mock_gate(state)
        if gate:
            return gate
        summary = await state.hand_summary()
        roms = summary["roms"]
        unknown = sorted(set(angles) - set(roms))
        if unknown:
            raise BackendError(
                f"unknown joints: {unknown} — valid joints: "
                f"{sorted(roms)}")
        applied: dict[str, float] = {}
        clamped: dict[str, dict] = {}
        for joint, value in angles.items():
            lo, hi = roms[joint]
            sent = min(max(float(value), lo), hi)
            if sent != float(value):
                if not clamp:
                    raise BackendError(
                        f"{joint}={value} is outside its ROM [{lo}, {hi}] "
                        "(degrees). Fix the value, or call with clamp=true "
                        f"to send {sent}.")
                clamped[joint] = {"requested": float(value), "applied": sent,
                                  "rom": [lo, hi]}
            applied[joint] = sent
        notes = []
        values = list(angles.values())
        if (any(v != 0 for v in values)
                and all(abs(v) <= 3.5 for v in values)
                and any(roms[j][1] - roms[j][0] > 20 for j in angles)):
            notes.append(
                "all requested values are within ±3.5 while these joints' "
                "ROMs span >20° — this API takes DEGREES; the values look "
                "like radians")
        now = time.monotonic()
        state.set_joints_times = [
            t for t in state.set_joints_times if now - t <= 5.0] + [now]
        if len(state.set_joints_times) > 10:
            notes.append(
                "streaming targets call-by-call is lossy (backend coalesces "
                "latest-wins at 50 Hz) — for trajectories record once and "
                "use orca_start_operation(kind='replay')")
        await backend.post("/api/joints/target", {"angles": applied})
        verification = None
        if verify:
            verification = await telemetry.watch_convergence(
                backend.url, applied, verify_timeout_s, tolerance_deg)
        payload: dict = {"ok": True, "applied": applied}
        if clamped:
            payload["clamped"] = clamped
        if notes:
            payload["notes"] = notes
        payload["verification"] = verification
        return await with_state(state, payload)

    @mcp.tool(annotations=_ann("Apply a named pose", destructive=True,
                               idempotent=True))
    async def orca_apply_pose(
        name: Annotated[str, Field(
            pattern=NAME_PATTERN,
            description="builtin pose (open, fist, peace, pinch, point), a "
                        "user pose, or 'neutral'")],
        verify: Annotated[bool, Field(
            description="watch joints.measured until converged")] = True,
        verify_timeout_s: Annotated[float, Field(ge=0.5, le=10)] = 3.0,
        tolerance_deg: Annotated[float, Field(ge=0.5, le=20)] = 3.0,
    ) -> dict:
        """Interpolated whole-hand move (~0.5 s) to a named pose (requires
        torque enabled + manual control). 'neutral' resolves to a saved pose
        of that name if one exists, else the config-defined safe pose.
        orca_list_library lists the available names."""
        gate = await mock_gate(state)
        if gate:
            return gate
        try:
            result = await backend.post(f"/api/poses/{name}/apply")
            angles = result.get("angles") or {}
        except BackendError as e:
            if "no pose named" not in str(e):
                raise
            if name == "neutral":
                # No saved pose shadows the name: fall back to the
                # config-defined neutral (matches backend resolution order).
                await backend.post("/api/joints/neutral")
                angles = dict((await state.hand_summary())["neutral"])
            else:
                raise BackendError(
                    f"{e} — orca_list_library shows available poses") from e
        verification = None
        if verify and angles:
            verification = await telemetry.watch_convergence(
                backend.url, angles, verify_timeout_s, tolerance_deg)
        return await with_state(state, {
            "ok": True, "name": name, "angles": angles,
            "verification": verification})

    # ----- library writes ----------------------------------------------------------

    @mcp.tool(annotations=_ann("Save or capture a pose", destructive=True,
                               idempotent=True))
    async def orca_save_pose(
        name: Annotated[str, Field(pattern=NAME_PATTERN)],
        angles: Annotated[dict[str, float] | None, Field(
            description="joint → degrees; omit to CAPTURE the hand's "
                        "current measured pose instead (needs encoders)")]
        = None,
    ) -> dict:
        """Save a named pose from explicit angles, or capture the current
        physical pose when angles is omitted. Overwrites an existing user
        pose of the same name silently; user poses shadow builtins."""
        gate = await mock_gate(state)
        if gate:
            return gate
        if angles is None:
            try:
                result = await backend.post("/api/poses/capture",
                                            {"name": name})
            except BackendError as e:
                if "capture needs encoders" in str(e):
                    raise BackendError(
                        f"{e} — pass explicit angles instead") from e
                raise
            return {"ok": True, "captured": True, **result}
        await backend.put(f"/api/poses/{name}", {"angles": angles})
        return {"ok": True, "name": name, "angles": angles}

    @mcp.tool(annotations=_ann("Delete a pose or trajectory",
                               destructive=True, idempotent=True))
    async def orca_delete_asset(
        kind: Literal["pose", "trajectory"],
        name: Annotated[str, Field(pattern=NAME_PATTERN)],
    ) -> dict:
        """Delete a user pose or a recorded trajectory from the library
        (builtin poses cannot be deleted). Not undoable."""
        gate = await mock_gate(state)
        if gate:
            return gate
        path = ("/api/poses/" if kind == "pose"
                else "/api/trajectories/") + name
        await backend.delete(path)
        return {"ok": True, "deleted": {"kind": kind, "name": name}}

    # ----- long-running operations ---------------------------------------------------

    @mcp.tool(annotations=_ann("Start an operation", destructive=True))
    async def orca_start_operation(
        kind: Literal["replay", "demo", "record", "calibrate", "tension"],
        name: Annotated[str | None, Field(
            pattern=NAME_PATTERN,
            description="trajectory (replay), demo name (demo), or NEW "
                        "trajectory name (record); required for those "
                        "kinds")] = None,
        speed: Annotated[float, Field(
            description="replay only; one of 0.5, 1.0, 2.0",
            json_schema_extra={"enum": [0.5, 1.0, 2.0]})] = 1.0,
        loop: Annotated[bool, Field(
            description="replay/demo: run until stopped — prefer cycles for "
                        "unattended runs")] = False,
        cycles: Annotated[int, Field(ge=1, le=10,
                                     description="demo only")] = 1,
        mode: Annotated[Literal["continuous", "waypoints"], Field(
            description="record only")] = "continuous",
        frequency: Annotated[float, Field(ge=1, le=60,
                                          description="record only, Hz")] = 50.0,
        joints: Annotated[list[str] | None, Field(
            description="calibrate only: subset of joints (null = all)")]
        = None,
        confirm: Annotated[bool, Field(
            description="required for calibrate/tension on real hardware; "
                        "ignored on mock")] = False,
    ) -> dict:
        """Start a long-running operation; returns a snapshot immediately —
        then poll/wait with orca_get_operation(wait_s=...). One operation at
        a time; needs manual control (replay/demo also need torque).

        record: DISABLES torque and takes control; a human physically poses
        the hand. Finish with orca_send_operation_input(value='save') to
        STOP AND SAVE — orca_control_operation(action='stop') or orca_estop
        aborts WITHOUT saving."""
        gate = await mock_gate(state)
        if gate:
            return gate
        if kind in ("replay", "demo", "record") and not name:
            raise BackendError(
                f"kind '{kind}' requires name= (orca_list_library shows "
                "trajectories and demos)")
        if kind == "replay" and speed not in (0.5, 1.0, 2.0):
            raise BackendError(
                f"speed={speed} is not supported — the backend accepts "
                "exactly 0.5, 1.0, or 2.0")
        if kind == "calibrate":
            gate = await confirm_gate(state, confirm, CALIBRATE_WHAT)
        elif kind == "tension":
            gate = await confirm_gate(state, confirm, TENSION_WHAT)
        if gate:
            return gate
        params: dict = {}
        if kind == "replay":
            params = {"name": name, "speed": speed, "loop": loop}
        elif kind == "demo":
            params = {"name": name, "loop": loop, "cycles": cycles}
        elif kind == "record":
            params = {"name": name, "mode": mode, "frequency": frequency}
        elif kind == "calibrate" and joints:
            params = {"joints": joints}
        snap = (await backend.post(f"/api/operation/{kind}/start",
                                   {"params": params})).get("operation")
        payload: dict = {"ok": True, "operation": snap}
        if kind == "record":
            payload["important"] = (
                "record disabled torque and owns control; finish with "
                "orca_send_operation_input(value='save') — a plain stop or "
                "e-stop ABORTS WITHOUT SAVING")
        return await with_state(state, payload)

    @mcp.tool(annotations=_ann("Stop/pause/resume operation",
                               destructive=True, idempotent=True))
    async def orca_control_operation(
        action: Literal["stop", "pause", "resume"],
    ) -> dict:
        """Control the running operation. Stopping a 'record' DISCARDS the
        recording (use orca_send_operation_input(value='save') to keep it);
        pause/resume apply to replay/demo playback."""
        if action == "resume":
            # stop/pause are de-escalation; resume RESTARTS motion.
            gate = await mock_gate(state)
            if gate:
                return gate
        result = await backend.post(f"/api/operation/{action}")
        return {"ok": True, "action": action,
                "stopped": result.get("stopped")}

    @mcp.tool(annotations=_ann("Answer an operation prompt"))
    async def orca_send_operation_input(
        value: Annotated[str, Field(
            description="answer to the operation's awaiting.prompt; for "
                        "record use 'save' to stop-and-save")],
    ) -> dict:
        """Answer an operation parked in 'awaiting_input' (see
        orca_get_operation → awaiting.prompt/options), or stop-and-save a
        running recording with value='save'."""
        # Input to a running record is exempt from --require-mock: record
        # never moves motors (torque is disabled at start), and gating
        # 'save' while stop stays ungated would push agents toward the
        # DESTRUCTIVE way of ending a human's recording.
        exempt = False
        try:
            op = (await backend.get("/api/operation")).get("operation")
            exempt = bool(op and op.get("kind") == "record"
                          and op.get("state") in ACTIVE_OP_STATES)
        except BackendError:
            pass
        if not exempt:
            gate = await mock_gate(state)
            if gate:
                return gate
        try:
            await backend.post("/api/operation/input", {"value": value})
        except BackendError as e:
            raise BackendError(
                f"{e} — only an operation in awaiting_input (or a running "
                "record) accepts input; check orca_get_operation") from e
        return {"ok": True}

    # ----- tactile -----------------------------------------------------------------

    @mcp.tool(annotations=_ann("Configure tactile sensing", idempotent=True))
    async def orca_configure_tactile(
        mode: Annotated[Literal["resultant", "taxels", "combined"] | None,
                        Field(description="what the tactile stream carries: "
                              "resultant → tactile.forces, taxels → "
                              "tactile.taxels, combined → both")] = None,
        zero: Annotated[bool, Field(
            description="capture a new zero baseline — only while NOTHING "
                        "touches the fingertips")] = False,
        zero_samples: Annotated[int, Field(ge=1, le=2000)] = 100,
        clear_zero: Annotated[bool, Field(
            description="clear the stored zero offsets")] = False,
    ) -> dict:
        """Configure tactile streaming and baseline in one call (set mode,
        zero, and/or clear_zero). No motion; requires tactile capability."""
        gate = await mock_gate(state)
        if gate:
            return gate
        if zero and clear_zero:
            raise BackendError("zero and clear_zero are mutually exclusive")
        if mode is None and not zero and not clear_zero:
            raise BackendError(
                "nothing to do — set mode, zero=true, or clear_zero=true")
        applied: dict = {}
        if mode is not None:
            await backend.post("/api/tactile/mode", {"mode": mode})
            applied["mode"] = mode
        if zero:
            await backend.post("/api/tactile/zero",
                               {"num_samples": zero_samples})
            applied["zeroed_samples"] = zero_samples
        if clear_zero:
            await backend.post("/api/tactile/clear_zero")
            applied["cleared_zero"] = True
        return {"ok": True, "applied": applied}

    # ----- teleoperation --------------------------------------------------------------

    @mcp.tool(annotations=_ann("Start teleop (preview)"))
    async def orca_teleop_start(
        source: Literal["mediapipe", "manus", "avp", "synthetic"],
        config: Annotated[dict | None, Field(
            description="optional source config: camera_index, zmq_addr, "
                        "avp_ip, retargeter, rate, preview (bool — publish "
                        "camera frames for orca_get_camera_preview; "
                        "mediapipe only)")] = None,
    ) -> dict:
        """Start a teleop session in PREVIEW: the tracker runs and streams
        ghost targets, but the hand does NOT move until orca_teleop_engage.
        Inspect with orca_get_camera_preview and
        orca_read_telemetry(['teleop.targets'])."""
        gate = await mock_gate(state)
        if gate:
            return gate
        result = await backend.post("/api/teleop/start", {
            "source": source, "mode": "managed", "config": config or {}})
        return {
            "ok": True, "session": result.get("session"),
            "note": ("PREVIEW — the hand does not move until "
                     "orca_teleop_engage"),
        }

    @mcp.tool(annotations=_ann("ENGAGE teleop (hand follows tracking)",
                               destructive=True, idempotent=True))
    async def orca_teleop_engage(
        confirm: Annotated[bool, Field(
            description="required on real hardware; ignored on mock")]
        = False,
        ramp_s: Annotated[float | None, Field(
            ge=0, le=10,
            description="blend-in ramp seconds (backend default when "
                        "omitted)")] = None,
    ) -> dict:
        """Engage teleop: the physical hand starts mirroring the tracked
        human hand (ROM-clamped, ramped in, staleness-watchdogged). Needs an
        active preview session and torque enabled. Only engage when the user
        asked — a human is usually on the other end."""
        gate = await mock_gate(state)
        if gate:
            return gate
        gate = await confirm_gate(state, confirm, ENGAGE_WHAT)
        if gate:
            return gate
        body = {"ramp_s": ramp_s} if ramp_s is not None else None
        result = await backend.post("/api/teleop/engage", body)
        return await with_state(
            state, {"ok": True, "session": result.get("session")})

    @mcp.tool(annotations=_ann("Stop/disengage teleop", idempotent=True))
    async def orca_teleop_stop(
        action: Literal["stop", "disengage"] = "stop",
    ) -> dict:
        """'disengage' drops back to safe preview (session keeps running);
        'stop' ends the session entirely and releases control ownership
        (needed before manual motion or operations)."""
        if action == "disengage":
            result = await backend.post("/api/teleop/disengage")
            return {"ok": True, "session": result.get("session")}
        result = await backend.post("/api/teleop/stop")
        return {"ok": True, "stopped": result.get("stopped")}
