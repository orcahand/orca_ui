"""Connection state machine vocabulary shared by supervisor, API, and frontend."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class HandState(str, Enum):
    DISCONNECTED = "disconnected"
    DETECTING = "detecting"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DEGRADED = "degraded"       # connected, but with fewer capabilities than declared
    RECONNECTING = "reconnecting"


class ControlSource(str, Enum):
    """Who owns the joint-target channel. Exactly one owner at a time.

    TELEOP is reserved for the planned orca_teleop integration (a separate
    process streaming retargeted joint targets); engaging it will acquire
    control the same way an operation does.
    """

    MANUAL = "manual"
    OPERATION = "operation"
    TELEOP = "teleop"


@dataclass(frozen=True)
class Capabilities:
    """What the current session can actually do (vs. ``declared`` = config)."""

    motors: bool = False
    tactile: bool = False
    encoders: bool = False
    feedback_loop: bool = False
    declared: dict = field(default_factory=dict)

    @property
    def degraded(self) -> bool:
        return (
            self.declared.get("motors", False) > self.motors
            or self.declared.get("tactile", False) > self.tactile
            or self.declared.get("encoders", False) > self.encoders
        )


@dataclass(frozen=True)
class StatusSnapshot:
    state: HandState
    capabilities: Capabilities | None
    torque_enabled: bool
    message: str
    ports: dict
    since: float

    def as_dict(self) -> dict:
        caps = None
        if self.capabilities is not None:
            caps = {
                "motors": self.capabilities.motors,
                "tactile": self.capabilities.tactile,
                "encoders": self.capabilities.encoders,
                "feedback_loop": self.capabilities.feedback_loop,
                "declared": dict(self.capabilities.declared),
                "degraded": self.capabilities.degraded,
            }
        return {
            "state": self.state.value,
            "capabilities": caps,
            "torque_enabled": self.torque_enabled,
            "message": self.message,
            "ports": dict(self.ports),
            "since": self.since,
        }
