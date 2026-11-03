"""Taxel geometry adapter: orca_core's sensor-frame geometry, vendored fallback
only when orca_core has none.

orca_core exposes ``OrcaHandTouch.get_taxel_geometry()`` for a connected hand
and ``load_all_taxel_geometry()`` for the packaged sensor models, with positions
in **meters** in the ``sensor`` frame (origin at the connector tail on the
mounting plane, X across the width, Y toward the fingertip dome, Z outward
through the surface). The endpoint normalizes positions to **millimeters**
because the 2D taxel view's layout constants are mm-tuned; 3D consumers convert
back.

Streamed per-taxel forces are in each taxel's *own* axes (fz along its surface
normal), not the sensor frame. ``orientations`` carries each taxel's 3x3
rotation from those local axes into the sensor frame, row-major, so a 3D
consumer draws ``R @ [fx, fy, fz]``. It is omitted when the installed orca_core
predates per-taxel orientations.
"""

from __future__ import annotations

MM_PER_M = 1000.0


def _serialize(geometries, source: str) -> dict:
    out = {}
    for finger, geometry in geometries.items():
        entry = {
            "frame": geometry.frame,
            "positions": [[float(x) * MM_PER_M for x in p] for p in geometry.positions],
            "source": source,
        }
        orientations = getattr(geometry, "orientations", None)
        if orientations is not None:
            entry["orientations"] = [
                [[float(v) for v in row] for row in rotation] for rotation in orientations
            ]
        out[finger] = entry
    return out


def get_taxel_geometry(session=None) -> dict:
    """Return ``{finger: {frame, positions: [[x,y,z] mm], orientations?, source}}``."""
    if session is not None and hasattr(session.hand, "get_taxel_geometry"):
        try:
            out = _serialize(session.hand.get_taxel_geometry(), "orca_core")
            if out:
                return out
        except Exception:
            pass

    # No connected tactile hand yet: orca_core's packaged models still give
    # the same positions plus the per-taxel axes.
    try:
        from orca_core.hardware.sensing.taxel_geometry import load_all_taxel_geometry

        out = _serialize(load_all_taxel_geometry(), "orca_core_packaged")
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
