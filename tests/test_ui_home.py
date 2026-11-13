"""The one-time move of ~/.orca_ui into ~/.orca/ui: whatever goes wrong, no
recording, pose or assembly progress is lost, and the console runs from
wherever the data actually is."""

import errno
import os

import pytest

from orca_ui import home
from orca_ui.home import move_legacy_ui_home


@pytest.fixture
def folders(tmp_path):
    source = tmp_path / "user" / ".orca_ui"
    (source / "library" / "orcahand-right" / "recordings").mkdir(parents=True)
    (source / "library" / "orcahand-right" / "recordings" / "wave.json").write_text("[1, 2]")
    (source / "assembly-progress-v2.json").write_text('{"current": "p7"}')
    return source, tmp_path / "orca-home" / "ui"


def _data(folder):
    return {
        str(path.relative_to(folder)): path.read_text()
        for path in sorted(folder.rglob("*")) if path.is_file()
    }


EXPECTED = {
    "assembly-progress-v2.json": '{"current": "p7"}',
    "library/orcahand-right/recordings/wave.json": "[1, 2]",
}


def test_a_plain_move_renames_the_folder(folders):
    source, target = folders
    assert move_legacy_ui_home(source, target) == (target, True)
    assert _data(target) == EXPECTED
    assert not source.exists()
    assert move_legacy_ui_home(source, target) == (target, False)


def test_both_present_uses_the_new_folder_and_touches_neither(folders, caplog):
    source, target = folders
    (target / "library").mkdir(parents=True)
    with caplog.at_level("WARNING"):
        assert move_legacy_ui_home(source, target) == (target, False)
    assert _data(source) == EXPECTED
    assert "no longer read" in caplog.text


def test_an_unwritable_home_keeps_the_old_folder_in_use(folders):
    source, target = folders
    target.parent.mkdir()
    os.chmod(target.parent, 0o500)
    try:
        assert move_legacy_ui_home(source, target) == (source, False)
    finally:
        os.chmod(target.parent, 0o700)
    assert _data(source) == EXPECTED
    assert not target.exists()


def _cross_filesystem(monkeypatch, target, fail_copy=False):
    rename, copytree = os.rename, home.shutil.copytree

    def fake_rename(src, dst):
        if os.fspath(dst) == os.fspath(target) and not os.fspath(src).endswith(".moving"):
            raise OSError(errno.EXDEV, "Invalid cross-device link")
        rename(src, dst)

    def fake_copytree(src, dst, *args, **kwargs):
        copytree(src, dst, *args, **kwargs)
        if fail_copy and os.fspath(dst).endswith(".moving"):
            raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(home.os, "rename", fake_rename)
    monkeypatch.setattr(home.shutil, "copytree", fake_copytree)


def test_across_filesystems_it_copies_then_deletes(folders, monkeypatch):
    source, target = folders
    _cross_filesystem(monkeypatch, target)
    assert move_legacy_ui_home(source, target) == (target, True)
    assert _data(target) == EXPECTED
    assert not source.exists() and not source.with_name(".orca_ui.moving").exists()


def test_a_failed_copy_puts_the_source_back(folders, monkeypatch):
    source, target = folders
    _cross_filesystem(monkeypatch, target, fail_copy=True)
    assert move_legacy_ui_home(source, target) == (source, False)
    assert _data(source) == EXPECTED
    assert not target.exists() and not target.with_name("ui.moving").exists()


def test_an_interrupted_copy_is_redone_from_the_parked_source(folders):
    """Killed mid-copy: the source sits under .moving, a partial copy beside the target."""
    source, target = folders
    held = source.with_name(".orca_ui.moving")
    os.rename(source, held)
    (target.with_name("ui.moving") / "library").mkdir(parents=True)
    assert move_legacy_ui_home(source, target) == (target, True)
    assert _data(target) == EXPECTED
    assert not held.exists() and not target.with_name("ui.moving").exists()


def test_a_library_dir_inside_the_old_folder_stops_the_move(folders):
    source, target = folders
    library = source / "library"
    assert move_legacy_ui_home(source, target, str(library)) == (source, False)
    assert _data(source) == EXPECTED
    assert not target.exists()


def test_orca_home_moves_the_console_state(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCA_HOME", str(tmp_path / "elsewhere"))
    assert home.ui_home() == tmp_path / "elsewhere" / "ui"
