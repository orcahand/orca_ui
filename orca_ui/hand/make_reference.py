"""Turn one well-tensioned hand's records into the shipped setup reference.

Reads a hand's setup.yaml (or the separate files it replaced), takes its
tension sweep, manual calibration travel (and optionally its automatic one
and a slack test), prints them against the reference shipped now for that
hand type, and with ``--write`` replaces that type's entry in
setup_reference.yaml::

    uv run --with-editable ../orca_core python -m orca_ui.hand.make_reference \\
        --dir PATH/TO/MODEL/FOLDER --hand 7CFBEC24BE210835 --write

PATH/TO/MODEL/FOLDER is where the hand's setup.yaml sits (beside its
calibration.yaml). Without ``--sweep`` / ``--travel`` it takes the hand's own
sweep reference (else its newest sweep) and its active travel baseline (else
its newest full manual calibration).
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from types import SimpleNamespace

import yaml
from orca_core.maintenance.setup_file import read_section

from orca_ui.hand import reference as shipped
from orca_ui.hand.sweeps import curves, decompose

HEADER = """\
# What every hand of a type is scored against until it has a reference of its
# own, made from one well-tensioned hand of that type by
# orca_ui/hand/make_reference.py. Ships with the console, so every install
# scores sweeps and counts clicks straight away. A hand's own sweep reference
# or active travel baseline (kept in its setup.yaml) takes precedence.
#
# ratchet.deg_per_click: motor degrees of free rotation one ratchet click
#   takes up: 360 / 45 teeth. Turns slack (slack test, guided tensioning)
#   into clicks.
# ratchet.sweep_share_per_click: how much one click raises a joint's sweep
#   friction, as a share of the reference (one click measured +40 to +120 %
#   on 7CFBEC24BE210835, 2026-10-21).
# ratchet.click_scale: the share of the estimate recommended per joint,
#   below 1 where the plain estimate over-tensioned.
# hands.<motor family>:<hand type>; a type without its own uses another of
#   the same motor family:
#   travel: motor degrees between the hard stops per joint from a manual
#     calibration, what guided tensioning expects each joint to reach;
#     travel_auto: the same hand's automatic calibration, for comparison.
#   slack: free rotation per joint in the slack test, motor degrees.
#   sweep: the reference tension sweep as curves, mean signed current per
#     5 % of the travel in flex-positive units, per joint and sense.
#   sweep_scale: per joint, what the sweep curves are multiplied by where the
#     reference hand was tighter than wanted (kept when the entry is remade).
"""


class _Dumper(yaml.SafeDumper):
    pass


_Dumper.add_representer(
    list,
    lambda d, data: d.represent_sequence(
        "tag:yaml.org,2002:seq", data, flow_style=True
    ),
)


def _newest(records: dict, hand: str, ok=lambda r: True) -> tuple[str, dict] | None:
    mine = [(k, r) for k, r in records.items() if r.get("hand_key") == hand and ok(r)]
    return max(mine, key=lambda kv: kv[1].get("recorded_at", "")) if mine else None


def _pick(
    records: dict, name: str | None, hand: str, ok=lambda r: True
) -> tuple[str, dict]:
    if name:
        if name not in records:
            sys.exit(
                f"no record named {name!r}; there are: {', '.join(sorted(records)) or 'none'}"
            )
        return name, records[name]
    found = _newest(records, hand, ok)
    if found is None:
        sys.exit(f"no record for hand {hand!r}")
    return found


def _friction(curve: dict) -> float | None:
    values = [v for v in decompose(curve)[1] if v is not None]
    return sum(values) / len(values) if values else None


def _row(joint: str, new, old, unit: str) -> str:
    if new is None:
        return f"  {joint:<11} {'—':>8}"
    line = f"  {joint:<11} {new:8.1f}{unit}"
    if old:
        line += f"   was {old:7.1f}{unit}  ({new / old:4.0%})"
    return line


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dir", required=True, help="the model folder with the hand's setup.yaml")
    parser.add_argument("--hand", required=True, help="the hand's board id (hand_key in the records)")
    parser.add_argument("--sweep", help="sweep name (default: the hand's reference, else its newest)")
    parser.add_argument("--travel", help="travel snapshot or baseline the range check expects "
                        "(default: active baseline, else newest full manual calibration)")
    parser.add_argument("--travel-auto", help="automatic calibration snapshot kept beside it for comparison")
    parser.add_argument("--slack", help="slack test key, or 'latest' (default: none)")
    parser.add_argument("--kind", help="hand type the reference is for (default: from the model folder)")
    parser.add_argument("--note", default="", help="why this hand is the reference")
    parser.add_argument("--write", action="store_true", help="replace this hand type's reference")
    args = parser.parse_args(argv)

    folder = os.path.abspath(args.dir)
    config = SimpleNamespace(
        calibration_path=os.path.join(folder, "calibration.yaml"),
        config_path=os.path.join(folder, "config.yaml"),
    )
    kind = args.kind or shipped.hand_kind(config)
    sweep_data = read_section(config, "tension_sweeps", legacy="tension_sweeps.yaml") or {}
    travel_data = read_section(config, "travel_baselines", legacy="travel_baselines.yaml") or {}
    slack_data = read_section(config, "slack_tests", legacy="slack_tests.yaml") or {}

    sweeps = sweep_data.get("sweeps") or {}
    marked = sweep_data.get("reference")
    sweep_name = args.sweep or (marked if (sweeps.get(marked) or {}).get("hand_key") == args.hand else None)
    sweep_name, sweep = _pick(sweeps, sweep_name, args.hand)
    family = sweep.get("motor_type") or "dynamixel"

    snapshots = travel_data.get("snapshots") or {}
    named = {**snapshots, **(travel_data.get("baselines") or {})}
    active = travel_data.get("active")
    travel_name = args.travel or (active if active in (travel_data.get("baselines") or {}) else None)
    if travel_name:
        travel_name, travel_entry = _pick(named, travel_name, args.hand)
    else:
        travel_name, travel_entry = _pick(
            snapshots, None, args.hand, ok=lambda r: not r.get("partial") and r.get("source") == "manual"
        )
    auto = _pick(snapshots, args.travel_auto, args.hand) if args.travel_auto else None
    slack_test = None
    if args.slack:
        # Only tests made with the joint held count; they carry max_free_deg.
        slack_key, slack_test = _pick(
            slack_data.get("tests") or {}, None if args.slack == "latest" else args.slack, args.hand,
            ok=lambda r: "max_free_deg" in (r.get("settings") or {}),
        )

    def fingers(table: dict) -> dict:
        return {j: round(float(t), 2) for j, t in (table or {}).items() if j != "wrist"}

    new_curves = curves(sweep.get("results") or [])
    new_travel = fingers(travel_entry.get("travel"))
    new_auto = fingers(auto[1].get("travel")) if auto else {}
    new_slack = {
        r["joint"]: round(float(r["total_deg"]), 2)
        for r in (slack_test or {}).get("results") or []
        if r.get("status") != "skipped" and r.get("total_deg") is not None
    }

    old = shipped.entry(config, family)
    old_curves = (old.get("sweep") or {}).get("curves") or {}
    old_travel = old.get("travel") or {}
    if not old_travel and os.path.exists(config.config_path):
        old_travel = (yaml.safe_load(open(config.config_path)) or {}).get("joint_motor_travel_v21") or {}

    print(f"reference for {family}:{kind}, hand {args.hand}")
    print(f"sweep {sweep_name}: mean friction, mA, against {(old.get('sweep') or {}).get('name') or 'nothing'}")
    for j, c in new_curves.items():
        print(_row(j, _friction(c), _friction(old_curves[j]) if j in old_curves else None, ""))
    print(f"travel {travel_name}: motor degrees between the stops, against the current reference")
    for j, t in new_travel.items():
        print(_row(j, t, old_travel.get(j), "°"))
    if auto:
        print(f"automatic calibration {auto[0]} against it")
        for j, t in new_auto.items():
            print(_row(j, t, new_travel.get(j), "°"))
    if slack_test is not None:
        print(f"slack test {slack_key}: free rotation, motor degrees")
        for j, v in new_slack.items():
            print(_row(j, v, (old.get("slack") or {}).get(j), "°"))

    if not args.write:
        print("\nnothing written; add --write to make this the shipped reference")
        return
    data = shipped.load()
    hands = dict(data.get("hands") or {})
    kept_scale = (hands.get(f"{family}:{kind}") or {}).get("sweep_scale")
    hands[f"{family}:{kind}"] = {
        "hand_key": args.hand,
        "made": date.today().isoformat(),
        "note": args.note,
        "travel_from": travel_name,
        "travel": new_travel,
        **({"travel_auto_from": auto[0], "travel_auto": new_auto} if auto else {}),
        **({"slack_from": slack_key, "slack": new_slack} if slack_test is not None else {}),
        **({"sweep_scale": kept_scale} if kept_scale else {}),
        "sweep": {
            "name": sweep_name,
            "recorded_at": sweep.get("recorded_at"),
            "note": sweep.get("note"),
            "speed_deg_s": (sweep.get("settings") or {}).get("speed_deg_s"),
            "sweep_current_ma": (sweep.get("settings") or {}).get("sweep_current_ma"),
            "curves": new_curves,
        },
    }
    out = {"ratchet": data.get("ratchet") or {}, "hands": hands}
    with open(shipped.REFERENCE_FILE, "w") as f:
        f.write(HEADER + yaml.dump(out, Dumper=_Dumper, sort_keys=False, width=200))
    print(f"\nwrote {family}:{kind} into {shipped.REFERENCE_FILE}")


if __name__ == "__main__":
    main()
