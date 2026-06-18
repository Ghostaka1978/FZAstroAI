"""Pure routing and intent-detection helpers.

These functions were extracted from FZAstroAI to keep the main window/controller
smaller. They are intentionally conservative and preserve the old regex logic.
"""

import ast
import re

from ..logging_utils import log_debug

IMAGE_FILE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif")


def build_web_query(text):
    clean_text = str(text or "").strip()
    clean_text = re.sub(r"\s+", " ", clean_text)
    clean_text = clean_text.replace("\n", " ")

    stock_match = re.search(
        r"\b([A-Za-z]{1,5})\s+(stock\s+)?price\b", clean_text, flags=re.IGNORECASE
    )

    if stock_match:
        ticker = stock_match.group(1).upper()
        return f"{ticker} stock price quote marketwatch yahoo finance nasdaq"

    if len(clean_text) > 180:
        clean_text = clean_text[:180]

    return f"current reliable information about {clean_text}"


def is_python_execution_request(text):
    clean_text = str(text or "").strip()

    if not clean_text:
        return False

    first_line = clean_text.splitlines()[0].strip().casefold()
    return bool(
        first_line in {"/run-python", "/run-py", "/py"}
        or first_line.startswith("/run-python ")
        or first_line.startswith("/run-python:")
        or first_line.startswith("/run-py ")
        or first_line.startswith("/run-py:")
        or first_line.startswith("/py ")
        or first_line.startswith("/py:")
    )


def is_python_generate_and_test_request(text):
    clean_text = re.sub(r"\s+", " ", str(text or "")).strip().casefold()

    if not clean_text:
        return False

    if is_python_execution_request(clean_text):
        return False

    if re.search(r"https?://", clean_text):
        return False

    mentions_python = bool(re.search(r"\b(?:python|py)\b", clean_text))
    mentions_code = bool(
        re.search(
            r"\b(?:code|script|program|function|snippet|example|lines?)\b",
            clean_text,
        )
    )
    asks_generation = bool(
        re.search(
            r"\b(?:give|write|create|make|generate|build|produce|show)\b",
            clean_text,
        )
    )
    asks_test = bool(
        re.search(
            r"\b(?:test|run|execute|check|verify|validate|see if it works|works)\b",
            clean_text,
        )
    )

    return bool(mentions_python and mentions_code and asks_generation and asks_test)


def python_code_has_risky_auto_actions(code):
    """Return True when generated Python should not be auto-executed.

    This is not a sandbox. It only gates model-generated auto-runs. Manual
    execution through the Run button or /run-python remains available for code
    the user explicitly trusts.
    """
    clean_code = str(code or "")

    if not clean_code.strip():
        return False

    risky_patterns = (
        r"\bsubprocess\b",
        r"\bos\.system\s*\(",
        r"\bos\.popen\s*\(",
        r"\bshutil\.rmtree\s*\(",
        r"\bos\.(?:remove|unlink|rmdir|removedirs|rename|replace)\s*\(",
        r"\bpathlib\.Path\([^\n]*\)\.(?:"
        r"unlink|rmdir|rename|replace|write_text|write_bytes|touch|mkdir|open"
        r")\s*\(",
        r"\b(?:requests|urllib|httpx|socket|ctypes|importlib)\b",
        r"\bopen\s*\([^\n]*(?:"
        r"[\'\"]w[\'\"]|[\'\"]a[\'\"]|[\'\"]x[\'\"]|"
        r"[\'\"]wb[\'\"]|[\'\"]ab[\'\"]|[\'\"]xb[\'\"]"
        r")",
        r"\b(?:eval|exec|compile|getattr|setattr|delattr)\s*\(",
        r"__import__\s*\(",
    )

    if any(
        re.search(pattern, clean_code, flags=re.IGNORECASE)
        for pattern in risky_patterns
    ):
        return True

    try:
        tree = ast.parse(clean_code)
    except SyntaxError:
        # If the generated block is not parseable Python, do not auto-run it.
        return True

    risky_modules = {
        "ctypes",
        "ftplib",
        "httpx",
        "importlib",
        "os",
        "pathlib",
        "requests",
        "shutil",
        "socket",
        "subprocess",
        "urllib",
        "urllib.request",
        "webbrowser",
    }
    risky_function_names = {
        "compile",
        "delattr",
        "eval",
        "exec",
        "getattr",
        "input",
        "open",
        "setattr",
        "__import__",
    }
    risky_method_names = {
        "chmod",
        "mkdir",
        "open",
        "popen",
        "remove",
        "removedirs",
        "rename",
        "replace",
        "rmdir",
        "rmtree",
        "spawnl",
        "spawnle",
        "spawnlp",
        "spawnlpe",
        "spawnv",
        "spawnve",
        "spawnvp",
        "spawnvpe",
        "startfile",
        "symlink",
        "system",
        "touch",
        "unlink",
        "write_bytes",
        "write_text",
    }
    risky_imported_names = set(risky_function_names)
    risky_module_aliases = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                module_name = str(alias.name or "")
                top_level_name = module_name.split(".", 1)[0]

                if module_name in risky_modules or top_level_name in risky_modules:
                    return True

        elif isinstance(node, ast.ImportFrom):
            module_name = str(node.module or "")
            top_level_name = module_name.split(".", 1)[0]

            if module_name in risky_modules or top_level_name in risky_modules:
                return True

    # A second pass is kept for future extension and for manually assembled ASTs.
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_name = str(alias.asname or alias.name or "").split(".", 1)[0]
                module_name = str(alias.name or "").split(".", 1)[0]

                if module_name in risky_modules:
                    risky_module_aliases.add(imported_name)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        func = node.func

        if isinstance(func, ast.Name):
            if func.id in risky_function_names or func.id in risky_imported_names:
                return True

        elif isinstance(func, ast.Attribute):
            if func.attr in risky_method_names:
                return True

            if (
                isinstance(func.value, ast.Name)
                and func.value.id in risky_module_aliases
            ):
                return True

    return False


