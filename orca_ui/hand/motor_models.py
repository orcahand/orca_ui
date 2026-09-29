"""Control-table facts for the motor models a bench knows how to drive.

A servo cannot be asked what it can do. Reading Goal Current from a model that
has no such register returns a plain zero with no error, so "does this register
exist" is not a question the protocol answers. The model has to be known.

So the operator declares it, from this list, and the declaration is checked
against the model number the servo reports. Every entry carries where its
numbers came from, because a wrong entry here writes to a register on hardware
that may not have one.

Nothing is guessed. A model that is not in this list is driven as if it had no
current control, which is the safe direction: the motor keeps whatever ceiling
it powered up with.
"""

from __future__ import annotations

from dataclasses import dataclass

# Families, matching orca_core's own names.
DYNAMIXEL = "dynamixel"
FEETECH = "feetech"


@dataclass(frozen=True)
class MotorModel:
    """What a bench needs to know before writing to a motor."""

    key: str
    label: str
    family: str
    # What the servo reports when pinged. Empty when we have no confirmed
    # number, which means a declaration of this model cannot be cross-checked.
    model_numbers: tuple[int, ...]
    # Whether a Goal Current register exists and means what we think.
    has_current_control: bool
    # Milliamps per register unit, and the ceiling the register accepts.
    current_scale_ma: float | None
    max_current_ma: float | None
    # Where these numbers came from. Audited by a human, not inferred.
    source: str

    @property
    def verifiable(self) -> bool:
        return bool(self.model_numbers)


UNKNOWN_KEY = "unknown"

UNKNOWN = MotorModel(
    key=UNKNOWN_KEY,
    label="Unknown / not declared",
    family="",
    model_numbers=(),
    # Fail closed: without knowing the model, no current register is assumed,
    # so nothing is written and the motor keeps its power-up ceiling.
    has_current_control=False,
    current_scale_ma=None,
    max_current_ma=None,
    source="no declaration — treated as having no current control",
)

# Confirmed by reading the control table off a real chain on 2026-09-29:
# model 1220 answers Current Limit with 910, model 1080 answers it with 0.
_MODELS: tuple[MotorModel, ...] = (
    MotorModel(
        key="xc330-t288",
        label="Dynamixel XC330-T288-T",
        family=DYNAMIXEL,
        model_numbers=(1220,),
        has_current_control=True,
        current_scale_ma=1.0,
        max_current_ma=910.0,
        source=("orca_core DynamixelClient (current_scale_ma, max_current_ma); "
                "Current Limit read back as 910 on hardware; confirmed by the "
                "operator as the finger-joint motor"),
    ),
    MotorModel(
        key="dxl-1080",
        # W240 and T240BB-T are two names for the same motor, which is why
        # orca_core and the parts list disagree without either being wrong.
        # Both are in the label so a search for either finds it.
        label="Dynamixel XC430-W240 / T240BB-T",
        family=DYNAMIXEL,
        model_numbers=(1080,),
        # No current sensor, so no Goal Current register: the wrist runs in
        # multi-turn position instead of current-based position.
        has_current_control=False,
        current_scale_ma=None,
        max_current_ma=None,
        source=("orca_core MODELS_WITHOUT_CURRENT_CONTROL; Current Limit and "
                "Goal Current both read back as 0 on hardware; confirmed by "
                "the operator as the wrist motor"),
    ),
    MotorModel(
        key="feetech-hls",
        label="Feetech HLS series",
        family=FEETECH,
        # The scan reports names rather than numbers for this family, so a
        # declaration here cannot be cross-checked yet.
        model_numbers=(),
        has_current_control=True,
        current_scale_ma=1.0,
        max_current_ma=900.0,
        source="orca_core FeetechClient class attributes",
    ),
)

BY_KEY: dict[str, MotorModel] = {m.key: m for m in (UNKNOWN, *_MODELS)}


def catalogue(family: str | None = None) -> list[MotorModel]:
    """Models offered in the picker, the unknown entry first."""
    models = [m for m in _MODELS if family is None or m.family == family]
    return [UNKNOWN, *models]


def get(key: str | None) -> MotorModel:
    """The declared model, or the fail-closed unknown."""
    return BY_KEY.get(key or "", UNKNOWN)


def for_model_number(number: int | None, family: str | None = None) -> MotorModel | None:
    """The model a reported number identifies, when exactly one does.

    Used to prefill the picker and to contradict a declaration that disagrees
    with what the servo says about itself.
    """
    if number is None:
        return None
    matches = [m for m in _MODELS
               if number in m.model_numbers
               and (family is None or m.family == family)]
    return matches[0] if len(matches) == 1 else None


def as_dict(model: MotorModel) -> dict:
    return {
        "key": model.key,
        "label": model.label,
        "family": model.family,
        "model_numbers": list(model.model_numbers),
        "has_current_control": model.has_current_control,
        "current_scale_ma": model.current_scale_ma,
        "max_current_ma": model.max_current_ma,
        "source": model.source,
        "verifiable": model.verifiable,
    }
