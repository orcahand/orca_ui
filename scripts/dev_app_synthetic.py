"""A synthetic app for the console: speaks the app contract (protocol 2) and
streams a smooth sine wave on every joint. Exercises a whole app tab (settings,
ghost, picture tile, engage and ramp, holds, disengage) with no camera or policy.

Run it the way the console runs an app: set the Teleop or RL tab's command to

    <orca_ui>/.venv/bin/python <orca_ui>/scripts/dev_app_synthetic.py

and press Start. Or start it by hand against a running console, which opens
an external session for it:

    uv run orca-ui --mock                                  # terminal 1
    uv run python scripts/dev_app_synthetic.py --app rl    # terminal 2

Its "tracking" setting is live, so you can watch the hold and auto-disengage
rules trip from the tab.
"""

from __future__ import annotations

import argparse
import json
import math
import time
import urllib.request

from websockets.sync.client import connect

# A plain 32x18 JPEG, so the picture tile has something to show.
FRAME_JPEG = (
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDACgcHiMeGSgjISMtKygwPGRBPDc3PHtYXUlkkYCZlo+"
    "AjIqgtObDoKrarYqMyP/L2u71////m8H////6/+b9//j/2wBDASstLTw1PHZBQXb4pYyl+Pj4+Pj4"
    "+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+Pj4+Pj/wAARCAASACADASIA"
    "AhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAL/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFgEB"
    "AQEAAAAAAAAAAAAAAAAAAAME/8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAwDAQACEQMRAD8AgBVl"
    "AAAAAAf/2Q=="
)

SCHEMA = [
    {"key": "amplitude", "title": "Amplitude", "type": "number", "default": 0.35,
     "minimum": 0.0, "maximum": 1.0, "live": True,
     "help": "fraction of each joint's half range"},
    {"key": "frequency_hz", "title": "Frequency (Hz)", "type": "number",
     "default": 0.2, "minimum": 0.05, "maximum": 2.0, "live": True},
    {"key": "tracking", "title": "Tracking", "type": "boolean", "default": True,
     "live": True, "help": "off: report tracking lost and stop sending targets"},
    {"key": "rate_hz", "title": "Target rate (Hz)", "type": "integer", "default": 30,
     "minimum": 1, "maximum": 100, "restart": True},
    {"key": "pattern", "title": "Pattern", "type": "enum", "default": "wave",
     "choices": [{"value": "wave", "title": "Wave"}, {"value": "fist", "title": "Slow fist"}]},
]


def check(values: dict) -> tuple[dict, dict]:
    """Apply a settings change; returns (applied values, errors)."""
    applied, errors = {}, {}
    for setting in SCHEMA:
        key = setting["key"]
        value = values.get(key, setting["default"])
        if setting["type"] in ("number", "integer"):
            try:
                value = int(value) if setting["type"] == "integer" else float(value)
            except (TypeError, ValueError):
                errors[key] = "not a number"
                value = setting["default"]
            if not setting["minimum"] <= value <= setting["maximum"]:
                errors[key] = f"between {setting['minimum']} and {setting['maximum']}"
                value = setting["default"]
        elif setting["type"] == "boolean":
            value = bool(value)
        elif setting["type"] == "enum" and value not in [c["value"] for c in setting["choices"]]:
            errors[key] = "not a choice"
            value = setting["default"]
        applied[key] = value
    return applied, errors


def send(ws, kind: str, data: dict) -> None:
    ws.send(json.dumps({"type": kind, "data": data}))


def external_session(url: str, app: str) -> tuple[str, str]:
    request = urllib.request.Request(
        url + "/api/app/start", method="POST",
        data=json.dumps({"app": app, "mode": "external"}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request) as response:
        token = json.loads(response.read())["token"]
    return url.replace("http", "ws", 1) + "/ws/app", token


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--connect", help="app link URL (the console passes it)")
    parser.add_argument("--token", help="session token (the console passes it)")
    parser.add_argument("--url", default="http://127.0.0.1:5001",
                        help="console to open an external session on (default: %(default)s)")
    parser.add_argument("--app", default="teleop", help="tab to run in (default: %(default)s)")
    args = parser.parse_args()

    link, token = (args.connect, args.token) if args.connect else external_session(args.url, args.app)
    with connect(link) as ws:
        send(ws, "hello", {"token": token, "proto": 2, "app": "synthetic"})
        reply = json.loads(ws.recv())
        if reply.get("type") != "hello_ok":
            raise SystemExit(f"refused: {reply}")
        hand = reply["data"]["hand"]
        values, errors = check(reply["data"].get("values") or {})
        send(ws, "settings", {"schema": SCHEMA, "values": values, "errors": errors})
        send(ws, "log", {"line": f"driving {hand['model']} ({len(hand['joints'])} joints)"})

        t0 = time.monotonic()
        next_status = next_frame = 0.0
        while True:
            try:
                while True:
                    message = json.loads(ws.recv(timeout=0))
                    if message["type"] == "stop":
                        return
                    if message["type"] == "set":
                        values, errors = check({**values, **message["data"]})
                        send(ws, "settings", {"schema": SCHEMA, "values": values, "errors": errors})
                    if message["type"] == "engaged":
                        send(ws, "log", {"line": f"engaged: {message['data']['engaged']}"})
            except TimeoutError:
                pass

            now = time.monotonic() - t0
            if values["tracking"]:
                angles = {}
                for index, joint in enumerate(hand["joints"]):
                    lo, hi = hand["ranges"][joint]
                    phase = 0.0 if values["pattern"] == "fist" else index * 0.7
                    wave = math.sin(2 * math.pi * values["frequency_hz"] * now + phase)
                    angles[joint] = (lo + hi) / 2 + values["amplitude"] * (hi - lo) / 2 * wave
                send(ws, "targets", {"angles": angles})
            if now >= next_status:
                send(ws, "status", {"tracking": values["tracking"],
                                    "info": {"Pattern": values["pattern"],
                                             "Rate": f"{values['rate_hz']} Hz"}})
                next_status = now + 0.5
            if now >= next_frame:
                send(ws, "frame", {"stream": "camera", "jpeg": FRAME_JPEG})
                next_frame = now + 0.2
            time.sleep(1.0 / values["rate_hz"])


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
