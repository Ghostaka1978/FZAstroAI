from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path

from .prompt import PROJECT_RULES
from .project_scanner import ProjectFile, ProjectScan, scan_project
from .task_classifier import DevTask, classify_dev_task

TRACEBACK_PATH_RE = re.compile(r'File "(?P<path>[^"]+\.py)", line (?P<line>\d+)')


CONTENT_EVIDENCE_EXTENSIONS = {
    ".py",
    ".md",
    ".txt",
    ".ps1",
    ".spec",
    ".json",
    ".toml",
    ".yaml",
    ".yml",
    ".ini",
    ".cfg",
}

GENERIC_REQUEST_TERMS = {
    "add",
    "adds",
    "after",
    "again",
    "all",
    "also",
    "and",
    "any",
    "app",
    "apply",
    "available",
    "before",
    "break",
    "change",
    "code",
    "configured",
    "confirmed",
    "create",
    "default",
    "diff",
    "does",
    "dont",
    "explicit",
    "file",
    "files",
    "fix",
    "for",
    "requirements",
    "requirement",
    "tokens",
    "tokenized",
    "persistent",
    "path",
    "mode",
    "fzastro",
    "existing",
    "desktop",
    "generate",
    "generated",
    "implementation",
    "inside",
    "must",
    "not",
    "patch",
    "preserve",
    "project",
    "proposal",
    "patchproposal",
    "propose",
    "return",
    "returns",
    "remove",
    "require",
    "required",
    "safe",
    "secure",
    "should",
    "summary",
    "summarize",
    "suggested",
    "test",
    "tests",
    "that",
    "the",
    "this",
    "update",
    "unified",
    "validate",
    "validation",
    "commands",
    "risk",
    "risks",
    "user",
    "with",
    "without",
}


def _important_request_terms(task: "DevTask") -> tuple[str, ...]:
    """Return generic evidence terms derived from the user request.

    This deliberately avoids task-specific file lists. The context planner ranks
    files because their path/symbol/body content matches these terms, not
    because a specific domain such as Web Companion is hardcoded.
    """

    raw_terms: list[str] = []
    request = task.request or ""
    raw_terms.extend(task.terms)
    raw_terms.extend(
        match.group(1) for match in re.finditer(r"['\"]([^'\"]{2,})['\"]", request)
    )

    expanded: list[str] = []
    for term in raw_terms:
        lower = str(term).strip().lower().replace("-", "_")
        if not lower:
            continue
        expanded.append(lower)
        if lower.endswith("s") and len(lower) > 4:
            expanded.append(lower[:-1])
        if "_" in lower:
            parts = [part for part in lower.split("_") if part]
            expanded.extend(parts)
            expanded.extend(
                part[:-1] for part in parts if part.endswith("s") and len(part) > 4
            )

    tokens = [
        token
        for token in dict.fromkeys(expanded)
        if len(token) >= 3 and token not in GENERIC_REQUEST_TERMS
    ]

    # A few adjacent phrases are useful because they are derived from the task
    # itself (for example "lan token" or "token fallback") and remain generic.
    request_tokens = [
        token
        for token in _tokenize(request)
        if len(token) >= 3 and token not in GENERIC_REQUEST_TERMS
    ]
    phrases: list[str] = []
    for left, right in zip(request_tokens, request_tokens[1:]):
        if left != right:
            phrases.append(f"{left} {right}")
    return tuple(dict.fromkeys(tokens + phrases))


