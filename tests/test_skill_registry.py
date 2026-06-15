from pathlib import Path

from fzastro_ai.skill_registry import (
    SKILL_ACTION_BY_ID,
    SKILL_BY_ID,
    SKILLS,
    iter_favorite_skill_actions,
    skill_actions_by_section,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_skill_registry_groups_actions_into_user_facing_skills():
    assert [skill.skill_id for skill in SKILLS] == [
        "research",
        "knowledge",
        "code_lab",
        "astro",
        "markets",
        "model_lab",
        "workspace",
    ]

    assert [skill.label for skill in SKILLS] == [
        "Research",
        "Knowledge",
        "Code Lab",
        "Astro",
        "Markets",
        "Model Lab",
        "Workspace",
    ]

    assert "astro.lookup" in SKILL_ACTION_BY_ID
    assert "markets.gold" in SKILL_ACTION_BY_ID
    assert "model.benchmark" in SKILL_ACTION_BY_ID
    assert SKILL_ACTION_BY_ID["skill.python.run_input"].kind == "composer"
    assert (
        SKILL_ACTION_BY_ID["skill.python.run_input"].composer_action_id
        == "python.run_input"
    )


def test_skill_actions_keep_existing_handlers_as_execution_layer():
    assert SKILL_ACTION_BY_ID["research.daily_news"].handler_name == "daily_news"
    assert (
        SKILL_ACTION_BY_ID["astro.targets"].handler_name == "open_astro_targets_dialog"
    )
    assert SKILL_ACTION_BY_ID["markets.oil"].handler_name == "retrieve_stock_price"
    assert SKILL_ACTION_BY_ID["markets.oil"].handler_args == ("CL=F",)
    assert (
        SKILL_ACTION_BY_ID["workspace.repository"].handler_name
        == "open_project_repository"
    )


def test_skill_actions_group_by_section_in_display_order():
    grouped = skill_actions_by_section("code_lab")

    assert list(grouped) == ["Composer", "Runner", "Review", "Delivery"]
    assert [action.label for action in grouped["Runner"]] == [
        "Run input as Python",
        "Run selected code",
    ]


def test_favorite_skill_actions_are_available_for_future_quick_access():
    favorites = iter_favorite_skill_actions()
    favorite_ids = {action.action_id for action in favorites}

    assert "research.daily_news" in favorite_ids
    assert "knowledge.open_library" in favorite_ids
    assert "astro.lookup" in favorite_ids
    assert "model.benchmark" in favorite_ids


def test_main_window_uses_skill_registry_for_top_and_composer_menus():
    app_text = (PROJECT_ROOT / "fzastro_ai" / "app.py").read_text(encoding="utf-8-sig")

    assert "from .skill_registry import" in app_text
    assert 'QLabel("SKILLS")' in app_text
    assert "self.skill_buttons" in app_text
    assert "build_skill_menu" in app_text
    assert "build_composer_skills_menu" in app_text
    assert "run_skill_action" in app_text
    assert "main_layout.addWidget(astro_bar)" not in app_text
