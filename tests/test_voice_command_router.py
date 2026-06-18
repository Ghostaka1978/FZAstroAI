from fzastro_ai.voice.command_router import (
    resolve_voice_command,
    voice_command_grammar,
    voice_help_examples,
)


def test_voice_command_routes_seeing():
    result = resolve_voice_command("open seeing")
    assert result.kind == "command"
    assert result.text == "/see"
    assert result.auto_execute is True


def test_voice_command_routes_targets():
    result = resolve_voice_command("show targets")
    assert result.kind == "command"
    assert result.text == "/targets"


def test_voice_command_routes_solar_map():
    result = resolve_voice_command("open solar system map")
    assert result.kind == "command"
    assert result.text == "/solar-map"


def test_voice_command_routes_object_alias():
    result = resolve_voice_command("lookup Andromeda")
    assert result.kind == "command"
    assert result.text == "/astro M31"


def test_voice_command_routes_spoken_catalog_alias():
    result = resolve_voice_command("lookup m thirty one")
    assert result.kind == "command"
    assert result.text == "/astro M31"


def test_voice_command_routes_daily_news_skill():
    result = resolve_voice_command("open daily news")
    assert result.kind == "skill"
    assert result.action_id == "research.daily_news"
    assert result.auto_execute is True


def test_voice_command_routes_document_library_skill():
    result = resolve_voice_command("open document library")
    assert result.kind == "skill"
    assert result.action_id == "knowledge.open_library"


def test_voice_command_routes_registry_generated_skill_phrase():
    result = resolve_voice_command("open llm benchmark")
    assert result.kind == "skill"
    assert result.action_id == "model.benchmark"


def test_voice_command_routes_market_aliases_to_global_pulse():
    result = resolve_voice_command("oil price")
    assert result.kind == "skill"
    assert result.action_id == "markets.global_pulse"
    assert result.auto_execute is True


def test_voice_command_routes_voice_help_method():
    result = resolve_voice_command("what can I say")
    assert result.kind == "method"
    assert result.method == "show_voice_commands_help_dialog"


def test_voice_command_confirms_risky_python_run():
    result = resolve_voice_command("run python")
    assert result.kind == "skill"
    assert result.action_id == "skill.python.run_input"
    assert result.requires_confirmation is True


def test_voice_command_unknown_inserts_for_review():
    result = resolve_voice_command("please explain tonight")
    assert result.kind == "insert"
    assert result.auto_execute is False


def test_voice_command_grammar_contains_key_polish_phrases():
    grammar = voice_command_grammar()
    assert "open seeing" in grammar
    assert "open daily news" in grammar
    assert "what can i say" in grammar
    assert "open document library" in grammar
    assert "[unk]" in grammar


def test_voice_help_examples_are_grouped():
    examples = voice_help_examples()
    assert any(category == "Astro Tools" for category, _ in examples)
    assert any("open daily news" in phrases for _, phrases in examples)
