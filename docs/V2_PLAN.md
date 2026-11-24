# Baton v2 upgrade plan

Baseline: commit `530b860`, tag **`v1-working`** (72 tests, autopilot passes all 6 judging tests). Roll back at any time with `git checkout v1-working`.

## 1. Decision needed before coding: where the files split

The brief allows "separate database files or schemas". In WAL mode, SQLite does **not** make a transaction across two attached files atomic. A crash mid-commit can leave one file updated and the other not (SQLite docs, ATTACH + WAL). Several v1 guarantees write to memory and state in one step:

- Editing Decision 2 writes the new memory revision, the stale flags, and the `decision.changed` / `record.stale` events.
- Changing a parent decision marks outputs stale in child rooms.

Putting memory, state and each room in their own files would silently weaken those guarantees. **My recommendation:**

| File | Holds | Why |
|---|---|---|
| `data/global.db` | users, sessions, rooms (name, invite code, settings, `parent_id`), memberships, agents, tokens | Small, rarely written, read on every request |
| `data/trees/<root_room_id>/master.db` | **master memory** (`mem_*` tables) and **master state** (`st_*` tables) for every room in one room tree, each row tagged with its `room_id` | Memory and state for one room tree stay in **one** file, so decision edits, stale flags, cross-room staleness, claims, exactly-once and event numbering all stay **atomic** |
| `data/agents/<agent_id>/private.db` | the agent's private state (drafts in progress) and private memory (scratch notes with expiry) | Private work never touches the master, so it needs no shared transaction |

Memory and state stay separate where it matters: separate tables, separate repositories (`MemoryRepo` and `StateRepo`) and separate APIs. They share a file only so they can share a transaction. A tree is at most 3 deep. Moving a room to another tree after creation isn't supported. Cross-file writes only happen where nothing can be left half-done: creating a room writes `global.db` and then creates or updates the tree file, which can be safely re-run.

If you'd rather have one file per room as the brief's example shows, cross-room staleness becomes eventually consistent: an outbox plus a reconciler, with stale flags appearing within about 1 second, not in the same commit. Tell me if you prefer that. Otherwise I'll go with the table above.

## 2. How each Postgres guarantee is replaced

| v1 guarantee (Postgres) | v2 (SQLite) | Kept test |
|---|---|---|
| Unique partial index on active claims | The same partial unique index (verified: SQLite 3.46 enforces it) plus `BEGIN IMMEDIATE` | 6 agents racing: exactly 1 winner |
| `SELECT … FOR UPDATE` on the submission row during apply | Every write transaction is `BEGIN IMMEDIATE` (locks the whole file for writing), plus the UNIQUE idempotency key, plus the apply runs only while `status='saved'`, all in one transaction | crash demo: 3 attempts, 1 revision; parallel-retry test |
| Locked room counter → gap-free `seq` | `room_state.last_seq` in the **same tree file** as `events`, incremented inside the same `BEGIN IMMEDIATE` transaction | 8 writers: seq 1..81, no gaps |
| `SKIP LOCKED` in the lease sweeper | Not needed: the sweeper is one short `BEGIN IMMEDIATE` transaction | lease expiry test |
| JSONB columns | `sa.JSON` (SQLite TEXT with JSON1). Python sees the same dicts and lists. | all |
| JSONB `@>`, `?|`, `->>` in event queries | A new `event_records(event_id, record_id)` lookup table, plus `json_extract` where needed | events `?record_id=`, recovery timeline, trace story |
| `timestamptz` | A `UTCDateTime` type that stores ISO-8601 UTC and reads back timezone-aware datetimes, so comparisons behave as before | lease expiry, ordering |
| Postgres `UUID` | SQLAlchemy's generic `Uuid` (same Python `uuid.UUID`) | all |
| `ilike` | `func.lower(...) ==` | demo sign-in test |

