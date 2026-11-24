# Baton API Contract (v2)

This is the contract between the Baton backend and the frontend. The frontend team builds against it in parallel, so **any change here must be agreed and noted in the changelog at the bottom**. FastAPI also serves live OpenAPI docs at `http://localhost:8000/docs`; if the two disagree, raise it, don't guess.

- Base URL: `http://localhost:8000` (override with `VITE_BATON_API_URL` on the frontend)
- WebSocket: `ws://localhost:8000/ws/rooms/{room_id}`
- MCP (agents only, not the frontend): `http://localhost:8000/mcp`
- All bodies are JSON. All timestamps are ISO-8601 UTC (`2026-11-24T10:42:07.123Z`).
- All IDs are UUID strings. **The examples below use short readable stand-ins** like `room_campus`, `rec_dec2` or `rev_dec2_v1` so you can follow which object is which; real responses contain UUIDs.

---

## 0. Conventions

### 0.1 Authentication

> **(v2)** Agent tokens (`bat_`) are now also accepted on the harness endpoints used by `baton-connect` (§11.6) and on `GET /api/agents/me/private`. Session tokens can never read another member's agent's private workspace.

There are two kinds of token. Only token hashes are stored server-side, and tokens are never logged.

| Token | Prefix | Who uses it | Where |
|---|---|---|---|
| Session token | `bs_` | The browser (a human user) | `Authorization: Bearer bs_...` on REST; `?token=bs_...` on the WebSocket |
| Agent token | `bat_` | An AI agent (Claude Code, Codex, Gemini CLI...) | `Authorization: Bearer bat_...` on `/mcp` only |

Store the session token in `localStorage`. It doesn't expire during the hackathon. REST endpoints reject agent tokens.

### 0.2 Errors

Every error uses the same shape and a meaningful HTTP status:

```json
{
  "error": {
    "code": "forbidden",
    "message": "Only the owner or a mentor can edit decisions.",
    "details": {}
  }
}
```

| HTTP | `code` | When |
|---|---|---|
| 400 | `bad_request` | Malformed input not caught by validation |
| 401 | `unauthorized` | Missing or invalid token |
| 403 | `forbidden` | Valid user, but their room role doesn't allow this |
| 404 | `not_found` | Unknown ID, or a room you aren't a member of |
| 409 | `conflict` | State conflict (e.g. approval already decided, task already claimed) |
| 422 | `validation_error` | Body failed schema validation. `details.fields` lists `{ "loc": ["body","title"], "msg": "..." }` |
| 500 | `internal` | Bug. The message is safe to show. |

### 0.3 Pagination

List endpoints that can grow (`events`, `submissions`) accept `limit` (default 100, max 500). Events page by `since_seq`; submissions by `before` (a timestamp). Other lists return everything.

### 0.4 Roles and permissions

> **(v2)** New rules: owners and mentors of a room can create **child rooms** under it (max depth 3). A member of a room can **read** (never write) the master memory of every **ancestor** room, but sees nothing of sibling rooms. Promotion requests into a room are decided by that room's owner/mentors. An agent's **private workspace** is readable only by that agent (MCP) and its owner (REST).

**Room member roles** (humans): `owner` (exactly one, the creator), `mentor`, `member`.

**Agent roles**: `planner`, `reviewer`, `observer`.

| Action | owner | mentor | member |
|---|:-:|:-:|:-:|
| View everything in the room, open the WebSocket | ✓ | ✓ | ✓ |
| Create/edit brief, decisions, tasks, sources | ✓ | ✓ | — |
| Preview stale impact of an edit | ✓ | ✓ | — |
| Update room settings | ✓ | ✓ | — |
| Change a member's role (member ⇄ mentor) | ✓ | — | — |
| Create an agent for yourself | ✓ | ✓ | ✓ |
| Revoke an agent | ✓ any | ✓ any | ✓ own |
| Approve/reject a pending revision | ✓ | ✓ | ✓ if they own a `reviewer` agent in this room |
| Comment on a record | ✓ | ✓ | ✓ |

| Agent action (via MCP) | planner | reviewer | observer |
|---|:-:|:-:|:-:|
| Read room context, tasks and records | ✓ | ✓ | ✓ |
| Claim/heartbeat/release/submit a task whose `role` is `planner` | ✓ | — | — |
| Claim/heartbeat/release/submit a task whose `role` is `reviewer` | — | ✓ | — |
| `add_source` | ✓ | ✓ | — |
| `comment` | ✓ | ✓ | — |

### 0.5 Status colours (UI reference)

| Status | Meaning | Colour |
|---|---|---|
| `open` | Task waiting for an agent | neutral/grey |
| `claimed` | An agent holds the lease and is working | indigo |
| `in_review` | Output waiting for human approval | indigo (outlined) |
| `approved` | Accepted, current | green |
| `stale` | Built on a decision revision that has since changed | amber |
| `rejected` | Failed verification or rejected by a human | red |

---

## 1. Core objects

These shapes are reused in every response.

### 1.1 User

```json
{ "id": "usr_asha", "display_name": "Asha", "created_at": "2026-11-24T09:00:00Z" }
```

### 1.2 Actor

Who did something. Appears in revisions, events, claims and comments.

```json
{ "kind": "agent", "id": "agt_claude", "name": "Asha's Claude", "tool": "claude_code", "role": "planner", "color": "#F59E0B", "user_id": "usr_asha", "user_name": "Asha" }
```

```json
{ "kind": "user", "id": "usr_asha", "name": "Asha", "room_role": "owner" }
```

```json
{ "kind": "system", "id": null, "name": "Baton" }
```

`system` is used for automatic actions such as lease expiry and stale propagation.

### 1.3 Room

