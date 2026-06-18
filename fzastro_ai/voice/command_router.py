"""Deterministic offline voice-command routing for FZAstro AI.

The router intentionally stays lightweight and dependency-free. Audio
transcription is handled elsewhere; this module only receives text and maps safe
phrases to the same local actions, Skill actions, and slash commands that the
GUI already supports.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from ..skill_registry import SKILLS


@dataclass(frozen=True)
class VoiceCommandResult:
    """Resolved voice-command intent.

    kind:
        - ``command`` inserts/executes a slash command, for example ``/see``.
        - ``skill`` executes an app Skill action from ``skill_registry``.
        - ``method`` calls a safe UI method on the main window.
        - ``insert`` inserts text into the composer for review.
        - ``empty`` means no usable speech was recognized.
    """

    kind: str
    text: str = ""
    method: str = ""
    action_id: str = ""
    transcript: str = ""
    confidence: float = 0.0
    auto_execute: bool = False
    requires_confirmation: bool = False
    note: str = ""


# Keep slash-command aliases conservative: only safe UI-opening actions should
# auto-execute here. The broader app Skill surface is generated below.
_COMMAND_ALIASES = {
    "seeing": "/see",
    "see": "/see",
    "open seeing": "/see",
    "show seeing": "/see",
    "start seeing": "/see",
    "night planner": "/see",
    "open night planner": "/see",
    "show night planner": "/see",
    "astro night planner": "/see",
    "astronomy night planner": "/see",
    "weather": "/see",
    "astro weather": "/see",
    "meteo": "/see",
    "open weather": "/see",
    "show weather": "/see",
    "targets": "/targets",
    "target": "/targets",
    "open targets": "/targets",
    "show targets": "/targets",
    "best targets": "/targets",
    "tonight targets": "/targets",
    "astrophotography targets": "/targets",
    "open target planner": "/targets",
    "target planner": "/targets",
    "solar map": "/solar-map",
    "open solar map": "/solar-map",
    "show solar map": "/solar-map",
    "solar system map": "/solar-map",
    "open solar system map": "/solar-map",
    "show solar system map": "/solar-map",
}

_METHOD_ALIASES = {
    "sun now": "open_sun_now_dialog",
    "open sun now": "open_sun_now_dialog",
    "show sun now": "open_sun_now_dialog",
    "site": "open_astro_location_dialog",
    "open site": "open_astro_location_dialog",
    "site settings": "open_astro_location_dialog",
    "location": "open_astro_location_dialog",
    "location settings": "open_astro_location_dialog",
    "imaging": "open_astro_imaging_dialog",
    "open imaging": "open_astro_imaging_dialog",
    "imaging settings": "open_astro_imaging_dialog",
    "lookup": "open_astro_lookup_dialog",
    "open lookup": "open_astro_lookup_dialog",
    "astro lookup": "open_astro_lookup_dialog",
    "help": "open_help_cheat_sheet",
    "open help": "open_help_cheat_sheet",
    "show help": "open_help_cheat_sheet",
    "benchmark": "open_llm_benchmark_dashboard",
    "model benchmark": "open_llm_benchmark_dashboard",
    "open benchmark": "open_llm_benchmark_dashboard",
    "clear composer": "clear_composer",
    "clear input": "clear_composer",
    "stop generation": "stop_generation",
    "cancel generation": "stop_generation",
    "cancel response": "stop_generation",
    "stop response": "stop_generation",
    "what can i say": "show_voice_commands_help_dialog",
    "show voice commands": "show_voice_commands_help_dialog",
    "voice commands": "show_voice_commands_help_dialog",
    "voice help": "show_voice_commands_help_dialog",
    "open voice help": "show_voice_commands_help_dialog",
    "commands": "show_voice_commands_help_dialog",
    "send message": "voice_send_message",
    "send": "voice_send_message",
}

_CONFIRMATION_METHODS = {
    "voice_send_message",
}

_OBJECT_ALIASES = {
    "andromeda": "M31",
    "andromeda galaxy": "M31",
    "orion": "M42",
    "orion nebula": "M42",
    "great orion nebula": "M42",
    "pleiades": "M45",
    "seven sisters": "M45",
    "triangulum": "M33",
    "triangulum galaxy": "M33",
    "pinwheel": "M101",
    "pinwheel galaxy": "M101",
    "whirlpool": "M51",
    "whirlpool galaxy": "M51",
    "dumbbell": "M27",
    "dumbbell nebula": "M27",
    "ring": "M57",
    "ring nebula": "M57",
    "eagle": "M16",
    "eagle nebula": "M16",
    "lagoon": "M8",
    "lagoon nebula": "M8",
    "trifid": "M20",
    "trifid nebula": "M20",
    "north america": "NGC 7000",
    "north america nebula": "NGC 7000",
    "north american nebula": "NGC 7000",
    "veil": "NGC 6960",
    "veil nebula": "NGC 6960",
    "western veil": "NGC 6960",
    "eastern veil": "NGC 6992",
    "california": "NGC 1499",
    "california nebula": "NGC 1499",
    "rosette": "NGC 2237",
    "rosette nebula": "NGC 2237",
    "heart": "IC 1805",
    "heart nebula": "IC 1805",
    "soul": "IC 1848",
    "soul nebula": "IC 1848",
    "horsehead": "Barnard 33",
    "horsehead nebula": "Barnard 33",
    "flame": "NGC 2024",
    "flame nebula": "NGC 2024",
    "helix": "NGC 7293",
    "helix nebula": "NGC 7293",
}

_SPOKEN_NUMBER_ALIASES = {
    "m one": "M1",
    "m thirteen": "M13",
    "m twenty seven": "M27",
    "m thirty one": "M31",
    "m thirty three": "M33",
    "m forty two": "M42",
    "m forty five": "M45",
    "m fifty one": "M51",
    "m fifty seven": "M57",
    "m eighty one": "M81",
    "m eighty two": "M82",
    "m one oh one": "M101",
    "messier one": "M1",
    "messier thirteen": "M13",
    "messier twenty seven": "M27",
    "messier thirty one": "M31",
    "messier thirty three": "M33",
    "messier forty two": "M42",
    "messier forty five": "M45",
    "messier fifty one": "M51",
    "messier fifty seven": "M57",
    "messier eighty one": "M81",
    "messier eighty two": "M82",
    "messier one oh one": "M101",
    "ngc seven thousand": "NGC 7000",
    "ngc six nine six zero": "NGC 6960",
    "ngc sixty nine sixty": "NGC 6960",
    "ngc six nine nine two": "NGC 6992",
    "ngc sixty nine ninety two": "NGC 6992",
    "ngc fourteen ninety nine": "NGC 1499",
    "ngc twenty twenty four": "NGC 2024",
    "ngc twenty two thirty seven": "NGC 2237",
    "ngc seventy two ninety three": "NGC 7293",
    "ic eighteen oh five": "IC 1805",
    "ic one eight zero five": "IC 1805",
    "ic eighteen forty eight": "IC 1848",
    "ic one eight four eight": "IC 1848",
}

_LOOKUP_PREFIXES = (
    "lookup",
    "look up",
    "astro",
    "find object",
    "search object",
    "show object",
    "open object",
    "object",
)

_DICTATION_PREFIXES = (
    "ask ",
    "type ",
    "write ",
    "dictate ",
    "message ",
    "prompt ",
)

_SKILL_ACTION_CONFIRMATION_IDS = {
    "skill.python.run_input",
    "skill.python.run_selection",
    "workspace.new_chat",
}

# Manual aliases make the phrases users naturally say less dependent on exact UI
# labels. Registry-generated phrases are added after these.
_MANUAL_SKILL_ALIASES = {
    "daily news": "research.daily_news",
    "open daily news": "research.daily_news",
    "show daily news": "research.daily_news",
    "today news": "research.daily_news",
    "todays news": "research.daily_news",
    "today's news": "research.daily_news",
    "refresh daily news": "research.daily_news",
    "update daily news": "research.daily_news",
    "open documents": "knowledge.open_library",
    "open document library": "knowledge.open_library",
    "document library": "knowledge.open_library",
    "documents": "knowledge.open_library",
    "knowledge library": "knowledge.open_library",
    "open knowledge": "knowledge.open_library",
    "import documents": "knowledge.open_library",
    "upload documents": "knowledge.open_library",
    "add documents": "knowledge.open_library",
    "search documents": "skill.documents.search_documents",
    "find in documents": "skill.documents.find_in_documents",
    "list documents": "skill.documents.list_documents",
    "indexed documents": "workspace.indexed_documents",
    "show indexed documents": "workspace.indexed_documents",
    "open memory": "knowledge.open_memory",
    "show memory": "knowledge.open_memory",
    "persistent memory": "knowledge.open_memory",
    "active context": "knowledge.active_context",
    "show active context": "knowledge.active_context",
    "model settings": "model.runtime_status",
    "model status": "model.runtime_status",
    "runtime status": "model.runtime_status",
    "refresh models": "model.refresh_models",
    "assistant persona": "model.show_persona",
    "show persona": "model.show_persona",
    "system prompt editor": "model.system_prompt_editor",
    "open system prompt editor": "model.system_prompt_editor",
    "new chat": "workspace.new_chat",
    "open history": "workspace.history",
    "show history": "workspace.history",
    "history": "workspace.history",
    "diagnostics": "workspace.diagnostics",
    "open diagnostics": "workspace.diagnostics",
    "about": "workspace.about",
    "open about": "workspace.about",
    "repository": "workspace.repository",
    "github": "workspace.repository",
    "open github": "workspace.repository",
    "open code lab": "skill.python.explain_code",
    "run python": "skill.python.run_input",
    "run input as python": "skill.python.run_input",
    "run selected code": "skill.python.run_selection",
    "explain code": "skill.python.explain_code",
    "debug code": "skill.python.debug_code",
    "create tests": "skill.python.create_tests",
    "create commit message": "skill.python.commit_message",
    "crm price": "markets.crm",
    "salesforce price": "markets.crm",
    "dropbox price": "markets.dbx",
    "dbx price": "markets.dbx",
    "oil price": "markets.oil",
    "gold price": "markets.gold",
}


def _normalize_for_matching(text: str) -> str:
    clean = str(text or "").casefold().strip()
    clean = clean.replace("/", " ")
    clean = clean.replace("-", " ")
    clean = clean.replace("_", " ")
    clean = re.sub(r"[^a-z0-9\s]", " ", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    clean = _replace_number_words(clean)
    return clean


def _replace_number_words(clean: str) -> str:
    replacements: Iterable[tuple[str, str]] = (
        ("zero", "0"),
        ("oh", "0"),
        ("one", "1"),
        ("two", "2"),
        ("three", "3"),
        ("four", "4"),
        ("five", "5"),
        ("six", "6"),
        ("seven", "7"),
        ("eight", "8"),
        ("nine", "9"),
    )

    # Only compact simple catalogue phrases such as "m 3 1" and "ngc 7 0 0 0".
    words = clean.split()
    if len(words) >= 2 and words[0] in {"m", "ngc", "ic"}:
        converted = []
        lookup = dict(replacements)
        for word in words[1:]:
            replacement = lookup.get(word, word)
            converted.append(replacement)
        if all(re.fullmatch(r"\d", part) for part in converted):
            return f"{words[0]} {''.join(converted)}"

    return clean


def _build_registry_skill_aliases() -> dict[str, str]:
    aliases: dict[str, str] = dict(_MANUAL_SKILL_ALIASES)

    for skill in SKILLS:
        skill_name = _normalize_for_matching(skill.label)
        for action in skill.actions:
            label = _normalize_for_matching(action.label)
            if not label:
                continue

            phrase_candidates = {
                label,
                f"open {label}",
                f"show {label}",
                f"run {label}",
                f"start {label}",
                f"{skill_name} {label}",
                f"open {skill_name} {label}",
            }
            for phrase in phrase_candidates:
                if phrase:
                    aliases.setdefault(phrase, action.action_id)

    return aliases


_VOICE_HELP_EXAMPLES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Astro Tools",
        (
            "open seeing",
            "open targets",
            "solar map",
            "sun now",
            "site settings",
            "imaging settings",
            "lookup Andromeda",
            "lookup NGC 7000",
        ),
    ),
    (
        "Research & Web",
        (
            "open daily news",
            "refresh daily news",
            "read page",
            "summarize page",
            "screenshot page",
        ),
    ),
    (
        "Knowledge",
        (
            "open document library",
            "search documents",
            "list documents",
            "open memory",
            "show active context",
        ),
    ),
    (
        "Code Lab",
        (
            "explain code",
            "debug code",
            "create tests",
            "run python",
            "create commit message",
        ),
    ),
    (
        "Model Lab",
        (
            "model benchmark",
            "refresh models",
            "model status",
            "show persona",
            "system prompt editor",
        ),
    ),
    (
        "Workspace",
        (
            "what can I say",
            "new chat",
            "open history",
            "open diagnostics",
            "open help",
            "clear composer",
            "stop generation",
        ),
    ),
)


_SKILL_ALIASES = _build_registry_skill_aliases()
_SAFE_EXECUTION_GRAMMAR = tuple(
    sorted(
        set(_COMMAND_ALIASES)
        | set(_METHOD_ALIASES)
        | set(_OBJECT_ALIASES)
        | set(_SKILL_ALIASES)
    )
)


def voice_command_grammar() -> list[str]:
    """Return a compact Vosk grammar list for command mode.

    ``[unk]`` lets Vosk still emit unknown object names and dictation text when
    the phrase is outside the command grammar.
    """

    examples = [
        *list(_SAFE_EXECUTION_GRAMMAR),
        *[f"lookup {name}" for name in _OBJECT_ALIASES],
        *[f"astro {name}" for name in _OBJECT_ALIASES],
        *[f"find {name}" for name in _OBJECT_ALIASES],
        *list(_SPOKEN_NUMBER_ALIASES),
        *[f"lookup {name}" for name in _SPOKEN_NUMBER_ALIASES],
        "ask what is the best target tonight",
        "ask explain tonight imaging conditions",
        "what can i say",
        "show voice commands",
        "[unk]",
    ]

    deduped: list[str] = []
    seen = set()
    for phrase in examples:
        clean = "[unk]" if phrase == "[unk]" else _normalize_for_matching(phrase)
        if clean and clean not in seen:
            deduped.append(clean)
            seen.add(clean)
    return deduped


def voice_help_examples() -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Return curated examples for the in-app 'What can I say?' dialog."""

    return _VOICE_HELP_EXAMPLES


