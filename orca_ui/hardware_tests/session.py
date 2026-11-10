"""A hardware-test session: one plan run on one hand, kept on disk as it goes.

:class:`HardwareTests` is the console's single entry point (one per app): it
starts, resumes and ends sessions and is what the REST router calls.
:class:`TestSession` holds one session's results and writes them through
:mod:`orca_ui.hardware_tests.store` after every change.

While a step is open, and while a check runs, a :class:`_Recorder` samples the
console's latest telemetry about ten times a second into the step's
``readings.jsonl`` and copies operation log lines, operation state changes
and warnings into the session's ``events.jsonl``, so a run can be diagnosed
from its files alone.
"""

from __future__ import annotations

import logging
import threading
import time
import traceback
from collections import deque
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from orca_ui.hardware_tests import catalog as cat
from orca_ui.hardware_tests import store, tab_enabled
from orca_ui.hardware_tests.checks.base import StopRequested
from orca_ui.hardware_tests.model import (
    DECIDED,
    CheckResult,
    FeatureDefinition,
    HandFacts,
    Plan,
    Step,
    StepResult,
)
from orca_ui.streaming import topics as T

logger = logging.getLogger(__name__)

SAMPLE_PERIOD_S = 0.1
LOG_LINES = 200
MAX_SCREENSHOT_BYTES = 20 * 1024 * 1024
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PERSON_STATUSES = ("pass", "fail", "observed", "skipped")
SIDES = ("main", "branch")

READING_TOPICS = (
    T.STATUS, T.MOTORS_TELEMETRY, T.JOINTS_MEASURED, T.JOINTS_ESTIMATE, T.JOINTS_TARGET,
    T.JOINTS_CORRECTION, T.TACTILE_FORCES, T.SENSORS_HEALTH, T.OPERATION_STATE,
)
_OPERATION_KEYS = ("kind", "run_id", "state", "phase", "detail", "progress", "awaiting", "error",
                   "started_at")
_TERMINAL = ("done", "error")

ReadingSource = Callable[[str], Optional[tuple]]
"""``StreamHub.latest``: topic -> ``(seq, ts_ms, payload)`` or None."""


