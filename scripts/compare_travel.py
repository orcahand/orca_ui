"""Compare a hand's motor-travel tables joint by joint.

Reads the travel_baselines section of setup.yaml in the hand's own folder, and
its archive (written by the console: one snapshot per calibration run, named
baselines such as GT_01), and prints, per joint, the active baseline, the
newest manual and automatic snapshots, the shared v2.1 block, and how far each
is from the baseline.

    uv run python scripts/compare_travel.py --dir ~/.orca/hands/0123456789ABCDEF
    uv run python scripts/compare_travel.py --dir <hand folder> path/to/config.yaml
    uv run python scripts/compare_travel.py --dir <hand folder> --against GT_00 \
        --manual manual_2026-10-15T17-50-00

A manual table (joint dragged by hand, torque off) below the automatic one
(motor-driven) on the same hand means the motor wound slack before the joint
moved; the automatic one falling short means the joint stalled before its stop.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import replace

from orca_core.hand_store import read_hand

from orca_ui.hand import baselines
from orca_ui.hand.models import available_models
from orca_ui.hand.supervisor import load_config


def _latest(
    snapshots: dict, source: str, pick: str | None
) -> tuple[str | None, dict | None]:
    if pick:
        return pick, snapshots.get(pick)
    for name, snap in snapshots.items():  # newest first
        if snap.get("source") == source:
            return name, snap
    return None, None


def _pct(value: float | None, ref: float | None) -> str:
    if value is None or not ref:
        return "    -"
    return f"{100 * value / ref:5.0f}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dir", required=True, help="The hand's folder, with its setup.yaml (~/.orca/hands/<id>)."
    )
    parser.add_argument(
        "config_path",
        nargs="?",
        default=None,
        help="Path to the hand's config.yaml; omit to use the model the hand's folder names.",
    )
    parser.add_argument(
        "--against",
        default=None,
        help="Baseline to compare against (default: the active one).",
    )
    parser.add_argument(
        "--manual", default=None, help="Snapshot name to use as the manual table."
    )
    parser.add_argument(
        "--auto", default=None, help="Snapshot name to use as the automatic table."
    )
    args = parser.parse_args()

    folder = os.path.abspath(os.path.expanduser(args.dir))
    config_path = args.config_path
    if config_path is None:
        model = read_hand(folder).get("model")
        config_path = next((m.config_path for m in available_models() if m.name == model), None)
        if config_path is None:
            print(f"{folder} names no known model ({model!r}): pass its config.yaml", file=sys.stderr)
            return 2
    config = replace(load_config(config_path), hand_dir=folder)
    state = baselines.state(config)
    ref_name = args.against or state["active"]
    ref = state["baselines"].get(ref_name, {}).get("travel") if ref_name else None
    manual_name, manual = _latest(state["snapshots"], "manual", args.manual)
    auto_name, auto = _latest(state["snapshots"], "auto", args.auto)
    shared = state["shared"]

    print(f"hand: {folder} ({config_path})")
    print(
        f"baseline: {ref_name or '(none active)'}   manual: {manual_name or '-'}   auto: {auto_name or '-'}"
    )
    print(
        f"{'joint':12}{'GT°':>8}{'manual°':>9}{'%GT':>6}{'auto°':>8}{'%GT':>6}{'auto/man%':>10}{'v21°':>8}{'%GT':>6}"
    )
    joints = [j for j in config.joint_ids if j in config.joint_to_motor_map]
    for j in joints:
        g = (ref or {}).get(j)
        m = (manual or {}).get("travel", {}).get(j)
        a = (auto or {}).get("travel", {}).get(j)
        v = shared.get(j)
        fmt = lambda x: f"{x:8.1f}" if x is not None else f"{'-':>8}"  # noqa: E731
        print(
            f"{j:12}{fmt(g)}{fmt(m)[1:]}{_pct(m, g):>6}{fmt(a)}{_pct(a, g):>6}{_pct(a, m):>10}{fmt(v)}{_pct(v, g):>6}"
        )
    if ref is None:
        print(
            "\nno active baseline: promote a snapshot in the console (Setup → Calibrate → settings)",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
