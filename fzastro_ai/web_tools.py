import hashlib
import html
import json
import re
import tempfile
import time
from datetime import datetime
from importlib import import_module
from pathlib import Path
from urllib.parse import quote, quote_plus, urlparse

import requests

from .config import (
    RENDERED_PAGE_IMAGE_PREVIEW_MAX_BYTES,
    WEB_IMAGE_CACHE_DIR,
    WEB_IMAGE_DOWNLOAD_MAX_BYTES,
    WEB_SEARCH_HTML_MAX_BYTES,
    WEB_SEARCH_JSON_MAX_BYTES,
)
from .logging_utils import log_exception, log_warning, log_debug
from .network_utils import (
    DownloadTooLargeError as WebDownloadTooLargeError,
    get_limited_json,
    get_limited_text,
    read_limited_response_body as _read_limited_response_body,
    response_header_int as _response_header_int,
)
from .news_tools import perform_daily_news_search


def _load_pixmap(file_path):
    from PySide6.QtGui import QPixmap

    pixmap = QPixmap()
    pixmap.load(str(file_path))
    return pixmap


def _compact_playwright_error(error, max_chars=420):
    """Return a short one-line browser launch error for user-facing messages."""
    text = re.sub(r"\s+", " ", str(error or "")).strip()

    # Playwright missing-browser messages include a large box drawing block with
    # installation advice.  That advice is useful in source mode but noisy and
    # often wrong for a frozen desktop app, so keep the actionable root cause and
    # add our own app-specific recovery text later.
    text = text.split("╔", 1)[0].strip()

    if len(text) > int(max_chars):
        text = text[: int(max_chars) - 3].rstrip() + "..."

    return text or error.__class__.__name__


def _launch_playwright_chromium(playwright, *, headless=True):
    """Launch a Chromium-compatible browser with packaged and system fallbacks.

    A PyInstaller one-file build can contain Playwright's Python package and
    driver while still missing the downloaded Chromium payload.  In that case
    Playwright raises "Executable doesn't exist" from the temporary _MEI folder.
    Falling back to installed Microsoft Edge / Google Chrome keeps browser-
    backed URL tools usable on normal Windows machines, while still reporting a
    clear packaging/setup error when no compatible browser exists.
    """
    candidates = [
        ("bundled Playwright Chromium", {}),
        ("installed Microsoft Edge", {"channel": "msedge"}),
        ("installed Google Chrome", {"channel": "chrome"}),
    ]
    failures = []

    for label, kwargs in candidates:
        try:
            return playwright.chromium.launch(headless=headless, **kwargs)
        except Exception as exc:
            failures.append((label, exc))
            log_debug(f"Playwright browser launch candidate failed: {label}", exc)

    details = "; ".join(
        f"{label}: {_compact_playwright_error(exc)}" for label, exc in failures
    )
    raise RuntimeError(
        "Playwright browser is not available. The app could not start bundled "
        "Chromium, installed Microsoft Edge, or installed Google Chrome. For "
        "source-tree runs, run `python -m playwright install chromium` in the "
        "active Python 3.11 environment. For frozen EXE releases, rebuild after "
        "installing Playwright Chromium in the build environment or rely on an "
        "installed Edge/Chrome browser. Launch details: "
        f"{details}"
    )


def _compact_search_error(error, max_chars=260):
    text = re.sub(r"\s+", " ", str(error or "")).strip()
    if len(text) > int(max_chars):
        text = text[: int(max_chars) - 3].rstrip() + "..."
    return text or error.__class__.__name__


def _make_ddgs_client(DDGS):
    # Newer ddgs versions accept timeout=..., older versions do not.  Keep both
    # paths so source installs and frozen builds with pinned dependencies work.
    try:
        return DDGS(timeout=8)
    except TypeError:
        return DDGS()


def _ddgs_text_results(query, max_results=10):
    """Return text search results without letting one DDGS backend kill the app.

    DDGS can route through multiple engines.  A single provider timeout, commonly
    Yandex, should be logged as a warning and followed by another provider.
    """
    DDGS = import_module("ddgs").DDGS

    attempts = [
        ("duckduckgo", {"backend": "duckduckgo"}),
        ("bing", {"backend": "bing"}),
        ("auto", {}),
    ]
    errors = []

    for label, kwargs in attempts:
        try:
            with _make_ddgs_client(DDGS) as ddgs:
                try:
                    results = list(ddgs.text(query, max_results=max_results, **kwargs))
                except TypeError:
                    # Older ddgs releases may not support backend=.  Retry once
                    # with the old signature instead of failing the search tool.
                    if kwargs:
                        with _make_ddgs_client(DDGS) as fallback_ddgs:
                            results = list(
                                fallback_ddgs.text(query, max_results=max_results)
                            )
                    else:
                        raise

            if results:
                return results, errors

            errors.append(f"{label}: no results")

        except Exception as exc:
            clean_error = _compact_search_error(exc)
            errors.append(f"{label}: {clean_error}")
            log_warning(f"perform_web_search provider failed ({label}): {clean_error}")

    return [], errors


