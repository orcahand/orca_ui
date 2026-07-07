"""FastAPI app factory: wires the hand service, stream hub, telemetry, and
API routers together. Hardware I/O lives on threads; asyncio only broadcasts."""

from __future__ import annotations

import asyncio
import contextlib
import os

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

from orca_ui.settings import UiSettings
from orca_ui.streaming import topics as T
from orca_ui.streaming.hub import StreamHub

WEBUI_DIR = os.path.join(os.path.dirname(__file__), "webui")


def create_app(settings: UiSettings) -> FastAPI:
    from orca_ui.api.assets import build_router as build_assets_router
    from orca_ui.api.assets import mount_assets
    from orca_ui.api.rest import build_router as build_rest_router
    from orca_ui.api.ws import build_ws_router
    from orca_ui.hand.service import HandService
    from orca_ui.hand.telemetry import TelemetryService

    hub = StreamHub()
    service = HandService(
        settings,
        publish_status=lambda snapshot: hub.publish(T.STATUS, snapshot),
        publish_error=lambda message: hub.publish(T.ERROR, {"message": message}),
        publish_topic=hub.publish,
    )
    telemetry = TelemetryService(service, hub, settings)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        service.start()
        telemetry.start()
        broadcaster = asyncio.create_task(hub.broadcaster())
        try:
            yield
        finally:
            broadcaster.cancel()
            telemetry.stop()
            service.stop()

    app = FastAPI(title="ORCA UI", version="0.2.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.service = service
    app.state.hub = hub

    app.include_router(build_rest_router(service))
    app.include_router(build_assets_router(service))
    app.include_router(build_ws_router(service, hub))
    # Order matters: /assets/hand (bundle) must register before the frontend's
    # /assets mount so the more specific prefix wins.
    mount_assets(app)
    _mount_webui(app)
    return app


def _mount_webui(app: FastAPI) -> None:
    """Serve the built frontend, or a clear hint when it hasn't been built."""
    index_html = os.path.join(WEBUI_DIR, "index.html")

    if not os.path.isfile(index_html):
        @app.get("/")
        def webui_missing():
            return JSONResponse({
                "error": "frontend not built",
                "hint": "run `npm run build` in frontend/ (or `npm run dev` "
                        "there for a live dev server proxying to this backend)",
            }, status_code=503)
        return

    from fastapi.staticfiles import StaticFiles
    assets_dir = os.path.join(WEBUI_DIR, "assets")
    if os.path.isdir(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="webui-assets")

    # SPA fallback: any non-API path serves index.html so client-side routes work.
    @app.get("/{path:path}")
    def spa(path: str):
        candidate = os.path.realpath(os.path.join(WEBUI_DIR, path))
        if path and candidate.startswith(os.path.realpath(WEBUI_DIR) + os.sep) \
                and os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(index_html)
