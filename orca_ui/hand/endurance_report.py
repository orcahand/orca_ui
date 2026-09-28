"""Self-contained HTML report for one endurance test.

The page (``endurance_report_template.html``) carries all its data inline and
draws the charts client-side, so the file can be attached to Slack, mailed or
opened offline like a PDF. The console builds it from its own records
(:func:`build_and_save`: the test, its samples CSV, the calibration history,
joint usage and hand info) and keeps it at ``endurance/reports/<name>.html``
next to the samples. The same page can be built from the files the Stats page
downloads (:func:`load_folder`):

    endurance.json, endurance-<label>-samples.csv, config.yaml,
    calibration.yaml, calibration_history.jsonl, joint_usage.json

    python -m orca_ui.hand.endurance_report <folder> [out.html]

and such a folder can be merged into a hand's config directory so the console
lists, serves and rebuilds the test like one it recorded itself
(:func:`import_export`; run it while no console is using that directory):

    python -m orca_ui.hand.endurance_report import <folder> <config dir>
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
import logging
import os
import re
import shutil
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

from orca_ui.hand import calibration_log

log = logging.getLogger(__name__)

FORCE_MIN_N = 0.05  # a hold "read force" when the resultant is above this


@dataclass
class ReportSources:
    test: dict[str, Any]  # full record as ``GET /api/endurance/tests/{id}`` returns it
    csv_text: str | None = None  # samples CSV, optional
    calibration_runs: list[dict[str, Any]] = field(default_factory=list)  # oldest first
    usage: dict[str, Any] | None = None  # ``GET /api/usage/stats`` snapshot
    hand: dict[str, Any] | None = None  # ``GET /api/hand/info``
    config: dict[str, Any] | None = None  # the hand's config.yaml (folder mode only)


# --------------------------------------------------------------------------- loading


def columnar(test: dict[str, Any]) -> dict[str, Any]:
    """endurance.json's per-bucket dicts → the REST record's column lists."""
    buckets = test["buckets"]
    out: dict[str, Any] = {
        "t0": [b["t0"] for b in buckets],
        "t1": [b["t1"] for b in buckets],
        "n": [b["n"] for b in buckets],
        "cycle0": [b["c0"] for b in buckets],
        "cycle1": [b["c1"] for b in buckets],
        "angle_min": {},
        "angle_max": {},
        "current_mean": {},
        "current_max": {},
        "force_mean": {},
        "force_max": {},
    }
    for joint in test["joints"]:
        cells = [b["angle"].get(joint) for b in buckets]
        out["angle_min"][joint] = [None if c is None else c[0] for c in cells]
        out["angle_max"][joint] = [None if c is None else c[1] for c in cells]
    for motor in test["motors"]:
        cells = [b["current"].get(str(motor)) for b in buckets]
        out["current_mean"][str(motor)] = [None if c is None else round(c[0], 1) for c in cells]
        out["current_max"][str(motor)] = [None if c is None else round(c[1], 1) for c in cells]
    for finger in test["fingers"]:
        cells = [b["force"].get(finger) for b in buckets]
        out["force_mean"][finger] = [None if c is None else round(c[0], 2) for c in cells]
        out["force_max"][finger] = [None if c is None else round(c[1], 2) for c in cells]
    return out


def load_folder(folder: str | Path, test_id: str | None = None) -> ReportSources:
    """The six files the console's Stats page downloads, as one folder."""
    import yaml

    folder = Path(folder)
    endurance = json.loads((folder / "endurance.json").read_text())
    tests = endurance["tests"]
    test = next((t for t in tests if t["id"] == test_id), None) if test_id else tests[-1]
    if test is None:
        raise FileNotFoundError(f"no test {test_id!r} in {folder / 'endurance.json'}")
    record = dict(test)
    record["buckets"] = columnar(test)
    record["active"] = endurance.get("active_id") == test["id"]

    csv_text = None
    for path in sorted(folder.glob("endurance-*-samples.csv")):
        csv_text = path.read_text()
        break

    runs: list[dict[str, Any]] = []
    history = folder / "calibration_history.jsonl"
    if history.exists():
        for line in history.read_text().splitlines():
            if line.strip():
                runs.append(json.loads(line))

    usage = None
    usage_path = folder / "joint_usage.json"
    if usage_path.exists():
        usage = json.loads(usage_path.read_text())

    config = None
    config_path = folder / "config.yaml"
    if config_path.exists():
        config = yaml.safe_load(config_path.read_text()) or {}

    return ReportSources(record, csv_text, runs, usage, None, config)