def extract_python_code_from_text(text, force=False):
    raw_text = str(text or "")
    clean_text = raw_text.strip()

    if not clean_text:
        return ""

    code_blocks = []

    for match in re.finditer(r"(?s)```([A-Za-z0-9_+\-.#]*)\s*\n(.*?)\n```", raw_text):
        language = str(match.group(1) or "").strip().casefold()
        code = str(match.group(2) or "").strip("\n")

        if language in {"", "python", "py"}:
            code_blocks.append(code)

    if code_blocks:
        return "\n\n".join(block for block in code_blocks if block.strip()).strip()

    if force:
        return clean_text

    first_line, _, remainder = clean_text.partition("\n")
    first_line = first_line.strip()
    remainder = remainder.lstrip()

    command_match = re.match(
        r"^/(?:run-python|run-py|py)\s*:?\s*(.*)$", first_line, flags=re.I
    )

    if not command_match:
        return ""

    inline_code = str(command_match.group(1) or "").strip()

    if inline_code and remainder:
        return f"{inline_code}\n{remainder}".strip()

    return (remainder or inline_code).strip()


def looks_like_python_code(text):
    clean_text = str(text or "").strip()

    if not clean_text:
        return False

    if clean_text.startswith("/"):
        return False

    python_patterns = (
        r"^\s*(?:def|class|import|from|for|while|if|elif|else|try|except|with)\b",
        r"\bprint\s*\(",
        r"\breturn\b",
        r"\b(?:True|False|None)\b",
        r"^\s*[A-Za-z_][A-Za-z0-9_]*\s*=",
        r"^\s*#",
    )

    lines = [line for line in clean_text.splitlines() if line.strip()]
    matched = 0

    for line in lines[:12]:
        if any(re.search(pattern, line) for pattern in python_patterns):
            matched += 1

    return matched > 0


def extract_last_python_code_block_from_text(text):
    raw_text = str(text or "")
    matches = list(re.finditer(r"(?s)```([A-Za-z0-9_+\-.#]*)\s*\n(.*?)\n```", raw_text))

    for match in reversed(matches):
        language = str(match.group(1) or "").strip().casefold()
        code = str(match.group(2) or "").strip("\n")

        if not code.strip():
            continue

        if language in {"python", "py"}:
            return code.strip()

    # Fallback: allow an unlabeled fenced block only when it strongly looks like Python.
    for match in reversed(matches):
        language = str(match.group(1) or "").strip().casefold()
        code = str(match.group(2) or "").strip("\n")

        if language == "" and looks_like_python_code(code):
            return code.strip()

    return ""


def is_web_image_request(text):
    clean = re.sub(r"\s+", " ", str(text or "").lower()).strip()

    if not clean:
        return False

    patterns = [
        r"\b(?:get|find|fetch|show|give|search(?:\s+for)?|look\s+up|retrieve|download)\s+"
        r"(?:me\s+)?(?:an?\s+|some\s+|the\s+)?"
        r"(?:image|photo|picture|wallpaper)s?\b",
        r"\b(?:image|photo|picture|wallpaper)s?\s+" r"(?:of|from|for)\b",
        r"\b(?:show|send)\s+(?:me\s+)?"
        r"(?:an?\s+|some\s+|the\s+)?"
        r"(?:image|photo|picture|wallpaper)s?\b",
    ]

    return any(re.search(pattern, clean) for pattern in patterns)


