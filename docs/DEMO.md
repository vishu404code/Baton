# Baton: 3-minute demo

**Story:** a mentor's team is launching a campus app. Claude Code writes the launch plan and Codex reviews it, handing off through Baton with no copied chat. Then the launch date changes, a crash happens mid-submit, and Baton keeps everyone honest. Each step proves one or more of the six judging tests.

## Before you present (5 minutes)

1. **Fresh data:**
   ```bash
   ./reset-demo.sh -y
   ```
   This seeds the "Campus App Launch" room with invite code `CAMPUS-7KQ2` and writes ready-made agent folders to `.baton/agents/`.
2. **Frontend:** start it in `frontend/`, then open two browser windows (one private):
   - Window A: sign in as **Asha** (owner). Open the **Board**.
   - Window B: sign in as **Ben** (member, owns the Codex reviewer). Open **Verification**.
3. **Terminals:** open two tabs at the repo root, one for Claude Code and one for Codex. Have the commands below ready to paste.
4. **Pacing:** `.env` has `BATON_CHECK_DELAY_MS=300`, so the audience can see the 7 checks tick.
5. **Backup:** if anything goes wrong on stage, run the autopilot. It plays the same story over the real endpoints and checks every test:
   ```bash
   docker compose exec backend python scripts/demo_run.py --pause 2
   ```

## The script

| Time | Do | Audience sees | Proves |
|---|---|---|---|
| 0:00 | One sentence: "Two different AI tools, one shared team record." Open **Members & Agents**. | Asha's Claude (claude_code, planner) and Ben's Codex (codex, reviewer) in one room, each with its own token and role. | **1**, **2** |
| 0:15 | Open **Decisions**. Point at Decision 2: "We launch on 10 January." | Brief, 3 decisions and 3 sources, all versioned. Only mentors can edit them. | **2** |
| 0:25 | **Claude Code drafts.** Run command A. | Verification screen: 7 checks tick green. Board: Task 1 → "Needs approval", Draft 1 v1 by Asha's Claude. | **3** |
| 0:50 | Asha approves Draft 1 in Task detail. | The task card turns green. | human approval |
| 1:00 | **Codex reviews.** Run command B. | Codex claims Task 2 and gets the draft, its `based_on` revisions and sources from Baton alone. Its comment appears live, then Review 2. | **3**, **1** |
| 1:25 | **Change the decision.** In Decisions, edit Decision 2 to "We launch on 15 January", with the note "exams clash". Pause on the preview. | Preview: **Draft 1 and Review 2 will go stale**, along with the path they're stale through. **Draft 3 (volunteer rota) unaffected.** | **4** |
| 1:40 | Click **Save as v2**. | Board: Task 1 and Task 2 turn amber with "based on Decision 2 v1, now v2". The rota stays green. | **4** |
| 1:50 | **Redo.** Run command C (Claude redoes Task 1). | Verification ticks; Draft 1 v2 appears as "Corrected work needs approval". | **4** |
| 2:05 | Window B (Ben): open Task 1 and compare the `based_on` pills. v1 has an amber Decision 2 v1; v2 has a green Decision 2 v2. Click **Approve**. | Draft 1 v2 is approved. The correction was checked by a teammate, not auto-applied. | **4**, human approval |
| 2:20 | **Crash.** Run command D. | Recovery: "interrupted" → "resumed" → **"Applied exactly once ✓"** (3 attempts, 1 revision). | **5** |
| 2:40 | **Evidence.** Open **Trace** for Task 1. | Graph: Draft 1 v2 → Decision 2 v2 → Asha; Draft 1 v1 → Decision 2 v1 (superseded); approved by Ben. The story panel tells it in order. | **6** |
| 2:55 | Open **Timeline**, filter by Task 1. | Every step has its owner, time, `#seq` and revision. | **6** |

### Commands

Run these from the repo root. The paths use the copies bundled inside the Claude and ChatGPT desktop apps; use plain `claude` / `codex` if they're on your PATH. For the bundled Claude, replace `<version>/<build>` with the folder name under `~/Library/Application Support/Claude/claude-code/` on your Mac.

