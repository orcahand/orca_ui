"""Pose & trajectory library: per-model YAML storage on the server machine.

Layout: ``<root>/<model_name>/poses.yaml`` + ``<root>/<model_name>/trajectories/*.yaml``.
Trajectory files use the exact schemas of orca_core's record/replay examples
(``metadata.type: discrete_waypoints | continuous``), so recordings are
interchangeable with the CLI scripts in both directions.
"""

from __future__ import annotations

import re
import threading
import time
from pathlib import Path

import yaml

NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")

CONTINUOUS = "continuous"
WAYPOINTS = "discrete_waypoints"


class LibraryError(ValueError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _check_name(name: str) -> str:
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise LibraryError(
            f"invalid name {name!r} (use 1-64 chars: letters, digits, _ , -)")
    return name


class Library:
    """Thread-safe file-backed store. Files are small; whole-file
    read/write under a lock keeps it simple and crash-safe enough."""

    def __init__(self, root: Path, model_name: str):
        self._dir = Path(root) / model_name
        self._poses_path = self._dir / "poses.yaml"
        self._traj_dir = self._dir / "trajectories"
        self._lock = threading.Lock()

    # ----- poses ------------------------------------------------------------

    def user_poses(self) -> dict[str, dict]:
        with self._lock:
            return self._read_poses()

    def save_pose(self, name: str, angles: dict[str, float]) -> None:
        _check_name(name)
        with self._lock:
            poses = self._read_poses()
            poses[name] = {
                "angles": {j: float(v) for j, v in angles.items()},
                "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            self._write_poses(poses)

    def delete_pose(self, name: str) -> None:
        _check_name(name)
        with self._lock:
            poses = self._read_poses()
            if name not in poses:
                raise LibraryError(f"no saved pose named {name!r}",
                                   status_code=404)
            del poses[name]
            self._write_poses(poses)

    def _read_poses(self) -> dict:
        if not self._poses_path.is_file():
            return {}
        return yaml.safe_load(self._poses_path.read_text()) or {}

    def _write_poses(self, poses: dict) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        self._poses_path.write_text(yaml.safe_dump(poses, sort_keys=True))

    # ----- trajectories -------------------------------------------------------

    def list_trajectories(self) -> list[dict]:
        with self._lock:
            out = []
            if not self._traj_dir.is_dir():
                return out
            for path in sorted(self._traj_dir.glob("*.yaml")):
                try:
                    data = yaml.safe_load(path.read_text()) or {}
                except Exception:
                    continue
                meta = data.get("metadata") or {}
                traj_type = meta.get("type")
                frames = len(data.get("angles") or data.get("waypoints") or [])
                frequency = meta.get("sampling_frequency_hz")
                duration = (
                    frames / frequency
                    if traj_type == CONTINUOUS and frequency
                    else None
                )
                out.append({
                    "name": path.stem,
                    "type": traj_type,
                    "frames": frames,
                    "frequency_hz": frequency,
                    "duration_s": duration,
                    "created_at": meta.get("created_at"),
                })
            return out

    def load_trajectory(self, name: str) -> dict:
        _check_name(name)
        path = self._traj_dir / f"{name}.yaml"
        with self._lock:
            if not path.is_file():
                raise LibraryError(f"no trajectory named {name!r}",
                                   status_code=404)
            return yaml.safe_load(path.read_text()) or {}

    def save_trajectory(self, name: str, data: dict,
                        overwrite: bool = False) -> None:
        _check_name(name)
        with self._lock:
            self._traj_dir.mkdir(parents=True, exist_ok=True)
            path = self._traj_dir / f"{name}.yaml"
            if path.exists() and not overwrite:
                raise LibraryError(f"trajectory {name!r} already exists",
                                   status_code=409)
            path.write_text(yaml.safe_dump(data, sort_keys=False))

    def trajectory_exists(self, name: str) -> bool:
        _check_name(name)
        return (self._traj_dir / f"{name}.yaml").is_file()

    def delete_trajectory(self, name: str) -> None:
        _check_name(name)
        with self._lock:
            path = self._traj_dir / f"{name}.yaml"
            if not path.is_file():
                raise LibraryError(f"no trajectory named {name!r}",
                                   status_code=404)
            path.unlink()
