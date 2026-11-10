"""Hardware tests: finding main's and the branch's checkouts, building the commands
that run each side's recorder, per-run config copies, and the recorder itself
against orca_core's mock hand. No hardware, no network: ``uv`` is replaced by a
stand-in that runs the recorder with this interpreter."""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import orca_core
from orca_ui.hardware_tests import recorder, sides
from orca_ui.hardware_tests.checks.base import StopRequested


def _checkout(path: Path, version: str = "1.2.3") -> Path:
    (path / "orca_core").mkdir(parents=True)
    (path / "orca_core" / "__init__.py").write_text("")
    (path / "pyproject.toml").write_text(f'[project]\nname = "orca_core"\nversion = "{version}"\n')
    return path


def test_checkouts_branch_is_the_console_core_and_main_follows_setting_env_then_worktree(tmp_path):
    branch_path = _checkout(tmp_path / "code" / "orca_core", "0.13.0")
    branch = sides.branch_checkout(SimpleNamespace(kind="local", location=str(branch_path), version="0.13.0"))
    assert branch.reason is None and branch.version == "0.13.0"

    released = sides.branch_checkout(SimpleNamespace(kind="released", location=None, version="0.12.0"))
    assert released.path is None and "./dev local" in released.reason

    missing = sides.main_checkout(branch, None, {})
    assert missing.path is None
    assert "worktree add" in missing.reason and "orca_core-main" in missing.reason

    default = _checkout(tmp_path / "code" / "worktrees" / "orca_core-main", "0.12.0")
    assert sides.main_checkout(branch, None, {}).path == default.resolve()
    from_env = _checkout(tmp_path / "env-main")
    assert sides.main_checkout(branch, None, {sides.MAIN_ENV: str(from_env)}).path == from_env.resolve()
    from_setting = _checkout(tmp_path / "setting-main")
    chosen = sides.main_checkout(branch, str(from_setting), {sides.MAIN_ENV: str(from_env)})
    assert chosen.path == from_setting.resolve()
    assert "same checkout" in sides.main_checkout(branch, str(branch_path), {}).reason
    assert "not an orca_core checkout" in sides.main_checkout(branch, str(tmp_path), {}).reason


def test_recorder_command_runs_in_the_checkouts_own_environment(tmp_path):
    cmd = sides.recorder_command("uv", tmp_path, "3.12", "neutral", tmp_path / "a.json",
                                 tmp_path / "out", mock=True)
    assert cmd[:9] == ["uv", "run", "--project", str(tmp_path), "--frozen", "--no-dev",
                       "--python", "3.12", "python"]
    assert cmd[9:] == [str(sides.RECORDER), "neutral", "--args-json", str(tmp_path / "a.json"),
                       "--out", str(tmp_path / "out"), "--mock"]
    env = sides.child_env({"VIRTUAL_ENV": "/x", "PYTHONPATH": "/y", "UV_PYTHON": "3.11", "HOME": "/h"})
    assert env == {"HOME": "/h", "PYTHONUNBUFFERED": "1"}


def test_config_copy_takes_the_sides_packaged_model_and_leaves_it_untouched(tmp_path):
    checkout = _checkout(tmp_path / "core")
    packaged = checkout / "orca_core" / "models" / "v2" / "orcahand-left" / "config.yaml"
    packaged.parent.mkdir(parents=True)
    packaged.write_text("hardware_version: auto\ncalibration_travel_margin: 0.1\n")
    console = tmp_path / "console" / "models" / "v2" / "orcahand-left"
    console.mkdir(parents=True)
    (console / "calibration.yaml").write_text("motor_limits: {}\n")

    assert sides.model_location(console / "config.yaml") == ("v2", "orcahand-left")
    assert sides.packaged_config(checkout, "orcahand-left", None) == packaged
    before = sides.file_digest(packaged)
    copy = sides.copy_config(packaged, tmp_path / "run" / "config",
                             calibration=console / "calibration.yaml",
                             overrides={"hardware_version": 200})
    assert sides.file_digest(packaged) == before
    import yaml
    data = yaml.safe_load(copy.read_text())
    assert data == {"hardware_version": 200, "calibration_travel_margin": 0.1}
    assert (copy.parent / "calibration.yaml").read_text() == "motor_limits: {}\n"