def _read_text_for_evidence(
    root: Path, file: ProjectFile, *, max_chars: int = 120_000
) -> str:
    if file.extension not in CONTENT_EVIDENCE_EXTENSIONS:
        return ""
    try:
        text = (root / file.path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if len(text) > max_chars:
        return text[:max_chars]
    return text


def _build_content_evidence(
    root: Path, files: tuple[ProjectFile, ...], task: "DevTask"
) -> dict[str, tuple[float, list[str]]]:
    """Score files by task-derived content evidence.

    The ranking is evidence-driven: terms are extracted from the request, each
    file is scanned for path/symbol/import/body matches, and common terms are
    down-weighted by document frequency.
    """

    terms = _important_request_terms(task)
    if not terms:
        return {}

    file_texts: dict[str, str] = {}
    term_paths: dict[str, set[str]] = {term: set() for term in terms}
    path_blobs: dict[str, str] = {}

    for file in files:
        text_blob = _read_text_for_evidence(root, file)
        metadata_blob = " ".join(
            [
                file.path.replace("/", " ").replace("_", " "),
                *file.symbols,
                *file.imports,
            ]
        )
        combined = f"{metadata_blob}\n{text_blob}".lower()
        file_texts[file.path] = combined
        path_blobs[file.path] = metadata_blob.lower()
        for term in terms:
            if term in combined:
                term_paths[term].add(file.path)

    total_files = max(1, len(files))
    evidence: dict[str, tuple[float, list[str]]] = {}
    for file in files:
        combined = file_texts.get(file.path, "")
        metadata = path_blobs.get(file.path, "")
        score = 0.0
        reasons: list[str] = []
        matched: list[str] = []
        for term in terms:
            if term not in combined:
                continue
            df = max(1, len(term_paths.get(term, ())))
            idf = 1.0 + math.log((total_files + 1) / (df + 1))
            idf = max(0.25, min(3.0, idf))
            if term in metadata:
                term_score = 5.0 * idf
            else:
                # Count a few occurrences but cap to avoid one large file
                # dominating the ranking.
                count = min(3, combined.count(term))
                term_score = (1.4 + count * 0.8) * idf
            if " " in term:
                term_score *= 1.25
            score += term_score
            matched.append(term)
        if score > 0:
            if matched:
                reasons.append("content evidence: " + ", ".join(matched[:8]))
            evidence[file.path] = (round(score, 2), reasons)
    return evidence


def _module_path_for_source(path: str) -> str:
    module = path
    if module.endswith(".py"):
        module = module[:-3]
    return module.replace("/", ".")


def _source_test_relationship_bonus(
    root: Path,
    files: tuple[ProjectFile, ...],
    base_scores: dict[str, tuple[float, list[str]]],
) -> dict[str, tuple[float, list[str]]]:
    """Boost tests that appear to exercise highly relevant source files.

    This is generic source/test pairing. It derives relationship candidates from
    selected source paths, module names, stems, imports, and test content.
    """

    source_candidates = [
        file
        for file in files
        if file.extension == ".py"
        and file.role != "test"
        and base_scores.get(file.path, (0.0, []))[0] > 0
    ]
    source_candidates.sort(key=lambda file: -base_scores.get(file.path, (0.0, []))[0])
    source_candidates = source_candidates[:8]
    if not source_candidates:
        return {}

    bonuses: dict[str, tuple[float, list[str]]] = {}
    for test_file in (file for file in files if file.role == "test"):
        try:
            test_text = (
                (root / test_file.path)
                .read_text(encoding="utf-8", errors="replace")
                .lower()
            )
        except OSError:
            test_text = ""
        path_lower = test_file.path.lower()
        score = 0.0
        reasons: list[str] = []
        for source in source_candidates:
            source_score = base_scores.get(source.path, (0.0, []))[0]
            if source_score <= 0:
                continue
            source_path = source.path.lower()
            stem = Path(source.path).stem.lower()
            module = _module_path_for_source(source.path).lower()
            package_parts = source_path.split("/")[:-1]
            package_tail = "_".join(
                part for part in package_parts if part not in {"fzastro_ai"}
            )
            relation_hit = False
            path_related = False
            if stem and stem in path_lower:
                score += min(30.0, 8.0 + source_score * 0.35)
                relation_hit = True
                path_related = True
            if package_tail and package_tail in path_lower:
                score += min(14.0, 3.0 + source_score * 0.12)
                relation_hit = True
                path_related = True
            imports_module = (
                f"from {module}" in test_text or f"import {module}" in test_text
            )
            if imports_module or (
                path_related and (module in test_text or source.path in test_text)
            ):
                score += min(22.0, 5.0 + source_score * 0.22)
                relation_hit = True
            elif path_related and stem and stem in test_text:
                score += min(10.0, 2.0 + source_score * 0.1)
                relation_hit = True
            if relation_hit:
                reasons.append(f"related test for `{source.path}`")
        if score > 0:
            bonuses[test_file.path] = (
                round(score, 2),
                list(dict.fromkeys(reasons))[:5],
            )
    return bonuses


@dataclass(frozen=True)
class ContextFile:
    """One selected file with a rank and optional text excerpt."""

    path: str
    score: float
    role: str
    reason: str
    excerpt: str = ""
    symbols: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class DevContext:
    """The compact developer context shown to the user/model."""

    task: DevTask
    root: str
    files: tuple[ContextFile, ...]
    summary: str
    prompt_package: str
    audit_manifest: str = ""
    audit_file_count: int = 0


def _tokenize(text: str) -> set[str]:
    return {
        token.lower() for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]{1,}", text or "")
    }


