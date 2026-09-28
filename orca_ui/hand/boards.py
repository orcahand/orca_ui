"""Board inventory and board-pinned detection — which hand this console owns.

One console normally takes whatever board answers first, which is right for a
bench with one hand. With two hands on one machine (one console per hand),
first-to-answer is a coin toss, so the operator pins a board: a pinned
supervisor probes and opens only that board's CDCs and never touches another
hand's ports, and :func:`scan_boards` feeds the picker that offers the choice.

The pin key is a device path — the motor CDC of an ORCA controller board, or
the adapter path of a legacy motor adapter. The board's identity reply
(hand serial, falling back to the MCU id) is what groups its two CDCs
together and what keeps a pinned console off everything else.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from orca_core import HandDetection
from orca_core.hand_factory import (
    SENSING_CONFIG_CAPS,
    _classic_motor_ports,
    _MODEL_BY_CAPS,
)
from orca_core.hardware.sensing.constants import DEFAULT_ENCODER_BAUDRATE
from orca_core.hardware.sensing.serial_discovery import (
    OrcaBoardInfo,
    _tactile_responds_at,
    detect_encoder_stream,
    oh_board_ports,
    port_in_use,
    probe_orca_info,
)

_PROBE_PASSES = 3
"""Identity-probe passes; the probe is racy on macOS composite CDC devices
(same allowance orca_core's detect_hand makes)."""


@dataclass(frozen=True)
class BoardEntry:
    """One selectable board: an ORCA controller board (both CDCs grouped by
    the identity they report) or a legacy motor adapter (VID-matched only).

    ``device`` is the pin key. ``busy`` means the ports stayed silent but are
    held open by some process — which includes this console's own session;
    the service layer overlays which ports are ours.
    """

    device: str
    kind: str  # "oh_board" | "motor_adapter"
    side: Optional[str]
    hand_id: Optional[str]
    model_name: Optional[str]  # from the provisioned CFG code, when declared
    ports: tuple[str, ...]
    busy: bool

    def as_dict(self) -> dict:
        return {
            "device": self.device,
            "kind": self.kind,
            "side": self.side,
            "hand_id": self.hand_id,
            "model_name": self.model_name,
            "ports": list(self.ports),
            "busy": self.busy,
        }


def _declared_model(info: OrcaBoardInfo) -> Optional[str]:
    caps = SENSING_CONFIG_CAPS.get(info.config) if info.config else None
    if caps is None:
        return None
    return _MODEL_BY_CAPS[caps].format(side=info.side or "right")


def scan_boards() -> list[BoardEntry]:
    """Every board on this machine, identified where possible.

    Probes only ports nothing holds open: a CDC in use — another console's,
    or our own session's — is listed busy and unidentified rather than
    disturbed.
    """
    candidates = list(oh_board_ports())
    infos: dict[str, OrcaBoardInfo] = {}
    unanswered = set(candidates)
    for _ in range(_PROBE_PASSES):
        for port in sorted(unanswered):
            info = probe_orca_info(port)
            if info is not None:
                infos[port] = info
                unanswered.discard(port)
        if not unanswered:
            break

    # Group one board's CDCs by the identity both report. A board without an
    # id (legacy firmware) can only be grouped when it is unambiguous: one
    # id-less motor CDC and one id-less sensor CDC on the whole machine.
    groups: dict[str, dict] = {}
    for port, info in infos.items():
        key = info.hand_id or f"anon:{info.role}:{port}"
        group = groups.setdefault(key, {"motor": None, "sensor": None,
                                        "info": info})
        group[info.role] = port
        if info.side and not group["info"].side:
            group["info"] = info
    anon = [key for key in groups if key.startswith("anon:")]
    if len(anon) == 2:
        a, b = (groups[key] for key in anon)
        if a["motor"] and b["sensor"] and not (a["sensor"] or b["motor"]):
            a["sensor"] = b["sensor"]
            del groups[anon[1]]
        elif b["motor"] and a["sensor"] and not (b["sensor"] or a["motor"]):
            b["sensor"] = a["sensor"]
            del groups[anon[0]]

    entries = []
    for group in groups.values():
        info: OrcaBoardInfo = group["info"]
        device = group["motor"] or group["sensor"]
        ports = tuple(p for p in (group["motor"], group["sensor"]) if p)
        entries.append(BoardEntry(
            device=device, kind="oh_board", side=info.side,
            hand_id=info.hand_id, model_name=_declared_model(info),
            ports=ports, busy=False))
    for port in sorted(unanswered):
        entries.append(BoardEntry(
            device=port, kind="oh_board", side=None, hand_id=None,
            model_name=None, ports=(port,), busy=port_in_use(port)))
    for port in _classic_motor_ports():
        if port in candidates:
            continue
        entries.append(BoardEntry(
            device=port, kind="motor_adapter", side=None, hand_id=None,
            model_name=None, ports=(port,), busy=port_in_use(port)))
    entries.sort(key=lambda entry: entry.device)
    return entries


def _find_mate(pin: str, info: OrcaBoardInfo) -> tuple[Optional[str], list[str]]:
    """The pinned board's other CDC, plus the ports that probed busy.

    An id match is required whenever the pinned CDC has one. Without an id
    (legacy firmware) only a lone id-less opposite-role candidate is safe —
    with two id-less boards there is no telling whose CDC it would be.
    """
    busy: list[str] = []
    matches: list[str] = []
    others = [p for p in oh_board_ports() if p != pin]
    for _ in range(_PROBE_PASSES):
        for port in others:
            if port in matches or port in busy:
                continue
            other = probe_orca_info(port)
            if other is None:
                if port_in_use(port):
                    busy.append(port)
                continue
            if other.role == info.role:
                continue
            if info.hand_id:
                if other.hand_id == info.hand_id:
                    matches.append(port)
            elif not other.hand_id:
                matches.append(port)
        if matches:
            break
    if info.hand_id:
        mate = matches[0] if matches else None
    else:
        mate = matches[0] if len(matches) == 1 else None
    return mate, busy


def detect_pinned_board(pin: str) -> Optional[HandDetection]:
    """Probe only the pinned board and name what it is.

    The scoped counterpart of orca_core's ``detect_hand()``: with a board
    pinned the console must never open — let alone connect — another hand's
    ports, so discovery starts at the pinned device and widens only to the
    CDC reporting the same identity. Returns ``None`` when the pinned device
    is absent, silent, or held by another process; callers decide how loudly
    to say so and must not fall back to a global probe.
    """
    info: Optional[OrcaBoardInfo] = None
    for _ in range(_PROBE_PASSES):
        info = probe_orca_info(pin)
        if info is not None:
            break
    if info is None:
        if pin not in oh_board_ports() and pin in _classic_motor_ports() \
                and not port_in_use(pin):
            # A legacy adapter has no identity to answer with; being openable
            # and VID-matched is all the confirmation there is. It resolves
            # to the default model, exactly as global detection would.
            return HandDetection(
                model_name=_MODEL_BY_CAPS[(False, False)].format(side="right"),
                side="right", has_tactile=False, has_encoders=False,
                motor_port=pin)
        return None

    mate, busy = _find_mate(pin, info)
    if info.role == "motor":
        motor_port, sensing_port = pin, mate
    else:
        motor_port, sensing_port = mate, pin

    probed_encoders = (sensing_port is not None
                       and detect_encoder_stream(sensing_port))
    # A dedicated tactile adapter is machine-global and can't be tied to one
    # board, so scoped detection only reads tactile on the shared CDC.
    probed_tactile = (sensing_port is not None
                      and _tactile_responds_at(sensing_port,
                                               DEFAULT_ENCODER_BAUDRATE))

    declared = SENSING_CONFIG_CAPS.get(info.config) if info.config else None
    has_tactile, has_encoders = (
        declared if declared is not None else (probed_tactile, probed_encoders))
    probed = {"tactile": probed_tactile, "encoders": probed_encoders}
    declared_caps = {"tactile": has_tactile, "encoders": has_encoders}
    side = info.side or "right"
    return HandDetection(
        model_name=_MODEL_BY_CAPS[(has_tactile, has_encoders)].format(side=side),
        side=side,
        has_tactile=has_tactile,
        has_encoders=has_encoders,
        motor_port=motor_port,
        sensing_port=sensing_port,
        identity=info,
        busy_ports=tuple(busy),
        declared_config=info.config,
        probed_tactile=probed_tactile,
        probed_encoders=probed_encoders,
        missing_capabilities=tuple(
            n for n, on in declared_caps.items() if on and not probed[n]),
        undeclared_capabilities=tuple(
            n for n, on in probed.items() if on and not declared_caps[n]),
    )