def perform_web_search(query, progress_callback=None):
    if "||" in query:
        return perform_daily_news_search(progress_callback=progress_callback)

    articles = []

    try:
        search_results, search_errors = _ddgs_text_results(query, max_results=10)

        if not search_results:
            if search_errors:
                log_warning(
                    "perform_web_search all providers failed: "
                    + "; ".join(search_errors)
                )
            return "No recent web results found. Search providers may have timed out."

        for item in search_results:
            title = item.get("title", "")
            snippet = item.get("body", "")
            url = item.get("href", "")

            if len(snippet.strip()) < 40:
                continue

            articles.append(
                f"Title: {title}\n" f"URL: {url}\n" f"Content:\n{snippet[:500]}"
            )

        if not articles:
            return "No recent web results found."

        return "[WEB ARTICLES]\n\n" + "\n\n---ARTICLE---\n\n".join(articles)

    except Exception as e:
        clean_error = _compact_search_error(e)
        log_warning(f"perform_web_search failed safely: {clean_error}")
        return f"Web search failed safely: {clean_error}"


def _bing_image_fallback_search(query, max_results=24):
    """Return Bing Images results using normal HTML when DDGS image search times out.

    DDGS can occasionally route image searches through DuckDuckGo endpoints that
    time out even when general internet access is fine.  This fallback keeps the
    user-facing "get me an image" command useful without changing the rest of
    the app's result scoring/downloading pipeline.
    """
    clean_query = re.sub(r"\s+", " ", str(query or "")).strip()

    if not clean_query:
        return []

    search_url = (
        "https://www.bing.com/images/search?"
        f"q={quote_plus(clean_query)}&form=HDRSC2&first=1"
    )

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    response_text = get_limited_text(
        search_url,
        max_bytes=WEB_SEARCH_HTML_MAX_BYTES,
        timeout=14,
        headers=headers,
    )

    from bs4 import BeautifulSoup

    soup = BeautifulSoup(response_text, "html.parser")
    results = []
    seen = set()

    def add_result(image_url, thumb_url="", title="", source_url=""):
        image_url = html.unescape(str(image_url or "")).strip()
        thumb_url = html.unescape(str(thumb_url or "")).strip()
        title = re.sub(r"\s+", " ", html.unescape(str(title or ""))).strip()
        source_url = html.unescape(str(source_url or "")).strip()

        if not image_url.startswith(("http://", "https://")):
            return

        if image_url in seen:
            return

        seen.add(image_url)
        results.append(
            {
                "image": image_url,
                "thumbnail": thumb_url,
                "title": title or clean_query,
                "source": "Bing Images",
                "url": source_url or search_url,
            }
        )

    # Bing stores the best image metadata as JSON inside a.iusc[m].
    for anchor in soup.select("a.iusc"):
        if len(results) >= int(max_results):
            break

        metadata_raw = anchor.get("m") or ""

        try:
            metadata = json.loads(metadata_raw)
        except Exception:
            metadata = {}

        add_result(
            metadata.get("murl"),
            metadata.get("turl"),
            metadata.get("t") or anchor.get("aria-label") or anchor.get_text(" "),
            metadata.get("purl"),
        )

    # Fallback parser for small Bing layout changes.
    if len(results) < max_results:
        for match in re.finditer(
            r'"murl"\s*:\s*"(https?://.*?)(?<!\\)"', response_text
        ):
            if len(results) >= int(max_results):
                break

            image_url = match.group(1).encode("utf-8").decode("unicode_escape")
            add_result(image_url, title=clean_query, source_url=search_url)

    return results


def _wikimedia_commons_image_fallback_search(query, max_results=24):
    """Return Wikimedia Commons image results through the official API.

    This is a stable fallback for simple requests like "image of a tree" when
    DDGS/DuckDuckGo image search returns no results or times out.  It also keeps
    the dependency chain simple: normal HTTPS + JSON, no browser scraping.
    """
    clean_query = re.sub(r"\s+", " ", str(query or "")).strip()

    if not clean_query:
        return []

    api_url = "https://commons.wikimedia.org/w/api.php"
    headers = {
        "User-Agent": (
            "FZAstroAI/1.0 (local desktop assistant; " "https://commons.wikimedia.org/)"
        ),
        "Accept": "application/json,text/plain,*/*",
    }
    params = {
        "action": "query",
        "generator": "search",
        "gsrsearch": clean_query,
        "gsrnamespace": 6,
        "gsrlimit": int(max_results),
        "prop": "imageinfo",
        "iiprop": "url|mime|size|extmetadata",
        "iiurlwidth": 1600,
        "format": "json",
        "formatversion": 2,
    }

    data = get_limited_json(
        api_url,
        params=params,
        timeout=14,
        headers=headers,
        max_bytes=WEB_SEARCH_JSON_MAX_BYTES,
    )

    pages = data.get("query", {}).get("pages", []) or []
    pages.sort(key=lambda item: int(item.get("index", 999999)))

    results = []
    seen = set()

    for page_info in pages:
        if len(results) >= int(max_results):
            break

        image_info_items = page_info.get("imageinfo") or []
        if not image_info_items:
            continue

        image_info = image_info_items[0]
        image_url = str(
            image_info.get("thumburl") or image_info.get("url") or ""
        ).strip()

        if not image_url.startswith(("http://", "https://")):
            continue

        lower_image_url = image_url.split("?", 1)[0].lower()
        if lower_image_url.endswith((".svg", ".gif", ".tif", ".tiff", ".ico")):
            continue

        if image_url in seen:
            continue

        seen.add(image_url)

        title = str(page_info.get("title") or clean_query).replace("File:", "").strip()
        description_url = str(image_info.get("descriptionurl") or "").strip()

        if not description_url:
            description_url = "https://commons.wikimedia.org/wiki/" + quote(
                str(page_info.get("title") or "").replace(" ", "_")
            )

        results.append(
            {
                "image": image_url,
                "thumbnail": image_info.get("thumburl") or image_url,
                "title": title,
                "source": "Wikimedia Commons",
                "url": description_url,
                "width": image_info.get("thumbwidth") or image_info.get("width"),
                "height": image_info.get("thumbheight") or image_info.get("height"),
                "_trusted_fallback": True,
            }
        )

    return results


