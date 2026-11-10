"""Run recorder scenarios with main's and with the branch's orca_core.

``compare`` checks run one scenario twice on the same hand: once under main's
orca_core checkout and once under the branch's, each in that checkout's own
environment (``uv run --project <checkout>``), through the standalone
``recorder.py``. The branch is the checkout the console itself imports; main
is a second checkout beside it (``settings.main_core``, ``$ORCA_CORE_MAIN``,
or ``<branch parent>/worktrees/orca_core-main``).

While a scenario that needs the hand runs, the console lets go of it
(``service.disconnect()``) and takes it back afterwards. Each run gets its own
copy of the side's packaged config for the hand's model, with the hand's
calibration beside it; the step's overrides go into that copy only.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Mapping, Optional

import yaml

from orca_ui.hardware_tests.checks.base import StopRequested

SIDES = ("main", "branch")
RECORDER = Path(__file__).with_name("recorder.py")
MAIN_ENV = "ORCA_CORE_MAIN"
MAIN_WORKTREE = Path("worktrees") / "orca_core-main"

HAND_SCENARIOS = frozenset({"detect", "calibrate", "neutral", "tension_hold", "joint_loop",
                            "tactile_health", "guided_tension_gate"})
"""Scenarios that open the hand's ports, so the console must let go of them first."""
NO_CONFIG_SCENARIOS = frozenset({"detect", "load_configs"})

SCENARIO_TIMEOUT_S = {
    "detect": 120.0, "load_configs": 180.0, "load_config": 60.0, "calibrate": 1200.0,
    "neutral": 300.0, "tension_hold": 300.0, "joint_loop": 300.0, "tactile_health": 120.0,
    "guided_tension_gate": 120.0,
}
DEFAULT_TIMEOUT_S = 600.0
ENV_PREPARE_TIMEOUT_S = 900.0
"""The first run in a checkout builds its environment, which can take minutes."""
STOP_GRACE_S = 20.0
"""How long a recorder gets to wind down (torque off, disconnect) after the stop file."""
TERM_GRACE_S = 5.0
RELEASE_WAIT_S = 10.0
RELEASE_SETTLE_S = 1.0
"""Time for the operating system to free the serial ports after the console closes them."""
RECONNECT_WAIT_S = 30.0
OUTPUT_TAIL_CHARS = 20_000
CHILD_ENV_DROP = ("VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME", "UV_PROJECT_ENVIRONMENT", "UV_PYTHON")
LOG_PREFIX = "[recorder] "


class SideUnavailable(RuntimeError):
    """The requested side cannot run; the message says why."""


# ----- checkouts --------------------------------------------------------------------------------


@dataclass(frozen=True)
class Checkout:
    path: Optional[Path]
    reason: Optional[str] = None
    version: Optional[str] = None


def is_checkout(path: Path) -> bool:
    return (path / "pyproject.toml").is_file() and (path / "orca_core" / "__init__.py").is_file()


def checkout_version(path: Path) -> Optional[str]:
    try:
        text = (path / "pyproject.toml").read_text()
    except OSError:
        return None
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return match.group(1) if match else None


def _display(path: Path) -> str:
    home = str(Path.home())
    text = str(path)
    return "~" + text[len(home):] if text == home or text.startswith(home + os.sep) else text


def branch_checkout(source) -> Checkout:
    """The checkout the console imports orca_core from, when it is a local one."""
    if source is None:
        return Checkout(None, "could not tell where the console's orca_core comes from")
    if getattr(source, "kind", None) != "local" or not getattr(source, "location", None):
        return Checkout(None, (
            f"the console runs a {getattr(source, 'kind', 'unknown')} orca_core "
            f"({getattr(source, 'version', '?')}), not a checkout; start it with ./dev local "
            "to test the branch"))
    path = Path(source.location).expanduser().resolve()
    if not is_checkout(path):
        return Checkout(None, f"{_display(path)} is not an orca_core checkout")
    return Checkout(path, None, checkout_version(path))


