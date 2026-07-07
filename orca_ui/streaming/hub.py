"""Latest-value topic store + async broadcaster.

Hardware threads call :meth:`StreamHub.publish` (mutex-guarded dict write —
never touches asyncio). One broadcaster task samples the store at the tick
rate and fans out to subscribed WebSocket clients, latest-wins per topic, so
a slow client skips frames instead of queueing them.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time

from orca_ui.streaming import topics as T

logger = logging.getLogger(__name__)

SEND_TIMEOUT_S = 1.0


class ClientConnection:
    def __init__(self, websocket):
        self.websocket = websocket
        self.subscriptions: set[str] = set()
        self.last_seq: dict[str, int] = {}
        self.last_sent: dict[str, float] = {}
        self.pending: dict[str, str] = {}
        self.wake = asyncio.Event()
        self.alive = True

    async def sender_loop(self) -> None:
        """Drain pending messages; latest-wins per topic."""
        while self.alive:
            await self.wake.wait()
            self.wake.clear()
            while self.pending:
                _topic, message = self.pending.popitem()
                try:
                    await asyncio.wait_for(
                        self.websocket.send_text(message), SEND_TIMEOUT_S)
                except Exception:
                    self.alive = False
                    return


class StreamHub:
    def __init__(self):
        self._lock = threading.Lock()
        self._store: dict[str, tuple[int, float, dict]] = {}
        self._clients: set[ClientConnection] = set()
        self._clients_lock = threading.Lock()

    # ----- producer side (any thread) ----------------------------------------

    def publish(self, topic: str, payload: dict) -> None:
        now_ms = time.time() * 1000.0
        with self._lock:
            seq = self._store.get(topic, (0, 0.0, None))[0] + 1
            self._store[topic] = (seq, now_ms, payload)

    def latest(self, topic: str):
        with self._lock:
            return self._store.get(topic)

    # ----- client registry (event loop) ---------------------------------------

    def register(self, client: ClientConnection) -> None:
        with self._clients_lock:
            self._clients.add(client)

    def unregister(self, client: ClientConnection) -> None:
        client.alive = False
        with self._clients_lock:
            self._clients.discard(client)

    def snapshot_message(self, topic: str) -> str | None:
        """Latest message for a topic, for send-on-subscribe."""
        entry = self.latest(topic)
        if entry is None:
            return None
        return _envelope(topic, *entry)

    # ----- broadcaster (event loop task) ---------------------------------------

    async def broadcaster(self) -> None:
        message_cache: dict[str, tuple[int, str]] = {}
        while True:
            await asyncio.sleep(T.BROADCAST_TICK_S)
            now = time.monotonic()
            with self._clients_lock:
                clients = list(self._clients)
            if not clients:
                continue
            with self._lock:
                store = dict(self._store)

            for client in clients:
                if not client.alive:
                    continue
                dirty = False
                for topic in client.subscriptions:
                    entry = store.get(topic)
                    if entry is None:
                        continue
                    seq, ts_ms, payload = entry
                    if seq <= client.last_seq.get(topic, 0):
                        continue
                    min_interval = T.MIN_INTERVAL_S.get(topic, 0.0)
                    if now - client.last_sent.get(topic, 0.0) < min_interval:
                        continue
                    cached = message_cache.get(topic)
                    if cached is None or cached[0] != seq:
                        try:
                            message = _envelope(topic, seq, ts_ms, payload)
                        except (TypeError, ValueError):
                            logger.exception("unserializable payload on %s", topic)
                            client.last_seq[topic] = seq  # don't retry forever
                            continue
                        message_cache[topic] = (seq, message)
                    else:
                        message = cached[1]
                    client.pending[topic] = message
                    client.last_seq[topic] = seq
                    client.last_sent[topic] = now
                    dirty = True
                if dirty:
                    client.wake.set()


def _envelope(topic: str, seq: int, ts_ms: float, payload: dict) -> str:
    return json.dumps(
        {"type": topic, "seq": seq, "t": ts_ms, "data": payload},
        separators=(",", ":"), allow_nan=False, default=_json_fallback,
    )


def _json_fallback(value):
    try:
        import numpy as np
        if isinstance(value, np.generic):
            return value.item()
        if isinstance(value, np.ndarray):
            return value.tolist()
    except ImportError:
        pass
    raise TypeError(f"not JSON serializable: {type(value)}")
