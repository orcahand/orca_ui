"""Wire contract for the teleop ingress socket (``/ws/teleop``).

This module is the single source of truth for the protocol between orca_ui
and the orca_teleop streamer child. The streamer mirrors these constants; any
change here is a cross-repo protocol change and bumps ``PROTO_VERSION``.

JSON text frames, envelope ``{type, data}``.

  child -> ui
    hello    {token, proto, source, hand: {model_name, side}, pid?, versions?}
    targets  {angles: {bare_joint_id: degrees}, seq?, t?}     (partial dicts ok)
    status   {ingress_fps?, tracking?, retarget_ms?, calibrating?}   ~2 Hz
    log      {level?, line}
    preview  {jpeg: <base64>, seq?}          only while config.preview is true

  ui -> child
    hello_ok {session_id, proto, joints, roms, neutral, engaged}
    config   partial config, e.g. {manual_wrist_deg: 10.0, preview: true}
    engaged  {engaged: bool}                 child resets smoothing on flips
    stop     {}
"""

from __future__ import annotations

import secrets

PROTO_VERSION = 1

HELLO_TIMEOUT_S = 5.0

# child -> ui message types
MSG_HELLO = "hello"
MSG_TARGETS = "targets"
MSG_STATUS = "status"
MSG_LOG = "log"
MSG_PREVIEW = "preview"

# ui -> child message types
MSG_HELLO_OK = "hello_ok"
MSG_CONFIG = "config"
MSG_ENGAGED = "engaged"
MSG_STOP = "stop"

# WebSocket close codes for a rejected ingress connection.
CLOSE_BAD_TOKEN = 4001
CLOSE_PROTO_MISMATCH = 4002
CLOSE_HAND_MISMATCH = 4003
CLOSE_SESSION_BUSY = 4004

SOURCES = ("mediapipe", "manus", "avp", "synthetic")


class HelloRejected(Exception):
    """Raised when a ``hello`` frame fails validation; carries the WS close code."""

    def __init__(self, message: str, close_code: int):
        super().__init__(message)
        self.close_code = close_code


def new_token() -> str:
    return secrets.token_urlsafe(16)


def validate_hello(data: dict, *, token: str | None, expected_side: str) -> dict:
    """Validate a ``hello`` payload against the active session.

    Returns the parsed hello (source, hand, pid) or raises
    :class:`HelloRejected` with the close code the endpoint should use.
    """
    if not token or data.get("token") != token:
        raise HelloRejected("bad or missing token", CLOSE_BAD_TOKEN)
    if data.get("proto") != PROTO_VERSION:
        raise HelloRejected(
            f"protocol mismatch (ui={PROTO_VERSION}, child={data.get('proto')!r})",
            CLOSE_PROTO_MISMATCH)
    source = data.get("source")
    if source not in SOURCES:
        raise HelloRejected(f"unknown source {source!r}", CLOSE_PROTO_MISMATCH)
    hand = data.get("hand") or {}
    side = hand.get("side")
    if side and side != expected_side:
        raise HelloRejected(
            f"hand side mismatch (ui={expected_side!r}, child={side!r})",
            CLOSE_HAND_MISMATCH)
    return {
        "source": source,
        "hand": {"model_name": hand.get("model_name"), "side": side},
        "pid": data.get("pid"),
        "versions": data.get("versions") or {},
    }


def hello_ok_payload(session_id: str, config,
                     session_config: dict | None = None) -> dict:
    """The ack sent back after a valid hello. Echoes the hand's joint set and
    ROMs so the child can warn loudly on a split-brain model mismatch.

    ``session_config`` carries the config accumulated BEFORE the child
    connected (e.g. the browser enabling the camera preview while the child
    was still starting) — the child applies it like a ``config`` message.
    """
    return {
        "session_id": session_id,
        "proto": PROTO_VERSION,
        "joints": list(config.joint_ids),
        "roms": {j: [float(v) for v in rom]
                 for j, rom in config.joint_roms_dict.items()},
        "neutral": {j: float(v) for j, v in config.neutral_position.items()},
        "engaged": False,
        "config": dict(session_config or {}),
    }


def config_to_argv(source: str, config: dict) -> list[str]:
    """Map a session config dict onto streamer CLI flags (managed spawn).

    Owned here so the manager/runner never re-derive the flag names — this is
    the same contract file the streamer mirrors.
    """
    argv = ["--source", source]
    flag_map = {
        "camera_index": "--camera-index",
        "zmq_addr": "--zmq-addr",
        "avp_ip": "--avp-ip",
        "retargeter": "--retargeter",
        "rate": "--rate",
        "manual_wrist_deg": "--wrist-angle",
    }
    for key, flag in flag_map.items():
        value = config.get(key)
        if value is not None and value != "":
            argv += [flag, str(value)]
    return argv
