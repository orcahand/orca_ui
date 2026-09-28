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

    from orca_ui.hand.operations import build_operation_manager

    hub = StreamHub()
    service = HandService(
        settings,
        publish_status=lambda snapshot: hub.publish(T.STATUS, snapshot),
        publish_error=lambda message: hub.publish(T.ERROR, {"message": message}),
        publish_topic=hub.publish,
    )
    operations = build_operation_manager(service, settings, hub.publish)
    service.attach_operation_manager(operations)
    teleop = None
    if settings.teleop_enabled:
        from orca_ui.hand.teleop import build_teleop_manager
        teleop = build_teleop_manager(service, settings, hub.publish)
        service.attach_teleop_manager(teleop)
    # Unconditional, and deliberately outside the teleop_enabled branch: this
    # is what makes teleop possible, so it has to exist precisely when the
    # manager does not. Refuses to run while a session is live (uv sync would
    # rewrite the venv under the running child).
    from orca_ui.hand.teleop.installer import TeleopInstaller
    installer = TeleopInstaller(
        publish=hub.publish,
        is_teleop_active=lambda: teleop is not None and teleop.active(),
    )
    service.attach_teleop_installer(installer)
    telemetry = TelemetryService(service, hub, settings)
    service.attach_telemetry(telemetry)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        service.start()
        telemetry.start()
        broadcaster = asyncio.create_task(hub.broadcaster())
        try:
            yield
        finally:
            broadcaster.cancel()
            # Teleop first: no targets may race into a dying stack.
            if teleop is not None:
                teleop.shutdown()
            installer.shutdown()
            operations.shutdown()
            telemetry.stop()
            service.stop()

    app = FastAPI(title="ORCA Hand Console", version="0.2.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.service = service
    app.state.hub = hub
    app.state.operations = operations
    app.state.teleop = teleop
    app.state.teleop_installer = installer
    app.state.telemetry = telemetry

    app.include_router(build_rest_router(service, telemetry))
    app.include_router(build_assets_router(service))
    app.include_router(build_ws_router(service, hub))
    if teleop is not None:
        from orca_ui.api.teleop_ws import build_teleop_ws_router
        app.include_router(build_teleop_ws_router(teleop))
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

    # index.html names the content-hashed bundle, so it must be revalidated on
    # every load or a rebuild goes unnoticed: without an explicit Cache-Control
    # browsers fall back to heuristic caching and a soft reload keeps running
    # the old JS. The ETag keeps the common case a 304.
    no_cache = {"Cache-Control": "no-cache"}

    # SPA fallback: any non-API path serves index.html so client-side routes work.
    @app.get("/{path:path}")
    def spa(path: str):
        candidate = os.path.realpath(os.path.join(WEBUI_DIR, path))
        if path and candidate.startswith(os.path.realpath(WEBUI_DIR) + os.sep) \
                and os.path.isfile(candidate):
            return FileResponse(candidate, headers=no_cache)
        return FileResponse(index_html, headers=no_cache)
