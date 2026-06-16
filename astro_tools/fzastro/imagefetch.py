from __future__ import annotations
import hashlib
import time
from pathlib import Path
from typing import Optional, Tuple, List
import requests

APP_DIR = Path(__file__).parent.resolve()
WEB_DIR = (APP_DIR / "web").resolve()
CACHE_DIR = (WEB_DIR / "cache" / "images").resolve()

HIPS_ENDPOINT = "https://alasky.u-strasbg.fr/hips-image-services/hips2fits"

DEFAULT_SURVEY = "DSS2/color"
FALLBACK_SURVEYS = [
    "2MASS/Color",
    "DSS2/blue",
]


def _fmt_float(x: float, n: int = 6) -> str:
    return f"{float(x):.{n}f}"


def _sanitize_survey(s: str) -> str:
    return s.replace("/", "_")


def _cache_key(
    survey: str,
    ra: float,
    dec: float,
    fov_deg: float,
    w: int,
    h: int,
    rotation_angle: float,
) -> str:
    base = f"{survey}|{_fmt_float(ra)}|{_fmt_float(dec)}|{_fmt_float(fov_deg)}|{int(w)}|{int(h)}|{_fmt_float(rotation_angle)}"
    hsh = hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]
    r = int(round(float(rotation_angle)))
    name = f"{_sanitize_survey(survey)}_{_fmt_float(ra)}_{_fmt_float(dec)}_{_fmt_float(fov_deg)}_{int(w)}x{int(h)}_r{r}_{hsh}.jpg"
    return name


def _is_fresh(p: Path, ttl_days: int) -> bool:
    if not p.exists():
        return False
    age_s = time.time() - p.stat().st_mtime
    return age_s <= ttl_days * 86400


def _ensure_dirs() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _hips_request(
    survey: str,
    ra: float,
    dec: float,
    fov_deg: float,
    w: int,
    h: int,
    rotation_angle: float,
    timeout: int,
) -> Optional[bytes]:
    params = {
        "hips": survey,
        "ra": _fmt_float(ra),
        "dec": _fmt_float(dec),
        "fov": _fmt_float(fov_deg),
        "width": int(w),
        "height": int(h),
        "format": "jpg",
        "projection": "TAN",
        "rotation_angle": float(rotation_angle),
    }
    try:
        r = requests.get(HIPS_ENDPOINT, params=params, timeout=timeout)
        if r.status_code == 200 and r.headers.get(
            "content-type", ""
        ).lower().startswith("image/"):
            return r.content
    except Exception:
        return None
    return None


def _try_chain(
    surveys: List[str],
    ra: float,
    dec: float,
    fov_deg: float,
    w: int,
    h: int,
    rotation_angle: float,
    timeout: int,
) -> Tuple[Optional[bytes], Optional[str]]:
    for s in surveys:
        blob = _hips_request(s, ra, dec, fov_deg, w, h, rotation_angle, timeout)
        if blob:
            return blob, s
    return None, None


def fetch_image(
    ra: float,
    dec: float,
    fov_deg: float,
    w: int = 2048,
    h: int = 2048,
    survey: Optional[str] = None,
    rotation_angle: float = 270.0,
    ttl_days: int = 30,
    timeout: int = 15,
) -> Tuple[Optional[Path], Optional[str], Optional[str]]:
    _ensure_dirs()
    ra = float(ra)
    dec = float(dec)
    fov_deg = _clamp(float(fov_deg), 0.02, 10.0)
    w = int(max(64, min(4096, int(w))))
    h = int(max(64, min(4096, int(h))))
    rotation_angle = _clamp(float(rotation_angle), 0.0, 360.0)
    primary = (
        survey.strip() if isinstance(survey, str) and survey.strip() else DEFAULT_SURVEY
    )
    chain = [primary] + [s for s in FALLBACK_SURVEYS if s != primary]
    key = _cache_key(primary, ra, dec, fov_deg, w, h, rotation_angle)
    path = CACHE_DIR / key
    if _is_fresh(path, ttl_days):
        return path, f"/web/cache/images/{path.name}", primary
    blob, used = _try_chain(chain, ra, dec, fov_deg, w, h, rotation_angle, timeout)
    if not blob or not used:
        return None, None, None
    key_used = _cache_key(used, ra, dec, fov_deg, w, h, rotation_angle)
    path_used = CACHE_DIR / key_used
    path_used.write_bytes(blob)
    return path_used, f"/web/cache/images/{path_used.name}", used


def image_credit_for(survey: Optional[str]) -> str:
    s = survey or DEFAULT_SURVEY
    # ASCII only for HTTP headers
    return f"CDS/Aladin HIPS2FITS - {s}"
