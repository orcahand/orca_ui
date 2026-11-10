"""The hardware-test data model shared by the catalog, the runner, the checks
and the REST API.

A *feature definition* (one YAML file per feature under ``definitions/``)
lists the steps that test one feature on a real hand. A *plan* (under
``plans/``) names the features one test session covers. A *session* runs a
plan on one hand; its results are stored per feature under
``<bench>/<hand>/tests/<feature>/<session>/``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal, Optional

StepKind = Literal["manual", "auto", "compare", "observe"]
"""``manual``: a person acts on the hand or watches it and decides.
``auto``: a check runs alone in the console and decides.
``compare``: a check runs the same scenario on main's and the branch's
orca_core and decides from the difference.
``observe``: recorded for the record; never passes or fails."""

StepStatus = Literal["pending", "running", "pass", "fail", "observed", "skipped", "error"]
DECIDED: frozenset[str] = frozenset({"pass", "fail", "observed", "skipped"})

PANELS = ("motor_positions", "motor_currents", "motor_temperatures", "joint_encoders",
          "tactile", "operation_log")
"""Live views a step can ask the Tests tab to show while it is open."""


@dataclass(frozen=True)
class AppliesTo:
    """Which hands a step runs on; an empty tuple means any."""

    motor_families: tuple[str, ...] = ()
    hardware_versions: tuple[int, ...] = ()
    sides: tuple[str, ...] = ()
    requires: tuple[str, ...] = ()
    """Capabilities the hand must have: ``tactile``, ``encoders``."""


@dataclass(frozen=True)
class Step:
    id: str
    title: str
    kind: StepKind
    instructions: str
    pass_rule: str
    applies_to: AppliesTo = AppliesTo()
    panels: tuple[str, ...] = ()
    action: Optional[str] = None
    """A console action the tab offers as a button, e.g. ``operation:slack_test``."""
    check: Optional[str] = None
    """Registered check name for ``auto``/``compare`` steps, and for ``manual``
    steps whose outcome a check can verify after the person is done."""
    params: dict = field(default_factory=dict)


@dataclass(frozen=True)
class FeatureDefinition:
    id: str
    title: str
    summary: str
    group: Literal["new", "existing", "observation"]
    steps: tuple[Step, ...]


@dataclass(frozen=True)
class Plan:
    id: str
    title: str
    summary: str
    features: tuple[str, ...]


@dataclass(frozen=True)
class HandFacts:
    """What the session knows about the hand under test."""

    label: str
    model_name: Optional[str]
    motor_family: Optional[str]
    hardware_version: Optional[int]
    hardware_version_source: Optional[str]
    side: Optional[str]
    capabilities: tuple[str, ...]
    mock: bool

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Metric:
    """One number a check reports, with what it is compared against."""

    name: str
    value: Optional[float | str]
    unit: str = ""
    main: Optional[float | str] = None
    """The same quantity measured with main's orca_core, for ``compare`` steps."""
    ok: Optional[bool] = None


@dataclass
class Series:
    """A time series or per-joint series the tab can plot."""

    name: str
    x: list[float]
    y: list[float]
    side: Literal["branch", "main", "console"] = "console"
    x_label: str = "s"
    y_label: str = ""


@dataclass
class CheckResult:
    status: Literal["pass", "fail", "observed", "skipped", "error"]
    summary: str
    metrics: list[Metric] = field(default_factory=list)
    series: list[Series] = field(default_factory=list)
    details: dict = field(default_factory=dict)
    """Anything else worth keeping, e.g. both sides' raw outputs. Stored as JSON."""

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class StepResult:
    step_id: str
    status: StepStatus = "pending"
    note: str = ""
    decided_by: Literal["", "person", "check"] = ""
    check: Optional[dict] = None
    """``CheckResult.as_dict()`` of the check that ran for this step."""
    screenshots: list[str] = field(default_factory=list)
    """File names in the step's ``screenshots/`` folder."""
    started_at: Optional[str] = None
    finished_at: Optional[str] = None

    def as_dict(self) -> dict:
        return asdict(self)
