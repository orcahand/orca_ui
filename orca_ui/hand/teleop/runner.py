"""Spawn and supervise the orca_teleop streamer child process.

The streamer lives in a *different* Python environment (its retargeter stack
is far too heavy for orca_ui), so it is always launched as a subprocess —
by default through ``uv run --project <orca_teleop checkout>``. Follows the
``browser.py`` precedent: own process group, best-effort cleanup, never let a
child outlive the server.
"""

from __future__ import annotations

import logging
import os
import re
import shlex
import shutil
import signal
import subprocess
import threading
from typing import Callable

from orca_ui.hand.teleop.paths import remembered_teleop_dir

logger = logging.getLogger(__name__)

STREAMER_SCRIPT = "orca-teleop-streamer"
TERM_GRACE_S = 3.0
KILL_GRACE_S = 2.0


_NAME_RE = re.compile(r'^name\s*=\s*["\']orca[-_]teleop["\']', re.MULTILINE)
_SCRIPT_RE = re.compile(r'^\s*%s\s*=' % re.escape(STREAMER_SCRIPT), re.MULTILINE)


def _read_pyproject(teleop_dir: str) -> str | None:
    """First 8 KB of the checkout's pyproject.toml, or None if unreadable.
    Bounded because this runs on every availability probe."""
    try:
        with open(os.path.join(teleop_dir, "pyproject.toml"), encoding="utf-8") as f:
            return f.read(8192)
    except OSError:
        return None


def _is_teleop_checkout(path: str) -> bool:
    """True when ``path`` is an orca_teleop source tree — content-sniffed the
    way ``core_source._is_core_checkout`` does it, so a directory that merely
    has the name does not qualify."""
    text = _read_pyproject(path)
    return bool(text and _NAME_RE.search(text))


def _find_sibling_teleop_dir() -> str | None:
    """Locate an orca_teleop checkout next to the orca_ui repo (the same
    sibling convention as the ``orca_core = {path = "../orca_core"}`` pin)."""
    import orca_ui

    package_dir = os.path.dirname(os.path.abspath(orca_ui.__file__))
    current = package_dir
    for _ in range(4):
        current = os.path.dirname(current)
        candidate = os.path.join(current, "orca_teleop")
        if _is_teleop_checkout(candidate):
            return candidate
    return None


def resolve_command(settings) -> tuple[list[str] | None, str, str]:
    """Resolve the streamer launch command. Returns
    ``(argv_prefix, detail, reason)``; ``argv_prefix`` is None when no runner
    is available, ``detail`` is the human sentence and ``reason`` the
    machine-readable cause the UI branches on.

    Never imports or executes anything from the teleop env — the probe must
    stay instant even when the env would take minutes to build.
    """
    if getattr(settings, "teleop_cmd", None):
        return (shlex.split(settings.teleop_cmd),
                f"command: {settings.teleop_cmd}", "ok")

    teleop_dir = (getattr(settings, "teleop_dir", None)
                  or os.environ.get("ORCA_TELEOP_DIR")
                  or remembered_teleop_dir()
                  or _find_sibling_teleop_dir())
    if not teleop_dir:
        return None, "no orca_teleop checkout found", "no_checkout"
    if not os.path.isdir(teleop_dir):
        # A configured path that isn't there yet is still "nothing to run" —
        # report it as such so the UI offers to fetch one.
        return None, f"no orca_teleop checkout at {teleop_dir}", "no_checkout"
    text = _read_pyproject(teleop_dir)
    if text is None:
        return None, f"no pyproject.toml in {teleop_dir}", "no_pyproject"
    if not _NAME_RE.search(text):
        return None, f"{teleop_dir} is not an orca_teleop checkout", "no_pyproject"
    # A checkout on a branch without the console's entry point (main, today)
    # would otherwise probe as available and fail at spawn.
    if not _SCRIPT_RE.search(text):
        return (None,
                f"{teleop_dir} declares no {STREAMER_SCRIPT} script — this "
                f"checkout is on a branch that predates it",
                "no_streamer_entrypoint")
    if shutil.which("uv") is None:
        return None, "uv not on PATH", "no_uv"
    prefix = ["uv", "run", "--project", teleop_dir,
              "--extra", "mediapipe", "--extra", "adaptive", STREAMER_SCRIPT]
    return prefix, f"uv run --project {teleop_dir}", "ok"


