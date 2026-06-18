import hashlib
import json
import re
import uuid
from datetime import datetime
from pathlib import Path

from .config import (
    CALIBRATION_PROFILE_SCHEMA_VERSION,
    CALIBRATION_PROFILES_FILE,
    LEGACY_MEMORY_FILE,
    MAX_MEMORY_CHARS,
    MAX_MEMORY_ENTRIES,
    MEMORY_CATEGORIES,
    MEMORY_CODE_CHUNK_CHARS,
    MEMORY_FILE,
    MEMORY_MAX_RESULTS,
    MEMORY_SCHEMA_VERSION,
    SOURCE_CODE_EXTENSIONS,
    SOURCE_CODE_LANGUAGE_BY_EXTENSION,
)
from .json_store import atomic_write_json, preserve_corrupt_file
from .logging_utils import log_exception


def empty_calibration_profile_store():
    return {
        "version": CALIBRATION_PROFILE_SCHEMA_VERSION,
        "updated_at": None,
        "active_profile": "precise",
        "profiles": {},
    }


def load_calibration_profile_store():
    if not CALIBRATION_PROFILES_FILE.exists():
        return empty_calibration_profile_store()

    try:
        raw_data = json.loads(CALIBRATION_PROFILES_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        log_exception("load_calibration_profile_store line 629", exc)
        preserve_corrupt_file(
            CALIBRATION_PROFILES_FILE, "preserve_corrupt_calibration_profile_store"
        )
        return empty_calibration_profile_store()

    if not isinstance(raw_data, dict):
        return empty_calibration_profile_store()

    allowed_profiles = {"precise", "architect", "explorer", "companion"}

    active_profile = str(raw_data.get("active_profile") or "precise").strip().lower()

    if active_profile not in allowed_profiles:
        active_profile = "precise"

    profiles = {}
    raw_profiles = raw_data.get("profiles") or {}

    if isinstance(raw_profiles, dict):
        for profile_key, raw_profile in raw_profiles.items():
            clean_key = str(profile_key or "").strip().lower()

            if clean_key not in allowed_profiles:
                continue

            if isinstance(raw_profile, dict):
                prompt = str(raw_profile.get("prompt") or "").strip()
                updated_at = str(raw_profile.get("updated_at") or "").strip()
            else:
                prompt = str(raw_profile or "").strip()
                updated_at = ""

            if not prompt:
                continue

            profiles[clean_key] = {"prompt": prompt, "updated_at": updated_at or None}

    return {
        "version": CALIBRATION_PROFILE_SCHEMA_VERSION,
        "updated_at": str(raw_data.get("updated_at") or "").strip() or None,
        "active_profile": active_profile,
        "profiles": profiles,
    }


def save_calibration_profile_store(profile_store):
    try:
        normalized = empty_calibration_profile_store()

        if isinstance(profile_store, dict):
            active_profile = (
                str(profile_store.get("active_profile") or "precise").strip().lower()
            )

            if active_profile in {"precise", "architect", "explorer", "companion"}:
                normalized["active_profile"] = active_profile

            raw_profiles = profile_store.get("profiles") or {}

            if isinstance(raw_profiles, dict):
                for profile_key, raw_profile in raw_profiles.items():
                    clean_key = str(profile_key or "").strip().lower()

                    if clean_key not in {
                        "precise",
                        "architect",
                        "explorer",
                        "companion",
                    }:
                        continue

                    if isinstance(raw_profile, dict):
                        prompt = str(raw_profile.get("prompt") or "").strip()
                        updated_at = str(raw_profile.get("updated_at") or "").strip()
                    else:
                        prompt = str(raw_profile or "").strip()
                        updated_at = ""

                    if not prompt:
                        continue

                    normalized["profiles"][clean_key] = {
                        "prompt": prompt,
                        "updated_at": updated_at or None,
                    }

        normalized["updated_at"] = datetime.now().isoformat(timespec="seconds")
        atomic_write_json(
            CALIBRATION_PROFILES_FILE,
            normalized,
            ensure_ascii=False,
            indent=2,
        )
        return True
    except Exception as exc:
        log_exception("save_calibration_profile_store line 721", exc)
        return False


def empty_persistent_memory():
    return {"version": MEMORY_SCHEMA_VERSION, "updated_at": None, "entries": []}


def normalize_memory_entry(entry, default_source="manual"):
    if not isinstance(entry, dict):
        entry = {"content": str(entry or "")}

    content = str(entry.get("content") or entry.get("text") or "")
    content = re.sub(r"\r\n?", "\n", content)

    # Python and other source code must retain indentation and line breaks.
    # Earlier versions normalized every run of spaces, which silently damaged
    # code imported from selected history chats.
    preserve_formatting = bool(entry.get("preserve_formatting")) or bool(
        re.search(r"(?m)^\s*(?:`{3,}|~{3,})", content)
    )

    if preserve_formatting:
        content = content.strip("\n")
    else:
        content = re.sub(r"[ \t]+", " ", content)
        content = re.sub(r"\n{3,}", "\n\n", content).strip()

    if not content:
        return None

    category = str(entry.get("category") or "other").strip().lower()

    if category not in MEMORY_CATEGORIES:
        category = "other"

    title = re.sub(r"\s+", " ", str(entry.get("title") or "")).strip()

    if not title:
        title = content[:80].rstrip(" .,:;-_")

    now = datetime.now().isoformat(timespec="seconds")
    source_titles = entry.get("source_titles") or []

    if isinstance(source_titles, str):
        source_titles = [source_titles]

    source_titles = [
        re.sub(r"\s+", " ", str(value)).strip()
        for value in source_titles
        if str(value).strip()
    ]

    tags = entry.get("tags") or []

    if isinstance(tags, str):
        tags = [tags]

    tags = [
        re.sub(r"\s+", " ", str(value)).strip().lower()
        for value in tags
        if str(value).strip()
    ]

    return {
        "id": str(entry.get("id") or uuid.uuid4().hex),
        "category": category,
        "title": title[:160],
        "content": content,
        "snapshot_date": str(entry.get("snapshot_date") or "").strip() or None,
        "source": str(entry.get("source") or default_source).strip() or default_source,
        "source_titles": source_titles[:20],
        "tags": tags[:20],
        "created_at": str(entry.get("created_at") or now),
        "updated_at": str(entry.get("updated_at") or now),
    }


def normalize_persistent_memory(memory_data):
    if isinstance(memory_data, list):
        memory_data = {"entries": memory_data}

    if not isinstance(memory_data, dict):
        memory_data = empty_persistent_memory()

    entries = []

    for raw_entry in memory_data.get("entries") or []:
        normalized = normalize_memory_entry(raw_entry)

        if normalized is not None:
            entries.append(normalized)

    return {
        "version": MEMORY_SCHEMA_VERSION,
        "updated_at": str(memory_data.get("updated_at") or "").strip() or None,
        "entries": entries[-MAX_MEMORY_ENTRIES:],
    }


def save_persistent_memory(memory_data):
    try:
        normalized = normalize_persistent_memory(memory_data)
        normalized["updated_at"] = datetime.now().isoformat(timespec="seconds")
        atomic_write_json(MEMORY_FILE, normalized, ensure_ascii=False, indent=2)
        return True
    except Exception as exc:
        log_exception("save_persistent_memory line 831", exc)
        return False


def load_persistent_memory():
    if MEMORY_FILE.exists():
        try:
            raw_data = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
            return normalize_persistent_memory(raw_data)
        except Exception as exc:
            log_exception("load_persistent_memory line 840", exc)
            preserve_corrupt_file(MEMORY_FILE, "preserve_corrupt_persistent_memory")
            return empty_persistent_memory()

    # One-time migration from versions that stored one unstructured text block.
    if LEGACY_MEMORY_FILE.exists():
        try:
            legacy_text = LEGACY_MEMORY_FILE.read_text(encoding="utf-8").strip()
        except Exception as exc:
            log_exception("load_persistent_memory line 847", exc)
            legacy_text = ""

        if legacy_text:
            migrated = empty_persistent_memory()
            migrated["entries"] = [
                normalize_memory_entry(
                    {
                        "category": "other",
                        "title": "Legacy persistent memory",
                        "content": legacy_text,
                        "source": "memory.txt migration",
                    }
                )
            ]
            save_persistent_memory(migrated)
            return migrated

    return empty_persistent_memory()


def compact_memory_entry_for_context(entry):
    return {
        "category": entry.get("category", "other"),
        "title": entry.get("title", ""),
        "content": entry.get("content", ""),
        "snapshot_date": entry.get("snapshot_date"),
        "source": entry.get("source", ""),
        "created_at": entry.get("created_at", ""),
    }


def _persistent_memory_query_terms(query):
    terms = [
        term.casefold()
        for term in re.findall(r"[^\W_]{2,}", str(query or ""), flags=re.UNICODE)
    ]

    stop_words = {
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "from",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "how",
        "into",
        "about",
        "your",
        "you",
        "are",
        "was",
        "were",
        "have",
        "has",
        "had",
        "please",
        "tell",
        "give",
        "show",
        "use",
        "using",
    }

    return [term for term in terms if term not in stop_words]


def search_persistent_memory_entries(
    memory_data, query, max_results=MEMORY_MAX_RESULTS
):
    normalized = normalize_persistent_memory(memory_data)
    entries = normalized.get("entries") or []
    clean_query = re.sub(r"\s+", " ", str(query or "")).strip().casefold()
    terms = _persistent_memory_query_terms(clean_query)

    if not clean_query:
        return list(reversed(entries[-max_results:]))

    scored = []

    for index, entry in enumerate(entries):
        title = str(entry.get("title") or "").casefold()
        content = str(entry.get("content") or "").casefold()
        category = str(entry.get("category") or "").casefold()
        tags = " ".join(str(value) for value in entry.get("tags") or []).casefold()
        sources = " ".join(
            str(value) for value in entry.get("source_titles") or []
        ).casefold()
        source = str(entry.get("source") or "").casefold()
        snapshot_date = str(entry.get("snapshot_date") or "").casefold()

        score = 0

        if len(clean_query) >= 3:
            if clean_query in title:
                score += 120
            if clean_query in content:
                score += 70
            if clean_query in tags:
                score += 45
            if clean_query in sources:
                score += 35

        matched_terms = 0

        for term in terms:
            term_score = 0

            if term in title:
                term_score += 18
            if term in tags:
                term_score += 14
            if term in sources:
                term_score += 10
            if term in category:
                term_score += 6
            if term in content:
                term_score += 4
            if term in source or term in snapshot_date:
                term_score += 3

            if term_score:
                matched_terms += 1
                score += term_score

        if terms and matched_terms == len(set(terms)):
            score += 30

        if score <= 0:
            continue

        # Prefer newer entries only as a tie-breaker; relevance remains primary.
        scored.append((score, index, entry))

    scored.sort(key=lambda value: (value[0], value[1]), reverse=True)
    return [entry for _score, _index, entry in scored[:max_results]]


def build_persistent_memory_context(memory_data, query=""):
    normalized = normalize_persistent_memory(memory_data)
    all_entries = normalized.get("entries") or []

    if not all_entries:
        return ""

    relevant_entries = search_persistent_memory_entries(
        normalized, query, max_results=MEMORY_MAX_RESULTS
    )

    # Stable profile/project/configuration memories remain available even when
    # the current wording does not share obvious keywords with them.
    foundational_categories = {
        "preference",
        "identity",
        "project",
        "configuration",
        "procedure",
        "decision",
    }
    foundational_entries = [
        entry
        for entry in reversed(all_entries)
        if entry.get("category") in foundational_categories
    ][:20]

    candidates = []
    seen_ids = set()

    for entry in relevant_entries + foundational_entries:
        entry_id = str(entry.get("id") or "")

        if entry_id and entry_id in seen_ids:
            continue

        if entry_id:
            seen_ids.add(entry_id)

        candidates.append(entry)

    if not candidates:
        candidates = list(reversed(all_entries[-20:]))

    selected_entries = []

    for entry in candidates:
        compact_entry = compact_memory_entry_for_context(entry)
        candidate = selected_entries + [compact_entry]
        candidate_json = json.dumps(
            {"version": MEMORY_SCHEMA_VERSION, "entries": candidate},
            ensure_ascii=False,
            separators=(",", ":"),
        )

        if len(candidate_json) <= MAX_MEMORY_CHARS:
            selected_entries = candidate
            continue

        if not selected_entries:
            available = max(300, MAX_MEMORY_CHARS - 700)
            compact_entry["content"] = compact_entry["content"][:available]
            selected_entries = [compact_entry]

        break

    memory_json = json.dumps(
        {
            "version": MEMORY_SCHEMA_VERSION,
            "query": str(query or "").strip(),
            "matched_entries": len(selected_entries),
            "total_library_entries": len(all_entries),
            "entries": selected_entries,
        },
        ensure_ascii=False,
        indent=2,
    )

    return (
        "\n\nAPPLICATION-SUPPLIED PERSISTENT MEMORY\n"
        "PERSISTENT_MEMORY = AVAILABLE\n"
        "The application searched the complete structured persistent-memory library "
        "and supplied the entries most relevant to the current request, plus a small "
        "set of stable profile/project/configuration entries. The complete library "
        "remains stored locally even when only a subset fits this request. Treat each "
        "entry as user-selected context, not independent proof. Respect snapshot_date "
        "for time-sensitive information and do not claim to remember anything outside "
        "this object.\n\n" + memory_json
    )


def parse_memory_extraction_payload(raw_text):
    clean_text = str(raw_text or "").strip()

    if clean_text.upper() in {"NO_DURABLE_MEMORY", "NO_USEFUL_MEMORY"}:
        return []

    clean_text = re.sub(r"^```(?:json)?\s*", "", clean_text, flags=re.IGNORECASE)
    clean_text = re.sub(r"\s*```$", "", clean_text)

    parsed = None

    for opening, closing in (("{", "}"), ("[", "]")):
        start = clean_text.find(opening)
        end = clean_text.rfind(closing)

        if start == -1 or end < start:
            continue

        try:
            parsed = json.loads(clean_text[start : end + 1])
            break
        except Exception as exc:
            log_exception("parse_memory_extraction_payload line 1104", exc)
            continue

    if isinstance(parsed, dict):
        raw_entries = parsed.get("entries") or []
    elif isinstance(parsed, list):
        raw_entries = parsed
    else:
        raw_entries = []

    normalized_entries = []

    for raw_entry in raw_entries:
        normalized = normalize_memory_entry(raw_entry, default_source="history")

        if normalized is not None:
            normalized_entries.append(normalized)

    # Backward-compatible fallback for a model that still returned bullets.
    if not normalized_entries:
        for line in clean_text.splitlines():
            item_text = re.sub(r"^\s*[-*•]\s*", "", line).strip()

            if not item_text:
                continue

            normalized = normalize_memory_entry(
                {
                    "category": "other",
                    "title": item_text[:80],
                    "content": item_text,
                    "source": "history",
                }
            )

            if normalized is not None:
                normalized_entries.append(normalized)

    return normalized_entries


def extract_news_article_entries(transcript):
    """Extract every article bullet from selected news chats without summarizing.

    The LLM extraction pass is still used for general memories, but this parser
    guarantees that a long daily brief is not collapsed into a handful of broad
    category summaries or truncated by a model context window.
    """
    entries = []
    seen = set()
    sections = re.split(r"\n\n={20,}\n\n", str(transcript or ""))

    for section in sections:
        title_match = re.search(r"^CHAT TITLE:\s*(.+)$", section, flags=re.MULTILINE)
        created_match = re.search(
            r"^CHAT CREATED:\s*(.+)$", section, flags=re.MULTILINE
        )
        chat_title = (
            title_match.group(1).strip() if title_match else "Selected news chat"
        )
        created = created_match.group(1).strip() if created_match else ""
        snapshot_date_match = re.match(r"(\d{4}-\d{2}-\d{2})", created)
        snapshot_date = snapshot_date_match.group(1) if snapshot_date_match else None

        lines = section.splitlines()
        current_heading = ""
        current_item = None
        article_items = []
        in_assistant = False

        def commit_item():
            nonlocal current_item

            if current_item is None:
                return

            content = re.sub(r"\s+", " ", " ".join(current_item)).strip()
            current_item = None

            if len(content) >= 25:
                article_items.append((current_heading, content))

        for raw_line in lines:
            line = raw_line.rstrip()
            clean = line.strip()

            role_match = re.match(
                r"^(USER|ASSISTANT|SYSTEM|TOOL):\s*(.*)$", clean, flags=re.IGNORECASE
            )

            if role_match:
                commit_item()
                in_assistant = role_match.group(1).upper() == "ASSISTANT"
                clean = role_match.group(2).strip()

                if not clean:
                    continue

            if not in_assistant:
                continue

            heading_match = re.match(r"^#{1,6}\s+(.+?)\s*$", clean)

            if heading_match:
                commit_item()
                current_heading = re.sub(r"[*_`]+", "", heading_match.group(1)).strip()
                continue

            bullet_match = re.match(r"^(?:[-*•]|\d+[.)])\s+(.+)$", clean)

            if bullet_match:
                commit_item()
                current_item = [bullet_match.group(1).strip()]
                continue

            if current_item is not None:
                if clean:
                    current_item.append(clean)
                else:
                    commit_item()

        commit_item()

        source_like_count = sum(
            1
            for _heading, content in article_items
            if "http://" in content
            or "https://" in content
            or re.search(r"\[[^\]]+\]", content)
        )
        news_like = (
            "news" in chat_title.casefold()
            or "brief" in chat_title.casefold()
            or (len(article_items) >= 8 and source_like_count >= 3)
        )

        if not news_like:
            continue

        for heading, content in article_items:
            title_text = re.sub(r"\[[^\]]+\]\([^)]*\)", "", content)
            title_text = re.sub(r"\[[^\]]+\]", "", title_text)
            title_text = re.sub(r"\s+", " ", title_text).strip(" -–—:;,. ")

            sentence_break = re.search(r"(?<=[.!?])\s+", title_text)

            if sentence_break:
                title_text = title_text[: sentence_break.start()].strip()

            if len(title_text) > 140:
                title_text = title_text[:137].rstrip() + "..."

            if heading and heading.casefold() not in title_text.casefold():
                entry_title = f"{heading}: {title_text}"
            else:
                entry_title = title_text

            url_match = re.search(r"https?://[^\s\])}>,]+", content)

            if url_match:
                key = "url:" + url_match.group(0).rstrip(".,;:").casefold()
            else:
                key = re.sub(r"\W+", " ", title_text.casefold()).strip()

            if not key or key in seen:
                continue

            seen.add(key)
            tags = ["news", "article"]

            if heading:
                tags.append(heading.casefold())

            entry = normalize_memory_entry(
                {
                    "category": "snapshot",
                    "title": entry_title or "News article",
                    "content": content,
                    "snapshot_date": snapshot_date,
                    "source": "history news article",
                    "source_titles": [chat_title],
                    "tags": tags,
                },
                default_source="history news article",
            )

            if entry is not None:
                entries.append(entry)

    return entries


def is_news_memory_section(section):
    """Return True when a history section is a generated news briefing.

    These sections are handled by extract_news_article_entries() without an
    additional LLM pass.  Requiring several sourced bullets prevents an
    ordinary conversation that merely mentions news from being skipped.
    """
    clean_section = str(section or "")

    title_match = re.search(r"^CHAT TITLE:\s*(.+)$", clean_section, flags=re.MULTILINE)
    chat_title = title_match.group(1).strip() if title_match else ""
    title_is_news = bool(
        re.search(
            r"\b(?:news|brief|briefing|headlines)\b", chat_title, flags=re.IGNORECASE
        )
    )

    in_assistant = False
    bullet_count = 0
    sourced_bullet_count = 0
    current_bullet = ""

    def commit_bullet():
        nonlocal current_bullet, bullet_count, sourced_bullet_count

        content = re.sub(r"\s+", " ", current_bullet).strip()
        current_bullet = ""

        if len(content) < 25:
            return

        bullet_count += 1

        if (
            "http://" in content
            or "https://" in content
            or re.search(r"\[[^\]]+\]", content)
        ):
            sourced_bullet_count += 1

    for raw_line in clean_section.splitlines():
        clean = raw_line.strip()
        role_match = re.match(
            r"^(USER|ASSISTANT|SYSTEM|TOOL):\s*(.*)$", clean, flags=re.IGNORECASE
        )

        if role_match:
            commit_bullet()
            in_assistant = role_match.group(1).upper() == "ASSISTANT"
            clean = role_match.group(2).strip()

        if not in_assistant:
            continue

        bullet_match = re.match(r"^(?:[-*•]|\d+[.)])\s+(.+)$", clean)

        if bullet_match:
            commit_bullet()
            current_bullet = bullet_match.group(1).strip()
            continue

        if current_bullet:
            if clean and not re.match(r"^#{1,6}\s+", clean):
                current_bullet += " " + clean
            else:
                commit_bullet()

    commit_bullet()

    return (title_is_news and bullet_count >= 3 and sourced_bullet_count >= 1) or (
        bullet_count >= 8 and sourced_bullet_count >= 3
    )


def remove_deterministic_news_sections(transcript):
    """Remove news brief sections already captured by the deterministic parser.

    This is the main speed optimisation for Remember Selected.  A large daily
    brief can contain 100+ articles and previously caused many sequential LLM
    calls even though those articles had already been extracted locally.
    """
    sections = re.split(r"\n\n={20,}\n\n", str(transcript or ""))
    remaining_sections = [
        section
        for section in sections
        if section.strip() and not is_news_memory_section(section)
    ]

    return "\n\n==============================\n\n".join(remaining_sections)


def source_code_language_for_filename(filename):
    suffix = Path(str(filename or "").strip()).suffix.casefold()
    return SOURCE_CODE_LANGUAGE_BY_EXTENSION.get(suffix, "")


def make_fenced_code(language, code):
    clean_language = re.sub(r"[^A-Za-z0-9_+.#-]", "", str(language or "").strip())
    code_text = re.sub(r"\r\n?", "\n", str(code or ""))
    longest_backtick_run = max(
        [len(match.group(0)) for match in re.finditer(r"`+", code_text)] or [0]
    )
    fence = "`" * max(3, longest_backtick_run + 1)
    ending = "" if code_text.endswith("\n") else "\n"
    return f"{fence}{clean_language}\n{code_text}{ending}{fence}"


def preserve_source_attachments_for_memory(text):
    """Keep source-code attachments while excluding ordinary document bodies.

    prepare_content() stores extracted attachment text inside the user message.
    Older history-memory code removed everything after the first "Attached file"
    marker, so an attached .py file never reached memory extraction.
    """
    source_text = re.sub(r"\r\n?", "\n", str(text or ""))
    first_attachment = re.search(r"(?m)^Attached file:\s*[^\n]+$", source_text)

    if first_attachment is None:
        return source_text

    user_text = source_text[: first_attachment.start()].rstrip()
    attachment_blob = source_text[first_attachment.start() :]
    attachment_blocks = re.split(r"\n\n---\n\n(?=Attached file:\s*)", attachment_blob)
    preserved_blocks = []

    for block in attachment_blocks:
        match = re.match(
            r"(?s)^Attached file:\s*(?P<name>[^\n]+)\n\n(?P<body>.*)$",
            block.strip("\n"),
        )

        if match is None:
            continue

        filename = match.group("name").strip()
        body = match.group("body")
        suffix = Path(filename).suffix.casefold()

        if suffix not in SOURCE_CODE_EXTENSIONS:
            continue

        if body.lstrip().startswith("Could not read this file:"):
            continue

        language = source_code_language_for_filename(filename)
        preserved_blocks.append(
            f"[ATTACHED SOURCE CODE: {filename}]\n" + make_fenced_code(language, body)
        )

    output_parts = []

    if user_text:
        output_parts.append(user_text)

    output_parts.extend(preserved_blocks)
    return "\n\n".join(output_parts).strip("\n")


def extract_fenced_code_blocks(text):
    """Return closed Markdown code fences without altering their indentation."""
    lines = re.sub(r"\r\n?", "\n", str(text or "")).split("\n")
    blocks = []
    opening_character = ""
    opening_length = 0
    language = ""
    code_lines = []
    opening_line = 0
    attachment_name = ""

    for line_index, line in enumerate(lines):
        if not opening_character:
            match = re.match(r"^[ \t]*(?P<fence>`{3,}|~{3,})(?P<info>.*)$", line)

            if match is None:
                continue

            fence = match.group("fence")
            opening_character = fence[0]
            opening_length = len(fence)
            info = match.group("info").strip()
            language = info.split()[0] if info else ""
            language = language.strip("{}.")
            code_lines = []
            opening_line = line_index + 1
            attachment_name = ""

            previous_index = line_index - 1

            while previous_index >= 0 and not lines[previous_index].strip():
                previous_index -= 1

            if previous_index >= 0:
                label_match = re.match(
                    r"^\[ATTACHED SOURCE CODE:\s*(.+?)\]$",
                    lines[previous_index].strip(),
                    flags=re.IGNORECASE,
                )

                if label_match:
                    attachment_name = label_match.group(1).strip()

            continue

        closing_pattern = (
            r"^[ \t]*"
            + re.escape(opening_character)
            + "{"
            + str(opening_length)
            + r",}[ \t]*$"
        )

        if re.match(closing_pattern, line):
            blocks.append(
                {
                    "language": language,
                    "code": "\n".join(code_lines),
                    "opening_line": opening_line,
                    "attachment_name": attachment_name,
                }
            )
            opening_character = ""
            opening_length = 0
            language = ""
            code_lines = []
            opening_line = 0
            attachment_name = ""
            continue

        code_lines.append(line)

    return blocks


def split_code_for_memory(code, max_chars=MEMORY_CODE_CHUNK_CHARS):
    code_text = re.sub(r"\r\n?", "\n", str(code or ""))

    if len(code_text) <= max_chars:
        end_line = max(1, code_text.count("\n") + 1)
        return [(code_text, 1, end_line)]

    chunks = []
    start = 0
    start_line = 1
    text_length = len(code_text)

    while start < text_length:
        target_end = min(start + max_chars, text_length)
        end = target_end

        if target_end < text_length:
            boundary = code_text.rfind("\n", start + max(max_chars // 2, 1), target_end)

            if boundary > start:
                end = boundary + 1

        chunk = code_text[start:end]
        newline_count = chunk.count("\n")
        end_line = start_line + newline_count

        if chunk.endswith("\n") and end_line > start_line:
            end_line -= 1

        chunks.append((chunk, start_line, max(start_line, end_line)))

        if end >= text_length:
            break

        if chunk.endswith("\n"):
            start_line = end_line + 1
        else:
            start_line = end_line

        start = end

    return chunks


def iter_history_transcript_messages(section):
    """Yield role/text pairs while ignoring role-like strings inside code fences."""
    current_role = ""
    current_lines = []
    opening_character = ""
    opening_length = 0

    def update_fence_state(content_line):
        nonlocal opening_character, opening_length

        if not opening_character:
            opening = re.match(r"^[ \t]*(?P<fence>`{3,}|~{3,})(?:.*)$", content_line)

            if opening:
                fence = opening.group("fence")
                opening_character = fence[0]
                opening_length = len(fence)

            return

        closing_pattern = (
            r"^[ \t]*"
            + re.escape(opening_character)
            + "{"
            + str(opening_length)
            + r",}[ \t]*$"
        )

        if re.match(closing_pattern, content_line):
            opening_character = ""
            opening_length = 0

    for raw_line in re.sub(r"\r\n?", "\n", str(section or "")).split("\n"):
        role_match = None

        if not opening_character:
            role_match = re.match(
                r"^(USER|ASSISTANT|SYSTEM|TOOL):(?:\s?(.*))?$",
                raw_line,
                flags=re.IGNORECASE,
            )

        if role_match:
            if current_role:
                yield current_role, "\n".join(current_lines)

            current_role = role_match.group(1).upper()
            remainder = role_match.group(2) or ""
            current_lines = [remainder] if remainder else []

            if remainder:
                update_fence_state(remainder)

            continue

        if not current_role:
            continue

        current_lines.append(raw_line)
        update_fence_state(raw_line)

    if current_role:
        yield current_role, "\n".join(current_lines)


def extract_history_code_entries(transcript):
    """Preserve every fenced code block as exact, searchable memory entries."""
    entries = []
    seen_hashes = set()
    sections = re.split(r"\n\n={20,}\n\n", str(transcript or ""))

    for section in sections:
        title_match = re.search(r"^CHAT TITLE:\s*(.+)$", section, flags=re.MULTILINE)
        created_match = re.search(
            r"^CHAT CREATED:\s*(.+)$", section, flags=re.MULTILINE
        )
        chat_title = title_match.group(1).strip() if title_match else "Selected chat"
        created_at = created_match.group(1).strip() if created_match else ""

        for role, message_text in iter_history_transcript_messages(section):
            for block in extract_fenced_code_blocks(message_text):
                code = str(block.get("code") or "")

                if not code.strip():
                    continue

                attachment_name = str(block.get("attachment_name") or "").strip()
                language = str(block.get("language") or "").strip().casefold()

                if not language and attachment_name:
                    language = source_code_language_for_filename(attachment_name)

                exact_hash = hashlib.sha256(
                    (language + "\0" + attachment_name + "\0" + code).encode(
                        "utf-8", errors="replace"
                    )
                ).hexdigest()

                if exact_hash in seen_hashes:
                    continue

                seen_hashes.add(exact_hash)
                chunks = split_code_for_memory(code)
                language_name = language.capitalize() if language else "Code"

                if attachment_name:
                    base_title = f"{language_name} source: {attachment_name}"
                else:
                    first_code_line = next(
                        (line.strip() for line in code.splitlines() if line.strip()),
                        "",
                    )
                    first_code_line = re.sub(r"\s+", " ", first_code_line)

                    if len(first_code_line) > 72:
                        first_code_line = first_code_line[:69].rstrip() + "..."

                    base_title = f"{language_name} code"

                    if first_code_line:
                        base_title += f": {first_code_line}"
                    elif chat_title:
                        base_title += f" from {chat_title}"

                total_parts = len(chunks)

                for part_index, (chunk, start_line, end_line) in enumerate(
                    chunks, start=1
                ):
                    entry_title = base_title

                    if total_parts > 1:
                        entry_title += (
                            f" (part {part_index}/{total_parts}, "
                            f"lines {start_line}-{end_line})"
                        )

                    tags = ["code", role.casefold()]

                    if language:
                        tags.append(language)

                    if attachment_name:
                        tags.extend(["attachment", attachment_name.casefold()])

                    payload = {
                        "category": "reference",
                        "title": entry_title,
                        "content": make_fenced_code(language, chunk),
                        "snapshot_date": None,
                        "source": (
                            "history code attachment"
                            if attachment_name
                            else "history code block"
                        ),
                        "source_titles": [chat_title],
                        "tags": tags,
                        "preserve_formatting": True,
                    }

                    if created_at and created_at.casefold() != "unknown":
                        payload["created_at"] = created_at

                    entry = normalize_memory_entry(
                        payload, default_source="history code block"
                    )

                    if entry is not None:
                        entries.append(entry)

    return entries


def remove_deterministic_code_blocks(transcript):
    """Remove closed code fences after they have been preserved exactly."""
    output_lines = []
    buffered_lines = []
    marker_prefix = ""
    opening_character = ""
    opening_length = 0

    for raw_line in re.sub(r"\r\n?", "\n", str(transcript or "")).split("\n"):
        if not opening_character:
            role_match = re.match(
                r"^((?:USER|ASSISTANT|SYSTEM|TOOL):\s*)(.*)$",
                raw_line,
                flags=re.IGNORECASE,
            )
            candidate = role_match.group(2) if role_match else raw_line
            opening = re.match(r"^[ \t]*(?P<fence>`{3,}|~{3,})(?:.*)$", candidate)

            if opening is None:
                output_lines.append(raw_line)
                continue

            fence = opening.group("fence")
            opening_character = fence[0]
            opening_length = len(fence)
            marker_prefix = role_match.group(1) if role_match else ""
            buffered_lines = [raw_line]
            continue

        buffered_lines.append(raw_line)
        closing_pattern = (
            r"^[ \t]*"
            + re.escape(opening_character)
            + "{"
            + str(opening_length)
            + r",}[ \t]*$"
        )

        if re.match(closing_pattern, raw_line):
            output_lines.append(
                marker_prefix + "[Exact code preserved as a separate memory entry]"
            )
            buffered_lines = []
            marker_prefix = ""
            opening_character = ""
            opening_length = 0

    # Do not discard malformed/unclosed code fences.
    if buffered_lines:
        output_lines.extend(buffered_lines)

    return "\n".join(output_lines)
