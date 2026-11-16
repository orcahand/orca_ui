"""Checks for the orca_core 0.14 / UI 0.6 release plan: the hand's own folder,
session hardware versions, the board's calibration, and torque off on every
way out of a routine.

Every check that changes the hand's files backs them up first and puts them
back on every way out (also on Stop or a failure), then has the console
reconnect so it runs on what is on disk again. Checks that move the hand say
so in their step's instructions and leave torque off.
"""

from __future__ import annotations

import contextlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

from orca_ui.hardware_tests.checks.base import CheckContext, StopRequested, register
from orca_ui.hardware_tests.checks.console import (
    POLL_S,
    STOP_GRACE_S,
    _busy,
    _no_hand,
    _service_error,
    _wait,
    _wait_connected,
)
from orca_ui.hardware_tests.model import CheckResult, Metric, Series

HAND_FILES = ("calibration.yaml", "calibration.previous.yaml", "joint_ranges.yaml", "setup.yaml",
              "hand.yaml", "board.bin")
"""What a check may change in the hand's folder (the archive is only ever added to)."""
STOP_DEADLINE_S = 10.0
"""A stopped routine must have let go of the hand within this long."""
HOLD_WAIT_S = 3.0
"""How long a routine runs before the check stops it, so motors are holding."""
VERSIONS = (200, 210, 211)


# ----- helpers ---------------------------------------------------------------------------


def hands_root() -> Path:
    """orca_core's folder of hand folders: <ORCA_HOME>/hands."""
    from orca_core.hand_store import HANDS_DIR, orca_home

    return orca_home() / HANDS_DIR


def _mock(ctx: CheckContext) -> bool:
    return bool(getattr(getattr(ctx, "settings", None), "mock", False)
                or getattr(ctx.service.settings, "mock", False))


def _hand(ctx: CheckContext):
    session = ctx.service.session
    return session.hand if session is not None else None


def _hand_dir(ctx: CheckContext) -> Optional[Path]:
    hand = _hand(ctx)
    folder = getattr(hand, "hand_dir", None) if hand is not None else None
    return Path(folder) if folder else None


def _calibration(ctx: CheckContext) -> dict:
    hand = _hand(ctx)
    try:
        return dict(hand.calibration_info) if hand is not None else {}
    except Exception:
        return {}


def _in_progress(path: Optional[str]) -> bool:
    """Whether the calibration file carries orca_core's mark of a run that never finished."""
    from orca_core.calibration_store import IN_PROGRESS, read_document

    try:
        return bool(path) and bool(read_document(path).get(IN_PROGRESS))
    except Exception:
        return False


def stopped_calibration_outcome(before: dict, after: dict, in_progress: bool) -> tuple[str, bool]:
    """orca_core saves after every step: a stopped run either wrote nothing, or left its
    partial file marked in progress with the last complete calibration as the previous."""
    stamp = lambda info: (info or {}).get("calibrated_at")  # noqa: E731
    if stamp(after) == stamp(before) and stamp(after.get("previous")) == stamp(before.get("previous")):
        return "unchanged (stopped before its first save)", True
    if not in_progress:
        return "replaced, but not marked as an unfinished run", False
    kept = stamp(before.get("previous")) if _was_unfinished(before) else stamp(before)
    if stamp(after.get("previous")) != kept:
        return (f"partial run in force, but the previous is {stamp(after.get('previous'))}, "
                f"not the last complete calibration ({kept})"), False
    return "partial run in force, marked unfinished; the last complete calibration is the previous", True


def _was_unfinished(info: dict) -> bool:
    return bool((info or {}).get("in_progress"))


def _state(ctx: CheckContext) -> dict:
    return ctx.service.hand_store_state() or {}


def _await_new_session(ctx: CheckContext, old, timeout_s: float = 60.0) -> None:
    """Wait until the console runs a session other than ``old`` and it is ready:
    a reconnect is only requested, so the old session may still look connected."""
    deadline = time.monotonic() + timeout_s
    while ctx.service.session is old or ctx.service.session is None:
        if time.monotonic() > deadline:
            raise TimeoutError(f"the console did not reconnect within {timeout_s:g} s")
        _wait(ctx, POLL_S)
    _wait_connected(ctx)


def _reconnect(ctx: CheckContext) -> None:
    """Have the console drop and redial the hand, and wait until it is ready again."""
    old = ctx.service.session
    ctx.service.reconnect()
    _await_new_session(ctx, old)


def _after(ctx: CheckContext, action: Callable[[], Any]) -> Any:
    """Run a console action that reconnects the hand, and wait for the new session."""
    old = ctx.service.session
    value = action()
    _await_new_session(ctx, old)
    return value


def _disconnect_reconnect(ctx: CheckContext) -> None:
    """What a person's Disconnect then Reconnect does."""
    ctx.service.disconnect()
    _wait(ctx, 0.5)
    _reconnect(ctx)


def calibration_file(ctx: CheckContext) -> Optional[Path]:
    """The calibration file the hand runs on: in its folder, unless one was named
    (the mock console keeps its own)."""
    path = _calibration(ctx).get("path") or getattr(getattr(_hand(ctx), "config", None), "calibration_path", None)
    if path:
        return Path(path)
    folder = _hand_dir(ctx)
    return folder / "calibration.yaml" if folder else None


@contextlib.contextmanager
def hand_files_restored(ctx: CheckContext, names: tuple[str, ...] = HAND_FILES) -> Iterator[Path]:
    """Back up ``names`` from the hand's folder (and a calibration kept elsewhere)
    and put them back afterwards, removing any the check created; reconnects so
    the console reads them again."""
    folder = _hand_dir(ctx)
    if folder is None:
        raise RuntimeError("the connected hand has no folder of its own yet")
    paths = [folder / name for name in names]
    if "calibration.yaml" in names:
        calibration = calibration_file(ctx)
        if calibration is not None and calibration.parent != folder:
            paths += [calibration, calibration.with_name("calibration.previous.yaml")]
    backup = ctx.out_dir / "backup"
    backup.mkdir(parents=True, exist_ok=True)
    had = {}
    for index, path in enumerate(paths):
        had[path] = path.is_file()
        if had[path]:
            shutil.copy2(path, backup / f"{index}-{path.name}")
    ctx.log(f"backed up {', '.join(str(p) for p in paths if had[p]) or 'nothing'}")
    try:
        yield folder
    finally:
        _torque_off_quietly(ctx)
        for index, path in enumerate(paths):
            if had[path]:
                shutil.copy2(backup / f"{index}-{path.name}", path)
            elif path.exists():
                path.unlink()
        ctx.log(f"put back the hand's files in {folder}")
        with contextlib.suppress(Exception):
            _reconnect(ctx)


def _torque_off_quietly(ctx: CheckContext) -> None:
    with contextlib.suppress(Exception):
        session = ctx.service.session
        if session is not None and session.caps.motors:
            ctx.service.disable_torque()


def torque_states(service) -> dict[int, Optional[bool]]:
    """Torque enable as each motor reports it (None: no answer, or no way to ask)."""
    from orca_ui.hand.service import _bus_fence

    session = service.session
    if session is None or not session.caps.motors:
        return {}
    hand = session.hand
    client = hand.motor_client
    ids = list(hand.config.motor_ids)
    mock_states = getattr(client, "_torque_enabled", None)
    if type(client).__name__.startswith("Mock") and isinstance(mock_states, dict):
        return {m: bool(mock_states.get(m)) for m in ids}
    module = type(client).__module__
    if module.endswith("dynamixel_client"):
        from orca_core.hardware.dynamixel_client import ADDR_TORQUE_ENABLE

        def read(m):
            return client.packet_handler.read1ByteTxRx(client.port_handler, m, ADDR_TORQUE_ENABLE)
    elif module.endswith("feetech_client"):
        from orca_core.hardware.feetech_registers import HLS

        def read(m):
            return client.packet_handler.read1ByteTxRx(m, HLS.TORQUE_ENABLE)
    else:
        return {m: None for m in ids}
    out: dict[int, Optional[bool]] = {}
    with _bus_fence(hand):
        for m in ids:
            try:
                with client._bus_lock:
                    value, result, error = read(int(m))
                out[m] = bool(value) if result == 0 and error == 0 else None
            except Exception:
                out[m] = None
    return out


RECONNECT_READ = "torque read after the console reconnected (the reconnect switches torque off itself)"


def reconnect_torque(states: dict) -> tuple[Metric, list[str]]:
    """The console's torque read, taken after it reconnected: its connect switches torque off
    (supervisor.py), so an all-off read proves nothing and is only recorded. A motor that
    still reads on fails all the same."""
    on = sorted(m for m, v in states.items() if v)
    off = sum(1 for v in states.values() if v is False)
    silent = sum(1 for v in states.values() if v is None)
    value = (f"{off} of {len(states)} off" + (f", {silent} silent" if silent else "")
             + (f", on: {', '.join(map(str, on))}" if on else "")) if states else "no motors read"
    problems = [f"motor(s) {', '.join(map(str, on))} read torque on even after the reconnect"] if on else []
    return Metric(RECONNECT_READ, value, ok=False if on else None), problems


def _flagged(failed: Optional[dict]) -> tuple[Metric, list[str]]:
    """orca_core's own read-back on a routine's way out: ``torque_off_failed`` names motors
    it could not confirm off."""
    motors = ", ".join(map(str, (failed or {}).get("motors") or []))
    metric = Metric("motors orca_core flagged as maybe holding", motors or "none", ok=not failed)
    return metric, ([f"orca_core could not confirm torque off on motor(s) {motors or '?'}"] if failed else [])


def _manager(ctx: CheckContext):
    manager = ctx.service.operation_manager
    if manager is None:
        raise RuntimeError("the console has no operation manager")
    return manager


def start_operation(ctx: CheckContext, kind: str, params: Optional[dict] = None) -> str:
    params = dict(params or {})
    if _mock(ctx):
        params.setdefault("step_duration_s", 0.05)
    else:
        params.pop("step_duration_s", None)
    snapshot = _manager(ctx).start(kind, params)
    ctx.log(f"started {kind} ({snapshot.get('run_id')})")
    return snapshot.get("run_id")


