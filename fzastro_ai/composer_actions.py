"""Structured composer action definitions.

The registry is intentionally Qt-free so the command templates can be tested
without starting the desktop UI.  The GUI renders these definitions into the
composer Code, Actions, and Library menus and asks for field values when needed.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import Iterable, Mapping


@dataclass(frozen=True)
class ComposerActionField:
    """One value required to build a composer action prompt."""

    name: str
    label: str
    kind: str = "text"
    default: str | int = ""
    minimum: int = 1
    maximum: int = 100000


@dataclass(frozen=True)
class ComposerAction:
    """One menu action available from the chat composer."""

    action_id: str
    group: str
    label: str
    description: str
    prompt_template: str = ""
    fields: tuple[ComposerActionField, ...] = ()
    mode: str = "insert_prompt"


COMPOSER_TEXT_ACTIONS: tuple[ComposerAction, ...] = (
    ComposerAction(
        action_id="text.summarize",
        group="Text",
        label="Summarize",
        description="Summarize the selected or current composer text.",
        prompt_template="Summarize this clearly. Keep the important details and omit repetition:\n\n{text}",
        fields=(ComposerActionField("text", "Text:"),),
    ),
    ComposerAction(
        action_id="text.rewrite_clearer",
        group="Text",
        label="Rewrite clearer",
        description="Rewrite text to be clearer while preserving meaning.",
        prompt_template="Rewrite this so it is clearer, easier to scan, and preserves the original meaning:\n\n{text}",
        fields=(ComposerActionField("text", "Text:"),),
    ),
    ComposerAction(
        action_id="text.make_professional",
        group="Text",
        label="Make professional",
        description="Make text sound more polished and professional.",
        prompt_template="Rewrite this in a professional, calm, and direct tone. Preserve the facts:\n\n{text}",
        fields=(ComposerActionField("text", "Text:"),),
    ),
    ComposerAction(
        action_id="text.make_shorter",
        group="Text",
        label="Make shorter",
        description="Condense text without losing key meaning.",
        prompt_template="Make this shorter while preserving the key meaning and any important details:\n\n{text}",
        fields=(ComposerActionField("text", "Text:"),),
    ),
    ComposerAction(
        action_id="text.expand_details",
        group="Text",
        label="Expand with details",
        description="Expand notes into a fuller explanation.",
        prompt_template="Expand this into a more complete explanation with useful details and structure:\n\n{text}",
        fields=(ComposerActionField("text", "Text:"),),
    ),
    ComposerAction(
        action_id="text.to_checklist",
        group="Text",
        label="Turn into checklist",
        description="Convert text into a practical checklist.",
        prompt_template="Turn this into a practical checklist with clear steps and verification points:\n\n{text}",
        fields=(ComposerActionField("text", "Text:"),),
    ),
    ComposerAction(
        action_id="text.release_notes",
        group="Text",
        label="Turn into release notes",
        description="Convert notes into release notes.",
        prompt_template=(
            "Turn this into release notes with sections for changes, fixes, tests, "
            "and any migration or validation notes:\n\n{text}"
        ),
        fields=(ComposerActionField("text", "Text:"),),
    ),
    ComposerAction(
        action_id="text.documentation",
        group="Text",
        label="Turn into documentation",
        description="Convert notes into user-facing documentation.",
        prompt_template="Turn this into clear documentation with headings, steps, and warnings where useful:\n\n{text}",
        fields=(ComposerActionField("text", "Text:"),),
    ),
    ComposerAction(
        action_id="text.action_items",
        group="Text",
        label="Extract action items",
        description="Extract decisions, tasks, owners, and risks.",
        prompt_template="Extract action items, decisions, blockers, and risks from this text:\n\n{text}",
        fields=(ComposerActionField("text", "Text:"),),
    ),
    ComposerAction(
        action_id="text.clarifying_questions",
        group="Text",
        label="Ask clarifying questions",
        description="Generate the most useful follow-up questions.",
        prompt_template="Read this and ask the smallest set of clarifying questions needed before acting:\n\n{text}",
        fields=(ComposerActionField("text", "Text:"),),
    ),
)


COMPOSER_WEB_ACTIONS: tuple[ComposerAction, ...] = (
    ComposerAction(
        action_id="web.read_page",
        group="Web",
        label="Read page",
        description="Extract readable text from a webpage URL.",
        prompt_template="Read this page: {url}",
        fields=(ComposerActionField("url", "URL:"),),
    ),
    ComposerAction(
        action_id="web.summarize_page",
        group="Web",
        label="Summarize page",
        description="Extract and summarize a webpage URL.",
        prompt_template="Summarize this page: {url}",
        fields=(ComposerActionField("url", "URL:"),),
    ),
    ComposerAction(
        action_id="web.screenshot_page",
        group="Web",
        label="Screenshot page",
        description="Capture a visual screenshot of a webpage URL.",
        prompt_template="Take screenshot: {url}",
        fields=(ComposerActionField("url", "URL:"),),
    ),
)


COMPOSER_DOCUMENT_ACTIONS: tuple[ComposerAction, ...] = (
    ComposerAction(
        action_id="documents.list_documents",
        group="Documents",
        label="List documents",
        description="List the documents currently indexed in the knowledge library.",
        mode="direct",
    ),
    ComposerAction(
        action_id="documents.search_documents",
        group="Documents",
        label="Search knowledge library",
        description="Search the knowledge library for a topic or phrase.",
        prompt_template="Search my documents for: {query}",
        fields=(ComposerActionField("query", "Search for:"),),
    ),
    ComposerAction(
        action_id="documents.search_inside",
        group="Documents",
        label="Search inside document",
        description="Find text inside one specific imported book or document.",
        fields=(
            ComposerActionField("title", "Document or book title or number:"),
            ComposerActionField("query", "Search for:"),
        ),
        mode="direct",
    ),
    ComposerAction(
        action_id="documents.find_in_documents",
        group="Documents",
        label="Find in documents",
        description="Find a specific fact, phrase, object, or answer in documents.",
        prompt_template="Find this in my documents: {query}",
        fields=(ComposerActionField("query", "Find:"),),
    ),
    ComposerAction(
        action_id="documents.brief_document",
        group="Documents",
        label="Brief document",
        description="Create a brief for a specific book or document.",
        fields=(ComposerActionField("title", "Document or book title or number:"),),
        mode="direct",
    ),
    ComposerAction(
        action_id="documents.open_as_book",
        group="Documents",
        label="Open as book",
        description="Open a PDF/book page-image reader for a specific imported document.",
        fields=(ComposerActionField("title", "Document or book title or number:"),),
        mode="direct",
    ),
    ComposerAction(
        action_id="documents.ask_document",
        group="Documents",
        label="Ask about document",
        description="Ask a question using one specific imported document.",
        prompt_template="Answer using only this document: {title}\n\nQuestion: {query}",
        fields=(
            ComposerActionField("title", "Document or book title:"),
            ComposerActionField("query", "Question:"),
        ),
    ),
    ComposerAction(
        action_id="documents.show_page_image",
        group="Documents",
        label="Show page image",
        description="Open the PDF/book reader at a specific rendered page.",
        fields=(
            ComposerActionField("title", "Document or book title or number:"),
            ComposerActionField("page", "Page:", kind="int", default=1),
        ),
        mode="direct",
    ),
)


COMPOSER_IMAGING_ACTIONS: tuple[ComposerAction, ...] = (
    ComposerAction(
        action_id="imaging.plan_next_target",
        group="Imaging",
        label="PLAN NEXT TARGET",
        description="Create a safe review-only FZAstro Imaging/N.I.N.A. plan for the next best practical target.",
        mode="direct",
    ),
    ComposerAction(
        action_id="imaging.plan_specific_target",
        group="Imaging",
        label="PLAN SPECIFIC TARGET",
        description="Create a safe review-only FZAstro Imaging/N.I.N.A. plan for a named target.",
        fields=(
            ComposerActionField("target", "Target name:"),
            ComposerActionField(
                "exposure_seconds",
                "Exposure seconds:",
                kind="int",
                default=60,
                minimum=1,
                maximum=3600,
            ),
            ComposerActionField(
                "gain", "Gain:", kind="int", default=200, minimum=0, maximum=10000
            ),
        ),
        mode="direct",
    ),
    ComposerAction(
        action_id="imaging.open_plans_folder",
        group="Imaging",
        label="OPEN PLANS FOLDER",
        description="Open the folder containing generated FZAstro Imaging/N.I.N.A. review plans.",
        mode="direct",
    ),
)


COMPOSER_PYTHON_ACTIONS: tuple[ComposerAction, ...] = (
    ComposerAction(
        action_id="python.run_input",
        group="Python",
        label="Run input as Python",
        description="Execute the current composer input through the Python runner.",
        mode="direct",
    ),
    ComposerAction(
        action_id="python.run_selection",
        group="Python",
        label="Run selected code",
        description="Execute only the selected composer text through the Python runner.",
        mode="direct",
    ),
    ComposerAction(
        action_id="python.explain_code",
        group="Python",
        label="Explain this code",
        description="Insert an editable prompt that asks the model to explain selected code.",
        prompt_template="Explain this Python code:\n\n```python\n{code}\n```",
        fields=(ComposerActionField("code", "Code:"),),
    ),
    ComposerAction(
        action_id="python.debug_code",
        group="Python",
        label="Fix this error / debug code",
        description="Insert an editable debugging prompt for selected code or traceback.",
        prompt_template=(
            "Debug this Python code or traceback. Identify likely causes, fix the issue, "
            "and provide a minimal corrected version:\n\n```python\n{code}\n```"
        ),
        fields=(ComposerActionField("code", "Code or traceback:"),),
    ),
    ComposerAction(
        action_id="python.refactor_code",
        group="Python",
        label="Refactor safely",
        description="Insert an editable refactoring prompt for selected code.",
        prompt_template=(
            "Refactor this Python code for correctness, maintainability, and "
            "small safe changes. Preserve behavior unless a bug is clear:\n\n"
            "```python\n{code}\n```"
        ),
        fields=(ComposerActionField("code", "Code:"),),
    ),
    ComposerAction(
        action_id="python.create_tests",
        group="Python",
        label="Add tests",
        description="Insert an editable prompt to generate tests for selected code.",
        prompt_template=(
            "Create focused pytest tests for this Python code. Cover normal, edge, "
            "and failure cases without changing the public behavior:\n\n"
            "```python\n{code}\n```"
        ),
        fields=(ComposerActionField("code", "Code:"),),
    ),
    ComposerAction(
        action_id="python.optimize_code",
        group="Python",
        label="Optimize",
        description="Insert an editable prompt to optimize selected code carefully.",
        prompt_template=(
            "Optimize this Python code only where it is safe. Explain tradeoffs and "
            "preserve behavior:\n\n```python\n{code}\n```"
        ),
        fields=(ComposerActionField("code", "Code:"),),
    ),
    ComposerAction(
        action_id="python.convert_to_patch",
        group="Python",
        label="Convert to patch",
        description="Ask for a minimal patch from selected code, logs, or notes.",
        prompt_template=(
            "Convert this into a minimal safe patch. Include changed files, the rationale, "
            "and tests to run:\n\n```text\n{code}\n```"
        ),
        fields=(ComposerActionField("code", "Code, logs, or notes:"),),
    ),
    ComposerAction(
        action_id="python.commit_message",
        group="Python",
        label="Create commit message",
        description="Create a commit message from selected code, diff, or notes.",
        prompt_template=(
            "Create a concise commit message from this diff or implementation note. "
            "Use a short subject and a useful body:\n\n```text\n{code}\n```"
        ),
        fields=(ComposerActionField("code", "Diff or notes:"),),
    ),
    ComposerAction(
        action_id="python.explain_traceback",
        group="Python",
        label="Explain traceback / error",
        description="Insert an editable prompt that analyzes the selected traceback or error.",
        prompt_template=(
            "Analyze this Python traceback/error. Explain the likely root cause, "
            "the smallest safe fix, and how to test it:\n\n```text\n{code}\n```"
        ),
        fields=(ComposerActionField("code", "Traceback or error:"),),
    ),
)


COMPOSER_ACTIONS: tuple[ComposerAction, ...] = (
    COMPOSER_TEXT_ACTIONS
    + COMPOSER_WEB_ACTIONS
    + COMPOSER_DOCUMENT_ACTIONS
    + COMPOSER_IMAGING_ACTIONS
    + COMPOSER_PYTHON_ACTIONS
)


COMPOSER_ACTION_BY_ID: dict[str, ComposerAction] = {
    action.action_id: action for action in COMPOSER_ACTIONS
}

CODE_MENU_GROUPS = ("Python",)
TEXT_ACTION_MENU_GROUPS = ("Text", "Web")
LIBRARY_MENU_GROUPS = ("Documents",)


def composer_actions_by_group(
    groups: Iterable[str] | None = None,
) -> "OrderedDict[str, list[ComposerAction]]":
    """Return composer actions grouped in their display order."""

    allowed_groups = set(groups) if groups is not None else None
    grouped: "OrderedDict[str, list[ComposerAction]]" = OrderedDict()

    for action in COMPOSER_ACTIONS:
        if allowed_groups is not None and action.group not in allowed_groups:
            continue

        grouped.setdefault(action.group, []).append(action)

    return grouped


def build_composer_action_prompt(
    action_id: str, values: Mapping[str, object] | None = None
) -> str:
    """Build the prompt text inserted for *action_id*.

    Raises KeyError for an unknown action and ValueError when a required field
    is missing or blank.
    """

    action = COMPOSER_ACTION_BY_ID[action_id]

    if action.mode != "insert_prompt":
        raise ValueError(f"Composer action does not insert a prompt: {action_id}")

    raw_values = values or {}
    cleaned_values: dict[str, str] = {}

    for field in action.fields:
        value = raw_values.get(field.name, field.default)
        cleaned_value = str(value or "").strip()

        if not cleaned_value:
            raise ValueError(f"Missing value for composer action field: {field.name}")

        cleaned_values[field.name] = cleaned_value

    return action.prompt_template.format(**cleaned_values)
