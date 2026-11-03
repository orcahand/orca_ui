"""Temporary, for in-house assembly until the release: a hand detected at start-up
keeps its config and calibration in its own folder, created on first sight.

``<root>/<hand id>/<model>/config.yaml``: the console names a hand's model after
the config's directory. ``ORCA_HAND_FOLDERS`` overrides the root, ``~/orca_bench``.
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

ROOT_ENV = "ORCA_HAND_FOLDERS"


def hand_folder_config(hand_id: str, model_name: str, packaged_config: str) -> str:
    """This hand's ``config.yaml`` for ``model_name``, created if it is missing.

    Files already directly in the hand's folder are copied in, so a hand set up
    by hand keeps its config and calibration; otherwise it starts from the
    packaged config.
    """
    root = Path(os.environ.get(ROOT_ENV) or Path.home() / "orca_bench")
    hand_dir = root / re.sub(r"[^\w.-]", "_", hand_id)
    model_dir = hand_dir / model_name
    config = model_dir / "config.yaml"
    if config.exists():
        return str(config)
    model_dir.mkdir(parents=True, exist_ok=True)
    if (hand_dir / "config.yaml").is_file():
        for existing in hand_dir.iterdir():
            if existing.is_file():
                shutil.copy2(existing, model_dir / existing.name)
    else:
        shutil.copy2(packaged_config, config)
    return str(config)
