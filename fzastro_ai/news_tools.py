import html
import json
import re
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone


from .config import (
    DAILY_NEWS_BRIEF_ITEMS_PER_SECTION,
    DAILY_NEWS_CACHE_FILE,
    DAILY_NEWS_CACHE_MAX_AGE_SECONDS,
    DAILY_NEWS_MAX_ITEMS_PER_SECTION,
    DAILY_NEWS_RSS_TIMEOUT_SECONDS,
    DAILY_NEWS_RSS_MAX_BYTES,
)
from .logging_utils import log_exception
from .network_utils import get_limited_text


def daily_news_rss_map():
    return {
        "World": "https://news.google.com/rss/headlines/section/topic/WORLD?hl=en-US&gl=US&ceid=US:en",
        "Europe": "https://news.google.com/rss/search?q=Europe+latest+news&hl=en-US&gl=US&ceid=US:en",
        "United States": "https://news.google.com/rss/search?q=United+States+latest+news&hl=en-US&gl=US&ceid=US:en",
        "Technology": "https://news.google.com/rss/headlines/section/topic/TECHNOLOGY?hl=en-US&gl=US&ceid=US:en",
        "Artificial Intelligence": "https://news.google.com/rss/search?q=artificial+intelligence+latest+news&hl=en-US&gl=US&ceid=US:en",
        "Cybersecurity": "https://news.google.com/rss/search?q=cybersecurity+latest+news&hl=en-US&gl=US&ceid=US:en",
        "Business": "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=en-US&gl=US&ceid=US:en",
        "Markets": "https://news.google.com/rss/search?q=stock+market+latest+news&hl=en-US&gl=US&ceid=US:en",
        "Energy": "https://news.google.com/rss/search?q=energy+oil+gas+electricity+latest+news&hl=en-US&gl=US&ceid=US:en",
        "Science": "https://news.google.com/rss/headlines/section/topic/SCIENCE?hl=en-US&gl=US&ceid=US:en",
        "Space": "https://news.google.com/rss/search?q=space+astronomy+NASA+ESA+latest+news&hl=en-US&gl=US&ceid=US:en",
        "Health": "https://news.google.com/rss/search?q=health+medicine+latest+news&hl=en-US&gl=US&ceid=US:en",
        "Climate": "https://news.google.com/rss/search?q=climate+environment+latest+news&hl=en-US&gl=US&ceid=US:en",
        "Defense": "https://news.google.com/rss/search?q=defense+military+geopolitics+latest+news&hl=en-US&gl=US&ceid=US:en",
    }


def load_daily_news_cache(max_age_seconds=None):
    """Return (cached_context, age_seconds) for the last assembled RSS context."""
    try:
        if not DAILY_NEWS_CACHE_FILE.exists():
            return "", None

        payload = json.loads(DAILY_NEWS_CACHE_FILE.read_text(encoding="utf-8"))

        if not isinstance(payload, dict):
            return "", None

        context = str(payload.get("context") or "").strip()
        created_at = str(payload.get("created_at") or "").strip()

        if "[NEWS HEADLINES]" not in context or not created_at:
            return "", None

        created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))

        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)

        age_seconds = max(
            0.0,
            (
                datetime.now(timezone.utc) - created.astimezone(timezone.utc)
            ).total_seconds(),
        )

        if max_age_seconds is not None and age_seconds > float(max_age_seconds):
            return "", age_seconds

        return context, age_seconds
    except Exception as exc:
        log_exception("load_daily_news_cache line 2482", exc)
        return "", None


def save_daily_news_cache(context):
    clean_context = str(context or "").strip()

    if "[NEWS HEADLINES]" not in clean_context:
        return False

    try:
        payload = {
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "context": clean_context,
        }
        temporary_file = DAILY_NEWS_CACHE_FILE.with_suffix(".json.tmp")
        temporary_file.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary_file.replace(DAILY_NEWS_CACHE_FILE)
        return True
    except Exception as exc:
        log_exception("save_daily_news_cache line 2503", exc)
        return False


