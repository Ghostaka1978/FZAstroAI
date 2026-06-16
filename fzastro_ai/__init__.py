"""FZAstro AI modular package.

Keep package import lightweight so startup/import smoke tests can run without
loading PySide6 UI modules or optional voice dependencies.
"""

from __future__ import annotations

from .config import APP_VERSION as __version__

__all__ = ["__version__"]
