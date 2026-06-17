"""User-facing skill registry for FZAstro AI.

Skills are the UX grouping layer.  The existing action mixins and composer
commands remain the execution layer, so the desktop UI can be reorganised
without moving business logic around.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import Iterable, Mapping


@dataclass(frozen=True)
class SkillAction:
    """One executable item exposed inside a user-facing skill menu."""

    action_id: str
    label: str
    description: str
    kind: str = (
        "direct"  # "direct" calls an app method; "composer" runs a composer action.
    )
    section: str = ""
    handler_name: str | None = None
    handler_args: tuple[object, ...] = ()
    handler_kwargs: tuple[tuple[str, object], ...] = ()
    composer_action_id: str | None = None
    favorite: bool = False

    @property
    def kwargs(self) -> dict[str, object]:
        return dict(self.handler_kwargs)


@dataclass(frozen=True)
class Skill:
    """A top-level capability group shown to users as a Skill."""

    skill_id: str
    label: str
    description: str
    icon: str
    actions: tuple[SkillAction, ...]


def _direct(
    action_id: str,
    label: str,
    description: str,
    handler_name: str,
    *handler_args: object,
    section: str = "",
    favorite: bool = False,
    **handler_kwargs: object,
) -> SkillAction:
    return SkillAction(
        action_id=action_id,
        label=label,
        description=description,
        kind="direct",
        section=section,
        handler_name=handler_name,
        handler_args=tuple(handler_args),
        handler_kwargs=tuple(handler_kwargs.items()),
        favorite=favorite,
    )


def _composer(
    composer_action_id: str,
    label: str,
    description: str,
    *,
    section: str = "",
    favorite: bool = False,
) -> SkillAction:
    return SkillAction(
        action_id=f"skill.{composer_action_id}",
        label=label,
        description=description,
        kind="composer",
        section=section,
        composer_action_id=composer_action_id,
        favorite=favorite,
    )


SKILLS: tuple[Skill, ...] = (
    Skill(
        skill_id="research",
        label="Research",
        description="Web, page-reading, screenshot, and daily briefing workflows.",
        icon="⌕",
        actions=(
            _direct(
                "research.daily_news",
                "Daily News",
                "Generate the daily news briefing.",
                "daily_news",
                section="Briefings",
                favorite=True,
            ),
            _composer(
                "web.read_page",
                "Read page",
                "Insert a prompt to extract readable text from a webpage URL.",
                section="Web pages",
            ),
            _composer(
                "web.summarize_page",
                "Summarize page",
                "Insert a prompt to summarize a webpage URL.",
                section="Web pages",
            ),
            _composer(
                "web.screenshot_page",
                "Screenshot page",
                "Insert a prompt to capture a visual webpage screenshot.",
                section="Web pages",
            ),
        ),
    ),
    Skill(
        skill_id="knowledge",
        label="Knowledge",
        description="Document library, local retrieval, PDF/book browsing, and memory.",
        icon="▤",
        actions=(
            _direct(
                "knowledge.open_library",
                "Open Document Library",
                "Open the Document Knowledge Library and import/search documents.",
                "open_document_knowledge_library",
                section="Library",
                favorite=True,
            ),
            _composer(
                "documents.list_documents",
                "List documents",
                "Show the indexed document inventory in chat.",
                section="Library",
            ),
            _composer(
                "documents.search_documents",
                "Search knowledge library",
                "Search all imported documents for a topic or phrase.",
                section="Search",
                favorite=True,
            ),
            _composer(
                "documents.find_in_documents",
                "Find in documents",
                "Find a specific fact, phrase, object, or answer in documents.",
                section="Search",
            ),
            _composer(
                "documents.search_inside",
                "Search inside document",
                "Search inside one specific imported document.",
                section="Document actions",
            ),
            _composer(
                "documents.brief_document",
                "Brief document",
                "Create a local brief for a specific imported document.",
                section="Document actions",
            ),
            _composer(
                "documents.open_as_book",
                "Open as book",
                "Open the PDF/book page-image reader for an imported document.",
                section="Document actions",
            ),
            _composer(
                "documents.ask_document",
                "Ask about document",
                "Ask a question using one specific imported document.",
                section="Document actions",
            ),
            _composer(
                "documents.show_page_image",
                "Show page image",
                "Open the document reader at a specific rendered page.",
                section="Document actions",
            ),
            _direct(
                "knowledge.open_memory",
                "Open Persistent Memory",
                "Review and manage persistent memory entries.",
                "open_persistent_memory_library",
                section="Memory & context",
            ),
            _direct(
                "knowledge.active_context",
                "Show active context",
                "Inspect active chat, model, memory, and document context.",
                "show_active_context_dialog",
                section="Memory & context",
            ),
        ),
    ),
    Skill(
        skill_id="code_lab",
        label="Code Lab",
        description="Python runner, code formatting, debugging, refactoring, tests, and patches.",
        icon="</>",
        actions=(
            _direct(
                "code.wrap_selection",
                "Wrap selection as code",
                "Wrap selected composer text as a Markdown code fence.",
                "mark_input_selection_as_code",
                section="Composer",
            ),
            _direct(
                "code.paste_clipboard",
                "Paste clipboard as code",
                "Paste clipboard text directly as a Markdown code fence.",
                "paste_clipboard_as_code",
                section="Composer",
                favorite=True,
            ),
            _composer(
                "python.run_input",
                "Run input as Python",
                "Execute the current composer input through the Python runner.",
                section="Runner",
                favorite=True,
            ),
            _composer(
                "python.run_selection",
                "Run selected code",
                "Execute only the selected composer text through the Python runner.",
                section="Runner",
            ),
            _composer(
                "python.explain_code",
                "Explain this code",
                "Insert a prompt that asks the model to explain selected code.",
                section="Review",
            ),
            _composer(
                "python.debug_code",
                "Fix this error / debug code",
                "Insert a debugging prompt for selected code or traceback.",
                section="Review",
            ),
            _composer(
                "python.refactor_code",
                "Refactor safely",
                "Insert a safe refactoring prompt for selected code.",
                section="Review",
            ),
            _composer(
                "python.create_tests",
                "Add tests",
                "Insert a prompt to generate focused pytest tests.",
                section="Review",
            ),
            _composer(
                "python.optimize_code",
                "Optimize",
                "Insert a prompt to optimize selected code carefully.",
                section="Review",
            ),
            _composer(
                "python.convert_to_patch",
                "Convert to patch",
                "Ask for a minimal patch from selected code, logs, or notes.",
                section="Delivery",
            ),
            _composer(
                "python.commit_message",
                "Create commit message",
                "Create a commit message from selected code, diff, or notes.",
                section="Delivery",
            ),
            _composer(
                "python.explain_traceback",
                "Explain traceback / error",
                "Analyze a selected traceback or error.",
                section="Delivery",
            ),
        ),
    ),
    Skill(
        skill_id="astro",
        label="Astro",
        description="FZASTRO observing site, imaging, lookup, SUN NOW, distance-ladder, 7Timer seeing, targets, and native solar map tools.",
        icon="☉",
        actions=(
            _direct(
                "astro.site",
                "SITE",
                "Pick the observing site used by SEEING and TARGETS.",
                "open_astro_location_dialog",
                section="Setup",
            ),
            _direct(
                "astro.imaging",
                "IMAGING",
                "Select camera preset, focal length, FOV, and rotation for LOOKUP.",
                "open_astro_imaging_dialog",
                section="Setup",
            ),
            _direct(
                "astro.lookup",
                "LOOKUP",
                "Astro object lookup with distance-ladder details and optional sky image.",
                "open_astro_lookup_dialog",
                section="Tools",
                favorite=True,
            ),
            _direct(
                "astro.sun_now",
                "SUN NOW",
                "Latest NASA/SDO Sun images with Helioviewer metadata and cached fallback.",
                "open_sun_now_dialog",
                section="Tools",
                favorite=True,
            ),
            _direct(
                "astro.seeing",
                "SEEING",
                "Open true astronomy seeing and transparency forecast from 7Timer ASTRO.",
                "open_astro_forecast_dialog",
                section="Tools",
            ),
            _direct(
                "astro.targets",
                "TARGETS",
                "Find best astrophotography targets for a location.",
                "open_astro_targets_dialog",
                section="Tools",
                favorite=True,
            ),
            _direct(
                "astro.solar_map",
                "SOLAR MAP",
                "Open the native interactive 2D solar-system map.",
                "open_solar_system_map",
                section="Tools",
            ),
        ),
    ),
    Skill(
        skill_id="markets",
        label="Markets",
        description="Stock, commodity, gold, and crude-oil quote actions.",
        icon="$",
        actions=(
            _direct(
                "markets.crm",
                "CRM — Salesforce",
                "Retrieve the current Salesforce stock price.",
                "retrieve_stock_price",
                "CRM",
                section="Stocks",
            ),
            _direct(
                "markets.dbx",
                "DBX — Dropbox",
                "Retrieve the current Dropbox stock price.",
                "retrieve_stock_price",
                "DBX",
                section="Stocks",
            ),
            _direct(
                "markets.oil",
                "OIL — Crude futures",
                "Retrieve the current crude oil futures price.",
                "retrieve_stock_price",
                "CL=F",
                section="Commodities",
            ),
            _direct(
                "markets.gold",
                "GOLD — Gold futures",
                "Retrieve the current gold futures price.",
                "retrieve_stock_price",
                "GC=F",
                section="Commodities",
            ),
        ),
    ),
    Skill(
        skill_id="model_lab",
        label="Model Lab",
        description="Model selection, refresh, benchmark, persona, calibration, and runtime status.",
        icon="◌",
        actions=(
            _direct(
                "model.refresh_models",
                "Refresh models",
                "Refresh the model list from the active runtime provider.",
                "refresh_models",
                section="Models",
            ),
            _direct(
                "model.benchmark",
                "LLM Benchmark",
                "Open latency, throughput, and model comparison benchmarks.",
                "open_llm_benchmark_dashboard",
                section="Models",
                favorite=True,
            ),
            _direct(
                "model.runtime_status",
                "Runtime / model status",
                "Show provider URL, selected model, Ollama status, and telemetry.",
                "show_runtime_model_status_dialog",
                section="Models",
            ),
            _direct(
                "model.show_persona",
                "Show assistant persona",
                "Show the active persona/calibration summary.",
                "show_current_persona_dialog",
                section="Persona & calibration",
            ),
            _direct(
                "model.insert_persona_question",
                "Insert assistant persona question",
                "Insert a composer question about the active persona.",
                "insert_current_persona_question",
                section="Persona & calibration",
            ),
            _direct(
                "model.system_prompt_editor",
                "Open System Prompt Editor",
                "Open calibration and system prompt editing tools.",
                "open_system_prompt_editor",
                section="Persona & calibration",
            ),
            _direct(
                "model.open_memory",
                "Open Persistent Memory",
                "Review persistent memory entries used by the assistant.",
                "open_persistent_memory_library",
                section="Persona & calibration",
            ),
        ),
    ),
    Skill(
        skill_id="workspace",
        label="Workspace",
        description="Chat lifecycle, history, context, diagnostics, help, and project links.",
        icon="▣",
        actions=(
            _direct(
                "workspace.new_chat",
                "New chat",
                "Start a new empty chat.",
                "new_chat",
                section="Chat",
            ),
            _direct(
                "workspace.history",
                "History",
                "Open or close the chat history panel.",
                "toggle_history_panel",
                section="Chat",
            ),
            _direct(
                "workspace.active_context",
                "Active context",
                "Inspect current context before adding or sending more information.",
                "show_active_context_dialog",
                section="Context",
            ),
            _direct(
                "workspace.indexed_documents",
                "Indexed documents",
                "Show the currently indexed documents in context form.",
                "show_indexed_documents_context",
                section="Context",
            ),
            _direct(
                "workspace.last_tool_result",
                "Last tool result",
                "Open the most recent local tool result.",
                "show_last_tool_result_dialog",
                section="Context",
            ),
            _direct(
                "workspace.diagnostics",
                "Diagnostics",
                "Open diagnostics and recent error log details.",
                "open_diagnostics_window",
                section="Help",
            ),
            _direct(
                "workspace.help",
                "Help",
                "Open the help cheat sheet.",
                "open_help_cheat_sheet",
                section="Help",
            ),
            _direct(
                "workspace.about",
                "About",
                "Open version and release information.",
                "open_about_window",
                section="Help",
            ),
            _direct(
                "workspace.repository",
                "GitHub repository",
                "Open the FZAstro AI GitHub repository in the external browser.",
                "open_project_repository",
                section="Help",
            ),
        ),
    ),
)


SKILL_BY_ID: dict[str, Skill] = {skill.skill_id: skill for skill in SKILLS}
SKILL_ACTION_BY_ID: dict[str, SkillAction] = {
    action.action_id: action for skill in SKILLS for action in skill.actions
}


def skill_actions_by_section(
    skill_id: str,
) -> "OrderedDict[str, list[SkillAction]]":
    """Return the actions for one skill grouped by display section."""

    skill = SKILL_BY_ID[skill_id]
    grouped: "OrderedDict[str, list[SkillAction]]" = OrderedDict()

    for action in skill.actions:
        grouped.setdefault(action.section, []).append(action)

    return grouped


def iter_favorite_skill_actions(
    skill_ids: Iterable[str] | None = None,
) -> tuple[SkillAction, ...]:
    """Return actions marked as favorites in skill display order."""

    allowed = set(skill_ids) if skill_ids is not None else None
    favorites: list[SkillAction] = []

    for skill in SKILLS:
        if allowed is not None and skill.skill_id not in allowed:
            continue
        favorites.extend(action for action in skill.actions if action.favorite)

    return tuple(favorites)
