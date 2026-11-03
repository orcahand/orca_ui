"""The Motors-tab chain grid must track the chain as the routine re-reads
it: a motor that dropped off and came back is green again."""

from types import SimpleNamespace

from orca_ui.hand.operations.chain import _ChainGrid, _progress_mapper


class _Ctx:
    def __init__(self):
        self.extra = None

    def set_extra(self, extra):
        self.extra = extra

    def log(self, *a, **k):
        pass

    def set_phase(self, *a, **k):
        pass

    def set_detail(self, *a, **k):
        pass

    def set_progress(self, *a, **k):
        pass


def _plan():
    return SimpleNamespace(all_target_ids=[3, 2, 1], wrist_id=1, motor_type="dynamixel",
                           target_baud=1_000_000, model_for=lambda m: "XC430" if m == 1 else "XC330")


def _states(ctx):
    return {slot["id"]: slot["state"] for slot in ctx.extra["chain"]}


def test_a_motor_that_drops_off_and_comes_back_is_configured_again():
    ctx, grid = _Ctx(), _ChainGrid(_plan())
    on_event = _progress_mapper(ctx, grid, "configure")

    on_event({"event": "step_started", "step": 1, "total": 3, "target_id": 3,
              "expected_model": "XC330", "attaches_to": "board", "message": "m"})
    on_event({"event": "motor_configured", "target_id": 3, "baudrate": 1_000_000, "configured_ids": [3]})
    on_event({"event": "step_started", "step": 2, "total": 3, "target_id": 2,
              "expected_model": "XC330", "attaches_to": "motor 3", "message": "m"})
    on_event({"event": "configured_motor_missing", "missing": [3]})
    assert _states(ctx)[3] == "invalid"

    on_event({"event": "configured_motor_returned", "target_id": 3})
    assert _states(ctx)[3] == "configured"


def test_every_step_redraws_the_prefix_from_the_chain_order():
    ctx, grid = _Ctx(), _ChainGrid(_plan())
    on_event = _progress_mapper(ctx, grid, "configure")

    on_event({"event": "configured_motor_missing", "missing": [3]})
    on_event({"event": "chain_shortened", "missing": [3], "stranded": [], "configured_ids": []})
    on_event({"event": "step_started", "step": 1, "total": 3, "target_id": 3,
              "expected_model": "XC330", "attaches_to": "board", "message": "m"})
    assert _states(ctx) == {3: "expected", 2: "pending", 1: "pending"}

    on_event({"event": "step_started", "step": 3, "total": 3, "target_id": 1,
              "expected_model": "XC430", "attaches_to": "motor 2", "message": "m"})
    assert _states(ctx) == {3: "configured", 2: "configured", 1: "expected"}


def test_a_motor_that_missed_one_survey_turns_green_when_it_answers_again():
    ctx, grid = _Ctx(), _ChainGrid(_plan())
    on_event = _progress_mapper(ctx, grid, "configure")
    on_event({"event": "step_started", "step": 2, "total": 3, "target_id": 2,
              "expected_model": "XC330", "attaches_to": "motor 3", "message": "m"})
    on_event({"event": "configured_motor_missing", "missing": [3]})
    assert _states(ctx)[3] == "invalid"
    on_event({"event": "configured_motors_back", "motor_ids": [3]})
    assert _states(ctx)[3] == "configured"
