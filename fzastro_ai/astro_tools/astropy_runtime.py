from __future__ import annotations

import os
import warnings
from pathlib import Path

_CONFIGURED = False


def configure_astropy_runtime() -> None:
    """Configure Astropy for offline/stable desktop use.

    FZAstro does not need fresh sub-arcsecond Earth-orientation tables for the
    local planning UI. Letting Astropy auto-download IERS-A data can block the
    app, produce malformed-cache warnings, or crash some Windows builds when the
    remote table is bad. Use bundled/degraded IERS data instead.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return
    _CONFIGURED = True

    os.environ.setdefault(
        "ASTROPY_CACHE_DIR",
        str(Path.home() / ".fzastro_ai" / "astropy_cache"),
    )
    os.environ.setdefault("FZASTRO_DISABLE_IERS_DOWNLOAD", "1")

    try:
        from astropy.utils import iers  # type: ignore
        from astropy.utils.iers import IERSStaleWarning, IERSWarning  # type: ignore

        iers.conf.auto_download = False
        iers.conf.auto_max_age = None
        try:
            iers.conf.iers_degraded_accuracy = "ignore"
        except Exception:
            try:
                iers.conf.iers_degraded_accuracy = "warn"
            except Exception:
                pass
        try:
            iers.conf.remote_timeout = 2.0
        except Exception:
            pass
        warnings.filterwarnings("ignore", category=IERSWarning)
        warnings.filterwarnings("ignore", category=IERSStaleWarning)
    except Exception:
        # Astropy may not be installed in the main app interpreter. The worker
        # subprocess will run the same setup in its own interpreter when needed.
        pass
