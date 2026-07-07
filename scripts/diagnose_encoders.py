"""Live joint-encoder diagnostic: polarity vs anchor vs dead slot.

Streams the encoder frames (sensing only — motors untouched) and prints, for
each encoder-calibrated joint, the raw word, error/parity flags, and the
decoded angle under BOTH polarities. Slowly flex and extend the suspect joint
by hand and read the columns:

  * angle(cfg) tracks your motion in the correct direction but sits offset
    by a roughly constant amount        -> BAD ANCHOR (recapture; a value of
    16383 usually means error words were averaged during capture)
  * angle(cfg) moves OPPOSITE to your motion, angle(flip) tracks correctly
                                        -> POLARITY flipped for this joint
  * err=1 / parity=0 / raw stuck at 0xFFFF or 0x0000
                                        -> dead slot / wiring

Stop the UI first — it holds the sensing port exclusively.

Usage:
    uv run python scripts/diagnose_encoders.py CONFIG [--joints j1 j2] [--seconds 30]
"""

from __future__ import annotations

import argparse
import os
import sys
import time

import numpy as np

from orca_core import load_hand
from orca_core.hardware.hand_serial_link import HandSerialLink
from orca_core.hardware.joint_encoder_client import JointEncoderClient
from orca_core.hardware.sensing.constants import (
    ENCODER_LSB_DEG,
    JOINT_ENCODER_POLARITY,
    JOINT_TO_ENCODER_SLOT,
)
from orca_core.hardware.sensing.serial_discovery import resolve_sensing_ports


def wrap_deg(delta: float) -> float:
    return (delta + 180.0) % 360.0 - 180.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("config", help="hand config.yaml (or its folder)")
    parser.add_argument("--joints", nargs="+", default=None,
                        help="joints to watch (default: all calibrated)")
    parser.add_argument("--seconds", type=float, default=30.0)
    parser.add_argument("--hz", type=float, default=2.0)
    args = parser.parse_args()

    config_path = args.config
    if os.path.isdir(config_path):
        config_path = os.path.join(config_path, "config.yaml")

    hand = load_hand(config_path=config_path)  # constructed only, never connected
    config = hand.config
    enc_cal = hand.calibration.joint_encoder_calibration_dict or {}
    joints = args.joints or sorted(enc_cal)
    missing = [j for j in joints if j not in enc_cal]
    if missing:
        print(f"note: no calibration anchor for {missing} — showing raw only")

    ports = resolve_sensing_ports(
        tactile_override="disabled",
        encoder_override=config.encoder_serial_port,
    )
    if ports.encoder is None:
        print("no encoder port found (is the UI still running and holding it?)")
        return 1

    link = HandSerialLink(port=ports.encoder, baudrate=config.encoder_baudrate)
    link.connect()
    client = JointEncoderClient(link)
    client.connect()
    client.start_stream()
    print(f"streaming from {ports.encoder} — wiggle the suspect joint slowly\n")

    header = (f"{'joint':12} {'slot':>4} {'raw':>6} {'err':>3} {'par':>3} "
              f"{'count':>6} {'anchor':>6} {'Δdeg':>8} {'angle(cfg)':>10} "
              f"{'angle(flip)':>11}")
    try:
        end = time.time() + args.seconds
        line_count = 0
        while time.time() < end:
            reading = client.get_latest()
            if reading is None:
                time.sleep(0.1)
                continue
            if line_count % 10 == 0:
                print(header)
            line_count += 1
            raw = np.asarray(reading.raw_counts)
            for joint in joints:
                slot = JOINT_TO_ENCODER_SLOT.get(joint)
                if slot is None:
                    continue
                word = int(raw[slot])
                count = word & 0x3FFF
                err = int(bool(reading.angle_error[slot]))
                parity = int(bool(reading.parity_ok[slot]))
                cal = enc_cal.get(joint)
                if cal is None:
                    print(f"{joint:12} {slot:>4} {word:#06x} {err:>3} {parity:>3} "
                          f"{count:>6} {'--':>6} {'--':>8} {'--':>10} {'--':>11}")
                    continue
                anchor = cal.enc_at_anchor_count
                rom_hi = float(config.joint_roms_dict[joint][1])
                polarity = JOINT_ENCODER_POLARITY[joint]
                delta = wrap_deg((count - anchor) * ENCODER_LSB_DEG)
                angle_cfg = polarity * delta + rom_hi
                angle_flip = -polarity * delta + rom_hi
                print(f"{joint:12} {slot:>4} {word:#06x} {err:>3} {parity:>3} "
                      f"{count:>6} {anchor:>6} {delta:>8.1f} {angle_cfg:>10.1f} "
                      f"{angle_flip:>11.1f}")
            print()
            time.sleep(1.0 / args.hz)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            client.disconnect()
        except Exception:
            pass
        try:
            link.disconnect()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
