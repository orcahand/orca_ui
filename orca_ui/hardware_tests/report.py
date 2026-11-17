"""A strict, machine-readable report of one finished hardware-test session,
for a contributor to commit to a PR and a maintainer's agent to check.

    python -m orca_ui.hardware_tests.report export <session.json> (--out <file> | --out-dir <dir>)
    python -m orca_ui.hardware_tests.report verify <report.json> [--repo <checkout>] [--expect-commit <sha>]

``export`` reads a stored session (its index, events and result files, see
:mod:`orca_ui.hardware_tests.store`). The code it ran on is what the session
recorded when it started (:func:`code_under_test`), and the plan and
definitions are read from that orca_ui commit; the exporting checkout is only
recorded as the generator. Reports go under ``hardware-test-reports/`` at the
root of the repo the PR targets.

``verify`` prints one line per problem and ``VERIFIED`` or ``REJECTED``. It
reads the plan and definitions from the tested orca_ui commit itself, so a
report cannot change what a step is. The integrity hash only catches edits
made without recomputing it; the git checks are what tie a report to code.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from orca_ui.hardware_tests import catalog as cat
from orca_ui.hardware_tests import store
from orca_ui.hardware_tests.model import FeatureDefinition, HandFacts

SCHEMA = "orca-hardware-test-report/1"
REPORTS_DIR = "hardware-test-reports"
BASE_PLAN = "base"
PACKAGE_PATH = "orca_ui/hardware_tests"
PLANS_PATH = f"{PACKAGE_PATH}/plans"
DEFINITIONS_PATH = f"{PACKAGE_PATH}/definitions"
STATUSES = ("pass", "fail", "observed", "skipped", "error", "running", "pending")
DEFAULT_TESTS_BRANCH = "origin/feature/hardware-tests"
_GIT_TIMEOUT_S = 30


class ReportError(Exception):
    pass


# ----- hashing and canonical JSON -------------------------------------------------------


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> Optional[str]:
    try:
        return sha256_bytes(path.read_bytes())
    except OSError:
        return None


def canonical(data) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def integrity_hash(report: dict) -> str:
    return sha256_bytes(canonical({k: v for k, v in report.items() if k != "integrity"}))


def dumps(report: dict) -> str:
    return json.dumps(report, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


# ----- git ----------------------------------------------------------------------------


def _git(repo: Path, *args: str, binary: bool = False) -> Optional[str | bytes]:
    """git's stdout in ``repo`` (stripped text unless ``binary``), or None on failure."""
    try:
        done = subprocess.run(["git", *args], cwd=repo, capture_output=True, timeout=_GIT_TIMEOUT_S,
                              env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"})
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    return done.stdout if binary else done.stdout.decode("utf-8", "replace").strip()


def _status_paths(porcelain: str) -> list[str]:
    paths = []
    for line in porcelain.splitlines():
        path = line[3:].split(" -> ")[-1].strip().strip('"')
        if path:
            paths.append(path)
    return paths


def checkout_state(path: Path) -> dict:
    """commit, branch and dirty flag of the git checkout rooted at ``path``.

    Untracked files count as dirty (they can be imported), except reports."""
    top = _git(path, "rev-parse", "--show-toplevel")
    if not top or Path(top).resolve() != path.resolve():
        return {"commit": None, "branch": None, "dirty": None, "reason": f"{path.name} is not a git checkout"}
    branch = _git(path, "rev-parse", "--abbrev-ref", "HEAD")
    status = _git(path, "status", "--porcelain", "--untracked-files=all")
    dirty = None if status is None else any(
        not p.startswith(REPORTS_DIR + "/") for p in _status_paths(status))
    return {"commit": _git(path, "rev-parse", "HEAD"), "branch": None if branch == "HEAD" else branch,
            "dirty": dirty, "reason": None}


def ui_root() -> Path:
    import orca_ui

    return Path(orca_ui.__file__).resolve().parent.parent


def ui_version(root: Path) -> str:
    try:
        import tomllib

        return tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    except (OSError, KeyError, ValueError):
        from orca_ui.changelog import ui_version as installed

        return installed()


def core_state(source=None) -> dict:
    """The orca_core this process imports, as the console reports it, without paths."""
    from orca_ui.core_source import resolve

    source = source or resolve()
    kind = {"released": "pypi"}.get(source.kind, source.kind)
    out = {"version": source.version, "source": kind, "commit": None, "branch": None, "dirty": None}
    if kind == "local" and source.location:
        state = checkout_state(Path(source.location))
        out.update(commit=state["commit"], branch=state["branch"], dirty=state["dirty"])
    return out


def code_under_test(root: Optional[Path] = None) -> dict:
    """orca_ui's version, commit, branch and dirty flag, and orca_core's as
    :func:`core_state` gives it, as a session records them when it starts."""
    root = root or ui_root()
    ui = checkout_state(root)
    return {"orca_ui": {"version": ui_version(root), "commit": ui["commit"], "branch": ui["branch"],
                        "dirty": ui["dirty"]},
            "orca_core": core_state()}


def code_identity(code: Optional[dict]) -> tuple:
    """What must stay the same for a session's results to belong to one code state."""
    code = code or {}
    ui, core = code.get("orca_ui") or {}, code.get("orca_core") or {}
    return (ui.get("version"), ui.get("commit"), ui.get("dirty"),
            core.get("version"), core.get("source"), core.get("commit"), core.get("dirty"))


# ----- the plan as one commit defines it ------------------------------------------------


@dataclass
class PlanSource:
    features: tuple[str, ...]
    definitions: list[FeatureDefinition]
    plan_files: dict[str, str]
    """Repo path -> sha256, for the plan and every plan it includes."""
    definition_files: dict[str, str]
    base_features: Optional[frozenset[str]]
    """None when there is no loadable base plan."""
    title: str


def load_plan_source(read: Callable[[str], Optional[bytes]], plan_id: str) -> PlanSource:
    """``plan_id`` resolved from files ``read`` returns by repo path (a commit or a folder)."""
    raw: dict = {}
    blobs: dict[str, bytes] = {}

    def text(path: str) -> str:
        blob = read(path)
        if blob is None:
            raise ReportError(f"{path} is missing")
        blobs[path] = blob
        try:
            return blob.decode("utf-8")
        except UnicodeDecodeError as e:
            raise ReportError(f"{path}: {e}")

    def load(pid: str) -> None:
        if pid not in raw:
            path = f"{PLANS_PATH}/{pid}.yaml"
            raw[pid] = cat.plan_from_text(text(path), Path(path).name)
            for included in raw[pid].includes:
                load(included)

    try:
        load(plan_id)
        features = cat.resolve_features(plan_id, raw)
        chain = cat.include_chain(plan_id, raw)
        definitions = [cat.feature_from_text(text(f"{DEFINITIONS_PATH}/{fid}.yaml"), f"{fid}.yaml")
                       for fid in features]
    except cat.CatalogError as e:
        raise ReportError(str(e))
    try:
        load(BASE_PLAN)
        base: Optional[frozenset[str]] = frozenset(cat.resolve_features(BASE_PLAN, raw))
    except (ReportError, cat.CatalogError):
        base = None
    return PlanSource(
        features=features,
        definitions=definitions,
        plan_files={f"{PLANS_PATH}/{p}.yaml": sha256_bytes(blobs[f"{PLANS_PATH}/{p}.yaml"]) for p in chain},
        definition_files={f"{DEFINITIONS_PATH}/{f}.yaml": sha256_bytes(blobs[f"{DEFINITIONS_PATH}/{f}.yaml"])
                          for f in features},
        base_features=base,
        title=raw[plan_id].title,
    )


def commit_reader(repo: Path, commit: str) -> Callable[[str], Optional[bytes]]:
    return lambda path: _git(repo, "show", f"{commit}:{path}", binary=True)


def folder_reader(root: Path) -> Callable[[str], Optional[bytes]]:
    def read(path: str) -> Optional[bytes]:
        try:
            return (root / path).read_bytes()
        except OSError:
            return None
    return read


# ----- export -------------------------------------------------------------------------


def redactor(label: str) -> Callable[[Optional[str]], str]:
    home = str(Path.home())

    def redact(text: Optional[str]) -> str:
        text = str(text or "")
        if home and home != os.sep:
            text = text.replace(home, "~")
        if len(label) >= 3:
            text = text.replace(label, "<hand>")
        return text

    return redact


def hand_facts(hand: dict) -> HandFacts:
    return HandFacts(label=str(hand.get("label") or ""), model_name=hand.get("model_name"),
                     motor_family=hand.get("motor_family"), hardware_version=hand.get("hardware_version"),
                     hardware_version_source=hand.get("hardware_version_source"), side=hand.get("side"),
                     capabilities=tuple(hand.get("capabilities") or ()), mock=bool(hand.get("mock")))


def summarize(steps: list[dict]) -> tuple[dict, str]:
    """Counts per status (``not_applicable`` apart) and the verdict."""
    counts = {s: 0 for s in STATUSES + ("not_applicable",)}
    judged = []
    for step in steps:
        if not step["applicable"]:
            counts["not_applicable"] += 1
            continue
        counts[step["status"]] = counts.get(step["status"], 0) + 1
        if step["kind"] != "observe":
            judged.append(step["status"])
    if "fail" in judged:
        verdict = "fail"
    elif judged and all(s == "pass" for s in judged):
        verdict = "pass"
    else:
        verdict = "incomplete"
    return counts, verdict


def build_report(session_path: Path, *, allow_dirty: bool = False, root: Optional[Path] = None) -> dict:
    """The report of the finished session at ``session_path``; raises ReportError when it may not be made.

    ``root`` is the orca_ui checkout exporting it, which must hold the commit
    the session recorded."""
    index = store.read_json(session_path)
    if not isinstance(index, dict) or not index.get("plan_id") or not index.get("stamp"):
        raise ReportError(f"{session_path} is not a stored hardware-test session")
    sid = index.get("id")
    if not index.get("finished_at"):
        raise ReportError(f"session {sid!r} is not finished; end it in the Tests tab first")
    code = index.get("code_under_test")
    if not isinstance(code, dict):
        raise ReportError(f"session {sid!r} has no record of the code it ran on (it was started before "
                          "sessions recorded it); run the plan again")
    if index.get("code_changed"):
        raise ReportError(f"the code changed during session {sid!r}, so its results cannot be exported; "
                          "run the plan again on one commit")
    ui, core = code.get("orca_ui") or {}, code.get("orca_core") or {}
    dirty = [name for name, state in (("orca_ui", ui), ("orca_core", core))
             if (name == "orca_ui" or state.get("source") == "local") and state.get("dirty") is not False]
    if dirty and not allow_dirty:
        raise ReportError(f"the {' and '.join(dirty)} checkout was modified, or not a git checkout, when session "
                          f"{sid!r} started (commit and run the plan again, or pass --allow-dirty to export a "
                          "report verify will reject)")

    root = root or ui_root()
    generator = checkout_state(root)
    if ui.get("commit"):
        if not _commit_exists(root, ui["commit"]):
            raise ReportError(f"the tested orca_ui commit {ui['commit'][:12]} is not in {root}; "
                              "export from the checkout the session ran on")
        read = commit_reader(root, ui["commit"])
    else:
        read = folder_reader(root)
    source = load_plan_source(read, index["plan_id"])

    label = str((index.get("hand") or {}).get("label") or index.get("label") or "")
    redact = redactor(label)
    hand = hand_facts(index.get("hand") or {})
    tests_dir = session_path.resolve().parent.parent
    base_features = source.base_features or frozenset()

    results_sha: dict[str, str] = {}
    steps: list[dict] = []
    for feature in source.definitions:
        result_path = tests_dir / feature.id / index["stamp"] / "result.json"
        stored = store.read_json(result_path)
        stored_steps = {}
        if isinstance(stored, dict):
            if stored.get("session") != index.get("id"):
                raise ReportError(f"{result_path} belongs to session {stored.get('session')!r}, not {index.get('id')!r}")
            results_sha[feature.id] = sha256_file(result_path)
            stored_steps = stored.get("steps") or {}
        for step in feature.steps:
            raw = stored_steps.get(step.id) or {}
            applicable, reason = cat.applicability(step, hand)
            steps.append({
                "id": step.id,
                "feature": feature.id,
                "title": step.title,
                "kind": step.kind,
                "base": feature.id in base_features,
                "applicable": applicable,
                "not_applicable_reason": reason,
                "status": raw.get("status") or "pending",
                "decided_by": raw.get("decided_by") or "",
                "message": redact((raw.get("check") or {}).get("summary")),
                "note": redact(raw.get("note")),
                "started_at": raw.get("started_at"),
                "finished_at": raw.get("finished_at"),
            })
    summary, verdict = summarize(steps)

    events = session_path.with_name(session_path.name[:-len(".json")] + ".events.jsonl")
    main = (index.get("sides") or {}).get("main") or {}
    report = {
        "schema": SCHEMA,
        "generator": {"tool": "orca_ui.hardware_tests.report", "orca_ui_version": ui_version(root),
                      "commit": generator["commit"], "branch": generator["branch"], "dirty": generator["dirty"],
                      "reason": generator["reason"]},
        "code_under_test": {
            "recorded": "at session start",
            "orca_ui": {k: ui.get(k) for k in ("version", "commit", "branch", "dirty")},
            "orca_core": {k: core.get(k) for k in ("version", "source", "commit", "branch", "dirty")},
            "main_side": {"available": bool(main.get("available")), "version": main.get("version"),
                          "reason": redact(main.get("reason")) or None},
        },
        "plan": {
            "id": index["plan_id"],
            "title": source.title,
            "features": list(source.features),
            "plan_files": source.plan_files,
            "definition_files": source.definition_files,
        },
        "hand": {
            "model_name": hand.model_name, "side": hand.side, "motor_family": hand.motor_family,
            "hardware_version": hand.hardware_version, "hardware_version_source": hand.hardware_version_source,
            "mock": hand.mock, "capabilities": list(hand.capabilities),
            "label_sha256": sha256_bytes(label.encode("utf-8")),
        },
        "session": {
            "id": index.get("id"),
            "started_at": index.get("started_at"),
            "finished_at": index.get("finished_at"),
            "code_changed": bool(index.get("code_changed")),
            "events_sha256": sha256_file(events),
            "results_sha256": results_sha,
        },
        "steps": steps,
        "summary": summary,
        "verdict": verdict,
    }
    report["integrity"] = {"sha256": integrity_hash(report),
                           "canonical": "JSON without 'integrity', sorted keys, no spaces, UTF-8"}
    return report


def report_name(report: dict) -> str:
    """``<YYYY-MM-DD>_<plan id>_<model_name>_<motor_family>.json``, dated when the session started."""
    day = str(report["session"].get("started_at") or "")[:10] or "undated"
    parts = (day, report["plan"]["id"], report["hand"].get("model_name") or "unknown-model",
             report["hand"].get("motor_family") or "unknown-motors")
    return "_".join(store.safe_name(str(p)) for p in parts) + ".json"


def export(session_path: Path, *, out: Optional[Path] = None, out_dir: Optional[Path] = None,
           allow_dirty: bool = False, root: Optional[Path] = None) -> Path:
    report = build_report(session_path, allow_dirty=allow_dirty, root=root)
    target = out if out is not None else Path(out_dir) / report_name(report)
    store.write_text(target, dumps(report))
    return target


# ----- verify -------------------------------------------------------------------------


class _Findings:
    def __init__(self):
        self.problems: list[str] = []
        self.notes: list[str] = []

    def problem(self, text: str) -> None:
        self.problems.append(text)

    def note(self, text: str) -> None:
        self.notes.append(text)


def _commit_exists(repo: Path, commit: str) -> bool:
    return _git(repo, "cat-file", "-e", f"{commit}^{{commit}}") is not None


def _commit_time(repo: Path, commit: str) -> Optional[datetime]:
    text = _git(repo, "show", "-s", "--format=%cI", commit)
    try:
        return datetime.fromisoformat(text) if text else None
    except ValueError:
        return None


def _changed(repo: Path, a: str, b: str) -> Optional[list[str]]:
    text = _git(repo, "diff", "--name-only", "--no-renames", a, b)
    return None if text is None else [line for line in text.splitlines() if line]


def _check_steps(report: dict, f: _Findings, kinds: dict[str, str], base: dict[str, bool]) -> None:
    for step in report.get("steps") or []:
        sid, status, who = step.get("id"), step.get("status"), step.get("decided_by")
        kind = kinds.get(sid, step.get("kind"))
        if not step.get("applicable") or kind == "observe":
            continue
        if status == "fail":
            f.problem(f"step {sid} failed: {step.get('message') or step.get('note') or 'no message'}")
            continue
        if status not in ("pass", "skipped"):
            f.problem(f"step {sid} is {status}, not decided")
            continue
        if kind in ("auto", "compare") and who != "check":
            f.problem(f"step {sid} is a {kind} step but was decided by {who or 'nobody'}, not by its check")
        if kind == "manual" and who != "person":
            f.problem(f"step {sid} is a manual step but was decided by {who or 'nobody'}, not by a person")
        if status == "skipped":
            reason = step.get("note") or (step.get("message") if who == "check" else "")
            if not str(reason or "").strip():
                f.problem(f"step {sid} was skipped without a note saying why")
            if base.get(sid, step.get("base")):
                f.problem(f"step {sid} belongs to the base plan and may not be skipped")


def _check_plan(report: dict, f: _Findings, ui_repo: Path, commit: str) -> tuple[dict, dict]:
    """Compare the report's plan and steps with the tested commit's files.

    Returns step id -> kind and step id -> in base, as the commit defines them."""
    plan = report.get("plan") or {}
    try:
        source = load_plan_source(commit_reader(ui_repo, commit), str(plan.get("id")))
    except ReportError as e:
        f.problem(f"the plan does not load from the tested orca_ui commit {commit[:12]}: {e}")
        return {}, {}
    if (plan.get("plan_files") or {}) != source.plan_files:
        f.problem("the plan files' sha256 differ from the tested commit's (a plan edited after testing?)")
    if (plan.get("definition_files") or {}) != source.definition_files:
        f.problem("the definition files' sha256 differ from the tested commit's (a step edited after testing?)")
    if list(plan.get("features") or []) != list(source.features):
        f.problem("the report's feature list is not what the tested commit's plan resolves to")
    if source.base_features is None:
        f.problem("the tested orca_ui commit has no loadable base plan")
    elif not source.base_features <= set(source.features):
        f.problem(f"plan {plan.get('id')!r} does not include the base plan")

    hand = hand_facts(report.get("hand") or {})
    kinds, base, expected = {}, {}, []
    for feature in source.definitions:
        for step in feature.steps:
            kinds[step.id] = step.kind
            base[step.id] = feature.id in (source.base_features or ())
            expected.append((step.id, feature.id, step.kind, cat.applicability(step, hand)[0]))
    listed = [(s.get("id"), s.get("feature"), s.get("kind"), s.get("applicable")) for s in report.get("steps") or []]
    if listed != expected:
        missing = [e[0] for e in expected if e not in listed]
        extra = [s[0] for s in listed if s not in expected]
        f.problem("the report's steps differ from the tested plan's (id, feature, kind, applicable): "
                  f"missing or changed {missing or '-'}, unexpected {extra or '-'}")
    return kinds, base


def _main_ref(repo: Path) -> Optional[str]:
    for ref in ("origin/main", "main"):
        if _git(repo, "rev-parse", "--verify", "--quiet", ref) is not None:
            return ref
    return None


def _check_relation(f: _Findings, repo: Path, target: str, tested: str, head: str, tests_branch: str) -> None:
    """The PR head adds nothing but reports to the tested code (see :func:`verify`)."""
    def reports_only(paths: list[str]) -> list[str]:
        return [p for p in paths if not p.startswith(REPORTS_DIR + "/")]

    mb = _git(repo, "merge-base", tested, head)
    if mb is None:
        f.problem(f"the tested commit {tested[:12]} and the PR head {head[:12]} share no history")
        return
    if mb == tested:
        f.note(f"relation: the tested commit {tested[:12]} is an ancestor of the PR head {head[:12]}")
    elif target != "orca_ui":
        f.problem(f"the tested orca_core commit {tested[:12]} is not an ancestor of the PR head {head[:12]}")
        return
    elif mb == head:
        f.note(f"relation: the PR head {head[:12]} is an ancestor of the tested commit {tested[:12]} "
               f"(the PR with {tests_branch} merged in)")
    else:
        f.note(f"relation: the tested commit {tested[:12]} is the PR at {mb[:12]} with {tests_branch} merged in, "
               f"and the PR head {head[:12]} has commits since")
    after = _changed(repo, mb, head)
    if after is None:
        f.problem("could not list the files the PR changed after testing")
    elif reports_only(after):
        f.problem(f"the PR changed files besides {REPORTS_DIR}/ after testing: {', '.join(reports_only(after)[:10])}")
    if mb == tested:
        return
    main = _main_ref(repo)
    branch_base = _git(repo, "merge-base", tests_branch, main) if main else None
    allowed = _changed(repo, branch_base, tests_branch) if branch_base else None
    if allowed is None:
        f.problem(f"cannot tell what {tests_branch} changes relative to main in {repo}")
        return
    merged = _changed(repo, mb, tested) or []
    stray = [p for p in merged if p not in allowed and not p.startswith("orca_ui/webui/")]
    if stray:
        f.problem(f"the tested commit differs from the PR in files {tests_branch} does not change: "
                  f"{', '.join(stray[:10])}")


def _target_of(repo: Path, head: str) -> Optional[str]:
    for name in ("orca_ui", "orca_core"):
        if _git(repo, "cat-file", "-e", f"{head}:{name}/__init__.py") is not None:
            return name
    return None


def verify(report: dict, *, repo: Optional[Path] = None, expect_commit: Optional[str] = None,
           tests_branch: str = DEFAULT_TESTS_BRANCH, ui_repo: Optional[Path] = None,
           target: Optional[str] = None) -> _Findings:
    """Every problem with ``report``; none means VERIFIED.

    With ``repo`` (a checkout of the repo the PR targets, ``expect_commit``
    its head), the tested commit must be an ancestor of the head with only
    reports added since; for orca_ui, the head may instead lead to the tested
    commit through a local merge of ``tests_branch``, changing only that
    branch's files and the rebuilt bundle.
    """
    f = _Findings()
    if not isinstance(report, dict) or report.get("schema") != SCHEMA:
        f.problem(f"unknown schema {report.get('schema') if isinstance(report, dict) else None!r} (expected {SCHEMA})")
        return f
    if (report.get("integrity") or {}).get("sha256") != integrity_hash(report):
        f.problem("the integrity hash does not match the report's contents (edited after export?)")
    steps = report.get("steps") or []
    try:
        summary, verdict = summarize(steps)
    except (KeyError, TypeError):
        f.problem("the steps are malformed")
        return f
    if summary != report.get("summary"):
        f.problem("the summary does not match the steps")
    if verdict != report.get("verdict"):
        f.problem(f"the verdict {report.get('verdict')!r} does not match the steps ({verdict!r})")

    if (report.get("session") or {}).get("code_changed") is not False:
        f.problem("the report does not say the code stayed the same during the session")
    if (report.get("hand") or {}).get("mock") is not False:
        f.problem("the session ran on a mock hand; a real hand is required")
    code = report.get("code_under_test") or {}
    ui, core = code.get("orca_ui") or {}, code.get("orca_core") or {}
    if not ui.get("commit"):
        f.problem("no orca_ui commit is recorded")
    if ui.get("dirty") is not False:
        f.problem("the orca_ui checkout was modified (dirty) or its state is unknown")
    if core.get("source") not in ("pypi", "local"):
        f.problem(f"orca_core came from {core.get('source')!r}; it must be the published release or a local checkout")
    if core.get("source") == "local" and (not core.get("commit") or core.get("dirty") is not False):
        f.problem("the local orca_core checkout has no commit recorded, or was modified (dirty)")

    target = target or (_target_of(repo, expect_commit or "HEAD") if repo else None)
    if repo and target is None:
        f.problem(f"{repo} at {expect_commit or 'HEAD'} is neither orca_ui nor orca_core")
    ui_repo = ui_repo or (repo if target == "orca_ui" else ui_root())

    kinds: dict[str, str] = {}
    base: dict[str, bool] = {}
    if ui.get("commit"):
        if _commit_exists(ui_repo, ui["commit"]):
            kinds, base = _check_plan(report, f, ui_repo, ui["commit"])
        else:
            f.problem(f"the tested orca_ui commit {ui['commit'][:12]} is not in {ui_repo}; "
                      "the plan and definitions cannot be checked")
    _check_steps(report, f, kinds, base)

    started = _parse_time((report.get("session") or {}).get("started_at"))
    checked_times = []
    if ui.get("commit") and _commit_exists(ui_repo, ui["commit"]):
        checked_times.append((ui_repo, ui["commit"]))

    if repo:
        head = _git(repo, "rev-parse", "--verify", f"{expect_commit or 'HEAD'}^{{commit}}")
        tested = ui.get("commit") if target == "orca_ui" else core.get("commit")
        if head is None:
            f.problem(f"the PR head {expect_commit or 'HEAD'} is not in {repo}")
        elif target == "orca_core" and core.get("source") != "local":
            f.problem("the session ran the published orca_core, not the orca_core PR's code")
        elif not tested:
            f.problem(f"no tested {target} commit is recorded")
        elif not _commit_exists(repo, tested):
            f.problem(f"the tested {target} commit {tested[:12]} is not in {repo}")
        elif target:
            f.note(f"target: {target} PR, head {head[:12]}, tested commit {tested[:12]}")
            _check_relation(f, repo, target, tested, head, tests_branch)
            checked_times.append((repo, tested))
    else:
        f.note("no --repo given: the tested commit was not compared with a PR head")

    for where, commit in dict.fromkeys(checked_times):
        committed = _commit_time(where, commit)
        if started is None or committed is None:
            f.problem(f"cannot compare the session's start with commit {commit[:12]}'s time")
        elif started <= committed:
            f.problem(f"the session started ({started.isoformat()}) before commit {commit[:12]} was made "
                      f"({committed.isoformat()})")
    return f


def _parse_time(text) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(text))
    except ValueError:
        return None