def _result_has_target_word(item, target_words):
    """Return True when an image result appears to describe the requested target.

    Some providers occasionally return generic/trending image results after a
    timeout recovery.  If none of the returned results mention the target term,
    the app should keep trying fallback providers instead of stopping early with
    "No relevant web image found."
    """
    if not target_words:
        return True

    metadata = (
        f"{item.get('title', '')} "
        f"{item.get('source', '')} "
        f"{item.get('url', '')} "
        f"{item.get('image', '')} "
        f"{item.get('thumbnail', '')}"
    ).lower()

    return any(word in metadata for word in target_words)


def _append_unique_image_results(destination, provider_results, seen_urls):
    """Append unique image results while preserving provider metadata."""
    added = 0

    for item in provider_results or []:
        image_url = str(item.get("image") or item.get("thumbnail") or "").strip()

        if not image_url or image_url in seen_urls:
            continue

        seen_urls.add(image_url)
        destination.append(item)
        added += 1

    return added


def _clear_results_if_not_about_target(results, target_words, provider_name):
    """Drop a provider result batch if none of it appears relevant."""
    if not results or not target_words:
        return results

    if any(_result_has_target_word(item, target_words) for item in results):
        return results

    log_warning(
        f"perform_web_image_search {provider_name} returned results, "
        "but none matched the target words; trying fallback providers"
    )

    return []


