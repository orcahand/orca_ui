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

    @router.post("/control/gains")
    def control_gains(body: schemas.GainsRequest):
        guard(service.set_gains, body.kp, body.ki, body.correction_max_deg,
              body.i_clamp_deg)
        return {"ok": True, "control": service.control_state()}

    @router.post("/control/max_current")
    def control_max_current(body: schemas.MaxCurrentRequest):
        guard(service.set_max_current, body.ma)
        return {"ok": True, "control": service.control_state()}

    @router.post("/control/rebase")
    def control_rebase():
        guard(service.rebase)
        return {"ok": True}

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

    return router
