"""FastAPI app factory: wires the hand service, stream hub, telemetry, and
API routers together. Hardware I/O lives on threads; asyncio only broadcasts."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import threading
import time

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse

from orca_ui.settings import UiSettings
from orca_ui.streaming import topics as T
from orca_ui.streaming.hub import StreamHub

logger = logging.getLogger(__name__)

WEBUI_DIR = os.path.join(os.path.dirname(__file__), "webui")


def create_app(settings: UiSettings) -> FastAPI:
    from orca_ui.api.assembly import build_router as build_assembly_router
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
    # The bench finds its own motors: with nothing connected it scans the bus
    # and adopts what answers. Not in mock mode, whose motors are the config's
    # by construction.
    auto_adopt = None
    if settings.bench and not settings.mock:
        from orca_ui.bench import BenchAutoAdopt
        auto_adopt = BenchAutoAdopt(service)

    idle_exit = None
    if settings.exit_on_close and settings.open_browser:
        idle_exit = IdleExit(
            clients=hub.client_count,
            busy=lambda: operations.active() or (teleop is not None and teleop.active()),
        )

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        from orca_ui.assembly_assets import prepare_assembly_models
        await asyncio.to_thread(prepare_assembly_models)
        service.start()
        telemetry.start()
        if auto_adopt is not None:
            auto_adopt.start()
        if idle_exit is not None:
            idle_exit.start()
        broadcaster = asyncio.create_task(hub.broadcaster())
        try:
            yield
        finally:
            broadcaster.cancel()
            if idle_exit is not None:
                idle_exit.shutdown()
            if auto_adopt is not None:
                auto_adopt.shutdown()
            # Teleop first: no targets may race into a dying stack.
            if teleop is not None:
                teleop.shutdown()
            installer.shutdown()
            operations.shutdown()
            telemetry.stop()
            service.stop()

    app = FastAPI(title="ORCA Motor Bench" if settings.bench else "ORCA Hand Console",
                  version="0.2.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.service = service
    app.state.hub = hub
    app.state.operations = operations
    app.state.teleop = teleop
    app.state.teleop_installer = installer
    app.state.telemetry = telemetry

    @app.post("/api/quit")
    def quit_server():
        """Stop the server from the page — the same orderly shutdown as
        Ctrl+C in the terminal: the run is refused, the hand is released."""
        if operations.active():
            raise HTTPException(status_code=409,
                                detail="a run is in progress — stop it first")
        if teleop is not None and teleop.active():
            raise HTTPException(status_code=409,
                                detail="teleop is active — stop it first")
        logger.info("quit requested from the page — shutting down")
        request_shutdown()
        return {"ok": True}

    app.include_router(build_rest_router(service, telemetry))
    app.include_router(build_assets_router(service))
    app.include_router(build_assembly_router())
    app.include_router(build_ws_router(service, hub))
    if teleop is not None:
        from orca_ui.api.teleop_ws import build_teleop_ws_router
        app.include_router(build_teleop_ws_router(teleop))
    # Order matters: /assets/hand (bundle) must register before the frontend's
    # /assets mount so the more specific prefix wins.
    mount_assets(app)
    _mount_webui(app, bench=settings.bench)
    return app


def request_shutdown() -> None:
    """Ask uvicorn to stop the way Ctrl+C does, so the lifespan teardown runs
    and the hand is released on the way out."""
    import signal
    import threading

    # From a request handler the signal must land on the main thread; a
    # short delay lets the HTTP reply go out first.
    threading.Timer(0.3, lambda: os.kill(os.getpid(), signal.SIGINT)).start()


class IdleExit(threading.Thread):
    """Exit when the browser is gone.

    The server is a tool that opened its own window; once that window — and
    every other tab on it — has been closed for ``GRACE_S``, the terminal
    should not need a Ctrl+C. A reload or a brief network blip is shorter
    than the grace. Never fires while an operation or teleop is active (a
    long run keeps going with the tab closed), and never before a browser
    has connected at least once, so a slow browser launch is not mistaken
    for a closed one.
    """

    GRACE_S = 10.0
    POLL_S = 1.0

    def __init__(self, clients, busy):
        super().__init__(name="IdleExit", daemon=True)
        self._clients = clients
        self._busy = busy
        self._stop = threading.Event()

    def shutdown(self) -> None:
        self._stop.set()

    def run(self) -> None:
        seen_client = False
        empty_since: float | None = None
        while not self._stop.wait(self.POLL_S):
            if self._clients() > 0:
                seen_client = True
                empty_since = None
                continue
            if not seen_client or self._busy():
                empty_since = None
                continue
            now = time.monotonic()
            if empty_since is None:
                empty_since = now
            elif now - empty_since >= self.GRACE_S:
                logger.info("browser closed — shutting down (start with "
                            "--keep-running to stay up without a page)")
                request_shutdown()
                return


def _mount_webui(app: FastAPI, bench: bool = False) -> None:
    """Serve the built frontend, or a clear hint when it hasn't been built.

    Two pages share the bundle: the console (index.html) and the motor bench
    (bench.html). Which one ``/`` is depends on the tool that launched the
    server; the other stays reachable at ``/console`` or ``/bench``.
    """
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

    bench_html = os.path.join(WEBUI_DIR, "bench.html")
    has_bench = os.path.isfile(bench_html)
    home = bench_html if bench and has_bench else index_html

    # SPA fallback: any non-API path serves the home page so client-side
    # routes work; the two named pages pick the other entry explicitly.
    @app.get("/{path:path}")
    def spa(path: str):
        route = path.strip("/")
        if route == "bench" and has_bench:
            return FileResponse(bench_html, headers=no_cache)
        if route == "console":
            return FileResponse(index_html, headers=no_cache)
        candidate = os.path.realpath(os.path.join(WEBUI_DIR, path))
        if path and candidate.startswith(os.path.realpath(WEBUI_DIR) + os.sep) \
                and os.path.isfile(candidate):
            return FileResponse(candidate, headers=no_cache)
        return FileResponse(home, headers=no_cache)