def perform_web_image_search(query):
    original_query = re.sub(r"\s+", " ", query).strip()

    if not original_query:
        return "Web image search failed: empty query."

    search_query = original_query

    cleanup_patterns = [
        r"^\s*(?:get|find|fetch|show|give|search(?:\s+for)?|look\s+up)\s+(?:me\s+)?",
        r"^\s*(?:an?\s+|some\s+|the\s+)?(?:image|photo|picture|wallpaper)s?\s+(?:of\s+)?",
        r"\bfrom\s+(?:the\s+)?(?:web|internet|online)\b",
        r"\bon\s+(?:the\s+)?(?:web|internet|online)\b",
    ]

    for pattern in cleanup_patterns:
        search_query = re.sub(pattern, " ", search_query, flags=re.IGNORECASE)

    search_query = re.sub(r"[^A-Za-z0-9\s\-]", " ", search_query)

    search_query = re.sub(r"\s+", " ", search_query).strip()
    search_query = re.sub(
        r"^(?:a|an|the)\s+", "", search_query, flags=re.IGNORECASE
    ).strip()

    if not search_query:
        search_query = original_query

    # Catalog designations are easy for generic image engines to confuse with
    # product model numbers. Expand M31 to its astronomical name.
    if re.search(r"\bm\s*31\b", search_query, flags=re.IGNORECASE):
        search_query = re.sub(
            r"\bm\s*31\b",
            "M31 Andromeda",
            search_query,
            flags=re.IGNORECASE,
        )

        if "astrophotography" not in search_query.lower():
            search_query += " galaxy astrophotography"

    ignored_words = {
        "image",
        "images",
        "photo",
        "photos",
        "picture",
        "pictures",
        "wallpaper",
        "wallpapers",
        "from",
        "web",
        "internet",
        "online",
        "please",
        "show",
        "find",
        "give",
        "fetch",
    }

    target_words = [
        word.lower()
        for word in re.findall(r"[A-Za-z0-9]+", search_query)
        if len(word) >= 3 and word.lower() not in ignored_words
    ]

    search_queries = [search_query, f"{search_query} photograph"]

    all_results = []
    seen_urls = set()
    search_errors = []

    # A single Bing/DDGS timeout must not abort every query. Retry each query
    # independently with a fresh client, then continue to the next variation.
    try:
        from ddgs import DDGS
    except Exception as error:
        DDGS = None
        clean_error = re.sub(r"\s+", " ", str(error)).strip()
        search_errors.append(f"DDGS unavailable: {clean_error[:220]}")

    for current_query in search_queries:
        query_succeeded = False

        for attempt in range(2):
            if DDGS is None:
                break

            try:
                with DDGS() as ddgs:
                    results = list(
                        ddgs.images(
                            current_query,
                            safesearch="moderate",
                            max_results=20,
                        )
                    )

                query_succeeded = True

                _append_unique_image_results(all_results, results, seen_urls)

                if results:
                    break

            except Exception as error:
                log_debug(
                    "perform_web_image_search DDGS provider attempt failed; fallback will continue",
                    error,
                )
                clean_error = re.sub(r"\s+", " ", str(error)).strip()
                search_errors.append(
                    f"{current_query} (attempt {attempt + 1}): {clean_error[:220]}"
                )
                time.sleep(0.35)

        if query_succeeded and all_results:
            # One successful query is enough; the scorer below chooses the best image.
            break

    all_results = _clear_results_if_not_about_target(all_results, target_words, "DDGS")

    if not all_results:
        # DuckDuckGo/DDGS image search can intermittently time out or return
        # unrelated/trending images.  Before failing the user request, try a
        # normal Bing Images HTML fallback.
        for current_query in search_queries:
            try:
                fallback_results = _bing_image_fallback_search(current_query)

                if _append_unique_image_results(
                    all_results, fallback_results, seen_urls
                ):
                    break

            except Exception as error:
                log_debug(
                    "perform_web_image_search Bing fallback attempt failed; fallback will continue",
                    error,
                )
                clean_error = re.sub(r"\s+", " ", str(error)).strip()
                search_errors.append(
                    f"Bing fallback {current_query}: {clean_error[:220]}"
                )

    all_results = _clear_results_if_not_about_target(
        all_results, target_words, "Bing fallback"
    )

    if not all_results:
        # Final fallback: Wikimedia Commons official API.  This is especially
        # useful for generic requests such as trees, animals, galaxies,
        # locations, and public-domain/reference-style images.
        for current_query in search_queries:
            try:
                fallback_results = _wikimedia_commons_image_fallback_search(
                    current_query
                )

                if _append_unique_image_results(
                    all_results, fallback_results, seen_urls
                ):
                    break

            except Exception as error:
                log_debug(
                    "perform_web_image_search Wikimedia fallback attempt failed; fallback will continue",
                    error,
                )
                clean_error = re.sub(r"\s+", " ", str(error)).strip()
                search_errors.append(
                    f"Wikimedia fallback {current_query}: {clean_error[:220]}"
                )

    all_results = _clear_results_if_not_about_target(
        all_results, target_words, "Wikimedia fallback"
    )

    if not all_results:
        if search_errors:
            log_warning(
                "perform_web_image_search all providers failed",
                search_errors[-1],
            )
            return (
                "Web image search failed: no usable image results were returned "
                "by DuckDuckGo, Bing, or Wikimedia Commons. Last provider message: "
                + search_errors[-1]
            )

        log_warning("perform_web_image_search no provider returned image results")
        return "No web images found."

    bad_keywords = {
        "news",
        "logo",
        "banner",
        "header",
        "template",
        "icon",
        "sprite",
        "advert",
        "advertisement",
        "infographic",
        "world-news",
        "breaking-news",
        "placeholder",
        "poster",
        "movie",
        "walmart",
        "product",
    }

    scored_results = []

    for item in all_results:
        image_url = str(item.get("image") or item.get("thumbnail") or "").strip()

        source_url = str(item.get("url", "")).strip()

        title = str(item.get("title", "")).strip()

        source_name = str(item.get("source", "")).strip()

        if not image_url.startswith(("http://", "https://")):
            continue

        metadata = (
            f"{title} " f"{source_name} " f"{source_url} " f"{image_url}"
        ).lower()

        title_lower = title.lower()
        score = 0

        if item.get("_trusted_fallback"):
            score += 2

        for word in target_words:
            if word in title_lower:
                score += 12

            if word in metadata:
                score += 4

        bad_matches = [keyword for keyword in bad_keywords if keyword in metadata]

        if "m31" in target_words and not ("m31" in metadata or "andromeda" in metadata):
            continue

        title_matches_target = any(word in title_lower for word in target_words)

        if bad_matches and not title_matches_target:
            continue

        score -= len(bad_matches) * 8

        width = item.get("width")
        height = item.get("height")

        try:
            width_value = int(width)
            height_value = int(height)

            if width_value < 300 or height_value < 200:
                continue

            if width_value >= 800 and height_value >= 500:
                score += 3

        except (TypeError, ValueError):
            pass

        scored_results.append((score, item))

    scored_results.sort(key=lambda entry: entry[0], reverse=True)

    if not scored_results:
        log_warning(
            "perform_web_image_search providers returned images but none passed relevance scoring"
        )
        return "No relevant web image found."

    # Keep downloaded web images in the application data directory so an
    # assistant image remains available after the chat is saved, reloaded, or
    # Windows clears the temporary directory.
    cache_dir = WEB_IMAGE_CACHE_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)

    content_type_extensions = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }

    for score, item in scored_results:
        if target_words and score <= 0:
            continue

        image_url = str(item.get("image") or item.get("thumbnail") or "").strip()

        try:
            download_headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/149.0.0.0 Safari/537.36"
                ),
                "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            }

            referer_url = str(item.get("url", "")).strip()
            if referer_url.startswith(("http://", "https://")):
                download_headers["Referer"] = referer_url

            response = requests.get(
                image_url,
                timeout=18,
                headers=download_headers,
                allow_redirects=True,
                stream=True,
            )

            if response.status_code != 200:
                response.close()
                continue

            content_type = (
                response.headers.get("Content-Type", "")
                .split(";", 1)[0]
                .strip()
                .lower()
            )

            extension = content_type_extensions.get(content_type)

            if extension is None:
                response.close()
                continue

            image_bytes = _read_limited_response_body(
                response, WEB_IMAGE_DOWNLOAD_MAX_BYTES
            )

            if not image_bytes:
                continue

            file_hash = hashlib.md5(image_url.encode("utf-8")).hexdigest()

            file_path = cache_dir / f"{file_hash}{extension}"

            with open(file_path, "wb") as image_file:
                image_file.write(image_bytes)

            pixmap = _load_pixmap(file_path)

            if pixmap.isNull():
                try:
                    file_path.unlink()
                except Exception as exc:
                    log_debug(
                        "perform_web_image_search cached image cleanup failed", exc
                    )
                    pass

                continue

            if pixmap.width() < 300:
                continue

            if pixmap.height() < 200:
                continue

            title = str(item.get("title", "")).strip()

            source_url = str(item.get("url", "")).strip()

            source_name = str(item.get("source", "")).strip()

            result_lines = [
                "[WEB IMAGE]",
                f"ImageFile: {file_path}",
                f"ImageURL: {image_url}",
            ]

            if title:
                result_lines.append(f"Title: {title}")

            if source_name:
                result_lines.append(f"SourceName: {source_name}")

            if source_url:
                result_lines.append(f"SourceURL: {source_url}")

            result_lines.append(f"Dimensions: " f"{pixmap.width()}x{pixmap.height()}")

            return "\n".join(result_lines)

        except Exception as exc:
            log_debug(
                "perform_web_image_search candidate download failed; trying next candidate",
                exc,
            )
            continue

    log_warning(
        "perform_web_image_search no scored candidate produced a downloadable image"
    )
    return "No relevant downloadable web image found."


