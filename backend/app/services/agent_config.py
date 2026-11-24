"""Ready-to-paste connection snippets for each agent tool (API contract §5).

Syntax checked against the official docs (Nov 2026):
- Claude Code: `claude mcp add --transport http <name> <url> --header "Authorization: Bearer ..."`
- Codex: [mcp_servers.<name>] with url + bearer_token_env_var in ~/.codex/config.toml
- Gemini CLI: mcpServers.<name>.httpUrl (Streamable HTTP) + headers in settings.json
"""

from __future__ import annotations

import json

from app.agent_instructions import INSTRUCTIONS_MD
from app.config import get_settings
from app.models import Agent

PLACEHOLDER = "<BATON_TOKEN>"
SERVER_NAME = "baton"


def build_config(agent: Agent, token: str | None = None) -> dict:
    url = get_settings().mcp_url
    tok = token or PLACEHOLDER
    auth = f"Bearer {tok}"

    mcp_json = json.dumps(
        {"mcpServers": {SERVER_NAME: {"type": "http", "url": url, "headers": {"Authorization": auth}}}}, indent=2
    )
    gemini_json = json.dumps({"mcpServers": {SERVER_NAME: {"httpUrl": url, "headers": {"Authorization": auth}}}}, indent=2)

    return {
        "agent_id": str(agent.id),
        "mcp_url": url,
        "token_placeholder": PLACEHOLDER,
        "token_included": token is not None,
        "snippets": {
            "claude_code": {
                "title": "Claude Code",
                "description": "Run in your project folder. Add --scope project to share it via .mcp.json.",
                "command": f'claude mcp add --transport http {SERVER_NAME} {url} --header "Authorization: {auth}"',
                "mcp_json": mcp_json,
            },
            "codex": {
                "title": "Codex CLI",
                "description": "Add to ~/.codex/config.toml, then export the token in the shell that runs codex.",
                "config_toml": (
                    f'[mcp_servers.{SERVER_NAME}]\nurl = "{url}"\nbearer_token_env_var = "BATON_TOKEN"\n'
                    "# Let Codex call Baton's tools without a prompt (needed for `codex exec`).\n"
                    'default_tools_approval_mode = "approve"'
                ),
                "env": f"export BATON_TOKEN={tok}",
            },
            "antigravity": {
                "title": "Antigravity",
                "description": "Add to ~/.gemini/config/mcp_config.json (or <workspace>/.agents/mcp_config.json), then reload MCP servers in Antigravity. Remote servers must use Streamable HTTP.",
                "mcp_config_json": json.dumps({"mcpServers": {SERVER_NAME: {"serverUrl": url, "headers": {"Authorization": auth}}}}, indent=2),
            },
            "gemini_cli": {
                "title": "Gemini CLI",
                "description": "Add to ~/.gemini/settings.json (or .gemini/settings.json in the project).",
                "settings_json": gemini_json,
            },
        },
        "instructions_md": INSTRUCTIONS_MD,
    }
