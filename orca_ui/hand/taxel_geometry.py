"""Taxel geometry adapter: orca_core's sensor-frame geometry when available,
vendored fallback otherwise.

orca_core (joint-sensing branch, since the taxel-geometry merge) exposes
``OrcaHandTouch.get_taxel_geometry()`` with positions in **meters** in the
``sensor`` frame (origin at the connector tail on the mounting plane, X across
the width, Y toward the fingertip dome, Z outward through the surface — the
same axes the streamed forces use). The endpoint normalizes to **millimeters**
because the 2D taxel view's layout constants are mm-tuned; 3D consumers
convert back. The vendored ``orca_ui.taxel_coordinates`` fallback (already mm)
covers hands without tactile support in the connected session.
"""

from __future__ import annotations

MM_PER_M = 1000.0


def get_taxel_geometry(session=None) -> dict:
    """Return ``{finger: {frame, positions: [[x,y,z] mm], source}}``."""
    if session is not None and hasattr(session.hand, "get_taxel_geometry"):
        try:
            geometries = session.hand.get_taxel_geometry()
            out = {}
            for finger, geometry in geometries.items():
                out[finger] = {
                    "frame": geometry.frame,
                    "positions": [
                        [float(x) * MM_PER_M for x in p] for p in geometry.positions
                    ],
                    "source": "orca_core",
                }
            if out:
                return out
        except Exception:
            pass

    from orca_ui.taxel_coordinates import get_all_coordinates

    coords = get_all_coordinates()
    return {
        finger: {
            "frame": "sensor",
            "positions": [[c["x"], c["y"], c["z"]] for c in points],
            "source": "orca_ui_fallback",
        }
        for finger, points in coords.items()
    }
