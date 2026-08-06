"""Fetch and build the orca_teleop checkout the console shells into.

orca_teleop cannot be a dependency of orca_ui: its retargeting stack is heavy
and it caps at Python <3.13 while the console runs on 3.13, so the two can
never share an environment. Without a checkout the Teleop tab's managed mode is
dead, and the only fix used to be a manual clone. This runs it from the UI.

Deliberately NOT an entry in the operations subsystem: operations take a
maintenance lease on the hand and require manual control, whereas this touches
no hardware and has to work with no hand connected at all — the case it exists
for. It is built unconditionally, even under ``--no-teleop``, because that flag
turns off the teleop *manager* and the install is what makes teleop possible in
the first place.
"""

from __future__ import annotations

import logging
import os
import shutil
import signal
import subprocess
import threading
import time
import uuid
from collections import deque
from typing import Callable

from orca_ui.hand.teleop.paths import (
    default_description_dir,
    default_install_dir,
    remember_teleop_dir,
)

logger = logging.getLogger(__name__)

TELEOP_REPO = "https://github.com/orcahand/orca_teleop.git"
TELEOP_BRANCH = "feat/teleop-streamer"
"""The console's ``orca-teleop-streamer`` entry point does not exist on main.
Bump this to main once the branch merges — ``runner.resolve_command`` reports
``no_streamer_entrypoint`` for any checkout that lacks the script, so a wrong
branch is diagnosed rather than discovered at spawn."""

DESCRIPTION_REPO = "https://github.com/orcahand/orcahand_description.git"
"""The retargeter hard-requires this URDF checkout. ``manager._resolve_urdf_dir``
only looks beside the teleop checkout, so an install that skipped it would
report success and then die at retargeter init."""

EXTRAS = ("mediapipe", "adaptive")
LOG_CAP = 500
TERM_GRACE_S = 3.0
KILL_GRACE_S = 2.0

# uv/git inherit the server's environment, which — when the console itself was
# started through `uv run` — points at orca_ui's 3.13 venv. Left in place,
# `uv sync` warns about the mismatch or, with UV_PROJECT_ENVIRONMENT set,
# builds into the wrong venv entirely.
_SCRUBBED_ENV = ("VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT", "PYTHONHOME",
                 "PYTHONPATH")

GIT_BIN = "git"
UV_BIN = "uv"


class InstallError(Exception):
    """Refused before anything ran — the message is user-facing."""


def inspect_target(path: str) -> dict:
    """Classify an install destination without touching it.

    ``empty`` (safe to clone into), ``existing_checkout`` (already orca_teleop —
    adopt it instead of cloning), ``occupied`` (something else is there).
    """
    from orca_ui.hand.teleop.runner import _is_teleop_checkout

    path = os.path.abspath(os.path.expanduser(path))
    if not os.path.exists(path):
        return {"path": path, "state": "empty", "detail": "will be created"}
    if os.path.isfile(path):
        return {"path": path, "state": "occupied", "detail": "path is a file"}
    if _is_teleop_checkout(path):
        return {"path": path, "state": "existing_checkout",
                "detail": "already an orca_teleop checkout"}
    if os.listdir(path):
        return {"path": path, "state": "occupied",
                "detail": "directory exists and is not empty"}
    return {"path": path, "state": "empty", "detail": "existing empty directory"}


def validate_target(path: str) -> str:
    """Absolute, expanded destination — or raise with why it is unusable.

    The path arrives from an HTTP caller and the server can be bound wider than
    localhost, so this is a real check, not a formality. The repo URL and branch
    are constants; the path is the only caller-controlled input.
    """
    if not path or not str(path).strip():
        raise InstallError("no install path given")
    resolved = os.path.abspath(os.path.expanduser(str(path).strip()))
    parent = os.path.dirname(resolved)
    if not os.path.isdir(parent):
        raise InstallError(f"parent directory does not exist: {parent}")
    if not os.access(parent, os.W_OK):
        raise InstallError(f"parent directory is not writable: {parent}")
    import orca_ui
    ui_root = os.path.dirname(os.path.dirname(os.path.abspath(orca_ui.__file__)))
    if resolved == ui_root:
        raise InstallError("refusing to install over the orca_ui checkout")
    state = inspect_target(resolved)["state"]
    if state == "occupied":
        raise InstallError(
            f"{resolved} already exists and is not an orca_teleop checkout")
    return resolved