def main_checkout(branch: Checkout, configured: Optional[str],
                  environ: Mapping[str, str]) -> Checkout:
    """main's checkout: the setting, else ``$ORCA_CORE_MAIN``, else the conventional worktree."""
    if configured:
        candidate, origin = Path(configured), "settings (--main-core)"
    elif environ.get(MAIN_ENV):
        candidate, origin = Path(environ[MAIN_ENV]), f"${MAIN_ENV}"
    elif branch.path is not None:
        candidate, origin = branch.path.parent / MAIN_WORKTREE, None
    else:
        return Checkout(None, "main's checkout is found beside the branch's, and there is no branch "
                              "checkout; pass --main-core <path>")
    candidate = candidate.expanduser().resolve()
    if origin is None and not candidate.exists():
        return Checkout(None, (
            f"no main checkout at {_display(candidate)}; create it with "
            f"`git -C {_display(branch.path)} worktree add {_display(candidate)} origin/main`, "
            "or pass --main-core <path>"))
    if not is_checkout(candidate):
        return Checkout(None, f"{_display(candidate)} (from {origin or 'the default location'}) "
                              "is not an orca_core checkout")
    if branch.path is not None and candidate == branch.path:
        return Checkout(None, f"main and the branch are the same checkout ({_display(candidate)})")
    return Checkout(candidate, None, checkout_version(candidate))


# ----- commands ---------------------------------------------------------------------------------


def python_version() -> str:
    return f"{sys.version_info.major}.{sys.version_info.minor}"


def uv_command(uv: str, checkout: Path, python: str, *argv: str) -> list[str]:
    """``python <argv>`` in ``checkout``'s own environment. ``--frozen`` keeps uv
    from rewriting the checkout's lock file."""
    return [uv, "run", "--project", str(checkout), "--frozen", "--no-dev",
            "--python", python, "python", *argv]


def recorder_command(uv: str, checkout: Path, python: str, scenario: str, args_file: Path,
                     out_dir: Path, *, mock: bool) -> list[str]:
    argv = [str(RECORDER), scenario, "--args-json", str(args_file), "--out", str(out_dir)]
    if mock:
        argv.append("--mock")
    return uv_command(uv, checkout, python, *argv)


def child_env(environ: Mapping[str, str]) -> dict:
    """The console's environment minus what would point a child at the console's own venv."""
    env = {k: v for k, v in environ.items() if k not in CHILD_ENV_DROP}
    env["PYTHONUNBUFFERED"] = "1"
    return env


# ----- configs ----------------------------------------------------------------------------------


def model_location(config_path: Path) -> tuple[Optional[str], str]:
    """``(version folder, model name)`` of a config, e.g. ``("v2", "orcahand-right")``;
    the version is ``None`` when the config does not sit in a ``models/<version>/`` tree."""
    model_dir = config_path.parent
    version_dir = model_dir.parent
    in_models = version_dir.parent.name == "models"
    return (version_dir.name if in_models else None), model_dir.name


def packaged_config(checkout: Path, model_name: str, version: Optional[str]) -> Optional[Path]:
    """The checkout's packaged ``config.yaml`` for ``model_name``: under ``version`` when
    given, else under the newest version folder that has the model."""
    models = checkout / "orca_core" / "models"
    if version:
        path = models / version / model_name / "config.yaml"
        return path if path.is_file() else None
    found = sorted(models.glob(f"*/{model_name}/config.yaml"),
                   key=lambda p: _version_key(p.parent.parent.name))
    return found[-1] if found else None


def _version_key(name: str) -> tuple:
    return tuple(int(n) for n in re.findall(r"\d+", name)) or (0,)


