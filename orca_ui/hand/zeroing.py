"""Tactile zero-offset capture, persistence, and restore.

Per-taxel offsets live under ``sensor_offsets`` in the hand's
``calibration.yaml``, in its own folder (orca_core keeps keys it does not
own). Resultant offsets are a *separate* baseline under
``resultant_offsets``: the sensor reports the resultant on the same
single-byte-per-axis scale as one taxel, not as the sum of its taxels, so it
cannot be derived from ``sensor_offsets``. Per-taxel noise gates live under
``taxel_noise_gates``. Files written before those keys existed simply leave
the resultant unzeroed and the taxels ungated.
"""

from __future__ import annotations

import logging
import os

from orca_core.utils.utils import read_yaml, update_yaml

from orca_ui.hand.hand_store import NoHandFolder

logger = logging.getLogger(__name__)


def _calibration_path(session) -> str | None:
    """The hand's calibration file; None before the hand knows its folder."""
    return getattr(session.hand.config, "calibration_path", None) or None


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
    gates = data.get("taxel_noise_gates")
    if not offsets and not resultants:
        return
    try:
        if offsets:
            client.set_taxel_offsets(offsets)
        if resultants:
            client.set_resultant_offsets(resultants)
        # Gates measure the dither left over *after* these offsets, so they
        # only mean anything paired with the run that produced them.
        if gates and offsets:
            client.set_taxel_noise_gates(gates)
        logger.info(
            "restored tactile zero offsets from %s "
            "(taxels=%s, resultant=%s, noise gates=%s)",
            path, bool(offsets), bool(resultants), bool(gates and offsets),
        )
    except Exception:
        logger.exception("failed to apply saved sensor offsets")


def capture_and_persist(session, num_samples: int = 100) -> dict:
    """Capture the current readings as the zero baseline and persist them."""
    client = session.tactile_client
    if client is None:
        raise RuntimeError("no tactile sensor connected")
    path = _calibration_path(session)
    if not path:
        raise NoHandFolder(
            "this hand's folder is not known yet, so a zero could not be kept: "
            "connect it with its motors powered once, then zero again")
    offsets = client.capture_taxel_offsets(num_samples=num_samples)
    update_yaml(path, "sensor_offsets", offsets)
    # Captured from the resultant stream alongside the taxels; ``None``
    # when the stream is taxels-only, and then persisted as such so a
    # reconnect doesn't restore a baseline from a different zeroing run.
    update_yaml(path, "resultant_offsets", client.resultant_offsets)
    update_yaml(path, "taxel_noise_gates", client.taxel_noise_gates)
    return offsets


def clear_offsets(session) -> None:
    client = session.tactile_client
    if client is None:
        raise RuntimeError("no tactile sensor connected")
    client.clear_taxel_offsets()