def resolve_voice_command(transcript: str) -> VoiceCommandResult:
    """Resolve a transcript into a safe FZAstro AI action."""

    original = str(transcript or "").strip()
    clean = _normalize_for_matching(original)

    if not clean:
        return VoiceCommandResult(
            kind="empty", transcript=original, note="No speech recognized."
        )

    if clean in _COMMAND_ALIASES:
        return VoiceCommandResult(
            kind="command",
            text=_COMMAND_ALIASES[clean],
            transcript=original,
            confidence=0.96,
            auto_execute=True,
            note="Voice command recognized.",
        )

    if clean in _METHOD_ALIASES:
        method_name = _METHOD_ALIASES[clean]
        return VoiceCommandResult(
            kind="method",
            method=method_name,
            transcript=original,
            confidence=0.96,
            auto_execute=True,
            requires_confirmation=method_name in _CONFIRMATION_METHODS,
            note="Voice UI action recognized.",
        )

    if clean in _SKILL_ALIASES:
        action_id = _SKILL_ALIASES[clean]
        return VoiceCommandResult(
            kind="skill",
            action_id=action_id,
            transcript=original,
            confidence=0.92,
            auto_execute=True,
            requires_confirmation=action_id in _SKILL_ACTION_CONFIRMATION_IDS,
            note="Voice Skill action recognized.",
        )

    astro_object = _extract_lookup_object(clean)
    if astro_object:
        return VoiceCommandResult(
            kind="command",
            text=f"/astro {astro_object}",
            transcript=original,
            confidence=0.86,
            auto_execute=True,
            note="Voice astronomy lookup recognized.",
        )

    for prefix in _DICTATION_PREFIXES:
        if clean.startswith(prefix):
            spoken_text = original[len(prefix) :].strip() or original
            return VoiceCommandResult(
                kind="insert",
                text=spoken_text,
                transcript=original,
                confidence=0.65,
                auto_execute=False,
                note="Voice dictation inserted for review.",
            )

    return VoiceCommandResult(
        kind="insert",
        text=original,
        transcript=original,
        confidence=0.35,
        auto_execute=False,
        note="Uncertain voice input inserted for review.",
    )


