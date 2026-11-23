"""The visual calibration study's research extras, kept in the code but off and hidden unless
the console is started with ``--research-ui``. Without it:

- no study map is applied (its mode reads off; a stored selection is kept, selecting is refused);
- telemetry computes no ghost hands (main stops, study mappings);
- these endpoints answer 404: ``/api/visual-calibration/study-map``, ``/lut``, ``/lut/command``,
  ``/study/*`` (the study server proxy) and ``/api/control/motor_currents``;
- the browser hides the Study tab, the dashboard's study panel, the ghost hands, and steps 7
  (live hand-pose estimate) and 11 (control sandbox) of Setup › Visual calibration. The
  ``/api/visual-calibration/live-fit/*`` endpoints behind step 7 stay open.
"""

from __future__ import annotations

from fastapi import HTTPException

_enabled = False


def enabled() -> bool:
    return _enabled


def configure(on: bool) -> None:
    """Set once by the app factory from ``UiSettings.research_ui``."""
    global _enabled
    _enabled = bool(on)


def require() -> None:
    """Route dependency: a research endpoint answers 404 while the extras are off."""
    if not _enabled:
        raise HTTPException(404, "a research extra: start the console with --research-ui")