class TeleopInstaller:
    """One install at a time: clone, build the env, remember the location.

    Threading mirrors ``ChildRunner``: a lock around a ``Popen``, a daemon
    thread pumping output, and the same terminate ladder for cancellation.
    """

    def __init__(self, publish: Callable[[str, dict], None] | None = None,
                 is_teleop_active: Callable[[], bool] | None = None):
        from orca_ui.streaming import topics as T

        self._T = T
        self._publish = publish or (lambda topic, payload: None)
        self._is_teleop_active = is_teleop_active or (lambda: False)
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._cancelled = False
        self._log: deque = deque(maxlen=LOG_CAP)
        self._log_seq = 0
        self._run_id: str | None = None
        self._state = {
            "running": False, "phase": None, "target": None,
            "error": None, "finished": False, "ok": None,
        }

    # ----- snapshot -------------------------------------------------------------

    def snapshot(self) -> dict:
        with self._lock:
            state = dict(self._state)
        state["default_path"] = default_install_dir()
        state["repo"] = TELEOP_REPO
        state["branch"] = TELEOP_BRANCH
        return state

    def log_payload(self) -> dict:
        """Cumulative ``{run_id, next_seq, lines}`` — same scheme as
        operation.log and teleop.log, so the frontend's seq-merge is reused."""
        with self._lock:
            return {"run_id": self._run_id, "next_seq": self._log_seq,
                    "lines": list(self._log)}

    # ----- lifecycle ------------------------------------------------------------

    def start(self, path: str | None = None) -> dict:
        """Begin an install. Raises :class:`InstallError` when refused."""
        target = validate_target(path or default_install_dir())
        if self._is_teleop_active():
            raise InstallError(
                "a teleop session is running — rebuilding its environment "
                "would corrupt the live child; stop teleop first")
        with self._lock:
            if self._state["running"]:
                raise InstallError("an install is already running")
            self._cancelled = False
            self._log.clear()
            # Own run_id space: each install gets a clean pane, and the
            # frontend's seq-merge resets on the change.
            self._log_seq = 0
            self._run_id = f"install:{uuid.uuid4().hex[:8]}"
            self._state = {"running": True, "phase": "starting",
                           "target": target, "error": None,
                           "finished": False, "ok": None}
            self._thread = threading.Thread(
                target=self._run, args=(target,),
                name="TeleopInstall", daemon=True)
        self._emit_state()
        self._append_log(f"installing orca_teleop into {target}")
        self._thread.start()
        return self.snapshot()

    def cancel(self) -> None:
        """Stop an install in flight. Safe to call when nothing is running."""
        with self._lock:
            self._cancelled = True
            proc = self._proc
        if proc is None or proc.poll() is not None:
            return
        self._append_log("cancelling…")
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            return
        try:
            proc.wait(timeout=TERM_GRACE_S)
            return
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            proc.wait(timeout=KILL_GRACE_S)
        except (ProcessLookupError, PermissionError, OSError,
                subprocess.TimeoutExpired):
            pass

    def shutdown(self) -> None:
        self.cancel()

    # ----- the job --------------------------------------------------------------

    def _run(self, target: str) -> None:
        created_dir = not os.path.exists(target)
        adopted = inspect_target(target)["state"] == "existing_checkout"
        try:
            if adopted:
                self._append_log(
                    "existing orca_teleop checkout found — skipping clone")
            else:
                self._set_phase("cloning")
                self._step([GIT_BIN, "clone", "--branch", TELEOP_BRANCH,
                            TELEOP_REPO, target], cwd=None)
                if self._is_cancelled():
                    # Only a tree we created is ours to remove, and only here:
                    # a half-built env is resumable, a half-cloned repo is not.
                    self._cleanup(target, created_dir)
                    return self._finish(False, "cancelled")

            self._set_phase("fetching hand description")
            self._ensure_description(target)
            if self._is_cancelled():
                return self._finish(False, "cancelled")

            self._set_phase("building environment")
            self._append_log(
                "building the teleop environment — mediapipe and pinocchio "
                "are large, this takes a few minutes")
            self._step([UV_BIN, "sync", "--project", target, "--no-progress",
                        *sum((["--extra", e] for e in EXTRAS), [])], cwd=target)
            if self._is_cancelled():
                return self._finish(False, "cancelled")

            # Only now: a remembered path must point at something usable.
            remember_teleop_dir(target)
            self._append_log(f"done — orca_teleop ready at {target}")
            self._finish(True, None)
        except FileNotFoundError as exc:
            missing = getattr(exc, "filename", None) or "a required tool"
            self._finish(False, f"{missing} is not on PATH")
        except InstallError as exc:
            self._finish(False, str(exc))
        except Exception as exc:                      # pragma: no cover
            logger.exception("teleop install failed")
            self._finish(False, str(exc))

    def _ensure_description(self, teleop_dir: str) -> None:
        """Clone orcahand_description beside the checkout when the retargeter
        would not otherwise find it. Non-fatal: teleop's synthetic source runs
        without a URDF, so a failure here degrades rather than blocks."""
        sibling = os.path.join(os.path.dirname(teleop_dir), "orcahand_description")
        for candidate in (sibling, default_description_dir()):
            if os.path.isdir(candidate):
                self._append_log(f"hand description found at {candidate}")
                return
        self._append_log("fetching orcahand_description (retargeter URDF)")
        try:
            self._step([GIT_BIN, "clone", DESCRIPTION_REPO, sibling], cwd=None)
        except Exception as exc:
            self._append_log(
                f"WARNING: could not fetch orcahand_description ({exc}) — "
                f"mediapipe/adaptive sources will fail until it is present "
                f"at {sibling}")

    def _step(self, argv: list[str], cwd: str | None) -> None:
        """Run one subprocess, streaming its output into the log ring."""
        env = {k: v for k, v in os.environ.items() if k not in _SCRUBBED_ENV}
        env["NO_COLOR"] = "1"          # the pane is text, not a terminal
        env["GIT_TERMINAL_PROMPT"] = "0"   # never block waiting for credentials
        self._append_log("$ " + " ".join(argv))
        proc = subprocess.Popen(
            argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            env=env, start_new_session=True, text=True, bufsize=1,
        )
        with self._lock:
            self._proc = proc
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                self._append_log(line.rstrip("\n"))
        finally:
            code = proc.wait()
            with self._lock:
                self._proc = None
        if code != 0 and not self._is_cancelled():
            raise InstallError(f"{os.path.basename(argv[0])} failed (exit {code})")

    def _cleanup(self, target: str, created_dir: bool) -> None:
        if created_dir and os.path.isdir(target):
            shutil.rmtree(target, ignore_errors=True)
            self._append_log(f"removed partial checkout at {target}")

    # ----- state plumbing -------------------------------------------------------

    def _is_cancelled(self) -> bool:
        with self._lock:
            return self._cancelled

    def _set_phase(self, phase: str) -> None:
        with self._lock:
            self._state["phase"] = phase
        self._emit_state()

    def _finish(self, ok: bool, error: str | None) -> None:
        if error:
            self._append_log(f"FAILED: {error}")
        with self._lock:
            self._state.update(running=False, phase=None, finished=True,
                               ok=ok, error=error)
        self._emit_state()

    def _emit_state(self) -> None:
        self._publish(self._T.TELEOP_INSTALL, self.snapshot())

    def _append_log(self, line: str) -> None:
        with self._lock:
            self._log.append({"seq": self._log_seq, "t": time.time(),
                              "line": line})
            self._log_seq += 1
        self._publish(self._T.TELEOP_INSTALL_LOG, self.log_payload())
