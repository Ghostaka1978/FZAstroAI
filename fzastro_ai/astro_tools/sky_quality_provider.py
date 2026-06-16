from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

from ..network_utils import get_limited_text


class SkyQualityLookupError(RuntimeError):
    """Raised when a sky-quality provider cannot return usable values."""


@dataclass(frozen=True)
class SkyQualityLookupResult:
    sqm: float | None
    bortle: float | None
    source: str
    source_url: str
    fetched_at_utc: str
    raw_summary: str = ""

    def to_location_fields(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "sky_quality_source": self.source,
            "sky_quality_fetched_at": self.fetched_at_utc,
            "sky_quality_source_url": self.source_url,
        }
        if self.sqm is not None:
            payload["sqm"] = round(float(self.sqm), 2)
        if self.bortle is not None:
            payload["bortle"] = int(round(float(self.bortle)))
            payload["bortle_precise"] = round(float(self.bortle), 1)
        return payload

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.update(self.to_location_fields())
        return data


def lightpollutionmap_app_url(lat: float, lon: float, *, zoom: int = 10) -> str:
    query = urlencode(
        {"lat": f"{float(lat):.6f}", "lng": f"{float(lon):.6f}", "zoom": int(zoom)}
    )
    return f"https://lightpollutionmap.app/?{query}"


def _valid_sqm(value: float | None) -> float | None:
    if value is None:
        return None
    value = float(value)
    if 10.0 <= value <= 23.5:
        return round(value, 2)
    return None


def _valid_bortle(value: float | None) -> float | None:
    if value is None:
        return None
    value = float(value)
    if 1.0 <= value <= 9.0:
        return round(value, 1)
    return None


def _first_number(patterns: tuple[str, ...], text: str) -> float | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE | re.DOTALL)
        if not match:
            continue
        for group in match.groups():
            if group is None:
                continue
            try:
                return float(str(group).replace(",", "."))
            except Exception:
                continue
    return None


def _location_details_slice(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or " ")).strip()
    if not cleaned:
        return ""
    start = cleaned.lower().find("location details")
    if start >= 0:
        cleaned = cleaned[start:]
    # Keep the part most likely to contain the clicked-location readout. This
    # avoids false matches from help text such as exposure examples.
    end_markers = (
        "Aurora Probability",
        "All-Sky Skyglow",
        "Nighttime Weather",
        "Light Pollution Trends",
        "Sky Light Pollution Analyzer",
        "Light Pollution Scale",
        "Light Pollution Map FAQ",
    )
    ends = [cleaned.find(marker) for marker in end_markers if cleaned.find(marker) > 0]
    if ends:
        cleaned = cleaned[: min(ends)]
    return cleaned[:6000]


def parse_lightpollutionmap_text(text: str) -> tuple[float | None, float | None, str]:
    section = _location_details_slice(text)
    if not section or "-- BORTLE" in section or "-- SQM" in section:
        # Do not immediately fail: rendered pages may still contain placeholders
        # plus real text farther down. Continue with all text as a fallback.
        section = re.sub(r"\s+", " ", str(text or " ")).strip()[:12000]

    # Common rendered patterns from lightpollutionmap.app location panel:
    #   "4.3 BORTLE ... 20.82 SQM"
    #   "Bortle 4.3" / "SQM 20.82"
    #   JSON-ish values from frontend state if present.
    bortle = _valid_bortle(
        _first_number(
            (
                r"([1-9](?:\.\d+)?)\s*BORTLE\b",
                r"\bBortle(?:\s+Scale)?\D{0,24}([1-9](?:\.\d+)?)\b",
                r"\"bortle(?:Class)?\"\s*:\s*\"?([1-9](?:\.\d+)?)",
            ),
            section,
        )
    )
    sqm = _valid_sqm(
        _first_number(
            (
                r"\b([1-2]\d(?:\.\d{1,3})?)\s*SQM\b",
                r"\bSQM\D{0,24}([1-2]\d(?:\.\d{1,3})?)\b",
                r"\"sqm\"\s*:\s*\"?([1-2]\d(?:\.\d{1,3})?)",
                r"\"skyQuality\"\s*:\s*\"?([1-2]\d(?:\.\d{1,3})?)",
            ),
            section,
        )
    )
    return sqm, bortle, section[:700]


