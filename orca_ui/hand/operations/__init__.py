"""Long-running hand operations (calibrate, tension, wizard, replay, record).

One :class:`OperationManager` per app runs at most one exclusive operation at
a time, publishes ``operation.state`` / ``operation.log``, and supports
stop / e-stop / awaiting-input. Real vs simulated (mock) implementations are
selected at registration time in :func:`build_operation_manager`.
"""

from __future__ import annotations

from orca_ui.hand.operations.base import OpContext, Operation
from orca_ui.hand.operations.events import (
    OperationSnapshot,
    OperationStopped,
    OpState,
)
from orca_ui.hand.operations.manager import OperationManager


def build_operation_manager(service, settings, publish_topic) -> OperationManager:
    """Construct the manager and register the operation set.

    Operation registration grows with the milestones (M2: calibrate/tension,
    M3: replay/record/demo, M6: wizard); mock mode substitutes simulated
    maintenance ops that emit the identical event stream.
    """
    manager = OperationManager(service, settings, publish_topic=publish_topic)
    return manager


__all__ = [
    "OpContext",
    "Operation",
    "OperationManager",
    "OperationSnapshot",
    "OperationStopped",
    "OpState",
    "build_operation_manager",
]
