from __future__ import annotations

# Loaded automatically by Python when this legacy tool directory is on sys.path.
# It prevents Astropy from downloading live IERS-A tables before script imports.
try:
    import os
    import warnings

    os.environ.setdefault(
        "ASTROPY_CACHE_DIR",
        os.path.join(os.path.expanduser("~"), ".fzastro_ai", "astropy_cache"),
    )
    os.environ.setdefault("FZASTRO_DISABLE_IERS_DOWNLOAD", "1")
    from astropy.utils import iers
    from astropy.utils.iers import IERSStaleWarning, IERSWarning

    iers.conf.auto_download = False
    iers.conf.auto_max_age = None
    try:
        iers.conf.iers_degraded_accuracy = "ignore"
    except Exception:
        pass
    warnings.filterwarnings("ignore", category=IERSWarning)
    warnings.filterwarnings("ignore", category=IERSStaleWarning)
except Exception:
    pass
