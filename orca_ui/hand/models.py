"""The catalogue of hand models the console can be pointed at.

Which model is in force is normally a conclusion rather than a setting: the
supervisor reads it off the controller board's identity reply on every
detection pass. A hand with no ORCA board to answer — a legacy build, or one
driven by someone else's electronics — has nothing to read, so
``detect_hand()`` degrades to orca_core's default model and every left /
touch / joint hand of that kind looks like a plain right one.

Naming the model is the way out. ``--model`` does it at startup; this module
is the list of names to offer when it has to be done from the browser
instead, read straight off orca_core's bundled model tree.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from orca_core.utils.utils import (
    _get_models_dir,
    _version_sort_key,
    read_yaml,
)


@dataclass(frozen=True)
class ModelEntry:
    """One bundled model, as offered in the picker."""

    name: str
    version: str
    side: str
    tactile: bool
    encoders: bool
    config_path: str

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "side": self.side,
            "tactile": self.tactile,
            "encoders": self.encoders,
            "config_path": self.config_path,
        }


def describe(config_path: str) -> tuple[str, bool, bool]:
    """``(side, tactile, encoders)`` read from a ``config.yaml``.

    Raw keys, not a loaded config: this runs over every bundled model to
    build a menu, and one model that fails validation must not blank the
    whole list. The keys are the same ones the config classes derive those
    three answers from — ``sensors`` selects the touch class, and
    ``has_joint_encoders`` is ``bool(joint_encoder_joints)``.
    """
    raw = read_yaml(config_path) or {}
    return (
        str(raw.get("type") or ""),
        "sensors" in raw,
        bool(raw.get("joint_encoder_joints")),
    )


def _entry(models_dir: str, version: str, name: str) -> ModelEntry | None:
    config_path = os.path.join(models_dir, version, name, "config.yaml")
    if not os.path.isfile(config_path):
        return None
    try:
        side, tactile, encoders = describe(config_path)
    except Exception:
        return None
    return ModelEntry(name=name, version=version, side=side, tactile=tactile,
                      encoders=encoders, config_path=config_path)


def _sort_key(entry: ModelEntry) -> tuple:
    # Grouped by side, then poorest to richest — the order the names read in
    # (plain, touch, joint, full) rather than the alphabetical jumble.
    return (entry.side, entry.tactile + 2 * entry.encoders, entry.name)


def available_models(model_version: str | None = None) -> list[ModelEntry]:
    """The bundled models a selection may name.

    With no ``model_version``, one entry per model name at its newest version
    — the same resolution ``--model NAME`` performs, so what the menu offers
    is what picking it gets. A pinned version (``--model-version v1``) lists
    that version instead, since that is the tree the process is working in.
    """
    models_dir = _get_models_dir()
    if not os.path.isdir(models_dir):
        return []
    versions = sorted(os.listdir(models_dir), key=_version_sort_key,
                      reverse=True)
    if model_version is not None:
        versions = [v for v in versions if v == model_version]

    entries: dict[str, ModelEntry] = {}
    for version in versions:
        version_dir = os.path.join(models_dir, version)
        if not os.path.isdir(version_dir):
            continue
        for name in sorted(os.listdir(version_dir)):
            if name in entries:
                continue  # newest version of each name wins
            entry = _entry(models_dir, version, name)
            if entry is not None:
                entries[name] = entry
    return sorted(entries.values(), key=_sort_key)
