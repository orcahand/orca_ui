"""Tactile zero-offset capture, persistence, and restore.

Per-taxel offsets live under ``sensor_offsets`` in the model's
``calibration.yaml`` — same convention as the original UI, so existing files
keep working. Resultant offsets are a *separate* baseline under
``resultant_offsets``: the sensor reports the resultant on the same
single-byte-per-axis scale as one taxel, not as the sum of its taxels, so it
cannot be derived from ``sensor_offsets``. Files written before that key
existed simply leave the resultant unzeroed.
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
    resultants = data.get("resultant_offsets")
    if not offsets and not resultants:
        return
    try:
        if offsets:
            client.set_taxel_offsets(offsets)
        if resultants:
            client.set_resultant_offsets(resultants)
        logger.info(
            "restored tactile zero offsets from %s (taxels=%s, resultant=%s)",
            path, bool(offsets), bool(resultants),
        )
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
        # Captured from the resultant stream alongside the taxels; ``None``
        # when the stream is taxels-only, and then persisted as such so a
        # reconnect doesn't restore a baseline from a different zeroing run.
        update_yaml(path, "resultant_offsets", client.resultant_offsets)
    return offsets


def clear_offsets(session) -> None:
    client = session.tactile_client
    if client is None:
        raise RuntimeError("no tactile sensor connected")
    client.clear_taxel_offsets()