# ----- command line ---------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m orca_ui.hardware_tests.report",
                                     description="Export or verify a hardware-test report.")
    sub = parser.add_subparsers(dest="command", required=True)
    ex = sub.add_parser("export", help="build a report from a stored, finished session")
    ex.add_argument("session", type=Path, help="the session's index, <bench>/<hand>/tests/sessions/<stamp> <plan>.json")
    where = ex.add_mutually_exclusive_group(required=True)
    where.add_argument("--out", type=Path, help="the report file to write")
    where.add_argument("--out-dir", type=Path,
                       help=f"a folder (e.g. {REPORTS_DIR}/) to write <date>_<plan>_<model>_<motors>.json into")
    ex.add_argument("--allow-dirty", action="store_true",
                    help="export a session whose checkout was modified when it started; "
                         "the report records it and verify rejects it")
    ve = sub.add_parser("verify", help="check a report strictly; exit 0 only when VERIFIED")
    ve.add_argument("report", type=Path)
    ve.add_argument("--repo", type=Path, help="a checkout of the repo the PR targets (orca_ui or orca_core)")
    ve.add_argument("--expect-commit", help="the PR head (default: HEAD of --repo)")
    ve.add_argument("--tests-branch", default=DEFAULT_TESTS_BRANCH,
                    help=f"the hardware-tests branch merged in for orca_ui PRs (default {DEFAULT_TESTS_BRANCH})")
    ve.add_argument("--ui-repo", type=Path,
                    help="the orca_ui checkout holding the tested commit, for orca_core PRs "
                         "(default: the checkout this module runs from)")
    ve.add_argument("--target", choices=("orca_ui", "orca_core"),
                    help="which repo --repo is (default: told from its files)")
    args = parser.parse_args(argv)

    if args.command == "export":
        try:
            path = export(args.session, out=args.out, out_dir=args.out_dir, allow_dirty=args.allow_dirty)
        except (ReportError, cat.CatalogError) as e:
            print(f"export refused: {e}", file=sys.stderr)
            return 1
        report = json.loads(path.read_text(encoding="utf-8"))
        print(f"wrote {path} (verdict {report['verdict']})")
        return 0

    try:
        report = json.loads(args.report.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"problem: cannot read {args.report}: {e}")
        print("REJECTED (1 problems)")
        return 1
    findings = verify(report, repo=args.repo, expect_commit=args.expect_commit, tests_branch=args.tests_branch,
                      ui_repo=args.ui_repo, target=args.target)
    for line in findings.notes:
        print(f"note: {line}")
    for line in findings.problems:
        print(f"problem: {line}")
    if findings.problems:
        print(f"REJECTED ({len(findings.problems)} problems)")
        return 1
    print("VERIFIED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
