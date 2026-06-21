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
    assert "markets.global_pulse" in SKILL_ACTION_BY_ID
    assert "markets.gold" not in SKILL_ACTION_BY_ID
    assert "markets.oil" not in SKILL_ACTION_BY_ID
    assert "markets.crm" not in SKILL_ACTION_BY_ID
    assert "markets.dbx" not in SKILL_ACTION_BY_ID
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
    assert (
        SKILL_ACTION_BY_ID["markets.global_pulse"].handler_name
        == "retrieve_global_market_pulse"
    )
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


def test_markets_menu_starts_with_global_market_pulse():
    grouped = skill_actions_by_section("markets")

    assert list(grouped) == [""]
    assert [action.label for action in grouped[""]] == ["GLOBAL MARKET PULSE"]


def test_favorite_skill_actions_are_available_for_future_quick_access():
    favorites = iter_favorite_skill_actions()
    favorite_ids = {action.action_id for action in favorites}

    assert "research.daily_news" in favorite_ids
    assert "knowledge.open_library" in favorite_ids
    assert "astro.lookup" in favorite_ids
    assert "model.benchmark" in favorite_ids


def test_astro_skill_mentions_distance_ladder_lookup_details():
    astro_skill = SKILL_BY_ID["astro"]
    lookup_action = SKILL_ACTION_BY_ID["astro.lookup"]

    assert "distance-ladder" in astro_skill.description
    assert "distance-ladder" in lookup_action.description


def test_astro_menu_uses_caps_for_app_actions_and_sections():
    grouped = skill_actions_by_section("astro")

    assert list(grouped) == ["SETUP", "TOOLS", "FZASTRO IMAGING"]
    assert [action.label for action in grouped["SETUP"]] == ["SITE", "IMAGING"]
    assert [action.label for action in grouped["TOOLS"]] == [
        "LOOKUP",
        "SUN NOW",
        "SEEING",
        "TARGETS",
        "SOLAR MAP",
    ]
    assert [action.label for action in grouped["FZASTRO IMAGING"]] == [
        "OPEN PLANS FOLDER",
        "FZASTRO IMAGING CONTROL",
    ]


def test_main_window_uses_skill_registry_for_top_and_composer_menus():
    app_text = (PROJECT_ROOT / "fzastro_ai" / "app.py").read_text(encoding="utf-8-sig")

    assert "from .skill_registry import" in app_text
    assert 'QLabel("SKILLS")' in app_text
    assert "self.skill_buttons" in app_text
    assert "build_skill_menu" in app_text
    assert "build_composer_skills_menu" in app_text
    assert "run_skill_action" in app_text
    assert "def _add_menu_section_title" in app_text
    assert "QWidgetAction(menu)" in app_text
    assert 'label.setObjectName("skillMenuSectionTitle")' in app_text
    assert "main_layout.addWidget(astro_bar)" not in app_text


def test_new_chat_and_imported_documents_buttons_live_next_to_tools():
    app_text = (PROJECT_ROOT / "fzastro_ai" / "app.py").read_text(encoding="utf-8-sig")

    composer_snippet = (
        "composer_toolbar_layout.addWidget(composer_tools_label, 0, Qt.AlignVCenter)\n"
        "        composer_toolbar_layout.addWidget(self.new_chat_button, 0, Qt.AlignVCenter)"
    )
    imported_before_clear_snippet = (
        "composer_toolbar_layout.addWidget(\n"
        "            self.imported_documents_button, 0, Qt.AlignVCenter\n"
        "        )\n"
        "        composer_toolbar_layout.addWidget(\n"
        "            self.composer_clear_button, 0, Qt.AlignVCenter"
    )
    assert composer_snippet in app_text
    assert imported_before_clear_snippet in app_text
    assert 'self.news_button = QPushButton("Daily News")' in app_text
    assert 'self.composer_markets_button = QPushButton("$ Markets")' in app_text
    assert "self.news_button.clicked.connect(self.daily_news)" in app_text
    assert (
        "self.composer_markets_button.clicked.connect(self.retrieve_global_market_pulse)"
        in app_text
    )
    assert (
        'self.composer_markets_button.setMenu(self.build_skill_menu("markets"))'
        not in app_text
    )
    assert "composer_toolbar_layout.addWidget(self.news_button" in app_text
    assert "self.composer_markets_button, 0, Qt.AlignVCenter" in app_text
    assert (
        '"New Chat", "newChatButton", "Start a new empty chat", width=84, height=34'
        in app_text
    )
    assert 'QPushButton("Imported Documents (0)")' in app_text
    assert "self.imported_documents_button.clicked.connect(" in app_text
    assert "self.show_knowledge_documents_in_chat" in app_text
    assert 'button.setText(f"Imported Documents ({int(document_count):,})")' in app_text
    assert "runtime_group_layout.addWidget(self.new_chat_button" not in app_text
    assert "skills_group_layout.addWidget(self.new_chat_button" not in app_text


