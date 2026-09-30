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
    # Milliamps per register unit, and the largest value the register accepts.
    # The register limit is a protocol fact and says nothing about heat.
    current_scale_ma: float | None
    max_current_ma: float | None
    # Where these numbers came from. Audited by a human, not inferred.
    source: str
    # Datasheet figures. Rated is what the motor draws continuously without
    # cooking; stall is what it draws for a moment at zero speed. Either may
    # be absent because the manufacturer did not publish it.
    rated_current_ma: float | None = None
    stall_current_ma: float | None = None
    # Operating Mode values the model accepts. Empty means unrecorded, which
    # is not the same as "all of them".
    operating_modes: tuple[int, ...] = ()

    @property
    def verifiable(self) -> bool:
        return bool(self.model_numbers)

    @property
    def ceiling_ma(self) -> "float | None":
        """The highest current a bench should hand this motor.

        The published continuous rating first. Failing that, stall current,
        which the motor at least survives momentarily. The register limit
        only as a last resort: it is a protocol fact about what the register
        accepts and carries no thermal meaning at all.

        None for a motor with no current register, where the stall figure is
        still a real number but there is nothing to write it to.
        """
        if not self.has_current_control:
            return None
        return self.rated_current_ma or self.stall_current_ma or self.max_current_ma

    def supports_mode(self, mode: int) -> "bool | None":
        """Whether this model accepts an Operating Mode value.

        None when the modes were never recorded — the caller must not read
        that as permission.
        """
        return (mode in self.operating_modes) if self.operating_modes else None


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
# So the family always has current control. Register 28 is NOT a thermal
# ceiling, though: read off a real chain it holds 450 raw (2925 mA) on motors
# that stall at 1.5 A, and 1000 raw (6500 mA) on one that stalls at 2.8 A.
# It is the overcurrent trip point, set roughly twice stall so that stalling
# does not trip it, and a bench must not mistake it for a rating.
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
        # Current Limit (38) accepts 0..910 at 1 mA/unit; Goal Current (102)
        # is bounded by whatever that register holds.
        max_current_ma=910.0,
        # ROBOTIS publishes no continuous rating for this model, so the stall
        # figure is the only thermal number there is — and note it is lower
        # than what the register will accept.
        rated_current_ma=None,
        stall_current_ma=800.0,
        operating_modes=(0, 1, 3, 4, 5, 16),
        source=("ROBOTIS XC330-T288-T control table and specification: model "
                "number 1220, Current Limit (38) 0..910 at 1.0 mA/unit, Goal "
                "Current (102) bounded by it, stall 0.92 N.m at 11.1 V / "
                "0.80 A; Current Limit read back as 910 on hardware"),
    ),
    MotorModel(
        key="dxl-1080",
        # W240 and T240BB-T are two names for the same motor, which is why
        # orca_core and the parts list disagree without either being wrong.
        # Both are in the label so a search for either finds it.
        label="Dynamixel XC430-W240 / T240BB-T",
        family=DYNAMIXEL,
        model_numbers=(1080,),
        # Its control table has no Goal Current (102) and no Current Limit
        # (38) at all: 100 is Goal PWM and 104 is Goal Velocity, leaving
        # 102-103 unallocated. Writing there is undefined, which is why this
        # motor is skipped rather than clamped.
        has_current_control=False,
        current_scale_ma=None,
        max_current_ma=None,
        stall_current_ma=1400.0,
        # No current-based position (5) and no current control (0). The wrist
        # runs in extended position (4) instead.
        operating_modes=(1, 3, 4, 16),
        source=("ROBOTIS XC430-W240 control table and specification: model "
                "number 1080, no Goal Current or Current Limit register, "
                "Operating Mode accepts only 1/3/4/16, stall 1.9 N.m at "
                "12 V / 1.4 A; both registers read back as 0 on hardware"),
    ),
    MotorModel(
        key="hls2915m",
        label="Feetech HLS2915M-C001",
        family=FEETECH,
        # Confirmed by the operator against the hand: the finger motors report
        # 6922. orca_core labels that number HLS3915, which is the same motor
        # under a different name; 5130 appears in orca_core's table for it too.
        model_numbers=(6922, 5130),
        has_current_control=True,
        current_scale_ma=HLS_CURRENT_SCALE_MA,
        # Stall, the hard clamp. Sustained draw here cooks the motor.
        # Register 44 accepts 2047 units, which is 13.3 A — far past this
        # motor. The datasheet numbers are what matter.
        max_current_ma=13305.5,
        rated_current_ma=500.0,
        stall_current_ma=1500.0,
        operating_modes=(0, 1, 2, 3),
        source=("HL-2915-C001 product specification A/0, 2026-01-18: rated "
                "current 500 mA, stall current 1.5 A at 12 V, stall torque "
                "14.2 kg.cm; registers from the HLS memory table (44 capped "
                "by 28, 6.5 mA/unit, modes 0-3); model number 6922 read off "
                "the finger motors and confirmed by the operator"),
    ),
    MotorModel(
        key="hls3930m",
        label="Feetech HLS3930M-C001",
        family=FEETECH,
        # Read off the wrist, where the parts list puts this model, and
        # orca_core labels 4106 HLS3930. Both agree, so it can be checked.
        model_numbers=(4106,),
        has_current_control=True,
        current_scale_ma=HLS_CURRENT_SCALE_MA,
        max_current_ma=13305.5,
        rated_current_ma=800.0,
        stall_current_ma=2800.0,
        operating_modes=(0, 1, 2, 3),
        source=("HLS3930M-C001 product specification A/0, 2024-04-25: rated "
                "current 800 mA, stall current 2.8 A at 12 V, stall torque "
                "35 kg.cm; registers from the HLS memory table (44 capped "
                "by 28, 6.5 mA/unit, modes 0-3)"),
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
        max_current_ma=13305.5,
        rated_current_ma=500.0,
        stall_current_ma=1500.0,
        operating_modes=(0, 1, 2, 3),
        source=("HLS memory table (6.5 mA/unit, register 44 capped by "
                "register 28, modes 0-3). Current limits are the most "
                "conservative of the catalogued HLS models, not this "
                "motor's own rating"),
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
        "stall_current_ma": model.stall_current_ma,
        "ceiling_ma": model.ceiling_ma,
        "operating_modes": list(model.operating_modes),
        "source": model.source,
        "verifiable": model.verifiable,
    }
