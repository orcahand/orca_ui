"""The teleop ingress WebSocket (``/ws/teleop``).

The producer side of teleop: the orca_teleop streamer child (or an external
streamer with the session token) connects here and pushes ``targets`` frames.
Deliberately separate from the browser ``/ws`` — that one is an
unauthenticated consumer protocol; this one is an authenticated producer.

The endpoint is a thin shim: parse frames, hand them to the TeleopManager.
Outbound messages (config/engaged/stop) can originate on REST threadpool or
watchdog threads, so :class:`ChildLink` schedules sends onto the event loop.
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from orca_ui.hand.teleop import protocol

logger = logging.getLogger(__name__)


class ChildLink:
    """Thread-safe handle the manager uses to talk to the connected child."""

    def __init__(self, websocket: WebSocket, loop: asyncio.AbstractEventLoop):
        self._websocket = websocket
        self._loop = loop

    def send_json(self, message: dict) -> None:
        payload = json.dumps(message, separators=(",", ":"))
        asyncio.run_coroutine_threadsafe(
            self._send(payload), self._loop)

    async def _send(self, payload: str) -> None:
        try:
            await self._websocket.send_text(payload)
        except Exception:
            logger.debug("teleop link send failed", exc_info=True)

    def close(self) -> None:
        asyncio.run_coroutine_threadsafe(self._close(), self._loop)

    async def _close(self) -> None:
        try:
            await self._websocket.close()
        except Exception:
            pass


def build_teleop_ws_router(teleop) -> APIRouter:
    router = APIRouter()

    @router.websocket("/ws/teleop")
    async def teleop_ingress(websocket: WebSocket):
        await websocket.accept()
        link = ChildLink(websocket, asyncio.get_running_loop())

        # First frame must be a valid hello, promptly.
        try:
            raw = await asyncio.wait_for(
                websocket.receive_text(), timeout=protocol.HELLO_TIMEOUT_S)
            hello = json.loads(raw)
            if hello.get("type") != protocol.MSG_HELLO:
                raise protocol.HelloRejected(
                    "first frame must be hello", protocol.CLOSE_PROTO_MISMATCH)
            hello_ok = teleop.ingress_connected(hello.get("data") or {}, link)
        except protocol.HelloRejected as e:
            logger.info("teleop ingress rejected: %s", e)
            await websocket.close(code=e.close_code, reason=str(e))
            return
        except (asyncio.TimeoutError, WebSocketDisconnect,
                ValueError, AttributeError):
            await websocket.close(code=protocol.CLOSE_PROTO_MISMATCH)
            return

        await websocket.send_text(json.dumps(
            {"type": protocol.MSG_HELLO_OK, "data": hello_ok},
            separators=(",", ":")))

        try:
            while True:
                raw = await websocket.receive_text()
                try:
                    message = json.loads(raw)
                    kind = message.get("type")
                    data = message.get("data") or {}
                except (ValueError, AttributeError):
                    continue
                if kind == protocol.MSG_TARGETS:
                    teleop.ingress_targets(data.get("angles") or {})
                elif kind == protocol.MSG_STATUS:
                    teleop.ingress_status(data)
                elif kind == protocol.MSG_LOG:
                    teleop.ingress_log(data)
                elif kind == protocol.MSG_PREVIEW:
                    teleop.ingress_preview(data)
                # unknown types are ignored (forward-compatible)
        except WebSocketDisconnect:
            pass
        except Exception:
            logger.debug("teleop ingress closed", exc_info=True)
        finally:
            teleop.ingress_disconnected(link)

    return router
