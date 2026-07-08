"""Operation interface + the context handed to a running operation."""

from __future__ import annotations

import queue
import threading
from typing import TYPE_CHECKING, Any

from orca_ui.hand.operations.events import OperationStopped
from orca_ui.hand.states import ControlSource

if TYPE_CHECKING:
    from orca_ui.hand.operations.manager import OperationManager
    from orca_ui.hand.service import HandService
    from orca_ui.settings import UiSettings

_STOP_SENTINEL = object()


class OpContext:
    """What an operation gets to work with while running.

    All mutators route through the manager so snapshot changes stay
    serialized and every change is published to ``operation.state``.
    """

    def __init__(
        self,
        manager: "OperationManager",
        service: "HandService",
        settings: "UiSettings",
        stop_event: threading.Event,
        input_queue: "queue.Queue[Any]",
    ):
        self._manager = manager
        self.service = service
        self.settings = settings
        self.stop_event = stop_event
        self._input_queue = input_queue

    # ----- snapshot updates ---------------------------------------------------

    def set_phase(self, phase: str, detail: str | None = None,
                  progress: float | None = None) -> None:
        self._manager.update_snapshot(phase=phase, detail=detail,
                                      progress=progress)

    def set_progress(self, progress: float, detail: str | None = None) -> None:
        self._manager.update_snapshot(progress=progress, detail=detail)

    def set_detail(self, detail: str) -> None:
        self._manager.update_snapshot(detail=detail)

    def log(self, line: str) -> None:
        self._manager.append_log(line)

    # ----- stop / input ---------------------------------------------------------

    def check_stop(self) -> None:
        if self.stop_event.is_set():
            raise OperationStopped()

    def sleep(self, seconds: float) -> None:
        """Stop-aware sleep: raises OperationStopped if a stop lands."""
        if self.stop_event.wait(seconds):
            raise OperationStopped()

    def wait_input(self, prompt: str, options: list[str]) -> str:
        """Park in ``awaiting_input`` until the user answers or a stop lands."""
        self.check_stop()
        self._manager.enter_awaiting_input(prompt, options)
        try:
            while True:
                try:
                    value = self._input_queue.get(timeout=0.2)
                except queue.Empty:
                    self.check_stop()
                    continue
                if value is _STOP_SENTINEL:
                    raise OperationStopped()
                return str(value)
        finally:
            self._manager.exit_awaiting_input()

    def announce_input(self, prompt: str, options: list[str]) -> None:
        """Enter ``awaiting_input`` WITHOUT blocking on the queue.

        For ops whose thread is blocked inside a hardware call while awaiting
        (e.g. tension's hold loop): the answer arrives via the operation's
        ``handle_input`` hook instead of the queue. Pair with
        :meth:`resume_running` once the hardware call returns."""
        self._manager.enter_awaiting_input(prompt, options)

    def resume_running(self) -> None:
        self._manager.exit_awaiting_input()


class Operation:
    """One long-running hand operation (calibrate, tension, replay, ...).

    Subclasses set ``kind`` and implement :meth:`run`. The manager owns the
    lifecycle: it validates params, acquires ``control_source`` if declared,
    runs :meth:`run` on a worker thread, and publishes every state change.
    """

    kind: str = ""
    # Set to ControlSource.OPERATION for ops that own the joint-target
    # channel for their duration (replay/demo/record).
    control_source: ControlSource | None = None

    def __init__(self, params: dict):
        self.params = params

    @classmethod
    def validate(cls, service: "HandService", params: dict) -> dict:
        """Check preconditions + normalize params. Runs on the caller thread
        so failures surface as HTTP errors. Raise ServiceError on bad input
        or unmet capability requirements."""
        return params

    def run(self, ctx: OpContext) -> dict | None:
        """Execute. Return value (or None) becomes the snapshot ``result``.
        Raise OperationStopped (usually via ctx.check_stop) on stop."""
        raise NotImplementedError

    def request_stop(self, ctx: OpContext) -> None:
        """Called on the *caller* thread when a stop/e-stop is requested,
        after the stop event is set. Override to interrupt blocking calls
        (e.g. set orca_core's task-stop event on an op-owned hand)."""

    def handle_input(self, value: str) -> bool:
        """Called on the *caller* thread when input arrives for an op in
        ``awaiting_input``. Return True to consume the value (ops blocked
        inside hardware calls, paired with ctx.announce_input); return False
        to route it to the queue for a blocking ctx.wait_input."""
        return False
