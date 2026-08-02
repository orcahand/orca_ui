"""Serialized motor command execution.

High-rate slider targets coalesce latest-wins and apply at most at
``MAX_APPLY_HZ``; long-running exclusive ops (go-to-neutral) run on the same
thread so they never interleave with target writes.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Callable, Optional

logger = logging.getLogger(__name__)

MAX_APPLY_HZ = 50.0


class CommandWorker(threading.Thread):
    def __init__(
        self,
        get_session: Callable[[], object | None],
        on_error: Callable[[str], None] | None = None,
    ):
        super().__init__(name="CommandWorker", daemon=True)
        self._get_session = get_session
        self._on_error = on_error or (lambda message: None)
        self._lock = threading.Lock()
        self._pending_targets: dict[str, float] = {}
        self._ops: deque[Callable[[], None]] = deque()
        self._wake = threading.Event()
        self._stop_event = threading.Event()
        self._last_apply = 0.0

    def submit_targets(self, angles: dict[str, float]) -> None:
        with self._lock:
            self._pending_targets.update(angles)
        self._wake.set()

    def submit_op(self, op: Callable[[], None]) -> None:
        """Queue an exclusive operation (e.g. go-to-neutral)."""
        with self._lock:
            self._ops.append(op)
        self._wake.set()

    def shutdown(self) -> None:
        self._stop_event.set()
        self._wake.set()
        self.join(timeout=2.0)

    def run(self) -> None:
        while not self._stop_event.is_set():
            self._wake.wait()
            self._wake.clear()
            if self._stop_event.is_set():
                return

            while True:
                with self._lock:
                    op = self._ops.popleft() if self._ops else None
                    targets: Optional[dict] = None
                    if op is None and self._pending_targets:
                        targets = self._pending_targets
                        self._pending_targets = {}
                if op is None and targets is None:
                    break
                if op is not None:
                    self._run_op(op)
                    continue
                self._apply_targets(targets)

    def _run_op(self, op: Callable[[], None]) -> None:
        try:
            op()
        except Exception as e:
            logger.exception("command op failed")
            self._on_error(f"command failed: {e}")

    def _apply_targets(self, targets: dict[str, float]) -> None:
        session = self._get_session()
        if session is None or not session.caps.motors:
            return
        # Rate-limit bus writes; coalescing means we always apply the newest.
        min_period = 1.0 / MAX_APPLY_HZ
        elapsed = time.monotonic() - self._last_apply
        if elapsed < min_period:
            time.sleep(min_period - elapsed)
        try:
            session.hand.set_joint_positions(targets)
            self._last_apply = time.monotonic()
        except Exception as e:
            logger.exception("set_joint_positions failed")
            self._on_error(f"set_joint_positions failed: {e}")
