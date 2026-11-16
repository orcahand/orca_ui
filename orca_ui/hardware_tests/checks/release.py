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


def _torque_metrics(states: dict) -> tuple[list[Metric], list[str]]:
    on = sorted(m for m, v in states.items() if v)
    silent = sorted(m for m, v in states.items() if v is None)
    metrics = [Metric("motors read torque off", sum(1 for v in states.values() if v is False),
                      unit=f"of {len(states)}", ok=not on and not silent)]
    problems = []
    if on:
        problems.append(f"torque still on for motor(s) {', '.join(map(str, on))}")
    if silent:
        problems.append(f"no torque read-back from motor(s) {', '.join(map(str, silent))}")
    return metrics, problems


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
    """After a hands-on stop: every motor reads torque off right now."""
    blocked = _no_hand(ctx)
    if blocked:
        return blocked
    with contextlib.suppress(Exception):
        _wait_connected(ctx)
    states = torque_states(ctx.service)
    metrics, problems = _torque_metrics(states)
    return _fail_or_pass(problems, f"all {len(states)} motors read torque off.", metrics,
                         details={"torque": {str(k): v for k, v in states.items()}})


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


def firmware_repo(ctx: CheckContext) -> Optional[Path]:
    """The orca_firmware checkout calibrate.py needs to write the board."""
    configured = (ctx.step.params or {}).get("firmware_repo") or os.environ.get("ORCA_FIRMWARE_REPO")
    candidates = [Path(configured).expanduser()] if configured else []
    checkout = getattr(ctx.sides, "checkout", lambda side: None)("branch")
    if checkout is not None:
        candidates += [checkout.parent / "orca_firmware", checkout.parent.parent / "orca_firmware"]
    candidates.append(Path.home() / "code" / "orca_firmware")
    return next((c.resolve() for c in candidates if (c / ".git").exists() or (c / "README.md").is_file()), None)


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
        return CheckResult(status="skipped", summary="no orca_firmware checkout found; set ORCA_FIRMWARE_REPO "
                           "(or keep it beside orca_core) and run the step again")
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
        wrote = ran["returncode"] == 0 and re.search(r"board", output, re.IGNORECASE) is not None
        metrics.append(Metric("calibrate.py wrote the board", "yes" if wrote else f"exit {ran['returncode']}", ok=wrote))
        if not wrote:
            return CheckResult(status="fail", summary="calibrate.py did not finish writing the board.",
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
    """Start the step's routine, let it hold, Stop or E-STOP it, and read torque back
    from every motor. Moves the hand. The hand's records are put back."""
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
    metrics = [Metric("stopped within", round(seconds, 2), unit="s", ok=seconds <= STOP_DEADLINE_S),
               Metric("ended as", f"{ended.get('state')} ({ended.get('detail') or ended.get('error') or ''})"),
               Metric("motors flagged as maybe holding", ", ".join(map(str, (failed or {}).get("motors") or [])) or "none",
                      ok=not failed)]
    torque, problems = _torque_metrics(states)
    metrics += torque
    if kind == "calibrate":
        kept = after.get("calibrated_at") == before.get("calibrated_at") and \
            (after.get("previous") or {}).get("calibrated_at") == (before.get("previous") or {}).get("calibrated_at")
        metrics.append(Metric("stopped run kept the calibration and its previous", "yes" if kept else "no", ok=kept))
        if not kept:
            problems.append("a stopped calibration changed the calibration in force or its previous")
    if seconds > STOP_DEADLINE_S:
        problems.append(f"the routine took {seconds:.1f} s to end")
    if failed:
        problems.append(f"orca_core could not confirm torque off on motors {failed.get('motors')}")
    how = "E-STOP" if estop else "Stop"
    return _fail_or_pass(problems, f"{how} ended the {kind.replace('_', ' ')} in {seconds:.1f} s and every motor "
                         "reads torque off.", metrics, details={"torque": {str(k): v for k, v in states.items()},
                                                                "snapshot": ended})


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
    xs, peak = [], []
    start_temps: dict = {}
    try:
        ctx.service.enable_torque()
        ctx.service.set_targets(_mid_pose(ctx.service.session.hand.config))
        _wait(ctx, 2.0)
        t0 = time.monotonic()
        while True:
            temps = {m["id"]: m.get("temp_c") for m in ctx.service.motor_snapshot()["motors"]}
            temps = {k: float(v) for k, v in temps.items() if v is not None}
            if not start_temps:
                start_temps = temps
            rise = max((temps[k] - start_temps.get(k, temps[k]) for k in temps), default=0.0)
            xs.append(round(time.monotonic() - t0, 1))
            peak.append(rise)
            ctx.progress(min(0.99, (time.monotonic() - t0) / hold_s), f"{rise:+.1f} °C")
            if time.monotonic() - t0 >= hold_s:
                break
            _wait(ctx, min(10.0, hold_s))
    finally:
        _torque_off_quietly(ctx)
    if not start_temps:
        return CheckResult(status="skipped", summary="the motors report no temperature")
    worst = max(peak)
    metrics = [Metric("largest rise", round(worst, 1), unit="°C", ok=worst <= max_rise),
               Metric("held for", round(xs[-1], 0), unit="s"), Metric("allowed rise", max_rise, unit="°C")]
    series = [Series(name="largest temperature rise", x=xs, y=peak, y_label="°C")]
    return _fail_or_pass([f"a motor warmed by {worst:.1f} °C"] if worst > max_rise else [],
                         f"holding for {xs[-1]:.0f} s warmed no motor by more than {worst:.1f} °C.", metrics,
                         series=series)


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
    tolerance = float(params.get("tolerance_ma", 15.0))
    from orca_ui.hand import sweeps

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
    results = (data or {}).get("results") or []
    peaks = [float(r.get("peak_ma") or 0) for r in results]
    worst = max(peaks, default=None)
    metrics = [Metric("limit set", limit, unit="mA"),
               Metric("sweep's highest drive current", worst if not _mock(ctx) else "not swept (mock)", unit="mA",
                      ok=None if _mock(ctx) else worst is not None and worst <= limit + tolerance),
               Metric("slack test's highest offered current", max(offered, default=None), unit="mA",
                      ok=not offered or max(offered) <= limit + 0.5),
               Metric("slack test's default", default_ma, unit="mA",
                      ok=default_ma is None or float(default_ma) <= limit + 0.5)]
    problems = [m.name for m in metrics if m.ok is False]
    if not results and not _mock(ctx):
        problems.append(f"the sweep saved no readings ({snapshot.get('error') or snapshot.get('detail')})")
    return _fail_or_pass(problems, f"with max current at {limit} mA the sweep drew at most {worst} mA and the "
                         "slack test offers nothing higher.", metrics)


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
    probe("gains", service.gains_state)
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

        limit = int((ctx.step.params or {}).get("max_current", 200))
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
    metrics = [Metric("~/.orca_ui left where it was", "yes" if unmoved else "moved", ok=unmoved),
               Metric("console state folder", lines[-1] if lines else ran.stderr[-200:],
                      ok=bool(lines) and lines[-1] == str(custom / "ui"))]
    if not _mock(ctx) and ctx.sides.available("branch") is None:
        root = hands_root()
        before = _tree(root)
        result = _connect_only(ctx, "connect")
        data = result.get("data") or {}
        folder = str(data.get("hand_dir") or "")
        metrics += [Metric("hand folder in the run's ORCA_HOME", folder,
                           ok=bool(result.get("ok")) and folder.startswith(str(ctx.out_dir))),
                    Metric("real hands folder untouched", "yes" if _tree(root) == before else "changed",
                           ok=_tree(root) == before)]
    problems = [m.name for m in metrics if m.ok is False]
    return _fail_or_pass(problems, "with ORCA_HOME elsewhere nothing was moved, and the hand was filed there.", metrics)


# ----- 20. orca_core's scripts on this hand ------------------------------------------------


@register("scripts_use_hand_folder")
def scripts_use_hand_folder(ctx: CheckContext) -> CheckResult:
    """neutral.py and zero.py run on the hand's stored calibration without
    calibrating; guided_tension.py interrupted leaves torque off; measure_travel
    reads the stored calibration without moving. Moves the hand."""
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
        ctx.progress(0.6, "guided_tension.py, then Ctrl-C")
        ran = runner.run_script("branch", "guided_tension.py", [], ctx.out_dir / "guided_tension", timeout_s=120.0,
                                real_store=True, interrupt_after_s=float((ctx.step.params or {}).get("interrupt_after_s", 20.0)))
        outputs["guided_tension.py"] = (ran["stdout"] + ran["stderr"])[-2000:]
    _wait_connected(ctx)
    torque, problems = _torque_metrics(torque_states(ctx.service))
    metrics += [Metric("guided_tension.py ended", "yes" if not ran["timed_out"] else "timed out", ok=not ran["timed_out"])]
    metrics += torque
    ran = runner.run_script("branch", "measure_travel.py", ["--from-calibration", "--dry-run", "--model-name", model],
                            ctx.out_dir / "measure_travel", timeout_s=120.0, real_store=True)
    outputs["measure_travel.py"] = (ran["stdout"] + ran["stderr"])[-2000:]
    metrics.append(Metric("measure_travel.py --from-calibration", "ran" if ran["returncode"] == 0 else
                          f"exit {ran['returncode']}", ok=ran["returncode"] == 0))
    problems += [m.name for m in metrics if m.ok is False and m.name not in problems]
    return _fail_or_pass(problems, "the scripts ran on the hand's stored calibration, and Ctrl-C left torque off.",
                         metrics, details={"outputs": outputs})