def test_recorder_arguments():
    opts = recorder.parse_args(["calibrate", "--args-json", "a.json", "--out", "o", "--mock"])
    assert (opts.scenario, opts.args_json, opts.out, opts.mock) == ("calibrate", "a.json", "o", True)
    with pytest.raises(SystemExit):
        recorder.parse_args(["calibrate"])
    with pytest.raises(SystemExit):
        recorder.parse_args(["no_such_scenario", "--out", "o"])


def test_recorder_refuses_a_hand_on_another_port_than_the_consoles(tmp_path):
    released = []
    hand = SimpleNamespace(
        config=SimpleNamespace(port="/dev/cu.usbmodemXXXX2"),
        stop_task=lambda timeout: released.append("stop"),
        disable_torque=lambda: released.append("torque"),
        disconnect=lambda: released.append("disconnect"),
    )
    same = recorder.Run("neutral", tmp_path, {"expected_motor_port": "/dev/cu.usbmodemXXXX2"}, mock=False)
    recorder.check_same_hand(same, hand)
    assert released == []

    other = recorder.Run("neutral", tmp_path, {"expected_motor_port": "/dev/cu.usbmodemXXXX1"}, mock=False)
    with pytest.raises(RuntimeError, match="console's hand is on"):
        recorder.check_same_hand(other, hand)
    assert released == ["stop", "torque", "disconnect"]


def test_recorder_writes_the_hardware_version_in_each_sides_encoding(monkeypatch):
    import orca_core.constants as constants

    if hasattr(constants, "normalize_hardware_version"):
        assert recorder.side_hardware_version(210) == 210
        monkeypatch.delattr(constants, "normalize_hardware_version")
    assert recorder.side_hardware_version(200) == 2
    assert recorder.side_hardware_version(210) == 21
    assert recorder.side_hardware_version(None) is None


def _packaged_copy(tmp_path: Path, model: str = "orcahand-right") -> Path:
    source = Path(orca_core.__file__).parent / "models" / "v2" / model / "config.yaml"
    return sides.copy_config(source, tmp_path / "config")


def test_recorder_calibrates_the_mock_hand_into_its_copy_and_always_writes_a_result(tmp_path):
    config = _packaged_copy(tmp_path)
    result = recorder.execute("calibrate", tmp_path / "cal",
                              {"config_path": str(config), "joints": ["index_mcp"]}, mock=True)
    assert result["ok"], result["error"]
    assert result["data"]["outcome"] == "done"
    assert (config.parent / "calibration.yaml").is_file()
    assert result["readings_count"] > 0 and (tmp_path / "cal" / "readings.jsonl").is_file()
    assert json.loads((tmp_path / "cal" / "result.json").read_text())["ok"]

    detect = recorder.execute("detect", tmp_path / "detect", {}, mock=True)
    assert detect["available"] is False and "mock" in detect["reason"]

    broken = recorder.execute("neutral", tmp_path / "broken", {"config_path": str(tmp_path / "nope.yaml")},
                              mock=True)
    assert broken["ok"] is False and "FileNotFoundError" in broken["traceback"]
    assert json.loads((tmp_path / "broken" / "result.json").read_text())["error"]


def test_recorder_stops_on_its_stop_file(tmp_path):
    config = _packaged_copy(tmp_path)
    out = tmp_path / "hold"
    out.mkdir()
    (out / recorder.STOP_FILE).touch()
    result = recorder.execute("tension_hold", out, {"config_path": str(config), "hold_s": 60},
                              mock=True)
    assert result["stopped"] and not result["ok"]
    assert not any("disconnect" in n for n in result["notes"])


