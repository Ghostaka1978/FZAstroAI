"""Embedded astrophotography/astronomy tools migrated from FZASTRO.

This package keeps the embedded FZASTRO scripts isolated behind a desktop-safe
engine and worker layer so the main PySide6 app does not need to run FastAPI.
"""

from .engine import (
    AstroToolResult,
    astro_dependency_report,
    best_targets,
    fetch_sky_image,
    lookup_object,
    observing_forecast,
    solar_system_map,
)

__all__ = [
    "AstroToolResult",
    "astro_dependency_report",
    "best_targets",
    "fetch_sky_image",
    "lookup_object",
    "observing_forecast",
    "solar_system_map",
]
