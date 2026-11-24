# Baton Architecture and Build Plan

> **v2 in progress:** see [V2_PLAN.md](V2_PLAN.md) for the SQLite, memory/state, room tree and ACP upgrade. This page describes v1 until milestone 2 lands.

## Components

```
 Claude Code ──┐                        ┌── Browser (frontend/, Vite :5173)
 Codex CLI  ───┼── MCP (Streamable HTTP)│      REST /api/*  +  WS /ws/rooms/{id}
 Gemini CLI ───┘   /mcp, bearer token   │
                         │              │
                ┌────────▼──────────────▼────────┐
                │ FastAPI app (backend/, :8000)   │
                │  api/*      REST routers        │
                │  mcp_server MCP tools           │
                │  ws         room event stream   │
                │  services/  ledger · staleness ·│
                │   claims · submissions ·        │
                │   verification · events ·       │
                │   presence                      │
                └────────────────┬────────────────┘
                                 │ SQLAlchemy 2
                        ┌────────▼────────┐
                        │ PostgreSQL 16   │
                        └─────────────────┘
```

The REST API, the MCP tools and the WebSocket are thin layers over the same `services/`, so a change made by an agent through MCP and one made by a mentor in the UI follow identical rules and produce identical events.

## Key design decisions

1. **One process, three surfaces.** FastAPI serves REST, the WebSocket, and the MCP server (official `mcp` SDK, Streamable HTTP, mounted at `/mcp`). Agents on teammates' laptops connect by URL and token; `BATON_PUBLIC_URL` controls the URL printed in configs.
2. **Append-only ledger.** `records` holds identity and a pointer to the current revision; `revisions` is insert-only. Edits create revision N+1. `based_on` is stored on the revision and mirrored into `dependencies` (from_revision → to_revision) for graph queries.
3. **Human-readable labels.** Records get a per-room, per-type `number`, giving labels like `Decision 2`. Error messages and agents use labels ("stale: based on Decision 2 v1, now v2"). `read_record` accepts a UUID or a label.
4. **Stale propagation** is a recursive walk over `dependencies`. Starting from all older revisions of the changed record, it finds the **current** revisions of output records (`draft`, `review`) that reach them, transitively, and marks those records (and their tasks) `stale`. It emits one `record.stale` event per record. The same function runs in dry-run mode for `/revisions/preview`. Outputs not reached are listed as `unaffected`.
5. **Claims.** A unique partial index (`claims(task_id) WHERE status = 'active'`) makes double-claims impossible at the database level. A lease expiry is checked on every claim-related call, plus a background sweeper every `BATON_LEASE_SWEEP_SECONDS` that marks leases `expired` and emits `claim.expired`.
6. **Verification pipeline.** Seven ordered checks, each a small function returning `(passed, detail)`. Results are written to `verification_results` and each one is published as a `verification.check` event **as it runs**, so the room sees them tick. It stops at the first failure. Checks 5–7 can be disabled per room (recorded as skipped).
7. **Exactly-once submits.** `submissions.idempotency_key` is UNIQUE. A submit happens in two committed steps:
   - **Step A (save):** insert the submission, run verification, set status `saved` (or `rejected`).
   - **Step B (apply):** create the output revision, update the task, set `completed` and `result_revision_id`. Step B runs in one transaction, guarded by `SELECT ... FOR UPDATE` on the submission row, and applies only if `status = 'saved'`.
   - A retry with the same key loads the existing row: `completed` returns it (`submission.duplicate`), `saved` runs Step B (`submission.resumed`), and `rejected` returns the rejection.
   - A saved submission is not re-verified on resume (it was verified when saved). If a decision changed in between, the applied revision is immediately marked stale by the same propagation rules.
   - `crash_demo.py` injects a crash between A and B.
8. **Approvals.** If the room has `require_approval`, or the task was `stale` when claimed (a redo of stale work), the new output revision starts `in_review` with a pending approval. Owners/mentors, or members who own a reviewer agent, decide from the UI.
9. **Events** are the single source of evidence: `events(room_id, seq)` is UNIQUE, and `seq` is allocated by incrementing `rooms.last_seq` under a row lock in the same transaction as the change, so sequences are gap-free and ordered. After commit, events are broadcast to the room's WebSocket subscribers via an in-process pub/sub (one backend container, so no Redis is needed). The WebSocket replays from the database for `since_seq`, so a broadcast missed during a reconnect is never lost.
10. **Presence.** Users are online while a WebSocket is open. Agents are online if `last_seen_at` (updated on every MCP call, throttled) is within `BATON_AGENT_ONLINE_SECONDS`. Changes emit `presence.changed`, which is not stored in `events` (it's too chatty). It only goes over the WebSocket, and is sent in `hello`.
11. **Auth.** Session tokens (`bs_`) and agent tokens (`bat_`) are random 32-byte secrets. Only SHA-256 hashes are stored. Uvicorn access logs are configured to hide the WebSocket `?token=` query string.

## Build plan (milestones from the brief)

| # | Deliverable | Status |
|---|---|---|
| 1 | Skeleton, docker-compose, `start.sh`/`stop.sh`/`reset-demo.sh`, `/health`, `API_CONTRACT.md`, `UI_SPEC.md` | done |
| 2 | Models + Alembic migration; sessions, rooms, invite codes, members, agents, tokens, config snippets | done |
| 3 | Ledger, revisions, claims with leases, records API, MCP server (read/claim/submit); one full task from Claude Code | done (real Claude Code completed Task 1) |
| 4 | Second agent (Codex/Gemini); handoff; WebSocket live events; presence | done (real Codex reviewed Claude Code's draft) |
| 5 | Verification pipeline with live checks; stale propagation + preview; approvals | done |
| 6 | Exactly-once submits, `crash_demo.py`, recovery endpoint, trace endpoint | done |
| 7 | `seed_demo.py`, `DEMO.md`, README, agent-configs, full test pass, two end-to-end demo runs | done (2 clean autopilot runs, all checks pass) |

Tests (pytest) run against a real Postgres (the compose `db` service or a throwaway one) because the rules depend on Postgres features (partial unique indexes, row locks, JSONB).