def fetch_daily_news_section(
    section_name, rss_url, max_items=DAILY_NEWS_MAX_ITEMS_PER_SECTION
):
    """Fetch one Google News RSS section. Safe to call from a worker thread."""
    try:
        from bs4 import BeautifulSoup

        response_text = get_limited_text(
            rss_url,
            timeout=DAILY_NEWS_RSS_TIMEOUT_SECONDS,
            max_bytes=DAILY_NEWS_RSS_MAX_BYTES,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/149.0.0.0 Safari/537.36"
                )
            },
        )

        soup = BeautifulSoup(response_text, "xml")
        items = []

        for item in soup.find_all("item")[: int(max_items)]:
            title = item.find("title")
            description = item.find("description")
            link = item.find("link")

            if not title or not title.text.strip():
                continue

            title_text = re.sub(r"\s+", " ", title.text.strip())
            source_name = "Source"

            if " - " in title_text:
                source_name = title_text.rsplit(" - ", 1)[1].strip() or source_name

            source_url = link.text.strip() if link and link.text.strip() else ""
            summary = ""

            if description and description.text:
                summary = BeautifulSoup(description.text, "html.parser").get_text(
                    " ", strip=True
                )
                summary = re.sub(r"\s+", " ", summary).strip()[:400]

            items.append(
                {
                    "title": title_text,
                    "source_name": source_name,
                    "source_url": source_url,
                    "summary": summary,
                }
            )

        return {"section": section_name, "items": items, "error": ""}
    except Exception as error:
        log_exception("fetch_daily_news_section line 2559", error)
        clean_error = re.sub(r"\s+", " ", str(error)).strip()
        return {"section": section_name, "items": [], "error": clean_error[:260]}


def format_daily_news_context_from_sections(section_results):
    """Serialize fetched section records into the existing [NEWS HEADLINES] format."""
    rss_entries = list(daily_news_rss_map().items())
    section_order = [name for name, _url in rss_entries]
    section_index = {name: index for index, name in enumerate(section_order)}
    result_by_section = {
        str(result.get("section") or ""): result
        for result in (section_results or [])
        if isinstance(result, dict)
    }
    sections = []

    for section_name in section_order:
        result = result_by_section.get(section_name)

        if result is None:
            continue

        section_lines = [section_name.upper()]
        items = list(result.get("items") or [])

        if not items and result.get("error"):
            section_lines.append(
                f"- Could not fetch {section_name} news: {result.get('error')}"
            )
            sections.append("\n".join(section_lines))
            continue

        base_id = section_index.get(section_name, 0) * 100

        for item_index, item in enumerate(
            items[:DAILY_NEWS_MAX_ITEMS_PER_SECTION], start=1
        ):
            title_text = str(item.get("title") or "").strip()

            if not title_text:
                continue

            entry = f"- {title_text}"
            source_url = str(item.get("source_url") or "").strip()
            source_name = str(item.get("source_name") or "Source").strip() or "Source"

            if source_url:
                source_id = f"NEWS_{base_id + item_index:04d}"
                entry += f"\nSourceID: {source_id}"
                entry += f"\nSourceName: {html.escape(source_name)}"
                entry += f"\nSourceURL: {html.escape(source_url, quote=True)}"

            summary = str(item.get("summary") or "").strip()

            if summary:
                entry += f"\nSummary: {summary[:400]}"

            section_lines.append(entry)

        sections.append("\n".join(section_lines))

    if not sections:
        return "No recent news results found."

    return "[NEWS HEADLINES]\n\n" + "\n\n".join(sections)


def perform_daily_news_search(progress_callback=None):
    """Fetch Daily News RSS feeds in parallel, with cache and progressive updates."""
    cached_context, cached_age = load_daily_news_cache(max_age_seconds=None)

    # A recent cache makes repeated button presses effectively instant.
    if cached_context and cached_age is not None:
        try:
            if progress_callback:
                progress_callback(cached_context)
        except Exception as exc:
            log_exception("perform_daily_news_search line 2634", exc)
            pass

        if cached_age <= DAILY_NEWS_CACHE_MAX_AGE_SECONDS:
            return cached_context

    rss_entries = list(daily_news_rss_map().items())
    completed_results = {}
    emitted_context = ""

    def emit_progress():
        nonlocal emitted_context

        if not progress_callback:
            return

        ordered_results = [
            completed_results[section_name]
            for section_name, _rss_url in rss_entries
            if section_name in completed_results
        ]
        partial_context = format_daily_news_context_from_sections(ordered_results)

        if partial_context and partial_context != emitted_context:
            emitted_context = partial_context

            try:
                progress_callback(partial_context)
            except Exception as exc:
                log_exception("perform_daily_news_search.emit_progress line 2662", exc)
                pass

    max_workers = min(len(rss_entries), 14)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(
                fetch_daily_news_section, section_name, rss_url
            ): section_name
            for section_name, rss_url in rss_entries
        }

        for future in as_completed(future_map):
            section_name = future_map[future]

            try:
                result = future.result()
            except Exception as error:
                log_exception("perform_daily_news_search line 2678", error)
                result = {
                    "section": section_name,
                    "items": [],
                    "error": re.sub(r"\s+", " ", str(error)).strip()[:260],
                }

            completed_results[section_name] = result
            emit_progress()

    ordered_results = [
        completed_results.get(section_name)
        for section_name, _rss_url in rss_entries
        if completed_results.get(section_name) is not None
    ]
    final_context = format_daily_news_context_from_sections(ordered_results)

    if "[NEWS HEADLINES]" in final_context and parse_news_sources(final_context):
        save_daily_news_cache(final_context)
        return final_context

    # If the live fetch failed badly, fall back to the latest available cache.
    if cached_context:
        return cached_context

    return final_context


