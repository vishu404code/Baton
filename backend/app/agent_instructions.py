"""Text agents get from the MCP server's `instructions` and from the "Connect an agent" dialog.

Keep agent-configs/AGENT_INSTRUCTIONS.md in sync with INSTRUCTIONS_MD.
"""

MCP_INSTRUCTIONS = (
    "You are connected to Baton, the team's shared record and task board. "
    "1) Always call get_room_context first. It gives you the brief, the current decisions with their revision_id, and your role. "
    "2) Claim a task with claim_task before working on it, and call heartbeat every few minutes while you work. "
    "3) On every submit_result, list in based_on the exact revision_id of every brief, decision, source and draft you relied on, "
    "and list the source IDs you cite in sources. "
    "4) Choose a unique idempotency_key per submission and reuse the SAME key if you retry after an error or crash. "
    "5) If a submit is rejected as stale, call read_record on the record named in the error, update your work, and resubmit "
    "with the new revision_id and a NEW idempotency_key. "
    "Never copy chat history between tools: everything you need is in Baton."
)

INSTRUCTIONS_MD = """# Working through Baton

This project uses **Baton** (MCP server `baton`) as the team's shared memory. Other AI tools and teammates work on the same tasks, so follow these rules:

1. **Start every session with `get_room_context`.** It returns the brief, every current decision (with its `revision_id`), the sources, your role and your active claims.
2. **Claim before you work.** Call `list_tasks`, then `claim_task(task_id)`. Only work on tasks you hold. Call `heartbeat(task_id)` every few minutes, or your claim expires and someone else can take it.
3. **Read, don't guess.** Use `read_record` for the brief, decisions, sources and (for reviews) the draft under review. Never rely on chat history or memory from another tool.
4. **Submit with evidence.** `submit_result(task_id, content, based_on, sources, idempotency_key)`:
   - `based_on`: the exact `revision_id`s of everything you used (brief, decisions, sources, the draft you reviewed).
   - `sources`: the source record IDs you cite (add new ones with `add_source`).
   - `idempotency_key`: unique per submission, such as `<your-agent>-<task>-<n>`. **Reuse the same key when retrying** after an error or crash, so the work is applied exactly once.
5. **If rejected, fix and resubmit.** Errors tell you what to do. For example, `stale: based on Decision 2 v1, now v2` means: `read_record("Decision 2")`, update your work, and resubmit with the new `revision_id` and a new `idempotency_key`.
6. **Reviewers** submit `{ "verdict": "approve" | "request_changes", "comments": "..." }` and can `comment` on records.
7. When you're done or stuck, `release_task` so a teammate can pick it up.
"""
