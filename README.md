# Baton

**A shared memory and handoff layer for AI coding agents.** Baton lets Claude Code, Codex, Gemini CLI and Cursor work on one project like teammates. They pass work between each other without losing context, using outdated decisions, or doing anything twice.

It works like a Discord server for agents. A mentor creates a **room**, teammates join with an **invite code**, and everyone connects their own agent. The mentor writes the brief and decisions and creates tasks. Agents claim tasks, read the shared record and submit work. Every submission passes **7 live verification checks** before it's applied, and everyone in the room watches it happen.

> Built for PS 01 (Generative AI): Multi-Agent Harness for a Shared Team Knowledge Base.

## Quick start

You need Docker Desktop (or OrbStack) running.

```bash
./start.sh
```

This builds and starts Postgres and the backend, waits for `/health`, and seeds the demo room if the database is empty. It then prints:
- the API URL (`http://localhost:8000`, with interactive docs at `/docs`)
- the MCP URL for agents (`http://localhost:8000/mcp`)
- the demo room's invite code (`CAMPUS-7KQ2`)
- ready-to-paste setup for each demo agent

| Command | What it does |
|---|---|
| `./stop.sh` | Stop, keep data |
| `./reset-demo.sh` | Wipe everything and re-seed the demo (asks first; `-y` skips the question) |
| `docker compose exec backend python scripts/crash_demo.py` | Crash an agent after "saved" and show it's applied exactly once |
| `docker compose exec backend python scripts/demo_run.py` | Autopilot: play the whole demo and check all six judging tests |

To let teammates on the same Wi-Fi connect their agents, set `BATON_PUBLIC_URL=http://<your-LAN-IP>:8000` in `.env` and run `./reset-demo.sh -y`.

## How it works

- **Rooms like Discord servers.** Anyone can create a room and becomes its owner (mentor). Others join with the invite code, and the owner can promote mentors. Each member connects agents with their own token and a role: `planner`, `reviewer` or `observer`.
- **One team record.** Briefs, decisions, sources, tasks, drafts and reviews are **append-only**. Every change is a new revision, and old ones are kept. Records have readable labels ("Decision 2", "Draft 1"); an output shares its task's number.
- **Claims with leases.** `claim_task` gives one agent exclusive ownership for 15 minutes (enforced by the database), `heartbeat` extends it, and an expired lease frees the task.
- **Live verification.** Every submit runs 7 checks in order, and each result streams to the room as it runs:

  | # | Check | Fails when |
  |---|---|---|
  | 1 | `claim_valid` | The agent doesn't hold the task's lease |
  | 2 | `permission` | The agent's role can't do this (e.g. a reviewer writing a draft) |
  | 3 | `revisions_current` | It's built on an outdated revision: `stale: based on Decision 2 v1, now v2` |
  | 4 | `no_conflicting_edit` | Someone changed the output since the agent's base revision |
  | 5 | `citations_present` | The draft cites fewer than `min_sources` sources (room setting) |
  | 6 | `sources_exist` | It cites a source that isn't in the room |
  | 7 | `content_schema` | Required fields are missing (e.g. a review without a verdict) |

  Checks 5–7 can be turned off per room.
- **Stale propagation.** Editing a decision (or a brief or source) marks every output built on the old version stale, including indirect dependents such as a review of a stale draft. Independent work is untouched. A preview shows the impact before saving.
- **Human approval.** Corrected stale work always waits for a mentor or reviewer to approve it. Rooms can require approval for all agent work.
- **Exactly once.** Submits are idempotent and two-step: `saved` (verified), then `completed` (applied). A crash between the two is finished once on retry with the same key.
- **Evidence.** Every action is written to an append-only event log with a per-room sequence number. The Timeline, Trace and Recovery views are built from it.

## Connecting an agent

In the UI, open **Members & Agents → Connect an agent**. Pick a tool and a role, copy the token (it's shown only once), and paste the snippet. For the demo, `./start.sh` also writes ready-made folders to `.baton/agents/`. Templates are in [agent-configs/](agent-configs/).

**Claude Code**
```bash
claude mcp add --transport http baton http://localhost:8000/mcp --header "Authorization: Bearer <BATON_TOKEN>"
```

**Codex** (`~/.codex/config.toml`)
```toml
[mcp_servers.baton]
url = "http://localhost:8000/mcp"
bearer_token_env_var = "BATON_TOKEN"
default_tools_approval_mode = "approve"
```
Then run `export BATON_TOKEN=<BATON_TOKEN>` in the shell that runs `codex`.

**Gemini CLI** (`~/.gemini/settings.json`)
```json
{ "mcpServers": { "baton": { "httpUrl": "http://localhost:8000/mcp", "headers": { "Authorization": "Bearer <BATON_TOKEN>" } } } }
```

Also paste [agent-configs/AGENT_INSTRUCTIONS.md](agent-configs/AGENT_INSTRUCTIONS.md) into the project's `CLAUDE.md` / `AGENTS.md` / `GEMINI.md`. Every agent gets the same nine tools: `get_room_context`, `list_tasks`, `read_record`, `claim_task`, `heartbeat`, `submit_result`, `release_task`, `add_source` and `comment`.

## The six judging tests

| # | Test | How Baton passes it |
|---|---|---|
| 1 | Connect two different tools | Claude Code and Codex (and Gemini CLI) use the same MCP tools by URL and token. Verified with the real CLIs. |
| 2 | Keep one team record | Versioned brief, decisions and sources. Agent-role and member-role permissions are enforced on every call. |
| 3 | Demonstrate a handoff | Codex's `claim_task` returns Claude's draft, its `based_on` revisions and sources. No chat is copied. |
| 4 | Handle a changed decision | Preview, stale flags (direct and indirect), rejected stale submits, redo, human approval. Independent work is kept. |
| 5 | Recover after interruption | `crash_demo.py`: saved → crash → resume with the same key → applied exactly once, counted from the database |
| 6 | Show the evidence | Event log (who, when, which revision) and a trace graph from a corrected output to the decision and teammate behind it |

The step-by-step presentation is in [docs/DEMO.md](docs/DEMO.md).

## Repository

| Path | What |
|---|---|
| `backend/` | FastAPI app: REST API, WebSocket, MCP server (`app/mcp_server.py`), services, Alembic migrations, tests |
| `frontend/` | Web UI, built separately (see `docs/UI_SPEC.md`) |
| `docs/API_CONTRACT.md` | The REST + WebSocket contract the frontend builds against |
| `docs/UI_SPEC.md` | Screens and layout |
| `docs/ARCHITECTURE.md` | Design decisions and build plan |
| `docs/DEMO.md` | The 3-minute demo script |
| `scripts/` | `seed_demo.py`, `crash_demo.py`, `demo_run.py` |
| `agent-configs/` | Agent config templates, instructions, and commands for running agents without a chat window |

## Development

The backend source is mounted into the container, so after a code change run `docker compose restart backend`.

Run the tests inside the container. They use a separate `baton_test` database in the same Postgres:

```bash
docker compose exec backend pytest -q
```

Schema changes go through Alembic:

```bash
docker compose exec backend alembic revision --autogenerate -m "..."
```

Then review the generated migration and restart the backend, which runs `alembic upgrade head` on start.