def parse_news_sources(web_context):
    """Return exact per-article metadata only for daily-news results.

    Each SourceID retains publisher, URL, source headline, and RSS summary. The
    extra fields are harmless to the citation renderer and allow selected news
    chats to preserve every fetched source record in persistent memory later.
    """
    clean_context = str(web_context or "")

    if "[NEWS HEADLINES]" not in clean_context:
        return {}

    sources = {}
    current_title = ""
    current_summary = ""
    source_id = ""
    source_name = ""
    source_url = ""

    def commit_source():
        nonlocal current_title, current_summary, source_id, source_name, source_url

        clean_id = html.unescape(str(source_id or "").strip())
        clean_name = html.unescape(str(source_name or "").strip())
        clean_url = html.unescape(str(source_url or "").strip())
        clean_title = html.unescape(str(current_title or "").strip())
        clean_summary = html.unescape(str(current_summary or "").strip())

        if clean_name and clean_url:
            key = clean_id or clean_name

            if key in sources:
                suffix = 2
                candidate = f"{key}_{suffix}"

                while candidate in sources:
                    suffix += 1
                    candidate = f"{key}_{suffix}"

                key = candidate

            sources[key] = {
                "name": clean_name,
                "url": clean_url,
                "title": clean_title,
                "summary": clean_summary,
            }

        current_title = ""
        current_summary = ""
        source_id = ""
        source_name = ""
        source_url = ""

    for line in clean_context.splitlines():
        clean = line.strip()

        if clean.startswith("- "):
            if source_name and source_url:
                commit_source()

            current_title = clean[2:].strip()
            continue

        if clean.startswith("SourceID:"):
            if source_name and source_url:
                commit_source()

            source_id = clean.replace("SourceID:", "", 1).strip()
            continue

        if clean.startswith("SourceName:"):
            source_name = clean.replace("SourceName:", "", 1).strip()
            continue

        if clean.startswith("SourceURL:"):
            source_url = clean.replace("SourceURL:", "", 1).strip()
            continue

        if clean.startswith("Summary:"):
            current_summary = clean.replace("Summary:", "", 1).strip()
            commit_source()

    if source_name and source_url:
        commit_source()

    return sources


DAILY_NEWS_LOW_VALUE_TITLES = {
    "opinion",
    "analysis",
    "live",
    "video",
    "videos",
    "watch",
    "listen",
    "photos",
    "pictures",
    "in pictures",
    "in photos",
    "in charts",
    "charts",
}


def clean_daily_news_title(title, source_name=""):
    """Return a display-safe RSS title, or an empty string for bad stubs.

    Google News RSS occasionally emits low-value fragments such as "OPINION" or
    "in charts." as standalone items after publisher suffix stripping. Those
    fragments looked like broken bullets in the Daily News card.  This cleaner
    keeps normal titles untouched but drops generic navigation/category labels.
    """
    clean_title = html.unescape(str(title or "")).strip()
    clean_source = html.unescape(str(source_name or "")).strip()

    clean_title = re.sub(r"\s+", " ", clean_title)
    clean_title = clean_title.strip(" \t\r\n-–—:;,.•")

    if not clean_title:
        return ""

    # Google News titles commonly end with " - Publisher".
    if clean_source and clean_title.casefold().endswith(
        (" - " + clean_source).casefold()
    ):
        clean_title = clean_title[: -len(" - " + clean_source)].rstrip(" -–—:;,.•")
    elif " - " in clean_title:
        possible_title, possible_source = clean_title.rsplit(" - ", 1)

        # Treat short suffixes as publisher names and remove them.
        if possible_source and len(possible_source.strip()) <= 80:
            clean_title = possible_title.strip(" -–—:;,.•")

    # Remove common section labels when they prefix an otherwise useful title.
    clean_title = re.sub(
        r"^(?:opinion|analysis|live|video|watch|photos?|pictures?)\s*[:|–—-]\s*",
        "",
        clean_title,
        flags=re.IGNORECASE,
    ).strip(" -–—:;,.•")

    # RSS titles are later rendered inside Markdown bullets.  A real headline
    # can begin with a hashtag, e.g. "#New40k ...".  Python-Markdown/Qt can
    # interpret that as an H1 inside the list item, making one news item huge.
    # Strip only leading Markdown/hashtag markers at the start of the title.
    clean_title = re.sub(
        r"^(?:(?:#{1,6}\s*)|(?:[-*•]\s+)|(?:\d{1,3}[.)]\s+))+",
        "",
        clean_title,
    ).strip(" -–—:;,.•")

    generic_key = re.sub(r"[^a-z0-9]+", " ", clean_title.casefold()).strip()

    if generic_key in DAILY_NEWS_LOW_VALUE_TITLES:
        return ""

    # Drop tiny headline fragments such as "in charts" or "BBC" that are not
    # useful news items by themselves.
    word_count = len(re.findall(r"[A-Za-z0-9]+", clean_title))
    if word_count <= 2 and not re.search(r"\d{3,}|\$|€|£|%", clean_title):
        return ""

    return clean_title