def follow_operation(ctx: CheckContext, run_id: str, *, answer: Optional[Callable[[dict], Optional[str]]] = None,
                     until: Optional[Callable[[dict, float], bool]] = None,
                     timeout_s: float = 1800.0) -> dict:
    """Follow ``run_id`` until it ends or ``until(snapshot, seconds)`` holds; prompts
    go to ``answer`` (None or no answer stops the run). Stop stops the operation too."""
    manager = _manager(ctx)
    start = time.monotonic()
    answered: Optional[tuple] = None
    while True:
        snapshot = manager.snapshot() or {}
        if snapshot.get("run_id") != run_id:
            raise RuntimeError("the operation was replaced by another one")
        elapsed = time.monotonic() - start
        if snapshot.get("state") in ("done", "error"):
            return snapshot
        if until is not None and until(snapshot, elapsed):
            return snapshot
        if snapshot.get("state") == "awaiting_input":
            awaiting = snapshot.get("awaiting") or {}
            key = (awaiting.get("prompt"), tuple(awaiting.get("options") or []), awaiting.get("seq"),
                   json.dumps(snapshot.get("extra") or {}, sort_keys=True, default=str)[:2000])
            if key != answered:
                value = answer(snapshot) if answer is not None else None
                if value is None:
                    stop_operation(ctx, run_id)
                    raise RuntimeError(f"the operation asked {awaiting.get('prompt')!r} and the check has no answer")
                answered = key
                manager.send_input(value)
        if elapsed > timeout_s:
            stop_operation(ctx, run_id)
            raise TimeoutError(f"the operation did not finish within {timeout_s:g} s")
        try:
            _wait(ctx, POLL_S)
        except StopRequested:
            stop_operation(ctx, run_id)
            raise


def stop_operation(ctx: CheckContext, run_id: str, *, estop: bool = False) -> tuple[dict, float]:
    """Stop (or E-STOP) the run; ``(last snapshot, seconds until it ended)``."""
    manager = _manager(ctx)
    start = time.monotonic()
    if estop:
        ctx.service.estop()
    else:
        manager.stop()
    while True:
        snapshot = manager.snapshot() or {}
        if snapshot.get("run_id") != run_id or snapshot.get("state") in ("done", "error"):
            return snapshot, time.monotonic() - start
        if time.monotonic() - start > STOP_GRACE_S:
            return snapshot, time.monotonic() - start
        time.sleep(0.05)


def _refusal(fn: Callable[[], Any]) -> Optional[str]:
    """The console's refusal message, or None when ``fn`` went through."""
    try:
        fn()
    except _service_error() as e:
        return str(e)
    return None


def _ready(ctx: CheckContext) -> Optional[CheckResult]:
    return _no_hand(ctx) or _busy(ctx)


def _fail_or_pass(problems: list[str], ok: str, metrics: list[Metric], **extra) -> CheckResult:
    if problems:
        return CheckResult(status="fail", summary="; ".join(problems) + ".", metrics=metrics, **extra)
    return CheckResult(status="pass", summary=ok, metrics=metrics, **extra)


@register("torque_off_now")
def torque_off_now(ctx: CheckContext) -> CheckResult:
    """After a hands-on stop: the routine ended and orca_core confirmed torque off on its
    way out. The console's own read comes after its reconnect, so it is only recorded."""
    blocked = _no_hand(ctx)
    if blocked:
        return blocked
    manager = ctx.service.operation_manager
    snapshot = (manager.snapshot() if manager is not None else None) or {}
    wanted = str(getattr(ctx.step, "action", None) or "").partition("operation:")[2] or None
    kind, state = snapshot.get("kind"), snapshot.get("state")
    if not snapshot:
        return CheckResult(status="error", summary="no routine ran in this console session: start it with "
                           "the button, then Stop")
    if wanted and kind != wanted:
        return CheckResult(status="error", summary=f"the last routine was {kind}, not {wanted}: start "
                           f"{wanted} with the button, then Stop")
    if state not in ("done", "error"):
        return CheckResult(status="error", summary=f"the {kind} is still {state}: press Stop first")
    try:
        _wait_connected(ctx)
    except TimeoutError as e:
        return CheckResult(status="error", summary=f"{e}; nothing was read")
    states = torque_states(ctx.service)
    read, problems = reconnect_torque(states)
    if not any(v is not None for v in states.values()):
        return CheckResult(status="error", summary="no motors read: the console got no torque read-back",
                           metrics=[read])
    flagged, flag_problems = _flagged((snapshot.get("extra") or {}).get("torque_off_failed"))
    metrics = [Metric("ended as", f"{state} ({snapshot.get('detail') or snapshot.get('error') or ''})"),
               flagged, read]
    return _fail_or_pass(flag_problems + problems, f"the {kind.replace('_', ' ')} ended and orca_core confirmed "
                         "torque off on every motor on its way out.", metrics,
                         details={"torque": {str(k): v for k, v in states.items()}, "snapshot": snapshot})


# ----- 1. the upgrade --------------------------------------------------------------------


@register("ui_home_moved")
def ui_home_moved(ctx: CheckContext) -> CheckResult:
    """The console's state lives in <ORCA_HOME>/ui; ~/.orca_ui, if any, links there."""
    from orca_ui.home import _custom_orca_home, legacy_ui_home, orca_home, ui_home

    home, legacy = ui_home(), legacy_ui_home()
    expected = orca_home() / "ui"
    metrics = [Metric("console state folder", str(home), ok=home == expected),
               Metric("ORCA_HOME", str(orca_home())),
               Metric("~/.orca_ui", "link" if legacy.is_symlink() else "folder" if legacy.exists() else "absent")]
    problems = []
    if home != expected:
        problems.append(f"the console keeps its state in {home}, not {expected} (the move did not happen)")
    if legacy.is_symlink():
        target = Path(os.readlink(legacy))
        ok = legacy.resolve() == expected.resolve()
        metrics.append(Metric("link points to", str(target), ok=ok))
        if not ok:
            problems.append(f"~/.orca_ui points to {target}, not {expected}")
    elif legacy.exists() and not _custom_orca_home():
        problems.append("~/.orca_ui is still a folder of its own: it was not moved")
    library = home / "library"
    entries = sorted(p.name for p in library.iterdir()) if library.is_dir() else []
    metrics.append(Metric("library entries", len(entries)))
    poses = ctx.service.list_poses()
    metrics.append(Metric("poses the console lists", len(poses)))
    return _fail_or_pass(problems, f"the console keeps its state in {home}; its library has {len(entries)} "
                         f"entries and it lists {len(poses)} poses.", metrics)


@register("hand_folder_matches")
def hand_folder_matches(ctx: CheckContext) -> CheckResult:
    """The connected hand's folder is <ORCA_HOME>/hands/<id> with its hand.yaml, and
    the id is the one the header shows."""
    blocked = _no_hand(ctx)
    if blocked:
        return blocked
    hand = _hand(ctx)
    state = _state(ctx)
    folder = _hand_dir(ctx)
    hand_id = getattr(hand, "hand_id", None)
    metrics = [Metric("hand id (header)", state.get("id")), Metric("hand id (orca_core)", hand_id),
               Metric("folder", str(folder) if folder else None)]
    problems = []
    if not hand_id or state.get("id") != hand_id:
        problems.append(f"the header shows {state.get('id')!r}, orca_core says {hand_id!r}")
    if folder is None or folder.name != hand_id:
        problems.append(f"the folder {folder} is not named after the hand id")
    if _mock(ctx):
        metrics.append(Metric("mock hand", "kept in a temporary folder"))
    else:
        root = hands_root()
        metrics.append(Metric("hands folder", str(root)))
        if folder is not None and folder.parent != root:
            problems.append(f"the folder is not under {root}")
        metrics.append(Metric("hands on this computer", len([p for p in root.iterdir() if p.is_dir()])
                              if root.is_dir() else 0))
    if folder is not None and not (folder / "hand.yaml").is_file():
        problems.append("the folder has no hand.yaml")
    return _fail_or_pass(problems, f"hand {hand_id} keeps its files in {folder}.", metrics)


@register("legacy_notice_state")
def legacy_notice_state(ctx: CheckContext) -> CheckResult:
    """Records which files from before the hand store the console names, if any."""
    state = _state(ctx)
    files = list(state.get("legacy_files") or [])
    return CheckResult(status="pass", summary=(f"the notice lists {len(files)} file(s) from before this version"
                                               if files else "no notice: none found, or it was dismissed"),
                       metrics=[Metric("files listed", len(files))], details={"legacy_files": files})


# ----- 2. hand menu ----------------------------------------------------------------------


@register("nickname_roundtrip")
def nickname_roundtrip(ctx: CheckContext) -> CheckResult:
    """Set, rename and clear the nickname; the original is put back."""
    blocked = _no_hand(ctx)
    if blocked:
        return blocked
    original = _state(ctx).get("nickname")
    seen = []
    try:
        for name in ("hwtest-a", "hwtest-b", None):
            ctx.check_stop()
            seen.append(ctx.service.set_nickname(name).get("nickname"))
        _reconnect(ctx)
        after_reconnect = _state(ctx).get("nickname")
        ctx.service.set_nickname("hwtest-kept")
        _reconnect(ctx)
        kept = _state(ctx).get("nickname")
    finally:
        with contextlib.suppress(Exception):
            ctx.service.set_nickname(original)
    restored = _state(ctx).get("nickname")
    metrics = [Metric("set, renamed, cleared", " → ".join(str(n) for n in seen), ok=seen == ["hwtest-a", "hwtest-b", None]),
               Metric("kept over a reconnect", kept, ok=kept == "hwtest-kept"),
               Metric("cleared stays cleared", after_reconnect, ok=after_reconnect is None),
               Metric("original put back", restored, ok=restored == original)]
    problems = [m.name for m in metrics if m.ok is False]
    return _fail_or_pass(problems, "the nickname is set, renamed, cleared and kept over a reconnect; the "
                         "original is back.", metrics)


# ----- 3. calibrate and restore previous -------------------------------------------------


def _calibrate(ctx: CheckContext, joints: Optional[list]) -> dict:
    run_id = start_operation(ctx, "calibrate", {"joints": joints} if joints else {})
    snapshot = follow_operation(ctx, run_id, timeout_s=1800.0)
    _wait_connected(ctx)
    return snapshot


def _log_lines(ctx: CheckContext) -> list[str]:
    return [line.get("line", "") for line in (_manager(ctx).log_payload().get("lines") or [])]


