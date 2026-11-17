"""The app link (``/ws/app``): the contract between the console and an app.

Single source of truth for protocol 2; ``docs/app-contract.md`` is the
human-readable copy. JSON text frames, envelope ``{type, data}``.

  app -> console
    hello     {token, proto: 2, app}                        first frame
    settings  {schema: [setting], values: {key: v}, errors: {key: text}}
    targets   {angles: {joint id: degrees}}                 partial dicts ok
    status    {tracking?: bool, info?: {label: text}}       ~1-2 Hz
    frame     {stream: name, jpeg: base64}                  <= 10 Hz per stream
    log       {line, level?}

  console -> app
    hello_ok  {session_id, proto: 2, hand: {...}, values: {key: v}}
    set       {key: value, ...}                             a user change
    engaged   {engaged: bool}
    stop      {}

A setting is ``{key, title?, type, default?, choices?, minimum?, maximum?,
help?, restart?, live?}`` with ``type`` one of SETTING_TYPES. Unknown message
types and unknown fields are ignored, so either side may add optional ones.
"""

from __future__ import annotations

import json
import math
import secrets

PROTO_VERSION = 2
HELLO_TIMEOUT_S = 5.0

MSG_HELLO = "hello"
MSG_SETTINGS = "settings"
MSG_TARGETS = "targets"
MSG_STATUS = "status"
MSG_FRAME = "frame"
MSG_LOG = "log"

MSG_HELLO_OK = "hello_ok"
MSG_SET = "set"
MSG_ENGAGED = "engaged"
MSG_STOP = "stop"

CLOSE_BAD_TOKEN = 4001
CLOSE_PROTO_MISMATCH = 4002
CLOSE_SESSION_BUSY = 4004

SETTING_TYPES = ("boolean", "integer", "number", "string", "enum")
MAX_SETTINGS = 64


class HelloRejected(Exception):
    """A ``hello`` failed validation; carries the WebSocket close code."""

    def __init__(self, message: str, close_code: int):
        super().__init__(message)
        self.close_code = close_code


def new_token() -> str:
    return secrets.token_urlsafe(16)


def check_hello(data: dict, *, token: str | None) -> str:
    """Validate a ``hello``; returns the app's name or raises HelloRejected."""
    if not token or data.get("token") != token:
        raise HelloRejected("bad or missing token", CLOSE_BAD_TOKEN)
    if data.get("proto") != PROTO_VERSION:
        raise HelloRejected(
            f"protocol mismatch (console={PROTO_VERSION}, app={data.get('proto')!r})",
            CLOSE_PROTO_MISMATCH)
    return str(data.get("app") or "app")[:64]


def hand_block(config, model_name: str) -> dict:
    """What an app needs to know about the hand it drives."""
    return {
        "model": model_name,
        "side": config.type,
        "hardware_version": config.hardware_version,
        "joints": list(config.joint_ids),
        "ranges": {j: [float(v) for v in rom]
                   for j, rom in config.joint_roms_dict.items()},
    }


def hello_ok(session_id: str, hand: dict, values: dict) -> dict:
    return {"session_id": session_id, "proto": PROTO_VERSION,
            "hand": hand, "values": dict(values)}


def clean_schema(schema) -> list[dict]:
    """The settings the console can draw, rebuilt from known fields only: the
    app is untrusted, and one odd field must not break the tab."""
    out: list[dict] = []
    seen: set[str] = set()
    for entry in _list(schema):
        if not isinstance(entry, dict):
            continue
        key = entry.get("key")
        if not isinstance(key, str) or not key or key in seen:
            continue
        kind = entry.get("type")
        if kind not in SETTING_TYPES:
            continue
        setting = {"key": key, "type": kind,
                   "restart": bool(entry.get("restart")), "live": bool(entry.get("live"))}
        for text in ("title", "help"):
            if entry.get(text) is not None:
                setting[text] = str(entry[text])
        for bound in ("minimum", "maximum"):
            if _finite_number(entry.get(bound)):
                setting[bound] = entry[bound]
        if "default" in entry and json_safe(entry["default"]):
            setting["default"] = entry["default"]
        if kind == "enum":
            choices = [{"value": c["value"], "title": str(c.get("title", c["value"]))}
                       for c in _list(entry.get("choices"))
                       if isinstance(c, dict) and "value" in c and json_safe(c["value"])]
            if not choices:
                continue
            setting["choices"] = choices
        seen.add(key)
        out.append(setting)
        if len(out) >= MAX_SETTINGS:
            break
    return out


def clean_values(values) -> dict:
    """Setting values the console can keep and publish: anything holding NaN
    or Infinity (which Python's json reads) would break every strict send."""
    if not isinstance(values, dict):
        return {}
    return {str(k): v for k, v in values.items() if json_safe(v)}


def json_safe(value) -> bool:
    """True when ``value`` survives strict JSON: no NaN or Infinity anywhere."""
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError):
        return False
    return True


def _finite_number(value) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def _list(value) -> list:
    return value if isinstance(value, list) else []


def finite_angles(angles) -> dict[str, float]:
    """Drop non-numeric and non-finite values from a ``targets`` payload."""
    out: dict[str, float] = {}
    for joint, value in (angles.items() if isinstance(angles, dict) else ()):
        try:
            v = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(v):
            out[str(joint)] = v
    return out
