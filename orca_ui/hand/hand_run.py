"""The rig's hand run as a child process of the console.

``python -m hand_study.run_hand --hand-id <id>`` (orca_core's visual calibration experiment) measures
the hand on the camera rig: about an hour of poses, each photographed by both cameras at every plate
stop, then the joint ranges fit and the accuracy check. It drives the hand and the plate through this
console's own REST API, so the console only starts it, follows its files and kills it. Its process
group (the runner, the plan builder, the solve workers) dies together: on Stop, on E-STOP and when
the console shuts down. Hand and plate torque goes off whenever a run ends. A console that died
without ending its run: the run sees it gone and ends itself (run_hand.watch_console), and the next
console kills a group still recorded in ``active.json`` (``reap_leftover``).
"""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable

from orca_core import hand_store

logger = logging.getLogger(__name__)

LOG_TAIL_BYTES = 4000
ACTIVE_FILE = "active.json"     # the running run's process group, beside the logs
CONSOLE_ENV = "ORCA_UI_PID"     # hand_study.paths.CONSOLE_ENV: the run ends itself when this pid is gone
RIG_ENV = "ORCA_RIG_ID"         # hand_study.paths.RIG_ENV: the rig the console has connected


class HandRun:
    def __init__(self, experiment: Path, ui_url: str, log_dir: Callable[[], Path],
                 safe_off: Callable[[], None], on_end: Callable[[dict], None] | None = None):
        """`safe_off`: hand and plate torque off (never raises); `on_end(state)`: after a run ended on its own."""
        self.experiment = experiment
        self.ui_url = ui_url
        self.log_dir = log_dir
        self.safe_off = safe_off
        self.on_end = on_end
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._starting = False
        self._info: dict = {}

    def alive(self) -> bool:
        """A run is running, or being started (so a check made meanwhile already sees it)."""
        proc = self._proc
        return self._starting or (proc is not None and proc.poll() is None)

    def start(self, hand_id: str, dry: bool = False, limit: int | None = None, rig_id: str | None = None,
              guard: Callable[[], None] | None = None, command: list[str] | None = None) -> dict:
        """Start a run for `hand_id` on the rig `rig_id`. `guard()` raises to refuse; it runs under the
        same lock as the start, while alive() already says True (`command`: another program, for tests).
        RuntimeError if a run is running."""
        with self._lock:
            if self.alive():
                raise RuntimeError("a hand run is already running: stop it first")
            self._starting = True
            try:
                if guard is not None:
                    guard()
                self._launch(hand_id, dry, limit, rig_id, command)
            finally:
                self._starting = False
        proc = self._proc
        threading.Thread(target=self._wait, args=(proc,), name="hand-run", daemon=True).start()
        logger.warning("hand run started for %s (pid %s, log %s)", hand_id, proc.pid, self._info["log"])
        return self.status()

    def _launch(self, hand_id: str, dry: bool, limit: int | None, rig_id: str | None,
                command: list[str] | None) -> None:
        """The run's process in a new session (its own group), its record in ACTIVE_FILE."""
        folder = self.log_dir()
        folder.mkdir(parents=True, exist_ok=True)
        stamp = f"{hand_id}-{time.strftime('%Y%m%d-%H%M%S')}"
        log, k = folder / f"{stamp}.log", 1
        while log.exists():                        # two runs in one second each get their own log
            k += 1
            log = folder / f"{stamp}-{k}.log"
        cmd = command or [sys.executable, "-m", "hand_study.run_hand", "--hand-id", hand_id,
                          *(["--dry"] if dry else []), *(["--limit", str(limit)] if limit else [])]
        # As hand_study.run_hand.run_env gives every process of a run: this ORCA_HOME (absolute) and
        # the experiment on the path; the run adds its own folder and config for its children.
        env = {**os.environ, "ORCA_UI": self.ui_url, hand_store.ORCA_HOME_ENV: str(hand_store.orca_home()),
               CONSOLE_ENV: str(os.getpid()),
               "PYTHONPATH": os.pathsep.join(filter(None, [str(self.experiment), os.environ.get("PYTHONPATH")]))}
        env.pop(RIG_ENV, None)
        if rig_id:
            env[RIG_ENV] = rig_id
        with log.open("ab") as out:
            proc = subprocess.Popen(cmd, cwd=self.experiment, env=env, stdout=out, stderr=subprocess.STDOUT,
                                    stdin=subprocess.DEVNULL, start_new_session=True)
        self._proc = proc
        self._info = {"hand": hand_id, "dry": dry, "pid": proc.pid, "started": time.time(), "log": str(log),
                      "run": None, "ended": None, "returncode": None, "stopped": None}
        try:
            (folder / ACTIVE_FILE).write_text(json.dumps({"pgid": proc.pid, "hand": hand_id, "log": str(log),
                                                          "console": os.getpid(), "started": time.time()}))
        except OSError:
            logger.exception("hand run: could not record its process group")

    def _wait(self, proc: subprocess.Popen) -> None:
        proc.wait()
        with self._lock:
            if self._proc is not proc:
                return
            self._info.update(ended=time.time(), returncode=proc.returncode)
            stopped = self._info["stopped"]
            try:
                (self.log_dir() / ACTIVE_FILE).unlink(missing_ok=True)
            except OSError:
                pass
        logger.warning("hand run ended (exit %s%s)", proc.returncode, f", {stopped}" if stopped else "")
        if stopped:
            return                                 # stop() or E-STOP turns the torque off
        self.safe_off()
        if self.on_end is not None:
            try:
                self.on_end(self.status())
            except Exception:
                logger.exception("hand run: after the run")

    def stop(self, why: str = "stopped", release: bool = True) -> bool:
        """Kill the run's whole process group at once (True if one was running); `release`: hand and
        plate torque off after. Never raises: E-STOP calls it."""
        with self._lock:
            proc = self._proc
            if proc is None or proc.poll() is not None:
                return False
            self._info["stopped"] = why
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        except Exception:
            logger.exception("hand run: kill failed")
        try:
            proc.wait(timeout=5)
        except Exception:
            logger.exception("hand run: did not end after the kill")
        if release:
            self.safe_off()
        return True

    def reap_leftover(self) -> dict | None:
        """At console start: kill a run an earlier console left (its group in active.json, if it still
        has a hand_study process). Returns what was recorded, None when there was nothing."""
        path = self.log_dir() / ACTIVE_FILE
        try:
            left = json.loads(path.read_text())
        except (OSError, ValueError):
            return None
        pgid = int(left.get("pgid") or 0)
        if pgid > 1 and pgid != os.getpgrp() and self._group_runs_hand_study(pgid):
            try:
                os.killpg(pgid, signal.SIGKILL)
                left["killed"] = True
            except (ProcessLookupError, PermissionError):
                pass
        path.unlink(missing_ok=True)
        logger.warning("hand run left by an earlier console: %s", left)
        return left

    @staticmethod
    def _group_runs_hand_study(pgid: int) -> bool:
        """Whether process group `pgid` still holds a hand_study process (not a reused id)."""
        try:
            out = subprocess.run(["ps", "-ax", "-o", "pgid=,command="], capture_output=True, text=True,
                                 timeout=10).stdout
        except (OSError, subprocess.SubprocessError):
            return False
        return any(line.split(None, 1)[0] == str(pgid) and "hand_study" in line
                   for line in out.splitlines() if line.strip())

    def status(self) -> dict:
        """The process as the console knows it, the run folder it announced, the log's last lines."""
        with self._lock:
            info = dict(self._info)
        if not info:
            return {"state": "idle"}
        if info["run"] is None:
            info["run"] = self._announced(Path(info["log"]))
            with self._lock:
                if info["run"] and self._info.get("log") == info["log"]:
                    self._info["run"] = info["run"]
        info["state"] = "running" if info["ended"] is None else "stopped" if info["stopped"] else "ended"
        info["log_tail"] = self._tail(Path(info["log"])).splitlines()[-12:]
        return info

    @staticmethod
    def _tail(log: Path) -> str:
        try:
            with log.open("rb") as f:
                f.seek(max(f.seek(0, os.SEEK_END) - LOG_TAIL_BYTES, 0))
                return f.read().decode(errors="replace")
        except OSError:
            return ""

    @staticmethod
    def _announced(log: Path) -> str | None:
        """The run folder run_hand prints once its plans are built ("run <folder>")."""
        try:
            with log.open(errors="replace") as f:
                return next((line[4:].strip() for line in f if line.startswith("run /")), None)
        except OSError:
            return None
