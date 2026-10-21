"""The shipped setup reference (setup_reference.yaml): what every hand of a
type is scored against until it has its own (tension sweep, travel, slack
test), made by make_reference.py from one well-tensioned hand of that type,
and what one ratchet click does.

Clicks are estimated conservatively, rounding toward fewer: a click too few
costs one more round, a click too many over-tensions the tendon.
"""

from __future__ import annotations

import math
import os
from functools import lru_cache
from pathlib import Path

from orca_core.utils.utils import read_yaml

REFERENCE_FILE = Path(__file__).with_name("setup_reference.yaml")
# A sweep estimate never goes past this share of the reference friction.
SWEEP_CEILING = 1.1
# Below this share of the reference a joint gets clicks from the sweep; above
# it the difference can be the hand rather than the tendon.
CLICK_BELOW_SHARE = 0.4


@lru_cache(maxsize=1)
def load() -> dict:
    return read_yaml(str(REFERENCE_FILE)) or {}


def hand_kind(config) -> str:
    """The hand type a model folder names, side left out: ``orcahand-touch-right``
    is ``touch``, ``orcahand-right`` is ``plain``."""
    name = os.path.basename(os.path.dirname(getattr(config, "config_path", "") or ""))
    parts = [p for p in name.split("-") if p not in ("orcahand", "left", "right")]
    return "-".join(parts) or "plain"


def entry(config, family: str | None) -> dict:
    """The reference for this hand's type and motor family (``family:kind``),
    else any of that family's (another hand type), else none. With no family
    known, any family's for this hand type."""
    hands = load().get("hands") or {}
    kind = hand_kind(config)
    if family:
        found = hands.get(f"{family}:{kind}") or next(
            (v for k, v in hands.items() if k.split(":")[0] == family), None
        )
    else:
        found = next((v for k, v in hands.items() if k.endswith(f":{kind}")), None)
    return dict(found or {})


def sweep(config, family: str | None) -> dict | None:
    """The reference sweep (name, curves, ...), or None. ``sweep_scale`` in the
    entry scales a joint's curves (below 1 where the reference hand was tighter
    than it should be)."""
    found = entry(config, family)
    ref = found.get("sweep")
    scale = found.get("sweep_scale") or {}
    if not ref or not scale:
        return ref
    curves = {}
    for joint, curve in (ref.get("curves") or {}).items():
        k = float(scale.get(joint, 1.0))
        curves[joint] = {
            **curve,
            **{sense: [None if v is None else v * k for v in curve[sense]] for sense in ("flex", "extend")},
        }
    return {**ref, "curves": curves}


def travel(config, family: str | None) -> dict[str, float]:
    """The reference hand's motor travel per joint (what guided tensioning
    expects); empty when the reference has none."""
    return {j: float(t) for j, t in (entry(config, family).get("travel") or {}).items()}


def slack(config, family: str | None) -> dict[str, float]:
    """The reference hand's slack test, free rotation per joint in motor degrees."""
    return {j: float(t) for j, t in (entry(config, family).get("slack") or {}).items()}


def deg_per_click() -> float | None:
    value = (load().get("ratchet") or {}).get("deg_per_click")
    return float(value) if value else None


def share_per_click() -> float:
    return float((load().get("ratchet") or {}).get("sweep_share_per_click") or 0.6)


def click_scale(joint: str) -> float:
    """How much of the estimate to recommend on ``joint`` (below 1 where the
    plain estimate over-tensioned)."""
    return float(((load().get("ratchet") or {}).get("click_scale") or {}).get(joint, 1.0))


def clicks_for_slack(slack_deg: float | None, joint: str) -> int | None:
    """Clicks that take up ``slack_deg`` motor degrees of free rotation on
    ``joint``, or None while degrees per click is unknown."""
    per_click = deg_per_click()
    if slack_deg is None or per_click is None:
        return None
    return max(0, math.floor(slack_deg * click_scale(joint) / per_click))


def clicks_for_share(share: float | None, joint: str) -> int | None:
    """Clicks that raise a sweep's friction ``share`` of the reference toward
    1.0 without passing SWEEP_CEILING; 0 from CLICK_BELOW_SHARE up."""
    if share is None:
        return None
    if share >= CLICK_BELOW_SHARE:
        return 0
    per_click = share_per_click()
    clicks = max(0, round((1.0 - share) * click_scale(joint) / per_click))
    while clicks and share + clicks * per_click > SWEEP_CEILING:
        clicks -= 1
    return clicks
