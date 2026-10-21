"""How much one ratchet click changes a tendon, measured on the hand.

For each joint you name, the tension probe measures the tendon in both senses:
take-up (motor degrees turned at a low fixed current before the tendon goes
taut = slack) and breakaway (mA at which the joint starts to move = preload).
You do a known number of clicks on that motor's top spool, it measures again,
and the change per click is printed and saved. The console reads the saved
take-up degrees per click to turn a joint's slack into "~N clicks" in the
guided tensioning dialog.

    uv run python scripts/click_test.py --joints index_pip,index_mcp --clicks 3 --rounds 3
    uv run python scripts/click_test.py --joints index_pip --mock           # smoke test

Stop the console first: it owns the serial port. Lay the hand palm up with the
fingers relaxed and keep it that way between measurements. Results are appended
to tension_probes.yaml (``clicks``) beside the hand's calibration.
"""

from __future__ import annotations

import argparse
import sys
from statistics import mean

from orca_core.maintenance.tension_probe import (
    METHODS,
    POSE_MID,
    ProbeSettings,
    run_tension_probe,
)
from orca_core.utils.cli import (
    add_hand_arguments,
    connect_hand,
    create_hand_from_args,
    shutdown_hand,
)
from orca_ui.hand.probes import ran_free

SENSES = ("flex", "extend")


def _measure(hand, joints, settings, methods, pose) -> dict[str, dict[str, dict[str, float | None]]]:
    """``{joint: {"takeup": {sense: free_deg}, "breakaway": {sense: breakaway_ma}}}``."""
    report = run_tension_probe(
        hand, methods=methods, joints=joints, settings=settings, pose=pose
    )
    out: dict[str, dict[str, dict[str, float | None]]] = {
        j: {m: {} for m in methods} for j in joints
    }
    for r in report["results"]:
        cell = out[r["joint"]][r["method"]]
        tag = f"  {r['joint']:<11} {r['sense']:<6} {r['method']:<9}"
        if r["skipped"]:
            print(f"{tag} skipped — {r['skipped']}")
            cell[r["sense"]] = None
        elif r["method"] == "takeup":
            if not ran_free(r):
                print(f"{tag} {r['free_deg']:6.2f}° free at {settings.takeup_current_ma:.0f} mA")
                cell[r["sense"]] = r["free_deg"]
            else:
                # The joint followed the motor to the cap: free joint or slack beyond the
                # cap, either way not a slack measurement this click can be scored against.
                print(f"{tag} ran to the {r['cap_deg']:.0f}° cap without stalling — not scored")
                cell[r["sense"]] = None
        else:
            ma = r["breakaway_ma"]
            print(f"{tag} {'never moved' if ma is None else f'{ma:6.0f} mA breakaway'}")
            cell[r["sense"]] = ma
    short = report.get("pose_short") or {}
    if short:
        print(f"  pose not reached on: {', '.join(f'{j} ({d:.0f}°)' for j, d in short.items())}")
    return out


