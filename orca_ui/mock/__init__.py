"""Hardware-free mock hand for the UI.

``--mock`` runs the exact production stack — real ``TactileClient``,
``JointEncoderClient``, ``JointLoopThread``, demuxer — over in-memory serial
links fed by background pumps. The closed loop genuinely converges: slider
commands move the mock motors, the encoder pump reflects them, and the
measured joints track the targets.
"""

from __future__ import annotations

import os
import shutil
import tempfile

_MODEL_DIR = os.path.join(os.path.dirname(__file__), "model")


def materialize_mock_model() -> str:
    """Copy the bundled mock model to a tempdir and return its config path.

    Runtime writes (persisted ports via ``update_yaml``, captured sensor
    offsets) land in the copy, never in the installed package.
    """
    run_dir = tempfile.mkdtemp(prefix="orca_ui_mock_model_")
    for name in ("config.yaml", "calibration.yaml"):
        shutil.copy(os.path.join(_MODEL_DIR, name), os.path.join(run_dir, name))
    return os.path.join(run_dir, "config.yaml")


def build_mock_hand(config_path: str, engage_feedback: bool = True):
    from orca_ui.mock.hands import build_mock_hand as _build
    return _build(config_path, engage_feedback=engage_feedback)
