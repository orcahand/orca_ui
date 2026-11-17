"""Start and end an app's process.

An app runs in its own Python environment (often a different Python), so it
is always a child process: the remembered command plus
``--connect <url> --token <token>``. It gets its own process group, and
ending it always signals the whole group, so nothing ``uv run`` started
outlives the console. Windows has no process-group signals: there the group
gets CTRL_BREAK, then ``taskkill /T /F`` takes the tree.
"""

from __future__ import annotations

import atexit
import logging
import os
import shlex
import signal
import subprocess
import threading
import time
from typing import Callable

logger = logging.getLogger(__name__)

STOP_GRACE_S = 1.0   # to exit by itself after the protocol's stop
TERM_GRACE_S = 3.0
KILL_GRACE_S = 2.0

_WINDOWS = os.name == "nt"


def split_command(command: str) -> list[str]:
    """Split a shell-style command; ``~`` at the start of a word is expanded."""
    return [os.path.expanduser(part) for part in shlex.split(command)]


class AppProcess:
    """One app process at a time: spawn, pipe its output, end its group."""

    def __init__(self, on_output: Callable[[str], None]):
        self._on_output = on_output
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        atexit.register(self.terminate)

    def spawn(self, command: str, url: str, token: str) -> int:
        """Start ``command --connect url --token token``; returns the pid.
        Raises RuntimeError when the command can't be started."""
        argv = split_command(command)
        if not argv:
            raise RuntimeError("no command set for this app")
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                raise RuntimeError("an app process is already running")
            logger.info("starting app: %s --connect %s --token ***", command, url)
            try:
                self._proc = subprocess.Popen(
                    argv + ["--connect", url, "--token", token],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                    **_new_group(),
                )
            except OSError as e:
                raise RuntimeError(f"can't start {argv[0]!r}: {e.strerror or e}")
            proc = self._proc
        threading.Thread(target=self._pump, args=(proc,),
                         name="AppOutput", daemon=True).start()
        return proc.pid

    def _pump(self, proc: subprocess.Popen) -> None:
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                self._on_output(line.rstrip("\n"))
        except Exception:
            logger.debug("app output pump ended", exc_info=True)

    def poll(self) -> int | None:
        """Exit code of the app process, or None while it runs (or none was started)."""
        with self._lock:
            proc = self._proc
        return proc.poll() if proc is not None else None

    def terminate(self) -> None:
        """Give the app STOP_GRACE_S to exit, then ask its group to stop, then
        kill what is left. Blocks for at most the three graces; never raises."""
        with self._lock:
            proc = self._proc
            self._proc = None
        if proc is None:
            return
        try:
            if _WINDOWS:
                _end_windows(proc)
            else:
                _end_group(proc)
        except Exception:
            logger.exception("couldn't end app process %s", proc.pid)


def _new_group() -> dict:
    if _WINDOWS:
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _end_group(proc: subprocess.Popen) -> None:
    """POSIX: SIGTERM the process group, then SIGKILL what is left."""
    group = proc.pid
    for sig, grace in ((None, STOP_GRACE_S),
                       (signal.SIGTERM, TERM_GRACE_S),
                       (signal.SIGKILL, KILL_GRACE_S)):
        if not _group_alive(proc, group):
            return
        try:
            if sig is not None:
                os.killpg(group, sig)
        except ProcessLookupError:
            return
        except PermissionError:
            logger.warning("not allowed to signal app process group %s", group)
            return
        if _wait(lambda: not _group_alive(proc, group), grace):
            return
    logger.warning("app process group %s survived SIGKILL", group)


def _end_windows(proc: subprocess.Popen) -> None:
    """Windows: CTRL_BREAK to the group (else terminate), then taskkill the tree."""
    def ask():
        try:
            proc.send_signal(signal.CTRL_BREAK_EVENT)
        except OSError:  # no console to send it through
            proc.terminate()

    def kill():
        try:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                           capture_output=True, timeout=KILL_GRACE_S)
        except (OSError, subprocess.SubprocessError):
            logger.warning("taskkill failed for app process %s", proc.pid, exc_info=True)
        try:
            proc.kill()
        except OSError:
            pass  # gone already

    for step, grace in ((None, STOP_GRACE_S), (ask, TERM_GRACE_S), (kill, KILL_GRACE_S)):
        if proc.poll() is not None:
            return
        if step is not None:
            step()
        if _wait(lambda: proc.poll() is not None, grace):
            return
    logger.warning("app process %s survived taskkill", proc.pid)


def _wait(done: Callable[[], bool], grace: float) -> bool:
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        if done():
            return True
        time.sleep(0.05)
    return False


def _group_alive(proc: subprocess.Popen, group: int) -> bool:
    proc.poll()  # reap the leader, so a finished leader doesn't count
    try:
        os.killpg(group, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
