"""OperationManager: at most one exclusive long-running operation at a time.

Owns the operation worker thread, the ``operation.state`` snapshot, and the
run's bounded log buffer. The log is published *cumulatively* — the hub is a
latest-value store with latest-wins coalescing at every layer, so per-line
publishes would drop burst lines; publishing the whole recent buffer means
latest-wins loses nothing and a page reload resyncs the visible log.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
import uuid
from collections import deque
from typing import Callable, Type

from orca_ui.hand.operations.base import _STOP_SENTINEL, OpContext, Operation
from orca_ui.hand.operations.events import (
    TERMINAL_STATES,
    OperationSnapshot,
    OperationStopped,
    OpState,
)
from orca_ui.settings import UiSettings
from orca_ui.streaming import topics as T

logger = logging.getLogger(__name__)

LOG_BUFFER_LINES = 500
SHUTDOWN_JOIN_TIMEOUT_S = 5.0


class OperationManager:
    def __init__(
        self,
        service,
        settings: UiSettings,
        publish_topic: Callable[[str, dict], None] | None = None,
    ):
        self._service = service
        self._settings = settings
        self._publish_topic = publish_topic or (lambda topic, payload: None)

        self._lock = threading.Lock()
        self._registry: dict[str, Type[Operation]] = {}
        self._snapshot: OperationSnapshot | None = None
        self._operation: Operation | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._input_queue: queue.Queue = queue.Queue()
        self._stop_reason: str | None = None
        self._pause_requested = False
        self._log: deque[dict] = deque(maxlen=LOG_BUFFER_LINES)
        self._log_seq = 0
        self._run_id: str | None = None

    # ----- registry -------------------------------------------------------------

    def register(self, op_cls: Type[Operation]) -> None:
        if not op_cls.kind:
            raise ValueError(f"{op_cls.__name__} has no kind")
        self._registry[op_cls.kind] = op_cls

    @property
    def kinds(self) -> list[str]:
        return sorted(self._registry)

    # ----- reads ----------------------------------------------------------------

    def snapshot(self) -> dict | None:
        with self._lock:
            return self._snapshot.as_dict() if self._snapshot else None

    def active(self) -> bool:
        with self._lock:
            return (
                self._snapshot is not None
                and self._snapshot.state not in TERMINAL_STATES
            )

    def log_payload(self) -> dict:
        with self._lock:
            return {
                "run_id": self._run_id,
                "next_seq": self._log_seq,
                "lines": list(self._log),
            }

    # ----- lifecycle ------------------------------------------------------------

    def start(self, kind: str, params: dict | None = None) -> dict:
        from orca_ui.hand.service import ServiceError

        op_cls = self._registry.get(kind)
        if op_cls is None:
            raise ServiceError(f"unknown operation: {kind!r} "
                               f"(available: {self.kinds})", status_code=404)

        def _conflict_check() -> None:
            if self._snapshot is not None and \
                    self._snapshot.state not in TERMINAL_STATES:
                raise ServiceError(
                    f"operation {self._snapshot.kind!r} is already running",
                    status_code=409)

        # Conflict first: "already running" is the truthful error even when
        # the running op has the hand in maintenance (no session → param
        # validation would 503 misleadingly). Then validate on the caller
        # thread so bad params surface as HTTP statuses before scheduling.
        with self._lock:
            _conflict_check()
        # No op may start while another control session owns the joint-target
        # channel: an engaged teleop must not have the hand yanked away by a
        # maintenance lease, and arbiter-acquiring ops get a synchronous 409
        # instead of an async ERROR snapshot.
        self._service.require_manual_control()
        clean_params = op_cls.validate(self._service, dict(params or {}))

        with self._lock:
            _conflict_check()
            run_id = f"{kind}-{uuid.uuid4().hex[:8]}"
            self._run_id = run_id
            self._snapshot = OperationSnapshot(
                kind=kind, run_id=run_id, params=clean_params,
                started_at=time.time(),
            )
            self._operation = op_cls(clean_params)
            self._stop_event = threading.Event()
            self._input_queue = queue.Queue()
            self._stop_reason = None
            self._pause_requested = False
            self._log.clear()
            self._log_seq = 0
            operation = self._operation
            stop_event = self._stop_event
            input_queue = self._input_queue

        self._publish_state()
        self._publish_log()

        ctx = OpContext(self, self._service, self._settings,
                        stop_event, input_queue)
        thread = threading.Thread(
            target=self._run, args=(operation, ctx),
            name=f"Operation-{kind}", daemon=True,
        )
        with self._lock:
            self._thread = thread
        thread.start()
        return self.snapshot() or {}

    def _run(self, operation: Operation, ctx: OpContext) -> None:
        acquired = False
        try:
            if operation.control_source is not None:
                self._service.acquire_control(operation.control_source,
                                              owner_label=operation.kind)
                acquired = True
            self.update_snapshot(state=OpState.RUNNING)
            result = operation.run(ctx)
            self._finish(OpState.DONE, result=result)
        except OperationStopped:
            reason = self._stop_reason or "stopped"
            if reason == "stopped (e-stop)":
                self._finish(OpState.ERROR, detail=reason, error=reason)
            else:
                self._finish(OpState.DONE, detail=reason)
        except Exception as e:
            logger.exception("operation %s failed", operation.kind)
            self._finish(OpState.ERROR, error=str(e))
        finally:
            if acquired:
                try:
                    self._service.release_control(
                        expected=operation.control_source)
                except Exception:
                    logger.exception("release_control failed")

    def _finish(self, state: OpState, result: dict | None = None,
                detail: str | None = None, error: str | None = None) -> None:
        with self._lock:
            if self._snapshot is None:
                return
            self._snapshot.state = state
            self._snapshot.awaiting = None
            if result is not None:
                self._snapshot.result = result
            if detail is not None:
                self._snapshot.detail = detail
            if error is not None:
                self._snapshot.error = error
        self._publish_state()

    def stop(self, estop: bool = False, wait: bool = False) -> bool:
        """Request the active operation to stop. Returns True if one was
        active. Never raises — safe to call from the e-stop path."""
        with self._lock:
            if self._snapshot is None or \
                    self._snapshot.state in TERMINAL_STATES:
                return False
            self._stop_reason = "stopped (e-stop)" if estop else "stopped"
            self._snapshot.state = OpState.STOPPING
            operation = self._operation
            stop_event = self._stop_event
            input_queue = self._input_queue
            thread = self._thread
        self._publish_state()
        stop_event.set()
        input_queue.put(_STOP_SENTINEL)
        if operation is not None:
            try:
                ctx = OpContext(self, self._service, self._settings,
                                stop_event, input_queue)
                operation.request_stop(ctx)
            except Exception:
                logger.exception("request_stop hook failed")
        if wait and thread is not None:
            thread.join(timeout=SHUTDOWN_JOIN_TIMEOUT_S)
        return True

    def send_input(self, value) -> None:
        from orca_ui.hand.service import ServiceError

        with self._lock:
            if self._snapshot is None or \
                    self._snapshot.state in TERMINAL_STATES:
                raise ServiceError("no operation running", status_code=409)
            state = self._snapshot.state
            operation = self._operation
            input_queue = self._input_queue
        # Ops consuming input mid-run (record's "stop & save", tension's
        # Release while blocked inside orca_core) take it via their hook on
        # the caller thread; a blocking ctx.wait_input gets the queue.
        try:
            if operation is not None and operation.handle_input(str(value)):
                return
        except Exception:
            logger.exception("handle_input hook failed")
        if state != OpState.AWAITING_INPUT:
            raise ServiceError("operation is not awaiting input",
                               status_code=409)
        input_queue.put(value)

    def pause(self) -> None:
        from orca_ui.hand.service import ServiceError

        with self._lock:
            if self._snapshot is None or \
                    self._snapshot.state in TERMINAL_STATES:
                raise ServiceError("no operation running", status_code=409)
            self._pause_requested = True

    def resume(self) -> None:
        with self._lock:
            self._pause_requested = False

    @property
    def pause_requested(self) -> bool:
        with self._lock:
            return self._pause_requested

    def shutdown(self) -> None:
        self.stop(wait=True)

    # ----- snapshot/log plumbing (called by OpContext) -----------------------------

    def update_snapshot(self, state: OpState | None = None,
                        phase: str | None = None,
                        detail: str | None = None,
                        progress: float | None = None,
                        extra: dict | None = None) -> None:
        with self._lock:
            snapshot = self._snapshot
            if snapshot is None or snapshot.state in TERMINAL_STATES:
                return
            # A stop request wins over concurrent op-thread updates.
            if state is not None and snapshot.state != OpState.STOPPING:
                snapshot.state = state
            if phase is not None:
                snapshot.phase = phase
            if detail is not None:
                snapshot.detail = detail
            if progress is not None:
                snapshot.progress = float(progress)
            if extra is not None:
                snapshot.extra = dict(extra)
        self._publish_state()

    def enter_awaiting_input(self, prompt: str, options: list[str]) -> None:
        with self._lock:
            snapshot = self._snapshot
            if snapshot is None or snapshot.state in TERMINAL_STATES:
                return
            if snapshot.state != OpState.STOPPING:
                snapshot.state = OpState.AWAITING_INPUT
            snapshot.awaiting = {"prompt": prompt, "options": list(options)}
        self._publish_state()

    def exit_awaiting_input(self) -> None:
        with self._lock:
            snapshot = self._snapshot
            if snapshot is None or snapshot.state in TERMINAL_STATES:
                return
            snapshot.awaiting = None
            if snapshot.state == OpState.AWAITING_INPUT:
                snapshot.state = OpState.RUNNING
        self._publish_state()

    def append_log(self, line: str) -> None:
        with self._lock:
            self._log.append({
                "seq": self._log_seq,
                "t": time.time(),
                "line": line,
            })
            self._log_seq += 1
        self._publish_log()

    def _publish_state(self) -> None:
        snapshot = self.snapshot()
        if snapshot is not None:
            self._publish_topic(T.OPERATION_STATE, snapshot)

    def _publish_log(self) -> None:
        self._publish_topic(T.OPERATION_LOG, self.log_payload())
