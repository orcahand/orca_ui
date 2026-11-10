"""Every joint mapping of the connected hand as a ghost-hand overlay in the 3D views: orca_core
basic (its own estimate, this hand's config + calibration), main's packaged stops, each fitted map
of the visual calibration study (maps/<hand>/*.json), and every other bench hand's hard stops
(~/orca_bench/<hand>/<model>/config.yaml with the same joints, same side). All are computed from
orca_core's own estimate each frame; none drives the hand (that is the study map's selection)."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

from orca_ui.hand import main_stops
from orca_ui.hand.study_map import APPROACH, LABELS, ORDER, STUDY_MAP

config_source: Callable[[], str | None] = lambda: None
_others: dict[str, tuple[float, list[tuple[str, str, str]]]] = {}
_heldout: dict[str, tuple[float, dict]] = {}
_RESCAN_S = 10.0


def _side(model: str) -> str:
    return model.rsplit("-", 1)[-1]


def other_hands(config_path: str | None) -> list[tuple[str, str, str]]:
    """[(hand, model, config path)] of the other bench hands with this hand's joints."""
    if not config_path or "orca_bench" not in Path(config_path).parts[:-2]:
        return []
    hit = _others.get(config_path)
    if hit and time.monotonic() - hit[0] < _RESCAN_S:
        return hit[1]
    cfg = Path(config_path)
    hand, model, bench = cfg.parent.parent.name, cfg.parent.name, cfg.parent.parent.parent
    own = main_stops._tables(config_path, config_path) or {}
    packaged = main_stops.packaged(config_path)
    pkg = (main_stops._tables(config_path, packaged) or {}) if packaged else {}
    out = []
    for p in sorted(bench.glob("*/*/config.yaml")):
        h, m = p.parent.parent.name, p.parent.name
        if h == hand or _side(m) != _side(model):
            continue
        t = main_stops._tables(config_path, str(p))
        # only hands with stops of their own: a folder still on the packaged stops is just "main stops" again
        if t and set(t) == set(own) and h.startswith("ser-") and any(t[j][2:4] != pkg.get(j, (None,) * 4)[2:4] for j in t):
            out.append((h, m, str(p)))
    _others[config_path] = (time.monotonic(), out)
    return out


def _bench_heldout(config_path: str | None) -> dict:
    """Held-out accuracy of the bench's visual_calibration.json (e.g. "main stops"), if any."""
    if not config_path:
        return {}
    p = Path(config_path).parent / "visual_calibration.json"
    try:
        m = p.stat().st_mtime
    except OSError:
        return {}
    hit = _heldout.get(str(p))
    if hit and hit[0] == m:
        return hit[1]
    try:
        h = json.loads(p.read_text()).get("heldout") or {}
        out = {k: {a: v["deg"]["all"][a] for a in ("rms", "p50", "p95", "max", "n")} for k, v in h.items()}
    except (OSError, ValueError, KeyError, TypeError):
        out = {}
    _heldout[str(p)] = (m, out)
    return out


def catalog(config_path: str | None = None) -> list[dict]:
    """The overlay rows: id, label, approach, kind (basic/main/fitted/other-hand), held-out
    accuracy when known, and `mode` for the rows the study-map selection can drive the hand with."""
    cfg = config_path or config_source()
    files = STUDY_MAP.files()
    maps = {n: STUDY_MAP._load(files[n]) or {} for n in ORDER if n in files}
    bench = _bench_heldout(cfg)
    std = next((d.get("heldout_standard") for d in maps.values() if d.get("heldout_standard")), None)
    rows = [{"id": "basic", "kind": "basic", "label": "orca_core basic", "approach": APPROACH["off"],
             "heldout": std, "mode": "off"}]
    main = main_stops.packaged(cfg) if cfg else None
    if main:
        same = main_stops.same_stops(cfg, main)
        rows.append({"id": "main", "kind": "main", "label": "main stops",
                     "approach": "orca_core with the packaged hard stops on main" + (" (= this hand's)" if same else ""),
                     "heldout": bench.get("main stops")})
    for n, d in maps.items():
        rows.append({"id": f"map:{n}", "kind": "fitted", "label": d.get("label") or LABELS[n],
                     "approach": d.get("approach") or APPROACH[n], "heldout": d.get("heldout"),
                     "params": d.get("params"), "n_poses": d.get("n_poses"), "created": d.get("created"),
                     "mode": n})
    for h, m, p in other_hands(cfg):
        same = " (= this hand's)" if main_stops.same_stops(cfg, p) else " (= main stops)" if main and main_stops.same_stops(p, main) else ""
        rows.append({"id": f"hand:{h}", "kind": "other-hand", "label": f"{h} stops",
                     "approach": f"orca_core with {h}'s hard stops ({m}){same}"})
    return rows


def evaluate(config_path: str | None, standard: dict[str, float]) -> dict[str, dict[str, float]]:
    """{overlay id: joint angles} from orca_core's own estimate."""
    cfg = config_path or config_source()
    out: dict[str, dict[str, float]] = {"basic": standard}
    main = main_stops.packaged(cfg) if cfg else None
    if main and (m := main_stops.remap(cfg, main, standard)):
        out["main"] = m
    for n in STUDY_MAP.files():
        out[f"map:{n}"] = STUDY_MAP.forward(standard, n)
    for h, _, p in other_hands(cfg):
        if r := main_stops.remap(cfg, p, standard):
            out[f"hand:{h}"] = r
    return out