def build_deterministic_daily_news_brief(
    web_context, max_items_per_section=DAILY_NEWS_BRIEF_ITEMS_PER_SECTION
):
    """Build the Daily News Brief directly from RSS records without an LLM.

    The daily-news workflow already has structured RSS items with SourceID,
    publisher and URL metadata.  Sending 100+ items to a reasoning model makes
    it spend minutes planning, self-checking and sometimes inventing bad IDs.
    This formatter keeps the briefing fast and deterministic while preserving
    clickable NEWS_#### citations through the existing news_sources renderer.
    It now fetches up to DAILY_NEWS_MAX_ITEMS_PER_SECTION records per section
    and shows up to DAILY_NEWS_BRIEF_ITEMS_PER_SECTION visible bullets per section.
    """
    clean_context = str(web_context or "")

    if "[NEWS HEADLINES]" not in clean_context:
        return ""

    wanted_sections = {
        "WORLD": "World",
        "EUROPE": "Europe",
        "UNITED STATES": "United States",
        "TECHNOLOGY": "Technology",
        "ARTIFICIAL INTELLIGENCE": "Artificial Intelligence",
        "CYBERSECURITY": "Cybersecurity",
        "BUSINESS": "Business",
        "MARKETS": "Markets",
        "ENERGY": "Energy",
        "SCIENCE": "Science",
        "SPACE": "Space",
        "HEALTH": "Health",
        "CLIMATE": "Climate",
        "DEFENSE": "Defense",
    }

    section_order = list(wanted_sections.values())
    section_items = {section: [] for section in section_order}
    current_section = ""
    current_item = None

    def commit_item():
        nonlocal current_item

        if not current_section or current_item is None:
            current_item = None
            return

        raw_title = current_item.get("title") or ""
        source_id = html.unescape(str(current_item.get("source_id") or "")).strip()
        source_name = html.unescape(str(current_item.get("source_name") or "")).strip()

        if not re.fullmatch(r"NEWS_\d{4,}", source_id):
            current_item = None
            return

        title = clean_daily_news_title(raw_title, source_name)

        if not title:
            current_item = None
            return

        section_items[current_section].append(
            {"title": title, "source_id": source_id, "source_name": source_name}
        )
        current_item = None

    for raw_line in clean_context.splitlines():
        line = raw_line.strip()

        if not line or line == "[NEWS HEADLINES]":
            continue

        upper_line = line.upper()

        if upper_line in wanted_sections:
            commit_item()
            current_section = wanted_sections[upper_line]
            continue

        if line.startswith("- "):
            commit_item()
            current_item = {"title": line[2:].strip()}
            continue

        if current_item is None:
            continue

        if line.startswith("SourceID:"):
            current_item["source_id"] = line.replace("SourceID:", "", 1).strip()
        elif line.startswith("SourceName:"):
            current_item["source_name"] = line.replace("SourceName:", "", 1).strip()

    commit_item()

    used_titles = set()
    output_lines = ["# Daily News Brief"]

    for section in section_order:
        selected_lines = []

        for item in section_items.get(section, []):
            title = item["title"]
            source_id = item["source_id"]
            title_key = re.sub(r"[^a-z0-9]+", " ", title.casefold()).strip()

            if title_key and title_key in used_titles:
                continue

            if title_key:
                used_titles.add(title_key)

            sentence = title.rstrip()

            if sentence and sentence[-1] not in ".!?":
                sentence += "."

            selected_lines.append(f"- {sentence} [{source_id}]")

            if len(selected_lines) >= int(max_items_per_section):
                break

        if not selected_lines:
            continue

        output_lines.extend(["", f"## {section}", ""])
        output_lines.extend(selected_lines)

    if len(output_lines) == 1:
        return "Daily news failed: no valid RSS source records were parsed."

    return "\n".join(output_lines).strip()