> **(v2)** Rooms gain `parent_id`, `root_id`, `depth` (1–3), `path` (ancestors → this room, as `[{id, name}]`), `children` (IDs of child rooms you can see) and `access`: `"member"` or `"read"` (an ancestor you can read but don't belong to). See §11.1.

```json
{
  "id": "room_campus",
  "name": "Campus App Launch",
  "invite_code": "CAMPUS-7KQ2",
  "owner_id": "usr_asha",
  "my_role": "owner",
  "settings": {
    "checks": { "citations_present": true, "sources_exist": true, "content_schema": true },
    "min_sources": 1,
    "lease_minutes": 15,
    "require_approval": true
  },
  "counts": { "members": 3, "agents": 2, "open_tasks": 1, "stale": 0, "pending_approvals": 0 },
  "latest_seq": 57,
  "created_at": "2026-11-24T09:00:00Z"
}
```

`settings.checks` only lists the optional checks (5–7). Checks 1–4 (`claim_valid`, `permission`, `revisions_current`, `no_conflicting_edit`) are always on.

### 1.4 Member

```json
{ "user": { "id": "usr_ben", "display_name": "Ben", "created_at": "2026-11-24T09:05:00Z" }, "role": "member", "joined_at": "2026-11-24T09:05:00Z", "online": true, "agent_ids": ["agt_codex"] }
```

### 1.5 Agent

> **(v2)** Agents gain `profile` (`harness`, `model`, `context_window`, `context_format`) and `session` (the live harness session or `null`). `tool` stays as in v1. See §11.2.

```json
{
  "id": "agt_codex",
  "room_id": "room_campus",
  "user_id": "usr_ben",
  "user_name": "Ben",
  "name": "Ben's Codex",
  "tool": "codex",
  "role": "reviewer",
  "color": "#22D3EE",
  "online": true,
  "last_seen_at": "2026-11-24T10:41:55Z",
  "working_on": { "task_id": "rec_task2", "label": "Task 2", "title": "Review launch plan" },
  "revoked": false,
  "created_at": "2026-11-24T09:06:00Z"
}
```

- `tool` is one of `claude_code`, `codex`, `gemini_cli`, `cursor` or `other`.
- `color` is assigned by the server from a fixed palette; use it for the agent's badge everywhere.
- `working_on` is the task the agent holds an active claim on (or `null`).

### 1.6 Record

> **(v2)** `brief`, `decision` and `source` records now live in the room's **master memory** (§11.3). They keep the same IDs, labels ("Decision 2"), revisions and shapes, and `/records` still returns them, with an extra `"store": "memory"` and, when they come from an ancestor room, `"room_id"`, `"room_name"` and `"inherited": true`. Tasks, drafts and reviews are **state** (`"store": "state"`). New task status flow: a review with verdict `request_changes` reopens the reviewed task (status `open`, event `task.reopened`).

A record is a long-lived item (a brief, a decision, a task...). Its content lives in revisions.

```json
{
  "id": "rec_dec2",
  "room_id": "room_campus",
  "type": "decision",
  "number": 2,
  "label": "Decision 2",
  "title": "Launch date",
  "status": "approved",
  "current_revision": 2,
  "current_revision_id": "rev_dec2_v2",
  "parent_task_id": null,
  "content": { "statement": "We launch on 15 January.", "rationale": "Exams end on 12 January." },
  "updated_at": "2026-11-24T10:42:07Z",
  "updated_by": { "kind": "user", "id": "usr_asha", "name": "Asha", "room_role": "owner" },
  "created_at": "2026-11-24T09:01:00Z"
}
```

- `type` is one of `brief`, `decision`, `task`, `source`, `draft` or `review`.
- `number` counts per room per type and is shown as `label` (`"Decision 2"`, `"Task 1"`, `"Source 3"`). **An output shares its task's number**: Task 1's draft is `Draft 1`, Task 2's review is `Review 2`. Agents and error messages use the label.
- `content` is the current revision's content.
- `parent_task_id` is set on `draft` and `review` records (the task that produced them).

**Content by type** (validated by the `content_schema` check):

| type | content fields |
|---|---|
| `brief` | `body` (markdown, required) |
| `decision` | `statement` (required), `rationale` (optional) |
| `source` | `url` and/or `text` (at least one), `summary` (optional) |
| `task` | `description` (required), `role`: `planner` \| `reviewer` (required), `review_of_task_id` (reviewer tasks: the task whose output is under review) |
| `draft` | `body` (markdown, required) |
| `review` | `verdict`: `approve` \| `request_changes` (required), `comments` (required, non-empty) |

**Status by type:**
- `brief`, `decision`, `source`: always `approved` (they are mentor-authored truth).
- `task`: `open` → `claimed` → (`in_review`) → `approved`; or `stale` / `rejected`, which return it to the board for redoing.
- `draft`, `review`: `in_review` → `approved` or `rejected`; any → `stale`.

### 1.7 Revision

```json
{
  "id": "rev_draft1_v1",
  "record_id": "rec_draft1",
  "number": 1,
  "title": "Launch plan",
  "content": { "body": "## Launch plan\n1. Soft launch on 10 January..." },
  "author": { "kind": "agent", "id": "agt_claude", "name": "Asha's Claude", "tool": "claude_code", "role": "planner", "color": "#F59E0B", "user_id": "usr_asha", "user_name": "Asha" },
  "based_on": [
    { "revision_id": "rev_brief1_v1", "record_id": "rec_brief1", "label": "Brief 1", "number": 1, "is_current": true },
    { "revision_id": "rev_dec2_v1", "record_id": "rec_dec2", "label": "Decision 2", "number": 1, "is_current": false }
  ],
  "sources": [
    { "record_id": "rec_src1", "label": "Source 1", "title": "Academic calendar 2026–27", "revision_id": "rev_src1_v1" }
  ],
  "submission_id": "sub_1",
  "created_at": "2026-11-24T10:05:00Z"
}
```

`based_on[].is_current` is `false` when a newer revision of that record exists. That's the reason an output is stale; highlight it in amber.

### 1.8 Claim

```json
{ "id": "clm_1", "task_id": "rec_task1", "agent": { "kind": "agent", "id": "agt_claude", "name": "Asha's Claude", "tool": "claude_code", "role": "planner", "color": "#F59E0B", "user_id": "usr_asha", "user_name": "Asha" }, "status": "active", "lease_expires_at": "2026-11-24T10:20:00Z", "created_at": "2026-11-24T10:05:00Z" }
```

`status` is one of `active`, `released` or `expired`. Show a countdown to `lease_expires_at` on active claims.

### 1.9 Submission and checks

```json
{
  "id": "sub_1",
  "idempotency_key": "claude-task1-attempt-1",
  "task_id": "rec_task1",
  "task_label": "Task 1",
  "agent": { "kind": "agent", "id": "agt_claude", "name": "Asha's Claude", "tool": "claude_code", "role": "planner", "color": "#F59E0B", "user_id": "usr_asha", "user_name": "Asha" },
  "status": "completed",
  "base_revision_id": null,
  "based_on": ["rev_brief1_v1", "rev_dec1_v1", "rev_dec2_v1"],
  "source_ids": ["rec_src1"],
  "payload": { "title": "Launch plan", "content": { "body": "## Launch plan..." } },
  "checks": [
    { "name": "claim_valid", "order": 1, "passed": true, "detail": "Asha's Claude holds the lease on Task 1 until 10:20:00Z." },
    { "name": "permission", "order": 2, "passed": true, "detail": "planner may submit a draft for a planner task." },
    { "name": "revisions_current", "order": 3, "passed": true, "detail": "All 3 based_on revisions are current." },
    { "name": "no_conflicting_edit", "order": 4, "passed": true, "detail": "No other edits to this task's output since the base revision." },
    { "name": "citations_present", "order": 5, "passed": true, "detail": "1 source cited (minimum 1)." },
    { "name": "sources_exist", "order": 6, "passed": true, "detail": "All cited sources exist in this room." },
    { "name": "content_schema", "order": 7, "passed": true, "detail": "draft has the required field: body." }
  ],
  "rejection_reason": null,
  "result_revision_id": "rev_draft1_v1",
  "result_record_id": "rec_draft1",
  "attempts": 1,
  "resumed": false,
  "approval": { "id": "apr_1", "status": "pending" },
  "created_at": "2026-11-24T10:05:00Z",
  "saved_at": "2026-11-24T10:05:00Z",
  "completed_at": "2026-11-24T10:05:01Z"
}
```

- `status` is one of:
  - `saved`: stored and verified, not yet applied. You'll see this during the crash demo.
  - `completed`: applied, so the result revision exists.
  - `rejected`: a check failed and nothing was applied.
- A disabled check appears with `"passed": true, "skipped": true, "detail": "Disabled in room settings."`.
- After the first failing check, the remaining checks are not run and are omitted.
- `base_revision_id` is the revision of the task's existing output this submission edits (`null` for the first draft).
- `attempts` counts calls with the same `idempotency_key`; `resumed` is `true` if a retry finished an interrupted submission.

A **rejected** example:

```json
{
  "id": "sub_4",
  "status": "rejected",
  "checks": [
    { "name": "claim_valid", "order": 1, "passed": true, "detail": "Ben's Codex holds the lease on Task 1." },
    { "name": "permission", "order": 2, "passed": true, "detail": "planner may submit a draft for a planner task." },
    { "name": "revisions_current", "order": 3, "passed": false, "detail": "stale: based on Decision 2 v1, now v2; call read_record and resubmit." }
  ],
  "rejection_reason": "stale: based on Decision 2 v1, now v2; call read_record and resubmit.",
  "result_revision_id": null
}
```

(Other fields as above.)

### 1.10 Approval

> **(v2)** Approvals gain `kind`: `"output"` (v1 behaviour) or `"memory"` (an agent's `add_memory` proposal waiting for a human). Promotions from child rooms use their own object and endpoints (§11.5).

```json
{
  "id": "apr_2",
  "revision_id": "rev_draft1_v2",
  "record_id": "rec_draft1",
  "record_label": "Draft 1",
  "task_id": "rec_task1",
  "task_label": "Task 1",
  "reason": "redo_of_stale",
  "status": "pending",
  "requested_at": "2026-11-24T10:47:00Z",
  "decided_by": null,
  "decided_at": null,
  "comment": null
}
```

- `reason` is either `require_approval` (room setting) or `redo_of_stale` (always needs approval).
- `status` is `pending`, `approved` or `rejected`.

### 1.11 Comment

```json
{ "id": "cmt_1", "record_id": "rec_draft1", "revision_number": 1, "author": { "kind": "agent", "id": "agt_codex", "name": "Ben's Codex", "tool": "codex", "role": "reviewer", "color": "#22D3EE", "user_id": "usr_ben", "user_name": "Ben" }, "text": "Section 3 cites Source 2 but the date is from Decision 2 v1.", "created_at": "2026-11-24T10:12:00Z" }
```

### 1.12 Event

Every action becomes an event with a per-room, gap-free, increasing `seq`. The Timeline, Trace and Recovery screens are built from events.

```json
{
  "id": "evt_57",
  "room_id": "room_campus",
  "seq": 57,
  "type": "decision.changed",
  "actor": { "kind": "user", "id": "usr_asha", "name": "Asha", "room_role": "owner" },
  "summary": "Asha changed Decision 2 \"Launch date\" to v2",
  "payload": { "...": "see section 9" },
  "created_at": "2026-11-24T10:42:07Z"
}
```

`summary` is a ready-to-display sentence, so the feed can show any event without type-specific code. `payload` carries structured data for richer rendering (section 9).

---

## 2. Health

### `GET /health`

No auth.

`200 OK`
```json
{ "status": "ok", "db": "ok", "version": "0.1.0" }
```

`503` with `{ "status": "degraded", "db": "unreachable", "version": "0.1.0" }` when Postgres is down.

---

## 3. Session (auth)

### `POST /api/session`

Creates a user and returns a session token. There are no passwords during the hackathon.

Request
```json
{ "display_name": "Asha" }
```

`201 Created`
```json
{
  "user": { "id": "usr_asha", "display_name": "Asha", "created_at": "2026-11-24T09:00:00Z" },
  "token": "bs_3n8Jq...redacted"
}
```

`display_name` must be 1–40 characters.

### `GET /api/me`

`200 OK`
```json
{ "user": { "id": "usr_asha", "display_name": "Asha", "created_at": "2026-11-24T09:00:00Z" } }
```

### `POST /api/session/demo`

Signs in as one of the seeded demo users, so the demo doesn't need typing. Available only when the demo room was seeded.

Request
```json
{ "display_name": "Asha" }
```

`200 OK`: same shape as `POST /api/session`. `404` if there is no seeded user with that name.

---

## 4. Rooms

### `POST /api/rooms`

> **(v2)** Optional `parent_id` creates a **child room** (caller must be owner/mentor of the parent; depth ≤ 3; `409` beyond). Emits `room.created` in the new room **and** in the parent.

Creates a room. The caller becomes `owner`.

Request
```json
{ "name": "Campus App Launch" }
```

`201 Created` → **Room** (1.3). An `event` of type `member.joined` (the owner) is the room's first event.

### `GET /api/rooms`

> **(v2)** Unchanged list of rooms you belong to; each item adds `parent_id` and `depth`. Use `GET /api/rooms/tree` (§11.1) for the nested sidebar.

The rooms I belong to, for the left rail.

`200 OK`
```json
{
  "rooms": [
    { "id": "room_campus", "name": "Campus App Launch", "my_role": "owner", "unread_hint": false, "counts": { "members": 3, "agents": 2, "open_tasks": 1, "stale": 0, "pending_approvals": 0 }, "latest_seq": 57 }
  ]
}
```

### `GET /api/rooms/{room_id}`

`200 OK` → **Room** (1.3).

### `POST /api/rooms/join`

> **(v2)** Joining a child room also grants **read** access to its ancestors' master memory (not membership, not their tasks).

Request
```json
{ "invite_code": "CAMPUS-7KQ2" }
```

`200 OK` → **Room**. Codes are case-insensitive. Joining a room you already belong to returns it unchanged. Emits `member.joined`. `404` for an unknown code.

### `PATCH /api/rooms/{room_id}/settings`

Owner or mentor. Partial update: send only what changes.

Request
```json
{ "checks": { "citations_present": false }, "min_sources": 2, "lease_minutes": 10, "require_approval": false }
```

`200 OK` → **Room** with updated `settings`. Emits `room.settings_changed`.

Validation: `min_sources` is 0–10; `lease_minutes` is 1–120.

### `GET /api/rooms/{room_id}/members`

`200 OK`
```json
{ "members": [ { "user": { "id": "usr_asha", "display_name": "Asha", "created_at": "2026-11-24T09:00:00Z" }, "role": "owner", "joined_at": "2026-11-24T09:00:00Z", "online": true, "agent_ids": ["agt_claude"] } ] }
```

### `PATCH /api/rooms/{room_id}/members/{user_id}`

Owner only. Promotes or demotes between `member` and `mentor`. The owner's role can't be changed.

Request
```json
{ "role": "mentor" }
```

`200 OK` → **Member**. Emits `member.role_changed`.

---

## 5. Agents

### `GET /api/rooms/{room_id}/agents`

`200 OK`
```json
{ "agents": [ { "id": "agt_claude", "room_id": "room_campus", "user_id": "usr_asha", "user_name": "Asha", "name": "Asha's Claude", "tool": "claude_code", "role": "planner", "color": "#F59E0B", "online": true, "last_seen_at": "2026-11-24T10:41:55Z", "working_on": null, "revoked": false, "created_at": "2026-11-24T09:02:00Z" } ] }
```

Revoked agents are omitted unless you pass `?include_revoked=true`.

### `POST /api/rooms/{room_id}/agents`

> **(v2)** Optional `profile` in the body (§11.2). Defaults are filled from `tool`.

Creates an agent owned by the caller. **The token is returned only in this response.** Show it once, with a copy button and a warning.

Request
```json
{ "name": "Ben's Codex", "tool": "codex", "role": "reviewer" }
```

`201 Created`
```json
{
  "agent": { "id": "agt_codex", "room_id": "room_campus", "user_id": "usr_ben", "user_name": "Ben", "name": "Ben's Codex", "tool": "codex", "role": "reviewer", "color": "#22D3EE", "online": false, "last_seen_at": null, "working_on": null, "revoked": false, "created_at": "2026-11-24T09:06:00Z" },
  "token": "bat_V7c2...redacted",
  "config": { "...": "same as GET .../config below, but with the real token filled in" }
}
```

Emits `agent.created`. Any room member can create agents (with any role) for themselves; the agent belongs to the caller.

### `GET /api/rooms/{room_id}/agents/{agent_id}/config`

> **(v2)** `snippets` gains a `baton_connect` entry (shown first in the dialog), and the response gains `profile`. See §11.6.

Ready-to-paste connection snippets. Because the server only stores the token hash, this endpoint uses the placeholder `<BATON_TOKEN>`. The create response fills in the real token.

`200 OK`
```json
{
  "agent_id": "agt_codex",
  "mcp_url": "http://192.168.1.20:8000/mcp",
  "token_placeholder": "<BATON_TOKEN>",
  "token_included": false,
  "snippets": {
    "claude_code": {
      "title": "Claude Code",
      "description": "Run in your project folder. Use --scope project to share via .mcp.json.",
      "command": "claude mcp add --transport http baton http://192.168.1.20:8000/mcp --header \"Authorization: Bearer <BATON_TOKEN>\"",
      "mcp_json": "{\n  \"mcpServers\": {\n    \"baton\": {\n      \"type\": \"http\",\n      \"url\": \"http://192.168.1.20:8000/mcp\",\n      \"headers\": { \"Authorization\": \"Bearer <BATON_TOKEN>\" }\n    }\n  }\n}"
    },
    "codex": {
      "title": "Codex CLI",
      "description": "Add to ~/.codex/config.toml, then export the token in the shell that runs codex.",
      "config_toml": "[mcp_servers.baton]\nurl = \"http://192.168.1.20:8000/mcp\"\nbearer_token_env_var = \"BATON_TOKEN\"\n# Let Codex call Baton's tools without a prompt (needed for `codex exec`).\ndefault_tools_approval_mode = \"approve\"",
      "env": "export BATON_TOKEN=<BATON_TOKEN>"
    },
    "gemini_cli": {
      "title": "Gemini CLI",
      "description": "Add to ~/.gemini/settings.json (or .gemini/settings.json in the project).",
      "settings_json": "{\n  \"mcpServers\": {\n    \"baton\": {\n      \"httpUrl\": \"http://192.168.1.20:8000/mcp\",\n      \"headers\": { \"Authorization\": \"Bearer <BATON_TOKEN>\" }\n    }\n  }\n}"
    }
  },
  "instructions_md": "# Working through Baton\n1. Always call get_room_context first...\n"
}
```

Highlight the snippet matching the agent's `tool` and keep the others in tabs. `instructions_md` is the text to paste into `CLAUDE.md` / `AGENTS.md` / `GEMINI.md`. `mcp_url` comes from `BATON_PUBLIC_URL`, so set it to your LAN IP for teammates on the same Wi-Fi.

### `DELETE /api/rooms/{room_id}/agents/{agent_id}`

Revokes the agent's token. Its active claims are released.

`204 No Content`. Emits `agent.revoked` (+ `task.released` per claim).

---

## 6. Records

### `GET /api/rooms/{room_id}/records`

> **(v2)** New query parameter `include_ancestors` (default `false` here, for v1 compatibility). With `true`, ancestor rooms' briefs, decisions and sources are included and marked `inherited: true`.

Query parameters (all optional):
- `type`: comma-separated, e.g. `decision,source`
- `status`: comma-separated
- `parent_task_id`

`200 OK`
```json
{ "records": [ { "id": "rec_dec2", "room_id": "room_campus", "type": "decision", "number": 2, "label": "Decision 2", "title": "Launch date", "status": "approved", "current_revision": 2, "current_revision_id": "rev_dec2_v2", "parent_task_id": null, "content": { "statement": "We launch on 15 January.", "rationale": "Exams end on 12 January." }, "updated_at": "2026-11-24T10:42:07Z", "updated_by": { "kind": "user", "id": "usr_asha", "name": "Asha", "room_role": "owner" }, "created_at": "2026-11-24T09:01:00Z" } ] }
```

Sorted by type, then `number`.

### `GET /api/rooms/{room_id}/board`

Everything the Board screen needs in one call.

`200 OK`
```json
{
  "tasks": [
    {
      "task": { "id": "rec_task1", "type": "task", "number": 1, "label": "Task 1", "title": "Write launch plan", "status": "stale", "current_revision": 1, "current_revision_id": "rev_task1_v1", "content": { "description": "Draft the launch plan from the brief and decisions.", "role": "planner", "review_of_task_id": null }, "...": "other Record fields" },
      "claim": null,
      "output": { "record_id": "rec_draft1", "label": "Draft 1", "type": "draft", "revision": 1, "revision_id": "rev_draft1_v1", "status": "stale", "author": { "kind": "agent", "id": "agt_claude", "name": "Asha's Claude", "tool": "claude_code", "role": "planner", "color": "#F59E0B", "user_id": "usr_asha", "user_name": "Asha" } },
      "stale_reason": "based on Decision 2 v1, now v2",
      "pending_approval": null,
      "last_submission": { "id": "sub_1", "status": "completed", "created_at": "2026-11-24T10:05:00Z" }
    }
  ],
  "columns": ["open", "claimed", "in_review", "stale", "approved", "rejected"]
}
```

- `claim`: the active **Claim**, or `null`.
- `output`: the task's current draft or review, or `null`.
- `pending_approval`: an **Approval** with `status: "pending"`, or `null`.

### `GET /api/records/{record_id}`

Record detail with full history. Drives Task detail and Decisions.

`200 OK`
```json
{
  "record": { "id": "rec_task1", "type": "task", "label": "Task 1", "title": "Write launch plan", "status": "in_review", "...": "Record fields" },
  "revisions": [ { "id": "rev_task1_v1", "number": 1, "...": "Revision fields, newest first" } ],
  "claim": null,
  "outputs": [
    { "record": { "id": "rec_draft1", "type": "draft", "label": "Draft 1", "status": "in_review", "...": "Record fields" }, "revisions": [ { "...": "Revision, newest first" } ] }
  ],
  "submissions": [ { "...": "Submission (1.9), newest first" } ],
  "approvals": [ { "...": "Approval (1.10), newest first" } ],
  "comments": [ { "...": "Comment (1.11), oldest first" } ],
  "dependents": [ { "record_id": "rec_draft1", "label": "Draft 1", "revision": 1, "status": "stale" } ],
  "brief": { "id": "rec_brief1", "label": "Brief 1", "title": "Campus app launch brief", "current_revision": 1, "content": { "body": "..." } }
}
```

- `outputs` and `submissions` are only present for tasks.
- `dependents` lists the output revisions whose `based_on` includes any revision of this record. It's useful on decisions and sources.
- `brief` is the room's latest brief, included for tasks so the detail screen needs one call.

### `GET /api/records/{record_id}/revisions/{number}`

`200 OK` → **Revision** (1.7).

### `POST /api/rooms/{room_id}/records`

Owner/mentor. Creates a `brief`, `decision`, `task` or `source` at revision 1. (`draft` and `review` records are only created by agent submissions.)

Request (decision)
```json
{ "type": "decision", "title": "Launch date", "content": { "statement": "We launch on 10 January.", "rationale": "Before term starts." } }
```

Request (task)
```json
{ "type": "task", "title": "Review launch plan", "content": { "description": "Check the plan against the brief and decisions. Verdict + comments.", "role": "reviewer", "review_of_task_id": "rec_task1" } }
```

Request (source)
```json
{ "type": "source", "title": "Academic calendar 2026–27", "content": { "url": "https://example.edu/calendar", "summary": "Exams end 12 January." } }
```

`201 Created`
```json
{ "record": { "...": "Record" }, "revision": { "...": "Revision" } }
```

Emits `revision.created`, plus `task.created` for tasks.

### `POST /api/records/{record_id}/revisions`

> **(v2)** Stale propagation now **crosses the room tree**: changing a decision in a parent room flags dependent outputs in child rooms too. Each `stale`/`unaffected` item gains `room_id`, `room_name` and `in_child_room`, and the response gains `by_room` (§11.4). Editing an **inherited** record from a child room returns `403`; edit it in the room that owns it.

Owner/mentor. Edits a `brief`, `decision`, `task` or `source` by appending a new revision (nothing is overwritten). **Editing a decision, brief or source triggers stale propagation.**

Request
```json
{ "title": "Launch date", "content": { "statement": "We launch on 15 January.", "rationale": "Exams end on 12 January." }, "note": "Exam timetable moved." }
```

`title` is optional (unchanged if omitted). `note` is optional and shown in the timeline.

`201 Created`
```json
{
  "record": { "id": "rec_dec2", "label": "Decision 2", "current_revision": 2, "...": "Record" },
  "revision": { "id": "rev_dec2_v2", "number": 2, "...": "Revision" },
  "stale": [
    { "record_id": "rec_draft1", "label": "Draft 1", "type": "draft", "title": "Launch plan", "revision": 1, "task_id": "rec_task1", "task_label": "Task 1", "reason": "based on Decision 2 v1, now v2", "path": ["Decision 2 v1", "Draft 1 v1"] },
    { "record_id": "rec_review2", "label": "Review 2", "type": "review", "title": "Review of launch plan", "revision": 1, "task_id": "rec_task2", "task_label": "Task 2", "reason": "based on Draft 1 v1, which is stale (Decision 2 v1, now v2)", "path": ["Decision 2 v1", "Draft 1 v1", "Review 2 v1"] }
  ],
  "unaffected": [
    { "record_id": "rec_draft3", "label": "Draft 3", "type": "draft", "title": "Volunteer rota", "revision": 1, "task_id": "rec_task3", "task_label": "Task 3", "status": "approved" }
  ]
}
```

- `stale` lists every output whose current revision now depends, directly or transitively, on an old revision of this record. Each one is now `stale`, its task is `stale`, and any active claim on it stays valid until it expires.
- `unaffected` lists outputs that don't depend on this record. They are kept, which proves independent work is preserved.

Emits `revision.created`, `decision.changed` (decisions only), and one `record.stale` per stale record.

### `POST /api/records/{record_id}/revisions/preview`

> **(v2)** Also lists child-room outputs, and adds `by_room`: `[{"room_id", "room_name", "count", "text": "1 output stale in Launch Week"}]`.

Owner/mentor. Same body as above. **Writes nothing** and returns what would go stale. Call it as the mentor edits (debounced) to show the warning before saving.

`200 OK`
```json
{
  "would_go_stale": [ { "record_id": "rec_draft1", "label": "Draft 1", "type": "draft", "title": "Launch plan", "revision": 1, "task_id": "rec_task1", "task_label": "Task 1", "reason": "based on Decision 2 v1, now v2", "path": ["Decision 2 v1", "Draft 1 v1"] } ],
  "unaffected": [ { "record_id": "rec_draft3", "label": "Draft 3", "type": "draft", "title": "Volunteer rota", "revision": 1, "task_id": "rec_task3", "task_label": "Task 3", "status": "approved" } ],
  "next_revision": 2
}
```

### `POST /api/records/{record_id}/comments`

Any member.

Request
```json
{ "text": "Please double-check the venue capacity." }
```

`201 Created` → **Comment**. Emits `comment.added`.

---

## 7. Submissions and approvals

Agents create submissions via MCP `submit_result` (section 10). The frontend reads them and decides approvals.

### `GET /api/rooms/{room_id}/submissions`

Query parameters: `task_id`, `status` (comma-separated), `agent_id`, `limit`, `before`.

`200 OK`
```json
{ "submissions": [ { "...": "Submission (1.9), newest first" } ] }
```

### `GET /api/submissions/{submission_id}`

`200 OK` → **Submission**.

### `GET /api/rooms/{room_id}/approvals`

> **(v2)** Items include `kind` (`output` | `memory`). Promotions are listed separately at `GET /api/rooms/{room_id}/promotions`.

Query parameter: `status=pending` (default) | `approved` | `rejected` | `all`.

`200 OK`
```json
{ "approvals": [ { "...": "Approval (1.10)", "revision": { "...": "the Revision awaiting approval, with based_on and sources" }, "previous_revision": { "...": "the stale Revision it replaces, or null" } } ] }
```

`previous_revision` lets the UI show a before/after diff.

### `POST /api/approvals/{approval_id}/decide`

See 0.4 for who may decide.

Request
```json
{ "decision": "approved", "comment": "Dates now match Decision 2 v2." }
```

`decision` is `approved` or `rejected`. `comment` is required when rejecting.

`200 OK`
```json
{ "approval": { "...": "Approval, now decided" }, "record": { "...": "the output Record" }, "task": { "...": "the task Record" } }
```

Effects:
- `approved`: the output and task become `approved`.
- `rejected`: the output becomes `rejected`, and the task goes back to `open` (with its claim released) so an agent can redo it.

Emits `approval.decided`. `409` if already decided.

---

## 8. Evidence and presence

### `GET /api/rooms/{room_id}/events`

Query parameters:
- `since_seq` (exclusive, default 0)
- `limit` (default 100, max 500)
- `types` (comma-separated)
- `record_id`: events touching this record, its task or its outputs

`200 OK`
```json
{ "events": [ { "...": "Event (1.12), ascending seq" } ], "latest_seq": 57, "has_more": false }
```

### `GET /api/records/{record_id}/trace`

> **(v2)** New edge `claimed_by` (output revision → the agent that held the task when it was written). Nodes from other rooms carry `room_id` and `room_name`, and edges can cross rooms (a child draft based on a parent decision), plus `promoted_to` (child revision → parent memory item).

Builds the evidence graph from an output (or a task, which uses its output) back through `based_on` to the decisions, sources and people behind it, including superseded revisions. Optional `?revision=N`.

`200 OK`
```json
{
  "root": "rev:rev_draft1_v2",
  "nodes": [
    { "id": "rev:rev_draft1_v2", "kind": "revision", "record_id": "rec_draft1", "record_type": "draft", "label": "Draft 1 v2", "title": "Launch plan", "status": "approved", "is_current": true, "created_at": "2026-11-24T10:47:00Z" },
    { "id": "rev:rev_draft1_v1", "kind": "revision", "record_id": "rec_draft1", "record_type": "draft", "label": "Draft 1 v1", "title": "Launch plan", "status": "stale", "is_current": false, "created_at": "2026-11-24T10:05:00Z" },
    { "id": "rev:rev_dec2_v2", "kind": "revision", "record_id": "rec_dec2", "record_type": "decision", "label": "Decision 2 v2", "title": "Launch date", "status": "approved", "is_current": true, "created_at": "2026-11-24T10:42:07Z" },
    { "id": "rev:rev_dec2_v1", "kind": "revision", "record_id": "rec_dec2", "record_type": "decision", "label": "Decision 2 v1", "title": "Launch date", "status": "approved", "is_current": false, "created_at": "2026-11-24T09:01:00Z" },
    { "id": "rev:rev_src1_v1", "kind": "revision", "record_id": "rec_src1", "record_type": "source", "label": "Source 1 v1", "title": "Academic calendar 2026–27", "status": "approved", "is_current": true, "created_at": "2026-11-24T09:01:00Z" },
    { "id": "agent:agt_claude", "kind": "agent", "label": "Asha's Claude", "tool": "claude_code", "color": "#F59E0B", "user_name": "Asha" },
    { "id": "user:usr_asha", "kind": "user", "label": "Asha", "room_role": "owner" },
    { "id": "user:usr_ben", "kind": "user", "label": "Ben", "room_role": "mentor" }
  ],
  "edges": [
    { "from": "rev:rev_draft1_v2", "to": "rev:rev_dec2_v2", "kind": "based_on" },
    { "from": "rev:rev_draft1_v2", "to": "rev:rev_src1_v1", "kind": "cites" },
    { "from": "rev:rev_draft1_v2", "to": "rev:rev_draft1_v1", "kind": "supersedes" },
    { "from": "rev:rev_draft1_v1", "to": "rev:rev_dec2_v1", "kind": "based_on" },
    { "from": "rev:rev_dec2_v2", "to": "rev:rev_dec2_v1", "kind": "supersedes" },
    { "from": "rev:rev_draft1_v2", "to": "agent:agt_claude", "kind": "authored_by", "at": "2026-11-24T10:47:00Z" },
    { "from": "rev:rev_dec2_v2", "to": "user:usr_asha", "kind": "authored_by", "at": "2026-11-24T10:42:07Z" },
    { "from": "rev:rev_draft1_v2", "to": "user:usr_ben", "kind": "approved_by", "at": "2026-11-24T10:49:30Z" }
  ],
  "story": [
    { "seq": 12, "at": "2026-11-24T10:05:00Z", "text": "Asha's Claude (claude_code) wrote Draft 1 v1 based on Decision 2 v1." },
    { "seq": 41, "at": "2026-11-24T10:42:07Z", "text": "Asha changed Decision 2 to v2: \"We launch on 15 January.\"" },
    { "seq": 42, "at": "2026-11-24T10:42:07Z", "text": "Draft 1 v1 marked stale (based on Decision 2 v1, now v2)." },
    { "seq": 47, "at": "2026-11-24T10:47:00Z", "text": "Asha's Claude wrote Draft 1 v2 based on Decision 2 v2." },
    { "seq": 49, "at": "2026-11-24T10:49:30Z", "text": "Ben approved Draft 1 v2." }
  ]
}
```

- Node `kind` is `revision`, `agent` or `user`.
- Edge `kind` is one of:
  - `based_on`: a revision used another as input.
  - `cites`: a revision cites a source.
  - `supersedes`: a newer revision of the same record replaces an older one.
  - `authored_by`: who wrote a revision.
  - `approved_by` / `rejected_by`: who decided an approval.
  - `claimed_by`: which agent held the task (reserved; not emitted yet).
  - `owned_by`: an agent node → the teammate who owns it.
- `story` is the chronological, human-readable trace, with `seq` linking to Timeline events.

### `GET /api/rooms/{room_id}/recovery`

> **(v2)** Also lists harness sessions that **crashed** (from `baton-connect`): items with `kind: "harness_session"`, alongside the v1 `kind: "submission"` items.

Submissions that were interrupted (saved but not completed), and those that were resumed by a retry, with proof they were applied once.

`200 OK`
```json
{
  "items": [
    {
      "submission_id": "sub_7",
      "idempotency_key": "crash-demo-3f9a",
      "task": { "id": "rec_task4", "label": "Task 4", "title": "Write FAQ" },
      "agent": { "kind": "agent", "id": "agt_crash", "name": "Crash-test agent", "tool": "other", "role": "planner", "color": "#A78BFA", "user_id": "usr_asha", "user_name": "Asha" },
      "state": "resumed",
      "attempts": 2,
      "saved_at": "2026-11-24T10:30:00Z",
      "interrupted": true,
      "resumed_at": "2026-11-24T10:30:09Z",
      "completed_at": "2026-11-24T10:30:09Z",
      "result_revision": { "id": "rev_draft4_v1", "record_id": "rec_draft4", "label": "Draft 4", "number": 1 },
      "applied_count": 1,
      "revisions_created_for_key": 1,
      "timeline": [
        { "seq": 30, "type": "submission.saved", "at": "2026-11-24T10:30:00Z" },
        { "seq": 31, "type": "agent.crashed", "at": "2026-11-24T10:30:00Z" },
        { "seq": 35, "type": "submission.resumed", "at": "2026-11-24T10:30:09Z" },
        { "seq": 36, "type": "revision.created", "at": "2026-11-24T10:30:09Z" },
        { "seq": 37, "type": "submission.completed", "at": "2026-11-24T10:30:09Z" }
      ]
    }
  ]
}
```

- `state` is one of:
  - `interrupted`: saved, never completed yet.
  - `resumed`: completed by a retry.
  - `duplicate_ignored`: a retry arrived after it was already completed.
- `applied_count` and `revisions_created_for_key` are counted from the database, not assumed. Show them as the "applied exactly once" proof.

### `GET /api/rooms/{room_id}/presence`

`200 OK`
```json
{
  "users": [ { "user_id": "usr_asha", "display_name": "Asha", "room_role": "owner", "online": true, "last_seen_at": "2026-11-24T10:42:00Z" } ],
  "agents": [ { "agent_id": "agt_claude", "name": "Asha's Claude", "tool": "claude_code", "role": "planner", "color": "#F59E0B", "user_id": "usr_asha", "user_name": "Asha", "online": true, "last_seen_at": "2026-11-24T10:41:55Z", "working_on": { "task_id": "rec_task1", "label": "Task 1", "title": "Write launch plan", "lease_expires_at": "2026-11-24T10:56:00Z" } } ]
}
```

- A user is online while they have an open WebSocket to the room.
- An agent is online if it made an MCP call or heartbeat within `BATON_AGENT_ONLINE_SECONDS` (default 120).

---

## 9. WebSocket: live room events

### Connecting

```
ws://localhost:8000/ws/rooms/{room_id}?token=bs_...&since_seq=57
```

- `token`: a session token (browsers can't set headers on WebSockets). The server never logs it.
- `since_seq`: optional. The server first replays every event with `seq > since_seq` in order, then streams live ones. Keep the last `seq` you processed, and on reconnect pass it, so nothing is missed or duplicated.

Close codes:
- `4401`: bad or missing token.
- `4403`: you aren't a member of the room.
- `4404`: unknown room.

### Server → client messages

Every message has a `kind`:

```json
{ "kind": "hello", "room_id": "room_campus", "latest_seq": 57, "presence": { "...": "same as GET /presence" } }
```

```json
{ "kind": "event", "event": { "...": "Event (1.12)" } }
```

```json
{ "kind": "pong" }
```

The server sends `hello` once after connecting, before any replayed events.

### Client → server messages

```json
{ "kind": "ping" }
```

Send one every 25 s to keep the connection alive.

```json
{ "kind": "resume", "since_seq": 57 }
```

`resume` replays any events after `since_seq` without reconnecting.

### Event types and payloads

Every event has the envelope from 1.12. These are the `payload` fields per `type`. Reference objects are compact: `{ "id", "label", "title" }` for records, and **Actor** for agents and users.

| type | payload | when |
|---|---|---|
| `member.joined` | `{ "user": User, "role": "member" }` | Someone created or joined the room |
| `member.role_changed` | `{ "user": User, "from": "member", "to": "mentor" }` | Owner changed a role |
| `room.settings_changed` | `{ "settings": RoomSettings, "changed": ["min_sources"] }` | Settings saved |
| `agent.created` | `{ "agent": Agent }` | Agent created |
| `agent.revoked` | `{ "agent_id": "agt_x" }` | Agent revoked |
| `agent.connected` | `{ "agent": Agent }` | Agent's first MCP call after being offline |
| `agent.crashed` | `{ "agent": Actor, "submission_id": "sub_7", "task": RecordRef }` | Crash demo only: the process died after `saved` |
| `presence.changed` | `{ "users": [...], "agents": [...] }` (same as GET /presence) | Anyone came online, went offline, or started/stopped working on a task. **Ephemeral:** not stored, so `seq` and `id` are `null`; it never appears in `GET /events` or replays. Don't use it to advance `lastSeq`. |
| `task.created` | `{ "task": Record }` | A mentor created a task |
| `task.claimed` | `{ "task": RecordRef, "claim": Claim }` | An agent claimed a task |
| `task.heartbeat` | `{ "task": RecordRef, "lease_expires_at": "..." }` | Lease extended. Update the countdown; don't show it in the activity feed. |
| `task.released` | `{ "task": RecordRef, "agent": Actor, "reason": "released" \| "submitted" \| "revoked" \| "rejected" }` | Claim ended normally |
| `claim.expired` | `{ "task": RecordRef, "agent": Actor, "expired_at": "..." }` | The lease ran out (the agent died or went quiet) |
| `submission.saved` | `{ "submission": Submission }` | All checks passed and the submission is stored, not yet applied |
| `verification.check` | `{ "submission_id": "sub_1", "task": RecordRef, "agent": Actor, "check": { "name": "revisions_current", "order": 3, "passed": false, "detail": "stale: based on Decision 2 v1, now v2; ..." }, "total_checks": 7 }` | One per check, streamed **as each check runs** (in order 1–7) |
| `submission.completed` | `{ "submission": Submission, "revision": Revision, "record": RecordRef }` | Applied: a new revision exists |
| `submission.rejected` | `{ "submission": Submission, "failed_check": "revisions_current", "reason": "stale: ..." }` | A check failed, so nothing was applied |
| `submission.resumed` | `{ "submission_id": "sub_7", "idempotency_key": "crash-demo-3f9a", "attempt": 2, "previous_status": "saved" }` | A retry with the same key found an interrupted submission and is finishing it |
| `submission.duplicate` | `{ "submission_id": "sub_7", "idempotency_key": "...", "attempt": 3 }` | A retry arrived after completion. The existing result was returned and nothing was applied. |
| `revision.created` | `{ "record": Record, "revision": Revision }` | Any new revision (mentor edit or agent output) |
| `decision.changed` | `{ "record": RecordRef, "from_revision": 1, "to_revision": 2, "before": {...content}, "after": {...content}, "note": "Exam timetable moved.", "stale_count": 2 }` | A mentor edited a decision |
| `record.stale` | `{ "record": RecordRef, "revision": 1, "task": RecordRef, "reason": "based on Decision 2 v1, now v2", "caused_by": { "record": RecordRef, "from_revision": 1, "to_revision": 2 }, "path": ["Decision 2 v1", "Draft 1 v1"] }` | One per output marked stale |
| `approval.requested` | `{ "approval": Approval }` | Corrected or new work is waiting for a human |
| `approval.decided` | `{ "approval": Approval, "decided_by": Actor }` | Approved or rejected |
| `comment.added` | `{ "comment": Comment, "record": RecordRef }` | Human or agent comment |
| `room.created` **(v2)** | `{ "room": Room, "parent": {id, name} \| null }` | A room was created; also sent to the parent room's stream for a child |
| `memory.added` **(v2)** | `{ "item": MemoryItem, "room": {id, name} }` | A memory item reached the master (mentor-authored, approved proposal, or approved promotion) |
| `memory.proposed` **(v2)** | `{ "item": MemoryItem, "approval": Approval }` | An agent's `add_memory` passed its checks and waits for approval |
| `promotion.requested` **(v2)** | `{ "promotion": Promotion }` | A child room's verified work asks to enter this (parent) room's master. Sent to both rooms. |
| `promotion.decided` **(v2)** | `{ "promotion": Promotion, "decided_by": Actor }` | The parent mentor approved or rejected it. Sent to both rooms. |
| `task.reopened` **(v2)** | `{ "task": RecordRef, "review": RecordRef, "reason": "request_changes" }` | A reviewer asked for changes, so the reviewed task is open again |
| `harness.session_started` **(v2)** | `{ "session": HarnessSession, "agent": Actor }` | `baton-connect` started a harness (Claude Code, Codex, Gemini CLI, OpenCode) |
| `harness.session_ended` **(v2)** | `{ "session": HarnessSession, "agent": Actor, "status": "ended" \| "crashed", "reason": "..." }` | The harness finished or crashed (crashes also appear in Recovery) |
| `harness.progress` **(v2)** | `{ "session_id", "agent": Actor, "kind": "message" \| "tool_call" \| "plan", "text": "..." }` | Live progress from a harness. **Ephemeral** like `presence.changed` (`seq: null`). |

**Example: an agent submits work based on an old decision.** The room receives this sequence in order:

```json
{ "kind": "event", "event": { "seq": 60, "type": "verification.check", "summary": "Ben's Codex · Task 1 · claim_valid passed", "payload": { "submission_id": "sub_4", "task": { "id": "rec_task1", "label": "Task 1", "title": "Write launch plan" }, "agent": { "kind": "agent", "id": "agt_codex", "name": "Ben's Codex", "tool": "codex", "role": "planner", "color": "#22D3EE", "user_id": "usr_ben", "user_name": "Ben" }, "check": { "name": "claim_valid", "order": 1, "passed": true, "detail": "Ben's Codex holds the lease on Task 1." }, "total_checks": 7 } } }
{ "kind": "event", "event": { "seq": 61, "type": "verification.check", "summary": "Ben's Codex · Task 1 · permission passed", "payload": { "...": "order 2" } } }
{ "kind": "event", "event": { "seq": 62, "type": "verification.check", "summary": "Ben's Codex · Task 1 · revisions_current FAILED: stale: based on Decision 2 v1, now v2", "payload": { "submission_id": "sub_4", "check": { "name": "revisions_current", "order": 3, "passed": false, "detail": "stale: based on Decision 2 v1, now v2; call read_record and resubmit." }, "total_checks": 7, "...": "task, agent" } } }
{ "kind": "event", "event": { "seq": 63, "type": "submission.rejected", "summary": "Ben's Codex's submission for Task 1 was rejected: stale: based on Decision 2 v1, now v2", "payload": { "failed_check": "revisions_current", "reason": "stale: based on Decision 2 v1, now v2; call read_record and resubmit.", "submission": { "...": "Submission" } } } }
```

A passing submission streams 7 `verification.check` events, then `submission.saved`, `revision.created`, `submission.completed`, `task.released` (reason `submitted`), and `approval.requested` if approval is needed.

---

## 10. MCP tools (reference, for agents)

The frontend doesn't call these, but every UI state is caused by them. Served at `/mcp` (Streamable HTTP). The agent's identity and role come from its bearer token. Every agent tool gets the identical tool list:

| Tool | Arguments | Returns |
|---|---|---|
| `get_room_context` | — | Room name, latest brief (with `revision_id`), all current decisions (with `revision_id`), sources, my agent name/role, my active claims, room settings |
| `list_tasks` | `status?` | Tasks with label, title, role, status, claim holder |
| `read_record` | `record_id` (UUID or label like `"Decision 2"`), `revision?` | Content, revision number, `revision_id`, `based_on`, status, cited sources, comments |
| `claim_task` | `task_id` | Claim with `lease_expires_at`, plus the task's inputs (brief, decisions, the draft under review for reviewer tasks) |
| `heartbeat` | `task_id` | New `lease_expires_at` |
| `submit_result` | `task_id`, `content`, `based_on` (revision IDs), `sources` (source record IDs), `idempotency_key`, `title?` | Submission status and every check result |
| `release_task` | `task_id` | OK |
| `add_source` | `title`, `url_or_text` | The new source record and its `revision_id` |
| `comment` | `record_id`, `text` | The comment |
| `search_memory` **(v2)** | `query?`, `category?`, `tags?`, `include_ancestors` (default `true`) | Matching master memory items (FTS5 text search), each with `revision_id` to cite, `room_name` and `inherited` |
| `save_private` **(v2)** | `key`, `content`, `expires_in_minutes?` (default 1440) | Saved to **your private workspace** only. Never visible to the room, never makes anything stale. |
| `read_private` **(v2)** | `key?` (omit to list) | Your private notes and drafts |
| `add_memory` **(v2)** | `category` (`fact` \| `lesson` \| `glossary` \| `note`), `title`, `body`, `tags?`, `sources?`, `confidence?`, `idempotency_key` | Runs checks (permission, sources exist, content), then becomes a master memory item, waiting for approval if the room requires it. Brief, decisions and sources stay mentor-only. |

**(v2)** `get_room_context` also returns `room.path` (ancestors → this room), `inherited_decisions` (from ancestor rooms, each with `room_name` and `revision_id`), `memory_highlights` (recent facts and lessons), and `others_working` (`[{agent, tool, task, since}]` for every other agent holding a claim in this room). `claim_task` returns a **context packet** sized for the calling agent's profile (§11.7).

Errors are short and actionable, e.g.:
- `stale: based on Decision 2 v1, now v2; call read_record("Decision 2") and resubmit with the new revision_id.`
- `not claimed: claim_task("Task 1") first.`
- `already claimed by Ben's Codex until 10:56Z; pick another task with list_tasks.`

---

## 11. v2 additions

Everything in this section is new in v2. v1 endpoints keep working unchanged, apart from the extra fields marked **(v2)** above.

### 11.1 Room tree (v2)

Rooms form trees, like Discord categories: **Campus App Launch** → **Launch Week** → (one more level allowed). A child room:
- **reads** its ancestors' master memory (brief, decisions, sources, facts…), marked `inherited`
- **writes** only its own master
- sends work **up** only through a verified submission plus a parent mentor's approval (a promotion, §11.5)
- has its own invite code; joining it gives read access to its ancestors, never to its siblings

**Room (v2 fields)**

```json
{
  "id": "room_week",
  "name": "Launch Week",
  "parent_id": "room_campus",
  "root_id": "room_campus",
  "depth": 2,
  "path": [{ "id": "room_campus", "name": "Campus App Launch" }, { "id": "room_week", "name": "Launch Week" }],
  "children": [],
  "access": "member",
  "invite_code": "WEEK-4MTD",
  "my_role": "owner",
  "settings": { "...": "as v1" },
  "counts": { "...": "as v1" },
  "latest_seq": 12,
  "created_at": "2026-11-24T09:10:00Z"
}
```

#### `POST /api/rooms` with `parent_id` (v2)

Request
```json
{ "name": "Launch Week", "parent_id": "room_campus" }
```
`201 Created` → **Room** (with `depth: 2`). `403` if you're not owner/mentor of the parent. `409` `"Rooms can be nested at most 3 deep."` Emits `room.created` in both rooms.

#### `GET /api/rooms/tree` (v2)

Everything the nested sidebar needs: every room you belong to, plus its ancestors (as `access: "read"` if you're not a member of them). Siblings you don't belong to are not included.

`200 OK`
```json
{
  "trees": [
    {
      "id": "room_campus", "name": "Campus App Launch", "access": "member", "my_role": "owner", "depth": 1,
      "counts": { "stale": 0, "pending_approvals": 1, "pending_promotions": 1 },
      "children": [
        {
          "id": "room_week", "name": "Launch Week", "access": "member", "my_role": "owner", "depth": 2,
          "counts": { "stale": 1, "pending_approvals": 0, "pending_promotions": 0 },
          "children": []
        }
      ]
    }
  ]
}
```

### 11.2 Agent profiles (v2)

```json
{
  "id": "agt_claude",
  "name": "Asha's Claude",
  "tool": "claude_code",
  "role": "planner",
  "profile": {
    "harness": "claude_code",
    "model": "claude-opus-5-5",
    "context_window": 200000,
    "context_format": "markdown",
    "connection": "acp"
  },
  "session": {
    "id": "hs_1", "status": "running", "harness": "claude_code", "model": "claude-opus-5-5",
    "task_label": "Task 1", "started_at": "2026-11-24T10:04:50Z", "last_update_at": "2026-11-24T10:05:02Z"
  },
  "...": "other v1 Agent fields"
}
```

- `harness` is one of `claude_code`, `codex`, `gemini_cli`, `opencode`, `cursor` or `other`.
- `connection` is either:
  - `acp`: `baton-connect` started the harness, so Baton sees its session.
  - `mcp`: the v1 direct path, where the agent was configured by hand.
- `context_format` is `markdown` or `json`.
- Defaults come from `tool`:

  | tool | default context window |
  |---|---|
  | claude_code | 200,000 |
  | codex | 272,000 |
  | gemini_cli | 1,000,000 |
  | opencode | 128,000 |
  | anything else | 32,000 |

#### `PATCH /api/rooms/{room_id}/agents/{agent_id}` (v2)

The agent's owner or a mentor can change its `name`, `role` or `profile`.

Request
```json
{ "profile": { "model": "gpt-6-luna", "context_window": 272000, "context_format": "json" } }
```
`200 OK` → **Agent**.

### 11.3 Memory (v2)

The **master memory** is long-term knowledge every agent in the room (and its child rooms) reads for context. Nothing in it is ever overwritten; every change is a new revision, as in the v1 ledger.

**Categories**

| category | label | `content` shape | Who writes it |
|---|---|---|---|
| `brief` | Brief N | `{ "body" }` | mentors |
| `decision` | Decision N | `{ "statement", "rationale?" }` | mentors |
| `source` | Source N | `{ "url?", "text?", "summary?" }` | mentors and agents (`add_source`, as v1) |
| `fact` | Fact N | `{ "body" }` | mentors, agents via `add_memory` |
| `lesson` | Lesson N | `{ "body" }` | mentors, agents via `add_memory` |
| `glossary` | Term N | `{ "term", "definition" }` | mentors, agents via `add_memory` |
| `note` | Note N | `{ "body" }` | mentors, agents via `add_memory`, promotions |

**MemoryItem**

```json
{
  "id": "mem_dec2",
  "room_id": "room_campus",
  "room_name": "Campus App Launch",
  "inherited": true,
  "category": "decision",
  "number": 2,
  "label": "Decision 2",
  "title": "Launch date",
  "body": "We launch on 15 January. — Exams end 12 January.",
  "content": { "statement": "We launch on 15 January.", "rationale": "Exams end 12 January." },
  "tags": ["dates", "launch"],
  "status": "approved",
  "confidence": 1.0,
  "expires_at": null,
  "provenance": {
    "added_by": { "kind": "user", "id": "usr_asha", "name": "Asha", "room_role": "owner" },
    "submission_id": null,
    "promoted_from": null
  },
  "current_revision": 2,
  "current_revision_id": "rev_dec2_v2",
  "created_at": "2026-11-24T09:01:00Z",
  "updated_at": "2026-11-24T10:42:07Z"
}
```

- `body` is a plain-text rendering for display and search. `content` keeps the category shape, and v1 shapes are unchanged.
- `status` is one of:
  - `approved`: in the master.
  - `pending`: an agent proposal waiting for approval.
  - `expired`: `expires_at` has passed. Expired items are hidden from searches unless `include_expired=true`.
- `confidence` runs from 0 to 1. Mentor-authored items are 1.0; agent proposals default to 0.7.
- `inherited` is `true` when the item belongs to an ancestor room.

#### `GET /api/rooms/{room_id}/memory` (v2)

Query parameters:
- `category`: comma-separated
- `tag`
- `q`: full-text search over title and body (SQLite FTS5; supports prefix `launch*` and phrases `"term starts"`)
- `include_ancestors`: default `true`
- `include_expired`: default `false`
- `status`: default `approved`; use `pending` or `all`

`200 OK`
```json
{
  "items": [ { "...": "MemoryItem, own room first, then ancestors nearest-first; within each, by category then number" } ],
  "counts": { "brief": 1, "decision": 3, "source": 3, "fact": 2, "lesson": 1, "glossary": 2, "note": 0 }
}
```

#### `GET /api/memory/{item_id}` (v2)

`200 OK` → `{ "item": MemoryItem, "revisions": [Revision…], "dependents": [ {record_id, label, room_name, status} ] }`. Readable by members of the item's room and of its descendants.

#### `POST /api/rooms/{room_id}/memory` (v2)

Owner/mentor. Creates an item at revision 1 (status `approved`). For `brief`, `decision` and `source`, this is the same as `POST /api/rooms/{room_id}/records`.

Request
```json
{ "category": "fact", "title": "Term start", "content": { "body": "Spring term starts 13 January." }, "tags": ["dates"], "expires_at": null }
```
`201 Created` → `{ "item": MemoryItem, "revision": Revision }`. Emits `memory.added`.

#### `POST /api/memory/{item_id}/revisions` and `…/revisions/preview` (v2)

Same bodies and responses as `POST /api/records/{id}/revisions` and its preview (decisions here **are** those records), including cross-room stale propagation (§11.4). `403` if the item is inherited; edit it in its own room.

### 11.4 Cross-room stale preview (v2)

Changing **Decision 2** in *Campus App Launch* also flags the draft in *Launch Week* that was based on it.

`POST /api/records/{decision_id}/revisions/preview` → `200 OK`
```json
{
  "would_go_stale": [
    { "record_id": "rec_draft1", "label": "Draft 1", "type": "draft", "title": "Launch plan", "revision": 1,
      "task_id": "rec_task1", "task_label": "Task 1", "room_id": "room_campus", "room_name": "Campus App Launch",
      "in_child_room": false, "reason": "based on Decision 2 v1, now v2", "path": ["Decision 2 v1", "Draft 1 v1"] },
    { "record_id": "rec_w_draft1", "label": "Draft 1", "type": "draft", "title": "Launch-day run sheet", "revision": 1,
      "task_id": "rec_w_task1", "task_label": "Task 1", "room_id": "room_week", "room_name": "Launch Week",
      "in_child_room": true, "reason": "based on Decision 2 v1 (Campus App Launch), now v2",
      "path": ["Campus App Launch › Decision 2 v1", "Launch Week › Draft 1 v1"] }
  ],
  "unaffected": [ { "...": "as v1, plus room_id / room_name / in_child_room" } ],
  "by_room": [
    { "room_id": "room_campus", "room_name": "Campus App Launch", "count": 1, "text": "1 output stale in Campus App Launch" },
    { "room_id": "room_week", "room_name": "Launch Week", "count": 1, "text": "1 output stale in Launch Week" }
  ],
  "next_revision": 2
}
```

Labels are per room ("Draft 1" exists in both rooms), so always show `room_name` next to a label from another room. Saving emits `decision.changed` in the parent and one `record.stale` **in each affected room's** stream.

### 11.5 Promotions: child → parent (v2)

A child room's work reaches the parent's master only as a **promotion**: verified in the child (and approved there if the child requires it), then approved by a parent mentor. On approval, the content is copied into the parent's master memory as a new item (category chosen by the requester, default `note`), with `provenance.promoted_from` pointing at the child revision. The child keeps its own copy.

**Promotion**
```json
{
  "id": "prm_1",
  "from_room": { "id": "room_week", "name": "Launch Week" },
  "to_room": { "id": "room_campus", "name": "Campus App Launch" },
  "source": { "record_id": "rec_w_draft1", "label": "Draft 1", "revision": 2, "revision_id": "rev_w_draft1_v2", "type": "draft", "title": "Launch-day run sheet" },
  "category": "note",
  "title": "Launch-day run sheet (from Launch Week)",
  "status": "pending",
  "requested_by": { "kind": "user", "id": "usr_chen", "name": "Chen", "room_role": "owner" },
  "requested_at": "2026-11-24T11:00:00Z",
  "decided_by": null,
  "decided_at": null,
  "comment": null,
  "result_item_id": null
}
```

#### `POST /api/records/{record_id}/promote` (v2)

Owner/mentor of the **child** room. Only `approved` outputs (or approved memory items) can be promoted.

Request
```json
{ "category": "note", "title": "Launch-day run sheet (from Launch Week)" }
```
`201 Created` → **Promotion**. `409` if the room has no parent or the record isn't approved. Emits `promotion.requested` in both rooms.

#### `GET /api/rooms/{room_id}/promotions?status=pending` (v2)

Promotions **into** this room (`status`: `pending` (default) | `approved` | `rejected` | `all`). Add `direction=outgoing` for promotions **from** this room. Each item includes `revision` (the full child Revision) for review.

#### `POST /api/promotions/{promotion_id}/decide` (v2)

Owner/mentor of the **parent** room. Same body as approvals: `{ "decision": "approved" | "rejected", "comment" }`, where the comment is required to reject. `200 OK` → `{ "promotion": Promotion, "item": MemoryItem | null }`. Emits `promotion.decided` (both rooms) and `memory.added` (parent) on approval.

### 11.6 Harness sessions and `baton-connect` (v2)

`baton-connect` is a CLI that runs **on the host** (not in Docker). It starts a harness through ACP (Agent Client Protocol), passes it the Baton MCP server, sends a Baton task as the prompt, and reports progress and the session's end (or crash) back to Baton. The v1 direct MCP setup keeps working as the fallback.

Install it once from the repo root:
```bash
uv tool install ./connector
```

**HarnessSession**
```json
{
  "id": "hs_1",
  "agent_id": "agt_claude",
  "room_id": "room_campus",
  "harness": "claude_code",
  "model": "claude-opus-5-5",
  "acp_agent": "claude-agent-acp 0.110.1",
  "mcp_transport": "http",
  "task_id": "rec_task1",
  "task_label": "Task 1",
  "status": "running",
  "started_at": "2026-11-24T10:04:50Z",
  "ended_at": null,
  "stop_reason": null,
  "error": null,
  "updates": 14,
  "last_update_at": "2026-11-24T10:05:02Z",
  "last_text": "Submitting the launch plan…"
}
```

- `status` is one of `running`, `ended` or `crashed`.
- `mcp_transport` is `http` (Baton is passed directly) or `stdio-bridge` (the harness doesn't support HTTP MCP, so `baton-connect` bridges).

#### Connector endpoints (agent token)

| Endpoint | Body | Response |
|---|---|---|
| `POST /api/harness/sessions` | `{ "harness", "model", "acp_agent", "mcp_transport", "task": "Task 1" \| null }` | `201` HarnessSession. Emits `harness.session_started`. |
| `POST /api/harness/sessions/{id}/updates` | `{ "kind": "message" \| "tool_call" \| "plan", "text" }` | `204`. Broadcast as ephemeral `harness.progress`, throttled to 2 per second per session. |
| `POST /api/harness/sessions/{id}/end` | `{ "status": "ended" \| "crashed", "stop_reason": "end_turn" \| null, "error": "..." \| null }` | `200` HarnessSession. Emits `harness.session_ended`. Crashes also appear in Recovery. |

A session with no update for 5 minutes is marked `crashed` with `error: "no heartbeat"`.

#### `GET /api/rooms/{room_id}/harness/sessions?active=true` (v2)

Members. `200 OK` → `{ "sessions": [HarnessSession…] }`.

#### Config snippet (v2)

`GET /api/rooms/{room_id}/agents/{agent_id}/config` adds, first in `snippets`:
```json
{
  "baton_connect": {
    "title": "baton-connect (recommended)",
    "description": "Starts Claude Code over ACP with Baton attached and reports progress live. Run on your laptop.",
    "install": "uv tool install ./connector",
    "command": "baton-connect run --server http://192.168.1.20:8000 --token <BATON_TOKEN> --harness claude_code --task \"Task 1\""
  }
}
```

### 11.7 Context packets (v2)

Baton builds the context an agent receives (from `claim_task`, or the `baton-connect` prompt) to fit the agent's profile:
- **Order (most important first):**
  1. the task
  2. decisions, this room's and inherited
  3. the brief
  4. cited and recent sources
  5. matching memory (facts, lessons, glossary)
  6. what other agents are doing
- **Size:** trimmed to `min(context_window × 0.25, 60,000)` tokens. Tokens are estimated as characters ÷ 4.
- **Format:** `markdown` or `json`, per the profile.
- **Never trimmed:** every item keeps its `revision_id`, so the agent can cite it in `based_on`.

#### `GET /api/rooms/{room_id}/agents/{agent_id}/context-packet?task=Task%201` (v2)

Owner of the agent or a mentor. Previews exactly what the agent will receive.

`200 OK`
```json
{ "format": "markdown", "budget_tokens": 50000, "used_tokens": 3120, "trimmed": [], "packet": "# Task 1 — Write launch plan\n..." }
```

### 11.8 Private workspace (v2)

Each agent has a private workspace: private state (drafts in progress) and private memory (scratch notes with an expiry). It never changes the master, never triggers stale flags, and never emits room events.

#### `GET /api/agents/{agent_id}/private` (v2)

**Only the agent's owner** (session token) or the agent itself (agent token). Anyone else gets `404`, even mentors.

`200 OK`
```json
{
  "agent_id": "agt_claude",
  "items": [
    { "key": "plan-outline", "kind": "draft", "content": "1. Soft launch…", "expires_at": null, "updated_at": "2026-11-24T10:03:00Z" },
    { "key": "todo", "kind": "note", "content": "Check venue capacity", "expires_at": "2026-11-25T10:03:00Z", "updated_at": "2026-11-24T10:03:00Z" }
  ]
}
```

Agents use the MCP tools `save_private` and `read_private` (§10). The pattern is: **pull** context from the master, work privately, then **push** to the master only with `submit_result` or `add_memory`.

## 12. Changelog

Newest first.

- **v2.0 (2026-11-24)**: room tree, master memory vs state, private workspaces, promotions, harness sessions via `baton-connect`, new MCP tools, new events. Every change is marked **(v2)** above and fully specified in §11. All v1 endpoints keep working.
- **v1.5 (2026-11-24, milestone 7)**: draft/review records take their task's number (Task 2 → Review 2).
- **v1.4 (2026-11-24, milestone 6)**: trace adds an `owned_by` edge (agent → the teammate who owns it), a `record` field ({id,label,title}) and `revision_id` on revision nodes; superseded revisions have `status: "superseded"`; a task with no output returns `root: null` plus `message`. Recovery items add `status`. Work resumed after its inputs changed is applied once and immediately marked stale (`record.stale` with `caused_by: null`).
- **v1.3 (2026-11-24, milestone 5)**: when work goes stale, its pending approval is closed automatically (`approval.decided` with actor `system`, `status: "rejected"`, `payload.approval.automatic: true`). Editing a source also flags outputs that cite it. Stale items include `status_before`.
- **v1.2 (2026-11-24, milestone 4)**: `presence.changed` messages have `seq: null` and `id: null` (not stored). MCP `list_tasks` also returns `claimable_by_you`.
- **v1.1 (2026-11-24, milestone 2)**: any member may create agents for themselves (simplified rule); agent config responses include `token_included` (`true` only in the create response).
- **v1 (2026-11-24)**: initial contract (milestone 1).
