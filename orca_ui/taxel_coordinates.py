"""Config-driven taxel coordinates for tactile sensor visualization.

Coordinates are loaded from sensor model config files in the models/ directory.
This module is UI-side only: orca_core does not need 3D taxel positions, but the
visualization layer in orca_ui does.
"""

import os
from typing import TypedDict

import yaml


class TaxelCoord(TypedDict):
    x: float
    y: float
    z: float


MODELS_DIR = os.path.join(os.path.dirname(__file__), "models")

# Finger-to-sensor-model mapping. Mirrors the wiring used by orca_core but kept
# local so the UI does not depend on orca_core internals for visualization data.
FINGER_MODELS = {
    "thumb": "touch-sensor-thumb",
    "index": "touch-sensor-finger",
    "middle": "touch-sensor-finger",
    "ring": "touch-sensor-finger",
    "pinky": "touch-sensor-pinky",
}

_model_cache: dict[str, list[TaxelCoord]] = {}


def _load_model_coordinates(model_name: str) -> list[TaxelCoord]:
    """Load coordinates for a sensor model from its config.yaml."""
    if model_name in _model_cache:
        return _model_cache[model_name]

    config_path = os.path.join(MODELS_DIR, model_name, "config.yaml")
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    coords = [TaxelCoord(x=c["x"], y=c["y"], z=c["z"]) for c in config["coordinates"]]
    _model_cache[model_name] = coords
    return coords


def get_coordinates(finger: str) -> list[TaxelCoord]:
    """Get taxel coordinates for a finger.

    Args:
        finger: Finger name ('thumb', 'index', 'middle', 'ring', 'pinky')

    Returns:
        List of coordinate dicts with 'x', 'y', 'z' keys (in mm)
    """
    model_name = FINGER_MODELS.get(finger)
    if model_name is None:
        return []
    return _load_model_coordinates(model_name)


def get_all_coordinates() -> dict[str, list[TaxelCoord]]:
    """Get taxel coordinates for all fingers.

    Returns:
        Dict mapping finger name to list of coordinate dicts
    """
    return {finger: _load_model_coordinates(model) for finger, model in FINGER_MODELS.items()}