def _path_matches_hint(path: str, hint: str) -> bool:
    normalized_path = path.replace("\\", "/").lower()
    normalized_hint = hint.replace("\\", "/").lower()
    return (
        normalized_path.endswith(normalized_hint) or normalized_hint in normalized_path
    )


def _traceback_path_hints(extra_text: str) -> tuple[str, ...]:
    hints: list[str] = []
    for match in TRACEBACK_PATH_RE.finditer(extra_text or ""):
        raw_path = match.group("path").replace("\\", "/")
        parts = raw_path.split("/")
        for index, part in enumerate(parts):
            if part == "fzastro_ai" or part == "tests":
                hints.append("/".join(parts[index:]))
                break
        else:
            hints.append(parts[-1])
    return tuple(dict.fromkeys(hints))


def _score_file(
    file: ProjectFile,
    task: DevTask,
    extra_text: str = "",
    *,
    evidence: dict[str, tuple[float, list[str]]] | None = None,
    test_relationships: dict[str, tuple[float, list[str]]] | None = None,
) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []
    lower_path = file.path.lower()
    path_tokens = _tokenize(file.path.replace("/", " ").replace("_", " "))
    symbol_tokens = _tokenize(" ".join(file.symbols))
    request_tokens = {term for term in task.terms if term not in GENERIC_REQUEST_TERMS}
    if "ui" not in task.role_hints:
        request_tokens.discard("ui")

    overlap = request_tokens.intersection(path_tokens | symbol_tokens)
    if overlap:
        score += len(overlap) * 5.0
        reasons.append("matches request terms: " + ", ".join(sorted(overlap)[:6]))

    all_hints = tuple(task.path_hints) + _traceback_path_hints(extra_text)
    for hint in all_hints:
        if _path_matches_hint(file.path, hint):
            score += 40.0
            reasons.append(f"explicit path hint: {hint}")
            break

    if task.role_hints and file.role in task.role_hints:
        score += 5.0
        reasons.append(f"role hint: {file.role}")

    normalized_path_key = lower_path.replace("/", "_").replace("-", "_")
    for role_hint in task.role_hints:
        normalized_role = role_hint.replace("-", "_")
        if normalized_role and normalized_role in normalized_path_key:
            score += 24.0
            reasons.append(f"path/category hint: {role_hint}")
            break

    if evidence and file.path in evidence:
        evidence_score, evidence_reasons = evidence[file.path]
        score += evidence_score
        reasons.extend(evidence_reasons)

    if test_relationships and file.path in test_relationships:
        related_score, related_reasons = test_relationships[file.path]
        score += related_score
        reasons.extend(related_reasons)

    if task.mode == "test" and file.role == "test":
        score += 7.0
        reasons.append("test-mode candidate")
    elif task.mode == "release" and file.role in {"docs", "build"}:
        score += 8.0
        reasons.append("release-mode candidate")
    elif (
        task.mode == "patch"
        and file.role
        in {
            "core",
            "ui",
            "actions",
            "worker",
            "astro_tools",
        }
        and (score > 0 or file.role in task.role_hints)
    ):
        score += 3.0
        reasons.append("patch-mode implementation candidate")

    if "fzastro_ai/app.py" == lower_path and (
        score > 0 or "app" in request_tokens or "core" in task.role_hints
    ):
        score += 2.0
        reasons.append("main application integration point")

    if lower_path.endswith("/__init__.py") and score > 0:
        score += 1.5
        reasons.append("package export/integration point")

    if task.mode == "patch" and file.role == "test":
        score *= 0.48
        reasons.append(
            "test file retained but ranked after implementation evidence for patch task"
        )

    if file.modified:
        score += 0.75
        reasons.append("locally modified file")

    return score, reasons


def _read_excerpt(root: Path, path: str, max_chars: int) -> str:
    absolute = root / path
    try:
        text = absolute.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""

    if len(text) <= max_chars:
        return text

    head = max_chars // 2
    tail = max_chars - head
    return (
        text[:head].rstrip()
        + "\n\n# ... excerpt truncated ...\n\n"
        + text[-tail:].lstrip()
    )


def _make_summary(
    task: DevTask,
    selected: list[ContextFile],
    scan: ProjectScan,
    *,
    audit_file_count: int = 0,
) -> str:
    lines = [
        f"Mode: {task.mode}",
        f"Scope: {task.scope}",
        f"Confidence: {task.confidence:.2f}",
        f"Project files scanned: {scan.file_count} ({scan.python_count} Python, {scan.test_count} tests)",
        f"Selected context files: {len(selected)}",
    ]
    if audit_file_count:
        lines.append(f"Project audit indexed Python files: {audit_file_count}")
    if task.role_hints:
        lines.append("Role hints: " + ", ".join(task.role_hints))
    if task.path_hints:
        lines.append("Path hints: " + ", ".join(task.path_hints))
    return "\n".join(lines)