def _extract_lookup_object(clean: str) -> str:
    for prefix in _LOOKUP_PREFIXES:
        if clean == prefix:
            return ""
        if clean.startswith(prefix + " "):
            candidate = clean[len(prefix) :].strip()
            return _normalize_astro_object_name(candidate)

    # Allow direct object phrases like "andromeda" or "m thirty one".
    return _normalize_astro_object_name(clean)


def _normalize_astro_object_name(candidate: str) -> str:
    candidate = _normalize_for_matching(candidate)
    if not candidate:
        return ""

    if candidate in _OBJECT_ALIASES:
        return _OBJECT_ALIASES[candidate]

    if candidate in _SPOKEN_NUMBER_ALIASES:
        return _SPOKEN_NUMBER_ALIASES[candidate]

    compact = candidate.replace(" ", "")
    match = re.fullmatch(r"m(?:essier)?(\d{1,3})", compact)
    if match:
        return f"M{match.group(1)}"

    match = re.fullmatch(r"ngc(\d{1,5})", compact)
    if match:
        return f"NGC {match.group(1)}"

    match = re.fullmatch(r"ic(\d{1,5})", compact)
    if match:
        return f"IC {match.group(1)}"

    match = re.fullmatch(r"barnard(\d{1,4})", compact)
    if match:
        return f"Barnard {match.group(1)}"

    # Preserve plausible manually-spoken object names while avoiding accidental
    # app-control words being treated as sky objects.
    if candidate in set(_COMMAND_ALIASES) | set(_METHOD_ALIASES) | set(_SKILL_ALIASES):
        return ""

    if _looks_like_object_name(candidate):
        return _title_case_object(candidate)

    return ""


def _looks_like_object_name(candidate: str) -> bool:
    if not candidate or len(candidate) < 2:
        return False

    if re.search(r"\d", candidate):
        return True

    astronomy_tokens = {
        "galaxy",
        "nebula",
        "cluster",
        "comet",
        "star",
        "jupiter",
        "saturn",
        "mars",
        "venus",
        "moon",
        "sun",
        "orion",
        "cygnus",
        "cassiopeia",
        "cepheus",
        "perseus",
        "taurus",
        "leo",
        "virgo",
        "scorpius",
        "sagittarius",
    }
    return any(token in candidate.split() for token in astronomy_tokens)


def _title_case_object(candidate: str) -> str:
    catalog_match = re.match(r"^(m|ngc|ic)\s+(\d+)$", candidate)
    if catalog_match:
        prefix, number = catalog_match.groups()
        if prefix == "m":
            return f"M{number}"
        return f"{prefix.upper()} {number}"

    return " ".join(part.capitalize() for part in candidate.split())
