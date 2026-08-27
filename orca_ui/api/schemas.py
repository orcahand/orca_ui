"""Pydantic request bodies. Responses are plain dicts assembled by the
service layer (they double as WS payloads); these models exist to validate
what clients send."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class JointTargets(BaseModel):
    angles: dict[str, float]


class RomFrameRequest(BaseModel):
    """ROM frame for the joint↔motor map: "anchor" (measured travel pinned to
    the config upper) or "centered" (measured delta split onto both ends)."""

    mode: str


class JointCalibrateRequest(BaseModel):
    """Manual joint-sensor calibration: the joint currently sits at
    ``angle_deg`` (operator-verified); re-anchor its encoder there."""

    joint: str
    angle_deg: float


class TorqueRequest(BaseModel):
    # Reserved for future per-motor control; today torque toggles hand-wide.
    motor_ids: Optional[list[int]] = None


class GainsRequest(BaseModel):
    kp: float = Field(ge=0)
    ki: float = Field(ge=0)
    correction_max_deg: float = Field(gt=0)
    # null = every loop-controlled joint; a joint list writes exactly those.
    joints: Optional[list[str]] = None


class GainsResetRequest(BaseModel):
    """Restore the config gains; null joints = every loop-controlled joint."""

    joints: Optional[list[str]] = None


class MaxCurrentRequest(BaseModel):
    ma: int = Field(gt=0, le=2000)


class TactileModeRequest(BaseModel):
    mode: Literal["resultant", "taxels", "combined"]


class DirectMotorModeRequest(BaseModel):
    enabled: bool


class DirectMotorPositionRequest(BaseModel):
    id: int = Field(ge=0)
    position: float  # motor position in radians; step-clamped server-side


class ZeroRequest(BaseModel):
    num_samples: int = Field(default=100, ge=1, le=2000)


class SweepRequest(BaseModel):
    """Dev-only (mock): sweep one joint through its ROM; null joint stops."""

    joint: Optional[str] = None
    period_s: float = Field(default=4.0, gt=0.1, le=60)


class OperationStartRequest(BaseModel):
    """Per-kind parameters are validated by the operation itself (the set of
    kinds is registration-dependent: real vs mock)."""

    params: dict = Field(default_factory=dict)


class OperationInputRequest(BaseModel):
    """Answer to an operation parked in ``awaiting_input``."""

    value: str


class PoseSaveRequest(BaseModel):
    angles: dict[str, float]


class PoseCaptureRequest(BaseModel):
    name: str


class TeleopStartRequest(BaseModel):
    """Start a teleop session. ``managed`` spawns the orca_teleop streamer
    child; ``external`` just mints a token for a manually-launched one."""

    source: str
    mode: Literal["managed", "external"] = "managed"
    config: dict = Field(default_factory=dict)


class TeleopEngageRequest(BaseModel):
    ramp_s: Optional[float] = Field(default=None, ge=0, le=10)


class TeleopInstallRequest(BaseModel):
    """Fetch + build the orca_teleop checkout. ``path`` defaults to the sibling
    location beside the orca_ui checkout."""

    path: Optional[str] = None


class TeleopConfigRequest(BaseModel):
    """Partial config update, forwarded to the streamer child (recognized
    keys are filtered by the manager)."""

    config: dict = Field(default_factory=dict)


class UsageSessionBody(BaseModel):
    """Create or rename a usage-stats session; label is optional cosmetics."""

    label: Optional[str] = Field(default=None, max_length=64)


class TrajectoryUpdateRequest(BaseModel):
    """Waypoint-editor save: full replacement waypoint list (row order =
    the recording's joint_ids). ``save_as`` writes a copy under a new name
    instead of overwriting."""

    waypoints: list[list[float]]
    save_as: Optional[str] = Field(default=None, max_length=64,
                                   pattern=r"^[A-Za-z0-9_\-]+$")


class TrajectoryToMotorRequest(BaseModel):
    """Translate a joint waypoint recording to motor space; ``save_as``
    names the copy (default: <name>_motor)."""

    save_as: Optional[str] = Field(default=None, max_length=64,
                                   pattern=r"^[A-Za-z0-9_\-]+$")
