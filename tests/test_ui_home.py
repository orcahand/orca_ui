"""The one-time move of ~/.orca_ui into ~/.orca/ui: whatever goes wrong, no
recording, pose or assembly progress is lost, and the console runs from
wherever the data actually is."""

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


def test_a_plain_move_renames_the_folder_and_links_the_old_path(folders):
    source, target = folders
    assert move_legacy_ui_home(source, target) == (target, True)
    assert _data(target) == EXPECTED
    assert source.is_symlink() and _data(source) == EXPECTED
    assert move_legacy_ui_home(source, target) == (target, False)


def test_an_old_path_linked_to_the_new_folder_counts_as_moved(folders, caplog):
    source, target = folders
    target.parent.mkdir()
    os.rename(source, target)
    os.symlink(target, source)
    with caplog.at_level("WARNING"):
        assert move_legacy_ui_home(source, target) == (target, False)
    assert _data(target) == EXPECTED
    assert caplog.text == ""


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


def test_a_library_dir_inside_the_old_folder_stops_the_move(folders):
    source, target = folders
    library = source / "library"
    assert move_legacy_ui_home(source, target, str(library)) == (source, False)
    assert _data(source) == EXPECTED
    assert not target.exists()


def test_with_orca_home_set_the_old_folder_is_not_moved(folders, monkeypatch, caplog):
    source, target = folders
    monkeypatch.setenv("HOME", str(source.parent))
    monkeypatch.setenv("ORCA_HOME", str(target.parent))
    monkeypatch.setattr(home, "_in_use", None)
    with caplog.at_level("WARNING"):
        assert home.prepare_ui_home() is None
    assert home.ui_home() == target
    assert _data(source) == EXPECTED and not source.is_symlink()
    assert str(source) in caplog.text
    # ORCA_HOME spelled out as the default still moves.
    monkeypatch.setenv("ORCA_HOME", "~/.orca")
    monkeypatch.setattr(home, "_in_use", None)
    assert home.prepare_ui_home() is not None
    assert _data(source.parent / ".orca" / "ui") == EXPECTED
