"""Sine-wave signal generators for driving the UI with a MockTactileClient.

Lets you exercise the full UI (resultant force vectors + per-taxel views) with
no hardware attached.
"""

import math
import time

from orca_core.hardware.sensing.constants import FINGER_NAMES, DEFAULT_TAXEL_COUNTS

# Per-axis amplitude/offset (Newtons). fz is unsigned on the wire (0..25.5 N),
# so it is always kept non-negative.
FREQ_HZ = 0.5      # oscillation frequency of the sine
XY_AMP = 8.0       # resultant amplitude for fx, fy   (within +/-12.7 N signed range)
Z_OFFSET = 8.0     # resultant baseline for fz
Z_AMP = 6.0        # resultant amplitude for fz       (2..14 N, within 0..25.5 N range)
# Taxels are normalized against MAX_TAXEL_FORCE (25 N) in the UI, so the taxel
# signal pulses through ~0..25 N to make the intensity/colour sweep visible.
# fz carries the bulk (unsigned, up to 25.5 N); fx/fy stay within +/-12.7 N.
TAXEL_XY_AMP = 10.0   # in-plane amplitude (within +/-12.7 N signed range)
TAXEL_Z_AMP = 25.0    # fz amplitude       (0..25 N, within 0..25.5 N range)
_TWO_PI_3 = 2.0 * math.pi / 3.0


def make_sine_providers(freq_hz=FREQ_HZ):
    """Return (resultant_provider, taxel_provider) callables for MockTactileClient.

    Each finger gets a phase offset so they animate out of step; each taxel gets
    an additional phase based on its index, so a wave travels across the taxel grid.
    """
    t0 = time.time()
    w = 2.0 * math.pi * freq_hz

    def _phase():
        return w * (time.time() - t0)

    def resultant_provider():
        p = _phase()
        out = {}
        for i, finger in enumerate(FINGER_NAMES):
            fphase = p + i * (2.0 * math.pi / len(FINGER_NAMES))
            out[finger] = [
                XY_AMP * math.sin(fphase),
                XY_AMP * math.sin(fphase + _TWO_PI_3),
                Z_OFFSET + Z_AMP * math.sin(fphase + 2 * _TWO_PI_3),
            ]
        return out

    def taxel_provider():
        p = _phase()
        out = {}
        for i, finger in enumerate(FINGER_NAMES):
            n = DEFAULT_TAXEL_COUNTS[finger]
            vecs = []
            for k in range(n):
                sp = 2.0 * math.pi * k / max(n, 1)  # spatial offset across taxels
                angle = p + sp + i                  # in-plane direction, rotates + travels
                env = 0.5 * (1.0 + math.sin(0.5 * p + sp))  # 0..1 intensity envelope
                xy = TAXEL_XY_AMP * env
                vecs.append([
                    xy * math.cos(angle),
                    xy * math.sin(angle),
                    TAXEL_Z_AMP * env,  # fz carries the magnitude, stays non-negative
                ])
            out[finger] = vecs
        return out

    return resultant_provider, taxel_provider
