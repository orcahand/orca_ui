"""Finger control for the motor bench: fingers mounted on the bench motors,
each joint a linear combination of motors with a captured range, driven from
sliders.

Nothing on the bench is calibrated, so a joint here is the operator's: a
name, the tendons that move it — each with a gain in joint degrees per
shaft degree, so the joint angle is the sum of gain × shaft angle over its
terms — and a range in joint degrees captured at its open and closed ends.
The page keeps a tendon list beside the joints (a name and the motor it is
wound on), so that terms name tendons and a motor can be reassigned in one
place; the run itself takes terms resolved to motors. A joint on one motor with gain 1 is the plain case: joint degrees are
shaft degrees. Routed tendons make joints share motors: an MCP/PIP pair
read as a sum and a difference of two shafts is two joints whose terms name
the same two motors. Joints that share motors form a coupling, and a
coupling must be square and invertible — as many motors as joints, each
pose reachable one way — so that the run can go from joint targets to shaft
commands and back from shaft readings to joint angles. The page keeps the setup beside the
bench config (``GET``/``PUT /api/fingers/setup``), so fingers mounted
yesterday come back mounted.

Driving is an operation, so it owns the bus and the control source like any
run. While engaged, the joints glide in joint space toward the targets the
page sends (``POST /api/fingers/targets``): one fraction per joint, 0 open to
1 closed, clamped to that, and the motors are written wherever the coupling
puts them. Nothing moves until every motor in play is held; the motor travel
the ranges imply is checked at the corners of the range box before anything
is written; the e-stop ends the run like any other; on exit the motors are
left held where they are.
"""

from __future__ import annotations

import math
import os
import re
import threading
import time

import numpy as np

from orca_ui.bench import assignments_of
from orca_ui.hand.operations.base import OpContext, Operation
from orca_ui.hand.operations.bench import (MIN_TRAVEL_DEG, _deg, _finite,
                                           check_shaft_range)
from orca_ui.hand.states import ControlSource

STREAM_HZ = 50.0
SAMPLE_PERIOD_S = 0.1
PUBLISH_PERIOD_S = 0.1
DEFAULT_SPEED_DEG_S = 360.0
MIN_SPEED_DEG_S, MAX_SPEED_DEG_S = 1.0, 2000.0
MAX_JOINTS = 32
# Joints coupled through shared motors; the range box has 2**n corners.
MAX_COUPLED = 6
MAX_GAIN = 100.0
SINGULAR_COND = 1e6
NAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_ .-]{0,31}$")

SETUP_FILE = "finger_setup.yaml"
SETUP_KEYS = ("tendons", "joints", "zeros", "settings")


# ----- the remembered setup ---------------------------------------------------


def setup_path(settings) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(settings.config_path)),
                        SETUP_FILE)


def load_setup(settings) -> dict:
    import yaml

    path = setup_path(settings)
    data: dict = {}
    if os.path.isfile(path):
        try:
            with open(path) as f:
                data = yaml.safe_load(f) or {}
        except Exception:
            data = {}
    return {key: data.get(key) for key in SETUP_KEYS}


def _clean_terms(raw, who: str) -> list[dict]:
    """Terms name a motor (``{motor, gain}``, what the run takes) or a tendon
    (``{tendon, gain}``, what the file keeps until the page resolves it)."""
    from orca_ui.hand.service import ServiceError

    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ServiceError(who + "terms must be a list of {motor | tendon, gain}")
    out: list[dict] = []
    seen: set = set()
    for term in raw:
        if not isinstance(term, dict):
            raise ServiceError(who + "each term is {motor | tendon, gain}")
        try:
            gain = _finite(term.get("gain", 1.0))
            if term.get("tendon") is not None:
                key = str(term["tendon"]).strip()
                if not NAME_RE.match(key):
                    raise ValueError
                clean = {"tendon": key, "gain": gain}
            else:
                key = int(term["motor"])
                clean = {"motor": key, "gain": gain}
        except (KeyError, TypeError, ValueError):
            raise ServiceError(who + "each term needs a tendon name or an integer motor "
                               "id, and a finite gain")
        if key in seen:
            raise ServiceError(who + f"{key} is listed twice")
        if gain == 0 or abs(gain) > MAX_GAIN:
            raise ServiceError(who + f"the gain on {key} must be nonzero and at most "
                               f"{MAX_GAIN:g} joint degrees per shaft degree")
        seen.add(key)
        out.append(clean)
    return out