def perform_website_screenshot(request_text):
    clean_request = re.sub(r"\s+", " ", str(request_text)).strip()

    url_match = re.search(r"https?://[^\s<>'\"]+", clean_request, flags=re.IGNORECASE)

    if not url_match:
        return "Website screenshot failed: no HTTP or HTTPS URL was found."

    page_url = url_match.group(0).rstrip(".,;:!?)]}")

    parsed_url = urlparse(page_url)

    if parsed_url.scheme.lower() not in ("http", "https"):
        return "Website screenshot failed: unsupported URL scheme."

    if not parsed_url.netloc:
        return "Website screenshot failed: invalid website URL."

    full_page = bool(
        re.search(
            r"\b(?:full[\s-]*page|entire\s+page|whole\s+page)\b",
            clean_request,
            flags=re.IGNORECASE,
        )
    )

    cache_dir = Path(tempfile.gettempdir()) / "fzastro_web_screenshots"

    cache_dir.mkdir(parents=True, exist_ok=True)

    domain_name = re.sub(r"[^A-Za-z0-9._-]+", "_", parsed_url.netloc).strip("._-")

    if not domain_name:
        domain_name = "website"

    request_hash = hashlib.md5(
        (page_url + "|" + str(full_page) + "|" + str(time.time_ns())).encode("utf-8")
    ).hexdigest()[:16]

    file_path = cache_dir / f"{domain_name}_{request_hash}.png"

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = _launch_playwright_chromium(playwright, headless=True)

            context = browser.new_context(
                viewport={"width": 1440, "height": 1000},
                device_scale_factor=1,
                ignore_https_errors=True,
                java_script_enabled=True,
            )

            page = context.new_page()

            page.set_default_timeout(15000)

            page.goto(page_url, wait_until="domcontentloaded", timeout=30000)

            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception as exc:
                log_debug(
                    "Website screenshot did not reach networkidle; continuing after DOM load",
                    exc,
                )
                pass

            if full_page:
                try:
                    page.evaluate(
                        """
                        async () => {
                            const delay = ms =>
                                new Promise(resolve => setTimeout(resolve, ms));

                            const maximumHeight = Math.max(
                                document.documentElement.scrollHeight,
                                document.body
                                    ? document.body.scrollHeight
                                    : 0
                            );

                            const step = Math.max(
                                Math.floor(window.innerHeight * 0.8),
                                400
                            );

                            for (
                                let position = 0;
                                position < maximumHeight;
                                position += step
                            ) {
                                window.scrollTo(0, position);
                                await delay(150);
                            }

                            window.scrollTo(0, 0);
                            await delay(500);
                        }
                        """
                    )
                except Exception as exc:
                    log_exception("perform_website_screenshot line 3137", exc)
                    pass

            page.wait_for_timeout(1000)

            page_title = page.title().strip()
            final_url = page.url

            if full_page:
                dimensions = page.evaluate(
                    """
                    () => ({
                        width: Math.max(
                            document.documentElement.scrollWidth,
                            document.body
                                ? document.body.scrollWidth
                                : 0
                        ),
                        height: Math.max(
                            document.documentElement.scrollHeight,
                            document.body
                                ? document.body.scrollHeight
                                : 0
                        )
                    })
                    """
                )
            else:
                dimensions = {"width": 1440, "height": 1000}

            page.screenshot(
                path=str(file_path),
                full_page=full_page,
                animations="disabled",
                caret="hide",
            )

            context.close()
            browser.close()

    except Exception as e:
        log_exception("perform_website_screenshot line 3177", e)
        try:
            if file_path.exists():
                file_path.unlink()
        except Exception as exc:
            log_exception("perform_website_screenshot line 3181", exc)
            pass

        return "Website screenshot failed: " + str(e)

    if not file_path.exists():
        return "Website screenshot failed: screenshot file was not created."

    if file_path.stat().st_size == 0:
        try:
            file_path.unlink()
        except Exception as exc:
            log_exception("perform_website_screenshot line 3192", exc)
            pass

        return "Website screenshot failed: screenshot file is empty."

    result_lines = [
        "[WEB SCREENSHOT]",
        f"ImageFile: {file_path}",
        f"PageURL: {final_url}",
        ("CaptureMode: Full page" if full_page else "CaptureMode: Viewport"),
    ]

    if page_title:
        result_lines.append(f"Title: {page_title}")

    result_lines.append(
        f"Dimensions: "
        f"{dimensions.get('width', 1440)}"
        f"x"
        f"{dimensions.get('height', 1000)}"
    )

    return "\n".join(result_lines)


