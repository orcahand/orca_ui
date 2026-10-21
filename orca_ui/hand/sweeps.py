"""Named tension sweeps (the ``tension_sweeps`` section of setup.yaml).

Each run of the tension sweep (the current every motor draws walking its joint
limit to limit and back) is saved under a name such as ``GT_sweep_00`` beside
the hand's calibration. One saved sweep can be marked the reference: the load
curve of a hand that is tensioned right. Later sweeps are compared against it
joint for joint, and the comparison says which tendons are tighter or looser
than the reference and where a dead band after the reversal shows slack.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from orca_core.maintenance.setup_file import read_section, write_section

from orca_ui.hand import reference as shipped_reference

SECTION = "tension_sweeps"
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,39}$")
DEFAULT_PREFIX = "GT_sweep_"
# Scoring is by curves along the travel, not by one number: from the out-and-
# back pass the current at each position splits into the static load
# (I_flex + I_extend) / 2, the preload the tendons and skin put on the motor,
# which the ratchet changes, and the friction (I_flex - I_extend) / 2, the drag
# of the routing, which tension raises. Both are compared with the reference
# sweep bin by bin; a stretch that departs by more than TOL_MA (or TOL_SHARE
# of the reference level, whichever is larger) is flagged.
BINS = 20
TOL_MA = 8.0
TOL_SHARE = 0.15
# A departure shorter than this many bins (10 % of the travel) is noise, not a stretch.
MIN_STRETCH_BINS = 2
# The joint's status comes from its mean friction as a share of the reference's:
# 90-110 % ok, below 90 % under (yellow, no click: the hand can explain it),
# below LOW low (red: the clicks start there), above 110 % over (grey,
# tighter, left alone). A reference under FLOOR_MA of friction has no usable
# share: then within TOL_MA is ok, and below it is under, never a click.
LOW = shipped_reference.CLICK_BELOW_SHARE
UNDER = 0.9
OVER = 1.1
FLOOR_MA = 15.0
SENSES = ("flex", "extend")
RANK = {"none": 0, "over": 1, "ok": 2, "under": 3, "slack": 4, "low": 5}
SLACK_DEG = 8.0


def _load(config) -> dict:
    data = read_section(config, SECTION, legacy="tension_sweeps.yaml") or {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("sweeps", {})
    data.setdefault("reference", None)
    return data


def next_name(config, prefix: str = DEFAULT_PREFIX) -> str:
    taken = [
        int(m.group(1))
        for n in _load(config)["sweeps"]
        if (m := re.fullmatch(re.escape(prefix) + r"(\d+)", n))
    ]
    return f"{prefix}{(max(taken) + 1 if taken else 0):02d}"


def dataset_name(config) -> str:
    """``sweep_20261021_095301``, with a letter suffix on a same-second collision."""
    base = f"sweep_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    taken = _load(config)["sweeps"]
    name = base
    for suffix in "bcdefgh":
        if name not in taken:
            return name
        name = f"{base}{suffix}"
    return name


def save(
    config,
    name: str | None,
    report: dict,
    *,
    hand_key: str | None = None,
    note: str | None = None,
    motor_type: str | None = None,
) -> str:
    data = _load(config)
    name = name or dataset_name(config)
    if not NAME_RE.match(name):
        raise ValueError("sweep names are 1-40 characters: letters, digits, _ . -")
    if name in data["sweeps"]:
        raise KeyError(f"sweep {name!r} already exists; sweep datasets are never overwritten")
    data["sweeps"][name] = {
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "hand_key": hand_key,
        "motor_type": motor_type,
        "note": note,
        **report,
    }
    write_section(config, SECTION, data)
    return name


def set_reference(config, name: str | None) -> None:
    data = _load(config)
    if name is not None and name not in data["sweeps"]:
        raise KeyError(f"no sweep dataset named {name!r}")
    data["reference"] = name
    write_section(config, SECTION, data)


def reference(config, family: str | None) -> tuple[str, dict] | None:
    """(name, dataset) the hand's sweeps are scored against: the saved sweep
    marked as reference, else the shipped one for the motor ``family`` (a
    dataset that carries ``curves`` instead of ``results``)."""
    data = _load(config)
    name = data.get("reference")
    if name and name in data["sweeps"]:
        return name, data["sweeps"][name]
    shipped = shipped_reference.sweep(config, family)
    return (shipped["name"], shipped) if shipped else None


def for_hand(config, hand_key: str | None) -> list[tuple[str, dict]]:
    """(name, dataset) of every sweep on ``hand_key``, newest first."""
    sweeps = _load(config)["sweeps"]
    mine = [(n, s) for n, s in sweeps.items() if hand_key is None or s.get("hand_key") == hand_key]
    return sorted(mine, key=lambda kv: kv[1].get("recorded_at", ""), reverse=True)


def levels(results: list[dict]) -> dict[str, dict[str, dict]]:
    """Per joint and sense, the mean over the passes of each sweep metric."""
    acc: dict[str, dict[str, dict[str, list]]] = {}
    for r in results:
        if r.get("skipped") or r.get("mean_ma") is None:
            continue
        cell = acc.setdefault(r["joint"], {}).setdefault(r["sense"], {"mean_ma": [], "end_ma": [], "deadband_deg": [], "short_deg": []})
        for k in cell:
            if r.get(k) is not None:
                cell[k].append(float(r[k]))
    return {
        j: {
            s: {k: (round(sum(v) / len(v), 2) if v else None) for k, v in cell.items()} | {"n": len(cell["mean_ma"])}
            for s, cell in senses.items()
        }
        for j, senses in acc.items()
    }


def curves(results: list[dict]) -> dict[str, dict]:
    """Per joint, the mean signed current in BINS bins along the travel for
    each sense, in flex-positive units, averaged over the passes::

        {joint: {"flex": [mA|None]*BINS, "extend": [...], "travel_deg": float,
                 "deadband_deg": {"flex": x, "extend": y}}}
    """
    acc: dict[str, dict] = {}
    for r in results:
        if r.get("skipped") or not isinstance(r.get("samples"), list) or not r["samples"]:
            continue
        travel = float(r.get("travel_deg") or 0) or 1.0
        flex_dir = r["direction"] if r["sense"] == "flex" else -r["direction"]
        cell = acc.setdefault(r["joint"], {"flex": [[] for _ in range(BINS)], "extend": [[] for _ in range(BINS)],
                                           "travel_deg": travel, "deadband": {"flex": [], "extend": []}})
        for deg, ma in r["samples"]:
            b = min(BINS - 1, max(0, int(float(deg) / travel * BINS)))
            cell[r["sense"]][b].append(float(ma) * flex_dir)
        if r.get("deadband_deg") is not None:
            cell["deadband"][r["sense"]].append(float(r["deadband_deg"]))
    out = {}
    for joint, cell in acc.items():
        out[joint] = {
            "flex": [round(sum(v) / len(v), 1) if v else None for v in cell["flex"]],
            "extend": [round(sum(v) / len(v), 1) if v else None for v in cell["extend"]],
            "travel_deg": round(cell["travel_deg"], 2),
            "deadband_deg": {k: (round(sum(v) / len(v), 2) if v else None) for k, v in cell["deadband"].items()},
        }
    return out


def decompose(curve: dict) -> tuple[list, list]:
    """(static, friction) per bin from a joint's flex and extend curves."""
    static, friction = [], []
    for f, e in zip(curve["flex"], curve["extend"]):
        if f is None or e is None:
            static.append(None)
            friction.append(None)
        else:
            static.append(round((f + e) / 2, 1))
            friction.append(round((f - e) / 2, 1))
    return static, friction