def clean_tendons(raw) -> list[dict]:
    from orca_ui.hand.service import ServiceError

    if not isinstance(raw, list):
        raise ServiceError("tendons must be a list of {name, motor}")
    if len(raw) > MAX_JOINTS:
        raise ServiceError(f"at most {MAX_JOINTS} tendons")
    out: list[dict] = []
    names: set[str] = set()
    motors: set[int] = set()
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise ServiceError("each tendon is {name, motor}")
        name = str(entry.get("name") or "").strip()
        if not NAME_RE.match(name):
            raise ServiceError(f"tendon {i + 1}: the name must be 1–32 letters, "
                               "digits, spaces, dots, dashes or underscores")
        if name.lower() in names:
            raise ServiceError(f"tendon {name!r} is listed twice")
        names.add(name.lower())
        motor = entry.get("motor")
        if motor is not None:
            try:
                motor = int(motor)
            except (TypeError, ValueError):
                raise ServiceError(f"tendon {name!r}: motor must be an integer id or null")
            if motor in motors:
                raise ServiceError(f"motor {motor} is wound with two tendons")
            motors.add(motor)
        out.append({"name": name, "motor": motor})
    return out


def _clean_joint(entry, index: int) -> dict:
    from orca_ui.hand.service import ServiceError

    if not isinstance(entry, dict):
        raise ServiceError("each joint is {name, terms, open_deg, closed_deg, group?}")
    name = str(entry.get("name") or "").strip()
    if not NAME_RE.match(name):
        raise ServiceError(f"joint {index + 1}: the name must be 1–32 letters, "
                           "digits, spaces, dots, dashes or underscores")
    who = f"joint {name!r}: "
    terms = _clean_terms(entry.get("terms"), who)
    ends = {}
    for key in ("open_deg", "closed_deg"):
        value = entry.get(key)
        if value is not None:
            try:
                value = _finite(value)
            except ValueError:
                raise ServiceError(who + f"{key} must be a number or null")
        ends[key] = value
    group = str(entry.get("group") or "").strip()[:32]
    return {"name": name, "terms": terms, "group": group, **ends}


def clean_joints(raw) -> list[dict]:
    """Validate the shape of a joint list: unique names, well-formed terms.
    Whether the motors exist is the bus's business, not the file's."""
    from orca_ui.hand.service import ServiceError

    if not isinstance(raw, list):
        raise ServiceError("joints must be a list")
    if len(raw) > MAX_JOINTS:
        raise ServiceError(f"at most {MAX_JOINTS} joints")
    out: list[dict] = []
    names: set[str] = set()
    for i, entry in enumerate(raw):
        joint = _clean_joint(entry, i)
        key = joint["name"].lower()
        if key in names:
            raise ServiceError(f"joint {joint['name']!r} is listed twice")
        names.add(key)
        out.append(joint)
    return out


def clean_zeros(raw) -> dict[int, float]:
    """Shaft positions (degrees) at which every joint reads zero."""
    from orca_ui.hand.service import ServiceError

    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ServiceError("zeros must be {motor id: shaft degrees}")
    out: dict[int, float] = {}
    for motor, value in raw.items():
        try:
            out[int(motor)] = _finite(value)
        except (TypeError, ValueError):
            raise ServiceError("zeros must be {motor id: shaft degrees}")
    return out


