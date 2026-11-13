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


def test_the_score_sheet_carries_exclusions_and_suggests_no_clicks_for_unswept_joints():
    """A run that jumps to the ratchet mid-round leaves joints unswept: their
    full "slack" is no measurement, so they must not be given clicks."""
    ctx = _Ctx()
    presenter = _Presenter(ctx, {})
    excluded = [{"joint": "ring_mcp", "motor": 4, "reason": "motor did not answer at connect"}]
    row = {"expected_deg": 100.0, "kept": None, "status": "low"}
    motors = [{**row, "joint": "index_mcp", "motor": 5, "spread_deg": 84.0, "slack_deg": 16.0},
              {**row, "joint": "index_pip", "motor": 6, "spread_deg": 0.0, "slack_deg": 100.0}]
    presenter.progress({"event": "spread", "round": 1, "motors": motors, "passed": 0, "scored": 2,
                        "fraction": 0.0, "excluded": excluded})
    assert ctx.extra["excluded"] == excluded
    swept, unswept = ctx.extra["motors"]
    assert swept["clicks_left"] == 2 and not swept.get("not_checked")
    assert unswept["not_checked"] is True and unswept["clicks_left"] is None


def test_a_range_checked_joint_whose_motor_never_moved_still_gets_clicks():
    """A fully slack tendon leaves its motor still: zero spread from a range
    check is the slackest result, not a joint nobody checked."""
    ctx = _Ctx()
    presenter = _Presenter(ctx, {})
    stage = {"key": "index", "joints": ["index_mcp"], "pose": "flat"}
    presenter.progress({"event": "step", "step": "range", "round": 1, "stage": stage,
                        "stage_index": 0, "stage_count": 1})
    row = {"expected_deg": 100.0, "kept": None, "status": "low", "spread_deg": 0.0,
           "slack_deg": 100.0, "motor": 5}
    presenter.progress({"event": "score", "round": 1, "passed": 0, "scored": 2, "fraction": 0.0,
                        "motors": [{**row, "joint": "index_mcp"}, {**row, "joint": "middle_mcp"}]})
    checked, unchecked = ctx.extra["motors"]
    assert not checked.get("not_checked") and checked["clicks_left"]
    assert unchecked["not_checked"] is True

    presenter.progress({"event": "step", "step": "pose", "round": 2, "stage": stage,
                        "stage_index": 0, "stage_count": 1})
    # Saved progress keeps 0.0 for a joint that was never swept: still no score, so no clicks.
    presenter.progress({"event": "score", "round": 2, "passed": 0, "scored": 2, "fraction": 0.0,
                        "motors": [{**row, "joint": "index_mcp", "kept": 0.0},
                                   {**row, "joint": "middle_mcp", "kept": 0.0}]})
    assert all(m["not_checked"] and m["clicks_left"] is None for m in ctx.extra["motors"])


def test_a_latched_motor_is_shown_until_its_reboot_clears_it(monkeypatch):
    """The routine names a latched motor; the dialog must show it with what to
    do, a "reboot:<id>" input must reboot that motor on the maintenance hand,
    and the entry must leave once the routine sees the register clear."""
    from orca_ui.hand.operations import hand_ops
    from orca_ui.hand.operations.guided_tension import GuidedTensionOperation

    ctx = _Ctx()
    op = GuidedTensionOperation({})
    presenter = op._presenter = _Presenter(ctx, {})
    presenter.progress({"event": "step", "step": "range", "round": 1})
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
    presenter.progress({"event": "fault", "motor": 8, "joint": "index_mcp", "flags": ["overload"]})
    monkeypatch.setattr(hand_ops, "reboot_held_motor", lambda hand, mid: ["overload"])
    op.handle_input("reboot:8")
    assert ctx.extra["faults"]["8"]["relatched"] is True


def test_a_reboot_is_refused_unless_that_motor_is_faulted_and_the_motors_hold(monkeypatch):
    from orca_ui.hand.operations import hand_ops
    from orca_ui.hand.operations.guided_tension import GuidedTensionOperation

    ctx = _Ctx()
    op = GuidedTensionOperation({})
    presenter = op._presenter = _Presenter(ctx, {})

    class _Hand:
        class config:
            motor_to_joint_dict = {8: "index_mcp", 1: "wrist"}

    op._hand = _Hand()
    rebooted = []
    monkeypatch.setattr(hand_ops, "reboot_held_motor", lambda hand, mid: rebooted.append(mid) or [])
    presenter.progress({"event": "step", "step": "pose", "round": 1})
    presenter.progress({"event": "fault", "motor": 8, "joint": "index_mcp", "flags": ["overload"]})
    op.handle_input("reboot:8")
    presenter.progress({"event": "step", "step": "range", "round": 1})
    for motor in ("254", "1", "-1"):
        op.handle_input(f"reboot:{motor}")
    assert rebooted == []
    op.handle_input("reboot:8")
    assert rebooted == [8]


def test_the_slack_tests_clicks_leave_after_the_first_tension_step():
    ctx = _Ctx()
    presenter = _Presenter(ctx, {})
    presenter.seed_ratchet({"index_mcp": 3})
    presenter.progress({"event": "step", "step": "tension", "round": 1})
    assert ctx.extra["ratchet"] == {"index_mcp": 3}
    presenter.progress({"event": "step", "step": "pose", "round": 2})
    assert "ratchet" not in ctx.extra


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


def test_a_dead_sampler_and_motors_left_holding_are_shown_and_logged():
    """Spreads that stopped updating, and motors that never acknowledged torque
    off at the end of the run, must reach the dialog and the log in plain words."""
    ctx = _Ctx()
    presenter = _Presenter(ctx, {})
    presenter.progress({"event": "sampler_failed", "round": 2, "error": "bus timeout"})
    presenter.progress({"event": "torque_off_failed", "motors": [7], "joints": ["index_pip"]})
    assert ctx.extra["sampler_failed"] == {"round": 2, "error": "bus timeout"}
    assert ctx.extra["torque_off_failed"] == {"motors": [7], "joints": ["index_pip"]}
    assert "no longer update" in ctx.lines[0]
    assert "motor 7 (index_pip)" in ctx.lines[1] and "E-STOP" in ctx.lines[1]