def _fetch_static_page(
    lat: float, lon: float, *, timeout: float
) -> tuple[float | None, float | None, str]:
    url = lightpollutionmap_app_url(lat, lon)
    text = get_limited_text(
        url,
        max_bytes=2_500_000,
        timeout=timeout,
        headers={
            "User-Agent": "FZAstroAI/1.0 (+https://github.com/) Python requests",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    return parse_lightpollutionmap_text(text)


def _fetch_with_playwright(
    lat: float, lon: float, *, timeout: float
) -> tuple[float | None, float | None, str]:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - optional dependency path
        raise SkyQualityLookupError(f"Playwright is not available: {exc}") from exc

    url = lightpollutionmap_app_url(lat, lon)
    timeout_ms = int(max(6.0, float(timeout)) * 1000)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-dev-shm-usage"])
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            try:
                page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 12_000))
            except Exception:
                pass
            page.wait_for_timeout(1800)

            # The URL centers the map. Some builds only calculate details after a
            # map click, so click the center of the Leaflet map container.
            try:
                box = page.locator(".leaflet-container").bounding_box(timeout=2500)
            except Exception:
                box = None
            if box:
                page.mouse.click(
                    box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
                )
            else:
                page.mouse.click(640, 450)
            page.wait_for_timeout(2500)

            text = page.evaluate("document.body ? document.body.innerText : ''")
            sqm, bortle, summary = parse_lightpollutionmap_text(text)
            if sqm is None and bortle is None:
                # One more short wait helps slow map tile/data requests.
                page.wait_for_timeout(2500)
                text = page.evaluate("document.body ? document.body.innerText : ''")
                sqm, bortle, summary = parse_lightpollutionmap_text(text)
            return sqm, bortle, summary
        finally:
            browser.close()


def fetch_lightpollutionmap_app_sky_quality(
    lat: float,
    lon: float,
    *,
    timeout: float = 25.0,
    prefer_browser: bool = True,
) -> SkyQualityLookupResult:
    """Fetch SQM/Bortle from lightpollutionmap.app for a site coordinate.

    lightpollutionmap.app does not publish a small documented JSON endpoint for
    third-party apps, so this provider is best-effort: it first checks static
    page data and then, when available, uses Playwright to render the interactive
    map and read the clicked-location panel.
    """
    lat_f = max(-90.0, min(90.0, float(lat)))
    lon_f = max(-180.0, min(180.0, float(lon)))
    source_url = lightpollutionmap_app_url(lat_f, lon_f)
    errors: list[str] = []

    methods = []
    if prefer_browser:
        methods.append(_fetch_with_playwright)
    methods.append(_fetch_static_page)
    if not prefer_browser:
        methods.append(_fetch_with_playwright)

    for method in methods:
        try:
            sqm, bortle, summary = method(lat_f, lon_f, timeout=timeout)
            if sqm is not None or bortle is not None:
                return SkyQualityLookupResult(
                    sqm=sqm,
                    bortle=bortle,
                    source="LightPollutionMap.app auto",
                    source_url=source_url,
                    fetched_at_utc=datetime.now(timezone.utc)
                    .replace(microsecond=0)
                    .isoformat()
                    .replace("+00:00", "Z"),
                    raw_summary=summary,
                )
            errors.append(f"{method.__name__}: no SQM/Bortle values found")
        except Exception as exc:
            errors.append(f"{method.__name__}: {exc}")

    raise SkyQualityLookupError("; ".join(errors[-3:]) or "No SQM/Bortle values found")