def _delta(before, after, clicks) -> dict[str, float]:
    """Per-click change for each sense both measurements have."""
    return {
        s: round((before[s] - after[s]) / clicks, 3)
        for s in SENSES
        if before.get(s) is not None and after.get(s) is not None
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    add_hand_arguments(parser, feedback_flag=False)
    parser.add_argument(
        "--joints",
        required=True,
        help="Comma-separated joints whose motor spools you will click (e.g. index_pip,index_mcp).",
    )
    parser.add_argument("--clicks", type=int, default=3, help="Clicks per round (default 3).")
    parser.add_argument(
        "--rounds", type=int, default=3, help="Measure → click → measure rounds (default 3)."
    )
    parser.add_argument(
        "--methods",
        default=",".join(METHODS),
        help=f"Probe methods, comma-separated (default {','.join(METHODS)}).",
    )
    parser.add_argument(
        "--pose",
        default=POSE_MID,
        choices=("mid", "neutral", "hold"),
        help="Where each probe starts (default mid: clear of both limits).",
    )
    parser.add_argument(
        "--takeup-current",
        type=float,
        default=ProbeSettings.takeup_current_ma,
        help=f"Fixed take-up current in mA (default {ProbeSettings.takeup_current_ma:g}).",
    )
    parser.add_argument(
        "--max-current",
        type=float,
        default=ProbeSettings.max_current_ma,
        help=f"Breakaway ramp ceiling in mA (default {ProbeSettings.max_current_ma:g}; Feetech ~600).",
    )
    parser.add_argument(
        "--hold-current",
        type=float,
        default=ProbeSettings.hold_current_ma,
        help=f"Current the other motors hold at, mA (default {ProbeSettings.hold_current_ma:g}).",
    )
    parser.add_argument(
        "--no-save", action="store_true", help="Do not append to tension_probes.yaml."
    )
    args = parser.parse_args()
    if args.clicks < 1 or args.rounds < 1:
        parser.error("--clicks and --rounds must be at least 1")
    joints = [j.strip() for j in args.joints.split(",") if j.strip()]
    methods = [m.strip() for m in args.methods.split(",") if m.strip()]
    if not set(methods) <= set(METHODS):
        parser.error(f"--methods must be from {list(METHODS)}")

    hand = create_hand_from_args(args, engage_feedback=False, engage_sensors=False)
    unknown = [j for j in joints if j not in hand.config.joint_to_motor_map]
    if unknown:
        parser.error(f"unknown joints {unknown}; one of {list(hand.config.joint_to_motor_map)}")
    motor_of = {j: abs(int(hand.config.joint_to_motor_map[j])) for j in joints}
    settings = ProbeSettings(
        takeup_current_ma=args.takeup_current,
        hold_current_ma=args.hold_current,
        max_current_ma=args.max_current,
    )
    rounds: dict[str, list[dict]] = {j: [] for j in joints}
    try:
        connect_hand(hand, interactive=not args.mock)
        print("\nMotors: " + ", ".join(f"{j} = M{m}" for j, m in motor_of.items()))
        print("Hand palm up, fingers relaxed, hands clear while it measures.")
        print("\nMeasuring before any click…")
        before = _measure(hand, joints, settings, methods, args.pose)
        for n in range(1, args.rounds + 1):
            print(f"\nRound {n}/{args.rounds}")
            for j in joints:
                ask = f"  {args.clicks} click(s) clockwise on the TOP spool of M{motor_of[j]} ({j}), then Enter… "
                if args.mock:
                    print(ask + "(mock: pressed for you)")
                else:
                    input(ask)
            print("Measuring again…")
            after = _measure(hand, joints, settings, methods, args.pose)
            for j in joints:
                entry = {"round": n, "clicks": args.clicks, "before": before[j], "after": after[j]}
                if "takeup" in methods:
                    entry["per_click_deg"] = _delta(before[j]["takeup"], after[j]["takeup"], args.clicks)
                if "breakaway" in methods:
                    # Preload rises with clicks, so report the increase as positive.
                    entry["per_click_ma"] = {
                        s: (-v if v else 0.0)
                        for s, v in _delta(before[j]["breakaway"], after[j]["breakaway"], args.clicks).items()
                    }
                rounds[j].append(entry)
                print(
                    f"  {j:<11} "
                    + "  ".join(f"take-up {s} {v:+.2f}°/click" for s, v in entry.get("per_click_deg", {}).items())
                    + "  "
                    + "  ".join(f"breakaway {s} {v:+.0f} mA/click" for s, v in entry.get("per_click_ma", {}).items())
                )
            before = after

        print("\nSummary")
        all_deg: list[float] = []
        for j in joints:
            degs = [max(r["per_click_deg"].values()) for r in rounds[j] if r.get("per_click_deg")]
            mas = [max(r["per_click_ma"].values()) for r in rounds[j] if r.get("per_click_ma")]
            parts = []
            if degs:
                parts.append(f"{mean(degs):+.2f}° of take-up per click (spread {max(degs) - min(degs):.2f}°)")
                all_deg += [d for d in degs if d > 0]
            if mas:
                parts.append(f"{mean(mas):+.0f} mA of breakaway per click")
            print(f"  {j:<11} " + "; ".join(parts))
        if all_deg:
            per_click = mean(all_deg)
            print(
                f"\n  Mean {per_click:.2f}° per click: a joint showing 10° of slack in the guided "
                f"check needs about {round(10 / per_click)} clicks."
            )
        if not args.no_save:
            from orca_ui.hand import probes

            for j in joints:
                key = probes.save_clicks(
                    hand.config,
                    {
                        "joint": j,
                        "motor": motor_of[j],
                        "methods": methods,
                        "pose": args.pose,
                        "takeup_current_ma": args.takeup_current,
                        "max_current_ma": args.max_current,
                        "hold_current_ma": args.hold_current,
                        "motor_type": getattr(type(hand.motor_client), "motor_type", None),
                        "rounds": rounds[j],
                    },
                )
                print(f"  saved {j} under clicks/{key}")
            print(f"  in {probes.probes_path(hand.config)}")
        return 0
    except KeyboardInterrupt:
        print("\nInterrupted — torque off.")
        return 1
    except ValueError as e:
        print(f"Cannot run: {e}", file=sys.stderr)
        return 1
    finally:
        shutdown_hand(hand)


if __name__ == "__main__":
    raise SystemExit(main())
