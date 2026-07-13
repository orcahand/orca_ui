"""One-shot and short-window reads of the backend's ``/ws`` telemetry stream.

Live values (measured joints, tactile, motor temps/currents) exist only on
the WebSocket — there is no REST endpoint for them. The hub replays the
latest value per topic immediately on subscribe, so a connect → subscribe →
collect → close round trip is a cheap snapshot; holding the socket open for
a few seconds yields a downsampled time series.

Windowed reads are change-filtered before they are returned: a stationary
hand publishes the same angles 60 times a second, and an agent pays for
every copy out of its context window. Only frames that actually moved
survive (see :data:`DEADBANDS`), and what was dropped is reported.
"""

from __future__ import annotations

import asyncio
import json
import math
import time

import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

# Pure constants module (no orca_core / hardware imports).
from orca_ui.streaming.topics import ALL_TOPICS

from orca_ui.mcp.client import BackendError, unreachable_hint

MAX_SAMPLES_PER_TOPIC = 150

# Per-group change thresholds for windowed reads, each in its group's own
# unit. A frame survives only if some value moved further than its band.
# Keyed by the payload's inner group name, because that is what fixes the
# unit: {"angles": {...}}, {"forces": {...}}, {"temps": ..., "currents": ...}.
# Groups absent here (stats, control.state, teleop.preview's jpeg, …) are
# never filtered — an unknown shape must pass through untouched.
DEADBANDS: dict[str, tuple[float, str]] = {
    "angles": (0.5, "°"),
    "forces": (0.25, "N"),
    "taxels": (0.1, "N"),
    "temps": (0.5, "°C"),
    "currents": (20.0, "mA"),
}

_CONNECT_ERRORS = (OSError, TimeoutError, asyncio.TimeoutError,
                   WebSocketException)


def _deadband_summary() -> str:
    return ", ".join(f"{group} {band}{unit}"
                     for group, (band, unit) in DEADBANDS.items())


def _max_delta(a, b) -> float:
    """Largest absolute difference between two numeric scalars or two
    equally shaped nested lists. ``inf`` whenever the types or shapes don't
    line up, so anything we can't compare is treated as changed and kept."""
    if isinstance(a, bool) or isinstance(b, bool):
        return math.inf
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b))
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        return max((_max_delta(x, y) for x, y in zip(a, b)), default=0.0)
    return math.inf


def _changed(prev: dict, cur: dict) -> bool:
    """True when ``cur`` moved past the deadband of any group, or when its
    shape is one we don't know how to compare."""
    if not cur or set(cur) != set(prev):
        return True
    if any(group not in DEADBANDS for group in cur):
        return True
    for group, value in cur.items():
        band = DEADBANDS[group][0]
        before = prev[group]
        if (not isinstance(value, dict) or not isinstance(before, dict)
                or set(value) != set(before)):
            return True
        if any(_max_delta(v, before[k]) > band for k, v in value.items()):
            return True
    return False


def _change_filter(samples: list[dict]) -> tuple[list[dict], int]:
    """Drop frames that haven't moved past the deadband since the last kept
    frame. The first and last frames always survive, so the series still
    brackets the window and ``samples[-1]`` stays the freshest frame."""
    if len(samples) <= 2:
        return samples, 0
    kept = [samples[0]]
    for sample in samples[1:-1]:
        if _changed(kept[-1]["data"], sample["data"]):
            kept.append(sample)
    kept.append(samples[-1])
    return kept, len(samples) - len(kept)


def _ws_url(base_url: str) -> str:
    return base_url.rstrip("/").replace("http", "ws", 1) + "/ws"


def _check_topics(topics: list[str]) -> None:
    unknown = set(topics) - set(ALL_TOPICS)
    if unknown:
        raise BackendError(
            f"unknown topics: {sorted(unknown)} — valid topics: {ALL_TOPICS}")


async def _subscribed(ws, topics: list[str]) -> None:
    await ws.send(json.dumps(
        {"type": "subscribe", "data": {"topics": list(topics)}}))


def _parse(raw: str) -> tuple[str | None, dict, float | None]:
    try:
        message = json.loads(raw)
    except ValueError:
        return None, {}, None
    kind = message.get("type")
    data = message.get("data") or {}
    if kind == "error" and "unknown topics" in str(data.get("message", "")):
        raise BackendError(
            f"{data['message']} — valid topics: {ALL_TOPICS}")
    return kind, data, message.get("t")


