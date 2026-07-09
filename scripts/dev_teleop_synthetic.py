"""Dev helper: drive the teleop ingress with synthetic waveform targets.

Starts an *external-mode* teleop session on a running orca-ui server, connects
to ``/ws/teleop`` as if it were the orca_teleop streamer child, and streams a
smooth per-joint sine wave. Lets you exercise the whole teleop UI (preview
ghost, engage/ramp, tracking loss, disengage) with zero teleop hardware:

    uv run orca-ui --mock                # terminal 1
    uv run python scripts/dev_teleop_synthetic.py   # terminal 2

Press Ctrl-C to stop (the UI sees a clean session stop). Pause frames with
SIGSTOP/typing 'p'+Enter to watch the tracking-lost watchdog trip.
"""

from __future__ import annotations

import argparse
import json
import math
import select
import sys
import time
import urllib.request

from websockets.sync.client import connect


def api(base: str, path: str, payload: dict | None = None) -> dict:
    request = urllib.request.Request(
        base + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Content-Type": "application/json"},
        method="POST" if payload is not None else "GET",
    )
    with urllib.request.urlopen(request) as response:
        return json.loads(response.read())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--url", default="http://127.0.0.1:5001",
                        help="orca-ui base URL (default: %(default)s)")
    parser.add_argument("--rate", type=float, default=30.0,
                        help="target frames per second (default: %(default)s)")
    parser.add_argument("--freq", type=float, default=0.2,
                        help="waveform frequency in Hz (default: %(default)s)")
    parser.add_argument("--amplitude", type=float, default=0.35,
                        help="waveform amplitude as a fraction of each "
                             "joint's half-ROM (default: %(default)s)")
    args = parser.parse_args()

    started = api(args.url, "/api/teleop/start",
                  {"source": "synthetic", "mode": "external"})
    token = started["token"]
    print(f"session {started['session']['session_id']} started (external)")

    ws_url = args.url.replace("http", "ws", 1) + "/ws/teleop"
    with connect(ws_url) as ws:
        ws.send(json.dumps({"type": "hello", "data": {
            "token": token, "proto": 1, "source": "synthetic",
            "hand": {"model_name": "dev-synthetic", "side": None},
        }}))
        hello_ok = json.loads(ws.recv())
        assert hello_ok["type"] == "hello_ok", hello_ok
        joints = hello_ok["data"]["joints"]
        roms = hello_ok["data"]["roms"]
        print(f"connected — {len(joints)} joints, streaming at {args.rate} Hz "
              f"(type 'p'+Enter to pause frames, Ctrl-C to quit)")

        paused = False
        t0 = time.monotonic()
        next_status = 0.0
        seq = 0
        try:
            while True:
                # non-blocking inbound: config/engaged/stop + pause toggle
                try:
                    while True:
                        message = json.loads(ws.recv(timeout=0))
                        print(f"<- {message['type']}: {message.get('data')}")
                        if message["type"] == "stop":
                            return
                except TimeoutError:
                    pass
                if select.select([sys.stdin], [], [], 0)[0]:
                    if sys.stdin.readline().strip().lower() == "p":
                        paused = not paused
                        print("paused — frames withheld" if paused
                              else "resumed")

                now = time.monotonic() - t0
                if not paused:
                    angles = {}
                    for index, joint in enumerate(joints):
                        lo, hi = roms[joint]
                        mid = (lo + hi) / 2.0
                        half = (hi - lo) / 2.0
                        phase = index * 0.7
                        angles[joint] = mid + args.amplitude * half * math.sin(
                            2 * math.pi * args.freq * now + phase)
                    seq += 1
                    ws.send(json.dumps({"type": "targets", "data": {
                        "angles": angles, "seq": seq}}))
                if now >= next_status:
                    ws.send(json.dumps({"type": "status", "data": {
                        "ingress_fps": args.rate if not paused else 0.0,
                        "tracking": not paused,
                        "retarget_ms": 0.1,
                    }}))
                    next_status = now + 1.0
                time.sleep(1.0 / args.rate)
        except KeyboardInterrupt:
            pass
        finally:
            try:
                api(args.url, "/api/teleop/stop", {})
                print("\nsession stopped")
            except Exception:
                pass


if __name__ == "__main__":
    main()
