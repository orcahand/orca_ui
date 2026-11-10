"""Hardware-test sessions: what reaches disk, resuming, a failed verification
overriding a person's pass, and the automatic run's gate, errors and Stop.

Runs on a stand-in service and readings source, so nothing here needs the
console or a hand."""

import threading
import time
from types import SimpleNamespace

import pytest

from orca_ui.hardware_tests import checks, store
from orca_ui.hardware_tests.model import CheckResult
from orca_ui.hardware_tests.session import HardwareTests, HardwareTestsError
from orca_ui.settings import UiSettings
from orca_ui.streaming import topics as T

PLAN = "merge-0.13"


class FakeService:
    def __init__(self, tmp_path):
        self.settings = UiSettings(config_path=str(tmp_path / "config.yaml"), mock=True,
                                   hardware_tests=True, bench_dir=str(tmp_path / "bench"))
        self.supervisor = SimpleNamespace(
            config=SimpleNamespace(motor_type="dynamixel", config_path=str(tmp_path / "config.yaml")),
            identity=SimpleNamespace(serial="ser-0000"), hand_id="ser-0000")
        self.session = None
        self.operation_manager = None

    def status(self):
        return {"state": "connected", "model": "orcahand-right", "side": "right",
                "capabilities": {"tactile": False, "encoders": True}, "hardware_version": 210,
                "hardware_version_pinned": False, "board_hardware_version": 210}


class FakeReadings:
    """``StreamHub.latest`` with a motor table that changes on every read."""

    def __init__(self):
        self.seq = 0
        self.log_lines: list[dict] = []

    def __call__(self, topic):
        if topic == T.MOTORS_TELEMETRY:
            self.seq += 1
            return self.seq, time.time() * 1000, {"currents": {"1": float(self.seq)}}
        if topic == T.OPERATION_LOG:
            return len(self.log_lines), time.time() * 1000, {
                "run_id": "slack_test-1", "next_seq": len(self.log_lines), "lines": list(self.log_lines)}
        return None


class FakeSides:
    def __init__(self, service, settings, *, log, stop_event):
        pass

    def available(self, side):
        return None if side == "branch" else "no main checkout"

    def version(self, side):
        return "0.13.0"

    def run(self, side, scenario, args, out_dir):
        return {}


def _tests(tmp_path, readings=None) -> HardwareTests:
    return HardwareTests(FakeService(tmp_path), FakeService(tmp_path).settings, readings=readings,
                         side_runner_factory=FakeSides, enabled=True)


