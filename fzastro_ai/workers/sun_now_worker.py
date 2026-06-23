from __future__ import annotations

import json
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlencode

from PySide6.QtCore import QThread, Signal

from ..config import APP_DIR
from ..json_store import atomic_write_json
from ..logging_utils import log_debug, log_exception, log_warning
from ..network_utils import get_limited_json, get_limited_response, get_limited_text

SUN_NOW_CACHE_DIR = APP_DIR / "sun_now"
SDO_LATEST_BASE_URL = "https://sdo.gsfc.nasa.gov/assets/img/latest"
SDO_LATEST_MOVIE_BASE_URL = "https://sdo.gsfc.nasa.gov/assets/img/latest/mpeg"
SDO_FEEDS_BASE_URL = "https://sdo.gsfc.nasa.gov/feeds"
SDO_DASHBOARD_URL = "https://sdo.gsfc.nasa.gov/data/dashboard/"
SDO_FEEDS_PAGE_URL = "https://sdo.gsfc.nasa.gov/resources/feeds.php"
SDO_MISSION_BLOG_RSS_URL = "https://sdoisgo.blogspot.com/feeds/posts/default?alt=rss"
SWPC_RSS_URL = "https://www.swpc.noaa.gov/rss.xml"
HELIOVIEWER_CLOSEST_IMAGE_URL = "https://api.helioviewer.org/v1/getClosestImage/"
REQUEST_HEADERS = {
    "User-Agent": "FZAstroAI/1.0 SUN-NOW (+https://github.com/Ghostaka1978/FZAstroAI)",
}


@dataclass(frozen=True)
class SunNowChannel:
    key: str
    label: str
    image_code: str
    observatory: str
    instrument: str
    detector: str
    measurement: str
    description: str
    interpretation: str
    feed_code: str = ""

    def image_url(self, resolution: int) -> str:
        safe_resolution = max(512, min(4096, int(resolution)))
        return f"{SDO_LATEST_BASE_URL}/latest_{safe_resolution}_{self.image_code}.jpg"

    def data_feed_url(self) -> str:
        code = str(self.feed_code or self.image_code).strip()
        if code.upper().startswith("HMI"):
            code = code.lower()
        else:
            code = f"aia_{code.zfill(4)}"
        return f"{SDO_FEEDS_BASE_URL}/{code}.rss"

    def movie_feed_url(self) -> str:
        code = str(self.feed_code or self.image_code).strip()
        return f"{SDO_FEEDS_BASE_URL}/dailymov_{code}.rss"

    def latest_movie_url(self, resolution: int = 1024) -> str:
        safe_resolution = max(512, min(2048, int(resolution or 1024)))
        if safe_resolution not in {512, 1024, 2048}:
            safe_resolution = 1024
        code = str(self.feed_code or self.image_code).strip()
        return f"{SDO_LATEST_MOVIE_BASE_URL}/latest_{safe_resolution}_{code}.mp4"


