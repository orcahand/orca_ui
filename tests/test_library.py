"""Pose/trajectory library: storage unit tests + poses API over the mock."""

import time

import pytest
from fastapi.testclient import TestClient

from orca_ui.library import Library, LibraryError
from orca_ui.mock import materialize_mock_model
from orca_ui.server import create_app
from orca_ui.settings import UiSettings


def _wait_for(predicate, timeout=10.0, interval=0.02):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    return predicate()


# ----- storage unit tests -----------------------------------------------------


def test_pose_crud_roundtrip(tmp_path):
    lib = Library(tmp_path, "test-model")
    assert lib.user_poses() == {}
    lib.save_pose("grip_a", {"index_mcp": 40.0, "thumb_cmc": 20.0})
    poses = lib.user_poses()
    assert poses["grip_a"]["angles"] == {"index_mcp": 40.0, "thumb_cmc": 20.0}
    lib.delete_pose("grip_a")
    assert lib.user_poses() == {}
    with pytest.raises(LibraryError):
        lib.delete_pose("grip_a")


def test_names_are_validated(tmp_path):
    lib = Library(tmp_path, "test-model")
    for bad in ("../evil", "a/b", "", "x" * 65, "sp ace"):
        with pytest.raises(LibraryError):
            lib.save_pose(bad, {"index_mcp": 1.0})
        with pytest.raises(LibraryError):
            lib.load_trajectory(bad)


def test_trajectory_storage(tmp_path):
    lib = Library(tmp_path, "test-model")
    data = {
        "metadata": {"type": "continuous", "sampling_frequency_hz": 50.0,
                     "joint_ids": ["a", "b"], "hand_type": "right"},
        "angles": [[0.0, 1.0], [0.5, 1.5]],
    }
    lib.save_trajectory("wave", data)
    assert lib.trajectory_exists("wave")
    with pytest.raises(LibraryError):        # no silent overwrite
        lib.save_trajectory("wave", data)
    assert lib.load_trajectory("wave")["angles"] == [[0.0, 1.0], [0.5, 1.5]]
    listing = lib.list_trajectories()
    assert listing[0]["name"] == "wave"
    assert listing[0]["frames"] == 2
    assert listing[0]["duration_s"] == pytest.approx(0.04)
    lib.delete_trajectory("wave")
    assert not lib.trajectory_exists("wave")


# ----- poses API over the mock ---------------------------------------------------


@pytest.fixture()
def client(tmp_path):
    config_path = materialize_mock_model()
    settings = UiSettings(config_path=config_path, mock=True,
                          open_browser=False, library_dir=str(tmp_path))
    app = create_app(settings)
    with TestClient(app) as test_client:
        assert _wait_for(
            lambda: test_client.get("/api/status").json()["state"] == "connected")
        yield test_client


def test_builtin_poses_listed_as_placeholders(client):
    poses = client.get("/api/poses").json()["poses"]
    by_name = {p["name"]: p for p in poses}
    assert {"open", "fist", "peace", "pinch", "point"} <= set(by_name)
    assert by_name["fist"]["builtin"] and by_name["fist"]["placeholder"]


def test_user_pose_shadows_builtin(client):
    assert client.put("/api/poses/fist",
                      json={"angles": {"index_mcp": 42.0}}).status_code == 200
    by_name = {p["name"]: p for p in client.get("/api/poses").json()["poses"]}
    assert by_name["fist"]["builtin"] is False
    # Deleting the user pose restores the built-in.
    assert client.delete("/api/poses/fist").status_code == 200
    by_name = {p["name"]: p for p in client.get("/api/poses").json()["poses"]}
    assert by_name["fist"]["builtin"] is True


def test_save_pose_rejects_unknown_joints(client):
    response = client.put("/api/poses/custom",
                          json={"angles": {"nope": 1.0}})
    assert response.status_code == 400
    assert "nope" in response.json()["detail"]


def test_capture_pose_saves_measured(client):
    response = client.post("/api/poses/capture", json={"name": "captured"})
    assert response.status_code == 200
    angles = response.json()["angles"]
    assert len(angles) >= 16   # every decodable encoder joint
    by_name = {p["name"]: p for p in client.get("/api/poses").json()["poses"]}
    assert by_name["captured"]["builtin"] is False


def test_apply_builtin_pose_moves_toward_fractions(client):
    # Torque off -> 409.
    assert client.post("/api/poses/fist/apply").status_code == 409
    assert client.post("/api/torque/enable").status_code == 200

    response = client.post("/api/poses/fist/apply")
    assert response.status_code == 200
    target = response.json()["angles"]
    assert target   # fraction-resolved, non-empty

    # The mock loop converges toward the fraction-resolved angles.
    def close_enough():
        service = client.app.state.service
        session = service.session
        measured = session.measured_joints() or {}
        checked = [j for j in ("index_mcp", "middle_mcp") if j in measured]
        return checked and all(
            abs(measured[j] - target[j]) < 5.0 for j in checked)

    assert _wait_for(close_enough, timeout=10.0), "pose apply never converged"


def test_unknown_pose_apply_404(client):
    client.post("/api/torque/enable")
    assert client.post("/api/poses/nonexistent/apply").status_code == 404


def test_demos_listing(client):
    demos = {d["name"]: d for d in client.get("/api/demos").json()["demos"]}
    assert "main" in demos and demos["main"]["source"] == "orca_core"
    assert "open_close" in demos and demos["open_close"]["source"] == "orca_ui"
