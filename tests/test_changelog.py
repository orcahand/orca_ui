"""The changelog document, and the discipline around it.

The release-has-an-entry test is the mechanism behind the rule in CLAUDE.md:
bumping the version without telling users what changed fails here.
"""

import re
import tomllib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orca_ui import changelog
from orca_ui.mock import materialize_mock_model
from orca_ui.server import create_app
from orca_ui.settings import UiSettings

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def pyproject() -> dict:
    with open(PROJECT_ROOT / "pyproject.toml", "rb") as fh:
        return tomllib.load(fh)


def declared_version() -> str:
    return pyproject()["project"]["version"]


def pinned_core_floor() -> str:
    """The lower bound of the orca-core requirement, e.g. "0.10.1"."""
    for requirement in pyproject()["project"]["dependencies"]:
        if requirement.replace("_", "-").startswith("orca-core"):
            floor = re.search(r">=\s*([0-9][0-9.]*)", requirement)
            assert floor, f"orca-core requirement has no lower bound: {requirement}"
            return floor.group(1)
    raise AssertionError("orca-core is not in the dependencies")


class TestTheDocument:
    def test_ships_inside_the_package(self):
        assert changelog.CHANGELOG_PATH.is_file()
        assert changelog.CHANGELOG_PATH.parent.name == "orca_ui"

    def test_this_release_has_an_entry(self):
        version = declared_version()
        assert version in [e["version"] for e in changelog.entries()], (
            f"orca_ui {version} has no changelog entry. Add '## UI {version} — <date>' "
            "to orca_ui/changelog.md with a Core: line and a header per change."
        )

    def test_entries_come_back_newest_first(self):
        found = [e["version"] for e in changelog.entries()]
        assert found == sorted(found, key=changelog._sort_key, reverse=True)

    def test_the_release_names_the_core_it_pairs_with(self):
        latest = changelog.entries()[0]
        assert latest["core"] == pinned_core_floor(), (
            "The 'Core:' line in orca_ui/changelog.md and the orca-core lower bound "
            "in pyproject.toml must name the same release."
        )

    def test_every_entry_carries_a_date(self):
        for entry in changelog.entries():
            assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", entry["date"]), entry


class TestParsing:
    def test_reads_version_date_and_core_from_a_heading(self):
        found = changelog.entries("## UI 1.2.3 — 2026-01-02\nCore: 4.5.6\n\nprose\n")
        assert found == [{"version": "1.2.3", "date": "2026-01-02", "core": "4.5.6"}]

    def test_the_ui_prefix_is_optional(self):
        assert changelog.latest_version("## 1.2.3 — 2026-01-02\n") == "1.2.3"

    def test_a_core_line_belongs_to_the_release_above_it(self):
        doc = "## 2.0.0 — 2026-02-02\nCore: 1.1.1\n\n## 1.0.0 — 2026-01-01\nCore: 0.9.0\n"
        assert {e["version"]: e["core"] for e in changelog.entries(doc)} == {
            "2.0.0": "1.1.1",
            "1.0.0": "0.9.0",
        }

    def test_a_release_without_a_core_line_reports_none(self):
        assert changelog.entries("## 1.0.0 — 2026-01-01\n")[0]["core"] is None

    def test_orders_by_version_not_by_position(self):
        doc = "## 0.9.0 — 2026-01-01\n\n## 0.10.0 — 2026-02-01\n"
        assert [e["version"] for e in changelog.entries(doc)] == ["0.10.0", "0.9.0"]
        assert changelog.latest_version(doc) == "0.10.0"

    def test_ignores_prose_headings(self):
        doc = "## Not a release\n\n### 1.0.0 — a subheading\n"
        assert changelog.entries(doc) == []

    def test_a_document_with_no_entries_has_no_latest(self):
        assert changelog.latest_version("just prose\n") is None