class ChildRunner:
    """One managed child at a time: spawn, capture output, terminate ladder."""

    def __init__(self, settings, on_output: Callable[[str], None] | None = None):
        self._settings = settings
        self._on_output = on_output or (lambda line: None)
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None

    # ----- availability ---------------------------------------------------------

    def availability(self) -> dict:
        argv, detail, reason = resolve_command(self._settings)
        return {"available": argv is not None, "detail": detail,
                "reason": reason}

    def probe_cameras(self, timeout_s: float = 30.0) -> list[dict]:
        """Run the streamer's ``--list-cameras`` probe (cv2 lives in the
        teleop env, not here). Blocking for a few seconds — the probe opens
        each camera once; on macOS the first run doubles as the camera
        permission prompt. Raises RuntimeError when no runner is available
        or the probe fails."""
        import json

        argv_prefix, detail, _reason = resolve_command(self._settings)
        if argv_prefix is None:
            raise RuntimeError(f"teleop runner unavailable — {detail}")
        try:
            result = subprocess.run(
                argv_prefix + ["--list-cameras"],
                capture_output=True, text=True, timeout=timeout_s,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError("camera probe timed out")
        if result.returncode != 0:
            tail = (result.stderr or "").strip().splitlines()[-3:]
            raise RuntimeError("camera probe failed: " + " | ".join(tail))
        # uv chatter goes to stderr; the probe prints one JSON line to stdout.
        for line in reversed(result.stdout.strip().splitlines()):
            line = line.strip()
            if line.startswith("["):
                return json.loads(line)
        raise RuntimeError("camera probe produced no JSON")

    # ----- lifecycle ------------------------------------------------------------

    def spawn(self, argv_suffix: list[str], env_extra: dict[str, str]) -> int:
        """Launch the streamer; returns the pid. Raises RuntimeError when no
        runner is available or a child is already running."""
        argv_prefix, detail, _reason = resolve_command(self._settings)
        if argv_prefix is None:
            raise RuntimeError(f"teleop runner unavailable — {detail}")
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                raise RuntimeError("teleop child already running")
            env = dict(os.environ)
            env.update(env_extra)
            argv = argv_prefix + argv_suffix
            logger.info("spawning teleop child: %s", " ".join(argv))
            self._proc = subprocess.Popen(
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
                start_new_session=True,   # own process group for group kill
                text=True,
                bufsize=1,
            )
            proc = self._proc
        threading.Thread(
            target=self._pump_output, args=(proc,),
            name="TeleopChildLog", daemon=True,
        ).start()
        return proc.pid

    def _pump_output(self, proc: subprocess.Popen) -> None:
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                self._on_output(line.rstrip("\n"))
        except Exception:
            logger.debug("teleop child log pump ended", exc_info=True)

    def poll(self) -> int | None:
        """Child exit code, or None while running / when nothing was spawned."""
        with self._lock:
            proc = self._proc
        return proc.poll() if proc is not None else None

    @property
    def pid(self) -> int | None:
        with self._lock:
            proc = self._proc
        return proc.pid if proc is not None and proc.poll() is None else None

    def terminate(self) -> None:
        """SIGTERM the process group, escalate to SIGKILL. Never raises.

        The manager sends the protocol-level ``stop`` first; this is the
        OS-level ladder for children that don't (or can't) comply.
        """
        with self._lock:
            proc = self._proc
            self._proc = None
        if proc is None or proc.poll() is not None:
            return
        for sig, grace in ((signal.SIGTERM, TERM_GRACE_S),
                           (signal.SIGKILL, KILL_GRACE_S)):
            try:
                os.killpg(proc.pid, sig)
            except (ProcessLookupError, PermissionError):
                return
            try:
                proc.wait(timeout=grace)
                return
            except subprocess.TimeoutExpired:
                continue
        logger.warning("teleop child %s survived SIGKILL grace", proc.pid)
