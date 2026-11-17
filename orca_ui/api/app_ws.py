"""The app link (``/ws/app``): where a running app connects with its token.

Separate from the browser's ``/ws``, which is an unauthenticated read
protocol; this one is an authenticated producer. The endpoint only parses
frames and hands them to :class:`AppSessions`. Sends can come from REST and
watchdog threads, so :class:`AppLink` schedules them onto the event loop.
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from orca_ui.hand.app import protocol

logger = logging.getLogger(__name__)


class AppLink:
    """Thread-safe handle on the connected app."""

    def __init__(self, websocket: WebSocket, loop: asyncio.AbstractEventLoop):
        self._websocket = websocket
        self._loop = loop

    def send_json(self, message: dict) -> None:
        payload = json.dumps(message, separators=(",", ":"))
        asyncio.run_coroutine_threadsafe(self._send(payload), self._loop)

    async def _send(self, payload: str) -> None:
        try:
            await self._websocket.send_text(payload)
        except Exception:
            logger.debug("app link send failed", exc_info=True)

    def close(self) -> None:
        asyncio.run_coroutine_threadsafe(self._close(), self._loop)

    async def _close(self) -> None:
        try:
            await self._websocket.close()
        except Exception:
            pass


def build_app_ws_router(apps) -> APIRouter:
    router = APIRouter()

    @router.websocket("/ws/app")
    async def app_link(websocket: WebSocket):
        await websocket.accept()
        link = AppLink(websocket, asyncio.get_running_loop())
        try:
            raw = await asyncio.wait_for(websocket.receive_text(),
                                         timeout=protocol.HELLO_TIMEOUT_S)
            hello = json.loads(raw)
            if hello.get("type") != protocol.MSG_HELLO:
                raise protocol.HelloRejected("the first frame must be hello",
                                             protocol.CLOSE_PROTO_MISMATCH)
            reply = apps.on_hello(hello.get("data") or {}, link)
        except protocol.HelloRejected as e:
            logger.info("app link refused: %s", e)
            await websocket.close(code=e.close_code, reason=str(e))
            return
        except (asyncio.TimeoutError, WebSocketDisconnect, ValueError, AttributeError):
            await websocket.close(code=protocol.CLOSE_PROTO_MISMATCH)
            return

        try:
            await websocket.send_text(json.dumps(
                {"type": protocol.MSG_HELLO_OK, "data": reply}, separators=(",", ":")))
            while True:
                raw = await websocket.receive_text()
                try:
                    message = json.loads(raw)
                    kind = message.get("type")
                    data = message.get("data") or {}
                except (ValueError, AttributeError):
                    continue
                if isinstance(data, dict):
                    apps.on_message(link, kind, data)
        except WebSocketDisconnect:
            pass
        except Exception:
            logger.debug("app link closed", exc_info=True)
        finally:
            apps.on_link_closed(link)

    return router
