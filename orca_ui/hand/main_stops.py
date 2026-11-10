"""orca_core's estimate as it would read with other hard stops: orca_core's packaged ones (the
model's config.yaml in the installed orca_core, = main) or another hand's (its config.yaml in
~/orca_bench). Same motors, same calibration, only the joint ROMs differ. orca_core maps a joint
linearly between its stops (lo + d, or hi - d for an inverted motor, d = motor travel / ratio), so
the motor's fraction of the way between the stops carries over: angle = lo_o + t (hi_o - lo_o), t
from the hand's own ROM. Drawn as ghost hands in the 3D views; nothing is commanded with it."""
from __future__ import annotations

import os
from functools import lru_cache

import yaml

_cache: dict[tuple[str, str], tuple[tuple[float, float], dict] | None] = {}


@lru_cache(maxsize=8)
def packaged(config_path: str) -> str | None:
    import orca_core
    model = os.path.basename(os.path.dirname(os.path.abspath(config_path)))
    root = os.path.join(os.path.dirname(orca_core.__file__), "models")
    for version in sorted(os.listdir(root), reverse=True):
        p = os.path.join(root, version, model, "config.yaml")
        if os.path.isfile(p):
            return p
    return None


def _tables(config_path: str, other: str) -> dict | None:
    """{joint: (own lo, own hi, other lo, other hi, inverted)}, reloaded when either config changes."""
    try:
        mtime = (os.path.getmtime(config_path), os.path.getmtime(other))
    except OSError:
        return None
    key = (config_path, other)
    hit = _cache.get(key)
    if hit is not None and hit[0] == mtime:
        return hit[1]
    with open(config_path) as f:
        own = yaml.safe_load(f) or {}
    with open(other) as f:
        oth = yaml.safe_load(f) or {}
    inv = {j: int(m) < 0 for j, m in (own.get("joint_to_motor_map") or {}).items()}
    a, b = own.get("joint_roms") or {}, oth.get("joint_roms") or {}
    out = {j: (*map(float, a[j]), *map(float, b[j]), inv.get(j, False)) for j in a if j in b}
    _cache[key] = (mtime, out)
    return out


def same_stops(config_path: str, other: str) -> bool:
    t = _tables(config_path, other)
    return bool(t) and all(r[0:2] == r[2:4] for r in t.values())


def remap(config_path: str | None, other: str | None, standard: dict[str, float]) -> dict[str, float] | None:
    """The estimate with `other`'s stops."""
    t = _tables(config_path, other) if config_path and other else None
    if not t:
        return None
    out = {}
    for j, q in standard.items():
        if j not in t or t[j][1] == t[j][0]:
            out[j] = q
            continue
        lo, hi, mlo, mhi, inv = t[j]
        f = (hi - q) / (hi - lo) if inv else (q - lo) / (hi - lo)
        out[j] = mhi - f * (mhi - mlo) if inv else mlo + f * (mhi - mlo)
    return out


def estimate(config_path: str | None, standard: dict[str, float]) -> dict[str, float] | None:
    """The estimate with main's stops; None when they are the hand's own (nothing to show apart)."""
    main = packaged(config_path) if config_path else None
    if not main or same_stops(config_path, main):
        return None
    return remap(config_path, main, standard)
