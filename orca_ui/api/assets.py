"""3D hand asset serving: the processed URDF bundle.

The bundle under ``orca_ui/models/hand_v2/<side>/`` is produced by
``scripts/build_hand_bundle.py``. Endpoints degrade gracefully (404 with a
hint) when it hasn't been built.
"""

from __future__ import annotations

import json
import os

import yaml
from fastapi import APIRouter, FastAPI, HTTPException

from orca_ui.hand.service import HandService

HAND_V2_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                           "models", "hand_v2")
BUILD_HINT = ("3D hand bundle not found — build it with "
              "`uv run --group assets python scripts/build_hand_bundle.py`")


def mount_assets(app: FastAPI) -> None:
    if os.path.isdir(HAND_V2_DIR):
        from fastapi.staticfiles import StaticFiles
        app.mount("/assets/hand", StaticFiles(directory=HAND_V2_DIR),
                  name="hand-assets")


def build_router(service: HandService) -> APIRouter:
    router = APIRouter(prefix="/api")

    def _side_dir(side: str) -> str:
        return os.path.join(HAND_V2_DIR, side)

    @router.get("/model/metadata")
    def model_metadata():
        side = service.supervisor.config.type
        manifest_path = os.path.join(_side_dir(side), "manifest.json")
        if not os.path.isfile(manifest_path):
            raise HTTPException(status_code=404, detail=BUILD_HINT)
        with open(manifest_path) as f:
            manifest = json.load(f)
        return {
            "side": side,
            "urdf_url": f"/assets/hand/{side}/hand.urdf",
            "mesh_base_url": f"/assets/hand/{side}/meshes/",
            "manifest": manifest,
        }

    @router.get("/model/fingertips")
    def model_fingertips():
        side = service.supervisor.config.type
        path = os.path.join(_side_dir(side), "fingertips.yaml")
        if not os.path.isfile(path):
            raise HTTPException(status_code=404, detail=BUILD_HINT)
        with open(path) as f:
            return yaml.safe_load(f)

    @router.get("/model/sensor_mounts")
    def model_sensor_mounts():
        """Per-finger ``T_fingertip_sensor`` as a row-major 4x4 (meters):
        the tactile sensor's fixed pose in its distal link frame, from
        orca_core's mesh-registered kinematics data."""
        try:
            from orca_core.kinematics import HandKinematics
            side = service.supervisor.config.type
            mounts = HandKinematics.load(side).sensor_mounts
        except Exception as e:
            raise HTTPException(
                status_code=404,
                detail=f"sensor mounts unavailable from orca_core: {e}")
        return {
            finger: {"matrix": [[float(v) for v in row] for row in t.matrix]}
            for finger, t in mounts.items()
        }

    return router