def safe_markdown_link_label(value, fallback="Link"):
    label = re.sub(r"\s+", " ", str(value or "")).strip()
    label = re.sub(r"[\[\]()]+", " ", label)
    label = re.sub(r"\s+", " ", label).strip(" -–—:;,.|")

    if not label:
        label = str(fallback or "Link").strip() or "Link"

    if len(label) > 140:
        label = label[:137].rstrip() + "..."

    return label


def download_rendered_page_image_previews(images, cache_dir, max_images=6):
    """Download a few real page images so extraction requests can show previews.

    The rendered-page extractor already lists every image URL.  This helper adds
    local image attachments for the first useful raster images, skipping logos,
    SVGs, TIFFs, tiny icons, and hidden elements.  The UI can then render the
    actual images through the existing ImagePreview widget.
    """
    preview_files = []
    seen_urls = set()
    preview_dir = Path(cache_dir) / "image_previews"
    preview_dir.mkdir(parents=True, exist_ok=True)

    extension_by_content_type = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }

    for image in images or []:
        if len(preview_files) >= int(max_images):
            break

        image_url = str(image.get("url", "")).strip()

        if not image_url.startswith(("http://", "https://")):
            continue

        if image_url in seen_urls:
            continue

        seen_urls.add(image_url)
        clean_path = image_url.split("?", 1)[0].lower()

        if clean_path.endswith((".svg", ".gif", ".tif", ".tiff", ".ico")):
            continue

        try:
            width_value = int(float(image.get("width", 0) or 0))
            height_value = int(float(image.get("height", 0) or 0))
        except Exception as exc:
            log_exception("download_rendered_page_image_previews line 3272", exc)
            width_value = 0
            height_value = 0

        if width_value and height_value and (width_value < 240 or height_value < 140):
            continue

        if image.get("visible") is False:
            continue

        try:
            response = requests.get(
                image_url,
                timeout=12,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/149.0.0.0 Safari/537.36"
                    ),
                    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
                },
                stream=True,
            )

            if response.status_code != 200:
                response.close()
                continue

            content_type = (
                response.headers.get("Content-Type", "")
                .split(";", 1)[0]
                .strip()
                .lower()
            )
            extension = extension_by_content_type.get(content_type)

            if extension is None:
                response.close()
                continue

            image_bytes = _read_limited_response_body(
                response, RENDERED_PAGE_IMAGE_PREVIEW_MAX_BYTES
            )

            if not image_bytes:
                continue

            file_hash = hashlib.md5(image_url.encode("utf-8")).hexdigest()
            file_path = preview_dir / f"rendered_{file_hash}{extension}"
            file_path.write_bytes(image_bytes)

            pixmap = _load_pixmap(file_path)

            if pixmap.isNull():
                try:
                    file_path.unlink()
                except Exception as exc:
                    log_exception(
                        "download_rendered_page_image_previews line 3322", exc
                    )
                    pass
                continue

            if pixmap.width() < 240 or pixmap.height() < 140:
                continue

            preview_files.append(str(file_path))
        except Exception as exc:
            log_exception("download_rendered_page_image_previews line 3330", exc)
            continue

    return preview_files


