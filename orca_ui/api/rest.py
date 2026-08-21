"""REST routes. Handlers are sync ``def`` so blocking hardware calls run in
FastAPI's threadpool, never on the event loop."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from orca_ui.api import schemas
from orca_ui.hand.service import HandService, ServiceError
from orca_ui.hand.taxel_geometry import get_taxel_geometry


def build_router(service: HandService) -> APIRouter:
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

    @router.post("/reconnect")
    def reconnect():
        service.supervisor.request_reconnect()
        return {"ok": True}

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

    @router.post("/control/rebase")
    def control_rebase():
        guard(service.rebase)
        return {"ok": True}

    # ----- direct motor control (advanced diagnostics) ---------------------------

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
