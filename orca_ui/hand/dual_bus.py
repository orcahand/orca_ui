"""Two motor buses behind one session, for a bench carrying both families.

Bare mode brings up loose motors, and a bench may well have a Feetech chain on
one adapter and a Dynamixel chain on another. One ``OrcaHand`` cannot span
them: its config pins a single port, family and rate, and the family facts the
console reads — register widths, current scales, reachable spans, control modes
— are class attributes of one motor client. So there are two hands, each with
its own correct client, and this module fronts them with the session surface
the rest of the console already speaks.

Routing is by motor id, which bare mode takes to be unique across the buses: a
command names a motor and nothing else, so two motors sharing an id on two
adapters could not be told apart. The survey shows the operator every id it
found, which is where a clash becomes visible.

Only the bench surface is fronted. There are no joints to command, no tendons,
no calibration and no sensing on loose motors, so the aggregate questions that
remain are per-motor ones and merge cleanly. Where a question has no single
answer across two families — the gain register's width, the family's reachable
span — the routing client declines to answer rather than picking a bus, and the
caller asks per motor instead.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from orca_core.hardware.motor_client import MotorRead

logger = logging.getLogger(__name__)

# Client calls that name one motor; dispatched to the bus that owns it.
_PER_MOTOR_CALLS = ("reboot_motor", "read_hardware_error")
# Client calls taking motor ids and returning a dict keyed by them; split
# across the buses and merged back.
_PER_ID_MAP_CALLS = ("default_profile", "read_profile_limits",
                     "read_servo_gains", "read_servo_profile",
                     "read_hardware_errors")
# Client calls taking a dict keyed by motor id; split across the buses.
_BY_ID_DICT_CALLS = ("write_servo_gains", "write_servo_profile")


class RoutingMotorClient:
    """A motor client over several buses, dispatching each call by motor id.

    Deliberately not a :class:`~orca_core.hardware.motor_client.MotorClient`
    and deliberately carrying none of a family's class attributes: a caller
    reaching for ``type(client).position_range_rad`` gets ``None`` and has to
    ask about a motor instead of about "the family", which is the only honest
    answer when there are two. Methods are bound per instance so that
    ``hasattr`` reports what the buses can really do rather than what this
    class could in principle forward.
    """

    def __init__(self, clients):
        self._clients = list(clients)
        self._owner = {int(motor_id): client
                       for client in self._clients
                       for motor_id in client.motor_ids}
        for name in _PER_MOTOR_CALLS:
            self._bind(name, self._per_motor_dispatcher)
        for name in _PER_ID_MAP_CALLS:
            self._bind(name, self._per_id_map_dispatcher)
        for name in _BY_ID_DICT_CALLS:
            self._bind(name, self._by_id_dict_dispatcher)

    def _bind(self, name: str, make) -> None:
        """Expose ``name`` only when every bus can answer it."""
        if all(hasattr(client, name) for client in self._clients):
            setattr(self, name, make(name))

    @property
    def motor_ids(self) -> list[int]:
        """Every bus's motors, in bus order — the order the merged config
        lists them in, so an array indexed by one is indexed by the other."""
        return [int(motor_id) for client in self._clients
                for motor_id in client.motor_ids]

    def client_for(self, motor_id: int):
        """The bus that owns ``motor_id``, or None if no bus claims it."""
        return self._owner.get(int(motor_id))

    @property
    def bus_clients(self) -> list:
        """One client per bus, for a question each has to answer for itself."""
        return list(self._clients)

    @property
    def _model_numbers(self) -> dict:
        """Merged model numbers, for checking an operator's declaration."""
        merged: dict = {}
        for client in self._clients:
            merged.update(getattr(client, "_model_numbers", None) or {})
        return merged

    def _per_motor_dispatcher(self, name: str):
        def call(motor_id, *args, **kwargs):
            client = self.client_for(motor_id)
            if client is None:
                raise KeyError(f"motor {motor_id} is on no connected bus")
            return getattr(client, name)(motor_id, *args, **kwargs)
        return call

    def _per_id_map_dispatcher(self, name: str):
        def call(motor_ids, *args, **kwargs):
            merged: dict = {}
            for client, ids in self._split(motor_ids).items():
                merged.update(getattr(client, name)(ids, *args, **kwargs) or {})
            return merged
        return call

    def _by_id_dict_dispatcher(self, name: str):
        def call(by_id, *args, **kwargs):
            for client, ids in self._split(by_id).items():
                getattr(client, name)({mid: by_id[mid] for mid in ids},
                                      *args, **kwargs)
        return call

    def _split(self, motor_ids) -> dict:
        """Group ``motor_ids`` by the bus that owns them, in bus order."""
        grouped: dict = {id(client): (client, []) for client in self._clients}
        for motor_id in motor_ids:
            client = self.client_for(motor_id)
            if client is None:
                logger.debug("motor %s is on no connected bus", motor_id)
                continue
            grouped[id(client)][1].append(motor_id)
        return {client: ids for client, ids in grouped.values() if ids}

    def take_hardware_alerts(self) -> dict:
        merged: dict = {}
        for client in self._clients:
            take = getattr(client, "take_hardware_alerts", None)
            if take is not None:
                merged.update(take() or {})
        return merged

    def write_desired_current(self, motor_ids, currents) -> None:
        by_id = dict(zip([int(mid) for mid in motor_ids], currents))
        for client, ids in self._split(by_id).items():
            client.write_desired_current(
                ids, np.asarray([by_id[mid] for mid in ids], dtype=float))


