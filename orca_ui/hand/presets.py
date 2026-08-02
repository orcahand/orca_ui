"""Built-in poses and movement sequences, defined as ROM fractions.

Fractions (0 = ROM lower / extended, 1 = ROM upper / flexed) survive
recalibration and work across hands of one model family. A user-saved pose
with the same name shadows the built-in.

The poses below are written as joint angles in degrees, which is how they
were dialled in, and converted to fractions against ``_ROM``. A hand
calibrated to a different ROM lands on slightly different angles.
"""

from __future__ import annotations

# ROM the pose angles are expressed against, joint -> (min deg, max deg).
# Kept in step with orca_core's v2 models.
_ROM = {
    "wrist": (-65, 35),
    "thumb_cmc": (-45, 33), "thumb_abd": (-18, 55),
    "thumb_mcp": (-25, 100), "thumb_dip": (-15, 107),
    "index_abd": (-30, 25), "index_mcp": (-25, 100), "index_pip": (-15, 107),
    "middle_abd": (-27, 27), "middle_mcp": (-25, 100), "middle_pip": (-15, 107),
    "ring_abd": (-27, 27), "ring_mcp": (-25, 100), "ring_pip": (-15, 107),
    "pinky_abd": (-30, 30), "pinky_mcp": (-25, 100), "pinky_pip": (-15, 107),
}


def _pose(**angles: float) -> dict[str, float]:
    """Flat hand at 0 deg, with the named joints set to the given angle."""
    return {j: (angles.get(j, 0.0) - lo) / (hi - lo) for j, (lo, hi) in _ROM.items()}


def _curl(*fingers: str, mcp: float, pip: float) -> dict[str, float]:
    """mcp/pip angles for the named fingers, to fold them into the palm."""
    return {f"{f}_{j}": a for f in fingers for j, a in (("mcp", mcp), ("pip", pip))}


BUILTIN_POSES: dict[str, dict[str, float]] = {
    "open": _pose(thumb_cmc=-21.0, thumb_abd=45.0, thumb_dip=17.0),
    "fist": _pose(thumb_cmc=10.0, thumb_abd=22.0, thumb_mcp=30.0, thumb_dip=26.0,
                  **_curl("index", "middle", "ring", "pinky", mcp=89.5, pip=99.2)),
    "peace": _pose(thumb_cmc=13.5, thumb_abd=22.1, thumb_mcp=45.0, thumb_dip=34.1,
                   index_abd=4.5, middle_abd=-7.5,
                   **_curl("ring", "pinky", mcp=87.2, pip=97.2)),
    "pinch": _pose(thumb_cmc=-8.0, thumb_abd=19.0, thumb_mcp=34.0, thumb_dip=33.5,
                   index_mcp=38.5, index_pip=61.0,
                   **_curl("middle", "ring", "pinky", mcp=-18.4, pip=9.4)),
    "point": _pose(thumb_cmc=10.0, thumb_abd=22.2, thumb_mcp=29.9, thumb_dip=25.8,
                   index_pip=2.5,
                   **_curl("middle", "ring", "pinky", mcp=89.5, pip=99.2)),
}

# Movement sequences: fraction keyframes played with a fixed per-segment
# duration (same shape as orca_core's demo presets).
BUILTIN_SEQUENCES: dict[str, list[dict[str, float]]] = {
    "open_close": [
        BUILTIN_POSES["open"],
        BUILTIN_POSES["fist"],
        BUILTIN_POSES["open"],
    ],
    "pinch_cycle": [
        BUILTIN_POSES["open"],
        BUILTIN_POSES["pinch"],
        BUILTIN_POSES["open"],
    ],
}
