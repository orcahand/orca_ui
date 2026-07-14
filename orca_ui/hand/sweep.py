"""Dev-only joint sweeper (mock mode): drives one joint through its ROM as a
triangle wave so the 3D view's joint directions can be verified
visually against the URDF, one joint at a time."""

from __future__ import annotations

import threading
import time

from orca_ui.hand.service import HandService, ServiceError

SWEEP_RATE_HZ = 30.0


class JointSweeper:
    def __init__(self, service: HandService):
        self._service = service
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._joint: str | None = None

    @property
    def active_joint(self) -> str | None:
        with self._lock:
            return self._joint

    def start(self, joint: str, period_s: float = 4.0) -> None:
        config = self._service.supervisor.config
        if joint not in config.joint_ids:
            raise ServiceError(f"unknown joint: {joint!r}")
        self.stop()
        if not self._service.status()["torque_enabled"]:
            self._service.enable_torque()
        rom_lo, rom_hi = config.joint_roms_dict[joint]
        self._stop.clear()
        with self._lock:
            self._joint = joint
        self._thread = threading.Thread(
            target=self._run, args=(joint, float(rom_lo), float(rom_hi), period_s),
            name="JointSweeper", daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)
        self._thread = None
        with self._lock:
            self._joint = None

    def _run(self, joint: str, lo: float, hi: float, period_s: float) -> None:
        t0 = time.monotonic()
        span = hi - lo
        while not self._stop.is_set():
            phase = ((time.monotonic() - t0) % period_s) / period_s  # 0..1
            tri = 2 * phase if phase < 0.5 else 2 * (1 - phase)      # 0..1..0
            try:
                self._service.set_targets({joint: lo + tri * span})
            except ServiceError:
                return  # torque dropped / session gone: sweep ends
            time.sleep(1.0 / SWEEP_RATE_HZ)
