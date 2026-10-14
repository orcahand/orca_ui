"""The real chain operation, when orca_core cannot place motors it found:
the console asks, resets on request and runs the chain again."""

import threading
from types import SimpleNamespace

from orca_core.maintenance.motor_chain import MotorChainAborted

from orca_ui.hand.operations import hand_ops
from orca_ui.hand.operations.chain import ConfigureChainOperation


class _Ctx:
    def __init__(self, answers):
        self.answers = list(answers)
        self.prompts = []
        self.lines = []
        self.extra = None
        self.stop_event = threading.Event()
        self.service = SimpleNamespace(supervisor=_Supervisor())

    def wait_input(self, prompt, options):
        self.prompts.append((prompt, options))
        return self.answers.pop(0)

    def log(self, line):
        self.lines.append(line)

    def set_extra(self, extra):
        self.extra = extra

    def set_phase(self, *a, **k):
        pass

    def set_detail(self, *a, **k):
        pass

    def set_progress(self, *a, **k):
        pass

    def check_stop(self):
        pass


class _Supervisor:
    def __init__(self):
        self.config = SimpleNamespace(motor_ids=[1, 2, 3], joint_to_motor_map={"wrist": 1},
                                      baudrate=1_000_000, motor_type="dynamixel")
        self.left = False

    def enter_maintenance(self, kind, probe=True):
        self.probed = probe
        return SimpleNamespace(presence=None)

    def exit_maintenance(self):
        self.left = True


def _wire(monkeypatch, runs, resets):
    """run_chain_configure pops ``runs``: an exception to raise or a result."""
    monkeypatch.setattr(hand_ops, "resolve_motor_port", lambda config, presence: "/dev/fake")

    def run(plan, *, progress_callback, prompt_callback, should_stop):
        outcome = runs.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(hand_ops, "run_chain_configure", run)
    monkeypatch.setattr(hand_ops, "reset_motor", lambda plan, m: resets.append(m["id"]) or True)


def _aborted():
    # Built the way any orca_core >= 0.6.0 can raise it; invalid_motors is what
    # 0.7.0 adds, and the operation reads it with getattr for the same reason.
    exc = MotorChainAborted("motors [2] answer at the target baud but the chain before them "
                            "is incomplete", invalid_ids=[2])
    exc.invalid_motors = [{"id": 2, "model_name": "XC330", "baud_rate": 1_000_000}]
    return exc


def test_an_abort_offers_a_reset_and_the_chain_runs_again(monkeypatch):
    resets = []
    _wire(monkeypatch, [_aborted(), [3, 2, 1]], resets)
    ctx = _Ctx(answers=["Reset and continue"])
    op = ConfigureChainOperation({"mode": "configure", "motor_type": "dynamixel"})

    assert op.run(ctx) == {"configured": [3, 2, 1]}
    assert resets == [2]
    assert ctx.prompts[0][1] == ["Reset and continue", "Stop"]
    assert ctx.service.supervisor.probed is False, "chain work skips the slow post-hand-off probe"
    assert [s["state"] for s in ctx.extra["chain"]] == ["pending", "pending", "pending"]
    assert ctx.service.supervisor.left


def test_declining_the_reset_fails_the_run_with_the_reason(monkeypatch):
    import pytest

    resets = []
    _wire(monkeypatch, [_aborted()], resets)
    ctx = _Ctx(answers=["Stop"])
    op = ConfigureChainOperation({"mode": "configure", "motor_type": "dynamixel"})

    with pytest.raises(RuntimeError, match="chain before them is incomplete"):
        op.run(ctx)
    assert resets == []
    assert [s["state"] for s in ctx.extra["chain"] if s["id"] == 2] == ["invalid"]