def _wait(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def _step(session_dict, step_id):
    return next(s for f in session_dict["features"] for s in f["steps"] if s["id"] == step_id)


def test_an_open_step_is_recorded_and_the_session_resumes(tmp_path):
    readings = FakeReadings()
    tests = _tests(tmp_path, readings)
    session = tests.start(PLAN, "")
    assert session.label == "ser-0000"
    assert session.as_dict()["sides"]["branch"] == {"available": True, "reason": None, "version": "0.13.0"}

    session.open("A1")
    readings.log_lines.append({"seq": 0, "t": time.time(), "line": "thumb_cmc: back — testing it again"})
    readings_file = session.step_dir("A1") / "readings.jsonl"
    assert _wait(lambda: len(store.read_jsonl(readings_file)) >= 3)
    assert _wait(lambda: any(e.get("type") == "operation_log" and e.get("step") == "A1"
                             for e in store.read_jsonl(session.paths.events)))
    session.close("A1")
    session.decide("B9", "pass", "same as main")

    index = store.read_json(session.paths.index_json)
    assert index["steps"]["B9"]["status"] == "pass" and not index["finished_at"]
    assert "| B9 Same behaviour as on main |" in session.paths.index_md.read_text()
    assert store.read_json(session.paths.feature_result("console-features"))["steps"]["B9"]["note"] == "same as main"

    # A new console on the same bench picks the unfinished session back up.
    again = _tests(tmp_path).start(PLAN, "ser-0000")
    assert again.id == session.id
    assert again.results["B9"].status == "pass"
    assert again.results["A1"].started_at is not None
    again.end()
    assert _tests(tmp_path).start(PLAN, "ser-0000").id != session.id


def test_a_failed_verification_overrides_a_pass(tmp_path, monkeypatch):
    monkeypatch.setattr(checks, "lookup", lambda name: lambda ctx: CheckResult(
        status="fail", summary="no slack test was saved during this step"))
    session = _tests(tmp_path).start(PLAN, "ser-0000")
    session.decide("A1", "pass", "looked fine")
    assert _wait(lambda: not _step(session.as_dict(), "A1")["verifying"])
    result = session.results["A1"]
    assert result.status == "fail" and result.decided_by == "check"
    assert "verification failed: no slack test was saved" in result.note
    assert result.check["status"] == "fail"


def test_the_automatic_run_waits_for_hands_on_steps_reports_errors_and_stops(tmp_path, monkeypatch):
    blocking = threading.Event()

    def check(ctx):
        if ctx.step.id == "A8a":
            raise RuntimeError("board did not answer")
        if ctx.step.id == "C3":
            blocking.set()
            while True:
                ctx.wait(0.05)
        return CheckResult(status="pass", summary="fine")

    monkeypatch.setattr(checks, "lookup", lambda name: check)
    session = _tests(tmp_path).start(PLAN, "ser-0000")

    with pytest.raises(HardwareTestsError) as refused:
        session.run_auto(["A2"])
    assert refused.value.status_code == 409 and "A1" in refused.value.detail["steps"]

    session.run_auto(["A2", "A8a", "C2", "C3"], force=True)
    assert blocking.wait(5.0)
    session.stop_auto()
    assert _wait(lambda: not session.auto_running)

    assert session.results["A2"].status == "pass"
    assert session.results["C2"].status == "observed"  # an observation never passes or fails
    assert session.results["A8a"].status == "error"
    assert "board did not answer" in session.results["A8a"].check["summary"]
    assert session.results["C3"].status == "skipped"
    events = store.read_jsonl(session.paths.events)
    error = next(e for e in events if e["type"] == "check_error")
    assert error["step"] == "A8a" and "Traceback" in error["traceback"]
    assert store.read_json(session.step_dir("A8a") / "check.json")["status"] == "error"


def test_slack_check_takes_the_fullest_run_of_the_step_and_a_real_retest(monkeypatch):
    from orca_ui.hand import slack_tests
    from orca_ui.hardware_tests.checks import console

    joints = ["thumb_cmc", "thumb_mcp"]
    reading = {"status": "pass", "total_deg": 3.0}

    def test(at, statuses):
        return {"recorded_at": at, "settings": {"current_ma": 60}, "motor_type": "dynamixel",
                "results": [dict(reading, joint=j) if s else {"joint": j, "status": "skipped"}
                            for j, s in zip(joints, statuses)]}

    saved = [("full", test("2026-01-01T10:01:00+00:00", [1, 1])),
             ("short", test("2026-01-01T10:02:00+00:00", [1, 0]))]
    monkeypatch.setattr(slack_tests, "for_hand", lambda config, hand: saved)
    lines = ["thumb_mcp: 3° free (1 + 2)", "thumb_mcp: back — testing it again", "thumb_mcp: skipped",
             "thumb_cmc: back — testing it again", "thumb_cmc: 4° free (2 + 2)"]
    service = SimpleNamespace(
        supervisor=SimpleNamespace(config=SimpleNamespace(joint_ids=joints, joint_to_motor_map={j: 1 for j in joints}),
                                   hand_id="ser-0000"),
        session=None)
    ctx = SimpleNamespace(step=SimpleNamespace(id="A1"), service=service,
                          step_result=lambda sid: {"started_at": "2026-01-01T10:00:00+00:00"},
                          step_events=lambda sid: [{"type": "operation_log", "line": l} for l in lines])

    result = console.slack_test_saved(ctx)
    assert result.status == "pass", result.summary
    assert result.details["slack_test"] == "full"
    assert next(m for m in result.metrics if m.name == "Back retested").value == "thumb_cmc"


def test_a_session_started_on_an_older_plan_resumes_with_the_new_steps(tmp_path):
    """A console restarted with more features in the plan resumes the open
    session: earlier decisions stay, the new steps appear pending."""
    import dataclasses

    from orca_ui.hardware_tests import catalog as cat

    full = cat.default_catalog()
    plan = full.plans[PLAN]
    older = cat.Catalog(features=full.features,
                        plans={PLAN: dataclasses.replace(plan, features=plan.features[:5])})
    first = HardwareTests(FakeService(tmp_path), FakeService(tmp_path).settings, catalog=older,
                          side_runner_factory=FakeSides, enabled=True)
    session = first.start(PLAN, "")
    session.decide("A1", "skipped", "done in an earlier session")
    first.shutdown()

    second = HardwareTests(FakeService(tmp_path), FakeService(tmp_path).settings, catalog=full,
                           side_runner_factory=FakeSides, enabled=True)
    resumed = second.start(PLAN, "")
    assert resumed.id == session.id
    assert resumed.results["A1"].status == "skipped"
    assert resumed.results["S1"].status == "pending"
    assert {f.id for f in resumed.features} == set(plan.features)
    assert any(e["type"] == "session_resumed" for e in store.read_jsonl(resumed.paths.events))
