"""The tactile zero lives in the hand's calibration file beside the motor
calibration: writing or resetting it must never put that calibration at risk."""

import os
from types import SimpleNamespace

import pytest
import yaml

from orca_core import calibration_store
from orca_core import hand_store as core_store
from orca_ui.hand import zeroing

CALIBRATION = {"calibrated_at": "2026-11-16T10:00:00Z", "sequence": 2,
               "motor_limits_dict": {1: [0.0, 1.0]}}


class _Tactile:
    resultant_offsets = {"thumb": [0.1, 0.2, 0.3]}
    taxel_noise_gates = {"thumb": [0.5]}
    cleared = False

    def capture_taxel_offsets(self, num_samples):
        return {"thumb": [[1.0, 2.0, 3.0]]}

    def clear_taxel_offsets(self):
        self.cleared = True


def _session(path):
    return SimpleNamespace(tactile_client=_Tactile(),
                           hand=SimpleNamespace(config=SimpleNamespace(calibration_path=str(path))))


def _read(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_a_zero_keeps_the_calibration_and_its_schema(tmp_path):
    path = tmp_path / "calibration.yaml"
    core_store.write_doc(path, CALIBRATION)
    zeroing.capture_and_persist(_session(path), num_samples=5)
    doc = _read(path)
    assert {k: doc[k] for k in CALIBRATION} == CALIBRATION
    assert doc["schema"] == core_store.SCHEMA
    assert doc["sensor_offsets"] == {"thumb": [[1.0, 2.0, 3.0]]}
    assert doc["resultant_offsets"] == {"thumb": [0.1, 0.2, 0.3]}


def test_a_write_that_fails_leaves_the_file_whole(tmp_path, monkeypatch):
    path = tmp_path / "calibration.yaml"
    core_store.write_doc(path, CALIBRATION)
    before = path.read_text(encoding="utf-8")

    def fail(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError):
        zeroing.capture_and_persist(_session(path), num_samples=5)
    assert path.read_text(encoding="utf-8") == before


def test_reset_removes_the_zero_from_the_file_and_keeps_the_calibration(tmp_path):
    path = tmp_path / "calibration.yaml"
    core_store.write_doc(path, CALIBRATION)
    session = _session(path)
    zeroing.capture_and_persist(session, num_samples=5)
    zeroing.clear_offsets(session)
    doc = _read(path)
    assert session.tactile_client.cleared
    assert not set(zeroing.ZERO_KEYS) & set(doc)
    assert {k: doc[k] for k in CALIBRATION} == CALIBRATION


def test_a_file_from_a_newer_orca_core_is_left_as_it_is(tmp_path):
    path = tmp_path / "calibration.yaml"
    path.write_text(yaml.safe_dump({**CALIBRATION, "schema": core_store.SCHEMA + 1}), encoding="utf-8")
    before = path.read_text(encoding="utf-8")
    session = _session(path)
    with pytest.raises(calibration_store.NewerCalibrationError):
        zeroing.capture_and_persist(session, num_samples=5)
    with pytest.raises(calibration_store.NewerCalibrationError):
        zeroing.clear_offsets(session)
    assert path.read_text(encoding="utf-8") == before
    assert not session.tactile_client.cleared
