"""The hardware-test report a contributor commits and a maintainer's agent
verifies: an honest session round-trips to VERIFIED, and an edited report, a
check's step decided by a person, a skipped base step or a mock hand do not.

Runs on a synthetic orca_ui checkout and stored session in tmp folders."""

import json
import os
import subprocess
from pathlib import Path

import pytest

from orca_ui.hardware_tests import report as rp
from orca_ui.hardware_tests import store

LABEL = "ser-1234"
STAMP = "2026-02-01_100000"
CORE = {"version": "0.14.0", "source": "pypi", "commit": None, "branch": None, "dirty": None}
DEFINITIONS = {
    "fb": [("B1", "auto", "check: x"), ("B2", "manual", "")],
    "fr": [("R1", "auto", "check: y"), ("R2", "observe", "")],
}


def _git(repo: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z", "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z"}
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false",
                           *args], cwd=repo, env=env, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture()
def repo(tmp_path) -> Path:
    """A committed orca_ui checkout whose plan ``rel`` includes ``base``."""
    root = tmp_path / "ui"
    package = root / rp.PACKAGE_PATH
    (package / "plans").mkdir(parents=True)
    (package / "definitions").mkdir()
    (root / "orca_ui" / "__init__.py").write_text("")
    (root / "pyproject.toml").write_text('[project]\nname = "orca-ui"\nversion = "9.9.9"\n')
    (package / "plans" / "base.yaml").write_text("id: base\ntitle: Base\nsummary: s\nfeatures: [fb]\n")
    (package / "plans" / "rel.yaml").write_text("id: rel\ntitle: Rel\nsummary: s\nincludes: [base]\nfeatures: [fr]\n")
    for fid, steps in DEFINITIONS.items():
        body = "".join(f"  - {{id: {sid}, title: t, kind: {kind}, instructions: i, pass_rule: p"
                       f"{', ' + check if check else ''}}}\n" for sid, kind, check in steps)
        (package / "definitions" / f"{fid}.yaml").write_text(
            f"id: {fid}\ntitle: {fid}\nsummary: s\ngroup: existing\nsteps:\n{body}")
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "plans")
    return root


def _session(tmp_path, *, mock=False, finished=True, **overrides) -> Path:
    """A stored ``rel`` session on disk; ``overrides`` replace step results by id."""
    paths = store.SessionPaths(tmp_path / "bench", LABEL, "rel", STAMP)
    hand = {"label": LABEL, "model_name": "orcahand-right", "motor_family": "feetech", "hardware_version": 210,
            "hardware_version_source": "board", "side": "right", "capabilities": [], "mock": mock}
    results = {
        "B1": {"status": "pass", "decided_by": "check", "check": {"summary": "fine"}},
        "B2": {"status": "pass", "decided_by": "person", "note": f"{LABEL} looked fine in {Path.home()}/x"},
        "R1": {"status": "pass", "decided_by": "check", "check": {"summary": "fine"}},
        "R2": {"status": "observed", "decided_by": "check", "check": {"summary": "seen"}},
        **overrides,
    }
    session_id = f"{STAMP} rel"
    for fid, steps in DEFINITIONS.items():
        store.write_json(paths.feature_result(fid), {
            "feature": fid, "session": session_id, "plan": "rel", "hand": hand,
            "steps": {sid: {"step_id": sid, "note": "", **results[sid]} for sid, _, _ in steps}})
    store.append_jsonl(paths.events, {"type": "session_started"})
    store.write_json(paths.index_json, {
        "id": session_id, "plan_id": "rel", "plan_title": "Rel", "stamp": STAMP, "label": LABEL, "hand": hand,
        "started_at": "2026-02-01T10:00:00.000+01:00",
        "finished_at": "2026-02-01T11:00:00.000+01:00" if finished else None,
        "sides": {"main": {"available": True, "reason": None, "version": "0.13.0"}}})
    return paths.index_json


def test_an_honest_session_round_trips_to_verified(tmp_path, repo):
    with pytest.raises(rp.ReportError, match="not finished"):
        rp.build_report(_session(tmp_path, finished=False), root=repo, core=CORE)

    out = rp.export(_session(tmp_path), out_dir=repo / rp.REPORTS_DIR, root=repo, core=CORE)
    assert out.name == "2026-02-01_rel_orcahand-right_feetech.json"
    text = out.read_text(encoding="utf-8")
    assert LABEL not in text and str(Path.home()) not in text
    report = json.loads(text)
    assert [s["id"] for s in report["steps"]] == ["B1", "B2", "R1", "R2"]
    assert report["verdict"] == "pass" and report["code_under_test"]["orca_ui"]["dirty"] is False

    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "Add the hardware-test report")
    findings = rp.verify(report, repo=repo, expect_commit=_git(repo, "rev-parse", "HEAD"))
    assert findings.problems == []
    assert any("ancestor of the PR head" in n for n in findings.notes)

    # Code committed after testing is not covered by the report.
    (repo / "orca_ui" / "late.py").write_text("")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "late")
    late = rp.verify(report, repo=repo, expect_commit=_git(repo, "rev-parse", "HEAD"))
    assert any("orca_ui/late.py" in p for p in late.problems)


def test_an_edited_report_is_rejected(tmp_path, repo):
    report = rp.build_report(_session(tmp_path), root=repo, core=CORE)
    report["steps"][0]["note"] = "all good"
    problems = rp.verify(report, ui_repo=repo).problems
    assert len(problems) == 1 and "integrity" in problems[0], problems


@pytest.mark.parametrize("session, problem", [
    (dict(B1={"status": "pass", "decided_by": "person", "note": "it worked"}), "not by its check"),
    (dict(B2={"status": "skipped", "decided_by": "person", "note": "no time"}), "base plan and may not be skipped"),
    (dict(mock=True), "a real hand is required"),
])
def test_a_report_breaking_a_rule_is_rejected(tmp_path, repo, session, problem):
    report = rp.build_report(_session(tmp_path, **session), root=repo, core=CORE)
    problems = rp.verify(report, ui_repo=repo).problems
    assert len(problems) == 1 and problem in problems[0], problems