def references_recent_image(text):
    """Return True when a message likely refers to an image already shown."""
    clean = re.sub(r"\s+", " ", str(text or "").lower()).strip()

    if not clean:
        return False

    patterns = [
        r"\b(?:this|that|the|previous|above|shown|displayed)\s+"
        r"(?:image|photo|picture|galaxy|nebula|object)\b",
        r"\b(?:image|photo|picture)\s+(?:you\s+)?(?:showed|found|displayed)\b",
        r"\b(?:how|what)\s+(?:is|about)\s+(?:this|that|it)\b",
        r"\b(?:does|do)\s+(?:this|that|it)\s+look\b",
    ]

    return any(re.search(pattern, clean) for pattern in patterns)


def has_explicit_http_url(text):
    return bool(
        re.search(r"https?://[^\s<>'\"]+", str(text or ""), flags=re.IGNORECASE)
    )


def is_website_screenshot_request(text):
    clean = str(text or "")

    if not has_explicit_http_url(clean):
        return False

    screenshot_patterns = [
        r"\b(?:take|capture|get|make|create|show)\b.*"
        r"\b(?:screenshot|screen[\s-]*shot)\b",
        r"\b(?:screenshot|screen[\s-]*shot)\b.*\b(?:of|from|for)\b",
    ]

    return any(
        re.search(pattern, clean, flags=re.IGNORECASE)
        for pattern in screenshot_patterns
    )


def is_rendered_page_request(text):
    clean = str(text or "")

    if not has_explicit_http_url(clean):
        return False

    if is_website_screenshot_request(clean):
        return False

    rendered_page_patterns = [
        r"\b(?:read|open|extract|scrape|inspect|analyze|analyse|summarize|summarise|review|check|explain|get|give|show|collect|list|save|download|pull)\b.*"
        r"\b(?:page|webpage|website|article|url|link|links|table|tables|image|images|content|text|html|this)\b",
        r"\b(?:page|webpage|website|article|url|link|links|table|tables|image|images|content|text|html)\b.*"
        r"\b(?:read|open|extract|scrape|inspect|analyze|analyse|summarize|summarise|review|check|explain|get|give|show|collect|list|save|download|pull)\b",
        r"\b(?:what\s+does|what's|what\s+is)\b.*"
        r"\b(?:this|that|the)\b.*\b(?:page|webpage|website|article|url|link|links|table|tables|image|images)\b.*"
        r"\b(?:say|about|contain)\b",
        r"\b(?:what\s+does|what's|what\s+is)\b.*https?://.*"
        r"\b(?:say|about|contain)\b",
        r"\b(?:visible\s+text|page\s+text|article\s+text|page\s+content|article\s+content|"
        r"rendered\s+html|final\s+html|page\s+html|rendered\s+page|dynamic\s+page|javascript\s+page)\b",
        r"^\s*(?:read|open|extract|scrape|inspect|analyze|analyse|summarize|summarise|review|check|explain|get|give|show|collect|list|save|download|pull)\b.*https?://",
        r"https?://[^\s<>'\"]+.*\b(?:read|open|extract|scrape|inspect|analyze|analyse|summarize|summarise|review|check|explain|get|give|show|collect|list|save|download|pull)\b",
    ]

    return any(
        re.search(pattern, clean, flags=re.IGNORECASE)
        for pattern in rendered_page_patterns
    )


def is_rendered_page_extraction_display_request(text):
    """Return True when a rendered page request should be shown directly."""
    clean = str(text or "")

    if not is_rendered_page_request(clean):
        return False

    direct_patterns = [
        r"\b(?:extract|scrape|pull|collect|list|get|give|show|save|download)\b.*"
        r"\b(?:image|images|link|links|table|tables|text|content|html)\b",
        r"\b(?:image|images|link|links|table|tables|text|content|html)\b.*"
        r"\b(?:extract|scrape|pull|collect|list|get|give|show|save|download)\b",
        r"\b(?:visible\s+text|page\s+text|article\s+text|page\s+content|article\s+content|"
        r"rendered\s+html|final\s+html|page\s+html)\b",
    ]

    return any(
        re.search(pattern, clean, flags=re.IGNORECASE) for pattern in direct_patterns
    )


def is_deterministic_url_tool_request(text):
    clean = str(text or "")
    return is_website_screenshot_request(clean) or is_rendered_page_request(clean)