**A. Claude Code drafts Task 1:**
```bash
cd .baton/agents/claude && "$HOME/Library/Application Support/Claude/claude-code/<version>/<build>/claude.app/Contents/MacOS/claude" -p "You are Asha's Claude, a planner. Use only the baton MCP tools. Call get_room_context, list_tasks, claim Task 1, write a concise launch plan following the brief and every decision, citing at least one source, and submit it with submit_result (based_on = revision_id of the brief and each decision; sources; idempotency_key asha-claude-task1-1)." --mcp-config .mcp.json --strict-mcp-config --allowedTools "mcp__baton__*"; cd -
```

**B. Codex reviews (Task 2):**
```bash
cd .baton/agents/codex && source env.sh && /Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex exec --skip-git-repo-check --ephemeral -s read-only -c 'approval_policy="never"' -c 'mcp_servers.baton.url="http://localhost:8000/mcp"' -c 'mcp_servers.baton.bearer_token_env_var="BATON_TOKEN"' -c 'mcp_servers.baton.default_tools_approval_mode="approve"' "You are Ben's Codex, a reviewer. Use only the baton MCP tools. Call get_room_context, claim Task 2, read the draft under review, check it against the brief, decisions and sources, comment on the draft with your main finding, then submit your review with submit_result (verdict + comments; based_on = brief, each decision and the draft revision; idempotency_key ben-codex-task2-1)."; cd -
```

**C. Claude Code redoes the stale plan:**
```bash
cd .baton/agents/claude && "$HOME/Library/Application Support/Claude/claude-code/<version>/<build>/claude.app/Contents/MacOS/claude" -p "You are Asha's Claude. Use only the baton MCP tools. Task 1 went stale because a decision changed. Call get_room_context, claim Task 1, read_record Decision 2, rewrite the plan on the current decisions, and resubmit with the new revision_ids and idempotency_key asha-claude-task1-2." --mcp-config .mcp.json --strict-mcp-config --allowedTools "mcp__baton__*"; cd -
```

**D. Crash and resume:**
```bash
docker compose exec backend python scripts/crash_demo.py --pause 6
```

> Want the red "stale" rejection on screen? A real agent usually re-reads before resubmitting, so it rarely shows. The autopilot always submits once on the old decision first: run its test-4 step, or the whole `demo_run.py`.

## What each judging test maps to

| # | Test | Where it's shown | Automated proof |
|---|---|---|---|
| 1 | Connect two different tools | Members & Agents; commands A and B (Claude Code + Codex, same 9 MCP tools) | `tests/test_mcp_flow.py` (real MCP over HTTP) |
| 2 | One team record, permissions enforced via both adapters | Decisions; Codex can't claim a planner task; members can't edit decisions | `test_claim_is_exclusive_and_role_checked`, `test_only_mentors_write_records_…` |
| 3 | Handoff without copying chat | Command B: Codex gets draft + `based_on` + sources from `claim_task` | `test_full_task_and_handoff_over_mcp` |
| 4 | Changed decision: flag, review citations, approve, keep independent work | Decisions preview → Board amber → redo → Ben approves; Draft 3 stays green | `tests/test_staleness_approvals.py` |
| 5 | Recover after interruption, applied once | `crash_demo.py` + Recovery | `test_recovery_shows_interrupted_then_resumed_applied_once`, `test_crash_after_save_then_retry_applies_once` |
| 6 | Evidence: owner, time, revision; trace a correction | Timeline + Trace (graph + story) | `test_trace_from_corrected_output_back_to_the_decision_and_teammate` |

The full rehearsal `scripts/demo_run.py` checks all six in one run (about 30 checks).

## If something goes wrong

| Symptom | Fix |
|---|---|
| UI shows "Can't reach Baton" | `./start.sh`; check `curl localhost:8000/health` |
| Agent says "unauthorized" | The tokens changed after a reset. Use the folders in `.baton/agents/`, which are rewritten on every reset. |
| Codex: "MCP tool call requires approval" | Keep the `default_tools_approval_mode="approve"` override in command B |
| "already claimed by …" | A previous run holds the lease (15 min). Run `./reset-demo.sh -y`. |
| Teammate's laptop can't connect | Set `BATON_PUBLIC_URL=http://<your-LAN-IP>:8000` in `.env`, run `./reset-demo.sh -y` and share the new config |
| Anything else on stage | Run the autopilot: `docker compose exec backend python scripts/demo_run.py --pause 2` |
