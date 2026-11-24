# Agent configs

Templates for connecting an AI coding tool to Baton. Replace `<BATON_URL>` with the MCP URL `./start.sh` prints (e.g. `http://localhost:8000/mcp`, or your LAN IP for teammates) and `<BATON_TOKEN>` with the agent's token (shown once when you create the agent in **Members & Agents → Connect an agent**).

Then paste [AGENT_INSTRUCTIONS.md](AGENT_INSTRUCTIONS.md) into the project's `CLAUDE.md` / `AGENTS.md` / `GEMINI.md`.

For the seeded demo, `./start.sh` writes ready-made folders with real tokens to `.baton/agents/` (gitignored).

| Tool | File | How |
|---|---|---|
| Claude Code | [claude-code.mcp.json](claude-code.mcp.json) | Save as `.mcp.json` in the project, or run `claude mcp add --transport http baton <BATON_URL> --header "Authorization: Bearer <BATON_TOKEN>"` |
| Codex CLI | [codex-config.toml](codex-config.toml) | Append to `~/.codex/config.toml`, then `export BATON_TOKEN=<BATON_TOKEN>` in the shell that runs `codex` |
| Gemini CLI | [gemini-settings.json](gemini-settings.json) | Save as `.gemini/settings.json` in the project (or merge into `~/.gemini/settings.json`) |

## Running agents headless (demo)

These are the exact commands used to verify the handoff with the seeded demo (run from the repo root after `./start.sh`). Paths are for the copies bundled in the Claude and ChatGPT desktop apps on macOS; use `claude` / `codex` directly if they're on your PATH.

**Claude Code drafts Task 1:**
```bash
cd .baton/agents/claude && "$HOME/Library/Application Support/Claude/claude-code/<version>/<build>/claude.app/Contents/MacOS/claude" -p "You are Asha's Claude, a planner agent. Use only the baton MCP tools. Call get_room_context, list_tasks, claim Task 1, write the launch plan, and submit it with submit_result (based_on = revision_ids of the brief and each decision, sources, idempotency_key)." --mcp-config .mcp.json --strict-mcp-config --allowedTools "mcp__baton__*"
```

**Codex reviews it (Task 2):**
```bash
cd .baton/agents/codex && source env.sh && /Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex exec --skip-git-repo-check --ephemeral -s read-only -c 'approval_policy="never"' -c 'mcp_servers.baton.url="http://localhost:8000/mcp"' -c 'mcp_servers.baton.bearer_token_env_var="BATON_TOKEN"' -c 'mcp_servers.baton.default_tools_approval_mode="approve"' "You are Ben's Codex, a reviewer agent. Use only the baton MCP tools. Call get_room_context, list_tasks, claim Task 2, review the draft against the brief, decisions and sources, comment on it, and submit your review with submit_result."
```

Codex needs `default_tools_approval_mode = "approve"` on the Baton server, or `codex exec` refuses every MCP call ("requires approval, but approval policy is never").