async def ws_snapshot(base_url: str, topics: list[str],
                      duration_s: float = 0.0, sample_hz: float = 5.0,
                      open_timeout: float = 3.0,
                      snapshot_timeout: float = 2.0) -> dict:
    """Latest value per topic (``duration_s=0``) or a sampled window.

    Topics with no publisher yet (e.g. ``teleop.preview`` without a session)
    are reported under ``missing`` instead of hanging the call.
    """
    _check_topics(topics)
    wanted = set(topics)
    latest: dict[str, dict] = {}
    wall_t: dict[str, float] = {}    # ms-epoch stamp of the newest frame kept
    samples: dict[str, list[dict]] = {t: [] for t in topics}
    last_kept: dict[str, float] = {}
    min_gap = 1.0 / max(sample_hz, 0.1)
    if duration_s > 0:
        # Auto-decimate so the sample budget always spans the full window
        # instead of silently truncating its tail.
        min_gap = max(min_gap, duration_s / MAX_SAMPLES_PER_TOPIC)

    try:
        async with websockets.connect(_ws_url(base_url),
                                      open_timeout=open_timeout) as ws:
            await _subscribed(ws, topics)
            loop = asyncio.get_running_loop()
            start = loop.time()
            deadline = start + (duration_s if duration_s > 0
                                else snapshot_timeout)
            while True:
                if duration_s <= 0 and wanted <= set(latest):
                    break   # snapshot complete
                if duration_s > 0 and all(
                        len(samples[t]) >= MAX_SAMPLES_PER_TOPIC
                        for t in topics):
                    break   # every topic at the sample budget
                remaining = deadline - loop.time()
                if remaining <= 0:
                    break
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
                except asyncio.TimeoutError:
                    break
                except ConnectionClosed:
                    break
                kind, data, stamp = _parse(raw)
                if kind not in wanted:
                    continue
                latest[kind] = data
                if stamp is not None:
                    wall_t[kind] = stamp
                now = loop.time()
                if duration_s > 0 and now - last_kept.get(kind, -1e9) >= min_gap:
                    if len(samples[kind]) < MAX_SAMPLES_PER_TOPIC:
                        samples[kind].append(
                            {"t": round(now - start, 3), "data": data})
                        last_kept[kind] = now
    except _CONNECT_ERRORS as e:
        raise BackendError(unreachable_hint(base_url)) from e

    missing = sorted(wanted - set(latest))
    now_ms = time.time() * 1000
    if duration_s > 0:
        kept: dict[str, list[dict]] = {}
        dropped: dict[str, int] = {}
        for topic in topics:
            if not samples[topic]:
                continue
            kept[topic], n_dropped = _change_filter(samples[topic])
            if n_dropped:
                dropped[topic] = n_dropped
        out: dict = {"topics": {t: {"samples": s, "count": len(s)}
                                for t, s in kept.items()}}
        effective_hz = 1.0 / min_gap
        if effective_hz < sample_hz - 0.01:
            out["note_rate"] = (
                f"sample_hz reduced to {round(effective_hz, 1)} to fit the "
                f"{MAX_SAMPLES_PER_TOPIC}-samples-per-topic budget over "
                f"{duration_s} s")
        if dropped:
            out["dropped_unchanged"] = dropped
            out["note_unchanged"] = (
                "frames whose every value stayed inside its deadband "
                f"({_deadband_summary()}) were dropped; the first and last "
                "frame of the window are always kept. Timestamps are real "
                "capture times, so a gap in `t` means nothing moved there — "
                "not that sampling stopped.")
    else:
        out = {"topics": {t: latest.get(t) for t in topics}}
    # Frame ages (the hub replays the last-ever value on subscribe, so a
    # topic can answer instantly with data that is minutes old — e.g. a
    # preview frame from an ended teleop session).
    out["age_ms"] = {t: int(now_ms - wall_t[t]) for t in topics
                     if t in wall_t}
    if missing:
        out["missing"] = missing
        out["note"] = (
            "missing topics have no publisher right now (needs the matching "
            "capability, tactile mode, or an active teleop session)")
    return out


async def watch_convergence(base_url: str, targets: dict[str, float],
                            timeout_s: float, tolerance_deg: float,
                            open_timeout: float = 3.0) -> dict:
    """Watch ``joints.measured`` until every verifiable target joint is
    within ``tolerance_deg`` of its target, or ``timeout_s`` elapses.

    ``joints.measured`` frames carry every encoder-decodable joint, so
    target joints absent from the stream are reported as ``unverified``
    (no encoder), not treated as failures.
    """
    per_joint: dict[str, float] = {}
    seen_frame = False
    verifiable: set[str] = set()
    converged = False

    try:
        async with websockets.connect(_ws_url(base_url),
                                      open_timeout=open_timeout) as ws:
            await _subscribed(ws, ["joints.measured"])
            loop = asyncio.get_running_loop()
            start = loop.time()
            deadline = start + timeout_s
            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    break
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
                except (asyncio.TimeoutError, ConnectionClosed):
                    break
                kind, data, _ = _parse(raw)
                if kind != "joints.measured":
                    continue
                angles = data.get("angles") or {}
                if not seen_frame:
                    seen_frame = True
                    verifiable = set(targets) & set(angles)
                    if not verifiable:
                        break
                per_joint = {
                    j: round(abs(float(angles[j]) - float(targets[j])), 2)
                    for j in verifiable if j in angles
                }
                if per_joint and all(e <= tolerance_deg
                                     for e in per_joint.values()):
                    converged = True
                    break
            waited = round(loop.time() - start, 2)
    except _CONNECT_ERRORS as e:
        raise BackendError(unreachable_hint(base_url)) from e

    if not seen_frame:
        return {"converged": None, "per_joint_error_deg": {},
                "unverified_joints": sorted(targets), "waited_s": waited,
                "note": ("no joints.measured frames — encoders unavailable; "
                         "motion was commanded but not verified")}
    result: dict = {
        "converged": converged if verifiable else None,
        "max_error_deg": max(per_joint.values()) if per_joint else None,
        "per_joint_error_deg": per_joint,
        "unverified_joints": sorted(set(targets) - verifiable),
        "waited_s": waited,
    }
    if not verifiable:
        result["note"] = ("none of the commanded joints are encoder-backed; "
                          "motion was commanded but cannot be verified")
    return result