class Coupling:
    """Joints that share motors, with the square map between them:
    ``q = B · (shaft − zero)`` as the terms give it, and its inverse
    ``shaft = zero + A · q`` for driving (degrees both sides)."""

    def __init__(self, joints: list[dict], zeros: dict[int, float]):
        from orca_ui.hand.service import ServiceError

        self.joints = joints
        self.names = [j["name"] for j in joints]
        self.motors = sorted({t["motor"] for j in joints for t in j["terms"]})
        who = " + ".join(self.names)
        if len(self.motors) != len(self.joints):
            raise ServiceError(
                f"{who}: {len(self.joints)} joint(s) on {len(self.motors)} motor(s) — "
                "joints that share motors must be as many as the motors they share")
        if len(self.joints) > MAX_COUPLED:
            raise ServiceError(f"{who}: at most {MAX_COUPLED} joints may be coupled")
        self.B = np.zeros((len(self.joints), len(self.motors)))
        for j, joint in enumerate(joints):
            for term in joint["terms"]:
                self.B[j, self.motors.index(term["motor"])] = term["gain"]
        if np.linalg.cond(self.B) > SINGULAR_COND:
            raise ServiceError(
                f"{who}: the coupling is singular — these joints cannot be moved "
                "independently with these gains")
        self.A = np.linalg.inv(self.B)
        self.zero = np.array([zeros.get(m, 0.0) for m in self.motors])

    def shaft_of(self, q: np.ndarray) -> np.ndarray:
        return self.zero + self.A @ q

    def q_of(self, shaft: np.ndarray) -> np.ndarray:
        return self.B @ (shaft - self.zero)

    def shaft_extremes(self, lo: np.ndarray, hi: np.ndarray) -> list[tuple[float, float]]:
        """Per motor, the least and the most shaft travel any pose in the
        joint range box asks for — the map is linear, so at the corners."""
        corners = np.array(np.meshgrid(*zip(lo, hi), indexing="ij")).reshape(len(lo), -1)
        shafts = self.zero[:, None] + self.A @ corners
        return [(float(row.min()), float(row.max())) for row in shafts]


def couplings_of(joints: list[dict], zeros: dict[int, float]) -> list[Coupling]:
    """Group joints by shared motors (transitively) and build each map."""
    from orca_ui.hand.service import ServiceError

    parent = list(range(len(joints)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    owner: dict[int, int] = {}
    for i, joint in enumerate(joints):
        if not joint["terms"]:
            raise ServiceError(f"joint {joint['name']!r}: no motor assigned")
        for term in joint["terms"]:
            if term["motor"] in owner:
                parent[find(i)] = find(owner[term["motor"]])
            else:
                owner[term["motor"]] = i
    groups: dict[int, list[dict]] = {}
    for i, joint in enumerate(joints):
        groups.setdefault(find(i), []).append(joint)
    return [Coupling(members, zeros) for members in groups.values()]


def save_setup(settings, body: dict) -> dict:
    import yaml

    from orca_ui.hand.service import ServiceError

    clean: dict = {}
    if body.get("tendons") is not None:
        clean["tendons"] = clean_tendons(body["tendons"])
    if body.get("joints") is not None:
        clean["joints"] = clean_joints(body["joints"])
    if body.get("zeros") is not None:
        clean["zeros"] = {str(m): v for m, v in clean_zeros(body["zeros"]).items()}
    if body.get("settings") is not None:
        if not isinstance(body["settings"], dict):
            raise ServiceError("settings must be an object")
        clean["settings"] = body["settings"]
    current = {k: v for k, v in load_setup(settings).items() if v is not None}
    current.update(clean)
    with open(setup_path(settings), "w") as f:
        yaml.safe_dump(current, f, sort_keys=False)
    return {key: current.get(key) for key in SETUP_KEYS}


# ----- named presets ----------------------------------------------------------------
#
# The setup file is the hand on the bench now and follows every edit. A
# preset is a copy of it under a name, so a hand that was set up once can be
# brought back after another has been on the bench.

PRESET_DIR = "finger_presets"
PRESET_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_ .-]{0,63}$")


def presets_dir(settings) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(settings.config_path)), PRESET_DIR)