def _mean(values: list) -> float | None:
    v = [x for x in values if x is not None]
    return round(sum(v) / len(v), 1) if v else None


def _stretches(mine: list, theirs: list, tol: float) -> list[dict]:
    """Contiguous runs of bins where ``mine`` departs from ``theirs`` by more than ``tol``,
    as {"from": %, "to": %, "diff_ma": mean difference}."""
    out: list[dict] = []
    run: list[tuple[int, float]] = []

    def close() -> None:
        if len(run) >= MIN_STRETCH_BINS:
            out.append({"from": round(run[0][0] / BINS * 100), "to": round((run[-1][0] + 1) / BINS * 100),
                        "diff_ma": round(sum(d for _, d in run) / len(run), 1)})
        run.clear()

    for i, (a, b) in enumerate(zip(mine, theirs)):
        if a is None or b is None or abs(a - b) <= tol:
            close()
            continue
        if run and (run[-1][1] > 0) != (a - b > 0):
            close()
        run.append((i, a - b))
    close()
    return out


def compare(results: list[dict], ref: dict | None) -> dict:
    """Score a sweep's results against the reference dataset, curve by curve.

    Returns ``{"joints": {joint: {...}}, "bands": {...}}`` with, per joint, the
    static and friction curves (mine and the reference's), their mean
    difference in mA, the stretches of the travel that depart, the friction
    ``share`` of the reference, and a status by that share: ``ok`` (90-110 %),
    ``under`` (below 90 %), ``low`` (below 40 %, where clicks start), ``over`` (above 110 %, tighter,
    left alone), ``slack`` (dead band wider by SLACK_DEG), or ``none`` without
    a reference.
    """
    mine = curves(results)
    theirs = (ref.get("curves") or curves(ref.get("results") or [])) if ref else {}
    joints: dict[str, dict] = {}
    for joint, curve in mine.items():
        static, friction = decompose(curve)
        out: dict = {
            "status": "none", "travel_deg": curve["travel_deg"],
            "static": static, "friction": friction, "ref_static": None, "ref_friction": None,
            "static_ma": _mean(static), "friction_ma": _mean(friction),
            "ref_static_ma": None, "ref_friction_ma": None,
            "static_diff_ma": None, "friction_diff_ma": None, "stretches": [], "share": None,
            "deadband_deg": curve["deadband_deg"],
        }
        refcurve = theirs.get(joint)
        if refcurve:
            ref_static, ref_friction = decompose(refcurve)
            out.update(ref_static=ref_static, ref_friction=ref_friction,
                       ref_static_ma=_mean(ref_static), ref_friction_ma=_mean(ref_friction))
            level = max(abs(out["ref_friction_ma"] or 0), abs(out["ref_static_ma"] or 0))
            tol = max(TOL_MA, TOL_SHARE * level)
            diffs_f = [a - b for a, b in zip(friction, ref_friction) if a is not None and b is not None]
            diffs_s = [a - b for a, b in zip(static, ref_static) if a is not None and b is not None]
            out["friction_diff_ma"] = round(sum(diffs_f) / len(diffs_f), 1) if diffs_f else None
            out["static_diff_ma"] = round(sum(diffs_s) / len(diffs_s), 1) if diffs_s else None
            out["stretches"] = [{"kind": "friction", **st} for st in _stretches(friction, ref_friction, tol)] + [
                {"kind": "static", **st} for st in _stretches(static, ref_static, tol)]
            out["tol_ma"] = round(tol, 1)
            ref_db = refcurve["deadband_deg"]
            wider = any(
                curve["deadband_deg"].get(k) is not None and ref_db.get(k) is not None
                and curve["deadband_deg"][k] - ref_db[k] > SLACK_DEG for k in SENSES
            )
            mine_f, ref_f = out["friction_ma"] or 0.0, out["ref_friction_ma"] or 0.0
            if ref_f >= FLOOR_MA:
                share = mine_f / ref_f
            else:
                # Too little friction in the reference for a share: judge the difference.
                share = 1.0 if abs(mine_f - ref_f) <= TOL_MA else (UNDER - 0.01 if mine_f < ref_f else OVER + 0.01)
            out["share"] = round(share, 3)
            if share < LOW:
                out["status"] = "low"
            elif share < UNDER:
                out["status"] = "under"
            elif share > OVER:
                out["status"] = "over"
            elif wider:
                out["status"] = "slack"
            else:
                out["status"] = "ok"
            out["clicks"] = _clicks(joint, out["status"], share, curve["deadband_deg"], ref_db)
        joints[joint] = out
    return {"joints": joints, "bands": {"tol_ma": TOL_MA, "tol_share": TOL_SHARE, "bins": BINS, "slack_deg": SLACK_DEG,
                                        "low": LOW, "under": UNDER, "over": OVER}}


