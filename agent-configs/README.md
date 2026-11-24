# Agent configs

For AI tools that connect to Baton themselves over MCP. (AIs Baton runs through an API key need no config: use **AI Models** and **Connect an Agent → Baton runs it for you**.)

The easiest way: **Members & Agents → Connect an Agent**, pick the tool, and copy the snippet Baton shows. It contains the right URL and the agent's token (shown once).

Replace `<BATON_URL>` with `http://127.0.0.1:8765/mcp` and `<BATON_TOKEN>` with the agent's token.

| Tool | File | Where it goes |
|---|---|---|
| Antigravity | [antigravity-mcp-config.json](antigravity-mcp-config.json) | `~/.gemini/config/mcp_config.json` (or `<workspace>/.agents/mcp_config.json`); remote servers must use Streamable HTTP |
| Claude Code | [claude-code.mcp.json](claude-code.mcp.json) | `.mcp.json` in the project, or `claude mcp add --transport http baton <BATON_URL> --header "Authorization: Bearer <BATON_TOKEN>"` |
| Codex | [codex-config.toml](codex-config.toml) | append to `~/.codex/config.toml`, then `export BATON_TOKEN=<BATON_TOKEN>` |
| Gemini CLI | [gemini-settings.json](gemini-settings.json) | `.gemini/settings.json` |

Also paste [AGENT_INSTRUCTIONS.md](AGENT_INSTRUCTIONS.md) into the project's `CLAUDE.md` / `AGENTS.md` / `GEMINI.md`. Every tool gets the same nine MCP tools: `get_room_context`, `list_tasks`, `read_record`, `claim_task`, `heartbeat`, `submit_result`, `release_task`, `add_source`, `comment`.

Codex needs `default_tools_approval_mode = "approve"` on the Baton server, or `codex exec` refuses every MCP call.