def _symbol_preview(symbols: tuple[str, ...], *, limit: int = 8) -> str:
    if not symbols:
        return "-"
    preview = ", ".join(symbols[:limit])
    if len(symbols) > limit:
        preview += ", ..."
    return preview


def _build_audit_manifest(selected: list[ContextFile], scan: ProjectScan) -> str:
    """Return a compact index for broad project audits.

    This deliberately indexes every selected Python file without pretending that
    every file body was loaded into the model context. Deep file bodies still
    appear later as excerpts for the most relevant files.
    """

    if not selected:
        return ""

    lines = [
        "# Project Audit Index",
        "",
        f"Indexed Python files: {len(selected)} of {scan.python_count} scanned Python files.",
        "The index covers every scanned Python file. Only files with excerpts below are deep-read initially; use follow-up read/search tools for deeper inspection.",
        "",
        "| File | Role | Score | Symbols |",
        "|---|---:|---:|---|",
    ]
    for file in selected:
        symbols = _symbol_preview(file.symbols, limit=4).replace("|", "\\|")
        lines.append(f"| `{file.path}` | {file.role} | {file.score:g} | {symbols} |")
    return "\n".join(lines)


def build_prompt_package(
    task: DevTask,
    selected: list[ContextFile],
    *,
    max_chars: int = 42_000,
    audit_manifest: str = "",
) -> str:
    """Build the model-facing, reviewable context package."""

    header = [
        "# Developer Workbench Context",
        "",
        "FZAstro AI Developer Agent Context",
        "",
        "## User request",
        task.request or "(empty request)",
        "",
        "## Visible workflow rules",
        "- Inspect relevant files before proposing edits.",
        "- Never claim a file was inspected unless the file content appears below or a tool read it.",
        "- Prefer unified diffs over full-file rewrites.",
        "- Preserve existing behavior unless the request explicitly changes it.",
        "- Do not modify generated files, external/, or bundled_apps/ unless explicitly approved.",
        "- Add or update regression tests when behavior changes.",
        "- After patching, run compileall and targeted pytest when possible.",
        "",
        "## Persistent FZAstro project rules",
        *(f"- {rule}" for rule in PROJECT_RULES),
        "",
        "## Context scope",
        f"- Task scope: `{task.scope}`",
    ]

    if audit_manifest:
        header.extend(
            [
                "- Broad project audit requested: all scanned Python files are indexed below.",
                "- The model must not claim full body inspection for files that only appear in the index.",
            ]
        )
    else:
        header.append("- Focused context selected from task/path/symbol relevance.")

    header.append("")
    if audit_manifest:
        deep_items = [item for item in selected if item.excerpt]
        header.append("## Initial deep-read files")
        for item in deep_items:
            symbol_note = (
                f"; symbols: {_symbol_preview(item.symbols, limit=5)}"
                if item.symbols
                else ""
            )
            header.append(f"- {item.path} [{item.role}] — {item.reason}{symbol_note}")
        header.extend(["", audit_manifest])
    else:
        header.append("## Selected files")
        for item in selected:
            symbol_note = (
                f"; symbols: {_symbol_preview(item.symbols, limit=5)}"
                if item.symbols
                else ""
            )
            header.append(f"- {item.path} [{item.role}] — {item.reason}{symbol_note}")

    parts = ["\n".join(header).rstrip()]
    remaining = max_chars - len(parts[0])

    for item in selected:
        if remaining <= 1200:
            break
        excerpt = item.excerpt
        if not excerpt:
            continue
        fence = "```"
        block = f"\n\n## File: {item.path}\n{fence}\n{excerpt}\n{fence}\n"
        if len(block) > remaining:
            block = (
                block[: remaining - 80].rstrip()
                + "\n# ... context package truncated ...\n```\n"
            )
        parts.append(block)
        remaining -= len(block)

    return "".join(parts).strip()


