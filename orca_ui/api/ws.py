"""WebSocket endpoint: topic subscriptions + the hot slider-command path.

Protocol (JSON text frames, envelope ``{type, seq?, t?, data}``):

  client -> server
    {"type": "subscribe",   "data": {"topics": ["joints.measured", ...]}}
    {"type": "unsubscribe", "data": {"topics": [...]}}
    {"type": "cmd.joints.target", "data": {"angles": {"index_mcp": 42.5}}}

  server -> client: one message per topic update (see streaming.topics),
  plus {"type": "error", "data": {"message": ...}} for per-client failures.
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from orca_ui.hand.service import HandService, ServiceError
from orca_ui.streaming import topics as T
from orca_ui.streaming.hub import ClientConnection, StreamHub

logger = logging.getLogger(__name__)


def build_ws_router(service: HandService, hub: StreamHub) -> APIRouter:
    router = APIRouter()

    @router.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        await websocket.accept()
        client = ClientConnection(websocket)
        hub.register(client)
        sender = asyncio.create_task(client.sender_loop())
        try:
            # Immediate state so a fresh client renders without waiting.
            for topic in (T.STATUS, T.CONTROL_STATE):
                message = hub.snapshot_message(topic)
                if message:
                    await websocket.send_text(message)

            while True:
                raw = await websocket.receive_text()
                await _handle_message(websocket, client, raw)
        except WebSocketDisconnect:
            pass
        except Exception:
            logger.debug("websocket closed", exc_info=True)
        finally:
            hub.unregister(client)
            client.wake.set()
            sender.cancel()

    async def _handle_message(websocket: WebSocket, client: ClientConnection,
                              raw: str) -> None:
        try:
            message = json.loads(raw)
            kind = message.get("type")
            data = message.get("data") or {}
        except (ValueError, AttributeError):
            await _send_error(websocket, "malformed message")
            return

        if kind == "subscribe":
            requested = set(data.get("topics") or [])
            unknown = requested - set(T.ALL_TOPICS)
            client.subscriptions |= (requested & set(T.ALL_TOPICS))
            # Replay latest immediately so panels paint without waiting a tick.
            for topic in requested & set(T.ALL_TOPICS):
                snapshot = hub.snapshot_message(topic)
                if snapshot:
                    await websocket.send_text(snapshot)
            if unknown:
                await _send_error(websocket, f"unknown topics: {sorted(unknown)}")
        elif kind == "unsubscribe":
            client.subscriptions -= set(data.get("topics") or [])
        elif kind == "cmd.joints.target":
            angles = data.get("angles") or {}
            try:
                # Runs in the event loop but only validates + enqueues to the
                # command worker; the bus write happens on the worker thread.
                service.set_targets(angles)
            except ServiceError as e:
                await _send_error(websocket, str(e))
        else:
            await _send_error(websocket, f"unknown message type: {kind!r}")

    async def _send_error(websocket: WebSocket, message: str) -> None:
        try:
            await websocket.send_text(json.dumps(
                {"type": "error", "data": {"message": message}}))
        except Exception:
            pass

    return router
