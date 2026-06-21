from fzastro_ai.dev_agent.openclaude_commands import (
    OPENCLAUDE_SLASH_COMMANDS,
    grouped_openclaude_slash_commands,
    openclaude_slash_command_skeleton,
)


def test_openclaude_slash_catalog_is_grouped_by_documented_categories():
    groups = grouped_openclaude_slash_commands()

    assert "Sessions & Conversations" in groups
    assert "Context & Memory" in groups
    assert "Models & Providers" in groups
    assert "Code Review & Git" in groups
    assert "Tools & Integrations" in groups
    assert "UI & Customization" in groups
    assert "Help & Diagnostics" in groups
    assert "Bundled Skills" in groups
    assert len(OPENCLAUDE_SLASH_COMMANDS) >= 69


def test_openclaude_slash_catalog_contains_key_docs_commands():
    commands = {item.command for item in OPENCLAUDE_SLASH_COMMANDS}

    for command in (
        "/clear",
        "/compact",
        "/context",
        "/knowledge",
        "/model",
        "/provider",
        "/review",
        "/security-review",
        "/mcp",
        "/permissions",
        "/config",
        "/keybindings",
        "/doctor",
        "/skills",
        "/batch",
        "/update-config",
    ):
        assert command in commands


def test_openclaude_command_skeletons_keep_menu_text_command_first():
    by_command = {item.command: item for item in OPENCLAUDE_SLASH_COMMANDS}

    assert openclaude_slash_command_skeleton(by_command["/clear"]) == "/clear"
    assert (
        openclaude_slash_command_skeleton(by_command["/compact"])
        == "/compact [instructions]"
    )
    assert (
        openclaude_slash_command_skeleton(by_command["/add-dir"]) == "/add-dir <path>"
    )


def test_openclaude_required_argument_commands_are_marked_for_prompting():
    required = {
        item.command for item in OPENCLAUDE_SLASH_COMMANDS if item.requires_argument
    }

    assert "/add-dir" in required
    assert "/btw" in required