SUN_NOW_CHANNELS: tuple[SunNowChannel, ...] = (
    SunNowChannel(
        key="aia_0171",
        label="AIA 171 Å · corona loops",
        image_code="0171",
        observatory="SDO",
        instrument="AIA",
        detector="AIA",
        measurement="171",
        description="Extreme ultraviolet view of the quiet corona and magnetic loops.",
        interpretation="Best for coronal loops, active-region structure, and quiet corona context.",
    ),
    SunNowChannel(
        key="aia_0193",
        label="AIA 193 Å · corona / flares",
        image_code="0193",
        observatory="SDO",
        instrument="AIA",
        detector="AIA",
        measurement="193",
        description="Extreme ultraviolet view of hot coronal plasma and active regions.",
        interpretation="Good default for coronal holes, active regions, and flare-hot plasma context.",
    ),
    SunNowChannel(
        key="aia_0211",
        label="AIA 211 Å · active regions",
        image_code="0211",
        observatory="SDO",
        instrument="AIA",
        detector="AIA",
        measurement="211",
        description="Extreme ultraviolet view of warmer coronal plasma.",
        interpretation="Useful for bright active-region arcades and coronal-hole contrast.",
    ),
    SunNowChannel(
        key="aia_0304",
        label="AIA 304 Å · prominences",
        image_code="0304",
        observatory="SDO",
        instrument="AIA",
        detector="AIA",
        measurement="304",
        description="Extreme ultraviolet chromosphere and transition-region view.",
        interpretation="Best for prominences, filaments, limb activity, and eruptive material.",
    ),
    SunNowChannel(
        key="aia_0335",
        label="AIA 335 Å · hot corona",
        image_code="0335",
        observatory="SDO",
        instrument="AIA",
        detector="AIA",
        measurement="335",
        description="Extreme ultraviolet hot-corona channel.",
        interpretation="Useful for hot active-region loops and post-flare coronal structure.",
    ),
    SunNowChannel(
        key="aia_0094",
        label="AIA 94 Å · flare plasma",
        image_code="0094",
        observatory="SDO",
        instrument="AIA",
        detector="AIA",
        measurement="94",
        description="Extreme ultraviolet high-temperature flare-sensitive channel.",
        interpretation="Best for very hot flare plasma and compact active-region cores.",
    ),
    SunNowChannel(
        key="aia_0131",
        label="AIA 131 Å · flares",
        image_code="0131",
        observatory="SDO",
        instrument="AIA",
        detector="AIA",
        measurement="131",
        description="Extreme ultraviolet flare-sensitive channel.",
        interpretation="Useful for flare loops, eruptions, and very hot coronal plasma.",
    ),
    SunNowChannel(
        key="aia_1600",
        label="AIA 1600 Å · lower atmosphere",
        image_code="1600",
        observatory="SDO",
        instrument="AIA",
        detector="AIA",
        measurement="1600",
        description="Ultraviolet lower-atmosphere and transition-region view.",
        interpretation="Useful for flare ribbons and photosphere/chromosphere transition context.",
    ),
    SunNowChannel(
        key="hmi_mag",
        label="HMI magnetogram · magnetic field",
        image_code="HMIB",
        observatory="SDO",
        instrument="HMI",
        detector="HMI",
        measurement="magnetogram",
        description="Photospheric line-of-sight magnetic-field quick-look map.",
        interpretation="White/black polarity patterns show magnetic complexity around active regions.",
    ),
    SunNowChannel(
        key="hmi_mag_color",
        label="HMI color magnetogram",
        image_code="HMIBC",
        observatory="SDO",
        instrument="HMI",
        detector="HMI",
        measurement="magnetogram",
        description="Colorized quick-look photospheric magnetic-field map.",
        interpretation="Color helps separate strong positive and negative magnetic polarity zones.",
    ),
    SunNowChannel(
        key="hmi_continuum",
        label="HMI continuum · sunspots",
        image_code="HMII",
        observatory="SDO",
        instrument="HMI",
        detector="HMI",
        measurement="continuum",
        description="Visible-light photosphere quick-look image.",
        interpretation="Best for sunspot groups and white-light photospheric structure.",
    ),
    SunNowChannel(
        key="hmi_doppler",
        label="HMI dopplergram",
        image_code="HMID",
        observatory="SDO",
        instrument="HMI",
        detector="HMI",
        measurement="dopplergram",
        description="Photospheric Doppler velocity quick-look map.",
        interpretation="Shows line-of-sight motion patterns across the solar photosphere.",
    ),
)

SUN_NOW_CHANNEL_BY_KEY = {channel.key: channel for channel in SUN_NOW_CHANNELS}
SUN_NOW_RESOLUTIONS = (1024, 2048, 512)
SUN_NOW_MODES = ("image", "movie")
SUN_NOW_NEWS_CACHE = SUN_NOW_CACHE_DIR / "solar_news.json"


def normalise_sun_mode(value: Any) -> str:
    mode = str(value or "image").strip().lower()
    return mode if mode in SUN_NOW_MODES else "image"


def normalise_sun_channel(value: str | None) -> SunNowChannel:
    key = str(value or "").strip()
    return SUN_NOW_CHANNEL_BY_KEY.get(key, SUN_NOW_CHANNELS[0])


def normalise_sun_resolution(value: Any) -> int:
    try:
        resolution = int(value)
    except Exception:
        resolution = 1024
    if resolution not in SUN_NOW_RESOLUTIONS:
        resolution = 1024
    return resolution


def _safe_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "")).strip("_") or "sun"


def _header_timestamp(headers: Any) -> str:
    for key in ("Last-Modified", "Date"):
        value = str(headers.get(key, "") or "").strip()
        if value:
            return value
    return ""