class HardwareTestsError(RuntimeError):
    def __init__(self, message: str, status_code: int = 400, detail: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail if detail is not None else message


# ----- hand facts -------------------------------------------------------------------


def hand_facts(service, label: str) -> HandFacts:
    """What the console knows about the connected hand right now."""
    from orca_ui.hand.operations.guided_tension import motor_family
    from orca_ui.hardware_tests.checks.console import hardware_version_source

    status = service.status()
    caps = status.get("capabilities")
    if caps is None:
        from orca_ui.hand.sessions import declared_capabilities

        settings = service.settings
        caps = declared_capabilities(service.supervisor.config, settings.engage_feedback,
                                     motors_enabled=settings.motors_enabled)
    try:
        family = motor_family(service)
    except Exception:
        family = None
    return HandFacts(
        label=label,
        model_name=status.get("model") or None,
        motor_family=family,
        hardware_version=status.get("hardware_version"),
        hardware_version_source=hardware_version_source(service, status),
        side=status.get("side") or None,
        capabilities=tuple(c for c in cat.CAPABILITIES if caps.get(c)),
        mock=bool(service.settings.mock),
    )


def default_hand_label(service) -> str:
    identity = getattr(service.supervisor, "identity", None)
    side = service.status().get("side") or None
    return store.default_label(getattr(identity, "serial", None), side)


# ----- side runner ------------------------------------------------------------------


class _UnavailableSides:
    """Stands in for the side runner when ``sides.py`` cannot be used."""

    def __init__(self, reason: str):
        self.reason = reason

    def available(self, side: str) -> Optional[str]:
        return self.reason

    def run(self, side: str, scenario: str, args: dict, out_dir: Path) -> dict:
        raise RuntimeError(self.reason)


def _default_side_runner_factory(service, settings, *, log, stop_event):
    from orca_ui.hardware_tests.sides import build_side_runner

    return build_side_runner(service, settings, log=log, stop_event=stop_event)


# ----- live recording ---------------------------------------------------------------


class _WarningCapture(logging.Handler):
    def __init__(self, emit_event: Callable[..., None]):
        super().__init__(level=logging.WARNING)
        self._emit_event = emit_event

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._emit_event("log_record", logger=record.name, level=record.levelname,
                             message=record.getMessage(),
                             traceback=self.formatter.formatException(record.exc_info)
                             if record.exc_info and self.formatter else None)
        except Exception:
            pass


def _trim_operation(payload: dict) -> dict:
    out = {k: payload.get(k) for k in _OPERATION_KEYS}
    extra = payload.get("extra") or {}
    out["extra"] = {k: v for k, v in extra.items() if isinstance(v, (str, int, float, bool)) or v is None}
    if payload.get("state") in _TERMINAL:
        out["result"] = payload.get("result")
    return out


class _Recorder:
    """Samples the latest readings into ``readings.jsonl`` and forwards
    operation activity and warnings as events, until stopped."""

    def __init__(self, step_id: str, step_dir: Path, source: Optional[ReadingSource],
                 emit_event: Callable[..., None], period_s: float = SAMPLE_PERIOD_S):
        self.step_id = step_id
        self.path = step_dir / "readings.jsonl"
        self.operations_path = step_dir / "operations.json"
        self._source = source
        self._emit = emit_event
        self._period = period_s
        self._stop = threading.Event()
        self._seq: dict[str, int] = {}
        self._log_run: Optional[str] = None
        self._log_seq = -1
        self._op_key: Optional[tuple] = None
        self.operations: list[dict] = []
        self._thread = threading.Thread(target=self._loop, name=f"hwtest-rec-{step_id}", daemon=True)
        self._capture = _WarningCapture(lambda event_type, **f: self._emit(event_type, step=step_id, **f))
        self._capture.setFormatter(logging.Formatter())

    def start(self) -> None:
        self._prime()
        logging.getLogger().addHandler(self._capture)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive() and threading.current_thread() is not self._thread:
            self._thread.join(timeout=2.0)
        logging.getLogger().removeHandler(self._capture)
        try:
            self._sample()
        except Exception:
            logger.exception("final readings sample failed")

    def _latest(self, topic: str) -> Optional[tuple]:
        if self._source is None:
            return None
        try:
            return self._source(topic)
        except Exception:
            return None

    def _prime(self) -> None:
        """Lines and operation states from before the step opened are not its own."""
        log = self._latest(T.OPERATION_LOG)
        if log is not None:
            payload = log[2] or {}
            self._log_run = payload.get("run_id")
            self._log_seq = int(payload.get("next_seq") or 0) - 1
        op = self._latest(T.OPERATION_STATE)
        if op is not None and op[2]:
            self._op_key = (op[2].get("run_id"), op[2].get("state"), op[2].get("phase"))

    def _loop(self) -> None:
        while not self._stop.wait(self._period):
            try:
                self._sample()
            except Exception:
                logger.exception("readings sample failed")

    def _sample(self) -> None:
        topics: dict[str, Any] = {}
        for topic in READING_TOPICS:
            entry = self._latest(topic)
            if entry is None or entry[0] == self._seq.get(topic):
                continue
            self._seq[topic] = entry[0]
            payload = entry[2]
            if topic == T.OPERATION_STATE and payload:
                payload = _trim_operation(payload)
                self._operation_changed(payload)
            topics[topic] = {"ts": round(entry[1] / 1000.0, 3), "data": payload}
        if topics:
            store.append_jsonl(self.path, {"t": round(time.time(), 3), "topics": topics})
        self._forward_log()

    def _operation_changed(self, op: dict) -> None:
        key = (op.get("run_id"), op.get("state"), op.get("phase"))
        if key == self._op_key:
            return
        self._op_key = key
        self._emit("operation_state", step=self.step_id,
                   **{k: op.get(k) for k in ("kind", "run_id", "state", "phase", "detail", "error")})
        if op.get("state") in _TERMINAL:
            self.operations.append(dict(op, finished_at=time.time()))
            store.write_json(self.operations_path, self.operations)

    def _forward_log(self) -> None:
        entry = self._latest(T.OPERATION_LOG)
        if entry is None:
            return
        payload = entry[2] or {}
        run_id = payload.get("run_id")
        if run_id != self._log_run:
            self._log_run, self._log_seq = run_id, -1
        for line in payload.get("lines") or []:
            seq = int(line.get("seq", -1))
            if seq > self._log_seq:
                self._log_seq = seq
                self._emit("operation_log", step=self.step_id, run_id=run_id,
                           line=line.get("line"), at=line.get("t"))


# ----- check context ------------------------------------------------------------------


class _Context:
    """The :class:`~orca_ui.hardware_tests.checks.base.CheckContext` a check runs with.

    Beyond the protocol it offers the session's settings, a stop-aware
    ``wait`` and read access to other steps' recordings."""

    def __init__(self, session: "TestSession", feature: FeatureDefinition, step: Step,
                 stop_event: threading.Event, sides, progress: Callable[[float, str], None]):
        self._session = session
        self.feature = feature
        self.step = step
        self.hand = session.hand
        self.service = session.service
        self.settings = session.settings
        self.sides = sides
        self.out_dir = session.step_dir(step.id)
        self.stop_event = stop_event
        self._progress = progress

    def log(self, line: str) -> None:
        self._session.log(line, step=self.step.id)

    def progress(self, fraction: float, detail: str = "") -> None:
        self._progress(min(max(float(fraction), 0.0), 1.0), detail)

    def check_stop(self) -> None:
        if self.stop_event.is_set():
            raise StopRequested()

    def wait(self, seconds: float) -> None:
        if self.stop_event.wait(seconds):
            raise StopRequested()

    def step_result(self, step_id: str) -> Optional[dict]:
        return self._session.step_result_dict(step_id)

    def step_dir(self, step_id: str) -> Optional[Path]:
        return self._session.step_dir(step_id) if step_id in self._session.feature_of else None

    def step_events(self, step_id: str) -> list[dict]:
        return [e for e in store.read_jsonl(self._session.paths.events) if e.get("step") == step_id]

    def session_events(self) -> list[dict]:
        """Every event of the session, for checks that look across steps."""
        return store.read_jsonl(self._session.paths.events)

    def step_operations(self, step_id: str) -> list[dict]:
        folder = self.step_dir(step_id)
        data = store.read_json(folder / "operations.json") if folder else None
        return data if isinstance(data, list) else []


# ----- session ----------------------------------------------------------------------------


def _status_for(kind: str, check_status: str) -> str:
    """An observe step records; it never passes or fails."""
    if kind == "observe" and check_status in ("pass", "fail"):
        return "observed"
    return check_status


class TestSession:
    __test__ = False  # not a pytest class

    def __init__(self, *, service, settings, catalog: cat.Catalog, plan: Plan, label: str,
                 session_stamp: str, root: Path, readings: Optional[ReadingSource],
                 side_runner_factory, resumed: bool = False):
        self.service = service
        self.settings = settings
        self.catalog = catalog
        self.plan = plan
        self.label = label
        self.paths = store.SessionPaths(root, label, plan.id, session_stamp)
        self.id = f"{session_stamp} {plan.id}"
        self._readings = readings
        self._side_runner_factory = side_runner_factory
        self._lock = threading.RLock()
        self._events_lock = threading.Lock()
        self._check_lock = threading.Lock()
        self.features: list[FeatureDefinition] = catalog.plan_features(plan.id)
        self.feature_of: dict[str, FeatureDefinition] = {s.id: f for f in self.features for s in f.steps}
        self.steps: dict[str, Step] = {s.id: s for f in self.features for s in f.steps}
        self.results: dict[str, StepResult] = {sid: StepResult(step_id=sid) for sid in self.steps}
        self.started_at = store.now_iso()
        self.finished_at: Optional[str] = None
        self.hand = hand_facts(service, label)
        self.sides_info: dict[str, dict] = {}
        self.open_step: Optional[str] = None
        self._recorders: dict[str, _Recorder] = {}
        self._verifying: set[str] = set()
        self._log: deque[str] = deque(maxlen=LOG_LINES)
        self._auto: dict = {"state": "idle", "current_step": None, "progress": 0.0, "detail": ""}
        self._auto_thread: Optional[threading.Thread] = None
        self._auto_stop: Optional[threading.Event] = None
        if resumed:
            self._load()
        self.refresh_sides()
        self.event("session_resumed" if resumed else "session_started", plan=plan.id, label=label,
                   hand=self.hand.as_dict(), sides=self.sides_info)
        with self._lock:
            self._save()

    # ----- persistence -----------------------------------------------------------------

    def _load(self) -> None:
        index = store.read_json(self.paths.index_json) or {}
        self.started_at = index.get("started_at") or self.started_at
        for feature in self.features:
            data = store.read_json(self.paths.feature_result(feature.id)) or {}
            for sid, raw in (data.get("steps") or {}).items():
                if sid not in self.results or not isinstance(raw, dict):
                    continue
                fields = {k: raw[k] for k in StepResult.__dataclass_fields__ if k in raw}
                result = StepResult(**fields)
                if result.status == "running":
                    result.status = "pending"
                self.results[sid] = result

    def _feature_payload(self, feature: FeatureDefinition) -> dict:
        return {
            "feature": feature.id,
            "session": self.id,
            "plan": self.plan.id,
            "hand": self.hand.as_dict(),
            "steps": {s.id: self.results[s.id].as_dict() for s in feature.steps},
        }

    def _save(self, feature_ids: Optional[list[str]] = None) -> None:
        """Write the given features' result.json (all when None), the index and the summary."""
        for feature in self.features:
            if feature_ids is None or feature.id in feature_ids:
                store.write_json(self.paths.feature_result(feature.id), self._feature_payload(feature))
        store.write_json(self.paths.index_json, self._index())
        store.write_text(self.paths.index_md, store.render_markdown(self._summary_head(), self._rows()))

    def _summary_head(self) -> dict:
        return {
            "id": self.id,
            "plan_id": self.plan.id,
            "plan_title": self.plan.title,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "hand": self.hand.as_dict(),
            "sides": self.sides_info,
            "results_dir": store.display_path(self.paths.tests_dir),
            "events_file": store.display_path(self.paths.events),
        }

    def _index(self) -> dict:
        return {
            **self._summary_head(),
            "stamp": self.paths.stamp,
            "label": self.label,
            "summary_file": str(self.paths.index_md),
            "events_file": str(self.paths.events),
            "features": [
                {"id": f.id, "title": f.title, "folder": str(self.paths.feature_dir(f.id)),
                 "result_file": str(self.paths.feature_result(f.id))}
                for f in self.features
            ],
            "steps": {
                sid: {
                    "feature": self.feature_of[sid].id,
                    "status": r.status,
                    "decided_by": r.decided_by,
                    "note": r.note,
                    "check": (r.check or {}).get("summary"),
                    "applicable": self.applicability(sid)[0],
                }
                for sid, r in self.results.items()
            },
        }

    def _rows(self) -> list[dict]:
        rows = []
        for feature in self.features:
            for step in feature.steps:
                result = self.results[step.id]
                applicable, reason = self.applicability(step.id)
                rows.append({
                    "feature": feature.id,
                    "step": step.id,
                    "title": step.title,
                    "kind": step.kind,
                    "status": result.status if applicable else f"not applicable ({reason})",
                    "note": result.note,
                    "check": (result.check or {}).get("summary"),
                    "folder": store.display_path(self.step_dir(step.id)),
                })
        return rows

    # ----- events and log -------------------------------------------------------------------

    def event(self, event_type: str, step: Optional[str] = None, **fields) -> None:
        record = {"t": store.now_iso(), "ts": round(time.time(), 3), "type": event_type}
        if step is not None:
            record["step"] = step
        record.update(fields)
        with self._events_lock:
            try:
                store.append_jsonl(self.paths.events, record)
            except OSError:
                logger.exception("could not append to %s", self.paths.events)

    def log(self, line: str, step: Optional[str] = None) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        with self._lock:
            self._log.append(f"{stamp} {f'[{step}] ' if step else ''}{line}")
        self.event("log", step=step, line=line)

    # ----- reads ------------------------------------------------------------------------

    def step_dir(self, step_id: str) -> Path:
        return self.paths.step_dir(self.feature_of[step_id].id, step_id)

    def applicability(self, step_id: str) -> tuple[bool, Optional[str]]:
        return cat.applicability(self.steps[step_id], self.hand)

    def step_result_dict(self, step_id: str) -> Optional[dict]:
        with self._lock:
            result = self.results.get(step_id)
            if result is None:
                return None
            return {**result.as_dict(), "dir": str(self.step_dir(step_id))}

    def refresh_sides(self) -> None:
        runner = self._side_runner(threading.Event())
        info: dict[str, dict] = {}
        for side in SIDES:
            try:
                reason = runner.available(side)
            except Exception as e:
                reason = f"could not check this side: {e}"
            version = None
            describe = getattr(runner, "version", None)
            if reason is None and callable(describe):
                try:
                    version = describe(side)
                except Exception:
                    version = None
            info[side] = {"available": reason is None, "reason": reason, "version": version}
        self.sides_info = info

    def _side_runner(self, stop_event: threading.Event):
        try:
            return self._side_runner_factory(
                self.service, self.settings,
                log=lambda line: self.log(line), stop_event=stop_event)
        except Exception as e:
            logger.info("side runner unavailable: %s", e)
            return _UnavailableSides(f"the main/branch runner (hardware_tests/sides.py) is unavailable: {e}")

    def as_dict(self) -> dict:
        with self._lock:
            features = []
            for feature in self.features:
                steps = []
                for step in feature.steps:
                    applicable, reason = self.applicability(step.id)
                    steps.append({
                        **asdict(step),
                        "applicable": applicable,
                        "not_applicable_reason": reason,
                        "hands_on": cat.is_hands_on(step),
                        "automatic": cat.is_automatic(step),
                        "verifying": step.id in self._verifying,
                        "folder": store.display_path(self.step_dir(step.id)),
                        "result": self.results[step.id].as_dict(),
                    })
                features.append({
                    "id": feature.id,
                    "title": feature.title,
                    "summary": feature.summary,
                    "group": feature.group,
                    "folder": store.display_path(self.paths.feature_dir(feature.id)),
                    "steps": steps,
                })
            return {
                "id": self.id,
                "plan_id": self.plan.id,
                "plan_title": self.plan.title,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "results_dir": store.display_path(self.paths.tests_dir),
                "index_file": store.display_path(self.paths.index_md),
                "events_file": store.display_path(self.paths.events),
                "hand": self.hand.as_dict(),
                "sides": {side: dict(self.sides_info.get(side) or {}) for side in SIDES},
                "auto": {**self._auto, "log": list(self._log)},
                "open_step": self.open_step,
                "features": features,
            }

    # ----- hands-on steps ------------------------------------------------------------------

    def _require_step(self, step_id: str) -> Step:
        step = self.steps.get(step_id)
        if step is None:
            raise HardwareTestsError(f"no step {step_id!r} in plan {self.plan.id}", 404)
        return step

    def _require_open(self) -> None:
        if self.finished_at is not None:
            raise HardwareTestsError("this session has ended", 409)

    def _start_recorder(self, step_id: str) -> bool:
        if step_id in self._recorders:
            return False
        recorder = _Recorder(step_id, self.step_dir(step_id), self._readings, self.event)
        self._recorders[step_id] = recorder
        recorder.start()
        return True

    def _stop_recorder(self, step_id: str) -> None:
        recorder = self._recorders.pop(step_id, None)
        if recorder is not None:
            recorder.stop()

    def open(self, step_id: str) -> None:
        self._require_step(step_id)
        self._require_open()
        with self._lock:
            if self.open_step == step_id:
                return
            if self.open_step is not None:
                self._close_locked(self.open_step)
            self.open_step = step_id
            result = self.results[step_id]
            if result.started_at is None:
                result.started_at = store.now_iso()
            self._start_recorder(step_id)
            self.event("step_opened", step=step_id)
            self._save([self.feature_of[step_id].id])

    def close(self, step_id: str) -> None:
        self._require_step(step_id)
        with self._lock:
            if self.open_step == step_id:
                self._close_locked(step_id)
                self._save([self.feature_of[step_id].id])

    def _close_locked(self, step_id: str) -> None:
        self._stop_recorder(step_id)
        self.open_step = None
        self.event("step_closed", step=step_id)

    def decide(self, step_id: str, status: str, note: str) -> None:
        step = self._require_step(step_id)
        self._require_open()
        if status not in PERSON_STATUSES:
            raise HardwareTestsError(f"status must be one of {', '.join(PERSON_STATUSES)}", 422)
        with self._lock:
            result = self.results[step_id]
            if result.status == "running" or step_id in self._verifying:
                raise HardwareTestsError(f"step {step_id} is still being checked", 409)
            if self.open_step == step_id:
                self._close_locked(step_id)
            result.status = status
            result.note = note
            result.decided_by = "person"
            result.check = None
            result.started_at = result.started_at or store.now_iso()
            result.finished_at = store.now_iso()
            self.event("step_decided", step=step_id, status=status, note=note)
            verify = bool(step.check) and step.kind == "manual" and status != "skipped"
            if verify:
                self._verifying.add(step_id)
            self._save([self.feature_of[step_id].id])
        if verify:
            threading.Thread(target=self._verify, args=(step_id,), name=f"hwtest-verify-{step_id}",
                             daemon=True).start()

    def _verify(self, step_id: str) -> None:
        """Run a decided step's check and let a failure override a person's pass."""
        step = self.steps[step_id]
        try:
            check = self._run_check(step, threading.Event(), lambda f, d: None, record=False)
        finally:
            with self._lock:
                self._verifying.discard(step_id)
        with self._lock:
            result = self.results[step_id]
            result.check = check.as_dict()
            if check.status == "fail" and result.status == "pass":
                result.status = "fail"
                result.decided_by = "check"
                reason = f"verification failed: {check.summary}"
                result.note = f"{result.note}\n{reason}".strip() if result.note else reason
            self.event("step_verified", step=step_id, check_status=check.status, summary=check.summary,
                       status=result.status)
            self._save([self.feature_of[step_id].id])

    def screenshot(self, step_id: str, png: bytes) -> Path:
        self._require_step(step_id)
        self._require_open()
        if not png.startswith(PNG_SIGNATURE):
            raise HardwareTestsError("the screenshot must be a PNG image", 415)
        if len(png) > MAX_SCREENSHOT_BYTES:
            raise HardwareTestsError("the screenshot is larger than 20 MB", 413)
        with self._lock:
            folder = self.step_dir(step_id) / "screenshots"
            folder.mkdir(parents=True, exist_ok=True)
            taken = {p.stem for p in folder.glob("*.png")}
            number = 1
            while str(number) in taken:
                number += 1
            path = folder / f"{number}.png"
            path.write_bytes(png)
            self.results[step_id].screenshots.append(path.name)
            self.event("screenshot", step=step_id, file=str(path))
            self._save([self.feature_of[step_id].id])
        return path

    # ----- automatic run ------------------------------------------------------------------

    def automatic_steps(self, step_ids: Optional[list[str]] = None) -> list[Step]:
        wanted = None if step_ids is None else set(step_ids)
        if wanted is not None:
            for sid in wanted:
                self._require_step(sid)
        return [
            s for f in self.features for s in f.steps
            if cat.is_automatic(s) and self.applicability(s.id)[0] and (wanted is None or s.id in wanted)
        ]

    def undecided_hands_on(self) -> list[str]:
        return [
            s.id for f in self.features for s in f.steps
            if cat.is_hands_on(s) and self.applicability(s.id)[0] and self.results[s.id].status not in DECIDED
        ]

    def run_auto(self, step_ids: Optional[list[str]] = None, force: bool = False) -> None:
        self._require_open()
        steps = self.automatic_steps(step_ids)
        with self._lock:
            if self._auto["state"] != "idle":
                raise HardwareTestsError("the automatic checks are already running", 409)
            undecided = self.undecided_hands_on()
            if undecided and not force:
                raise HardwareTestsError(
                    "decide the hands-on steps first, or run anyway", 409,
                    detail={"message": "hands-on steps are not decided yet", "steps": undecided})
            if not steps:
                raise HardwareTestsError("no automatic step applies to this hand", 409)
            stop_event = threading.Event()
            self._auto_stop = stop_event
            self._auto.update(state="running", current_step=None, progress=0.0, detail="starting")
            for step in steps:
                if self.results[step.id].status not in DECIDED:
                    self.results[step.id].status = "pending"
            self._auto_thread = threading.Thread(
                target=self._auto_loop, args=(steps, stop_event), name="hwtest-auto", daemon=True)
        self.event("auto_started", steps=[s.id for s in steps], forced=force, undecided=undecided)
        self._auto_thread.start()

    def stop_auto(self) -> None:
        with self._lock:
            if self._auto["state"] != "running" or self._auto_stop is None:
                return
            self._auto.update(state="stopping", detail="stopping after the current step")
            self._auto_stop.set()
        self.event("auto_stop_requested")

    @property
    def auto_running(self) -> bool:
        with self._lock:
            return self._auto["state"] != "idle"

    def _auto_loop(self, steps: list[Step], stop_event: threading.Event) -> None:
        total = len(steps)
        stopped = False
        try:
            self.refresh_sides()
            for index, step in enumerate(steps):
                if stop_event.is_set():
                    stopped = True
                    break

                def progress(fraction: float, detail: str, index=index, step=step) -> None:
                    with self._lock:
                        self._auto.update(progress=(index + fraction) / total,
                                          detail=f"{step.id} {step.title}" + (f" — {detail}" if detail else ""))

                with self._lock:
                    self._auto.update(current_step=step.id, progress=index / total,
                                      detail=f"{step.id} {step.title}")
                    result = self.results[step.id]
                    result.status = "running"
                    result.decided_by = ""
                    result.started_at = store.now_iso()
                    result.finished_at = None
                    self._save([self.feature_of[step.id].id])
                self.log(f"running {step.id} {step.title}", step=step.id)
                check = self._run_check(step, stop_event, progress)
                with self._lock:
                    result = self.results[step.id]
                    result.status = _status_for(step.kind, check.status)
                    result.decided_by = "check"
                    result.check = check.as_dict()
                    result.finished_at = store.now_iso()
                    self._save([self.feature_of[step.id].id])
                self.log(f"{step.id}: {result.status} — {check.summary}", step=step.id)
            stopped = stopped or stop_event.is_set()
        except Exception as e:
            logger.exception("automatic run failed")
            self.event("auto_error", error=repr(e), traceback=traceback.format_exc())
            self.log(f"automatic run failed: {e}")
        finally:
            with self._lock:
                self._auto.update(state="idle", current_step=None,
                                  progress=self._auto["progress"] if stopped else 1.0,
                                  detail="stopped" if stopped else "finished")
                self._save()
            self.event("auto_finished", stopped=stopped)

    def _run_check(self, step: Step, stop_event: threading.Event,
                   progress: Callable[[float, str], None], record: bool = True) -> CheckResult:
        """Run ``step``'s check, recording live readings when ``record``; never raises."""
        from orca_ui.hardware_tests import checks

        with self._check_lock:
            with self._lock:
                started_recorder = record and self._start_recorder(step.id)
            self.event("check_started", step=step.id, check=step.check)
            try:
                fn = checks.lookup(step.check or "")
                ctx = _Context(self, self.feature_of[step.id], step, stop_event,
                               self._side_runner(stop_event), progress)
                result = fn(ctx)
                if not isinstance(result, CheckResult):
                    raise TypeError(f"check {step.check!r} returned {type(result).__name__}, not CheckResult")
            except StopRequested:
                result = CheckResult(status="skipped", summary="stopped by the person before the check finished")
            except Exception as e:
                trace = traceback.format_exc()
                self.event("check_error", step=step.id, check=step.check, error=repr(e), traceback=trace)
                self.log(f"{step.id}: check raised {type(e).__name__}: {e}", step=step.id)
                result = CheckResult(status="error", summary=f"{type(e).__name__}: {e}",
                                     details={"traceback": trace})
            finally:
                if started_recorder:
                    with self._lock:
                        self._stop_recorder(step.id)
            try:
                store.write_json(self.step_dir(step.id) / "check.json", result.as_dict())
            except (OSError, TypeError, ValueError):
                logger.exception("could not write the check result of %s", step.id)
            self.event("check_finished", step=step.id, check=step.check, status=result.status,
                       summary=result.summary)
            return result

    # ----- end ------------------------------------------------------------------------------

    def end(self) -> None:
        with self._lock:
            if self._auto["state"] != "idle":
                raise HardwareTestsError("stop the automatic checks before ending the session", 409)
            if self.open_step is not None:
                self._close_locked(self.open_step)
            for step_id in list(self._recorders):
                self._stop_recorder(step_id)
            self.finished_at = store.now_iso()
            self.event("session_ended")
            self._save()


class HardwareTests:
    """The console's hardware-test front door: at most one session at a time."""

    def __init__(self, service, settings, *, readings: Optional[ReadingSource] = None,
                 catalog: Optional[cat.Catalog] = None, side_runner_factory=None,
                 enabled: Optional[bool] = None):
        self.service = service
        self.settings = settings
        self._readings = readings
        self._catalog = catalog
        self._side_runner_factory = side_runner_factory or _default_side_runner_factory
        self._enabled = enabled
        self._lock = threading.Lock()
        self.session: Optional[TestSession] = None

    @property
    def enabled(self) -> bool:
        return tab_enabled(self.settings) if self._enabled is None else self._enabled

    @property
    def catalog(self) -> cat.Catalog:
        if self._catalog is None:
            self._catalog = cat.default_catalog()
        return self._catalog

    @property
    def root(self) -> Path:
        return store.bench_root(getattr(self.settings, "bench_dir", None))

    def state(self) -> dict:
        if not self.enabled:
            return {"enabled": False, "plans": [], "session": None, "default_label": None}
        session = self.session
        try:
            label = default_hand_label(self.service)
        except Exception:
            label = None
        resumable = [
            {"plan_id": p.id, "label": label, "stamp": found}
            for p in self.catalog.plans.values()
            if label and (found := store.find_unfinished(self.root, label, p.id))
        ] if session is None else []
        return {
            "enabled": True,
            "plans": [{"id": p.id, "title": p.title, "summary": p.summary} for p in self.catalog.plans.values()],
            "session": session.as_dict() if session else None,
            "default_label": label,
            "resumable": resumable,
            "bench_dir": store.display_path(self.root),
        }

    def require_session(self) -> TestSession:
        session = self.session
        if session is None:
            raise HardwareTestsError("no test session — start one first", 409)
        return session

    def start(self, plan_id: str, hand_label: Optional[str]) -> TestSession:
        plan = self.catalog.plans.get(plan_id)
        if plan is None:
            raise HardwareTestsError(f"unknown plan {plan_id!r}", 404)
        label = store.safe_name(hand_label or "") or default_hand_label(self.service)
        with self._lock:
            current = self.session
            if current is not None:
                if current.plan.id == plan.id and current.label == label:
                    return current
                raise HardwareTestsError(
                    f"session {current.id} for {current.label} is still open — end it first", 409)
            resume = store.find_unfinished(self.root, label, plan.id)
            self.session = TestSession(
                service=self.service, settings=self.settings, catalog=self.catalog, plan=plan,
                label=label, session_stamp=resume or store.new_stamp(self.root, label, plan.id), root=self.root,
                readings=self._readings, side_runner_factory=self._side_runner_factory,
                resumed=resume is not None)
            return self.session

    def end(self) -> None:
        with self._lock:
            session = self.session
            if session is None:
                return
            session.end()
            self.session = None

    def shutdown(self) -> None:
        session = self.session
        if session is None:
            return
        session.stop_auto()
        thread = session._auto_thread
        if thread is not None:
            thread.join(timeout=5.0)
        with session._lock:
            for step_id in list(session._recorders):
                session._stop_recorder(step_id)