def _clicks(joint: str, status: str, share: float, deadband: dict, ref_deadband: dict) -> int | None:
    """Ratchet clicks the joint still needs: from the friction share when it is
    under, from the extra dead band when only that is wide, 0 otherwise."""
    if status in ("low", "under"):
        return shipped_reference.clicks_for_share(share, joint)
    if status == "slack":
        extra = max(
            (deadband[k] - ref_deadband[k] for k in SENSES
             if deadband.get(k) is not None and ref_deadband.get(k) is not None),
            default=0.0,
        )
        return shipped_reference.clicks_for_slack(extra, joint)
    return 0


def state(config, family: str | None) -> dict:
    data = _load(config)
    # Curves are large; the listing carries the levels, the full dataset is read by name.
    return {
        "sweeps": {
            n: {k: v for k, v in s.items() if k != "results"} | {"levels": levels(s.get("results") or [])}
            for n, s in sorted(data["sweeps"].items(), key=lambda kv: kv[1].get("recorded_at", ""), reverse=True)
        },
        "reference": (reference(config, family) or (None,))[0],
        "reference_shipped": data["reference"] not in data["sweeps"],
        "next_name": next_name(config),
    }


def dataset(config, name: str) -> dict | None:
    return _load(config)["sweeps"].get(name)