@register("calibrate_and_restore")
def calibrate_and_restore(ctx: CheckContext) -> CheckResult:
    """Two calibrations, then restore previous: refused with torque on, swaps with
    torque off. The hand's calibration files are put back afterwards."""
    blocked = _ready(ctx)
    if blocked:
        return blocked
    if _mock(ctx):
        return CheckResult(status="skipped", summary="the mock console's calibration is simulated and writes no file")
    joints = (ctx.step.params or {}).get("joints")
    metrics: list[Metric] = []
    problems: list[str] = []
    before = _calibration(ctx)
    keep_new = not before.get("calibrated_at")
    with contextlib.ExitStack() as stack:
        if not keep_new:
            stack.enter_context(hand_files_restored(ctx, ("calibration.yaml", "calibration.previous.yaml")))
        ctx.progress(0.05, "first calibration")
        first = _calibrate(ctx, joints)
        named = [line for line in _log_lines(ctx) if str(_hand_dir(ctx) or "§") in line]
        info1 = _calibration(ctx)
        ctx.progress(0.45, "second calibration")
        second = _calibrate(ctx, joints)
        info2 = _calibration(ctx)
        for label, snap in (("first", first), ("second", second)):
            if snap.get("state") != "done" or snap.get("detail") == "stopped":
                problems.append(f"the {label} calibration ended {snap.get('state')}: {snap.get('error') or snap.get('detail')}")
        if problems:
            return CheckResult(status="fail", summary="; ".join(problems) + ".", metrics=metrics)
        metrics += [Metric("log names the file written", named[-1] if named else "no", ok=bool(named)),
                    Metric("sequence after two runs", info2.get("sequence"),
                           ok=info1.get("sequence") is not None and info2.get("sequence") == info1["sequence"] + 1),
                    Metric("previous is the first run", (info2.get("previous") or {}).get("calibrated_at"),
                           ok=(info2.get("previous") or {}).get("calibrated_at") == info1.get("calibrated_at"))]
        ctx.service.enable_torque()
        refused = _refusal(ctx.service.restore_previous_calibration)
        _torque_off_quietly(ctx)
        metrics.append(Metric("refused with torque on", refused or "no", ok=bool(refused) and "torque" in refused))
        ctx.progress(0.8, "restore previous")
        _after(ctx, ctx.service.restore_previous_calibration)
        info3 = _calibration(ctx)
        metrics.append(Metric("in force after restore", info3.get("calibrated_at"),
                              ok=info3.get("calibrated_at") == info1.get("calibrated_at")))
        metrics.append(Metric("previous after restore", (info3.get("previous") or {}).get("calibrated_at"),
                              ok=(info3.get("previous") or {}).get("calibrated_at") == info2.get("calibrated_at")))
        problems += [m.name for m in metrics if m.ok is False]
    tail = (" The hand had no calibration before, so the newest one stays." if keep_new
            else " The hand's own calibration files are back.")
    return _fail_or_pass(problems, "two calibrations, the log names the file, restore is refused with torque on "
                         "and swaps the two with torque off." + tail, metrics)


@register("refused_while_operation_runs")
def refused_while_operation_runs(ctx: CheckContext) -> CheckResult:
    """With a slack test waiting at its first joint, restore previous, the board's
    calibration and a version change are refused; the test carries on."""
    blocked = _ready(ctx)
    if blocked:
        return blocked
    with hand_files_restored(ctx, ("setup.yaml",)):
        run_id = start_operation(ctx, "slack_test")
        follow_operation(ctx, run_id, until=lambda s, t: s.get("state") == "awaiting_input", timeout_s=120.0)
        status = ctx.service.status()
        other = next(v for v in VERSIONS if v != status.get("hardware_version"))
        refusals = {
            "restore previous": _refusal(ctx.service.restore_previous_calibration),
            "take the board's calibration": _refusal(lambda: ctx.service.board_calibration_choice("use_board")),
            "hardware version change": _refusal(lambda: ctx.service.set_hardware_version(other)),
        }
        still = (_manager(ctx).snapshot() or {}).get("state")
        stop_operation(ctx, run_id)
        _wait_connected(ctx)
    metrics = [Metric(name, why or "went through", ok=bool(why) and "running" in why) for name, why in refusals.items()]
    metrics.append(Metric("slack test still waiting", still, ok=still == "awaiting_input"))
    problems = [m.name for m in metrics if m.ok is False]
    return _fail_or_pass(problems, "every change was refused while the slack test ran, and the test carried on.",
                         metrics, details={"refusals": refusals})


# ----- 4. hardware version for the session -----------------------------------------------


def _await_version(ctx: CheckContext, version: Optional[int], timeout_s: float = 60.0) -> dict:
    deadline = time.monotonic() + timeout_s
    while True:
        status = ctx.service.status()
        if (version is None or status.get("hardware_version") == version) and ctx.service.session_ready \
                and status.get("state") in ("connected", "degraded"):
            return status
        if time.monotonic() > deadline:
            return status
        _wait(ctx, POLL_S)


def _set_version(ctx: CheckContext, version: Optional[int]) -> dict:
    """Choose ``version`` for the session (None: the board's); waits out the reconnect
    a change of the version in force brings."""
    old, before = ctx.service.session, ctx.service.status().get("hardware_version")
    ctx.service.set_hardware_version(version)
    deadline = time.monotonic() + 5.0
    while ctx.service.session is old and time.monotonic() < deadline:
        if ctx.service.status().get("hardware_version") == before and version in (None, before):
            break
        _wait(ctx, POLL_S)
    if ctx.service.session is not old:
        _await_new_session(ctx, old)
    return _await_version(ctx, version)


