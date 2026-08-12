"""Sample tactile.taxels off the orca-ui WebSocket and summarize the range.

Answers one question: how large does a single taxel's force magnitude actually
get under a hard fingertip press? That is the denominator the magnitude ramp
normalizes against (``MAX_TAXEL_FORCE_BY_FINGER`` in the frontend's
``theme/tokens.ts``), and it is NOT the 25.5 N full scale of the wire
encoding — re-run this and update those values if the sensor hardware changes.

Needs the orca-ui backend up with a tactile stream running (any mode that
includes taxels). Press one finger hard and hold; the summary reports the peak
magnitude every taxel reached, and flags readings sitting on the int8/uint8
rails, which mean the sensor is saturating rather than measuring.

Usage: python scripts/measure_taxels.py [seconds] [finger]
"""

import asyncio
import json
import math
import sys

import websockets

URL = "ws://localhost:5001/ws"
PRESS_N = 2.0  # a finger peaking below this was not pressed, just idling


async def main(duration_s: float, focus: str) -> None:
    # {finger: [peak magnitude per taxel]} and the peak whole-frame picture.
    peaks: dict[str, list[float]] = {}
    frames = 0
    # {finger: (frame max magnitude, [magnitudes], [vectors])} — tracked for
    # every finger so one capture can cover several presses in sequence.
    best: dict[str, tuple] = {}

    async with websockets.connect(URL, max_size=None) as ws:
        await ws.send(json.dumps(
            {"type": "subscribe", "data": {"topics": ["tactile.taxels"]}}))
        deadline = asyncio.get_event_loop().time() + duration_s
        while asyncio.get_event_loop().time() < deadline:
            try:
                raw = await asyncio.wait_for(
                    ws.recv(), timeout=max(0.1, deadline - asyncio.get_event_loop().time()))
            except asyncio.TimeoutError:
                break
            message = json.loads(raw)
            if message.get("type") != "tactile.taxels":
                continue
            taxels = message["data"]["taxels"]
            frames += 1
            for finger, vectors in taxels.items():
                mags = [math.sqrt(x * x + y * y + z * z) for x, y, z in vectors]
                slot = peaks.setdefault(finger, [0.0] * len(mags))
                for i, m in enumerate(mags):
                    if m > slot[i]:
                        slot[i] = m
                top = max(mags)
                if finger not in best or top > best[finger][0]:
                    best[finger] = (top, mags, vectors)

    print(f"frames: {frames}")
    print()
    print("per-finger peak taxel magnitude over the whole capture (N):")
    for finger, slot in sorted(peaks.items()):
        ranked = sorted(slot, reverse=True)
        print(f"  {finger:<7} n={len(slot):<3} "
              f"max={ranked[0]:6.2f}  2nd={ranked[1]:6.2f}  "
              f"5th={ranked[4]:6.2f}  10th={ranked[9]:6.2f}  "
              f"median={ranked[len(ranked) // 2]:6.2f}")

    # Only fingers that were actually pressed are worth a breakdown; the rest
    # sit at the ~0.35 N noise floor.
    pressed = sorted(
        (f for f, (top, _, _) in best.items() if top >= PRESS_N),
        key=lambda f: best[f][0], reverse=True,
    )
    if focus in best and focus not in pressed:
        pressed.append(focus)

    for finger in pressed:
        top, mags, vectors = best[finger]
        ranked_idx = sorted(range(len(mags)), key=lambda i: mags[i], reverse=True)
        print(f"\npeak single frame on {finger} (max taxel {top:.2f} N) — top 12 taxels:")
        print("   idx      fx      fy      fz     |F|")
        for i in ranked_idx[:12]:
            fx, fy, fz = vectors[i]
            rail = ""
            if abs(fx) >= 12.7 or abs(fy) >= 12.7 or fz >= 25.5:
                rail = "  <- railed"
            print(f"  {i:4d}  {fx:6.1f}  {fy:6.1f}  {fz:6.1f}  {mags[i]:6.2f}{rail}")
        loaded = [m for m in mags if m > 0.3]
        print(f"\n  taxels above 0.3 N in that frame: {len(loaded)}/{len(mags)}"
              f"   sum |F| = {sum(mags):.1f} N")


if __name__ == "__main__":
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 12.0
    finger = sys.argv[2] if len(sys.argv) > 2 else "ring"
    asyncio.run(main(seconds, finger))
