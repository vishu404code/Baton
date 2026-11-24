# Architecture

```
┌──────────────────────── Baton desktop app (Electron) ────────────────────────┐
│  window ── http://127.0.0.1:8765 ──►  FastAPI backend (started by the app)   │
│                                         ├─ REST /api      the UI               │
│                                         ├─ WebSocket /ws  live room events     │
│                                         ├─ MCP /mcp       Antigravity, Claude  │
│                                         │                 Code, Codex, ...     │
│                                         ├─ agent runner ─► Claude / ChatGPT /  │
│                                         │                 DeepSeek / Gemini    │
│                                         └─ SQLite (WAL)   one file, one writer │
└────────────────────────────────────────────────────────────────────────────────┘
```

## Pieces

| Piece | Where |
|---|---|
| Rules (ledger, claims, verification, staleness, events) | `backend/app/services/` |
| REST / WebSocket / MCP surfaces (thin layers over the services) | `backend/app/api/`, `ws.py`, `mcp_server.py` |
| AI providers behind one interface | `backend/app/llm/` |
| Agent runner (claim → ask the model → submit) | `backend/app/services/agent_runner.py` |
| Local first-run project | `backend/app/services/bootstrap.py` |
| Desktop shell | `desktop/main.js` |

## Decisions

- **SQLite, one file.** Write transactions are `BEGIN IMMEDIATE`, so SQLite serialises writers. That is what keeps three guarantees race-free (each has a test, looped 15×): one active claim per task (partial unique index), exactly-once submits (unique idempotency key + apply only while `saved`), and gap-free event numbers (counter updated in the same transaction). Read sessions never wait for the writer (WAL). Never open a second write session on the same thread.
- **Three checks.** `claim_valid`, `revisions_current`, `content_schema`. Role permissions are enforced when a task is claimed, so they are not repeated; claims are exclusive, so edit-conflict checks and mandatory citations were dropped.
- **The model call never holds a database transaction.** The runner claims and builds the prompt, closes the session, calls the AI, then submits in a new session.
- **Same pipeline for everyone.** An API-run AI, Claude Code over MCP and a human edit all go through the same services, so they obey the same rules and produce the same events.
- **Append-only record.** Revisions, events and check results are never updated or deleted; "current" is a pointer.
- **Keys.** Stored in `providers.json` (mode 600) in the data folder, never returned by the API, never logged. Environment variables work too.
- **The window only talks to `127.0.0.1`.** The backend binds to localhost.