def build_dev_context(
    root: Path | str,
    request: str,
    *,
    scan: ProjectScan | None = None,
    extra_text: str = "",
    max_files: int = 12,
    max_excerpt_chars: int = 8_000,
    max_prompt_chars: int = 42_000,
) -> DevContext:
    """Select and package files likely to be useful for a coding task."""

    root_path = Path(root).resolve()
    project_scan = scan or scan_project(root_path)
    task = classify_dev_task(request)

    evidence = _build_content_evidence(root_path, project_scan.files, task)

    # First pass without source/test relationships. The second pass uses these
    # evidence scores to boost nearby tests generically, for example a test file
    # whose path or imports match a relevant implementation module.
    initial_scores: dict[str, tuple[float, list[str]]] = {}
    for file in project_scan.files:
        score, reasons = _score_file(
            file,
            task,
            extra_text=extra_text,
            evidence=evidence,
        )
        if score > 0:
            initial_scores[file.path] = (score, reasons)

    test_relationships = _source_test_relationship_bonus(
        root_path, project_scan.files, initial_scores
    )

    ranked: list[tuple[float, ProjectFile, list[str]]] = []
    for file in project_scan.files:
        score, reasons = _score_file(
            file,
            task,
            extra_text=extra_text,
            evidence=evidence,
            test_relationships=test_relationships,
        )
        if score > 0:
            ranked.append((score, file, reasons))

    if not ranked:
        ranked = [
            (1.0, file, ["general project context"])
            for file in project_scan.files
            if file.path in {"README.md", "fzastro_ai/app.py", "fzastro_ai/config.py"}
        ]

    ranked.sort(key=lambda item: (-item[0], item[1].path.lower()))

    if task.mode == "patch" and task.scope != "project_audit":
        # Patch planning should inspect implementation evidence before tests.
        # Test files stay in the context, but they should not displace the
        # source files that actually contain the behavior to change.  This is
        # generic ranking hygiene rather than a domain-specific route.
        implementation = [
            item
            for item in ranked
            if item[1].role != "test" and not item[1].path.lower().startswith("docs/")
        ]
        tests = [item for item in ranked if item[1].role == "test"]
        support = [
            item for item in ranked if item not in implementation and item not in tests
        ]
        ordered: list[tuple[float, ProjectFile, list[str]]] = []
        implementation_quota = max(
            1, min(max_files, max_files - min(3, max_files // 3))
        )
        test_quota = max(1, min(3, max_files // 3))
        ordered.extend(implementation[:implementation_quota])
        ordered.extend(tests[:test_quota])
        ordered.extend(support[: max(0, max_files - len(ordered))])
        for item in ranked:
            if item not in ordered:
                ordered.append(item)
            if len(ordered) >= len(ranked):
                break
        ranked = ordered

    audit_manifest = ""
    audit_file_count = 0
    selected: list[ContextFile] = []

    if task.scope == "project_audit":
        ranked_by_path = {
            file.path: (score, reasons) for score, file, reasons in ranked
        }
        python_files = [file for file in project_scan.files if file.extension == ".py"]

        def audit_sort_key(file: ProjectFile) -> tuple[float, str]:
            score, _reasons = ranked_by_path.get(file.path, (0.0, []))
            modified_bonus = 1.0 if file.modified else 0.0
            return (-(score + modified_bonus), file.path.lower())

        python_files.sort(key=audit_sort_key)
        deep_excerpt_paths = {file.path for file in python_files[:max_files]}
        for file in python_files:
            score, reasons = ranked_by_path.get(file.path, (1.0, []))
            if not reasons:
                reasons = ["project audit inventory entry"]
            excerpt = (
                _read_excerpt(root_path, file.path, max_excerpt_chars)
                if file.path in deep_excerpt_paths
                else ""
            )
            selected.append(
                ContextFile(
                    path=file.path,
                    score=round(max(score, 1.0), 2),
                    role=file.role,
                    reason="; ".join(dict.fromkeys(reasons)),
                    excerpt=excerpt,
                    symbols=file.symbols,
                )
            )
        audit_file_count = len(selected)
        audit_manifest = _build_audit_manifest(selected, project_scan)
    else:
        for score, file, reasons in ranked[:max_files]:
            selected.append(
                ContextFile(
                    path=file.path,
                    score=round(score, 2),
                    role=file.role,
                    reason="; ".join(dict.fromkeys(reasons)),
                    excerpt=_read_excerpt(root_path, file.path, max_excerpt_chars),
                    symbols=file.symbols,
                )
            )

    summary = _make_summary(
        task, selected, project_scan, audit_file_count=audit_file_count
    )
    prompt_package = build_prompt_package(
        task,
        selected,
        max_chars=max_prompt_chars,
        audit_manifest=audit_manifest,
    )
    return DevContext(
        task=task,
        root=str(root_path),
        files=tuple(selected),
        summary=summary,
        prompt_package=prompt_package,
        audit_manifest=audit_manifest,
        audit_file_count=audit_file_count,
    )
