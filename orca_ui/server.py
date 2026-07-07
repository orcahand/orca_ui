"""FastAPI app factory.

Wires the hand service, streaming hub, API routers, and static mounts. The
heavy lifting lives in ``orca_ui.hand`` (hardware lifecycle), ``orca_ui.api``
(REST + WebSocket), and ``orca_ui.streaming`` (topic hub).
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

from orca_ui.settings import UiSettings

WEBUI_DIR = os.path.join(os.path.dirname(__file__), "webui")


def create_app(settings: UiSettings) -> FastAPI:
    app = FastAPI(title="ORCA UI", version="0.2.0")
    app.state.settings = settings

    @app.get("/api/status")
    def status():
        # Placeholder until the hand service lands.
        return {"state": "disconnected", "message": "hand service not yet wired"}

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
    app.mount("/assets", StaticFiles(directory=os.path.join(WEBUI_DIR, "assets")),
              name="webui-assets")

    # SPA fallback: any non-API path serves index.html so client-side routes work.
    @app.get("/{path:path}")
    def spa(path: str):
        candidate = os.path.join(WEBUI_DIR, path)
        if path and os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(index_html)