def copy_config(source: Path, dest_dir: Path, *, calibration: Optional[Path] = None,
                overrides: Optional[Mapping] = None) -> Path:
    """Copy ``source`` into ``dest_dir`` with ``calibration`` beside it and
    ``overrides`` applied to the copy's top-level keys; returns the copy's path."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / "config.yaml"
    shutil.copyfile(source, target)
    if calibration is not None and calibration.is_file():
        shutil.copyfile(calibration, dest_dir / "calibration.yaml")
    if overrides:
        data = yaml.safe_load(target.read_text()) or {}
        data.update(dict(overrides))
        tmp = dest_dir / ".config.yaml.tmp"
        tmp.write_text(yaml.safe_dump(data, sort_keys=False))
        os.replace(tmp, target)
    return target


def file_digest(path: Path) -> Optional[str]:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


# ----- process ----------------------------------------------------------------------------------


@dataclass
class ProcessOutcome:
    returncode: Optional[int]
    duration_s: float
    timed_out: bool = False
    stopped: bool = False

    def as_dict(self) -> dict:
        return {"returncode": self.returncode, "duration_s": round(self.duration_s, 3),
                "timed_out": self.timed_out, "stopped": self.stopped}


class _LineForwarder:
    """Forwards new recorder lines from a growing log file to the live log."""

    def __init__(self, path: Path, log: Callable[[str], None], prefix: str):
        self._path = path
        self._log = log
        self._prefix = prefix
        self._offset = 0
        self._partial = ""

    def poll(self) -> None:
        try:
            with open(self._path, "rb") as fh:
                fh.seek(self._offset)
                chunk = fh.read()
        except OSError:
            return
        if not chunk:
            return
        self._offset += len(chunk)
        text = self._partial + chunk.decode("utf-8", "replace")
        lines = text.split("\n")
        self._partial = lines.pop()
        for line in lines:
            if line.startswith(LOG_PREFIX):
                self._log(self._prefix + line[len(LOG_PREFIX):])


def _signal_group(proc: subprocess.Popen, sig: int) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
        if hasattr(os, "killpg"):
            os.killpg(proc.pid, sig)
        elif sig == getattr(signal, "SIGKILL", None):
            proc.kill()
        else:
            proc.terminate()


def run_process(cmd: list[str], *, cwd: Path, env: Mapping[str, str], stdout_path: Path,
                stderr_path: Path, timeout_s: float, stop_event: threading.Event,
                stop_file: Optional[Path] = None, forward: Optional[_LineForwarder] = None,
                stop_grace_s: float = STOP_GRACE_S, term_grace_s: float = TERM_GRACE_S,
                poll_s: float = 0.2) -> ProcessOutcome:
    """Run ``cmd`` to the end, its output in two files. On a stop or the timeout it
    first creates ``stop_file`` (when given) and waits ``stop_grace_s`` for a clean
    exit, then SIGTERMs and finally SIGKILLs the process group."""
    start = time.monotonic()
    timed_out = stopped = False
    wind_down_until: Optional[float] = None
    kill_at: Optional[float] = None
    with open(stdout_path, "wb") as out, open(stderr_path, "wb") as err:
        proc = subprocess.Popen(cmd, cwd=str(cwd), env=dict(env), stdout=out, stderr=err,
                                stdin=subprocess.DEVNULL, start_new_session=True)
        while True:
            try:
                returncode = proc.wait(timeout=poll_s)
                break
            except subprocess.TimeoutExpired:
                pass
            if forward is not None:
                forward.poll()
            now = time.monotonic()
            if wind_down_until is None:
                if stop_event.is_set():
                    stopped = True
                elif now - start > timeout_s:
                    timed_out = True
                if stopped or timed_out:
                    if stop_file is not None:
                        stop_file.touch()
                        wind_down_until = now + stop_grace_s
                    else:
                        wind_down_until = now
            elif kill_at is None and now >= wind_down_until:
                _signal_group(proc, signal.SIGTERM)
                kill_at = now + term_grace_s
            elif kill_at is not None and now >= kill_at:
                _signal_group(proc, getattr(signal, "SIGKILL", signal.SIGTERM))
                returncode = proc.wait()
                break
    if forward is not None:
        forward.poll()
    return ProcessOutcome(returncode, time.monotonic() - start, timed_out, stopped)


def _tail(path: Path, limit: int = OUTPUT_TAIL_CHARS) -> str:
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return ""
    return text[-limit:]


# ----- the runner -------------------------------------------------------------------------------


class SideRunner:
    """Runs recorder scenarios and orca_core scripts with either side's orca_core.

    Implements :class:`~orca_ui.hardware_tests.checks.base.SideRunner`; also
    offers :meth:`version`, :meth:`describe`, :meth:`run_script`,
    :meth:`config_source` and :meth:`hand_released` to the checks that need them.
    """

    def __init__(self, service, settings, *, log: Callable[[str], None],
                 stop_event: threading.Event, checkouts: Mapping[str, Checkout],
                 uv: Optional[str], python: Optional[str] = None,
                 environ: Optional[Mapping[str, str]] = None):
        self.service = service
        self.settings = settings
        self._log = log
        self._stop_event = stop_event
        self._checkouts = dict(checkouts)
        self._uv = uv
        self._python = python or python_version()
        self._env = child_env(os.environ if environ is None else environ)
        self._mock = bool(getattr(settings, "mock", False))
        self._prepared: dict[str, Optional[str]] = {}
        self._release_depth = 0
        self.release_settle_s = 0.0 if self._mock else RELEASE_SETTLE_S

    # ----- what is available --------------------------------------------------------------

    def available(self, side: str) -> Optional[str]:
        if side not in SIDES:
            return f"unknown side {side!r}"
        if self._uv is None:
            return "uv is not on PATH; it runs each side in its own environment"
        checkout = self._checkouts.get(side)
        if checkout is None or checkout.path is None:
            return (checkout.reason if checkout else None) or f"no {side} checkout"
        return self._prepared.get(side)

    def version(self, side: str) -> Optional[str]:
        checkout = self._checkouts.get(side)
        return checkout.version if checkout else None

    def checkout(self, side: str) -> Optional[Path]:
        checkout = self._checkouts.get(side)
        return checkout.path if checkout else None

    def describe(self) -> dict:
        out = {}
        for side in SIDES:
            reason = self.available(side)
            path = self.checkout(side)
            out[side] = {"available": reason is None, "reason": reason,
                         "version": self.version(side),
                         "checkout": _display(path) if path else None}
        return out

    def _require(self, side: str) -> Path:
        reason = self.available(side)
        if reason is not None:
            raise SideUnavailable(f"{side}'s orca_core is not available: {reason}")
        return self._checkouts[side].path

    # ----- configs --------------------------------------------------------------------------

    def console_config(self) -> Optional[Path]:
        """The config.yaml the console's hand runs with."""
        config = getattr(getattr(self.service, "supervisor", None), "config", None)
        path = getattr(config, "config_path", None) or getattr(self.settings, "config_path", None)
        return Path(path) if path else None

    def config_source(self, side: str) -> tuple[Path, str]:
        """``(config.yaml to copy, where it came from)`` for the hand's model on ``side``.

        The side's packaged config for the console's model; a model no checkout
        packages (the console's own mock model) falls back to the console's config."""
        console = self.console_config()
        if console is None:
            raise RuntimeError("the console has no config for the hand")
        version, name = model_location(console)
        version = version or getattr(self.settings, "model_version", None)
        packaged = packaged_config(self._require(side), name, version)
        if packaged is not None:
            return packaged, "packaged"
        if self._mock and console.is_file():
            return console, "console"
        raise RuntimeError(f"{side}'s orca_core packages no model {name!r}"
                           + (f" under {version}" if version else ""))

    def prepare_config(self, side: str, out_dir: Path,
                       overrides: Optional[Mapping] = None) -> Path:
        """Copy the side's config for the hand into ``out_dir/config`` with the hand's
        calibration beside it, apply ``overrides``, and return the copy's path."""
        source, origin = self.config_source(side)
        console = self.console_config()
        calibration = console.parent / "calibration.yaml" if console else None
        path = copy_config(source, out_dir / "config", calibration=calibration,
                           overrides=overrides)
        (out_dir / "config" / "source.json").write_text(json.dumps({
            "config": str(source), "origin": origin,
            "calibration": str(calibration) if calibration and calibration.is_file() else None,
            "overrides": dict(overrides or {}),
        }, indent=2))
        return path

    # ----- the hand -------------------------------------------------------------------------

    def console_motor_port(self) -> Optional[str]:
        """The motor port the console's hand is on, so a run can refuse another hand."""
        supervisor = getattr(self.service, "supervisor", None)
        try:
            ports = supervisor.status().ports if supervisor is not None else {}
        except Exception:
            return None
        port = (ports or {}).get("motor")
        return port if port and port != "mock" else None

    @contextlib.contextmanager
    def hand_released(self) -> Iterator[None]:
        """Hold the console off the hand's ports for the duration; nests."""
        if self._release_depth:
            self._release_depth += 1
            try:
                yield
            finally:
                self._release_depth -= 1
            return
        manager = getattr(self.service, "operation_manager", None)
        if manager is not None and manager.active():
            raise RuntimeError("an operation is running in the console; stop it before the "
                               "check releases the hand")
        self._log("console lets go of the hand")
        self.service.disconnect()
        self._wait(lambda: getattr(self.service, "session", None) is None, RELEASE_WAIT_S)
        if self.release_settle_s:
            time.sleep(self.release_settle_s)
        self._release_depth = 1
        try:
            yield
        finally:
            self._release_depth = 0
            self._log("console takes the hand back")
            try:
                self.service.reconnect()
            except Exception as e:
                self._log(f"reconnect failed: {e}")
            else:
                # Ready, not just connected: the next release must not land while
                # the console is still starting its tactile stream.
                if not self._wait(lambda: self.service.session_ready,
                                  RECONNECT_WAIT_S, stoppable=True):
                    self._log("the console has not reconnected yet; it keeps trying")

    def _wait(self, condition: Callable[[], bool], timeout_s: float, *,
              stoppable: bool = False) -> bool:
        end = time.monotonic() + timeout_s
        while not condition():
            if time.monotonic() > end or (stoppable and self._stop_event.is_set()):
                return False
            time.sleep(0.05)
        return True

    # ----- running ----------------------------------------------------------------------------

    def _prepare_env(self, side: str, out_dir: Path) -> None:
        """Build the side's environment once and check it imports that side's orca_core."""
        if side in self._prepared:
            return
        checkout = self._checkouts[side].path
        self._log(f"{side}: preparing its environment ({_display(checkout)})")
        code = "import os, orca_core; print(os.path.realpath(orca_core.__file__))"
        outcome = run_process(
            uv_command(self._uv, checkout, self._python, "-c", code),
            cwd=out_dir, env=self._env, stdout_path=out_dir / "env.stdout.log",
            stderr_path=out_dir / "env.stderr.log", timeout_s=ENV_PREPARE_TIMEOUT_S,
            stop_event=self._stop_event)
        if outcome.stopped:
            raise StopRequested()
        printed = _tail(out_dir / "env.stdout.log").strip().splitlines()
        imported = Path(printed[-1]) if printed else None
        if outcome.returncode != 0 or imported is None:
            reason = (f"its environment did not start (exit {outcome.returncode}): "
                      + _tail(out_dir / "env.stderr.log", 400).strip())
        elif not imported.is_relative_to(checkout):
            reason = f"its environment imports orca_core from {_display(imported)}, not the checkout"
        else:
            reason = None
        self._prepared[side] = reason
        if reason:
            raise SideUnavailable(f"{side}'s orca_core is not available: {reason}")

    def run(self, side: str, scenario: str, args: dict, out_dir: Path) -> dict:
        """Run ``scenario`` with ``side``'s orca_core and return its ``result.json``.

        ``args["config_overrides"]`` go into the run's config copy. A scenario that
        needs the hand runs while the console has let go of it."""
        checkout = self._require(side)
        if self._stop_event.is_set():
            raise StopRequested()
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        self._prepare_env(side, out_dir)
        args = dict(args)
        overrides = args.pop("config_overrides", None)
        if scenario not in NO_CONFIG_SCENARIOS and "config_path" not in args:
            args["config_path"] = str(self.prepare_config(side, out_dir, overrides))
        stop_file = out_dir / "STOP"
        stop_file.unlink(missing_ok=True)
        (out_dir / "result.json").unlink(missing_ok=True)
        args["stop_file"] = str(stop_file)
        if scenario in HAND_SCENARIOS:
            args.setdefault("expected_motor_port", self.console_motor_port())
        args_file = out_dir / "args.json"
        args_file.write_text(json.dumps(args, indent=2))
        cmd = recorder_command(self._uv, checkout, self._python, scenario, args_file, out_dir,
                               mock=self._mock)
        released = self.hand_released() if scenario in HAND_SCENARIOS else contextlib.nullcontext()
        self._log(f"{side}: {scenario} started")
        with released:
            outcome = run_process(
                cmd, cwd=out_dir, env=self._env, stdout_path=out_dir / "stdout.log",
                stderr_path=out_dir / "stderr.log",
                timeout_s=SCENARIO_TIMEOUT_S.get(scenario, DEFAULT_TIMEOUT_S),
                stop_event=self._stop_event, stop_file=stop_file,
                forward=_LineForwarder(out_dir / "stdout.log", self._log, f"{side}: "))
        result = self._read_result(out_dir, outcome)
        result["runner"] = {**outcome.as_dict(), "side": side, "command": cmd,
                            "out_dir": str(out_dir)}
        self._log(f"{side}: {scenario} {_verdict(result)}")
        if outcome.stopped:
            raise StopRequested()
        return result

    @staticmethod
    def _read_result(out_dir: Path, outcome: ProcessOutcome) -> dict:
        try:
            result = json.loads((out_dir / "result.json").read_text())
            if isinstance(result, dict):
                if outcome.timed_out:
                    result.update(ok=False, error=f"timed out after {outcome.duration_s:.0f} s "
                                                  f"({result.get('error') or 'it was stopped'})")
                return result
        except (OSError, ValueError):
            pass
        why = ("timed out" if outcome.timed_out else "was stopped" if outcome.stopped
               else f"exited with {outcome.returncode}")
        return {"ok": False, "available": True, "stopped": outcome.stopped,
                "error": f"the recorder {why} without writing result.json; see stderr.log: "
                         + _tail(out_dir / "stderr.log", 600).strip()}

    def run_script(self, side: str, script: str, argv: list[str], out_dir: Path, *,
                   timeout_s: float = 60.0) -> dict:
        """Run ``scripts/<script>`` of ``side``'s checkout with ``argv`` (no hand released).

        Returns the exit code, whether it timed out, and the output's tail."""
        checkout = self._require(side)
        if self._stop_event.is_set():
            raise StopRequested()
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        self._prepare_env(side, out_dir)
        stem = Path(script).stem
        cmd = uv_command(self._uv, checkout, self._python,
                         str(checkout / "scripts" / script), *argv)
        outcome = run_process(cmd, cwd=out_dir, env=self._env,
                              stdout_path=out_dir / f"{stem}.stdout.log",
                              stderr_path=out_dir / f"{stem}.stderr.log",
                              timeout_s=timeout_s, stop_event=self._stop_event,
                              term_grace_s=2.0)
        if outcome.stopped:
            raise StopRequested()
        return {**outcome.as_dict(), "command": cmd,
                "stdout": _tail(out_dir / f"{stem}.stdout.log"),
                "stderr": _tail(out_dir / f"{stem}.stderr.log")}

    def scripts(self, side: str) -> list[str]:
        """File names of the side's ``scripts/*.py``."""
        return sorted(p.name for p in (self._require(side) / "scripts").glob("*.py"))


def _verdict(result: dict) -> str:
    if result.get("available") is False:
        return f"not available on this side: {result.get('reason')}"
    if result.get("ok"):
        return "finished"
    return f"failed: {result.get('error')}"


def build_side_runner(service, settings, *, log: Callable[[str], None],
                      stop_event: threading.Event) -> SideRunner:
    """The runner a test session uses: checkouts resolved from the console's orca_core,
    ``settings.main_core`` and ``$ORCA_CORE_MAIN``."""
    from orca_ui.core_source import resolve_cached

    try:
        source = resolve_cached()
    except Exception:
        source = None
    branch = branch_checkout(source)
    main = main_checkout(branch, getattr(settings, "main_core", None), os.environ)
    return SideRunner(service, settings, log=log, stop_event=stop_event,
                      checkouts={"main": main, "branch": branch}, uv=shutil.which("uv"))