def sources_from_console(
    recorder: Any,
    test_id: str,
    *,
    calibration_path: str | None,
    usage: dict[str, Any] | None,
    hand: dict[str, Any] | None,
) -> ReportSources:
    """Everything the report can use, from the running console's own records."""
    recorder.save()  # flush the rows still buffered in memory
    test = recorder.test(test_id)
    if test is None:
        raise KeyError(test_id)
    csv_text = None
    csv_path = recorder.samples_path(test_id)
    if csv_path:
        try:
            csv_text = Path(csv_path).read_text(encoding="utf-8")
        except OSError as exc:
            log.warning("samples CSV for %s unreadable: %s", test_id, exc)
    runs: list[dict[str, Any]] = []
    if calibration_path:
        try:
            runs = list(reversed(calibration_log.read_runs(calibration_path)))  # oldest first
        except Exception as exc:  # noqa: BLE001 — the report works without it
            log.warning("calibration history unavailable: %s", exc)
    return ReportSources(test, csv_text, runs, usage, hand, None)


def build_and_save(
    recorder: Any,
    test_id: str,
    *,
    calibration_path: str | None,
    usage: dict[str, Any] | None = None,
    hand: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the report for ``test_id``, write it under the recorder's reports
    directory and record it on the test. Returns the ``report`` info dict."""
    src = sources_from_console(
        recorder, test_id, calibration_path=calibration_path, usage=usage, hand=hand
    )
    html = build_html(src)
    name = report_filename(src.test)
    path = Path(recorder.reports_dir()) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(html, encoding="utf-8")
    tmp.replace(path)
    return recorder.set_report(test_id, name, path.stat().st_size)


# --------------------------------------------------------------------------- data


def _elapsed_s(test: dict[str, Any]) -> float:
    if test.get("elapsed_s") is not None:
        return float(test["elapsed_s"])
    try:
        started = dt.datetime.fromisoformat(test["started_at"])
        ended = dt.datetime.fromisoformat(test["ended_at"] or test["started_at"])
        return (ended - started).total_seconds()
    except (TypeError, ValueError):
        return 0.0


def _pose_from_csv(
    csv_text: str, joints: list[str], fingers: list[str], bucket_s: float, n_buckets: int
) -> tuple[dict[str, Any], dict[str, float]]:
    """Per bucket: median angle at the higher and the lower hold of each cycle,
    plus the last hold time at which each fingertip read force."""
    acc: dict[tuple[int, int], dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    last_force: dict[str, float] = {}
    reader = csv.reader(io.StringIO(csv_text))
    header = next(reader, None) or []
    angle_cols = [
        (i, h.split(":", 1)[1]) for i, h in enumerate(header) if h.startswith("angle_deg:")
    ]
    force_cols = [(i, h.split(":", 1)[1]) for i, h in enumerate(header) if h.startswith("force_n:")]
    leg_col = header.index("leg") if "leg" in header else None
    for row in reader:
        if not row or leg_col is None or len(row) <= leg_col:
            continue
        try:
            t = float(row[0])
        except ValueError:
            continue
        for i, finger in force_cols:
            if i < len(row) and row[i]:
                try:
                    if float(row[i]) > FORCE_MIN_N:
                        last_force[finger] = t
                except ValueError:
                    pass
        if not row[leg_col]:
            continue
        leg = int(row[leg_col])
        if leg > 1:
            continue  # leg 2 returns to the leg-0 pose
        cell = acc[(int(t // bucket_s), leg)]
        for i, joint in angle_cols:
            if i < len(row) and row[i]:
                try:
                    cell[joint].append(float(row[i]))
                except ValueError:
                    pass
    medians: dict[int, dict[str, list[float | None]]] = {
        leg: {j: [None] * n_buckets for j in joints} for leg in (0, 1)
    }
    for (b, leg), cell in acc.items():
        if 0 <= b < n_buckets:
            for joint, values in cell.items():
                if joint in medians[leg]:
                    medians[leg][joint][b] = round(statistics.median(values), 2)
    # A recording decides which waypoint is leg 0, so "leg" flips between
    # recordings; the higher and the lower hold are what repeatability needs.
    upper = {j: [None] * n_buckets for j in joints}
    lower = {j: [None] * n_buckets for j in joints}
    for j in joints:
        for k in range(n_buckets):
            vals = [v for v in (medians[0][j][k], medians[1][j][k]) if v is not None]
            if vals:
                upper[j][k], lower[j][k] = max(vals), min(vals)
    return {"upper": upper, "lower": lower}, last_force


def _pick_session(usage: dict[str, Any] | None, test: dict[str, Any]) -> dict[str, Any] | None:
    sessions = (usage or {}).get("sessions") or []
    if not sessions:
        return None
    started, ended = test.get("started_at") or "", test.get("ended_at") or "￿"
    chosen = None
    for s in sessions:
        s_start, s_end = s.get("started_at") or "", s.get("ended_at")
        if s_start <= started and (s_end is None or s_end >= ended):
            chosen = s
    return chosen or sessions[-1]


def report_data(src: ReportSources) -> dict[str, Any]:
    """Everything the template needs, JSON-serialisable."""
    test = src.test
    joints: list[str] = list(test["joints"])
    motors = [int(m) for m in test["motors"]]
    motor_joint = {str(k): v for k, v in (test.get("motor_joint") or {}).items()}
    fingers: list[str] = list(test.get("fingers") or [])
    cols = test["buckets"]
    n_buckets = len(cols["t0"])
    bucket_s = float(test.get("bucket_s") or (cols["t1"][0] - cols["t0"][0] if n_buckets else 1))

    buckets = {
        "t0": cols["t0"],
        "t1": cols["t1"],
        "n": cols["n"],
        "c0": cols.get("cycle0") or [0] * n_buckets,
        "c1": cols.get("cycle1") or [0] * n_buckets,
        "angle_min": {
            j: (cols.get("angle_min") or {}).get(j) or [None] * n_buckets for j in joints
        },
        "angle_max": {
            j: (cols.get("angle_max") or {}).get(j) or [None] * n_buckets for j in joints
        },
        "cur_mean": {
            str(m): (cols.get("current_mean") or {}).get(str(m)) or [None] * n_buckets
            for m in motors
        },
        "cur_peak": {
            str(m): (cols.get("current_max") or {}).get(str(m)) or [None] * n_buckets
            for m in motors
        },
        "force_mean": {
            f: (cols.get("force_mean") or {}).get(f) or [None] * n_buckets for f in fingers
        },
        "force_max": {
            f: (cols.get("force_max") or {}).get(f) or [None] * n_buckets for f in fingers
        },
    }

    # hand geometry: config.yaml (folder) or /api/hand/info (REST)
    roms: dict[str, list[float]] = {}
    side = None
    max_current = None
    baseline: dict[str, float] = {}
    baseline_source = "first checkpoint"
    if src.config:
        roms = {j: [float(v) for v in r] for j, r in (src.config.get("joint_roms") or {}).items()}
        side = src.config.get("type")
        max_current = src.config.get("max_current")
        baseline = {j: float(v) for j, v in (src.config.get("joint_motor_travel") or {}).items()}
        if baseline:
            baseline_source = "config.yaml"
    elif src.hand:
        for j in src.hand.get("joints") or []:
            if j.get("rom"):
                roms[j["id"]] = [float(v) for v in j["rom"]]
        side = src.hand.get("side")
    checkpoints = [
        {
            "t": c["t"],
            "cycle": c.get("cycle"),
            "started_at": c.get("started_at"),
            "completed": c.get("completed"),
            "travel": c.get("travel_deg") or {},
            "problems": c.get("problems") or [],
        }
        for c in test.get("checkpoints") or []
    ]
    if not baseline and checkpoints:
        baseline = {j: float(v) for j, v in checkpoints[0]["travel"].items() if v}

    pose = None
    last_force: dict[str, float] = {}
    if src.csv_text and n_buckets:
        pose, last_force = _pose_from_csv(src.csv_text, joints, fingers, bucket_s, n_buckets)
    # 2 = read force, 1 = all zero, 0 = no reading (finger absent from the frame)
    read_state = {
        f: [
            (0 if n > 0 else None) if m is None else (2 if m > FORCE_MIN_N else 1)
            for m, n in zip(buckets["force_max"][f], buckets["n"], strict=True)
        ]
        for f in fingers
    }
    last_force_t: dict[str, float | None] = {}
    for f in fingers:
        if f in last_force:
            last_force_t[f] = last_force[f]
        else:
            ks = [k for k, st in enumerate(read_state[f]) if st == 2]
            last_force_t[f] = buckets["t1"][ks[-1]] if ks else None

    events = list(test.get("events") or [])
    notable = [e for e in events if e.get("kind") != "tactile"]
    last_state: dict[str, dict[str, Any]] = {}
    for e in events:
        if e.get("severity") in ("bad", "ok"):
            last_state[str(e.get("subject"))] = e
    open_bad = [e for e in last_state.values() if e.get("severity") == "bad"]

    runs = [
        {
            "kind": r.get("kind"),
            "t": r.get("t"),
            "t1": r.get("ended_t"),
            "cycles": r.get("cycles", 0),
            "name": (r.get("params") or {}).get("name"),
            "speed": (r.get("params") or {}).get("speed"),
            "state": r.get("state"),
        }
        for r in test.get("runs") or []
    ]

    started_at, ended_at = test.get("started_at"), test.get("ended_at")
    history = [
        {
            "started_at": h.get("started_at"),
            "finished_at": h.get("finished_at"),
            "completed": h.get("completed"),
            "force_wrist": h.get("force_wrist"),
            "joints": h.get("joints"),
            "problems": [
                {
                    k: p.get(k)
                    for k in ("kind", "joint", "severity", "headline", "travel_deg", "expected_deg")
                }
                for p in h.get("problems") or []
            ],
            "in_test": bool(
                started_at
                and h.get("started_at")
                and started_at <= h["started_at"] <= (ended_at or "￿")
            ),
        }
        for h in src.calibration_runs
    ]

    session = _pick_session(src.usage, test)
    usage_rows = (
        {j: dict(d) for j, d in (session or {}).get("joints", {}).items()} if session else None
    )

    return {
        "meta": {
            "label": test.get("label") or "unnamed test",
            "id": test.get("id"),
            "hand": side,
            "max_current": max_current,
            "started_at": started_at,
            "ended_at": ended_at,
            "active": bool(test.get("active")),
            "elapsed_s": _elapsed_s(test),
            "cycles": int(test.get("cycles_total") or 0),
            "samples": int(test.get("samples") or 0),
            "bucket_s": bucket_s,
            "runs": len(runs),
            "checkpoints": len(checkpoints),
            "events_kept": len(events),
            "events_dropped": int(test.get("events_dropped") or 0),
            "events_bad": sum(1 for e in events if e.get("severity") == "bad"),
            "last_event_t": max((e.get("t") or 0 for e in events), default=0),
            "baseline_source": baseline_source,
            "has_csv": src.csv_text is not None,
            "usage_session": (
                {"label": session.get("label"), "started_at": session.get("started_at")}
                if session
                else None
            ),
            "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        },
        "joints": joints,
        "motors": motors,
        "motor_joint": motor_joint,
        "fingers": fingers,
        "roms": roms,
        "baseline_travel": baseline,
        "buckets": buckets,
        "pose": pose,
        "read_state": read_state,
        "last_force_t": last_force_t,
        "force_min_n": FORCE_MIN_N,
        "runs": runs,
        "events": notable,
        "open_bad": open_bad,
        "checkpoints": checkpoints,
        "history": history,
        "usage": usage_rows,
    }


# --------------------------------------------------------------------------- html


def _template() -> str:
    return (
        resources.files("orca_ui.hand")
        .joinpath("endurance_report_template.html")
        .read_text(encoding="utf-8")
    )


def build_html(src: ReportSources) -> str:
    data = report_data(src)
    payload = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    return _template().replace("/*__DATA__*/", payload, 1)


def report_filename(test: dict[str, Any]) -> str:
    label = re.sub(
        r"[^A-Za-z0-9_-]+", "-", str(test.get("label") or test.get("id") or "test")
    ).strip("-")
    stamp = ""
    try:
        stamp = dt.datetime.fromisoformat(test["started_at"]).strftime("%Y%m%d")
    except (KeyError, TypeError, ValueError):
        pass
    return f"endurance-{label}{'-' + stamp if stamp else ''}.html"



# --------------------------------------------------------------------------- cli


def import_export(folder: str | Path, config_dir: str | Path) -> dict[str, Any]:
    """Merge the tests of an exported folder into ``config_dir`` (the hand's
    config directory: ``endurance.json``, ``endurance/<id>.csv``,
    ``calibration_history.jsonl``, ``joint_usage.json``) and build their
    reports, so the console serves them and Slack can post them. Tests the
    directory already knows are left alone. Not safe while a console is
    running on that directory: it would overwrite ``endurance.json`` on its
    next save."""
    from orca_ui.hand import endurance as rec

    folder, config_dir = Path(folder), Path(config_dir)
    exported = json.loads((folder / "endurance.json").read_text())
    target_path = config_dir / rec.ENDURANCE_BASENAME
    if target_path.exists():
        target = json.loads(target_path.read_text())
    else:
        target = {"schema": rec.SCHEMA, "created_at": exported.get("created_at"),
                  "updated_at": None, "active_id": None, "tests": [], "test_seq": 0}
    known = {t["id"] for t in target["tests"]}
    samples_dir = config_dir / rec.SAMPLES_DIRNAME
    reports_dir = samples_dir / rec.REPORTS_DIRNAME
    reports_dir.mkdir(parents=True, exist_ok=True)
    csvs = sorted(folder.glob("endurance-*-samples.csv"))

    # hand-level files: calibration runs the target does not have yet, usage if none
    history = folder / calibration_log.HISTORY_BASENAME
    if history.exists():
        target_history = config_dir / calibration_log.HISTORY_BASENAME
        have = set()
        if target_history.exists():
            for line in target_history.read_text().splitlines():
                if line.strip():
                    have.add(json.loads(line).get("started_at"))
        new_lines = [line for line in history.read_text().splitlines()
                     if line.strip() and json.loads(line).get("started_at") not in have]
        if new_lines:
            with open(target_history, "a", encoding="utf-8") as f:
                f.write("".join(line + "\n" for line in new_lines))
    usage = folder / "joint_usage.json"
    if usage.exists() and not (config_dir / "joint_usage.json").exists():
        shutil.copyfile(usage, config_dir / "joint_usage.json")

    added: list[str] = []
    reports: list[str] = []
    for test in exported.get("tests", []):
        if test["id"] in known or test["id"] == exported.get("active_id"):
            continue  # already there, or still running on the exporting console
        test = dict(test)
        test["report"] = None
        stem = report_filename(test)[len("endurance-"):].rsplit("-", 1)[0]
        matching = [c for c in csvs if c.name == f"endurance-{stem}-samples.csv"]
        if not matching and len(csvs) == 1 and len(exported.get("tests", [])) == 1:
            matching = csvs
        if matching:
            shutil.copyfile(matching[0], samples_dir / f"{test['id']}.csv")
        src = load_folder(folder, test["id"])
        name = report_filename(test)
        out = reports_dir / name
        tmp = out.with_suffix(".tmp")
        tmp.write_text(build_html(src), encoding="utf-8")
        os.replace(tmp, out)
        test["report"] = {"file": name, "built_at": rec._now_iso(),
                          "bytes": out.stat().st_size}
        target["tests"].append(test)
        added.append(test["id"])
        reports.append(str(out))

    target["tests"].sort(key=lambda t: t.get("started_at") or "")
    target["test_seq"] = max(int(target.get("test_seq") or 0),
                             int(exported.get("test_seq") or 0), len(target["tests"]))
    target["updated_at"] = rec._now_iso()
    tmp_path = target_path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(target, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp_path, target_path)
    return {"added": added, "reports": reports, "tests": len(target["tests"])}


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return 2
    if args[0] == "import":
        if len(args) != 3:
            print(__doc__)
            return 2
        result = import_export(args[1], args[2])
        if not result["added"]:
            print(f"nothing to import: {args[2]} already has every test in {args[1]}")
        for path in result["reports"]:
            print(f"imported, report at {path}")
        print(f"{args[2]}: {result['tests']} test(s) recorded")
        return 0
    folder = Path(args[0])
    src = load_folder(folder)
    out = Path(args[1]) if len(args) > 1 else folder / report_filename(src.test)
    out.write_text(build_html(src), encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
