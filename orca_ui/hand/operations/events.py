"""Operation state vocabulary shared by manager, API, and frontend."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class OpState(str, Enum):
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"            # replay/demo only: playback holds position
    AWAITING_INPUT = "awaiting_input"
    STOPPING = "stopping"
    DONE = "done"
    ERROR = "error"


TERMINAL_STATES = frozenset({OpState.DONE, OpState.ERROR})


@dataclass
class OperationSnapshot:
    """The single source of truth published on the ``operation.state`` topic.

    Mutated only by :class:`~orca_ui.hand.operations.manager.OperationManager`
    under its lock; everyone else sees ``as_dict()`` copies.
    """

    kind: str
    run_id: str
    state: OpState = OpState.STARTING
    phase: str | None = None
    detail: str | None = None
    progress: float | None = None
    params: dict = field(default_factory=dict)
    awaiting: dict | None = None    # {"prompt": str, "options": [str]}
    result: dict | None = None
    error: str | None = None
    started_at: float = 0.0

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "run_id": self.run_id,
            "state": self.state.value,
            "phase": self.phase,
            "detail": self.detail,
            "progress": self.progress,
            "params": dict(self.params),
            "awaiting": dict(self.awaiting) if self.awaiting else None,
            "result": dict(self.result) if self.result else None,
            "error": self.error,
            "started_at": self.started_at,
        }


class OperationStopped(Exception):
    """Raised inside an operation's run() when a stop was requested."""