def _utc_now_for_helioviewer() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _cached_image_path(channel: SunNowChannel, resolution: int) -> Path:
    return SUN_NOW_CACHE_DIR / f"{_safe_filename(channel.key)}_{int(resolution)}.jpg"


def _metadata_path(channel: SunNowChannel, resolution: int) -> Path:
    return SUN_NOW_CACHE_DIR / f"{_safe_filename(channel.key)}_{int(resolution)}.json"


def _load_cached_metadata(path: Path) -> dict[str, Any]:
    try:
        if path.exists():
            with path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                return data
    except Exception as exc:
        log_debug("SunNowWorker cache metadata load skipped", exc)
    return {}


def _write_json(path: Path, payload: dict[str, Any]):
    atomic_write_json(path, payload, indent=2)


def _strip_rss_html(value: str, limit: int = 260) -> str:
    clean = re.sub(r"<[^>]+>", " ", str(value or ""))
    clean = re.sub(r"\s+", " ", clean).strip()
    if len(clean) > int(limit):
        clean = clean[: int(limit) - 1].rstrip() + "…"
    return clean


def _parse_rss_items(
    xml_text: str, *, source: str, limit: int = 8
) -> list[dict[str, Any]]:
    text = str(xml_text or "").strip()
    if not text:
        return []
    try:
        root = ET.fromstring(text)
    except Exception as exc:
        log_debug("SunNowWorker RSS parse skipped", exc)
        return []

    items = []
    ns_media = "{http://search.yahoo.com/mrss/}"
    ns_atom = "{http://www.w3.org/2005/Atom}"
    for node in list(root.findall("./channel/item")) + list(
        root.findall(f".//{ns_atom}entry")
    ):

        def child_text(*names: str) -> str:
            for name in names:
                child = node.find(name)
                if child is not None and child.text:
                    return str(child.text).strip()
            return ""

        title = child_text("title", f"{ns_atom}title")
        link = child_text("link")
        if not link:
            atom_link = node.find(f"{ns_atom}link")
            if atom_link is not None:
                link = str(atom_link.attrib.get("href") or "").strip()
        published = child_text("pubDate", f"{ns_atom}updated", f"{ns_atom}published")
        summary = child_text("description", f"{ns_atom}summary", f"{ns_atom}content")
        media_url = ""
        media_type = ""
        for enc in node.findall("enclosure"):
            media_url = str(enc.attrib.get("url") or "").strip()
            media_type = str(enc.attrib.get("type") or "").strip()
            if media_url:
                break
        if not media_url:
            for media in node.findall(f"{ns_media}content"):
                media_url = str(media.attrib.get("url") or "").strip()
                media_type = str(media.attrib.get("type") or "").strip()
                if media_url:
                    break
        if not media_url:
            for media in node.findall(f"{ns_media}thumbnail"):
                media_url = str(media.attrib.get("url") or "").strip()
                media_type = str(media.attrib.get("type") or "").strip()
                if media_url:
                    break
        item = {
            "title": _strip_rss_html(title, 140) or source,
            "link": urljoin(SDO_FEEDS_BASE_URL + "/", link) if link else "",
            "published": _strip_rss_html(published, 120),
            "summary": _strip_rss_html(summary),
            "media_url": (
                urljoin(SDO_FEEDS_BASE_URL + "/", media_url) if media_url else ""
            ),
            "media_type": media_type,
            "source": source,
        }
        if item["title"] or item["link"] or item["media_url"]:
            items.append(item)
        if len(items) >= int(limit):
            break
    return items


def _fetch_rss_items(
    url: str, *, source: str, limit: int = 8, timeout: int = 12
) -> list[dict[str, Any]]:
    try:
        text = get_limited_text(
            str(url),
            max_bytes=768 * 1024,
            timeout=timeout,
            headers=REQUEST_HEADERS,
        )
        return _parse_rss_items(text, source=source, limit=limit)
    except Exception as exc:
        log_debug(f"SunNowWorker RSS unavailable: {url}", exc)
        return []


def _cache_news_items(items: list[dict[str, Any]]):
    try:
        SUN_NOW_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _write_json(
            SUN_NOW_NEWS_CACHE,
            {"items": list(items or []), "updated": _utc_now_for_helioviewer()},
        )
    except Exception as exc:
        log_debug("SunNowWorker news cache write skipped", exc)


