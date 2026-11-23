"""Write to board: the connected hand's calibration and joint ranges onto its own board.

orca_core packs them (``board_push.push_for_hand``: the calibration file in force, the hand's
``joint_ranges.yaml``, and refuses a push that would lose newer ranges on the board) and writes them
with the store tool of a private orca_firmware checkout. Without that checkout nothing is offered:
writing a board is an internal step of the assemblers' rig flow, never a customer's. The hand lets
go of its port under a maintenance lease, the board is written and read back, and the hand reconnects.
"""

from __future__ import annotations

from orca_ui.hand.operations.base import OpContext, Operation


def board_writer() -> dict:
    """Whether this computer can write a hand's board, and why not."""
    try:
        from orca_core import board_push
    except ImportError:
        return {"available": False, "tool": None,
                "reason": "the installed orca_core cannot write a hand's board"}
    tool = board_push.firmware_tool()
    if tool is None:
        return {"available": False, "tool": None,
                "reason": f"no orca_firmware checkout with {board_push.TOOL_RELATIVE_PATH.as_posix()} at "
                          f"{board_push.firmware_checkout()} (or set {board_push.FIRMWARE_REPO_ENV}): "
                          "writing a hand's board is an internal tool"}
    return {"available": True, "tool": str(tool), "reason": None}


class BoardWriteOperation(Operation):
    kind = "board_write"

    @classmethod
    def validate(cls, service, params: dict) -> dict:
        from orca_ui.hand.service import ServiceError

        writer = board_writer()
        if not writer["available"]:
            raise ServiceError(writer["reason"], status_code=409)
        session = service.session
        if session is None or not session.caps.motors:
            raise ServiceError("no hand is connected", status_code=409)
        if not getattr(session.hand, "board_hand_id", None):
            raise ServiceError("this hand has no board to write", status_code=409)
        if service.supervisor.status().torque_enabled:
            raise ServiceError("turn torque off before writing the board", status_code=409)
        return {}

    def run(self, ctx: OpContext) -> dict:
        from orca_core import board_push, hand_store

        supervisor = ctx.service.supervisor
        session = ctx.service.session
        if session is None:
            raise RuntimeError("the hand disconnected")
        hand = session.hand
        port = hand.config.port
        ctx.set_phase("releasing", "the hand lets go of its port")
        supervisor.enter_maintenance(self.kind, probe=False)
        try:
            ctx.set_phase("writing", f"calibration and joint ranges to the board on {port}")
            result = board_push.push_for_hand(hand)
            held = None
            if result.written:
                ctx.set_phase("reading back", f"what the board on {port} holds now")
                held = board_push.board_contents(port)
        finally:
            supervisor.exit_maintenance()
        ranges = (hand_store.read_joint_ranges(hand.hand_dir, hand.config.joint_ids) if hand.hand_dir else {})
        out = {"written": result.written, "reason": result.reason or None, "sequence": result.sequence,
               "size": result.size, "port": port,
               "file_ranges": sorted((ranges.get("joint_roms") or {})), "board": None, "confirmed": False}
        if held is not None:
            board_roms = (held.joint_ranges or {}).get("joint_roms") or {}
            file_roms = ranges.get("joint_roms") or {}
            out["board"] = {"sequence": held.sequence, "serial": held.identity.serial,
                            "ranges": sorted(board_roms),
                            "ranges_measured_at": (held.joint_ranges or {}).get("measured_at")}
            out["confirmed"] = held.sequence == result.sequence and \
                all(list(board_roms.get(j) or []) == list(r) for j, r in file_roms.items())
        ctx.log(f"board write: {'written' if result.written else 'not written'}"
                + (f" ({result.reason})" if result.reason else "")
                + (f", read back: sequence {held.sequence}, ranges of {len(out['board']['ranges'])} joints"
                   if held is not None else ""))
        return out
