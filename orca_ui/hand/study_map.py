"""The visual calibration study's joint maps as a layer on top of manual joint commands.

The hand study (orca_core experiments/visual_calibration/hand_study) measured, from photos,
where each joint really is for a given command. A map holds, per joint, the measured map
command -> true angle (monotone, piecewise linear) and orca_core's estimate -> true (for display).
Maps are per hand: ``maps/<hand>/<name>.json`` (``stops``: hard stops refitted, linear;
``curve``: one curve per joint; ``lut``: the curve plus terms over the finger's other joints and
the wrist; ``advanced``: the physical model of hand_study/advanced.py, a smooth curve, tendon
coupling, compliance and backlash), and the first study's ``joint_map.json`` for ser-4485. When a map is
selected it is the hand's joint mapping for all of orca-ui: every joint target (any source: sliders,
REST/ws, poses, sequences, teleop, neutral/zero) is the true angle wanted and turned into the command
that reaches it (``command``), clamped to the reachable range; every joint estimate read from
orca_core comes back as the true angle (``estimate``, in HandSession). orca_core's own calibration is
untouched; off (the default), both pass through unchanged. The selection is kept per hand on disk.
Hysteresis (approach direction) is corrected only by the advanced map, from the direction
each joint's target moves in; its compliance term is used at zero current (no current feed).
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Callable

import numpy as np

from orca_ui import research

STUDY = Path.home() / ".orca_ui" / "visual_calibration" / "hand_study"
PATH = STUDY / "joint_map.json"
LEGACY_HAND = "ser-4485"
LABELS = {"stops": "Hard stops (refit)", "curve": "Per-joint curve", "lut": "Coupled table (LUT)",
          "advanced": "Advanced", "joint_map": "Joint map (first study)"}
APPROACH = {"off": "orca_core linear map, this hand's config",
            "stops": "linear between refitted stops",
            "curve": "monotone curve per joint",
            "lut": "per joint + neighbouring-joint coupling",
            "advanced": "physical model: tendon coupling, hysteresis by direction, compliance",
            "joint_map": "per-joint curve of the first study"}
NAMES = ("stops", "curve", "lut", "advanced")
PREFERRED = ("curve", "advanced", "lut", "stops", "joint_map")
ORDER = ("stops", "curve", "lut", "advanced", "joint_map")


def _hat(x: float, knots: np.ndarray) -> np.ndarray:
    x = min(max(x, knots[0]), knots[-1])
    k = int(np.clip(np.searchsorted(knots, x, side="right") - 1, 0, len(knots) - 2))
    t = (x - knots[k]) / (knots[k + 1] - knots[k])
    b = np.zeros(len(knots))
    b[k], b[k + 1] = 1 - t, t
    return b


class StudyMap:
    def __init__(self, path: Path = PATH, root: Path = STUDY / "maps", selection: Path | None = None):
        self.path, self.root = path, root
        self.selection = selection or path.parent / "study_map_selected.json"
        self._modes: dict[str, str] | None = None
        self.hand_source: Callable[[], str | None] = lambda: None
        self._lock = threading.Lock()
        self._cache: dict[Path, tuple[float, dict]] = {}
        self._dir: dict[str, float] = {}

    def _selected(self) -> dict[str, str]:
        if self._modes is None:
            try:
                self._modes = dict(json.loads(self.selection.read_text()))
            except (OSError, ValueError):
                self._modes = {}
        return self._modes

    @property
    def mode(self) -> str:
        """The connected hand's selected map; off for a hand never set or whose map is gone, and
        always off without --research-ui (a stored selection is kept but not applied)."""
        if not research.enabled():
            return "off"
        hand = self.hand_source()
        m = self._selected().get(hand or "", "off")
        return m if m == "off" or m in self.files(hand) else "off"

    @mode.setter
    def mode(self, mode: str) -> None:
        if mode != "off" and not research.enabled():
            raise ValueError("study maps are a research extra: start the console with --research-ui")
        modes = self._selected()
        modes[self.hand_source() or ""] = mode
        try:
            self.selection.parent.mkdir(parents=True, exist_ok=True)
            self.selection.write_text(json.dumps(modes, indent=1))
        except OSError:
            pass                                    # still applies for this run

    @property
    def enabled(self) -> bool:
        return self.mode != "off"

    def _load(self, p: Path) -> dict | None:
        with self._lock:
            if not p.exists():
                self._cache.pop(p, None)
                return None
            m = p.stat().st_mtime
            if p not in self._cache or self._cache[p][0] != m:
                self._cache[p] = (m, json.loads(p.read_text()))
            return self._cache[p][1]

    def files(self, hand: str | None = None) -> dict[str, Path]:
        """The maps of the connected hand, by name."""
        hand = hand if hand is not None else self.hand_source()
        out = {}
        if hand:
            for name in NAMES:
                if (self.root / hand / f"{name}.json").exists():
                    out[name] = self.root / hand / f"{name}.json"
        if (hand in (None, LEGACY_HAND)) and self.path.exists():
            out["joint_map"] = self.path
        return out

    def data(self, name: str | None = None) -> dict | None:
        files = self.files()
        if name is None or name == "off":
            mode = self.mode
            name = mode if mode in files else next((n for n in PREFERRED if n in files), None)
        return self._load(files[name]) if name in files else None

    def set_mode(self, mode: str) -> None:
        if mode != "off" and mode not in self.files():
            raise ValueError(f"no study map '{mode}' for hand {self.hand_source() or '?'}")
        self.mode = mode

    def set_enabled(self, on: bool) -> None:
        """Back-compat switch: on picks the preferred map of this hand."""
        if not on:
            self.mode = "off"
            return
        files = self.files()
        best = next((n for n in PREFERRED if n in files), None)
        if best is None:
            raise ValueError(f"no study map for hand {self.hand_source() or '?'}")
        self.mode = best

    def state(self) -> dict:
        files = self.files()
        mode = self.mode
        options = []
        for n in ORDER:
            if n in files:
                d = self._load(files[n]) or {}
                options.append({"name": n, "label": LABELS[n], "approach": APPROACH[n], "created": d.get("created"),
                                "n_poses": d.get("n_poses"), "params": d.get("params"), "heldout": d.get("heldout"),
                                "heldout_standard": d.get("heldout_standard")})
        return {"enabled": mode != "off", "mode": mode, "hand": self.hand_source(),
                "available": bool(files), "options": options, "path": str(files.get(mode, "")),
                "standard": {"label": "Standard", "approach": APPROACH["off"]},
                "scope": "global: every joint target and every published joint estimate", "map": self.data()}

    def _forward_coupled(self, d: dict, x: dict[str, float]) -> dict[str, float]:
        c = d["coupled"]
        out = {}
        for j, w in c["w"].items():
            w = np.asarray(w, float)
            cols = [_hat(float(x.get(j, 0.0)), np.asarray(c["own"][j]))]
            for p in c["parts"][j]:
                pk = np.asarray(c["pk"][p])
                cols.append(_hat(float(x.get(p, 0.0)), pk) - _hat(0.0, pk))
            out[j] = float(x.get(j, 0.0) + np.concatenate(cols) @ w)
        return out

    @staticmethod
    def _forward_advanced(d: dict, x: dict[str, float], dirs: dict[str, float] | None = None,
                          cur: dict[str, float] | None = None) -> dict[str, float]:
        a = d["advanced"]
        out = {}
        for j, coef in a["a"].items():
            lo, hi = a["rom"][j]
            xj = float(x.get(j, 0.0))
            u = min(max(2 * (xj - lo) / (hi - lo) - 1, -a["u_clip"]), a["u_clip"])
            P = (1.0, u, (3 * u * u - 1) / 2, (5 * u ** 3 - 3 * u) / 2)
            v = xj + sum(c * p for c, p in zip(coef, P))
            v += sum(c * float(x.get(p, 0.0)) for c, p in zip(a["c"][j], a["parts"][j]))
            v += a["k_per_a"][j] * float((cur or {}).get(j, 0.0)) / 1000 + a["beta"][j] * float((dirs or {}).get(j, 0.0))
            out[j] = v
        return out

    def estimate(self, estimate: dict[str, float]) -> dict[str, float]:
        """orca_core's estimate as the true angles while a map is selected; unchanged when off."""
        mode = self.mode
        return self.forward(estimate, mode) if mode != "off" else estimate

    def forward(self, estimate: dict[str, float], name: str | None = None) -> dict[str, float]:
        """Where the joints really are, from orca_core's estimate (map `name`, else the selected, else the preferred)."""
        d = self.data(name)
        if d is None:
            return dict(estimate)
        if d.get("advanced"):
            f = self._forward_advanced(d, estimate, self._dir)
            return {j: f.get(j, v) for j, v in estimate.items()}
        if d.get("coupled"):
            f = self._forward_coupled(d, estimate)
            return {j: f.get(j, v) for j, v in estimate.items()}
        out = {}
        for j, v in estimate.items():
            t = d["joints"].get(j)
            out[j] = float(np.interp(v, t["assumed_knots"], t["assumed_true"])) if t else v
        return out

    def command(self, angles: dict[str, float], current: dict[str, float] | None = None) -> dict[str, float]:
        """The commands that make each joint really reach the wanted angle (identity when
        off, for joints the study does not correct, or with no map). A coupled map needs the
        whole pose: `current` (the other joints' targets) fills it, and every joint's command
        comes back, since moving one joint changes what its partners need."""
        mode = self.mode
        d = self.data(mode) if mode != "off" else None
        if d is None:
            return dict(angles)
        if d.get("advanced"):
            return self._command_advanced(d, angles, current or {})
        if d.get("coupled") and current:
            angles = {**{j: float(v) for j, v in current.items()}, **angles}
        out = {}
        for j, want in angles.items():
            t = d["joints"].get(j)
            if t is None or not t.get("applied"):
                out[j] = want
                continue
            cmd, true = np.asarray(t["cmd_knots"], float), np.asarray(t["cmd_true"], float)
            lo, hi = min(true[0], true[-1]), max(true[0], true[-1])
            want = min(max(float(want), lo), hi)
            order = np.argsort(true)
            out[j] = float(np.interp(want, true[order], cmd[order]))
        if d.get("coupled"):
            # the per-joint curves give the start; the coupling terms are undone iteratively,
            # every command kept inside the curve's knots (the configured range)
            goal = {j: min(max(float(v), d["joints"][j]["reach"][0]), d["joints"][j]["reach"][1])
                    if j in d["joints"] else float(v) for j, v in angles.items()}
            full = dict(out)
            for _ in range(30):
                got = self._forward_coupled(d, full)
                err = {j: goal[j] - got[j] for j in goal if j in got}
                for j, e in err.items():
                    k = d["joints"][j]["cmd_knots"]
                    full[j] = float(np.clip(full[j] + 0.8 * e, k[0], k[-1]))
                if max((abs(e) for e in err.values()), default=0.0) < 0.05:
                    break
            out = {j: full[j] for j in angles}
        return out

    def _command_advanced(self, d: dict, angles: dict[str, float], current: dict[str, float]) -> dict[str, float]:
        """Every joint's command for the whole pose (coupling), each joint moving in the direction
        its target moves (backlash; a joint whose target stays keeps its last direction)."""
        a = d["advanced"]
        goal = {**{j: float(v) for j, v in current.items()}, **{j: float(v) for j, v in angles.items()}}
        for j, v in angles.items():
            if j in current and abs(float(v) - float(current[j])) > 0.05:
                self._dir[j] = 1.0 if float(v) > float(current[j]) else -1.0
        for j in goal:
            if j in d["joints"]:
                lo, hi = d["joints"][j]["reach"]
                goal[j] = min(max(goal[j], lo), hi)
        x = dict(goal)
        for _ in range(40):
            got = self._forward_advanced(d, x, self._dir)
            err = {j: goal[j] - got[j] for j in goal if j in got}
            for j, e in err.items():
                lo, hi = a["rom"][j]
                x[j] = float(min(max(x[j] + 0.8 * e, lo), hi))      # commands stay inside the configured range
            if max((abs(e) for e in err.values()), default=0.0) < 0.02:
                break
        return {j: x[j] for j in goal}


STUDY_MAP = StudyMap()