def _load_cached_news_items() -> list[dict[str, Any]]:
    try:
        data = _load_cached_metadata(SUN_NOW_NEWS_CACHE)
        items = data.get("items") if isinstance(data, dict) else []
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    except Exception as exc:
        log_debug("SunNowWorker news cache read skipped", exc)
    return []


def load_solar_news(limit: int = 8) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    # Mission blog gives SDO-specific events. SWPC gives broader operational alerts/warnings.
    items.extend(
        _fetch_rss_items(
            SDO_MISSION_BLOG_RSS_URL,
            source="SDO Mission Blog",
            limit=max(3, int(limit)),
        )
    )
    items.extend(
        _fetch_rss_items(SWPC_RSS_URL, source="NOAA SWPC", limit=max(3, int(limit)))
    )

    deduped: list[dict[str, Any]] = []
    seen = set()
    for item in items:
        key = (str(item.get("title") or ""), str(item.get("link") or ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
        if len(deduped) >= int(limit):
            break
    if deduped:
        _cache_news_items(deduped)
        return deduped
    return _load_cached_news_items()[: int(limit)]


def _movie_cache_path(channel: SunNowChannel, resolution: int = 1024) -> Path:
    return (
        SUN_NOW_CACHE_DIR
        / f"{_safe_filename(channel.key)}_{int(resolution)}_latest_movie.mp4"
    )


def _movie_metadata_path(channel: SunNowChannel, resolution: int = 1024) -> Path:
    return (
        SUN_NOW_CACHE_DIR
        / f"{_safe_filename(channel.key)}_{int(resolution)}_latest_movie.json"
    )


def _select_movie_item(items: list[dict[str, Any]]) -> dict[str, Any]:
    for item in items:
        media_url = str(item.get("media_url") or "").strip()
        lower = media_url.lower()
        if media_url and any(ext in lower for ext in (".mp4", ".mov", ".m4v", ".webm")):
            return item
    for item in items:
        if str(item.get("media_url") or "").strip():
            return item
    return items[0] if items else {}


def _download_sdo_movie(
    movie_url: str, cache_path: Path
) -> tuple[Path, dict[str, Any]]:
    response, body = get_limited_response(
        movie_url,
        max_bytes=160 * 1024 * 1024,
        timeout=45,
        headers=REQUEST_HEADERS,
    )
    if not body:
        raise ValueError("NASA/SDO returned an empty movie")
    SUN_NOW_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    suffix = Path(str(movie_url).split("?", 1)[0]).suffix.lower() or ".mp4"
    if suffix not in {".mp4", ".mov", ".m4v", ".webm"}:
        suffix = ".mp4"
    final_path = cache_path.with_suffix(suffix)
    tmp_path = final_path.with_suffix(final_path.suffix + ".tmp")
    tmp_path.write_bytes(body)
    tmp_path.replace(final_path)
    return final_path, {
        "bytes": len(body),
        "last_modified": _header_timestamp(response.headers),
        "media_type": response.headers.get("Content-Type", "video/mp4"),
    }


def load_sun_now_movie(
    channel_key: str | None = None, resolution: Any = 1024
) -> dict[str, Any]:
    channel = normalise_sun_channel(channel_key)
    movie_resolution = normalise_sun_resolution(resolution)
    feed_url = channel.movie_feed_url()
    latest_movie_url = channel.latest_movie_url(movie_resolution)
    cache_path = _movie_cache_path(channel, movie_resolution)
    metadata_file = _movie_metadata_path(channel, movie_resolution)
    cache_metadata = _load_cached_metadata(metadata_file)

    result: dict[str, Any] = {
        "mode": "movie",
        "channel_key": channel.key,
        "label": f"{channel.label} · recent movie loop",
        "observatory": channel.observatory,
        "instrument": channel.instrument,
        "detector": channel.detector,
        "measurement": channel.measurement,
        "description": channel.description,
        "interpretation": f"Looping recent SDO movie for {channel.label}.",
        "resolution": movie_resolution,
        "source": "NASA/SDO latest MPEG movie",
        "source_url": latest_movie_url,
        "feed_url": feed_url,
        "latest_movie_url": latest_movie_url,
        "image_path": str(cache_path),
        "media_path": str(cache_path),
        "media_type": "video/mp4",
        "cache_used": False,
        "bytes": 0,
        "last_modified": "",
        "helioviewer_date": "",
        "helioviewer_id": "",
        "status_note": "",
        "movie_title": "Recent SDO movie loop",
        "movie_url": latest_movie_url,
        "rss_items": [],
    }

    # The RSS daily-movie feeds are useful for discovery, but some feed entries
    # have historically lagged or exposed stale archive dates. Prefer the SDO
    # current MPEG endpoint, then keep RSS as a fallback source.
    try:
        final_path, movie_meta = _download_sdo_movie(latest_movie_url, cache_path)
        result.update(movie_meta)
        result["image_path"] = str(final_path)
        result["media_path"] = str(final_path)
        result["movie_url"] = latest_movie_url
        result["source_url"] = latest_movie_url
        result["source"] = "NASA/SDO latest MPEG movie"
        result["status_note"] = "Fresh NASA/SDO recent MPEG movie loaded."
        _write_json(metadata_file, result)
        return result
    except Exception as latest_exc:
        log_warning("SunNowWorker NASA/SDO latest movie fetch failed", latest_exc)
        result["status_note"] = (
            f"Latest MPEG fetch failed, trying RSS fallback: {latest_exc}"
        )

    items = _fetch_rss_items(feed_url, source="SDO Daily Movie", limit=8, timeout=14)
    result["rss_items"] = items
    movie_item = _select_movie_item(items)
    rss_movie_url = str(
        movie_item.get("media_url") or movie_item.get("link") or ""
    ).strip()
    if rss_movie_url:
        try:
            final_path, movie_meta = _download_sdo_movie(rss_movie_url, cache_path)
            result.update(movie_meta)
            result["image_path"] = str(final_path)
            result["media_path"] = str(final_path)
            result["movie_url"] = rss_movie_url
            result["movie_title"] = str(movie_item.get("title") or "SDO daily movie")
            result["source"] = "NASA/SDO daily movie RSS fallback"
            result["source_url"] = feed_url
            result["media_type"] = str(
                movie_item.get("media_type") or result.get("media_type") or "video/mp4"
            )
            result["status_note"] = "Fresh NASA/SDO RSS daily movie fallback loaded."
            _write_json(metadata_file, result)
            return result
        except Exception as rss_exc:
            log_warning("SunNowWorker NASA/SDO RSS movie fetch failed", rss_exc)
            result["status_note"] = (
                f"Latest MPEG and RSS movie fetches failed: {rss_exc}"
            )

    cached_candidates = [
        cache_path,
        cache_path.with_suffix(".mp4"),
        cache_path.with_suffix(".mov"),
        cache_path.with_suffix(".m4v"),
        cache_path.with_suffix(".webm"),
    ]
    cached = next(
        (
            path
            for path in cached_candidates
            if path.exists() and path.stat().st_size > 0
        ),
        None,
    )
    if cached is not None:
        result.update(cache_metadata)
        result["media_path"] = str(cached)
        result["image_path"] = str(cached)
        result["source_url"] = str(result.get("source_url") or latest_movie_url)
        result["cache_used"] = True
        result["status_note"] = str(
            result.get("status_note")
            or "Using cached SDO movie because live movie download failed."
        )
        return result
    raise ValueError("SDO movie sources did not return a playable media URL")


def _fetch_helioviewer_metadata(channel: SunNowChannel) -> dict[str, Any]:
    query = urlencode(
        {
            "date": _utc_now_for_helioviewer(),
            "observatory": channel.observatory,
            "instrument": channel.instrument,
            "detector": channel.detector,
            "measurement": channel.measurement,
        }
    )
    url = f"{HELIOVIEWER_CLOSEST_IMAGE_URL}?{query}"
    try:
        payload = get_limited_json(
            url,
            max_bytes=128 * 1024,
            timeout=12,
            headers=REQUEST_HEADERS,
        )
        if isinstance(payload, dict):
            return payload
    except Exception as exc:
        log_debug("SunNowWorker Helioviewer metadata unavailable", exc)
    return {}


def load_sun_now_image(
    channel_key: str | None = None, resolution: Any = 1024
) -> dict[str, Any]:
    channel = normalise_sun_channel(channel_key)
    image_resolution = normalise_sun_resolution(resolution)
    image_url = channel.image_url(image_resolution)
    cache_path = _cached_image_path(channel, image_resolution)
    metadata_file = _metadata_path(channel, image_resolution)
    cache_metadata = _load_cached_metadata(metadata_file)

    result: dict[str, Any] = {
        "mode": "image",
        "channel_key": channel.key,
        "label": channel.label,
        "observatory": channel.observatory,
        "instrument": channel.instrument,
        "detector": channel.detector,
        "measurement": channel.measurement,
        "description": channel.description,
        "interpretation": channel.interpretation,
        "resolution": image_resolution,
        "source": "NASA/SDO latest image",
        "source_url": image_url,
        "image_path": str(cache_path),
        "cache_used": False,
        "bytes": 0,
        "last_modified": "",
        "helioviewer_date": "",
        "helioviewer_id": "",
        "status_note": "",
    }

    helioviewer_payload = _fetch_helioviewer_metadata(channel)
    if helioviewer_payload:
        result["helioviewer_date"] = str(helioviewer_payload.get("date") or "")
        result["helioviewer_id"] = str(helioviewer_payload.get("id") or "")

    try:
        response, body = get_limited_response(
            image_url,
            max_bytes=20 * 1024 * 1024,
            timeout=25,
            headers=REQUEST_HEADERS,
        )
        if not body:
            raise ValueError("NASA/SDO returned an empty image")

        SUN_NOW_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp_path = cache_path.with_suffix(cache_path.suffix + ".tmp")
        tmp_path.write_bytes(body)
        tmp_path.replace(cache_path)

        result["bytes"] = len(body)
        result["last_modified"] = _header_timestamp(response.headers)
        if not result["last_modified"]:
            result["last_modified"] = cache_metadata.get("last_modified", "")
        result["status_note"] = "Fresh NASA/SDO image loaded."
        _write_json(metadata_file, result)
        return result
    except Exception as exc:
        log_warning("SunNowWorker NASA/SDO image fetch failed", exc)
        if cache_path.exists() and cache_path.stat().st_size > 0:
            result.update(cache_metadata)
            result["image_path"] = str(cache_path)
            result["source_url"] = image_url
            result["cache_used"] = True
            result["status_note"] = (
                f"Using cached SUN NOW image because live download failed: {exc}"
            )
            return result
        raise


def load_sun_now(
    channel_key: str | None = None, resolution: Any = 1024, mode: Any = "image"
) -> dict[str, Any]:
    if normalise_sun_mode(mode) == "movie":
        result = load_sun_now_movie(channel_key, resolution)
    else:
        result = load_sun_now_image(channel_key, resolution)
    result["news_items"] = load_solar_news(limit=8)
    result["sdo_dashboard_url"] = SDO_DASHBOARD_URL
    result["sdo_feeds_page_url"] = SDO_FEEDS_PAGE_URL
    result["sdo_mission_blog_rss_url"] = SDO_MISSION_BLOG_RSS_URL
    result["swpc_rss_url"] = SWPC_RSS_URL
    return result


class SunNowWorker(QThread):
    """Load latest NASA/SDO solar imagery away from the Qt UI thread."""

    finished_sun_now = Signal(dict, float, bool)
    error_received = Signal(str)

    def __init__(
        self,
        channel_key: str | None = None,
        resolution: Any = 1024,
        mode: Any = "image",
    ):
        super().__init__()
        self.channel_key = str(channel_key or "").strip()
        self.resolution = resolution
        self.mode = normalise_sun_mode(mode)
        self.stop_requested = False

    def stop(self):
        self.stop_requested = True
        try:
            self.requestInterruption()
        except Exception:
            pass

    def should_stop(self) -> bool:
        return bool(self.stop_requested or self.isInterruptionRequested())

    def run(self):
        start = time.perf_counter()
        try:
            if self.should_stop():
                return
            result = load_sun_now(self.channel_key, self.resolution, self.mode)
            if self.should_stop():
                return
            elapsed = max(0.0, time.perf_counter() - start)
            self.finished_sun_now.emit(result, elapsed, True)
        except Exception as error:
            if self.should_stop():
                return
            log_exception("SunNowWorker.run", error)
            self.error_received.emit(str(error))
