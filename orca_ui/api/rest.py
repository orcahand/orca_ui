"""REST routes. Handlers are sync ``def`` so blocking hardware calls run in
FastAPI's threadpool, never on the event loop."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from orca_ui.api import schemas
from orca_ui.hand.service import HandService, ServiceError
from orca_ui.hand.taxel_geometry import get_taxel_geometry


def build_router(service: HandService, telemetry=None) -> APIRouter:
    router = APIRouter(prefix="/api")

    def guard(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ServiceError as e:
            raise HTTPException(status_code=e.status_code, detail=str(e))

    # ----- status / info -----------------------------------------------------

    @router.get("/status")
    def status():
        return service.status()

    @router.get("/hand/info")
    def hand_info():
        return service.hand_info()

    @router.get("/stats")
    def stats():
        return service.stats()

    @router.get("/calibration/history")
    def calibration_history():
        from orca_ui.hand.calibration_log import read_runs
        config = service.supervisor.config
        path = getattr(config, "calibration_path", None)
        # Current sensor frame (anchor count, polarity, anchor pose) per
        # joint, so the browser can decode each run's raw hardstop magnet
        # counts into today's angles — the un-homed view that shows magnet
        # slip between sweeps.
        frame: dict = {}
        try:
            from orca_core.calibration import CalibrationResult
            from orca_core.hardware.sensing.constants import (
                joint_encoder_polarity_for_side,
            )
            cal = CalibrationResult.from_calibration_path(
                path, list(config.motor_ids))
            polarity = joint_encoder_polarity_for_side(str(config.type))
            for joint, jec in cal.joint_encoder_calibration_dict.items():
                rom = config.joint_roms_dict.get(joint)
                pol = polarity.get(joint)
                if rom is None or pol is None or \
                        jec.enc_at_anchor_count is None:
                    continue
                frame[joint] = {
                    "anchor_count": int(jec.enc_at_anchor_count),
                    "polarity": int(pol),
                    "anchor_angle_deg": float(rom[1]),
                }
        except Exception:
            pass  # sensors absent / no calibration yet: runs still served
        return {"runs": read_runs(path) if path else [], "frame": frame}

    # ----- usage stats -----------------------------------------------------

    def _usage_tracker():
        tracker = telemetry.usage_tracker() if telemetry is not None else None
        if tracker is None:
            raise HTTPException(status_code=503,
                                detail="usage stats unavailable")
        return tracker

    @router.get("/usage/stats")
    def usage_stats():
        return _usage_tracker().snapshot()

    @router.post("/usage/session")
    def usage_new_session(body: schemas.UsageSessionBody | None = None):
        label = body.label if body is not None else None
        return {"ok": True, "id": _usage_tracker().new_session(label)}

    @router.put("/usage/session/{session_id}")
    def usage_rename_session(session_id: str, body: schemas.UsageSessionBody):
        if not _usage_tracker().rename_session(session_id, body.label or ""):
            raise HTTPException(status_code=404, detail="no such session")
        return {"ok": True}

    @router.delete("/usage/session/{session_id}")
    def usage_delete_session(session_id: str):
        if not _usage_tracker().delete_session(session_id):
            raise HTTPException(status_code=404, detail="no such session")
        return {"ok": True}

    @router.post("/usage/reset")
    def usage_reset():
        _usage_tracker().reset()
        return {"ok": True}

    @router.get("/ports")
    def ports():
        import serial.tools.list_ports
        from orca_core.constants import KNOWN_VIDS

        vid_labels = {}
        for kind, vids in KNOWN_VIDS.items():
            for vid in vids if isinstance(vids, (list, tuple)) else [vids]:
                vid_labels.setdefault(vid, kind)

        out = []
        for p in serial.tools.list_ports.comports():
            if p.vid is None:
                continue
            out.append({
                "device": p.device,
                "description": p.description,
                "kind": vid_labels.get(p.vid),
            })
        out.sort(key=lambda x: (x["kind"] is None, x["device"]))
        return out

    @router.get("/models")
    def models():
        return service.models()

    @router.post("/model/select")
    def model_select(body: schemas.ModelSelectRequest):
        """Pin the hand config by name (or null = back to auto-detection).

        The hands that need this are the ones detection cannot name: without
        an ORCA controller board to answer, every hand resolves to the
        default model whatever it actually is.
        """
        return guard(service.select_model, body.name, body.version)

    @router.post("/reconnect")
    def reconnect():
        # Also lifts a /disconnect hold — this is the way back from one.
        return {"ok": True, "status": service.reconnect()}

    @router.post("/disconnect")
    def disconnect():
        """Close the session and leave the ports free (torque off).

        Not the same as the connect ladder losing the hand: nothing
        reconnects until /reconnect asks it to.
        """
        return {"ok": True, "status": guard(service.disconnect)}

    # ----- operations / e-stop ----------------------------------------------------

    def _manager():
        manager = service.operation_manager
        if manager is None:
            raise HTTPException(status_code=503,
                                detail="operations unavailable")
        return manager

    @router.get("/operation")
    def operation_snapshot():
        return {"operation": _manager().snapshot()}

    @router.get("/operation/log")
    def operation_log():
        return _manager().log_payload()

    @router.post("/operation/{kind}/start")
    def operation_start(kind: str,
                        body: schemas.OperationStartRequest | None = None):
        params = body.params if body else {}
        return {"operation": guard(_manager().start, kind, params)}

    @router.post("/operation/stop")
    def operation_stop():
        stopped = _manager().stop()
        return {"ok": True, "stopped": stopped}

    @router.post("/operation/pause")
    def operation_pause():
        guard(_manager().pause)
        return {"ok": True}

    @router.post("/operation/resume")
    def operation_resume():
        _manager().resume()
        return {"ok": True}

    @router.post("/operation/input")
    def operation_input(body: schemas.OperationInputRequest):
        guard(_manager().send_input, body.value)
        return {"ok": True}

    @router.post("/estop")
    def estop():
        # Never raises; always 200 with a report of what was actioned.
        return {"ok": True, "report": service.estop()}

    # ----- teleoperation ------------------------------------------------------------

    def _teleop():
        teleop = service.teleop_manager
        if teleop is None:
            raise HTTPException(status_code=503, detail="teleop unavailable")
        return teleop

    @router.get("/teleop/state")
    def teleop_state():
        return {"session": _teleop().snapshot()}

    @router.get("/teleop/sources")
    def teleop_sources():
        return _teleop().sources()

    @router.post("/teleop/cameras/scan")
    def teleop_scan_cameras():
        # Slow (probes each device through the streamer child); the frontend
        # shows a scanning state. 409 while a session owns the camera.
        return guard(_teleop().scan_cameras)

    @router.get("/teleop/log")
    def teleop_log():
        return _teleop().log_payload()

    @router.post("/teleop/start")
    def teleop_start(body: schemas.TeleopStartRequest):
        return guard(_teleop().start, body.source, body.mode, body.config)

    @router.post("/teleop/stop")
    def teleop_stop():
        stopped = _teleop().stop()
        return {"ok": True, "stopped": stopped}

    @router.post("/teleop/engage")
    def teleop_engage(body: schemas.TeleopEngageRequest | None = None):
        ramp_s = body.ramp_s if body else None
        return {"session": guard(_teleop().engage, ramp_s)}

    @router.post("/teleop/disengage")
    def teleop_disengage():
        return {"session": guard(_teleop().disengage)}

    @router.post("/teleop/config")
    def teleop_config(body: schemas.TeleopConfigRequest):
        return {"config": guard(_teleop().set_config, body.config)}

    # ----- teleop install -----------------------------------------------------------
    # Not behind _teleop(): that 503s when there is no teleop MANAGER
    # (--no-teleop), which is unrelated to whether the orca_teleop checkout
    # exists — and the install is what fixes the latter.

    def _installer():
        installer = service.teleop_installer
        if installer is None:
            raise HTTPException(status_code=503, detail="installer unavailable")
        return installer

    @router.get("/teleop/install")
    def teleop_install_state(path: str | None = None):
        from orca_ui.hand.teleop.installer import inspect_target

        installer = _installer()
        state = installer.snapshot()
        state["target"] = inspect_target(path or state["default_path"])
        return state

    @router.get("/teleop/install/log")
    def teleop_install_log():
        return _installer().log_payload()

    @router.post("/teleop/install")
    def teleop_install(body: schemas.TeleopInstallRequest | None = None):
        from orca_ui.hand.teleop.installer import InstallError

        try:
            return _installer().start(body.path if body else None)
        except InstallError as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    @router.post("/teleop/install/cancel")
    def teleop_install_cancel():
        _installer().cancel()
        return {"ok": True}

    # ----- motor control -------------------------------------------------------

    @router.post("/torque/enable")
    def torque_enable(_body: schemas.TorqueRequest | None = None):
        return guard(service.enable_torque)

    @router.post("/torque/disable")
    def torque_disable(_body: schemas.TorqueRequest | None = None):
        guard(service.disable_torque)
        return {"ok": True}

    @router.post("/joints/target")
    def joints_target(body: schemas.JointTargets):
        guard(service.set_targets, body.angles)
        return {"ok": True}

    @router.post("/joints/neutral")
    def joints_neutral():
        guard(service.go_neutral)
        return {"ok": True}

    @router.post("/joints/calibrate")
    def joints_calibrate(body: schemas.JointCalibrateRequest):
        return guard(service.calibrate_joint_manual, body.joint, body.angle_deg)

    @router.get("/control/gains")
    def control_gains_state():
        return guard(service.gains_state)

    @router.post("/control/gains")
    def control_gains(body: schemas.GainsRequest):
        guard(service.set_gains, body.kp, body.ki, body.correction_max_deg,
              body.joints)
        return {"ok": True, "control": service.control_state()}

    @router.post("/control/gains/reset")
    def control_gains_reset(body: schemas.GainsResetRequest | None = None):
        guard(service.reset_gains, body.joints if body else None)
        return {"ok": True, "control": service.control_state()}

    @router.post("/control/max_current")
    def control_max_current(body: schemas.MaxCurrentRequest):
        guard(service.set_max_current, body.ma)
        return {"ok": True, "control": service.control_state()}

    @router.post("/control/rom_frame")
    def control_rom_frame(body: schemas.RomFrameRequest):
        return guard(service.set_rom_frame, body.mode)

    @router.post("/control/rebase")
    def control_rebase():
        guard(service.rebase)
        return {"ok": True}

    # ----- direct motor control (advanced diagnostics) ---------------------------

    @router.post("/motors/{motor_id}/reboot")
    def motor_reboot(motor_id: int):
        """Clear a latched hardware error. Comes back with torque off."""
        return guard(service.reboot_motor, motor_id)

    @router.get("/motors/direct")
    def motors_direct_snapshot():
        return guard(service.motor_snapshot)

    @router.post("/motors/direct/mode")
    def motors_direct_mode(body: schemas.DirectMotorModeRequest):
        return guard(service.set_direct_motor_mode, body.enabled)

    @router.post("/motors/direct/position")
    def motors_direct_position(body: schemas.DirectMotorPositionRequest):
        return guard(service.set_motor_position, body.id, body.position)

    # ----- poses / trajectories / demos --------------------------------------------

    @router.get("/poses")
    def poses_list():
        return {"poses": service.list_poses()}

    @router.put("/poses/{name}")
    def pose_save(name: str, body: schemas.PoseSaveRequest):
        guard(service.save_pose, name, body.angles)
        return {"ok": True}

    @router.delete("/poses/{name}")
    def pose_delete(name: str):
        guard(service.delete_pose, name)
        return {"ok": True}

    @router.post("/poses/{name}/apply")
    def pose_apply(name: str):
        return guard(service.apply_pose, name)

    @router.post("/poses/capture")
    def pose_capture(body: schemas.PoseCaptureRequest):
        return guard(service.capture_pose, body.name)

    @router.get("/trajectories")
    def trajectories_list():
        return {"trajectories": service.library.list_trajectories()}

    def _library_call(fn, *args, **kwargs):
        from orca_ui.library import LibraryError
        try:
            return fn(*args, **kwargs)
        except LibraryError as e:
            raise ServiceError(str(e), status_code=e.status_code)

    @router.get("/trajectories/{name}")
    def trajectory_get(name: str):
        return guard(_library_call, service.library.load_trajectory, name)

    @router.put("/trajectories/{name}")
    def trajectory_update(name: str, body: schemas.TrajectoryUpdateRequest):
        # Waypoint editor save: replace the waypoints of an existing
        # waypoint recording (optionally under a new name), each angle
        # clamped to its joint's ROM. Continuous recordings are sampled
        # motion — there is no meaningful per-frame hand edit.
        def apply():
            from datetime import datetime, timezone

            from orca_ui.library import WAYPOINTS

            data = _library_call(service.library.load_trajectory, name)
            meta = data.get("metadata") or {}
            if meta.get("type") != WAYPOINTS:
                raise ServiceError(
                    "only waypoint recordings are editable — continuous "
                    "recordings are sampled motion", status_code=409)
            joint_ids = list(meta.get("joint_ids")
                             or service.supervisor.config.joint_ids)
            if not body.waypoints:
                raise ServiceError("a trajectory needs at least one waypoint")
            roms = service.supervisor.config.joint_roms_dict
            clean = []
            for index, waypoint in enumerate(body.waypoints):
                if len(waypoint) != len(joint_ids):
                    raise ServiceError(
                        f"waypoint {index + 1}: expected {len(joint_ids)} "
                        f"joint values, got {len(waypoint)}")
                row = []
                for joint, value in zip(joint_ids, waypoint):
                    angle = float(value)
                    rom = roms.get(joint)
                    if rom is not None:
                        angle = min(max(angle, float(rom[0])), float(rom[1]))
                    row.append(round(angle, 3))
                clean.append(row)
            data["waypoints"] = clean
            meta["edited_at"] = datetime.now(
                timezone.utc).astimezone().isoformat(timespec="seconds")
            data["metadata"] = meta
            target = body.save_as or name
            _library_call(service.library.save_trajectory, target, data,
                          overwrite=target == name)
            return {"ok": True, "name": target, "frames": len(clean)}

        return guard(apply)

    @router.post("/trajectories/{name}/to_motor")
    def trajectory_to_motor(name: str,
                            body: schemas.TrajectoryToMotorRequest):
        # Translate a joint-space waypoint recording into raw motor
        # positions via the calibrated joint↔motor map. Refused without a
        # completed calibration — the map does not exist without one.
        def convert():
            import time as _time

            from orca_ui.library import MOTOR_WAYPOINTS, WAYPOINTS

            session = service.session
            if session is None:
                raise ServiceError("hand not connected", status_code=503)
            hand = session.hand
            if not getattr(hand, "calibrated", False):
                raise ServiceError(
                    "joint→motor translation needs a calibrated hand — "
                    "calibrate first", status_code=409)
            data = _library_call(service.library.load_trajectory, name)
            meta = data.get("metadata") or {}
            if meta.get("type") != WAYPOINTS:
                raise ServiceError(
                    "only joint waypoint recordings can be translated to "
                    "motor space", status_code=409)
            config = service.supervisor.config
            joint_ids = list(meta.get("joint_ids") or config.joint_ids)
            motor_ids = [int(m) for m in config.motor_ids]
            rows = []
            for index, waypoint in enumerate(data.get("waypoints") or []):
                pose = {j: float(v) for j, v in zip(joint_ids, waypoint)
                        if v is not None}
                motor_pos = hand._joint_to_motor_pos(pose)
                row = []
                for idx, motor_id in enumerate(motor_ids):
                    value = motor_pos[idx]
                    if value is None:
                        raise ServiceError(
                            f"waypoint {index + 1}: motor {motor_id} has no "
                            "calibrated joint↔motor mapping — recalibrate "
                            "that joint first", status_code=409)
                    row.append(round(float(value), 5))
                rows.append(row)
            if not rows:
                raise ServiceError("trajectory contains no waypoints")
            target = body.save_as or f"{name}_motor"
            _library_call(service.library.save_trajectory, target, {
                "metadata": {
                    "type": MOTOR_WAYPOINTS,
                    "motor_ids": motor_ids,
                    "hand_type": config.type,
                    "created_at": _time.strftime("%Y%m%d_%H%M%S"),
                    "translated_from": name,
                },
                "waypoints": rows,
            })
            return {"ok": True, "name": target, "frames": len(rows)}

        return guard(convert)

    @router.delete("/trajectories/{name}")
    def trajectory_delete(name: str):
        guard(service.delete_trajectory, name)
        return {"ok": True}

    @router.get("/demos")
    def demos_list():
        return {"demos": service.demos_listing()}

    # ----- tactile ---------------------------------------------------------------

    @router.post("/tactile/mode")
    def tactile_mode(body: schemas.TactileModeRequest):
        guard(service.set_tactile_mode, body.mode)
        return {"ok": True, "mode": body.mode}

    @router.post("/tactile/zero")
    def tactile_zero(body: schemas.ZeroRequest | None = None):
        num_samples = body.num_samples if body else 100
        guard(service.zero_tactile, num_samples)
        return {"ok": True}

    @router.post("/tactile/clear_zero")
    def tactile_clear_zero():
        guard(service.clear_tactile_zero)
        return {"ok": True}

    @router.get("/tactile/geometry")
    def tactile_geometry():
        return get_taxel_geometry(service.session)

    # ----- dev helpers (mock mode only) ------------------------------------------

    if service.settings.mock:
        from orca_ui.hand.sweep import JointSweeper

        sweeper = JointSweeper(service)
        service.attach_sweeper(sweeper)   # so estop can reach it

        @router.post("/mock/joint_sweep")
        def mock_joint_sweep(body: schemas.SweepRequest):
            if body.joint is None:
                sweeper.stop()
            else:
                guard(sweeper.start, body.joint, body.period_s)
            return {"ok": True, "sweeping": sweeper.active_joint}

    return router
