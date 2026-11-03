"""Stopping during manual calibration ends the run as an abort, not a failed prompt."""

from types import SimpleNamespace

from orca_ui.hand.operations.calibrate import ManualCapture
from orca_ui.hand.operations.events import OperationStopped


def test_a_stop_while_waiting_for_the_operator_answers_abort():
    def stopped(*args):
        raise OperationStopped()

    ctx = SimpleNamespace(set_extra=lambda extra: None, set_phase=lambda *a, **k: None, wait_input=stopped)
    capture = ManualCapture(ctx, [{"joint": "index_mcp", "direction": "flex"}], lambda joint: 3)
    assert capture.prompt({"joint": "index_mcp", "direction": "flex", "motor": 3}) == "abort"
