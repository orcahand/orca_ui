"""Built-in poses and movement sequences, defined as ROM fractions.

Fractions (0 = ROM lower / extended, 1 = ROM upper / flexed) survive
recalibration and work across hands of one model family. These built-ins are
PLACEHOLDERS until tuned on the real hand — they are flagged as such in the
API so the UI can style them accordingly. A user-saved pose with the same
name shadows the built-in.
"""

from __future__ import annotations

_ABD_CENTER = {
    "thumb_abd": 0.5, "index_abd": 0.5, "middle_abd": 0.5,
    "ring_abd": 0.5, "pinky_abd": 0.5,
}

_FLEXION = ["thumb_cmc", "thumb_mcp", "thumb_dip",
            "index_mcp", "index_pip", "middle_mcp", "middle_pip",
            "ring_mcp", "ring_pip", "pinky_mcp", "pinky_pip"]


def _pose(flexion: float, wrist: float = 0.5, **overrides) -> dict[str, float]:
    pose = {j: flexion for j in _FLEXION}
    pose.update(_ABD_CENTER)
    pose["wrist"] = wrist
    pose.update(overrides)
    return pose


BUILTIN_POSES: dict[str, dict[str, float]] = {
    "open": _pose(0.08),
    "fist": _pose(0.92, thumb_cmc=0.6, thumb_abd=0.65),
    "peace": _pose(0.9,
                   index_mcp=0.08, index_pip=0.06, index_abd=0.32,
                   middle_mcp=0.08, middle_pip=0.06, middle_abd=0.68,
                   thumb_cmc=0.75, thumb_mcp=0.7, thumb_dip=0.55),
    "pinch": _pose(0.12,
                   index_mcp=0.6, index_pip=0.55,
                   thumb_cmc=0.55, thumb_abd=0.6,
                   thumb_mcp=0.5, thumb_dip=0.5),
    "point": _pose(0.9,
                   index_mcp=0.06, index_pip=0.05,
                   thumb_cmc=0.65, thumb_mcp=0.6),
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