@register("session_hardware_version")
def session_hardware_version(ctx: CheckContext) -> CheckResult:
    """A version chosen for the session is in force, survives Disconnect/Reconnect,
    and "use board's" takes it back; the original choice is restored."""
    blocked = _ready(ctx)
    if blocked:
        return blocked
    start = ctx.service.status()
    original = start.get("hardware_version_override")
    board = start.get("board_hardware_version")
    in_force = start.get("hardware_version")
    other = next(v for v in VERSIONS if v != in_force and (in_force is None or v // 10 != in_force // 10)) \
        if in_force is not None else 210
    metrics: list[Metric] = [Metric("board says", board), Metric("in force at the start", in_force)]
    try:
        chosen = _set_version(ctx, other)
        metrics.append(Metric("after choosing", chosen.get("hardware_version"),
                              ok=chosen.get("hardware_version") == other and chosen.get("hardware_version_override") == other))
        _disconnect_reconnect(ctx)
        again = _await_version(ctx, other)
        metrics.append(Metric("after Disconnect and Reconnect", again.get("hardware_version"),
                              ok=again.get("hardware_version") == other))
        back = _set_version(ctx, None)
        expected = board if board is not None else back.get("hardware_version")
        metrics.append(Metric("after use board's", back.get("hardware_version"),
                              ok=back.get("hardware_version_override") is None and back.get("hardware_version") == expected))
    finally:
        with contextlib.suppress(Exception):
            if ctx.service.status().get("hardware_version_override") != original:
                _set_version(ctx, original)
    problems = [m.name for m in metrics if m.ok is False]
    note = "" if board is not None else " This hand's board reports no version, so 'use board's' returns to the config's."
    return _fail_or_pass(problems, f"v{other} was in force for the session, kept over a reconnect, and dropped "
                         "again." + note + " A restart dropping it is covered by the console's tests.", metrics)


# ----- 5. the board's calibration --------------------------------------------------------


FIRMWARE_TOOL = Path("tools") / "bench" / "cal_store.py"
BOARD_WRITTEN = "Calibration also written to the hand's own board"
BOARD_NOT_WRITTEN = re.compile(r"Calibration kept on this computer only: (.+)")


def firmware_candidates(ctx: CheckContext) -> list[Path]:
    """Where an orca_firmware checkout is looked for, in order."""
    configured = (ctx.step.params or {}).get("firmware_repo") or os.environ.get("ORCA_FIRMWARE_REPO")
    candidates = [Path(configured).expanduser()] if configured else []
    checkout = getattr(ctx.sides, "checkout", lambda side: None)("branch")
    if checkout is not None:
        candidates += [checkout.parent / "orca_firmware", checkout.parent.parent / "orca_firmware"]
    candidates.append(Path.home() / "code" / "orca_firmware")
    return candidates


def firmware_repo(ctx: CheckContext) -> Optional[Path]:
    """The orca_firmware checkout calibrate.py needs to write the board: one that has its store tool."""
    return next((c.resolve() for c in firmware_candidates(ctx) if (c / FIRMWARE_TOOL).is_file()), None)


# orca_core's reasons for leaving the board alone that say nothing is wrong with the write itself
# (orca_core/board_push.py); every other "kept on this computer only" reason is a failed write.
BOARD_SKIP_REASONS = (
    re.compile(r"^no orca_firmware checkout (at |on this computer$)"),
    re.compile(r"^the orca_firmware checkout at .+ has no tools/bench/cal_store\.py$"),
    re.compile(r"^this hand has no board to keep a calibration on$"),
)


def board_write_outcome(returncode: int, output: str) -> tuple[str, str]:
    """What calibrate.py did with the board: ``wrote``, ``not_written`` (nothing to write
    with or to, with its reason) or ``failed`` (with its reason)."""
    if returncode == 0 and BOARD_WRITTEN in output:
        return "wrote", ""
    kept = BOARD_NOT_WRITTEN.search(output)
    if returncode == 0 and kept:
        reason = kept.group(1).strip().rstrip(".")
        if any(p.search(reason) for p in BOARD_SKIP_REASONS):
            return "not_written", reason
        return "failed", reason
    return "failed", f"exit {returncode}"


def _sensor_offsets(path: Optional[Path]) -> Any:
    import yaml

    try:
        return (yaml.safe_load(Path(path).read_text()) or {}).get("sensor_offsets") if path else None
    except (OSError, yaml.YAMLError):
        return None


@register("board_calibration_banner")
def board_calibration_banner(ctx: CheckContext) -> CheckResult:
    """calibrate.py writes a new calibration to the board (from a scratch store);
    the console then offers it and every answer behaves; the computer's files are
    put back. Moves the hand: a full calibration."""
    blocked = _ready(ctx)
    if blocked:
        return blocked
    if _mock(ctx):
        return CheckResult(status="skipped", summary="a mock hand has no board to write a calibration to")
    if ctx.service.status().get("board_hardware_version") is None and not getattr(_hand(ctx), "hand_id", None):
        return CheckResult(status="skipped", summary="this hand has no controller board")
    repo = firmware_repo(ctx)
    if repo is None:
        tried = ", ".join(str(c).replace(str(Path.home()), "~", 1) for c in firmware_candidates(ctx))
        return CheckResult(status="skipped", summary=f"no orca_firmware checkout with {FIRMWARE_TOOL} (tried {tried}); "
                           "set ORCA_FIRMWARE_REPO to one that has it and run the step again")
    runner = ctx.sides
    if runner.available("branch") is not None or not hasattr(runner, "run_script"):
        return CheckResult(status="skipped", summary=f"the branch's orca_core cannot run scripts: {runner.available('branch')}")
    metrics: list[Metric] = []
    problems: list[str] = []
    tactile_before = _sensor_offsets(calibration_file(ctx))
    with hand_files_restored(ctx):
        computer = _calibration(ctx)
        ctx.progress(0.05, "calibrate.py, writing the board")
        with runner.hand_released():
            ran = runner.run_script("branch", "calibrate.py", [], ctx.out_dir / "calibrate",
                                    timeout_s=1800.0, env={"ORCA_FIRMWARE_REPO": str(repo)})
        output = ran["stdout"] + ran["stderr"]
        outcome, reason = board_write_outcome(ran["returncode"], output)
        if outcome == "not_written":
            # calibrate.py finished but left the board alone; the hand's files are put back on the way out.
            return CheckResult(status="skipped", summary=f"calibrate.py ran but did not write the board: {reason}",
                               metrics=[Metric("calibrate.py wrote the board", reason, ok=None)],
                               details={"output": output[-3000:]})
        wrote = outcome == "wrote"
        metrics.append(Metric("calibrate.py wrote the board", "yes" if wrote else reason, ok=wrote))
        if not wrote:
            return CheckResult(status="fail", summary=f"calibrate.py did not write the board: {reason}",
                               metrics=metrics, details={"output": output[-3000:]})
        _wait_connected(ctx)
        offered = _state(ctx).get("board_calibration_newer")
        metrics.append(Metric("banner offers the board's", "yes" if offered else "no", ok=bool(offered)))
        ctx.service.board_calibration_choice("keep_session")
        hidden = _state(ctx).get("board_calibration_newer") is None
        _reconnect(ctx)
        hidden_reconnect = _state(ctx).get("board_calibration_newer") is None
        _disconnect_reconnect(ctx)
        back = _state(ctx).get("board_calibration_newer") is not None
        metrics += [Metric("keep this computer's hides it", "yes" if hidden else "no", ok=hidden),
                    Metric("still hidden after the console's own reconnect", "yes" if hidden_reconnect else "no",
                           ok=hidden_reconnect),
                    Metric("back after Disconnect and Reconnect", "yes" if back else "no", ok=back)]
        board_at = ((offered or {}).get("board") or {}).get("calibrated_at")
        ctx.progress(0.7, "use it")
        _after(ctx, lambda: ctx.service.board_calibration_choice("use_board"))
        used = _calibration(ctx)
        metrics += [Metric("in force after use it", used.get("calibrated_at"), ok=used.get("calibrated_at") == board_at),
                    Metric("previous is the computer's", (used.get("previous") or {}).get("calibrated_at"),
                           ok=(used.get("previous") or {}).get("calibrated_at") == computer.get("calibrated_at")),
                    Metric("banner gone after use it", "yes" if not _state(ctx).get("board_calibration_newer") else "no",
                           ok=not _state(ctx).get("board_calibration_newer"))]
        if tactile_before is not None:
            kept = _sensor_offsets(calibration_file(ctx)) == tactile_before
            metrics.append(Metric("tactile zero kept", "yes" if kept else "no", ok=kept))
        _after(ctx, ctx.service.restore_previous_calibration)
        again = _state(ctx).get("board_calibration_newer") is not None
        metrics.append(Metric("banner back after restore previous", "yes" if again else "no", ok=again))
        ctx.service.board_calibration_choice("keep_until_change")
        _disconnect_reconnect(ctx)
        quiet = _state(ctx).get("board_calibration_newer") is None
        metrics.append(Metric("don't ask again holds over a reconnect", "yes" if quiet else "no", ok=quiet))
    problems += [m.name for m in metrics if m.ok is False]
    return _fail_or_pass(problems, "the board's newer calibration was offered and every answer behaved. The "
                         "computer's files are back; the board keeps the new calibration, so the banner may offer it.",
                         metrics, details={"output": output[-3000:]})


# ----- 6. stops and torque off -----------------------------------------------------------


def _holding(wait_s: float) -> Callable[[dict, float], bool]:
    def until(snapshot: dict, seconds: float) -> bool:
        return snapshot.get("state") == "running" and seconds >= wait_s
    return until


def _slack_answer(snapshot: dict) -> Optional[str]:
    options = (snapshot.get("awaiting") or {}).get("options") or []
    return "Test" if "Test" in options else None


@register("stop_releases_torque")
def stop_releases_torque(ctx: CheckContext) -> CheckResult:
    """Start the step's routine, let it hold, Stop or E-STOP it: judged on how fast it
    ended and on orca_core's own torque read-back on the way out. Moves the hand. The
    hand's records are put back."""
    blocked = _ready(ctx)
    if blocked:
        return blocked
    params = ctx.step.params or {}
    kind = str(params.get("operation", "tension_sweep"))
    estop = params.get("how") == "estop"
    started_params = dict(params.get("params") or {})
    wait_s = HOLD_WAIT_S
    if _mock(ctx):
        # Simulated routines run on a timer: slow them so there is something to stop.
        started_params["step_duration_s"] = 1.0
        wait_s = 0.5
    before = _calibration(ctx)
    before["in_progress"] = _in_progress(before.get("path"))
    with hand_files_restored(ctx, ("setup.yaml", "calibration.yaml", "calibration.previous.yaml")):
        run_id = start_operation(ctx, kind, started_params)
        answer = _slack_answer if kind == "slack_test" else (lambda s: None)
        snapshot = follow_operation(ctx, run_id, answer=answer, until=_holding(wait_s), timeout_s=120.0)
        if snapshot.get("state") in ("done", "error"):
            return CheckResult(status="error", summary=f"{kind} ended before the check could stop it: "
                               f"{snapshot.get('error') or snapshot.get('detail')}")
        ended, seconds = stop_operation(ctx, run_id, estop=estop)
        failed = (ended.get("extra") or {}).get("torque_off_failed")
        _wait_connected(ctx)
        states = torque_states(ctx.service)
        after = _calibration(ctx)
        after_in_progress = _in_progress(after.get("path"))
    ended_ok = ended.get("run_id") != run_id or ended.get("state") in ("done", "error")
    flagged, problems = _flagged(failed)
    read, read_problems = reconnect_torque(states)
    metrics = [Metric("stopped within", round(seconds, 2), unit="s", ok=ended_ok and seconds <= STOP_DEADLINE_S),
               Metric("ended as", f"{ended.get('state')} ({ended.get('detail') or ended.get('error') or ''})",
                      ok=ended_ok),
               flagged, read]
    problems += read_problems
    if kind == "calibrate":
        outcome, kept = stopped_calibration_outcome(before, after, after_in_progress)
        metrics.append(Metric("calibration after the stop", outcome, ok=kept))
        if not kept:
            problems.append(f"a stopped calibration left the files wrong: {outcome}")
    if not ended_ok:
        problems.append(f"the routine had not ended {seconds:.1f} s after the {'E-STOP' if estop else 'Stop'}")
    elif seconds > STOP_DEADLINE_S:
        problems.append(f"the routine took {seconds:.1f} s to end")
    how = "E-STOP" if estop else "Stop"
    return _fail_or_pass(problems, f"{how} ended the {kind.replace('_', ' ')} in {seconds:.1f} s and orca_core "
                         "confirmed torque off on every motor on its way out.", metrics,
                         details={"torque": {str(k): v for k, v in states.items()}, "snapshot": ended})


# ----- 7. holding and the current limit --------------------------------------------------


def _mid_pose(config) -> dict:
    return {j: (float(r[0]) + float(r[1])) / 2 for j, r in config.joint_roms_dict.items()
            if j != "wrist" and j in config.joint_to_motor_map}


@register("holding_temperature")
def holding_temperature(ctx: CheckContext) -> CheckResult:
    """Hold a mid-flexed pose with torque on and watch the motor temperatures.
    Moves the hand; torque goes off at the end."""
    blocked = _ready(ctx)
    if blocked:
        return blocked
    if _mock(ctx):
        return CheckResult(status="skipped", summary="the mock hand's temperatures are synthetic")
    params = ctx.step.params or {}
    hold_s = float(params.get("hold_s", 180.0))
    max_rise = float(params.get("max_rise_c", 5.0))
    abort_rise = float(params.get("abort_rise_c", 15.0))
    abort_temp = float(params.get("abort_temp_c", 60.0))
    xs, peak = [], []
    start_temps: dict = {}
    temps: dict = {}
    currents: dict[int, list[float]] = {}
    joints: dict = {}
    targets = _mid_pose(ctx.service.session.hand.config)
    errors: dict = {}
    stopped = None
    try:
        ctx.service.enable_torque()
        ctx.service.set_targets(targets)
        _wait(ctx, 2.0)
        t0 = time.monotonic()
        while True:
            motors = ctx.service.motor_snapshot()["motors"]
            temps = {m["id"]: float(m["temp_c"]) for m in motors if m.get("temp_c") is not None}
            for m in motors:
                joints[m["id"]] = m.get("joint")
                if m.get("current_ma") is not None:
                    currents.setdefault(m["id"], []).append(float(m["current_ma"]))
            if not start_temps:
                start_temps = temps
            rise = max((temps[k] - start_temps.get(k, temps[k]) for k in temps), default=0.0)
            xs.append(round(time.monotonic() - t0, 1))
            peak.append(rise)
            ctx.progress(min(0.99, (time.monotonic() - t0) / hold_s), f"{rise:+.1f} °C")
            stopped = holding_abort(start_temps, temps, abort_rise, abort_temp)
            if stopped or time.monotonic() - t0 >= hold_s:
                break
            _wait(ctx, min(5.0, hold_s))
        pose = ctx.service.current_pose()
        errors = {j: float(pose[j]) - float(t) for j, t in targets.items() if j in pose}
    finally:
        _torque_off_quietly(ctx)
    if not start_temps:
        return CheckResult(status="skipped", summary="the motors report no temperature")
    worst = max(peak)
    table = holding_table(start_temps, temps, currents, joints, errors)
    hottest = "; ".join(f"M{r['motor']} {r['joint']} {r['rise_c']:+.0f} °C at {r['mean_ma']:.0f} mA, "
                        f"{r['error_deg']:+.0f}° from target" if r["error_deg"] is not None else
                        f"M{r['motor']} {r['joint']} {r['rise_c']:+.0f} °C at {r['mean_ma']:.0f} mA"
                        for r in table[:3])
    metrics = [Metric("largest rise", round(worst, 1), unit="°C", ok=worst <= max_rise),
               Metric("held for", round(xs[-1], 0), unit="s"), Metric("allowed rise", max_rise, unit="°C"),
               Metric("stopped early", stopped or "no", ok=None if not stopped else False),
               Metric("hottest motors", hottest or "none", ok=None)]
    series = [Series(name="largest temperature rise", x=xs, y=peak, y_label="°C")]
    problems = ([f"a motor warmed by {worst:.1f} °C ({hottest})"] if worst > max_rise else []) + \
        ([f"stopped early: {stopped}"] if stopped else [])
    return _fail_or_pass(problems, f"holding for {xs[-1]:.0f} s warmed no motor by more than {worst:.1f} °C.",
                         metrics, series=series, details={"motors": table})


def holding_abort(start: dict, temps: dict, max_rise: float, max_temp: float) -> Optional[str]:
    """Why holding must stop now: a motor warmed by more than ``max_rise`` or reached ``max_temp``."""
    for motor, temp in sorted(temps.items()):
        if temp >= max_temp:
            return f"motor {motor} reached {temp:.0f} °C"
        if temp - start.get(motor, temp) > max_rise:
            return f"motor {motor} warmed by {temp - start[motor]:.0f} °C"
    return None


def holding_table(start: dict, end: dict, currents: dict, joints: dict, errors: dict) -> list[dict]:
    """Per motor, hottest first: its joint, start and end temperature, mean current and
    how far the joint ended from its target (degrees, None when unknown)."""
    rows = []
    for motor, temp in end.items():
        joint = joints.get(motor) or ""
        drawn = currents.get(motor) or []
        rows.append({"motor": motor, "joint": joint, "start_c": start.get(motor, temp), "end_c": temp,
                     "rise_c": temp - start.get(motor, temp),
                     "mean_ma": abs(sum(drawn) / len(drawn)) if drawn else 0.0,
                     "error_deg": round(errors[joint], 1) if joint in errors else None})
    return sorted(rows, key=lambda r: (-r["rise_c"], -r["mean_ma"]))


@contextlib.contextmanager
def _max_current(ctx: CheckContext, ma: int) -> Iterator[None]:
    original = ctx.service.max_current
    ctx.service.set_max_current(ma)
    try:
        yield
    finally:
        if original is not None:
            with contextlib.suppress(Exception):
                ctx.service.set_max_current(int(original))


@register("current_limit_respected")
def current_limit_respected(ctx: CheckContext) -> CheckResult:
    """With max current at 100 mA, a tension sweep on one joint draws no more and
    the slack test offers no more. Moves the hand. Max current and records are put back."""
    blocked = _ready(ctx)
    if blocked:
        return blocked
    params = ctx.step.params or {}
    limit = int(params.get("limit_ma", 100))
    joint = str(params.get("joint", "index_mcp"))
    from orca_ui.hand import sweeps

    goal = None
    with hand_files_restored(ctx, ("setup.yaml",)), _max_current(ctx, limit):
        slack = (ctx.service.hand_info().get("slack_current") or {})
        offered = [float(v) for v in (slack.get("choices_ma") or []) if isinstance(v, (int, float))]
        default_ma = slack.get("default_ma")
        snapshot, data = {}, None
        if not _mock(ctx):
            run_id = start_operation(ctx, "tension_sweep", {"joints": [joint], "repeats": 1})
            snapshot = follow_operation(ctx, run_id, timeout_s=600.0)
            _wait_connected(ctx)
            saved = (snapshot.get("result") or {}).get("saved")
            data = sweeps.dataset(ctx.service.supervisor.config, saved) if saved else None
            # Read before the limit is put back: what the motors hold on the console's connection.
            goal = goal_current_metric(ctx.service, limit)
    results = (data or {}).get("results") or []
    metrics = [Metric("limit set", limit, unit="mA")]
    if _mock(ctx):
        metrics.append(Metric("sweep", "not swept (mock)"))
    else:
        metrics += sweep_current_metrics((data or {}).get("settings") or {}, results, limit)
        metrics.append(goal)
    metrics += [Metric("slack test's highest offered current", max(offered, default=None), unit="mA",
                       ok=not offered or max(offered) <= limit + 0.5),
                Metric("slack test's default", default_ma, unit="mA",
                       ok=default_ma is None or float(default_ma) <= limit + 0.5)]
    problems = [m.name for m in metrics if m.ok is False]
    if not results and not _mock(ctx):
        problems.append(f"the sweep saved no readings ({snapshot.get('error') or snapshot.get('detail')})")
    return _fail_or_pass(problems, f"with max current at {limit} mA every current the sweep and the slack test "
                         "command stays within it, the measured drive current stays within it, and the joint moved.",
                         metrics)


OVER_LIMIT_FACTOR = 1.15     # a reading above limit × this counts as over the limit
OVER_LIMIT_RUN = 3           # this many such readings in a row is current held above the limit
OVER_LIMIT_SHARE = 0.20      # as is more than this share of a run's readings
MOVED_DEG = 0.5              # a run whose joint moved less than this measured nothing


def _run_label(r: dict) -> str:
    return f"{r.get('joint')} {r.get('sense') or r.get('direction')}"


def _over_limit(currents: list[float], limit: float) -> tuple[int, int]:
    """(longest run of readings over the limit, how many are over it)."""
    longest = streak = over = 0
    for ma in currents:
        if abs(ma) > limit * OVER_LIMIT_FACTOR:
            over += 1
            streak += 1
            longest = max(longest, streak)
        else:
            streak = 0
    return longest, over


def sweep_current_metrics(settings: dict, results: list, limit: float) -> list[Metric]:
    """The sweep's commanded currents and its measured drive current against ``limit``:
    a run fails when its measured current stays above the limit, or when its joint never
    moved, since it then measured nothing."""
    commanded = {k: float(v) for k, v in settings.items()
                 if k.endswith("_current_ma") and isinstance(v, (int, float))}
    high = max(commanded.values(), default=None)
    held_over, still, highest = [], [], None
    for r in results:
        samples = [s for s in (r.get("samples") or []) if isinstance(s, (list, tuple)) and len(s) >= 2]
        currents = [float(s[1]) for s in samples if isinstance(s[1], (int, float))]
        if currents:
            highest = max(highest or 0.0, max(abs(c) for c in currents))
            longest, over = _over_limit(currents, limit)
            if longest >= OVER_LIMIT_RUN or over > OVER_LIMIT_SHARE * len(currents):
                held_over.append(f"{_run_label(r)}: {over}/{len(currents)} readings over "
                                 f"{limit * OVER_LIMIT_FACTOR:.0f} mA, mean {abs(float(r.get('mean_ma') or 0)):.0f} mA")
        angles = [float(s[0]) for s in samples if isinstance(s[0], (int, float))]
        span = (max(angles) - min(angles)) if angles else abs(float(r.get("end_deg") or 0) - float(r.get("start_deg") or 0))
        if span < MOVED_DEG:
            still.append(_run_label(r))
    return [
        Metric("sweep's highest commanded current", high, unit="mA", ok=bool(commanded) and high <= limit + 0.5),
        Metric("drive current held above the limit", "; ".join(held_over) or "no",
               ok=bool(results) and not held_over),
        Metric("sweep's highest drive current reading", highest, unit="mA", ok=None),
        Metric("did not move at this current", ", ".join(still) or "none", ok=bool(results) and not still),
    ]


GOAL_AFTER_SWEEP = "goal current the motors hold after the sweep (torque off)"


def goal_current_metric(service, limit: float) -> Metric:
    """What the motors hold once the sweep has ended, recorded only: the sweep puts back the
    hand file's limit, and the console writes its own again before it next enables torque."""
    session = service.session
    client = getattr(getattr(session, "hand", None), "motor_client", None)
    if client is None or not hasattr(client, "read_goal_currents"):
        return Metric(GOAL_AFTER_SWEEP, "no way to read it", ok=None)
    try:
        read = client.read_goal_currents()
    except Exception as e:
        return Metric(GOAL_AFTER_SWEEP, f"{type(e).__name__}: {e}", ok=None)
    values = [abs(float(v)) for v in read.values() if isinstance(v, (int, float))]
    above = sorted(m for m, v in read.items() if isinstance(v, (int, float)) and abs(float(v)) > limit + 0.5)
    shown = f"highest {max(values):.1f} mA" if values else "no answer"
    return Metric(GOAL_AFTER_SWEEP, shown + (f"; above the console's {limit:g} mA on motor(s) {above}" if above else ""),
                  unit="", ok=None)


@register("sweep_refused_below_minimum")
def sweep_refused_below_minimum(ctx: CheckContext) -> CheckResult:
    """With max current below the sweep's lowest setting the sweep refuses to start."""
    from orca_ui.hand.operations.tension_sweep import validate_sweep_params

    blocked = _ready(ctx)
    if blocked:
        return blocked
    limit = int((ctx.step.params or {}).get("limit_ma", 40))
    with _max_current(ctx, limit):
        refused = _refusal(lambda: validate_sweep_params(ctx.service, {}))
    ok = bool(refused) and "minimum" in refused.lower()
    return _fail_or_pass([] if ok else [f"the sweep did not refuse at {limit} mA ({refused})"],
                         f"at {limit} mA the sweep refuses: {refused}",
                         [Metric("refusal", refused or "none", ok=ok)])


PROBE_JOINT = "index_mcp"
PROBE_DEG = 10.0             # how far past where it stands the motor is asked to go
PROBE_S = 2.0                # how long each direction is held
PROBE_HZ = 20.0
PROBE_SETTLE_S = 0.2         # readings before this are the motor starting, not holding
PROBE_ABORT_MA = 300.0       # current above this for longer than PROBE_ABORT_S stops the probe
PROBE_ABORT_S = 1.0
PROBE_ABORT_WARM_C = 5.0
PROBE_LIMITS_MA = (100, 50)
FEETECH_PROTECTION_CURRENT, FEETECH_GOAL_CURRENT, FEETECH_TORQUE_LIMIT = 28, 44, 48
FEETECH_PRESENT_CURRENT = 69
FEETECH_MA_PER_UNIT = 6.5


def signed_current_raw(raw: int) -> int:
    """Feetech's present current: magnitude in bits 0-14, sign in bit 15."""
    return -(raw & 0x7FFF) if raw & 0x8000 else raw


class FeetechMotorProbe:
    """One Feetech motor driven and read directly on the console's connection."""

    def __init__(self, hand, motor: int):
        import numpy as np

        self._np = np
        self.hand, self.client, self.motor = hand, hand.motor_client, int(motor)
        self.index = list(hand.config.motor_ids).index(self.motor)

    def _word(self, address: int) -> Optional[int]:
        with self.client._bus_lock:
            raw, result, error = self.client.packet_handler.read2ByteTxRx(self.motor, address)
        return int(raw) if result == 0 else None

    def registers(self) -> dict:
        return {"protection_current_28": self._word(FEETECH_PROTECTION_CURRENT),
                "goal_current_44": self._word(FEETECH_GOAL_CURRENT),
                "torque_limit_48": self._word(FEETECH_TORQUE_LIMIT)}

    def others_off(self) -> None:
        others = [int(m) for m in self.hand.config.motor_ids if int(m) != self.motor]
        self.client.set_torque_enabled(others, False)

    def torque(self, on: bool) -> None:
        self.client.set_torque_enabled([self.motor], on)

    def set_limit(self, ma: float) -> Optional[float]:
        self.client.write_desired_current([self.motor], self._np.array([float(ma)]))
        return self.goal_current()

    def goal_current(self) -> Optional[float]:
        return self.client.read_goal_currents([self.motor]).get(self.motor)

    def position(self) -> float:
        return float(self.client.read_position_velocity_current()[0][self.index])

    def goal(self, position_rad: float) -> None:
        self.client.write_desired_pos([self.motor], self._np.array([float(position_rad)]))

    def current(self) -> tuple[Optional[float], Optional[int]]:
        raw = self._word(FEETECH_PRESENT_CURRENT)
        return (None, None) if raw is None else (signed_current_raw(raw) * FEETECH_MA_PER_UNIT, raw)

    def temperature(self) -> Optional[float]:
        values = self.client.read_temperature()
        return float(values[self.index]) if values is not None else None


def flex_sign(hand, joint: str) -> float:
    """+1 when flexing ``joint`` turns its motor towards higher angles, else -1."""
    motor = hand.config.joint_to_motor_map[joint]
    ratio = float(hand.calibration.joint_to_motor_ratios_dict.get(motor) or 1.0)
    inverted = bool(hand.config.joint_inversion_dict.get(joint, False))
    return (1.0 if ratio >= 0 else -1.0) * (-1.0 if inverted else 1.0)


PROBE_CLOCK = time


def probe_direction(probe, start: float, delta_rad: float, *, clock=None, check_stop=lambda: None) -> dict:
    """Ask the motor ``delta_rad`` past ``start`` for PROBE_S, reading it at PROBE_HZ; the
    goal goes back to ``start`` on the way out. ``abort`` says why it stopped early."""
    clock = clock or PROBE_CLOCK
    t0 = clock.monotonic()
    warm0 = probe.temperature()
    samples: list[dict] = []
    over_since, abort, next_temp = None, None, 0.5
    probe.goal(start + delta_rad)
    try:
        while True:
            now = clock.monotonic() - t0
            if now >= PROBE_S:
                break
            ma, raw = probe.current()
            samples.append({"t": round(now, 3), "ma": ma, "raw": raw, "goal_ma": probe.goal_current(),
                            "pos_deg": round(math.degrees(probe.position() - start), 2)})
            if ma is not None and abs(ma) > PROBE_ABORT_MA:
                over_since = now if over_since is None else over_since
                if now - over_since > PROBE_ABORT_S:
                    abort = f"current above {PROBE_ABORT_MA:.0f} mA for over {PROBE_ABORT_S:.0f} s"
                    break
            else:
                over_since = None
            if now >= next_temp:
                next_temp = now + 0.5
                warm = probe.temperature()
                if warm0 is not None and warm is not None and warm - warm0 > PROBE_ABORT_WARM_C:
                    abort = f"motor warmed by {warm - warm0:.0f} °C"
                    break
            check_stop()
            clock.sleep(1.0 / PROBE_HZ)
    finally:
        probe.goal(start)
    return {"samples": samples, "abort": abort}


def limit_hold_verdict(samples: list[dict], limit: float) -> dict:
    """Whether the present current stayed within ``limit`` + 15% once the motor had started."""
    held = [abs(s["ma"]) for s in samples if s.get("ma") is not None and s["t"] >= PROBE_SETTLE_S]
    peak = max(held, default=None)
    mean = sum(held) / len(held) if held else None
    return {"ok": bool(held) and peak <= limit * OVER_LIMIT_FACTOR, "peak_ma": peak, "mean_ma": mean,
            "readings": len(held)}


@register("current_limit_one_motor")
def current_limit_one_motor(ctx: CheckContext) -> CheckResult:
    """On one Feetech finger motor, with every other motor off: write a goal-current limit,
    read it back, and drive 10° each way against the hand at 100 mA and 50 mA, reading the
    present current. Moves one finger. Torque off and max current put back on every exit."""
    blocked = _ready(ctx)
    if blocked:
        return blocked
    if _mock(ctx):
        return CheckResult(status="skipped", summary="a mock motor has no current to measure")
    hand = _hand(ctx)
    if not type(hand.motor_client).__module__.endswith("feetech_client"):
        return CheckResult(status="skipped", summary="only Feetech motors are probed here")
    params = ctx.step.params or {}
    joint = str(params.get("joint", PROBE_JOINT))
    motor = abs(int(hand.config.joint_to_motor_map[joint]))
    if not hand.calibration._motor_ready(motor):
        return CheckResult(status="skipped", summary=f"{joint} is not calibrated; calibrate the hand first")
    from orca_ui.hand.service import _bus_fence

    probe = FeetechMotorProbe(hand, motor)
    sign = flex_sign(hand, joint)
    metrics: list[Metric] = []
    problems: list[str] = []
    details: dict = {"joint": joint, "motor": motor, "runs": {}}
    with _max_current(ctx, max(PROBE_LIMITS_MA)):
        try:
            with _bus_fence(hand):
                probe.others_off()
                details["registers_before"] = probe.registers()
                start = probe.position()
                probe.goal(start)
                for limit in PROBE_LIMITS_MA:
                    read_back = probe.set_limit(limit)
                    written = register_ma(limit)
                    matches = read_back is not None and abs(read_back - written) < 0.5
                    metrics.append(Metric(f"goal current read back at {limit} mA", read_back, unit="mA",
                                          ok=matches))
                    if not matches:
                        problems.append(f"the goal-current register reads {read_back} mA after writing "
                                        f"{written} mA: the write path is at fault")
                        continue
                    probe.torque(True)
                    for sense, direction in (("flex", sign), ("extend", -sign)):
                        ctx.progress(0.1, f"{joint} {sense} at {limit} mA")
                        run = probe_direction(probe, start, direction * math.radians(PROBE_DEG),
                                              check_stop=ctx.check_stop)
                        verdict = limit_hold_verdict(run["samples"], limit)
                        details["runs"][f"{sense}@{limit}"] = {**run, **verdict}
                        metrics.append(Metric(f"{sense} at {limit} mA: peak / mean present current",
                                              _peak_mean(verdict), unit="mA",
                                              ok=verdict["ok"] and not run["abort"]))
                        if run["abort"]:
                            problems.append(f"{sense} at {limit} mA stopped: {run['abort']}")
                            break
                        if not verdict["ok"]:
                            problems.append(f"{sense} at {limit} mA drew {_peak_mean(verdict)} mA "
                                            f"(limit {limit} mA)")
                    probe.torque(False)
                    if any(r.get("abort") for r in details["runs"].values()):
                        break
                details["registers_after"] = probe.registers()
        finally:
            with contextlib.suppress(Exception):
                probe.torque(False)
            _torque_off_quietly(ctx)
    return _fail_or_pass(problems, f"on {joint} (motor {motor}) the goal current read back as written and the "
                         f"present current stayed within {PROBE_LIMITS_MA} mA (+15%) both ways.", metrics,
                         details=details)


def register_ma(ma: float) -> float:
    """``ma`` as the goal-current register holds it: whole 6.5 mA units, rounded down."""
    return int(float(ma) // FEETECH_MA_PER_UNIT) * FEETECH_MA_PER_UNIT


def _peak_mean(verdict: dict) -> str:
    if verdict["peak_ma"] is None:
        return "no readings"
    return f"{verdict['peak_ma']:.0f} / {verdict['mean_ma']:.0f}"


# ----- 9. slack test ---------------------------------------------------------------------


@register("slack_skip_all")
def slack_skip_all(ctx: CheckContext) -> CheckResult:
    """A slack test that skips every joint reads as nothing tested and leaves the
    calibration block as it was. The hand's records are put back."""
    from orca_ui.hand import slack_tests

    blocked = _ready(ctx)
    if blocked:
        return blocked
    config = ctx.service.supervisor.config
    block_before = slack_tests.calibration_block(config)

    def answer(snapshot: dict) -> Optional[str]:
        options = (snapshot.get("awaiting") or {}).get("options") or []
        for wanted in ("Skip", "Finish"):
            if wanted in options:
                return wanted
        return None

    with hand_files_restored(ctx, ("setup.yaml",)):
        run_id = start_operation(ctx, "slack_test")
        snapshot = follow_operation(ctx, run_id, answer=answer, timeout_s=300.0)
        _wait_connected(ctx)
        summary = slack_tests.summary(config) or {}
        block_after = slack_tests.calibration_block(config)
    statuses = {j: r.get("status") for j, r in (summary.get("results") or {}).items()}
    nothing = bool(statuses) and all(s == "skipped" for s in statuses.values())
    metrics = [Metric("ended", snapshot.get("state"), ok=snapshot.get("state") == "done"),
               Metric("every joint skipped", f"{sum(s == 'skipped' for s in statuses.values())} of {len(statuses)}",
                      ok=nothing),
               Metric("calibration block unchanged", "yes" if block_after == block_before else "no",
                      ok=block_after == block_before)]
    problems = [m.name for m in metrics if m.ok is False]
    return _fail_or_pass(problems, "skipping every joint saves a test that tested nothing, and the calibration "
                         "block is as it was.", metrics)


# ----- 10. touch ---------------------------------------------------------------------------


@register("tactile_zero_kept")
def tactile_zero_kept(ctx: CheckContext) -> CheckResult:
    """Zero the tactile sensors, reconnect: the zero is back on the sensors. The
    calibration file (where the zero lives) is put back."""
    blocked = _no_hand(ctx)
    if blocked:
        return blocked
    session = ctx.service.session
    if getattr(session, "tactile_client", None) is None:
        return CheckResult(status="skipped", summary="this hand has no tactile sensors connected")
    if _mock(ctx):
        return CheckResult(status="skipped", summary="the mock console writes a fresh calibration on every connect, "
                           "so it keeps no zero")
    with hand_files_restored(ctx, ("calibration.yaml",)):
        ctx.service.zero_tactile()
        saved = _sensor_offsets(calibration_file(ctx))
        _reconnect(ctx)
        live = getattr(ctx.service.session.tactile_client, "taxel_offsets", None)
    ok = saved is not None and live is not None and json.dumps(live, sort_keys=True, default=str) == \
        json.dumps(saved, sort_keys=True, default=str)
    return _fail_or_pass([] if ok else ["the sensors did not get the saved zero back after reconnecting"],
                         "the zero is saved in the hand's calibration and back on the sensors after a reconnect.",
                         [Metric("zero saved", "yes" if saved else "no", ok=saved is not None),
                          Metric("zero back after reconnect", "yes" if ok else "no", ok=ok)])


# ----- 11. records per hand ---------------------------------------------------------------


@register("records_in_hand_folder")
def records_in_hand_folder(ctx: CheckContext) -> CheckResult:
    """The Setup records the console reads are the connected hand's own."""
    from orca_core.maintenance.setup_file import setup_path

    blocked = _no_hand(ctx)
    if blocked:
        return blocked
    config = ctx.service.supervisor.config
    folder = _hand_dir(ctx)
    path = Path(setup_path(config))
    ok = folder is not None and path.parent == folder
    return _fail_or_pass([] if ok else [f"the console reads Setup records from {path}, not from {folder}"],
                         f"Setup records come from {path}.", [Metric("setup records", str(path), ok=ok)])


# ----- 12. mock mode ----------------------------------------------------------------------


def _tree(root: Path) -> dict:
    if not root.is_dir():
        return {}
    out = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            stat = path.stat()
            out[str(path.relative_to(root))] = (stat.st_size, stat.st_mtime_ns)
    return out


@register("mock_leaves_store")
def mock_leaves_store(ctx: CheckContext) -> CheckResult:
    """A mock hand connecting and calibrating never touches the hands folder."""
    from orca_core import MockOrcaHand
    root = hands_root()
    before = _tree(root)
    config = ctx.service.supervisor.config
    hand = MockOrcaHand(config_path=config.config_path)
    hand.connect()
    try:
        joints = [j for j in config.joint_ids if j != "wrist"][:1]
        hand.calibrate(joints=joints)
        mock_dir = hand.hand_dir
    finally:
        with contextlib.suppress(Exception):
            hand.disconnect()
    changed = sorted(set(before) ^ set(_tree(root)) | {k for k, v in _tree(root).items() if before.get(k) != v})
    inside = mock_dir and Path(mock_dir).resolve().is_relative_to(root.resolve())
    metrics = [Metric("files changed under hands/", len(changed), ok=not changed),
               Metric("mock hand's folder", str(mock_dir), ok=not inside)]
    return _fail_or_pass([f"changed: {', '.join(changed[:5])}"] if changed else
                         (["the mock hand's folder is inside the hands folder"] if inside else []),
                         f"a mock hand calibrated in {mock_dir}; {root} is untouched.", metrics)


# ----- 13. click-through the console can answer ---------------------------------------------


def has_feedback_loop(status: dict) -> bool:
    """Whether the hand runs a joint-feedback loop (joint encoders): only then are there gains to read."""
    return bool(((status or {}).get("capabilities") or {}).get("feedback_loop"))


@register("console_regressions")
def console_regressions(ctx: CheckContext) -> CheckResult:
    """What the console's pages read still answers: status, hand info, motors,
    poses (saved and deleted again), models, boards, gains; Disconnect releases
    the hand with torque off and Reconnect brings it back."""
    from orca_ui.home import ui_home

    blocked = _ready(ctx)
    if blocked:
        return blocked
    service = ctx.service
    metrics: list[Metric] = []
    problems: list[str] = []

    def probe(name: str, fn: Callable[[], Any], judge: Callable[[Any], bool] = lambda v: v is not None) -> Any:
        try:
            value = fn()
            ok = bool(judge(value))
        except Exception as e:
            value, ok = f"{type(e).__name__}: {e}", False
        metrics.append(Metric(name, "ok" if ok else str(value)[:120], ok=ok))
        if not ok:
            problems.append(name)
        return value

    probe("status", service.status, lambda s: s.get("state") in ("connected", "degraded"))
    probe("hand info", service.hand_info, lambda i: "hand" in i)
    count = len(service.session.hand.config.motor_ids)
    probe("motor table", service.motor_snapshot, lambda s: len(s["motors"]) == count)
    probe("models", service.models)
    probe("boards", service.boards)
    if has_feedback_loop(service.status()):
        probe("gains", service.gains_state)
    else:
        metrics.append(Metric("gains", "not applicable: this hand has no joint-feedback loop", ok=None))
    name = "hwtest-pose"
    probe("pose saved", lambda: service.capture_pose(name))
    probe("pose listed", service.list_poses, lambda poses: any(p.get("name") == name for p in poses))
    probe("pose deleted", lambda: service.delete_pose(name) or True)
    library = ui_home() / "library"
    probe("library in the console's state folder", lambda: str(library), lambda _: library.is_dir() or _mock(ctx))
    probe("Disconnect", lambda: service.disconnect() or service.status(),
          lambda s: s.get("released") and not s.get("torque_enabled"))
    probe("Reconnect", lambda: _reconnect(ctx) or service.status(),
          lambda s: s.get("state") in ("connected", "degraded"))
    return _fail_or_pass(problems, "every page's reads answered; a pose saved and deleted; Disconnect released "
                         "the hand with torque off and Reconnect brought it back.", metrics)


# ----- 15. ports and the board's side -------------------------------------------------------


def _connect_only(ctx: CheckContext, folder: str, **args) -> dict:
    return ctx.sides.run("branch", "connect_only", {"detected_hardware_version": None, **args},
                         ctx.out_dir / folder)


@register("named_port_and_side_refused")
def named_port_and_side_refused(ctx: CheckContext) -> CheckResult:
    """A named motor port nobody answers on fails without finding the hand elsewhere,
    and a model of the other side is refused by the board. Neither moves the hand."""
    blocked = _ready(ctx)
    if blocked:
        return blocked
    if _mock(ctx):
        return CheckResult(status="skipped", summary="a mock hand has no ports or board to refuse")
    if ctx.sides.available("branch") is not None:
        return CheckResult(status="skipped", summary=f"the branch's orca_core cannot run: {ctx.sides.available('branch')}")
    status = ctx.service.status()
    side = status.get("side")
    model = status.get("model") or ""
    other_model = model.replace(side, "left" if side == "right" else "right") if side and side in model else None
    port = _connect_only(ctx, "port", motor_port="/dev/cu.usbmodem-hwtest-nothing", expected_motor_port=None)
    metrics = [Metric("unknown port", "refused" if not port.get("ok") else "connected",
                      ok=not port.get("ok") and not (port.get("data") or {}).get("connected"))]
    details = {"port": port.get("error")}
    if other_model:
        wrong = _connect_only(ctx, "side", model_name=other_model)
        refused = not wrong.get("ok") and side in str(wrong.get("error") or "").lower()
        metrics.append(Metric(f"{other_model} on this {side} hand", "refused" if refused else
                              (wrong.get("error") or "connected"), ok=refused))
        details["side"] = wrong.get("error")
    else:
        metrics.append(Metric("other side", f"not tried: no other-side model for {model!r}"))
    problems = [m.name for m in metrics if m.ok is False]
    return _fail_or_pass(problems, "the named port failed without a fallback and the other side's model was refused.",
                         metrics, details=details)


# ----- 16. joint ranges measured on this hand -------------------------------------------------


@register("measured_joint_ranges")
def measured_joint_ranges(ctx: CheckContext) -> CheckResult:
    """A hand-written joint_ranges.yaml is in force and said so; a bad value is
    ignored; without it the model's ranges are back. Moves one joint to both ends."""
    import yaml

    blocked = _ready(ctx)
    if blocked:
        return blocked
    params = ctx.step.params or {}
    joint = str(params.get("joint", "index_pip"))
    measured = [float(v) for v in params.get("range", [0.0, 80.0])]
    tolerance_rad = float(params.get("tolerance_deg", 12.0)) * 3.141592653589793 / 180
    metrics: list[Metric] = []
    model_rom = list(ctx.service.supervisor.config.joint_roms_dict.get(joint) or [])
    with hand_files_restored(ctx, ("joint_ranges.yaml",)) as folder:
        path = folder / "joint_ranges.yaml"
        path.write_text(yaml.safe_dump({"measured_at": time.strftime("%Y-%m-%d"), "joint_roms": {joint: measured}}))
        _reconnect(ctx)
        info = _state(ctx).get("joint_ranges") or {}
        rom = list(_hand(ctx).config.joint_roms_dict.get(joint) or [])
        metrics += [Metric("hand menu says", info.get("source"), ok=info.get("source") == "measured"),
                    Metric(f"{joint} range in force", str(rom), ok=rom == measured)]
        ends = _drive_to_ends(ctx, joint, measured)
        for label, (reached, limit) in ends.items():
            ok = reached is not None and limit is not None and abs(reached - limit) <= tolerance_rad
            metrics.append(Metric(f"motor at the {label} end vs its calibrated limit",
                                  None if reached is None else round(abs(reached - (limit or 0)) * 180 / 3.14159, 1),
                                  unit="° off", ok=ok if limit is not None else None))
        path.write_text(yaml.safe_dump({"measured_at": "2026-01-01", "joint_roms": {joint: [0, "abc"]}}))
        _reconnect(ctx)
        bad_rom = list(_hand(ctx).config.joint_roms_dict.get(joint) or [])
        metrics.append(Metric("a bad value is ignored", str(bad_rom), ok=bad_rom == model_rom))
        path.unlink()
        _reconnect(ctx)
        gone = _state(ctx).get("joint_ranges") or {}
        metrics.append(Metric("without the file", gone.get("source"), ok=gone.get("source") == "model"))
    problems = [m.name for m in metrics if m.ok is False]
    return _fail_or_pass(problems, f"{joint}'s measured range {measured} was in force and mapped onto the "
                         "calibrated motor limits; a bad value and no file both fall back to the model.", metrics)


def _drive_to_ends(ctx: CheckContext, joint: str, rom: list) -> dict:
    """Drive ``joint`` to both ends of ``rom``; {end: (motor position reached, its calibrated limit)}."""
    hand = _hand(ctx)
    motor = abs(int(hand.config.joint_to_motor_map[joint]))
    try:
        limits = list((hand.calibration.motor_limits_dict or {}).get(motor) or [])
    except Exception:
        limits = []
    out = {}
    try:
        ctx.service.enable_torque()
        for index, (label, value) in enumerate((("low", rom[0]), ("high", rom[1]))):
            ctx.service.set_targets({joint: value})
            _wait(ctx, float((ctx.step.params or {}).get("settle_s", 3.0)))
            reached = next((m["position"] for m in ctx.service.motor_snapshot()["motors"] if m["id"] == motor), None)
            reached_limit = None
            if len(limits) == 2 and None not in limits:
                reached_limit = min(limits, key=lambda lim: abs(lim - reached)) if reached is not None else None
            out[label] = (reached, reached_limit)
    finally:
        _torque_off_quietly(ctx)
    return out


# ----- 17. a damaged file ----------------------------------------------------------------


@register("damaged_calibration_set_aside")
def damaged_calibration_set_aside(ctx: CheckContext) -> CheckResult:
    """An unreadable calibration.yaml is set aside and the hand still connects;
    the real file is put back."""
    blocked = _ready(ctx)
    if blocked:
        return blocked
    if _mock(ctx):
        return CheckResult(status="skipped", summary="the mock console writes a fresh calibration on every connect, "
                           "so a damaged one never reaches it")
    before = _calibration(ctx)
    target = calibration_file(ctx)
    if target is None:
        return CheckResult(status="error", summary="the hand has no calibration file to damage")
    with hand_files_restored(ctx):
        existing = set(target.parent.glob(f"{target.name}.corrupt-*"))
        target.write_text("not: [valid\n")
        _reconnect(ctx)
        aside = sorted(set(target.parent.glob(f"{target.name}.corrupt-*")) - existing)
        connected = ctx.service.status().get("state") in ("connected", "degraded")
        during = _calibration(ctx).get("calibrated_at")
        for path in aside:
            path.unlink()
    after = _calibration(ctx)
    metrics = [Metric("connected with the damaged file", "yes" if connected else "no", ok=connected),
               Metric("file set aside", aside[0].name if aside else "no", ok=bool(aside)),
               Metric("calibration while damaged", during or "none (or the board's)"),
               Metric("calibration back afterwards", after.get("calibrated_at"),
                      ok=after.get("calibrated_at") == before.get("calibrated_at"))]
    problems = [m.name for m in metrics if m.ok is False]
    return _fail_or_pass(problems, "the damaged file was set aside, the hand connected, and the real calibration "
                         "is back.", metrics)


# ----- 18. your own config -----------------------------------------------------------------


def edited_max_current(resolved, wanted=None) -> int:
    """A max current for the edited copy that this hand's motor family accepts: above every
    calibration current it resolves, and unlike the one in force, so the copy's value shows."""
    floor = max(float(resolved.calibration_current), float(resolved.wrist_calibration_current),
                float(resolved.calibration_max_current or 0))
    current = int(resolved.max_current)
    if wanted is not None and int(wanted) > floor and int(wanted) != current:
        return int(wanted)
    if current - 10 > floor:
        return current - 10
    return max(int(floor) + 10, current + 10)


@register("standalone_config")
def standalone_config(ctx: CheckContext) -> CheckResult:
    """A standalone copy loads as its model, runs this hand with its own calibration
    and folder, and takes a value changed in it; a bare copy is refused."""
    from orca_core import load_config, write_standalone_config
    from orca_core.hand_config import HandConfigValidationError, OrcaHandConfig

    blocked = _ready(ctx)
    if blocked:
        return blocked
    config = ctx.service.supervisor.config
    packaged = config.config_path
    copy = Path(write_standalone_config(str(ctx.out_dir / "standalone" / "config.yaml"), config_path=packaged))
    same = load_config(config_path=str(copy)) == load_config(config_path=packaged)
    # A packaged v2 config leans on shared.yaml; the mock console's own model does not.
    import orca_core

    models = Path(orca_core.__file__).parent / "models" / "v2"
    name = Path(packaged).parent.name
    slim = models / name / "config.yaml" if (models / name / "config.yaml").is_file() \
        else models / "orcahand-right" / "config.yaml"
    bare = ctx.out_dir / "bare"
    bare.mkdir(exist_ok=True)
    shutil.copyfile(slim, bare / "config.yaml")
    try:
        OrcaHandConfig.from_config_path(config_path=str(bare / "config.yaml"))
        refused = None
    except HandConfigValidationError as e:
        refused = str(e)
    metrics = [Metric("standalone copy loads as the model", "yes" if same else "no", ok=same),
               Metric("bare copy refused", (refused or "loaded")[:160],
                      ok=bool(refused) and "write_standalone_config" in refused)]
    if not _mock(ctx) and ctx.sides.available("branch") is None:
        import yaml

        limit = edited_max_current(ctx.service.session.hand.config, (ctx.step.params or {}).get("max_current"))
        changed = yaml.safe_load(copy.read_text())
        changed["max_current"] = limit
        edited = ctx.out_dir / "edited" / "config.yaml"
        edited.parent.mkdir(parents=True, exist_ok=True)
        edited.write_text(yaml.safe_dump(changed, sort_keys=False))
        result = ctx.sides.run("branch", "connect_only",
                               {"config_path": str(edited), "use_hand_folder": True, "real_store": True},
                               ctx.out_dir / "connect")
        data = result.get("data") or {}
        metrics += [Metric("connected", "yes" if result.get("ok") else result.get("error"), ok=bool(result.get("ok"))),
                    Metric("same hand folder", data.get("hand_dir"), ok=data.get("hand_dir") == str(_hand_dir(ctx))),
                    Metric("same calibration", (data.get("calibration") or {}).get("calibrated_at"),
                           ok=(data.get("calibration") or {}).get("calibrated_at") == _calibration(ctx).get("calibrated_at")),
                    Metric("max current from the copy", data.get("max_current"), ok=data.get("max_current") == limit)]
    else:
        metrics.append(Metric("run on the hand", "not tried (mock, or the branch's orca_core cannot run)"))
    problems = [m.name for m in metrics if m.ok is False]
    return _fail_or_pass(problems, "the standalone copy loads as its model and runs this hand from its own folder; "
                         "a bare copy is refused with a pointer to write_standalone_config.", metrics)


# ----- 19. ORCA_HOME elsewhere ----------------------------------------------------------------

def store_snapshot(root: Path) -> dict:
    """Every file in the hands folder as its size and mtime: any write shows."""
    return _tree(root)


def snapshot_changes(before: dict, after: dict) -> list[str]:
    """Files added, removed or changed between two :func:`store_snapshot` results."""
    return sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))


@register("orca_home_elsewhere")
def orca_home_elsewhere(ctx: CheckContext) -> CheckResult:
    """With ORCA_HOME elsewhere the console moves nothing and the hand gets a folder
    there; the real store is untouched."""
    home = ctx.out_dir / "home"
    legacy = home / ".orca_ui"
    (legacy / "library").mkdir(parents=True, exist_ok=True)
    custom = ctx.out_dir / "custom-orca-home"
    code = "from orca_ui.home import prepare_ui_home, ui_home; print(prepare_ui_home()); print(ui_home())"
    env = {**os.environ, "HOME": str(home), "ORCA_HOME": str(custom), "PYTHONDONTWRITEBYTECODE": "1"}
    ran = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=60)
    lines = ran.stdout.strip().splitlines()
    unmoved = legacy.is_dir() and not legacy.is_symlink()
    details: dict = {}
    metrics = [Metric("~/.orca_ui left where it was", "yes" if unmoved else "moved", ok=unmoved),
               Metric("console state folder", lines[-1] if lines else ran.stderr[-200:],
                      ok=bool(lines) and lines[-1] == str(custom / "ui"))]
    if not _mock(ctx) and ctx.sides.available("branch") is None:
        root = hands_root()
        # Both snapshots inside the release: the console's own disconnect and reconnect stay outside.
        with ctx.sides.hand_released():
            before = store_snapshot(root)
            result = _connect_only(ctx, "connect")
            changed = snapshot_changes(before, store_snapshot(root))
        data = result.get("data") or {}
        folder = str(data.get("hand_dir") or "")
        metrics += [Metric("hand folder in the run's ORCA_HOME", folder,
                           ok=bool(result.get("ok")) and folder.startswith(str(ctx.out_dir))),
                    Metric("real hands folder untouched", "yes" if not changed else "changed: " + ", ".join(changed[:5]),
                           ok=not changed)]
        details["changed_in_real_store"] = changed
    problems = [m.name for m in metrics if m.ok is False]
    return _fail_or_pass(problems, "with ORCA_HOME elsewhere nothing was moved, and the hand was filed there.", metrics,
                         details=details)


