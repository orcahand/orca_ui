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
    # What the motor can draw continuously without cooking, from its
    # datasheet. This is the sensible bench default; max_current_ma is the
    # stall figure and only a hard clamp.
    rated_current_ma: float | None = None

    @property
    def verifiable(self) -> bool:
        return bool(self.model_numbers)

    @property
    def ceiling_ma(self) -> "float | None":
        """The highest current a bench should hand this motor.

        The continuous rating where the datasheet gives one. Stall current is
        what the motor survives for a moment, not what it survives held
        against a load, and a bench holds things against loads.
        """
        return self.rated_current_ma or self.max_current_ma


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

# Every HLS servo shares one memory table (Feetech HLS memory-table manual):
#   28  Protection Current  RW  0..2047, 6.5 mA/unit, copied into 44 at power-up
#   33  Operating Mode      RW  0 position, 1 speed, 2 current, 3 PWM
#   44  Goal Torque         RW  -2047..2047, 6.5 mA/unit, caps running current
#   69  Present Current     R   6.5 mA/unit
# So the family always has current control, and the per-motor ceiling is
# readable from register 28 rather than assumed from the model.
HLS_CURRENT_SCALE_MA = 6.5

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
        key="hls2915m",
        label="Feetech HLS2915M-C001",
        family=FEETECH,
        # The datasheet does not give the number the servo reports, and the
        # bus has not been read for it yet, so a declaration of this model
        # cannot be cross-checked.
        model_numbers=(),
        has_current_control=True,
        current_scale_ma=HLS_CURRENT_SCALE_MA,
        # Stall, the hard clamp. Sustained draw here cooks the motor.
        max_current_ma=1500.0,
        rated_current_ma=500.0,
        source=("HL-2915-C001 product specification A/0, 2026-01-18: rated "
                "current 500 mA, stall current 1.5 A at 12 V, stall torque "
                "14.2 kg.cm; scale from the HLS memory table (6.5 mA/unit)"),
    ),
    MotorModel(
        key="hls3930m",
        label="Feetech HLS3930M-C001",
        family=FEETECH,
        model_numbers=(),
        has_current_control=True,
        current_scale_ma=HLS_CURRENT_SCALE_MA,
        max_current_ma=2800.0,
        rated_current_ma=800.0,
        source=("HLS3930M-C001 product specification A/0, 2024-04-25: rated "
                "current 800 mA, stall current 2.8 A at 12 V, stall torque "
                "35 kg.cm; scale from the HLS memory table (6.5 mA/unit)"),
    ),
    MotorModel(
        key="feetech-hls",
        label="Feetech HLS series (generic)",
        family=FEETECH,
        model_numbers=(),
        has_current_control=True,
        current_scale_ma=HLS_CURRENT_SCALE_MA,
        # No model, so no datasheet rating: fall back to the lowest ceiling
        # any catalogued HLS motor tolerates rather than the register maximum
        # of 2047 units, which is 13.3 A and belongs to no motor here.
        max_current_ma=1500.0,
        rated_current_ma=500.0,
        source=("HLS memory table (6.5 mA/unit, register 44 capped by "
                "register 28). Limits are the most conservative of the "
                "catalogued HLS models, not this motor's own rating"),
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
        "rated_current_ma": model.rated_current_ma,
        "ceiling_ma": model.ceiling_ma,
        "source": model.source,
        "verifiable": model.verifiable,
    }