def test_run_process_asks_by_stop_file_then_terminates(tmp_path):
    stop_file = tmp_path / "STOP"
    polite = [sys.executable, "-c",
              "import os, time\nwhile not os.path.exists(%r): time.sleep(0.02)\nprint('bye')" % str(stop_file)]
    stop = threading.Event()
    stop.set()
    outcome = sides.run_process(polite, cwd=tmp_path, env={}, stdout_path=tmp_path / "o.log",
                                stderr_path=tmp_path / "e.log", timeout_s=30, stop_event=stop,
                                stop_file=stop_file, stop_grace_s=5, poll_s=0.02)
    assert outcome.stopped and outcome.returncode == 0
    assert (tmp_path / "o.log").read_text().strip() == "bye"

    stubborn = [sys.executable, "-c", "import time\nwhile True: time.sleep(0.05)"]
    start = time.monotonic()
    outcome = sides.run_process(stubborn, cwd=tmp_path, env={}, stdout_path=tmp_path / "o2.log",
                                stderr_path=tmp_path / "e2.log", timeout_s=0.2,
                                stop_event=threading.Event(), stop_file=tmp_path / "STOP2",
                                stop_grace_s=0.2, term_grace_s=1.0, poll_s=0.02)
    assert outcome.timed_out and outcome.returncode != 0
    assert time.monotonic() - start < 10


class _Service:
    def __init__(self, config_path: Path, *, busy: bool = False):
        self.session = object()
        self.calls: list[str] = []
        self.operation_manager = SimpleNamespace(active=lambda: busy)
        self.supervisor = SimpleNamespace(config=SimpleNamespace(config_path=str(config_path)))

    def disconnect(self):
        self.calls.append("disconnect")
        self.session = None

    def reconnect(self):
        self.calls.append("reconnect")
        self.session = object()


def _runner(tmp_path: Path, service, *, stop_event=None) -> sides.SideRunner:
    fake_uv = tmp_path / "uv"
    fake_uv.write_text(
        f"#!{sys.executable}\n"
        "import os, sys\n"
        "args = sys.argv[1:]\n"
        "i = args.index('python', args.index('--python') + 2)\n"
        "os.execv(sys.executable, [sys.executable] + args[i + 1:])\n")
    fake_uv.chmod(0o755)
    core = Path(orca_core.__file__).resolve().parent.parent
    checkouts = {side: sides.Checkout(core, None, "x") for side in sides.SIDES}
    runner = sides.SideRunner(service, SimpleNamespace(mock=True), log=lambda line: None,
                              stop_event=stop_event or threading.Event(), checkouts=checkouts,
                              uv=str(fake_uv), environ={})
    return runner


def test_side_run_copies_the_config_releases_the_hand_and_reconnects(tmp_path):
    console = Path(orca_core.__file__).parent / "models" / "v2" / "orcahand-right" / "config.yaml"
    service = _Service(console)
    runner = _runner(tmp_path, service)
    assert runner.available("main") is None

    loaded = runner.run("branch", "load_config",
                        {"config_overrides": {"hardware_version": 200},
                         "detected_hardware_version": 210}, tmp_path / "pin")
    assert loaded["ok"], loaded.get("error")
    assert service.calls == []
    assert loaded["data"]["hardware_version"] in (2, 200)
    assert (tmp_path / "pin" / "config" / "config.yaml").is_file()
    assert (tmp_path / "pin" / "stdout.log").is_file() and (tmp_path / "pin" / "stderr.log").is_file()

    detected = runner.run("main", "detect", {}, tmp_path / "detect")
    assert detected["available"] is False
    assert service.calls == ["disconnect", "reconnect"] and service.session is not None


def test_side_run_refuses_to_release_the_hand_while_an_operation_runs(tmp_path):
    console = Path(orca_core.__file__).parent / "models" / "v2" / "orcahand-right" / "config.yaml"
    service = _Service(console, busy=True)
    runner = _runner(tmp_path, service)
    with pytest.raises(RuntimeError, match="operation is running"):
        runner.run("branch", "detect", {}, tmp_path / "detect")
    assert service.calls == []

    stopped = threading.Event()
    stopped.set()
    with pytest.raises(StopRequested):
        _runner(tmp_path, _Service(console), stop_event=stopped).run(
            "branch", "load_configs", {}, tmp_path / "stopped")
