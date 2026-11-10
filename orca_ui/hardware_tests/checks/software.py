"""The software check that closes a merge session: both test suites and the
downstream check, run against the orca_core checkout the console imports and
this orca_ui checkout. It needs no hand and never touches one.
"""

from __future__ import annotations

import os
import re
import sys
import threading
from pathlib import Path
from typing import Optional

from orca_ui.hardware_tests.checks.base import CheckContext, StopRequested, register
from orca_ui.hardware_tests.model import CheckResult, Metric

SUITE_TIMEOUT_S = 1800.0
_PYTEST_TALLY = re.compile(r"(\d+ (?:passed|failed|errors?|skipped)[^\n]*) in [\d.]+s")


def orca_ui_root() -> Path:
    import orca_ui

    return Path(orca_ui.__file__).resolve().parent.parent


def branch_core() -> tuple[Optional[Path], Optional[str]]:
    """The local orca_core checkout the console imports, or why there is none."""
    from orca_ui.core_source import resolve_cached

    source = resolve_cached()
    if source.kind != "local" or not source.location:
        return None, f"the console runs a {source.kind} orca_core, not a local checkout (./dev local)"
    return Path(source.location), None


def repos_root(folder: Path, core: Path, ui: Path) -> Path:
    """A folder of links to the sibling checkouts beside orca_core, with orca_ui
    pointing at this checkout, so the downstream check tests what is merged."""
    folder.mkdir(parents=True, exist_ok=True)
    for sibling in core.parent.iterdir():
        if sibling.is_dir() and not sibling.name.startswith(".") and sibling.name != "orca_ui":
            link = folder / sibling.name
            if not link.exists():
                link.symlink_to(sibling, target_is_directory=True)
    ui_link = folder / "orca_ui"
    if ui_link.is_symlink() or ui_link.exists():
        ui_link.unlink()
    ui_link.symlink_to(ui, target_is_directory=True)
    return folder


def commands(core: Path, ui: Path, links: Path, python: str) -> list[tuple[str, Path, list[str], dict]]:
    env = {"UV_PYTHON": python}
    return [
        ("orca_core suite", core, ["uv", "run", "pytest", "tests/", "-q"], env),
        ("orca_ui suite", ui, ["./dev", "test", "tests", "-q"], {**env, "ORCA_CORE": str(core)}),
        ("downstream", core, ["uv", "run", "python", "tools/check_downstream.py", "--run-tests",
                              "--repos-root", str(links)], env),
    ]


def _env(extra: dict) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in ("VIRTUAL_ENV", "PYTHONPATH")}
    env.update(extra)
    return env


def tally(text: str) -> str:
    """The last pytest summary in ``text``, e.g. ``538 passed, 14 warnings``."""
    found = _PYTEST_TALLY.findall(text)
    return found[-1] if found else ""


@register("software_suites")
def software_suites(ctx: CheckContext) -> CheckResult:
    """S1: orca_core's and orca_ui's suites and the downstream check all exit 0."""
    from orca_ui.hardware_tests.sides import run_process

    core, reason = branch_core()
    if core is None:
        return CheckResult(status="skipped", summary=f"Not run: {reason}.")
    ui = orca_ui_root()
    python = f"{sys.version_info.major}.{sys.version_info.minor}"
    links = repos_root(ctx.out_dir / "repos", core, ui)
    stop = getattr(ctx, "stop_event", None) or threading.Event()
    metrics: list[Metric] = []
    failed: list[str] = []
    runs = commands(core, ui, links, python)
    for index, (name, cwd, cmd, extra) in enumerate(runs):
        ctx.check_stop()
        ctx.progress(index / len(runs), name)
        ctx.log(f"{name}: {' '.join(cmd)} (in {cwd.name})")
        stem = name.replace(" ", "_")
        outcome = run_process(cmd, cwd=cwd, env=_env(extra), stdout_path=ctx.out_dir / f"{stem}.log",
                              stderr_path=ctx.out_dir / f"{stem}.err.log", timeout_s=SUITE_TIMEOUT_S,
                              stop_event=stop)
        if outcome.stopped:
            raise StopRequested()
        text = (ctx.out_dir / f"{stem}.log").read_text(errors="replace")
        ok = outcome.returncode == 0 and not outcome.timed_out
        summary = tally(text) or ("timed out" if outcome.timed_out else f"exit {outcome.returncode}")
        metrics.append(Metric(name, summary, ok=ok))
        metrics.append(Metric(f"{name} time", round(outcome.duration_s), unit="s"))
        ctx.log(f"{name}: {'ok' if ok else 'FAILED'} — {summary}")
        if not ok:
            failed.append(f"{name} ({summary}; see {stem}.log)")
    ctx.progress(1.0, "done")
    details = {"orca_core": str(core), "orca_ui": str(ui), "python": python}
    if failed:
        return CheckResult(status="fail", summary="failed: " + "; ".join(failed) + ".", metrics=metrics,
                           details=details)
    return CheckResult(status="pass", summary="both suites and the downstream check pass.", metrics=metrics,
                       details=details)