# ----- 20. orca_core's scripts on this hand ------------------------------------------------


@register("scripts_use_hand_folder")
def scripts_use_hand_folder(ctx: CheckContext) -> CheckResult:
    """neutral.py and zero.py run on the hand's stored calibration without
    calibrating; guided_tension.py interrupted while it holds ends with orca_core
    confirming torque off; measure_travel reads the stored calibration without
    moving. Moves the hand."""
    blocked = _ready(ctx)
    if blocked:
        return blocked
    if _mock(ctx):
        return CheckResult(status="skipped", summary="the scripts run on the real hand only")
    if not _calibration(ctx).get("calibrated_at"):
        return CheckResult(status="skipped", summary="the hand has no calibration on this computer; the scripts "
                           "would calibrate it first. Calibrate, then run the step again")
    runner = ctx.sides
    if runner.available("branch") is not None:
        return CheckResult(status="skipped", summary=f"the branch's orca_core cannot run: {runner.available('branch')}")
    model = ctx.service.status().get("model") or ""
    metrics: list[Metric] = []
    outputs = {}
    with runner.hand_released():
        for index, script in enumerate(("neutral.py", "zero.py")):
            ctx.progress(0.1 + 0.2 * index, script)
            ran = runner.run_script("branch", script, [], ctx.out_dir / Path(script).stem, timeout_s=300.0,
                                    real_store=True)
            out = ran["stdout"] + ran["stderr"]
            outputs[script] = out[-2000:]
            calibrated_first = re.search(r"calibrating|starting calibration", out, re.IGNORECASE) is not None
            metrics.append(Metric(script, "ran" if ran["returncode"] == 0 else f"exit {ran['returncode']}",
                                  ok=ran["returncode"] == 0 and not calibrated_first))
        ctx.progress(0.6, "guided_tension.py, then Ctrl-C while it holds")
        # Enter past the first pose, then Ctrl-C while the range check holds (torque on). Slack
        # scoring never skips a stage, so even a fully tensioned hand reaches that hold.
        ran = runner.run_script("branch", "guided_tension.py", ["--scoring", "slack"], ctx.out_dir / "guided_tension",
                                timeout_s=120.0, real_store=True, stdin_text="1\n", interrupt_on=GUIDED_HOLDING,
                                interrupt_after_s=float((ctx.step.params or {}).get("interrupt_after_s", 3.0)))
        tension_out = ran["stdout"] + ran["stderr"]
        outputs["guided_tension.py"] = tension_out[-2000:]
    _wait_connected(ctx)
    tension, cannot_run = guided_ctrl_c_metrics(ran, tension_out)
    read, problems = reconnect_torque(torque_states(ctx.service))
    metrics += tension + [read]
    ran = runner.run_script("branch", "measure_travel.py", ["--from-calibration", "--dry-run", "--model-name", model],
                            ctx.out_dir / "measure_travel", timeout_s=120.0, real_store=True)
    outputs["measure_travel.py"] = (ran["stdout"] + ran["stderr"])[-2000:]
    metrics.append(Metric("measure_travel.py --from-calibration", "ran" if ran["returncode"] == 0 else
                          f"exit {ran['returncode']}", ok=ran["returncode"] == 0))
    problems += [m.name for m in metrics if m.ok is False and m.name not in problems]
    if cannot_run and not problems:
        return CheckResult(status="skipped", summary=f"neutral, zero and measure_travel ran on the stored "
                           f"calibration, but guided_tension.py cannot run on this hand ({cannot_run}), so "
                           "its Ctrl-C was not tried.", metrics=metrics, details={"outputs": outputs})
    return _fail_or_pass(problems, "the scripts ran on the hand's stored calibration, and Ctrl-C while guided "
                         "tensioning held ended it with orca_core confirming torque off.",
                         metrics, details={"outputs": outputs})


