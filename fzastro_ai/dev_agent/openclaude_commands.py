from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OpenClaudeSlashCommand:
    """A documented OpenClaude slash command exposed in the embedded UI."""

    category: str
    command: str
    label: str
    description: str
    argument_hint: str = ""
    requires_argument: bool = False


# Keep this catalog aligned with the public OpenClaude command reference.
# Optional placeholders are shown in the menu but the base command is submitted
# so OpenClaude can use its native picker/defaults. Required placeholders prompt
# once before submission.
OPENCLAUDE_SLASH_COMMANDS: tuple[OpenClaudeSlashCommand, ...] = (
    # Sessions & conversations
    OpenClaudeSlashCommand(
        "Sessions & Conversations",
        "/clear",
        "Clear",
        "Clear conversation history and free up context.",
    ),
    OpenClaudeSlashCommand(
        "Sessions & Conversations",
        "/compact",
        "Compact",
        "Clear history but keep a summary in context.",
        "instructions",
    ),
    OpenClaudeSlashCommand(
        "Sessions & Conversations",
        "/resume",
        "Resume",
        "Resume a previous conversation.",
        "conversation id or search term",
    ),
    OpenClaudeSlashCommand(
        "Sessions & Conversations",
        "/rename",
        "Rename",
        "Rename the current conversation.",
        "name",
    ),
    OpenClaudeSlashCommand(
        "Sessions & Conversations",
        "/branch",
        "Branch",
        "Create a branch of the current conversation.",
        "name",
    ),
    OpenClaudeSlashCommand(
        "Sessions & Conversations",
        "/rewind",
        "Rewind",
        "Restore code and/or conversation to a previous point.",
    ),
    OpenClaudeSlashCommand(
        "Sessions & Conversations",
        "/export",
        "Export",
        "Export the current conversation to a file or clipboard.",
        "filename",
    ),
    OpenClaudeSlashCommand(
        "Sessions & Conversations",
        "/copy",
        "Copy",
        "Copy the agent's last response to clipboard.",
        "N",
    ),
    OpenClaudeSlashCommand(
        "Sessions & Conversations",
        "/btw",
        "BTW",
        "Ask a side question without interrupting the main conversation.",
        "question",
        True,
    ),
    OpenClaudeSlashCommand(
        "Sessions & Conversations",
        "/goal",
        "Goal",
        "Set and manage a session completion goal.",
        "condition|status|pause|resume|clear",
    ),
    OpenClaudeSlashCommand(
        "Sessions & Conversations",
        "/tasks",
        "Tasks",
        "List and manage background tasks.",
    ),
    OpenClaudeSlashCommand(
        "Sessions & Conversations",
        "/session",
        "Session",
        "Show remote session URL and QR code.",
    ),
    OpenClaudeSlashCommand(
        "Sessions & Conversations",
        "/desktop",
        "Desktop",
        "Continue the current session in Claude Desktop.",
    ),
    OpenClaudeSlashCommand(
        "Sessions & Conversations",
        "/mobile",
        "Mobile",
        "Show QR code to download the Claude mobile app.",
    ),
    OpenClaudeSlashCommand(
        "Sessions & Conversations", "/exit", "Exit", "Exit the REPL."
    ),
    # Context & memory
    OpenClaudeSlashCommand(
        "Context & Memory", "/context", "Context", "Show current context usage."
    ),
    OpenClaudeSlashCommand(
        "Context & Memory", "/files", "Files", "List all files currently in context."
    ),
    OpenClaudeSlashCommand(
        "Context & Memory",
        "/add-dir",
        "Add Dir",
        "Add a new working directory.",
        "path",
        True,
    ),
    OpenClaudeSlashCommand(
        "Context & Memory", "/init", "Init", "Initialize a project instruction file."
    ),
    OpenClaudeSlashCommand(
        "Context & Memory", "/memory", "Memory", "Edit persistent memory files."
    ),
    OpenClaudeSlashCommand(
        "Context & Memory", "/dream", "Dream", "Run memory consolidation."
    ),
    OpenClaudeSlashCommand(
        "Context & Memory",
        "/knowledge",
        "Knowledge",
        "Manage the native Knowledge Graph.",
        "enable yes|no / clear / status / list",
    ),
    OpenClaudeSlashCommand(
        "Context & Memory",
        "/wiki",
        "Wiki",
        "Initialize and inspect the OpenClaude project wiki.",
        "init|status",
    ),
    OpenClaudeSlashCommand(
        "Context & Memory", "/cost", "Cost", "Show session cost and duration."
    ),
    OpenClaudeSlashCommand(
        "Context & Memory",
        "/request-size",
        "Request Size",
        "Show estimated request context load and top contributors.",
    ),
    OpenClaudeSlashCommand(
        "Context & Memory",
        "/cache-stats",
        "Cache Stats",
        "Show per-turn and session cache hit/miss stats.",
    ),
    # Models & providers
    OpenClaudeSlashCommand(
        "Models & Providers",
        "/model",
        "Model",
        "Set the AI model for the session.",
        "model",
    ),
    OpenClaudeSlashCommand(
        "Models & Providers", "/provider", "Provider", "Manage API provider profiles."
    ),
    OpenClaudeSlashCommand(
        "Models & Providers",
        "/effort",
        "Effort",
        "Set effort level for model usage.",
        "low|medium|high|max|auto",
    ),
    OpenClaudeSlashCommand(
        "Models & Providers", "/login", "Login", "Sign in with your Anthropic account."
    ),
    OpenClaudeSlashCommand(
        "Models & Providers",
        "/logout",
        "Logout",
        "Sign out from your Anthropic account.",
    ),
    OpenClaudeSlashCommand(
        "Models & Providers",
        "/onboard-github",
        "Onboard GitHub",
        "Set up GitHub Copilot OAuth device login.",
    ),
    OpenClaudeSlashCommand(
        "Models & Providers", "/usage", "Usage", "Show plan usage limits."
    ),
    OpenClaudeSlashCommand(
        "Models & Providers",
        "/extra-usage",
        "Extra Usage",
        "Configure extra usage for limit overrun handling.",
    ),
    # Code review & git
    OpenClaudeSlashCommand(
        "Code Review & Git",
        "/diff",
        "Diff",
        "View uncommitted changes and per-turn diffs.",
    ),
    OpenClaudeSlashCommand(
        "Code Review & Git", "/review", "Review", "Review a pull request."
    ),
    OpenClaudeSlashCommand(
        "Code Review & Git",
        "/security-review",
        "Security Review",
        "Complete a security review of pending changes.",
    ),
    OpenClaudeSlashCommand(
        "Code Review & Git",
        "/pr-comments",
        "PR Comments",
        "Get comments from a GitHub pull request.",
    ),
    OpenClaudeSlashCommand(
        "Code Review & Git",
        "/auto-fix",
        "Auto Fix",
        "Configure auto-fix after AI edits.",
    ),
    OpenClaudeSlashCommand(
        "Code Review & Git",
        "/plan",
        "Plan",
        "Enable plan mode or view the current plan.",
        "open|description",
    ),
    OpenClaudeSlashCommand(
        "Code Review & Git",
        "/install-github-app",
        "Install GitHub App",
        "Set up GitHub Actions integration.",
    ),
    OpenClaudeSlashCommand(
        "Code Review & Git",
        "/install-slack-app",
        "Install Slack App",
        "Install the Slack app integration.",
    ),
    # Tools & integrations
    OpenClaudeSlashCommand(
        "Tools & Integrations",
        "/mcp",
        "MCP",
        "Manage MCP servers.",
        "enable|disable [server-name]",
    ),
    OpenClaudeSlashCommand(
        "Tools & Integrations",
        "/lsp",
        "LSP",
        "Inspect and set up LSP code intelligence.",
        "status|recommend|install|uninstall|restart",
    ),
    OpenClaudeSlashCommand(
        "Tools & Integrations",
        "/ide",
        "IDE",
        "Manage IDE integrations and show status.",
        "open",
    ),
    OpenClaudeSlashCommand(
        "Tools & Integrations", "/plugin", "Plugin", "Manage OpenClaude plugins."
    ),
    OpenClaudeSlashCommand(
        "Tools & Integrations",
        "/reload-plugins",
        "Reload Plugins",
        "Activate pending plugin changes.",
    ),
    OpenClaudeSlashCommand(
        "Tools & Integrations", "/skills", "Skills", "List available skills."
    ),
    OpenClaudeSlashCommand(
        "Tools & Integrations", "/agents", "Agents", "Manage agent configurations."
    ),
    OpenClaudeSlashCommand(
        "Tools & Integrations",
        "/hooks",
        "Hooks",
        "View hook configurations for tool events.",
    ),
    OpenClaudeSlashCommand(
        "Tools & Integrations",
        "/permissions",
        "Permissions",
        "Manage allow and deny tool permission rules.",
    ),
    # UI & customization
    OpenClaudeSlashCommand(
        "UI & Customization", "/config", "Config", "Open the config panel."
    ),
    OpenClaudeSlashCommand(
        "UI & Customization", "/theme", "Theme", "Change the theme."
    ),
    OpenClaudeSlashCommand(
        "UI & Customization", "/logo", "Logo", "Change the startup logo color scheme."
    ),
    OpenClaudeSlashCommand(
        "UI & Customization",
        "/color",
        "Color",
        "Set the prompt bar color for this session.",
        "color|default",
    ),
    OpenClaudeSlashCommand(
        "UI & Customization",
        "/keybindings",
        "Keybindings",
        "Open or create keybindings configuration.",
    ),
    OpenClaudeSlashCommand(
        "UI & Customization", "/vim", "Vim", "Toggle Vim and Normal editing modes."
    ),
    OpenClaudeSlashCommand(
        "UI & Customization",
        "/statusline",
        "Status Line",
        "Set up OpenClaude's status line UI.",
    ),
    OpenClaudeSlashCommand(
        "UI & Customization",
        "/terminal-setup",
        "Terminal Setup",
        "Install the Shift+Enter newline binding.",
    ),
    OpenClaudeSlashCommand(
        "UI & Customization",
        "/commit-message",
        "Commit Message",
        "Configure commit attribution text.",
        "status|off|default|set text|co-author name email",
    ),
    OpenClaudeSlashCommand(
        "UI & Customization",
        "/output-style",
        "Output Style",
        "Deprecated; use /config for output style.",
    ),
    OpenClaudeSlashCommand(
        "UI & Customization", "/stickers", "Stickers", "Order OpenClaude stickers."
    ),
    # Help & diagnostics
    OpenClaudeSlashCommand(
        "Help & Diagnostics", "/help", "Help", "Show help and available commands."
    ),
    OpenClaudeSlashCommand(
        "Help & Diagnostics",
        "/status",
        "Status",
        "Show version, model, account, API connectivity, and tool status.",
    ),
    OpenClaudeSlashCommand(
        "Help & Diagnostics",
        "/doctor",
        "Doctor",
        "Diagnose and verify installation/settings.",
    ),
    OpenClaudeSlashCommand(
        "Help & Diagnostics", "/stats", "Stats", "Show usage statistics and activity."
    ),
    OpenClaudeSlashCommand(
        "Help & Diagnostics",
        "/insights",
        "Insights",
        "Generate a report analyzing OpenClaude sessions.",
    ),
    OpenClaudeSlashCommand(
        "Help & Diagnostics", "/release-notes", "Release Notes", "View release notes."
    ),
    OpenClaudeSlashCommand(
        "Help & Diagnostics",
        "/feedback",
        "Feedback",
        "Submit feedback about OpenClaude.",
        "report",
    ),
    # Bundled skills
    OpenClaudeSlashCommand(
        "Bundled Skills",
        "/batch",
        "Batch",
        "Plan and execute a large-scale change across worktree agents.",
    ),
    OpenClaudeSlashCommand(
        "Bundled Skills", "/loop", "Loop", "Run or reschedule a repeated prompt."
    ),
    OpenClaudeSlashCommand(
        "Bundled Skills",
        "/simplify",
        "Simplify",
        "Review changed code for reuse, quality, and efficiency.",
    ),
    OpenClaudeSlashCommand(
        "Bundled Skills", "/debug", "Debug", "Enable debug logging and diagnose issues."
    ),
    OpenClaudeSlashCommand(
        "Bundled Skills",
        "/update-config",
        "Update Config",
        "Configure settings.json permissions, env vars, hooks, and behavior.",
    ),
    OpenClaudeSlashCommand(
        "Bundled Skills",
        "/keybindings-help",
        "Keybindings Help",
        "Customize keyboard shortcuts and keybindings.json.",
    ),
    # FZAstro compatibility affordance retained for older OpenClaude builds.
    OpenClaudeSlashCommand(
        "Compatibility",
        "/buddy",
        "Buddy",
        "Open the legacy Buddy shortcut if this OpenClaude build provides it.",
    ),
)

OPENCLAUDE_SLASH_COMMAND_CATEGORIES: tuple[str, ...] = tuple(
    dict.fromkeys(command.category for command in OPENCLAUDE_SLASH_COMMANDS)
)


def openclaude_slash_command_skeleton(spec: OpenClaudeSlashCommand) -> str:
    """Return the concise menu text for a command without descriptions."""

    hint = str(spec.argument_hint or "").strip()
    if not hint:
        return spec.command
    wrapper = "<{}>" if spec.requires_argument else "[{}]"
    return f"{spec.command} {wrapper.format(hint)}"


def grouped_openclaude_slash_commands() -> (
    dict[str, tuple[OpenClaudeSlashCommand, ...]]
):
    """Return slash commands grouped in stable UI order."""

    groups: dict[str, list[OpenClaudeSlashCommand]] = {
        category: [] for category in OPENCLAUDE_SLASH_COMMAND_CATEGORIES
    }
    for command in OPENCLAUDE_SLASH_COMMANDS:
        groups.setdefault(command.category, []).append(command)
    return {category: tuple(items) for category, items in groups.items()}
