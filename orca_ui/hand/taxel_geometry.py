"""Taxel geometry adapter: orca_core PR #79 when available, vendored fallback.

orca_core's ``feature/taxel-geometry`` branch adds
``OrcaHandTouch.get_taxel_geometry()`` returning positions in the
``fingertip_local`` frame. Until that merges into the branch this UI tracks,
the vendored ``orca_ui.taxel_coordinates`` models serve the same numbers.
Duck-typing on the hand keeps this a zero-code-change upgrade.
"""

from __future__ import annotations


def get_taxel_geometry(session=None) -> dict:
    """Return ``{finger: {frame, positions: [[x,y,z] mm], source}}``."""
    if session is not None and hasattr(session.hand, "get_taxel_geometry"):
        try:
            geometries = session.hand.get_taxel_geometry()
            out = {}
            for finger, geometry in geometries.items():
                out[finger] = {
                    "frame": geometry.frame,
                    "positions": [list(map(float, p)) for p in geometry.positions],
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
            "frame": "fingertip_local",
            "positions": [[c["x"], c["y"], c["z"]] for c in points],
            "source": "orca_ui_fallback",
        }
        for finger, points in coords.items()
    }
