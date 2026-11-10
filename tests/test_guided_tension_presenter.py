"""The guided-tension presenter turns the routine's events into the snapshot the
dialog renders; a hand with motors missing must show only the stages that run."""

from orca_ui.hand.operations import hand_ops
from orca_ui.hand.operations.guided_tension import _Presenter


class _Ctx:
    def __init__(self):
        self.extra = None
        self.lines = []

    def set_extra(self, extra):
        self.extra = extra

    def log(self, line):
        self.lines.append(line)

    def set_phase(self, *a, **k):
        pass


def test_stages_with_no_present_joint_leave_the_sidebar():
    ctx = _Ctx()
    presenter = _Presenter(ctx, {"hold_ap": 200.0})
    absent = ["thumb_cmc", "thumb_abd", "thumb_mcp", "thumb_dip",
              "ring_abd", "ring_mcp", "ring_pip", "pinky_abd", "pinky_mcp", "pinky_pip"]
    presenter.progress({"event": "step", "step": "pose", "round": 1,
                        "stage": hand_ops.range_stages()[0], "stage_index": 0, "stage_count": 2,
                        "absent_joints": absent})
    assert [s["key"] for s in ctx.extra["stages"]] == ["index", "middle"]
    assert ctx.extra["absent_joints"] == sorted(absent)


def test_the_exclusion_list_rides_along_with_every_score():
    ctx = _Ctx()
    presenter = _Presenter(ctx, {})
    excluded = [{"joint": "ring_mcp", "motor": 4, "reason": "motor did not answer at connect"}]
    presenter.progress({"event": "spread", "round": 1, "motors": [], "passed": 0, "scored": 0,
                        "fraction": 0.0, "excluded": excluded})
    assert ctx.extra["excluded"] == excluded


def test_a_latched_motor_is_shown_until_its_reboot_clears_it(monkeypatch):
    """The routine names a latched motor; the dialog must show it with what to
    do, a "reboot:<id>" input must reboot that motor on the maintenance hand,
    and the entry must leave once the routine sees the register clear."""
    from orca_ui.hand.operations import hand_ops
    from orca_ui.hand.operations.guided_tension import GuidedTensionOperation

    ctx = _Ctx()
    op = GuidedTensionOperation({})
    presenter = op._presenter = _Presenter(ctx, {})
    presenter.progress({"event": "fault", "motor": 8, "joint": "index_mcp", "flags": ["overload"]})
    fault = ctx.extra["faults"]["8"]
    assert fault["kind"] == "load" and fault["joint"] == "index_mcp" and "reboot" in fault["advice"]

    rebooted = []

    class _Hand:
        class config:
            motor_to_joint_dict = {8: "index_mcp"}

    op._hand = _Hand()
    monkeypatch.setattr(hand_ops, "reboot_held_motor", lambda hand, mid: rebooted.append(mid) or [])
    assert op.handle_input("reboot:8") is True
    assert rebooted == [8]
    # Cleared on the reply itself: the routine's own re-read may be a step away.
    assert ctx.extra["faults"] == {}
    assert any("holding again" in line for line in ctx.lines)
    # A reboot the fault survives stays shown, marked as such.
    monkeypatch.setattr(hand_ops, "reboot_held_motor", lambda hand, mid: ["overload"])
    op.handle_input("reboot:8")
    assert ctx.extra["faults"]["8"]["relatched"] is True


def test_rounds_count_on_from_the_saved_progress():
    """A run that resumes after two scored rounds opens on round 3; only a
    restart (no saved progress) begins at round 1."""
    ctx = _Ctx()
    presenter = _Presenter(ctx, {})
    presenter.progress({"event": "resumed", "best": {"index_mcp": 0.9}, "rounds": 2})
    presenter.progress({"event": "step", "step": "pose", "round": 1})
    assert ctx.extra["round"] == 3
    presenter.progress({"event": "score", "round": 1, "motors": [], "passed": 1, "scored": 1,
                        "fraction": 1.0})
    assert ctx.extra["history"][-1]["round"] == 3
    assert ctx.lines[-1].startswith("round 3:")

    fresh = _Ctx()
    _Presenter(fresh, {}).progress({"event": "step", "step": "pose", "round": 1})
    assert fresh.extra["round"] == 1


def test_limits_read_back_and_drawn_currents_reach_the_operation_log():
    """So a run's log shows the limit each motor held and what it drew, and a
    limit that did not land stands out."""
    ctx = _Ctx()
    presenter = _Presenter(ctx, {})
    stage = {"key": "ring", "joints": ["ring_abd", "ring_mcp", "ring_pip"]}
    presenter.progress({"event": "current_limits", "phase": "range_check", "stage": stage,
                        "limits": {"ring_mcp": {"asked": 140.0, "held": 140.0},
                                   "index_mcp": {"asked": 300.0, "held": 300.0},
                                   "wrist": {"asked": 100.0, "held": None}}})
    assert ctx.lines[-1] == ("current limits (range check, ring), asked→held mA: "
                             "ring_mcp 140→140, index_mcp 300→300, wrist 100→none")
    presenter.progress({"event": "current_limits", "phase": "pull",
                        "limits": {"ring_mcp": {"asked": 300.0, "held": 0.0}}})
    assert "MISMATCH on ring_mcp" in ctx.lines[-1]
    presenter.progress({"event": "currents_drawn", "stage": stage,
                        "drawn": {"ring_mcp": {"peak": 132.0, "mean": 41.5}}})
    assert ctx.lines[-1] == "currents drawn while checking ring, peak/mean mA: ring_mcp 132/41.5"