**Single writer.** Inside the backend, one process-wide write lock is taken when a write transaction begins (`BEGIN IMMEDIATE`) and released on commit or rollback. Read-only work (GET endpoints, WebSocket replay, presence) uses a separate read engine with no lock; WAL lets reads run alongside writes. Scripts in a second process, like `crash_demo.py`, are covered by `BEGIN IMMEDIATE` plus `busy_timeout=5000`. Every connection sets: `journal_mode=WAL`, `busy_timeout=5000`, `foreign_keys=ON`, `synchronous=NORMAL`.

**Stop condition (from your ground rules):** if any of the three kept tests can't pass reliably (run 20× in a loop), I stop and report before going further.

## 3. Files that change

| Area | Files |
|---|---|
| Docs first | `docs/API_CONTRACT.md` (changelog v2.0, every new or changed part marked **(v2)**), `docs/UI_SPEC.md` (room tree sidebar, Memory screen, harness/LLM per agent, `baton-connect` tab, child-room stale items) |
| Infra | `docker-compose.yml` (drop `db`; bind-mount `./data`), `.env.example`, `start.sh` / `stop.sh` / `reset-demo.sh` (wipe `./data` instead of the volume; same behaviour), `backend/Dockerfile`, `pyproject.toml` (drop psycopg) |
| Database layer | `app/db.py` → engines per file, the write lock, pragmas; new `app/repo/` (`global_repo.py`, `memory_repo.py`, `state_repo.py`, `private_repo.py`); `app/models.py` split into `models_global.py`, `models_master.py`, `models_private.py`; Alembic: 3 migration sets (global, master, private) run when each file is opened |
| Services (moved onto repositories) | `ledger.py` (memory vs state records), `claims.py`, `submissions.py`, `verification.py` (inherited records in checks 3 and 6), `staleness.py` (crosses rooms in the tree), `events.py` (`event_records`), `evidence.py`, `presence.py`; new `memory.py`, `private.py`, `rooms_tree.py`, `promotion.py`, `context_packets.py`, `harness.py` |
| API | `api/records.py` (v1 endpoints kept; brief, decisions and sources now come from memory), new `api/memory.py`, `api/tree.py`, `api/harness.py`, promotion approvals in `api/approvals.py`, `api/agents.py` (adds the `baton-connect` command and agent profiles) |
| MCP | `mcp_server.py`: the 9 tools stay; adds `search_memory`, `save_private`, `read_private`, `add_memory`; `get_room_context` adds tree path, inherited decisions and who's working on what. `MCPServer` 2.x API and the disabled transport-security check stay as they are. |
| Connector (new, host side) | `connector/` Python package (`baton-connect` CLI, uv), ACP client, stdio↔HTTP MCP bridge, harness profiles |
| Scripts / tests | `seed_demo.py` (tree + memory items), `crash_demo.py`, `demo_run.py` (parent decision → child stale), `tests/conftest.py` (temporary `data/` per test instead of a Postgres test DB), new tests per milestone |

## 4. ACP facts (checked in the official docs today)

| Harness | How Baton starts it | HTTP MCP in the session |
|---|---|---|
| Gemini CLI | `gemini --acp` (`--experimental-acp` is deprecated); npm `@google/gemini-cli` | Not confirmed |
| OpenCode | `opencode acp` | Yes (`mcpCapabilities.http: true`) |
| Claude Code | adapter `@agentclientprotocol/claude-agent-acp` (binary `claude-agent-acp`, Node ≥ 22; `CLAUDE_CODE_EXECUTABLE` points at your existing `claude`) | Not confirmed |
| Codex | adapter `@agentclientprotocol/codex-acp` (binary `codex-acp`; bundles a compatible Codex, or `CODEX_PATH`) | README says HTTP is supported; the flag isn't shown |