def _preset_path(settings, name: str) -> str:
    from orca_ui.hand.service import ServiceError

    name = str(name).strip()
    if not PRESET_RE.match(name):
        raise ServiceError("a preset name is 1–64 letters, digits, spaces, dots, "
                           "dashes or underscores")
    return os.path.join(presets_dir(settings), f"{name}.yaml")


def list_presets(settings) -> dict:
    directory = presets_dir(settings)
    names = []
    if os.path.isdir(directory):
        for entry in sorted(os.listdir(directory)):
            if entry.endswith(".yaml"):
                names.append({"name": entry[:-5],
                              "saved_at": os.path.getmtime(os.path.join(directory, entry))})
    return {"presets": names}


def save_preset(settings, name: str) -> dict:
    import yaml

    path = _preset_path(settings, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    current = {k: v for k, v in load_setup(settings).items() if v is not None}
    with open(path, "w") as f:
        yaml.safe_dump(current, f, sort_keys=False)
    return list_presets(settings)


def load_preset(settings, name: str) -> dict:
    """Make the preset the setup in force; returns the setup as the page reads it."""
    import yaml

    from orca_ui.hand.service import ServiceError

    path = _preset_path(settings, name)
    if not os.path.isfile(path):
        raise ServiceError(f"no preset {name!r}", status_code=404)
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    body = {key: data.get(key) for key in SETUP_KEYS}
    # Validated like any PUT, so a hand-edited file cannot smuggle a bad shape in.
    with open(setup_path(settings), "w") as f:
        yaml.safe_dump({}, f)
    return save_setup(settings, {k: v for k, v in body.items() if v is not None})


def delete_preset(settings, name: str) -> dict:
    from orca_ui.hand.service import ServiceError

    path = _preset_path(settings, name)
    if not os.path.isfile(path):
        raise ServiceError(f"no preset {name!r}", status_code=404)
    os.remove(path)
    return list_presets(settings)


# ----- the operation --------------------------------------------------------------


class _Joint:
    """One joint: its range in joint degrees and the command gliding to the target."""

    def __init__(self, spec: dict):
        self.name: str = spec["name"]
        self.motors = [t["motor"] for t in spec["terms"]]
        self.open = float(spec["open_deg"])
        self.closed = float(spec["closed_deg"])
        self.target = 0.0        # fraction, 0 open .. 1 closed
        self.cmd = self.open     # joint degrees last commanded
        self.position: float | None = None   # joint degrees, from the shafts
        self.current: float | None = None    # mA, summed over its motors

    @property
    def span(self) -> float:
        return self.closed - self.open

    def deg_of(self, fraction: float) -> float:
        return self.open + fraction * self.span

    def fraction_of(self, deg: float) -> float:
        return min(1.0, max(0.0, (deg - self.open) / self.span))

    def begin(self, position: float) -> None:
        self.position = position
        self.target = self.fraction_of(position)
        self.cmd = self.deg_of(self.target)

    def tick(self, step_deg: float) -> bool:
        """Glide the command toward the target by at most ``step_deg``."""
        goal = self.deg_of(self.target)
        delta = goal - self.cmd
        if abs(delta) < 1e-6:
            return False
        self.cmd = goal if abs(delta) <= step_deg else self.cmd + math.copysign(step_deg, delta)
        return True

    def report(self) -> dict:
        return {
            "name": self.name,
            "motors": list(self.motors),
            "open_deg": self.open,
            "closed_deg": self.closed,
            "target": round(self.target, 4),
            "cmd_deg": round(self.cmd, 2),
            "position_deg": None if self.position is None else round(self.position, 2),
            "fraction": None if self.position is None else round(self.fraction_of(self.position), 4),
            "current_ma": None if self.current is None else round(self.current, 1),
        }


class FingerControlOperation(Operation):
    kind = "finger_control"
    control_source = ControlSource.OPERATION

    def __init__(self, params: dict):
        super().__init__(params)
        self._lock = threading.Lock()
        self._pending: dict[str, float] = {}
        self._speed = float(params.get("speed_deg_s", DEFAULT_SPEED_DEG_S))

    @classmethod
    def validate(cls, service, params: dict) -> dict:
        from orca_ui.hand.service import ServiceError

        session = service.session
        if session is None:
            raise ServiceError("hand not connected", status_code=503)
        if not session.caps.motors:
            raise ServiceError("no motor bus in this session", status_code=409)
        held = set(service.held_motors())
        if not held:
            raise ServiceError("torque is off — hold the motors first", status_code=409)
        known = [int(m) for m in session.hand.config.motor_ids]
        limits = getattr(session.hand, "motor_limits_dict", None) or {}

        joints = clean_joints(params.get("joints"))
        if not joints:
            raise ServiceError("define at least one joint")
        zeros = clean_zeros(params.get("zeros"))
        for joint in joints:
            who = f"joint {joint['name']!r}: "
            if joint["open_deg"] is None or joint["closed_deg"] is None:
                raise ServiceError(who + "capture both the open and the closed end")
            if abs(joint["closed_deg"] - joint["open_deg"]) < MIN_TRAVEL_DEG:
                raise ServiceError(who + "the open and the closed end are the same")
            for term in joint["terms"]:
                if "motor" not in term:
                    raise ServiceError(who + f"tendon {term['tendon']!r} is not on a motor")
                if term["motor"] not in known:
                    raise ServiceError(who + f"unknown motor {term['motor']}")
                if term["motor"] not in held:
                    raise ServiceError(who + f"motor {term['motor']} is released — "
                                       "hold it first", status_code=409)
        couplings = couplings_of(joints, zeros)
        for coupling in couplings:
            lo = np.array([min(j["open_deg"], j["closed_deg"]) for j in coupling.joints])
            hi = np.array([max(j["open_deg"], j["closed_deg"]) for j in coupling.joints])
            who = " + ".join(coupling.names) + ": "
            for motor, (s_lo, s_hi) in zip(coupling.motors, coupling.shaft_extremes(lo, hi)):
                check_shaft_range(motor, s_lo, s_hi, limits, who=who)
        joints.sort(key=lambda j: min(known.index(t["motor"]) for t in j["terms"]))
        speed = cls.clean_speed(params.get("speed_deg_s", DEFAULT_SPEED_DEG_S))
        return {"joints": joints, "zeros": {str(m): v for m, v in zeros.items()},
                "speed_deg_s": speed}

    @staticmethod
    def clean_speed(value) -> float:
        from orca_ui.hand.service import ServiceError

        try:
            speed = _finite(value)
        except ValueError:
            raise ServiceError("speed_deg_s must be a number")
        if not MIN_SPEED_DEG_S <= speed <= MAX_SPEED_DEG_S:
            raise ServiceError(f"speed_deg_s must be {MIN_SPEED_DEG_S:g}..{MAX_SPEED_DEG_S:g}")
        return speed

    # ----- targets, from any thread -------------------------------------------------

    def set_targets(self, targets: dict, speed_deg_s=None) -> dict:
        """Queue new fractions for the run thread; unknown joints are refused,
        fractions are clamped to the captured range."""
        from orca_ui.hand.service import ServiceError

        if not isinstance(targets, dict):
            raise ServiceError("targets must be {joint name: fraction}")
        known = {j["name"]: j for j in self.params["joints"]}
        clean: dict[str, float] = {}
        for name, value in targets.items():
            if name not in known:
                raise ServiceError(f"unknown joint {name!r}", status_code=404)
            try:
                fraction = _finite(value)
            except ValueError:
                raise ServiceError(f"joint {name!r}: the target must be a number 0..1")
            clean[name] = min(1.0, max(0.0, fraction))
        speed = None if speed_deg_s is None else self.clean_speed(speed_deg_s)
        with self._lock:
            self._pending.update(clean)
            if speed is not None:
                self._speed = speed
        return {"targets": clean, "speed_deg_s": speed if speed is not None else self._speed}

    # ----- run ----------------------------------------------------------------------

    def run(self, ctx: OpContext) -> dict:
        from orca_ui.hand.service import ServiceError

        service = ctx.service
        session = service.session
        if session is None:
            raise ServiceError("hand not connected", status_code=503)
        self._hand = session.hand
        self._index = {int(m): i for i, m in enumerate(self._hand.config.motor_ids)}
        self._joints = [_Joint(spec) for spec in self.params["joints"]]
        by_name = {j.name: j for j in self._joints}
        zeros = {int(m): float(v) for m, v in self.params.get("zeros", {}).items()}
        self._couplings = [(c, [by_name[n] for n in c.names])
                           for c in couplings_of(self.params["joints"], zeros)]
        self._ids = [m for c, _ in self._couplings for m in c.motors]
        self._t0 = time.monotonic()
        self._last_publish = 0.0
        self._last_sample = 0.0
        numbers = assignments_of(self._hand.config)

        ctx.log(f"engaging {len(self._joints)} joint(s) at {self._speed:g}°/s:")
        for joint in self._joints:
            motors = ", ".join(f"motor {numbers.get(m, m)}" for m in joint.motors)
            ctx.log(f"  {joint.name}: {motors}, open {joint.open:.1f}° → "
                    f"closed {joint.closed:.1f}°")
        service.set_direct_motor_mode(True, from_operation=True)
        try:
            positions = self._hand.get_motor_pos(as_dict=True)
            for coupling, joints in self._couplings:
                q = coupling.q_of(np.array([_deg(positions[m]) for m in coupling.motors]))
                for joint, angle in zip(joints, q):
                    joint.begin(float(angle))
            ctx.set_phase("engaged", detail=self._detail())
            self._publish(ctx, force=True)
            self._loop(ctx)
        finally:
            service.set_direct_motor_mode(False, from_operation=True)
            self._publish(ctx, force=True)
        ctx.log("disengaged — the motors stay held where they are")
        return {"elapsed_s": round(time.monotonic() - self._t0, 1),
                "joints": [j.report() for j in self._joints]}

    def _loop(self, ctx: OpContext) -> None:
        dt = 1.0 / STREAM_HZ
        next_t = time.monotonic()
        while True:
            ctx.check_stop()
            now = time.monotonic()
            with self._lock:
                pending, self._pending = self._pending, {}
                speed = self._speed
            for joint in self._joints:
                if joint.name in pending:
                    joint.target = pending[joint.name]
            step = speed * dt
            if any([j.tick(step) for j in self._joints]):
                self._write()
            if now - self._last_sample >= SAMPLE_PERIOD_S:
                self._sample(now)
            self._publish(ctx, force=bool(pending))
            next_t += dt
            delay = next_t - time.monotonic()
            if delay > 0:
                ctx.sleep(delay)
            else:
                next_t = time.monotonic()

    def _write(self) -> None:
        shafts: list[float] = []
        for coupling, joints in self._couplings:
            shafts.extend(coupling.shaft_of(np.array([j.cmd for j in joints])))
        # The hardware client divides positions by its scale — array, not list.
        self._hand.write_motor_pos(self._ids, np.radians(np.asarray(shafts, dtype=float)))

    def _sample(self, now: float) -> None:
        self._last_sample = now
        state = self._hand.get_motor_state()
        for coupling, joints in self._couplings:
            rows = [self._index[m] for m in coupling.motors]
            q = coupling.q_of(np.array([_deg(state.position[i]) for i in rows]))
            for joint, angle in zip(joints, q):
                joint.position = float(angle)
                joint.current = sum(abs(float(state.current[self._index[m]]))
                                    for m in joint.motors)

    def _detail(self) -> str:
        return " · ".join(f"{j.name} {j.target * 100:.0f}%" for j in self._joints)

    def _publish(self, ctx: OpContext, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_publish < PUBLISH_PERIOD_S:
            return
        self._last_publish = now
        if force:
            ctx.set_detail(self._detail())
        ctx.set_extra({
            "elapsed_s": round(now - self._t0, 1),
            "speed_deg_s": self._speed,
            "joints": [j.report() for j in self._joints],
        })