class TestTheDismissal:
    """One indicator file, named after the release, cleared on every write."""

    @pytest.fixture(autouse=True)
    def state_dir(self, tmp_path, monkeypatch):
        directory = tmp_path / ".changelog"
        monkeypatch.setattr(changelog, "STATE_DIR", directory)
        return directory

    def test_nothing_is_dismissed_before_anything_is_written(self, state_dir):
        assert changelog.seen_version() is None
        assert not state_dir.exists()

    def test_ticking_writes_one_indicator_named_after_the_release(self, state_dir):
        changelog.set_seen("0.3.0")
        assert [p.name for p in state_dir.iterdir()] == ["ui-0.3.0.seen"]
        assert changelog.seen_version() == "0.3.0"

    def test_a_later_release_replaces_the_indicator_rather_than_adding_one(
        self, state_dir
    ):
        changelog.set_seen("0.3.0")
        changelog.set_seen("0.3.1")
        changelog.set_seen("0.4.0")
        assert [p.name for p in state_dir.iterdir()] == ["ui-0.4.0.seen"]
        assert changelog.seen_version() == "0.4.0"

    def test_unticking_clears_the_folder_but_keeps_it(self, state_dir):
        changelog.set_seen("0.3.0")
        changelog.set_seen(None)
        assert list(state_dir.iterdir()) == []
        assert changelog.seen_version() is None

    def test_a_stale_indicator_does_not_dismiss_the_current_release(self, state_dir):
        changelog.set_seen("0.2.0")
        assert changelog.changelog()["dismissed"] is False

    def test_the_indicator_says_what_it_is_and_how_to_undo_it(self, state_dir):
        changelog.set_seen("0.3.0")
        body = (state_dir / "ui-0.3.0.seen").read_text()
        assert "0.3.0" in body and "Delete this file" in body

    def test_an_unwritable_directory_is_not_an_error(self, tmp_path, monkeypatch):
        blocked = tmp_path / "a-file"
        blocked.write_text("not a directory")
        monkeypatch.setattr(changelog, "STATE_DIR", blocked / ".changelog")
        assert changelog.set_seen("0.3.0") is None
        assert changelog.seen_version() is None

    def test_clearing_leaves_anything_that_is_not_a_file(self, state_dir):
        state_dir.mkdir(parents=True)
        (state_dir / "a-directory").mkdir()
        changelog.set_seen("0.3.0")
        assert (state_dir / "a-directory").is_dir()
        assert changelog.seen_version() == "0.3.0"


class TestTheRoute:
    @pytest.fixture()
    def client(self):
        settings = UiSettings(
            config_path=materialize_mock_model(), mock=True, open_browser=False
        )
        with TestClient(create_app(settings)) as test_client:
            yield test_client

    @pytest.fixture(autouse=True)
    def state_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(changelog, "STATE_DIR", tmp_path / ".changelog")

    def test_ticking_and_unticking_round_trips_through_the_backend(self, client):
        assert client.get("/api/changelog").json()["dismissed"] is False

        dismissed = client.post("/api/changelog/seen", json={"dismissed": True}).json()
        assert dismissed["dismissed"] is True
        assert client.get("/api/changelog").json()["dismissed"] is True

        restored = client.post("/api/changelog/seen", json={"dismissed": False}).json()
        assert restored["dismissed"] is False
        assert client.get("/api/changelog").json()["dismissed"] is False

    def test_serves_the_document_and_what_it_covers(self, client):
        body = client.get("/api/changelog").json()
        assert body["latest_version"] == changelog.latest_version()
        assert body["ui_version"] == declared_version()
        assert body["recommended_core"] == pinned_core_floor()
        assert body["versions"][0] == body["latest_version"]
        assert body["markdown"].lstrip().startswith("<!--")

    def test_picks_up_an_edit_without_a_restart(self, client, tmp_path, monkeypatch):
        edited = tmp_path / "changelog.md"
        edited.write_text("## 9.9.9 — 2026-12-31\n\n### Something new\nprose\n")
        monkeypatch.setattr(changelog, "CHANGELOG_PATH", edited)
        body = client.get("/api/changelog").json()
        assert body["latest_version"] == "9.9.9"
        assert "Something new" in body["markdown"]

    def test_a_missing_document_is_not_an_error(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr(changelog, "CHANGELOG_PATH", tmp_path / "gone.md")
        body = client.get("/api/changelog").json()
        assert body["markdown"] == ""
        assert body["latest_version"] is None
        assert body["recommended_core"] is None
