"""The rig's hand run as a child process of the console.

``python -m hand_study.run_hand --hand-id <id>`` (orca_core's visual calibration experiment) measures
the hand on the camera rig: about an hour of poses, each photographed by both cameras at every plate
stop, then the joint ranges fit and the accuracy check. It drives the hand and the plate through this
console's own REST API, so the console only starts it, follows its files and kills it. Its process
group (the runner, the plan builder, the solve workers) dies together: on Stop, on E-STOP and when
the console shuts down. Hand and plate torque goes off whenever a run ends.
"""

from __future__ import annotations

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
        self._info: dict = {}

    def alive(self) -> bool:
        proc = self._proc
        return proc is not None and proc.poll() is None

    def start(self, hand_id: str, dry: bool = False, limit: int | None = None,
              command: list[str] | None = None) -> dict:
        """Start a run for `hand_id` (`command`: another program, for tests). RuntimeError if one runs."""
        with self._lock:
            if self.alive():
                raise RuntimeError("a hand run is already running: stop it first")
            folder = self.log_dir()
            folder.mkdir(parents=True, exist_ok=True)
            log = folder / f"{hand_id}-{time.strftime('%Y%m%d-%H%M%S')}.log"
            cmd = command or [sys.executable, "-m", "hand_study.run_hand", "--hand-id", hand_id,
                              *(["--dry"] if dry else []), *(["--limit", str(limit)] if limit else [])]
            # As hand_study.run_hand.run_env gives every process of a run: this ORCA_HOME (absolute) and
            # the experiment on the path; the run adds its own folder and config for its children.
            env = {**os.environ, "ORCA_UI": self.ui_url, hand_store.ORCA_HOME_ENV: str(hand_store.orca_home()),
                   "PYTHONPATH": os.pathsep.join(filter(None, [str(self.experiment), os.environ.get("PYTHONPATH")]))}
            with log.open("ab") as out:
                proc = subprocess.Popen(cmd, cwd=self.experiment, env=env, stdout=out, stderr=subprocess.STDOUT,
                                        stdin=subprocess.DEVNULL, start_new_session=True)
            self._proc = proc
            self._info = {"hand": hand_id, "dry": dry, "pid": proc.pid, "started": time.time(), "log": str(log),
                          "run": None, "ended": None, "returncode": None, "stopped": None}
        threading.Thread(target=self._wait, args=(proc,), name="hand-run", daemon=True).start()
        logger.warning("hand run started for %s (pid %s, log %s)", hand_id, proc.pid, log)
        return self.status()

    def _wait(self, proc: subprocess.Popen) -> None:
        proc.wait()
        with self._lock:
            if self._proc is not proc:
                return
            self._info.update(ended=time.time(), returncode=proc.returncode)
            stopped = self._info["stopped"]
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
