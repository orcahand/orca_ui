"""Tactile zero-offset capture, persistence, and restore.

Offsets live under ``sensor_offsets`` in the model's ``calibration.yaml`` —
same convention as the original UI, so existing files keep working.
"""

from __future__ import annotations

import logging
import os

from orca_core.utils.utils import read_yaml, update_yaml

logger = logging.getLogger(__name__)


def _calibration_path(session) -> str | None:
    path = getattr(session.hand.config, "calibration_path", None)
    if path:
        return path
    config_path = getattr(session.hand.config, "config_path", None)
    if config_path:
        return os.path.join(os.path.dirname(config_path), "calibration.yaml")
    return None


def apply_saved_offsets(session) -> None:
    """Restore persisted zero offsets onto a freshly connected session."""
    client = session.tactile_client
    if client is None:
        return
    path = _calibration_path(session)
    if not path or not os.path.isfile(path):
        return
    data = read_yaml(path) or {}
    offsets = data.get("sensor_offsets")
    if offsets:
        try:
            client.set_taxel_offsets(offsets)
            logger.info("restored tactile zero offsets from %s", path)
        except Exception:
            logger.exception("failed to apply saved sensor offsets")


def capture_and_persist(session, num_samples: int = 100) -> dict:
    """Capture the current readings as the zero baseline and persist them."""
    client = session.tactile_client
    if client is None:
        raise RuntimeError("no tactile sensor connected")
    offsets = client.capture_taxel_offsets(num_samples=num_samples)
    path = _calibration_path(session)
    if path:
        update_yaml(path, "sensor_offsets", offsets)
    return offsets


def clear_offsets(session) -> None:
    client = session.tactile_client
    if client is None:
        raise RuntimeError("no tactile sensor connected")
    client.clear_taxel_offsets()
