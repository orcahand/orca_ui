"""Compare a hand's motor-travel tables joint by joint.

Reads travel_baselines.yaml beside the hand's calibration (written by the
console: one snapshot per calibration run, named baselines such as GT_01) and
prints, per joint, the active baseline, the newest manual and automatic
snapshots, the shared v2.1 block, and how far each is from the baseline.

    uv run python scripts/compare_travel.py                       # autodetect the hand
    uv run python scripts/compare_travel.py path/to/config.yaml
    uv run python scripts/compare_travel.py --against GT_00 --manual manual_2026-10-15T17-50-00

A manual table (joint dragged by hand, torque off) below the automatic one
(motor-driven) on the same hand means the motor wound slack before the joint
moved; the automatic one falling short means the joint stalled before its stop.
"""

from __future__ import annotations

import argparse
import sys

from orca_ui.hand import baselines
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
        "config_path",
        nargs="?",
        default=None,
        help="Path to the hand's config.yaml; omit to autodetect the connected hand's model.",
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

    config_path = args.config_path
    if config_path is None:
        from orca_ui.hand.supervisor import _resolve_config_path

        config_path = _resolve_config_path(None)
    config = load_config(config_path)
    state = baselines.state(config)
    ref_name = args.against or state["active"]
    ref = state["baselines"].get(ref_name, {}).get("travel") if ref_name else None
    manual_name, manual = _latest(state["snapshots"], "manual", args.manual)
    auto_name, auto = _latest(state["snapshots"], "auto", args.auto)
    shared = state["shared"]

    print(f"hand: {config_path}")
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