class _FanOutEvent:
    """Every bus's task-stop event as one. An interrupt that reached only one
    bus would leave the other still driving."""

    def __init__(self, events):
        self._events = list(events)

    def set(self) -> None:
        for event in self._events:
            event.set()

    def clear(self) -> None:
        for event in self._events:
            event.clear()

    def is_set(self) -> bool:
        return any(event.is_set() for event in self._events)


@dataclass
class DualBusHand:
    """One hand-shaped surface over several connected single-bus hands.

    ``config`` is the merged bench config: every bus's motors and pseudo-joints
    with no port, family or rate of its own. Reads that return an array come
    back concatenated in bus order, which is the order ``config.motor_ids``
    lists, so an existing caller zipping the two still lines up.
    """

    hands: list
    config: object

    def __post_init__(self):
        self._routing = RoutingMotorClient([h.motor_client for h in self.hands])
        self._task_stop_event = _FanOutEvent(
            h._task_stop_event for h in self.hands)

    @property
    def motor_client(self):
        return self._routing

    def hand_for(self, motor_id: int):
        """The single-bus hand that owns ``motor_id``, or None."""
        client = self._routing.client_for(motor_id)
        for hand in self.hands:
            if hand.motor_client is client:
                return hand
        return None

    def client_for(self, motor_id: int):
        return self._routing.client_for(motor_id)

    # ----- lifecycle -------------------------------------------------------

    def is_connected(self) -> bool:
        """True only while every bus is up: a bench half gone is not a bench,
        and the console must reconnect rather than quietly drive one adapter."""
        return bool(self.hands) and all(h.is_connected() for h in self.hands)

    def disconnect(self) -> tuple[bool, str]:
        failures = []
        for hand in self.hands:
            try:
                result = hand.disconnect()
            except Exception as e:
                failures.append(f"{_bus_name(hand)}: {e}")
                continue
            if isinstance(result, tuple) and len(result) == 2 and not result[0]:
                failures.append(f"{_bus_name(hand)}: {result[1]}")
        if failures:
            return False, "; ".join(failures)
        return True, f"disconnected {len(self.hands)} buses"

    def is_calibrated(self, *args, **kwargs) -> bool:
        """Never. Loose motors have no hardstops to calibrate against, so the
        motor-derived joint estimate this gates would be meaningless."""
        return False

    # ----- reads -----------------------------------------------------------

    def get_motor_pos(self, as_dict: bool = False):
        return self._gather("get_motor_pos", as_dict)

    def get_motor_current(self, as_dict: bool = False):
        return self._gather("get_motor_current", as_dict)

    def get_motor_temp(self, as_dict: bool = False):
        return self._gather("get_motor_temp", as_dict)

    def _gather(self, method: str, as_dict: bool):
        if as_dict:
            merged: dict = {}
            for hand in self.hands:
                merged.update(getattr(hand, method)(as_dict=True))
            return merged
        return np.concatenate(
            [np.asarray(getattr(hand, method)()) for hand in self.hands])

    def get_motor_state(self) -> MotorRead:
        reads = [hand.get_motor_state() for hand in self.hands]
        return MotorRead(*(np.concatenate([np.asarray(r[i]) for r in reads])
                           for i in range(len(MotorRead._fields))))

    # ----- writes ----------------------------------------------------------

    def write_motor_pos(self, motor_ids, positions) -> None:
        by_id = dict(zip([int(mid) for mid in motor_ids], positions))
        for hand, ids in self._split_hands(by_id).items():
            hand.write_motor_pos(ids, [by_id[mid] for mid in ids])

    def enable_torque(self, motor_ids=None) -> list[int]:
        return self._torque("enable_torque", motor_ids)

    def disable_torque(self, motor_ids=None) -> list[int]:
        return self._torque("disable_torque", motor_ids)

    def _torque(self, method: str, motor_ids) -> list[int]:
        """Every bus is asked even if one raises: leaving half a bench
        powered because the other half failed is the dangerous outcome."""
        failed, errors = [], []
        groups = ({hand: None for hand in self.hands} if motor_ids is None
                  else self._split_hands(motor_ids))
        for hand, ids in groups.items():
            try:
                failed += list(getattr(hand, method)(ids) or [])
            except Exception as e:
                errors.append(f"{_bus_name(hand)}: {e}")
                failed += list(ids if ids is not None else hand.config.motor_ids)
        if errors:
            logger.warning("%s failed on %s", method, "; ".join(errors))
        return failed

    def set_max_current(self, current) -> None:
        """One value for every motor, or a per-motor list in merged order."""
        if np.ndim(current) == 0:
            for hand in self.hands:
                hand.set_max_current(float(current))
            return
        values = [float(v) for v in current]
        ids = self.config.motor_ids
        if len(values) != len(ids):
            raise ValueError(
                "Number of currents do not match the number of motors.")
        by_id = dict(zip([int(mid) for mid in ids], values))
        for hand in self.hands:
            hand.set_max_current([by_id[int(mid)]
                                  for mid in hand.config.motor_ids])

    def wait_for_motion(self, timeout: float = 5.0) -> None:
        for hand in self.hands:
            hand.wait_for_motion(timeout=timeout)

    def get_servo_gains(self) -> dict:
        return self._merge_per_motor("get_servo_gains")

    def get_servo_profile(self) -> dict:
        return self._merge_per_motor("get_servo_profile")

    def set_servo_gains(self, gains: dict) -> None:
        self._scatter_per_motor("set_servo_gains", gains)

    def set_servo_profile(self, profiles: dict) -> None:
        self._scatter_per_motor("set_servo_profile", profiles)

    def _merge_per_motor(self, method: str) -> dict:
        merged: dict = {}
        for hand in self.hands:
            merged.update(getattr(hand, method)() or {})
        return merged

    def _scatter_per_motor(self, method: str, by_id: dict) -> None:
        for hand, ids in self._split_hands(by_id).items():
            getattr(hand, method)({mid: by_id[mid] for mid in ids})

    def _split_hands(self, motor_ids) -> dict:
        grouped: dict = {id(hand): (hand, []) for hand in self.hands}
        for motor_id in motor_ids:
            hand = self.hand_for(motor_id)
            if hand is None:
                logger.debug("motor %s is on no connected bus", motor_id)
                continue
            grouped[id(hand)][1].append(int(motor_id))
        return {hand: ids for hand, ids in grouped.values() if ids}


def bus_clients(hand) -> list:
    """One motor client per bus behind ``hand``, for a question each bus has
    to answer for itself. A single-bus hand yields its one client."""
    client = getattr(hand, "motor_client", None)
    if client is None:
        return []
    buses = getattr(client, "bus_clients", None)
    return list(buses) if buses else [client]


def client_owning(hand, motor_id: int):
    """The motor client that owns ``motor_id`` on ``hand``.

    On a single-bus hand that is the one client, whatever the id. On a bench
    whose buses carry different families it is the one that can actually answer
    for this motor: the family decides the register map, the current scale, the
    error vocabulary and the reachable travel, so asking the other bus returns
    a wrong answer rather than an error.
    """
    client = getattr(hand, "motor_client", None)
    route = getattr(client, "client_for", None)
    return client if route is None else route(motor_id)


def _bus_name(hand) -> str:
    config = getattr(hand, "config", None)
    return (f"{getattr(config, 'motor_type', '?')} @ "
            f"{getattr(config, 'port', '?')}")
