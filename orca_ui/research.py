"""The visual calibration study's research extras: the Study tab, study maps, the ghost-hand
overlays, the control sandbox and the live hand-pose estimate.

They stay in the code but are off and hidden unless the console is started with
``--research-ui``: no study map is ever applied, telemetry computes no overlays,
their endpoints answer 404 and the browser shows none of them.
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