GUIDED_HOLDING = "motors hold this pose at"
"""What guided_tension.py prints once its range check holds the pose (torque on)."""
GUIDED_CANNOT_RUN = re.compile(r"Guided tensioning cannot run: (.+)")


def guided_ctrl_c_metrics(ran: dict, output: str) -> tuple[list[Metric], Optional[str]]:
    """Whether guided_tension.py was interrupted while holding and ended on it with torque
    confirmed off; and why it could not run at all on this hand (None when it could)."""
    refused = GUIDED_CANNOT_RUN.search(output)
    if refused and ran.get("interrupted_s") is None:
        return [Metric("guided_tension.py Ctrl-C while holding", f"not tried: {refused.group(1).strip()}",
                       ok=None)], refused.group(1).strip()
    if ran.get("interrupted_s") is None:
        why = "timed out before its range check held" if ran.get("timed_out") else \
            f"exited before the Ctrl-C (exit {ran.get('returncode')})"
        return [Metric("guided_tension.py Ctrl-C while holding", why, ok=False)], None
    after = max(0.0, float(ran.get("duration_s") or 0.0) - float(ran["interrupted_s"]))
    ended = "Guided tensioning interrupted" in output and not ran.get("timed_out")
    held = "Torque could not be switched off" in output
    return [Metric("guided_tension.py ended on the Ctrl-C", f"in {after:.1f} s" if ended else
                   ("timed out" if ran.get("timed_out") else f"exit {ran.get('returncode')} without saying so"),
                   ok=ended and after <= STOP_DEADLINE_S),
            Metric("orca_core confirmed torque off on its way out", "no: it says torque could not be switched off"
                   if held else "yes", ok=not held)], None
