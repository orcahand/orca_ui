"""Pure helpers for what an app may command: range clamp and ramp-in blend."""

from __future__ import annotations


def clamp(angles: dict[str, float],
          ranges: dict[str, tuple[float, float]]) -> tuple[dict[str, float], list[str]]:
    """Clamp each joint to its range. Returns ``(clamped, unknown joints)``."""
    out: dict[str, float] = {}
    unknown: list[str] = []
    for joint, value in angles.items():
        rom = ranges.get(joint)
        if rom is None:
            unknown.append(joint)
            continue
        out[joint] = min(max(value, rom[0]), rom[1])
    return out, unknown


def blend(start: dict[str, float], target: dict[str, float], began: dict[str, float],
          now: float, duration: float) -> tuple[dict[str, float], bool]:
    """Ramp each joint linearly from ``start`` to ``target``. Returns ``(pose, done)``.

    Each joint's ramp begins the first time a target names it (recorded in
    ``began``), so a joint an app starts sending late still ramps in. A joint
    missing from ``start`` is left out. ``done`` once every joint of ``start``
    has finished its ramp.
    """
    pose: dict[str, float] = {}
    for joint, value in target.items():
        if joint not in start:
            continue
        t0 = began.setdefault(joint, now)
        fraction = 1.0 if duration <= 0 else min(max((now - t0) / duration, 0.0), 1.0)
        pose[joint] = start[joint] + (value - start[joint]) * fraction
    done = all(joint in began and now - began[joint] >= duration for joint in start)
    return pose, done