def test_compact_model_status_text_keeps_top_bar_from_clipping():
    model_controls_text = (PROJECT_ROOT / "fzastro_ai" / "model_controls.py").read_text(
        encoding="utf-8-sig"
    )

    assert "def _compact_model_status_message" in model_controls_text
    assert 'return "Ollama off"' in model_controls_text
    assert "self.model_box.addItem(visible_status" in model_controls_text
    assert '"Ollama is off — refresh is read-only."' not in model_controls_text


def test_model_and_profile_controls_share_top_bar_with_web_in_config_sidebar():
    app_text = (PROJECT_ROOT / "fzastro_ai" / "app.py").read_text(encoding="utf-8-sig")

    assert 'self.mode_menu_button = QPushButton("Mode ▾")' not in app_text
    assert "self.mode_menu_button.setMenu(self.build_top_mode_menu())" not in app_text
    assert "mode_group_layout.addWidget(self.mode_menu_button" not in app_text
    assert "self.profile_menu_button.setMenu(self.build_profile_menu())" in app_text
    assert "mode_group_layout.addWidget(self.profile_menu_button" in app_text
    assert "def build_profile_menu(self):" in app_text
    assert "top_bar_layout.addWidget(runtime_group, 0)" in app_text
    assert "top_bar_layout.addWidget(web_group, 0)" not in app_text
    assert "cockpitWebGroup" not in app_text
    assert "web_quick_row.addWidget(self.web_box" in app_text
    assert "web_quick_row.addWidget(self.web_companion_button" in app_text
    assert "Web mode is in Web Companion below." in app_text
    assert "top_bar_layout.addWidget(mode_group, 0)" in app_text
    assert "self.model_box.setFixedWidth(185)" in app_text
    assert "self.model_box.view().setFixedWidth(185)" in app_text
    assert "self.model_box.view().setMinimumWidth(185)" in app_text
    assert "self.model_box.view().setMinimumWidth(240)" not in app_text
    assert "self.model_box.view().setMinimumWidth(340)" not in app_text
    assert "self.model_box.view().setMinimumWidth(520)" not in app_text
    assert "main_layout.addWidget(runtime_bar)" not in app_text


def test_side_panels_overlay_main_without_layout_cramping():
    app_text = (PROJECT_ROOT / "fzastro_ai" / "app.py").read_text(encoding="utf-8-sig")
    main_layout_text = (
        PROJECT_ROOT / "fzastro_ai" / "ui" / "main_layout.py"
    ).read_text(encoding="utf-8-sig")
    history_text = (PROJECT_ROOT / "fzastro_ai" / "ui" / "history_panel.py").read_text(
        encoding="utf-8-sig"
    )

    assert "self.root_shell = root" in app_text
    assert "self.sidebar = QWidget(root)" in app_text
    assert "self.history_panel = QWidget(root)" in app_text
    assert "root_layout.addWidget(self.sidebar)" not in app_text
    assert "root_layout.addWidget(self.history_panel)" not in app_text
    assert "root_layout.addWidget(main, 1)" in app_text
    assert "def _position_overlay_panels(self):" in main_layout_text
    assert "sidebar.raise_()" in main_layout_text
    assert "history_panel.raise_()" in main_layout_text
    assert "def resizeEvent(self, event):" in main_layout_text
    assert (
        'position_panels = getattr(self, "_position_overlay_panels", None)'
        in history_text
    )
    assert 'self.sidebar_close_button = QPushButton("×", self.sidebar)' in app_text
    assert "self.sidebar_close_button.clicked.connect(self.close_sidebar)" in app_text
    layout_text = (PROJECT_ROOT / "fzastro_ai" / "ui" / "main_layout.py").read_text(
        encoding="utf-8-sig"
    )
    assert "close_button.move(close_x, 16)" in layout_text
    assert "close_button.raise_()" in layout_text
    assert "sidebar_mark.mousePressEvent = self._handle_sidebar_mark_click" in app_text
    assert "def close_sidebar(self):" in main_layout_text


def test_context_and_mode_are_in_skills_menu_labels():
    app_text = (PROJECT_ROOT / "fzastro_ai" / "app.py").read_text(encoding="utf-8-sig")

    assert 'self.composer_actions_button = QPushButton("Skills ▾")' in app_text
    assert (
        "self.composer_actions_button.setMenu(self.build_composer_skills_menu())"
        in app_text
    )
    assert '"knowledge": "Context"' in app_text
    assert '"model_lab": "Mode"' in app_text
    assert 'if skill.skill_id in {"astro", "markets"}:' in app_text
    assert "composer_layout.addWidget(self.skills_drawer)" not in app_text
    assert (
        "self.composer_actions_button.clicked.connect(self.toggle_skills_drawer)"
        not in app_text
    )
    assert '"Import PDF/document"' not in app_text
