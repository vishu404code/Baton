"""Text agents get from the MCP server's `instructions` and from the standing-instruction blocks Baton
writes into each tool's global instruction file (CLAUDE.md, AGENTS.md, GEMINI.md)."""

MCP_INSTRUCTIONS = (
    "You are connected to Baton: one shared memory that several AI tools (Claude Code, Codex/ChatGPT, Antigravity, "
    "Gemini CLI) use on the same project. "
    "1) At the START of EVERY conversation, call get_handoff and continue from it. It tells you the goal, the decisions, "
    "what the other tools already did and what to do next. Never ask the user to re-explain what other tools did. "
    "2) When you finish a meaningful piece of work, make a decision, hit a blocker, or the user says they are switching "
    "to another tool, call save_context(summary, next_steps, files) so the next tool can pick up exactly where you stopped. "
    "3) For structured work use tasks: list_tasks, claim_task, then submit_result with the exact revision_id of everything "
    "you used in based_on, and reuse the same idempotency_key when retrying. If a submit is rejected as stale, read_record "
    "the record named in the error and resubmit with a NEW idempotency_key."
)

INSTRUCTIONS_MD = """# Baton: shared memory across my AI tools

Baton (MCP server `baton`) keeps one shared record of this project for every AI tool I use. Follow these rules in every conversation:

1. **First thing, call `get_handoff`** and continue from it. Do not ask me to re-explain what other tools already did.
2. **When you finish a chunk of work, make a decision, or I say I'm switching tools, call `save_context`** with a short `summary`, the `next_steps`, and the `files` you touched. The next tool reads this.
3. Respect the decisions listed in the handoff; they are binding. If you must change one, say so and save it with `kind="decision"`.
4. For task-style work: `list_tasks` → `claim_task` → `submit_result` (put every revision_id you used in `based_on`; reuse the same `idempotency_key` on retries; if rejected as stale, `read_record` and resubmit with a new key).
"""