def perform_rendered_page_extraction(request_text):
    clean_request = re.sub(r"\s+", " ", str(request_text)).strip()

    url_match = re.search(r"https?://[^\s<>'\"]+", clean_request, flags=re.IGNORECASE)

    if not url_match:
        return "Rendered-page extraction failed: no HTTP or HTTPS URL was found."

    page_url = url_match.group(0).rstrip(".,;:!?)]}")

    parsed_url = urlparse(page_url)

    if parsed_url.scheme.lower() not in ("http", "https"):
        return "Rendered-page extraction failed: unsupported URL scheme."

    if not parsed_url.netloc:
        return "Rendered-page extraction failed: invalid website URL."

    cache_dir = Path(tempfile.gettempdir()) / "fzastro_rendered_pages"

    cache_dir.mkdir(parents=True, exist_ok=True)

    domain_name = re.sub(r"[^A-Za-z0-9._-]+", "_", parsed_url.netloc).strip("._-")

    if not domain_name:
        domain_name = "website"

    request_hash = hashlib.md5(
        (page_url + "|" + str(time.time_ns())).encode("utf-8")
    ).hexdigest()[:16]

    base_name = f"{domain_name}_{request_hash}"

    html_file = cache_dir / f"{base_name}.html"

    text_file = cache_dir / f"{base_name}.txt"

    json_file = cache_dir / f"{base_name}.json"

    browser = None
    context = None

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = _launch_playwright_chromium(playwright, headless=True)

            context = browser.new_context(
                viewport={"width": 1440, "height": 1000},
                device_scale_factor=1,
                ignore_https_errors=True,
                java_script_enabled=True,
            )

            page = context.new_page()

            page.set_default_timeout(15000)

            response = page.goto(page_url, wait_until="domcontentloaded", timeout=30000)

            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception as exc:
                log_debug(
                    "Rendered page did not reach networkidle; continuing after DOM load",
                    exc,
                )
                pass

            try:
                page.evaluate(
                    """
                    async () => {
                        const delay = ms =>
                            new Promise(resolve => setTimeout(resolve, ms));

                        const maximumHeight = Math.max(
                            document.documentElement.scrollHeight,
                            document.body
                                ? document.body.scrollHeight
                                : 0
                        );

                        const step = Math.max(
                            Math.floor(window.innerHeight * 0.8),
                            400
                        );

                        for (
                            let position = 0;
                            position < maximumHeight;
                            position += step
                        ) {
                            window.scrollTo(0, position);
                            await delay(150);
                        }

                        window.scrollTo(0, 0);
                        await delay(300);
                    }
                    """
                )
            except Exception as exc:
                log_exception("perform_rendered_page_extraction line 3433", exc)
                pass

            page_title = page.title().strip()
            final_url = page.url

            status_code = None

            if response is not None:
                try:
                    status_code = response.status
                except Exception as exc:
                    log_exception("perform_rendered_page_extraction line 3444", exc)
                    status_code = None

            visible_text = page.evaluate(
                """
                () => {
                    if (!document.body) {
                        return "";
                    }

                    return document.body.innerText || "";
                }
                """
            )

            visible_text = re.sub(r"\r\n?", "\n", str(visible_text or ""))

            visible_text = re.sub(r"[ \t]+\n", "\n", visible_text)

            visible_text = re.sub(r"\n{3,}", "\n\n", visible_text).strip()

            links = page.evaluate(
                """
                () => {
                    const results = [];
                    const seen = new Set();

                    for (
                        const anchor
                        of document.querySelectorAll("a[href]")
                    ) {
                        const href = anchor.href || "";

                        if (!href) {
                            continue;
                        }

                        if (
                            href.startsWith("javascript:")
                            || href.startsWith("mailto:")
                            || href.startsWith("tel:")
                        ) {
                            continue;
                        }

                        const text = (
                            anchor.innerText
                            || anchor.getAttribute("aria-label")
                            || anchor.getAttribute("title")
                            || ""
                        )
                            .replace(/\\s+/g, " ")
                            .trim();

                        const key = `${text}|${href}`;

                        if (seen.has(key)) {
                            continue;
                        }

                        seen.add(key);

                        results.push({
                            text: text,
                            url: href,
                            target:
                                anchor.getAttribute("target")
                                || ""
                        });
                    }

                    return results;
                }
                """
            )

            tables = page.evaluate(
                """
                () => {
                    return Array
                        .from(
                            document.querySelectorAll("table")
                        )
                        .map((table, tableIndex) => {
                            const captionElement =
                                table.querySelector("caption");

                            const caption = captionElement
                                ? (
                                    captionElement.innerText
                                    || ""
                                )
                                    .replace(/\\s+/g, " ")
                                    .trim()
                                : "";

                            const rows = Array
                                .from(
                                    table.querySelectorAll("tr")
                                )
                                .map(row => {
                                    return Array
                                        .from(
                                            row.querySelectorAll(
                                                "th, td"
                                            )
                                        )
                                        .map(cell => ({
                                            text: (
                                                cell.innerText
                                                || ""
                                            )
                                                .replace(
                                                    /\\s+/g,
                                                    " "
                                                )
                                                .trim(),
                                            type:
                                                cell.tagName
                                                    .toLowerCase(),
                                            colspan:
                                                Number(
                                                    cell.getAttribute(
                                                        "colspan"
                                                    )
                                                    || 1
                                                ),
                                            rowspan:
                                                Number(
                                                    cell.getAttribute(
                                                        "rowspan"
                                                    )
                                                    || 1
                                                )
                                        }));
                                })
                                .filter(
                                    row => row.length > 0
                                );

                            return {
                                index: tableIndex + 1,
                                caption: caption,
                                rows: rows
                            };
                        })
                        .filter(
                            table => table.rows.length > 0
                        );
                }
                """
            )

            images = page.evaluate(
                """
                () => {
                    const results = [];
                    const seen = new Set();

                    for (
                        const image
                        of document.querySelectorAll("img")
                    ) {
                        const source = (
                            image.currentSrc
                            || image.src
                            || ""
                        ).trim();

                        if (!source) {
                            continue;
                        }

                        if (seen.has(source)) {
                            continue;
                        }

                        seen.add(source);

                        const rectangle =
                            image.getBoundingClientRect();

                        const style =
                            window.getComputedStyle(image);

                        const visible = Boolean(
                            rectangle.width > 0
                            && rectangle.height > 0
                            && style.display !== "none"
                            && style.visibility !== "hidden"
                            && Number(style.opacity) !== 0
                        );

                        results.push({
                            url: source,
                            alt:
                                image.getAttribute("alt")
                                || "",
                            title:
                                image.getAttribute("title")
                                || "",
                            width:
                                image.naturalWidth
                                || Math.round(
                                    rectangle.width
                                ),
                            height:
                                image.naturalHeight
                                || Math.round(
                                    rectangle.height
                                ),
                            displayed_width:
                                Math.round(
                                    rectangle.width
                                ),
                            displayed_height:
                                Math.round(
                                    rectangle.height
                                ),
                            visible: visible
                        });
                    }

                    return results;
                }
                """
            )

            metadata = page.evaluate(
                """
                () => {
                    const getMeta = selector => {
                        const element =
                            document.querySelector(selector);

                        return element
                            ? (
                                element.getAttribute("content")
                                || ""
                            ).trim()
                            : "";
                    };

                    return {
                        description:
                            getMeta(
                                'meta[name="description"]'
                            ),
                        canonical_url:
                            (
                                document.querySelector(
                                    'link[rel="canonical"]'
                                )
                                || {}
                            ).href
                            || "",
                        language:
                            document.documentElement.lang
                            || "",
                        og_title:
                            getMeta(
                                'meta[property="og:title"]'
                            ),
                        og_description:
                            getMeta(
                                'meta[property="og:description"]'
                            ),
                        og_image:
                            getMeta(
                                'meta[property="og:image"]'
                            )
                    };
                }
                """
            )

            rendered_html = page.content()

            extraction_data = {
                "requested_url": page_url,
                "final_url": final_url,
                "title": page_title,
                "status_code": status_code,
                "extracted_at": datetime.now().isoformat(),
                "metadata": metadata,
                "visible_text": visible_text,
                "links": links,
                "tables": tables,
                "images": images,
            }

            with open(html_file, "w", encoding="utf-8") as file:
                file.write(rendered_html)

            with open(text_file, "w", encoding="utf-8") as file:
                file.write(visible_text)

            with open(json_file, "w", encoding="utf-8") as file:
                json.dump(extraction_data, file, ensure_ascii=False, indent=2)

            context.close()
            context = None

            browser.close()
            browser = None

    except Exception as e:
        log_exception("perform_rendered_page_extraction line 3750", e)
        try:
            if context is not None:
                context.close()
        except Exception as exc:
            log_exception("perform_rendered_page_extraction line 3754", exc)
            pass

        try:
            if browser is not None:
                browser.close()
        except Exception as exc:
            log_exception("perform_rendered_page_extraction line 3760", exc)
            pass

        for output_file in (html_file, text_file, json_file):
            try:
                if output_file.exists():
                    output_file.unlink()
            except Exception as exc:
                log_exception("perform_rendered_page_extraction line 3767", exc)
                pass

        return "Rendered-page extraction failed: " + str(e)

    if not json_file.exists():
        return "Rendered-page extraction failed: structured output was not created."

    link_preview_lines = []

    for link in links[:50]:
        link_text = re.sub(r"\s+", " ", str(link.get("text", ""))).strip()

        link_url = str(link.get("url", "")).strip()

        if not link_url:
            continue

        link_label = safe_markdown_link_label(link_text, "Open link")
        link_preview_lines.append(f"- [{link_label}]({link_url})")

    table_preview_lines = []

    for table in tables[:10]:
        table_number = table.get("index", len(table_preview_lines) + 1)

        caption = str(table.get("caption", "")).strip()

        if caption:
            table_preview_lines.append(f"Table {table_number}: {caption}")
        else:
            table_preview_lines.append(f"Table {table_number}")

        for row in table.get("rows", [])[:20]:
            values = [
                re.sub(r"\s+", " ", str(cell.get("text", ""))).strip() for cell in row
            ]

            values = [value for value in values if value]

            if values:
                table_preview_lines.append(" | ".join(values))

    image_preview_lines = []

    for image in images[:50]:
        image_url = str(image.get("url", "")).strip()

        if not image_url:
            continue

        alt_text = re.sub(r"\s+", " ", str(image.get("alt", ""))).strip()

        dimensions = f"{image.get('width', 0)}" f"x" f"{image.get('height', 0)}"

        image_label = safe_markdown_link_label(
            alt_text,
            f"Image {len(image_preview_lines) + 1}",
        )

        image_preview_lines.append(f"- [{image_label}]({image_url}) ({dimensions})")

    wants_image_previews = bool(
        re.search(
            r"\b(?:image|images|photo|photos|picture|pictures)\b",
            clean_request,
            flags=re.IGNORECASE,
        )
    )

    image_preview_files = (
        download_rendered_page_image_previews(images, cache_dir, max_images=6)
        if wants_image_previews
        else []
    )

    result_lines = [
        "[RENDERED PAGE]",
        f"RequestedURL: {page_url}",
        f"FinalURL: {final_url}",
        f"Title: {page_title}",
        f"StatusCode: {status_code}",
        f"VisibleTextFile: {text_file}",
        f"RenderedHTMLFile: {html_file}",
        f"StructuredJSONFile: {json_file}",
        f"VisibleTextCharacters: {len(visible_text)}",
        f"LinkCount: {len(links)}",
        f"TableCount: {len(tables)}",
        f"ImageCount: {len(images)}",
    ]

    for image_preview_file in image_preview_files:
        result_lines.append(f"ImageFile: {image_preview_file}")

    result_lines.extend(
        [
            "",
            "[VISIBLE TEXT]",
            visible_text[:12000],
        ]
    )

    if link_preview_lines:
        result_lines.extend(["", "[LINKS]", "\n".join(link_preview_lines)])

    if table_preview_lines:
        result_lines.extend(["", "[TABLES]", "\n".join(table_preview_lines)])

    if image_preview_lines:
        result_lines.extend(["", "[IMAGES]", "\n".join(image_preview_lines)])

    return "\n".join(result_lines)