The Python client SDK is `agent-client-protocol` (`import acp`; `spawn_agent_process`, `initialize`, `new_session(cwd, mcp_servers)`, `prompt`, `session_update`). After `initialize`, the connector reads `agentCapabilities.mcpCapabilities.http`. If it's true, Baton is passed as an HTTP MCP server with the `Authorization` header. If not, the connector passes itself as a **stdio MCP bridge** (`baton-connect mcp-bridge`, which forwards to `/mcp`), which every ACP agent must support.

## 5. Choices I'll make unless you object (noted, not asked)

- **No live data migration.** Postgres only holds demo data, so v2 starts by re-seeding. The demo keeps the same labels ("Decision 2 v2"), the same people and the invite code `CAMPUS-7KQ2`. Memory items keep the v1 shape (UUID ids, revision ids, labels), so `based_on` works unchanged.
- **The frontend contract doesn't break.** v1 endpoints keep working: brief, decisions and sources are still returned by `/records` (now backed by memory). v2 adds new endpoints next to them.
- **Promotion (child → parent):** after a child output or `add_memory` item is verified (and approved in the child if required), a **promotion request** goes to the parent. When a parent mentor approves, the content is copied into the parent's master memory as a new item (default category `note`), with provenance pointing at the child revision. Nothing is moved; the child keeps its copy.
- **`add_memory`:** creates a submission-like proposal that runs the relevant checks (claim not required; permission, schema, sources) and becomes a master memory item, waiting for approval when the room has `require_approval` on.
- **Private workspace:** readable only through the agent's own token (MCP) and the owner's session (REST `/api/agents/{id}/private`). A test asserts that other members get 404. Private writes never emit room events.
- **Context packets:** token budget estimated as chars/4. Each agent profile has `harness`, `model`, `context_window`, `context_format` (`markdown` | `json`). The packet is ordered: task → decisions (own + inherited) → brief → cited sources → relevant memory (FTS) → others' current work, and trimmed to the budget.

## 6. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Refactoring every service onto repositories | Regressions | Small steps; all 72 tests + the autopilot after each milestone; `v1-working` tag to roll back |
| SQLite write serialization | Slower under load | Transactions are milliseconds; the demo has 3 agents. The verification check delay sleeps **outside** the transaction. |
| Cross-file writes | Atomicity | Avoided by design (section 1). Room creation can be safely re-run. |
| Gemini CLI | Not installed. Its README says unpaid and Google One users were moved to Antigravity CLI (`agy`). | Prove M5 with **Claude Code + Codex** (both logged in on this Mac). Gemini and OpenCode profiles ship but are tested only if you install them. |
| ACP adapters need npm installs | Downloads | I'll ask before installing `@agentclientprotocol/claude-agent-acp` and `codex-acp` (versions pinned) |
| Claude adapter HTTP MCP unconfirmed | Agent can't see Baton | stdio bridge fallback (section 4); the direct v1 MCP path stays |
| Docs drift for the frontend team | Wrong UI | Contract and UI spec are updated first; every change marked (v2) |

## 7. Milestones and checks

1. ✔ Step 0 done · plan approved (one file per room tree) · `API_CONTRACT.md` v2.0 (§11) + `UI_SPEC.md` (§7) marked (v2)
2. SQLite + repository layer: **72 tests + autopilot pass on SQLite**; the three kept tests are looped 20×
3. Memory/state split, master/private workspaces, the 4 new MCP tools
4. Room tree: inheritance, cross-room stale + preview, promotion with approval; the two v1 fixes (request_changes reopens the draft task; `claimed_by` trace links)
5. `baton-connect` with profiles + context packets; Claude Code and Codex over ACP; the direct MCP path still works
6. New seed, `DEMO.md`, full tests, autopilot run twice

After every milestone: `docker compose exec backend pytest -q` and `docker compose exec backend python scripts/demo_run.py --pause 2`. You asked for `python scripts/demo_run.py` with no container; it needs the backend's code, so it runs inside the container, as in v1. A commit and a tag follow each milestone (`v2-m2`, …).
