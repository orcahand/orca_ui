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
    assert [s["key"] for s in ctx.extra["stages"]] == ["thumb_index", "middle"]
    assert ctx.extra["absent_joints"] == sorted(absent)


def test_the_exclusion_list_rides_along_with_every_score():
    ctx = _Ctx()
    presenter = _Presenter(ctx, {})
    excluded = [{"joint": "ring_mcp", "motor": 4, "reason": "motor did not answer at connect"}]
    presenter.progress({"event": "spread", "round": 1, "motors": [], "passed": 0, "scored": 0,
                        "fraction": 0.0, "excluded": excluded})
    assert ctx.extra["excluded"] == excluded


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