def explicitly_requests_external_information(text):
    clean = str(text or "").lower()

    if (
        not re.search(r"https?://[^\s<>\'\"]+", clean)
        and re.search(r"\b(?:python|code|script|snippet|example|program)\b", clean)
        and re.search(
            r"\b(?:show|write|create|generate|make|give|print|prints|example)\b",
            clean,
        )
    ):
        return False

    if is_web_image_request(clean):
        # "image from page 270 from <book/pdf>" is local document routing,
        # not an external web-image request.
        if re.search(
            r"\bpages?\s*\d{1,6}\b|\b\d{1,6}(?:st|nd|rd|th)\s+page\b", clean
        ) and re.search(
            r"\b(?:book|manual|document|doc|pdf|file)\b|\.pdf\b",
            clean,
        ):
            return False
        return True

    if re.search(r"https?://[^\s<>\'\"]+", clean):
        return True

    patterns = [
        r"\b(?:search|browse|check|look up|find)\b.*\b(?:web|internet|online)\b",
        r"\b(?:verify|confirm|cross[- ]?check)\b.*\b(?:online|externally|web|internet)\b",
        r"\b(?:latest|current|today|tonight|right now|recent|breaking)\b",
        r"\b(?:news|weather|forecast|stock price|market price|exchange rate|live score)\b",
        r"\b(?:website|webpage|url|screenshot|rendered page)\b",
    ]

    return any(re.search(pattern, clean) for pattern in patterns)


def references_document_knowledge(text):
    clean = str(text or "").lower()

    document_patterns = [
        r"\b(?:document|documents|doc|docs|pdf)\b",
        r"\b(?:my|our)\s+(?:spreadsheet|workbook|presentation|slides?|notes?)\b",
        r"\b(?:attached|attachment|uploaded|imported)\b",
        r"\b(?:knowledge library|document library|local library)\b",
        r"\b(?:my|our)\s+(?:file|files|document|documents|pdf|report|notes|data)\b",
        r"\b(?:in|from|according to|based on)\s+(?:my|our|the)\s+"
        r"(?:file|document|pdf|report|notes|library)\b",
        r"\bcompare\b.*\b(?:file|document|pdf|report|notes|library)\b",
        r"\b(?:book|books|manual|manuals)\b.*\b(?:have|imported|indexed|stored|available|loaded|library)\b",
        r"\b(?:what|which|list|show|give|tell|name)\b.*\b(?:books|manuals|documents|docs|pdfs|files)\b.*\b(?:have|imported|indexed|stored|available|loaded)\b",
        r"\b(?:first|second|third|fourth|fifth|last|other|another|same|1st|2nd|3rd|4th|5th)\s+(?:book|manual|document|doc|pdf|file)s?\b",
        r"\b(?:book|manual|document|doc|pdf|file)s?\b.*\b(?:talks?\s+about|covers?|summari[sz]e|summary|brief|overview|about)\b",
        r"\b(?:summari[sz]e|brief|describe|explain|what\s+(?:is|does|are|do))\b.*\b(?:book|manual|document|doc|pdf|file)s?\b",
    ]

    return any(re.search(pattern, clean) for pattern in document_patterns)


def is_ambiguous_follow_up(text):
    clean = str(text or "").lower().strip()

    patterns = [
        r"\b(?:it|its|that|this|they|them|those|these)\b",
        r"\b(?:the same|the one|the above|mentioned earlier)\b",
        r"^(?:and|also|what about|how about)\b",
        r"\b(?:first|second|third|fourth|fifth|last|other|another|same|1st|2nd|3rd|4th|5th)\s+(?:book|manual|document|doc|pdf|file)s?\b",
        r"\bother\s+\d+\s+(?:book|manual|document|doc|pdf|file)s?\b",
    ]

    return any(re.search(pattern, clean) for pattern in patterns)


def is_clearly_web_only_request(
    text, recent_context="", files=None, force_search=False
):
    if files:
        return False

    if not (force_search or explicitly_requests_external_information(text)):
        return False

    if references_document_knowledge(text):
        return False

    if is_ambiguous_follow_up(text):
        if references_document_knowledge(recent_context):
            return False

    return True


def explicitly_or_contextually_references_documents(text, recent_context=""):
    if references_document_knowledge(text):
        return True

    if is_ambiguous_follow_up(text):
        return references_document_knowledge(recent_context)

    return False


def is_local_document_direct_request(
    text, knowledge_library, files=None, log_exception_func=None
):
    """Return True when a request should be handled by the local PDF library."""
    if files:
        return False

    clean_text = str(text or "")

    if re.search(r"https?://[^\s<>\'\"]+", clean_text, flags=re.IGNORECASE):
        return False

    try:
        return bool(
            knowledge_library.query_is_direct_page_display_request(clean_text)
            or knowledge_library.query_requests_document_inventory(clean_text)
            or (
                knowledge_library.query_requests_verbatim_text(clean_text)
                and (
                    references_document_knowledge(clean_text)
                    or bool(knowledge_library.query_requested_pdf_pages(clean_text))
                    or knowledge_library.query_initial_visual_batch_request(clean_text)
                    is not None
                )
            )
        )
    except Exception as error:
        if log_exception_func is not None:
            log_exception_func("is_local_document_direct_request", error)
        log_debug("LOCAL DOCUMENT DIRECT PREFLIGHT ERROR", error)
        return False
