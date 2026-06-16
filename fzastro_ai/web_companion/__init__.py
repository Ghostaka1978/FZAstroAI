"""Browser-based companion UI for FZAstro AI.

This package is intentionally separate from the PySide6 desktop app so the
normal desktop startup path stays unchanged.  Importing ``fzastro_ai`` does not
import FastAPI, Uvicorn, Qt, or any web companion modules.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
