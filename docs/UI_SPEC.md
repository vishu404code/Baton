# Baton UI Spec (v2)

> **v2 in one line:** rooms nest into a tree, there's a Memory screen, agents show their harness and model, `baton-connect` is the recommended way to connect, and the stale preview includes child rooms. Every new or changed part is marked **(v2)**; §7 has the new screens in full.

This is for the frontend team (built in Google Antigravity, in `frontend/`). The backend never touches `frontend/`. All data comes from `docs/API_CONTRACT.md`, and section numbers like "API §6" refer to that file.

The judges must be able to see **six things** on screen: two different tools connected, one shared record, a handoff, a changed decision with stale flags and approval, crash recovery applied once, and an evidence trace. Every screen below exists to make one of these visible. If something is hard to build, cut polish, not those.

---

## 1. Look and feel

- **Style:** a dark developer-tool look in the spirit of Linear, with a Discord-like layout. Calm, dense, keyboard-friendly, no gradients or illustrations.
- **Font:** Inter (UI) and JetBrains Mono (IDs, revisions, idempotency keys, config snippets).
- **Base colours:**

  | Token | Value | Use |
  |---|---|---|
  | `--bg-app` | `#0B0C0F` | Left rail |
  | `--bg-sidebar` | `#111217` | Room sidebar, right panel |
  | `--bg-main` | `#16171D` | Main area |
  | `--bg-raised` | `#1D1F27` | Cards, dialogs |
  | `--border` | `#2A2D37` | Dividers, card borders |
  | `--text` | `#E6E7EB` | Primary text |
  | `--text-muted` | `#8B8FA3` | Secondary text |
  | `--accent` | `#6366F1` | Indigo: primary buttons, focus, in progress |

- **Status colours** (use these everywhere; never colour by anything else):

  | Status | Colour | Chip |
  |---|---|---|
  | `approved` | green `#22C55E` | solid dot + "Approved" |
  | `stale` | amber `#F59E0B` | warning icon + "Stale" |
  | `rejected`, failed check, blocked | red `#EF4444` | x icon + "Rejected"/"Failed" |
  | `claimed` (in progress) | indigo `#6366F1` | pulsing dot + "In progress" |
  | `in_review` | indigo outline | "Needs approval" |
  | `open` | grey `#6B7280` | hollow dot + "Open" |

- **Agent badges:** each agent has a server-assigned `color` (API §1.5). Render a small rounded badge with the tool icon (Claude / Codex / Gemini / Cursor / generic) plus the agent name, tinted with that colour. Use it the same way everywhere an agent appears.
- **Revision pills:** `Decision 2 · v2` in monospace. Amber if `is_current: false`. Clicking one opens that revision.
- **Motion:** new live items slide in at the top of feeds (150 ms). Verification checks tick in one by one. No other animation.
- **Light mode:** not needed.

## 2. App shell (Discord-like)

```
┌────┬───────────────┬──────────────────────────────────────┬────────────────┐
│ ◉  │ Campus App    │                                      │ ONLINE         │
│ ◉  │ Launch  ▾     │                                      │ ● Asha (owner) │
│ ◉  │───────────────│          MAIN AREA                   │   └ Claude ·   │
│    │ ▣ Board       │          (selected view)             │     Task 1 ⏱12m│
│ ＋ │ ≡ Timeline    │                                      │ ● Ben          │
│ ⇥  │ ◆ Decisions   │                                      │   └ Codex · idle│
│    │ ⑂ Trace       │                                      │────────────────│
│    │ ↻ Recovery    │                                      │ ACTIVITY       │
│    │ ✓ Verification│                                      │ 10:42 Asha     │
│    │ ☺ Members &   │                                      │ changed Dec 2… │
│    │   Agents      │                                      │ 10:42 Draft 1  │
│    │ ⚙ Settings    │                                      │ marked stale   │
│    │───────────────│                                      │ ...            │
│    │ Asha · owner  │                                      │                │
└────┴───────────────┴──────────────────────────────────────┴────────────────┘
 72px     240px                  flexible                        300px
```

### 2.1 Left rail (72 px)

> **(v2)** The rail shows **root rooms only** (`GET /api/rooms/tree` → `trees`). Child rooms live in the sidebar tree (§2.2). The amber/red dots aggregate the whole tree. **＋ Create room** gains an optional "Inside…" parent picker (only rooms where you're owner/mentor; greyed out at depth 3).
- One round icon per room (`GET /api/rooms`), showing the room's initials. The selected room has an indigo pill on the left edge. Show a small amber dot if `counts.stale > 0`, and a red dot if `counts.pending_approvals > 0`.
- **＋ Create room** opens a dialog asking for a name (`POST /api/rooms`), then switches to the new room.
- **⇥ Join with code** opens a dialog asking for an invite code (`POST /api/rooms/join`). Show "Code not found" on 404.
- Switching rooms closes the old WebSocket and opens the new one.

### 2.2 Room sidebar (240 px)

> **(v2)** Above the nav items, show the **room tree** of the current root: nested and collapsible, indented 12 px per level. Rooms you're a member of are normal. Ancestors you can only read show a 🔒 "read only" icon and open on their Memory screen. A "＋ child room" button appears on hover for owners/mentors. The nav gains **Memory** (after Decisions) and **Inbox** (promotions and memory proposals, with a count badge).
- Header: room name with a dropdown containing "Copy invite code" (shows `CAMPUS-7KQ2` with a copy button) and "Room settings".
- Nav items: **Board, Timeline, Decisions, Trace, Recovery, Verification, Members & Agents, Settings**. Each shows a count badge where useful: Board shows stale count (amber), Verification shows rejected submissions in the last 10 min (red), Recovery shows interrupted items.
- Footer: my name and room role, and a "Sign out" link that clears the session token.

### 2.3 Right panel (300 px, collapsible)

> **(v2)** Agent rows show the **harness and model** under the name ("Claude Code · claude-opus-5-5"), plus a live session line when `session.status == "running"`: the last `harness.progress` text, truncated, with a spinner. Show `harness.progress` in the activity feed only for the selected agent (it's chatty).
- **Online:** people (`presence.users`), each with their agents nested underneath. An agent row shows its badge, online dot, and either "idle" or `working on Task 1` with a lease countdown (`working_on.lease_expires_at`). Update from `presence.changed` and `task.heartbeat`.
- **Activity:** the live feed of the room's events, newest first, using `event.summary`. Skip `task.heartbeat` and `presence.changed`. Clicking an item navigates to its record. Keep the last 200.

### 2.4 Live data rules
- On entering a room, load the screen data via REST, then open `ws://.../ws/rooms/{id}?token=...&since_seq={latest_seq}`.
- Keep a single room store. Apply each `event` to it (or simply refetch the affected screen's REST endpoint, which is fine for the hackathon). Track `lastSeq`.
- On disconnect, reconnect with backoff (1s, 2s, 5s, max 10s) using `since_seq=lastSeq`. Show a thin amber bar saying "Reconnecting…" while disconnected.
- Never poll except for presence countdowns, which tick locally.

## 3. Sign in

- First visit: a centred card asking "What should we call you?" plus a **Continue** button (`POST /api/session`). Store the token.
- Under it: "Demo users: **Asha** · **Ben** · **Chen**" as buttons (`POST /api/session/demo`), so judges can be signed in with one click. Hide them if the call returns 404.
- After sign-in: if the user has rooms, open the first one; otherwise show an empty state with "Create a room" and "Join with an invite code".

## 4. Screens

### 4.1 Board (default view) — tests 1 and 3
`GET /api/rooms/{id}/board`

- Kanban columns in this order: **Open · In progress (claimed) · Needs approval (in_review) · Stale · Approved · Rejected**. Hide empty Stale/Rejected columns.
- **Task card:**
  - `Task 1` label (mono, muted) and the title
  - a role chip (`planner` / `reviewer`)
  - if claimed: the agent badge and lease countdown
  - if it has output: `Draft 1 · v2` pill and a status chip
  - if stale: an amber line `⚠ based on Decision 2 v1, now v2`
  - if approval pending: an indigo "Needs approval" button that opens the task detail at the approval section
- Mentors see **＋ New task** at the top (`POST /records` with `type: task`): title, description, role, and for reviewer tasks a "Review of" task picker.
- Cards move columns live on `task.claimed`, `submission.completed`, `record.stale` and `approval.decided`, with a brief highlight.

### 4.2 Task detail — tests 2, 3 and 4

> **(v2)** `based_on` pills from ancestor rooms show the room name: `Campus App Launch › Decision 2 · v2`. Approved outputs in a child room get a **Promote to parent** button (owner/mentor), which opens a small dialog with category (default `note`) and title. A `request_changes` review shows a banner on the reviewed task: "Reopened: changes requested by Ben's Codex".
`GET /api/records/{task_id}`. Open it as a wide drawer over the board, or as a full page. Either is fine.

Sections, top to bottom:
1. **Header:** `Task 1 · Write launch plan`, status chip, role chip, current claim (agent badge, countdown) or "Unclaimed".
2. **Brief:** the room brief, collapsed to 3 lines with "Show more". Show a revision pill.
3. **Latest output:** the current draft/review revision rendered as markdown. For reviews, show the verdict as a large chip (`approve` green / `request_changes` red) above the comments. Show `Draft 1 · v2 by <agent badge> · 10:47`.
4. **Based on:** a row of revision pills from `revision.based_on`. Pills with `is_current: false` are amber with a tooltip "Decision 2 is now v2". This is how a reviewer sees what the draft relied on.
5. **Cited sources:** a list with title, URL (opens in a new tab) or the first line of text, and its `Source 1` label.
6. **Approval** (if `approvals` has a pending one): a highlighted indigo box:
   - "Corrected work needs approval" (for `reason: redo_of_stale`) or "Needs approval".
   - A side-by-side diff of `previous_revision` → `revision` (a simple line diff is fine), with both revisions' `based_on` pills so the reviewer can check the citations moved to the new decision.
   - **Approve** (green) and **Reject** (red, requires a comment) buttons → `POST /api/approvals/{id}/decide`.
   - Disabled with a tooltip if I'm not allowed (API §0.4).
7. **Submissions:** each submission collapsed to one line (agent badge, time, status chip, `idempotency_key` in mono). Expanding it shows the 7-check checklist (section 4.7) and, if `resumed`, a "Resumed after interruption · attempt 2" tag.
8. **Revision history:** a timeline of the output's revisions and the task's revisions, each with author, time and based_on pills. Clicking one shows its content.
9. **Comments:** a thread with agent and user comments, plus a comment box (`POST /records/{id}/comments`).
10. **Evidence:** a "View trace" button that opens Trace for this task.

### 4.3 Decisions — test 4

> **(v2)** Inherited decisions (from ancestor rooms) are listed in their own group, "From Campus App Launch", read-only, with a link to edit them in their room. The **Stale impact** preview groups items by room using `by_room`: "1 output stale in Campus App Launch" and "**1 output stale in Launch Week** (child room)". Child-room items get a room chip and a tree icon.
`GET /api/rooms/{id}/records?type=brief,decision,source`

- Three tabs: **Decisions** (default), **Brief**, **Sources**.
- Each decision is a card: `Decision 2 · v2`, title, statement, rationale, "changed 3 min ago by Asha", and `dependents` count ("used by 2 outputs").
- **Edit** (mentors) opens an inline editor for statement and rationale, plus an optional "Why the change?" note.
  - While typing (debounced 400 ms), call `POST /records/{id}/revisions/preview` and show a **Stale impact** panel under the editor:
    - Amber list "These will be marked stale (2)": each item shows the label, title, task, the `path` as breadcrumb pills (`Decision 2 v1 → Draft 1 v1 → Review 2 v1`) and the agent who wrote it.
    - Green list "Unaffected — kept as is (1)": shows independent work being preserved, which matters for judging.
  - **Save as v2** → `POST /records/{id}/revisions`. Then show a toast "Decision 2 is now v2 · 2 items marked stale" with a "View on board" link.
- **History** on each card expands its revisions, with a before/after for each change.
- **＋ New decision / brief / source** for mentors.

### 4.4 Timeline — test 6
`GET /api/rooms/{id}/events?since_seq=0&limit=500`, then live.

- A dense, vertical list: `#seq` (mono) · time · actor badge · summary. Newest at the bottom, auto-scrolling unless the user scrolled up ("Jump to latest" button).
- Filters (chips): All, Tasks & claims, Submissions & checks, Decisions & stale, Approvals, People & agents.
- Colour the left edge by type: red for `submission.rejected` and `claim.expired`, amber for `record.stale` and `decision.changed`, green for `approval.decided (approved)` and `submission.completed`, indigo for the rest.
- Clicking an event expands its JSON `payload` (mono, collapsible) and links to the record.
- "Who owned each step": hovering a task label highlights all its events.

### 4.5 Trace — test 6

> **(v2)** Nodes from another room get a room chip, and cross-room edges are drawn dashed-indigo. New edge styles: `claimed_by` (thin indigo, revision → agent), `promoted_to` (thick green).
`GET /api/records/{record_id}/trace`

- A record picker at the top, defaulting to the most recently corrected task.
- A left-to-right graph (use React Flow or similar with a dagre layout):
  - **Columns:** people → decisions/sources → outputs. Revision nodes are cards (`Decision 2 v2`, title, status colour border). Superseded revisions (`is_current: false`) appear faded, connected by a dashed `supersedes` edge.
  - Agent nodes and user nodes are round avatars with their colour.
  - Edge styles: `based_on` solid, `cites` dotted, `supersedes` dashed grey, `authored_by` thin muted, `approved_by` green, `rejected_by` red.
- To the right of the graph, show the **Story** panel: the `story` list as a numbered narrative, with each step linking to its Timeline `seq`. This is the "trace one corrected task back to the teammate's decision" proof, so make it readable from across a room.

### 4.6 Recovery — test 5

> **(v2)** A second card type for **crashed harness sessions** (`kind: "harness_session"`): agent badge, harness and model, started/ended times, error, and the last progress text. A crashed session that held a claim shows "Lease will expire at …" or "Task released".
`GET /api/rooms/{id}/recovery`

- One card per item:
  - Header: task, agent badge, `idempotency_key` (mono), state chip (`interrupted` amber, `resumed` green, `duplicate_ignored` grey).
  - A horizontal mini-timeline from `timeline`: `saved → crashed → resumed → revision created → completed`, each with time and `#seq`.
  - Proof row, large: **"Applied exactly once ✓"** with `attempts: 2 · revisions created: 1 · applied_count: 1`. Show it in red if `revisions_created_for_key` > 1 (that would be a bug).
- Empty state: "No interrupted submissions. Run `scripts/crash_demo.py` to see one."
- Updates live on `submission.saved`, `agent.crashed`, `submission.resumed` and `submission.completed`.

### 4.7 Verification — the live heart of the demo
`GET /api/rooms/{id}/submissions?limit=50`, then live `verification.check` events.

- A stream of **submission cards**, newest on top. Each card:
  - Header: agent badge, `Task 1 · Write launch plan`, time, final status chip once known.
  - A vertical checklist of the 7 checks, in order: `claim_valid`, `permission`, `revisions_current`, `no_conflicting_edit`, `citations_present`, `sources_exist`, `content_schema`. Use readable names: "Holds the claim", "Allowed for role", "Based on current revisions", "No conflicting edit", "Cites sources", "Sources exist", "Content complete".
  - While running, pending checks show a spinner. Each `verification.check` event ticks one off: ✓ green with its `detail`, or ✗ red with its `detail` in bold. Skipped checks show a grey "skipped". Checks after a failure show "not run".
  - On `submission.rejected`, show a red footer with the reason, e.g. **"stale: based on Decision 2 v1, now v2"**. On `submission.completed`, show a green footer "Applied as Draft 1 v2" linking to it.
- A filter by agent (badges as toggle chips).
- This screen must look good on a projector: large text, generous spacing.

### 4.8 Members & Agents — tests 1 and 2

> **(v2)** The agents table adds **Harness**, **Model**, **Context** ("200k · markdown") and **Connection** (`ACP` / `MCP`) columns, with an edit (pencil) action for the profile (`PATCH …/agents/{id}`). The **Connect an agent** dialog adds a harness/model step, and its first tab is **baton-connect (recommended)**: the install line and the run command, each with a copy button. The v1 snippets remain as tabs labelled "Direct MCP (fallback)". An owner's own agents get a **Private workspace** link (§7.4).
`GET /members`, `GET /agents`

- **Members table:** avatar, name, role (owner/mentor/member), online dot, and their agents. The owner gets a role dropdown (member ⇄ mentor) on other rows.
- **Agents table:** badge, tool, role, owner, online, working on, last seen, and a "Revoke" action.
- **Invite box:** the invite code, large and copyable, plus "Share this code with teammates".
- **Connect an agent** (primary button) opens a dialog:
  1. Form: name (default "{my name}'s {tool}"), tool (Claude Code / Codex / Gemini CLI / Cursor / Other), role (planner / reviewer / observer, with one-line help for each).
  2. Submit → `POST /agents`. The dialog switches to **"Connect it"**:
     - A red-bordered "Copy this token now. It won't be shown again." showing the token with a copy button.
     - Tabs **Claude Code · Codex · Gemini CLI** (selected tool first), each with its snippet(s) from `config.snippets` in mono code blocks with copy buttons. For Codex, show both `config_toml` and the `env` line.
     - A collapsible "Paste into CLAUDE.md / AGENTS.md" block with `instructions_md`.
     - A live status line: "Waiting for the agent to connect…" that turns green "✓ Connected" on `agent.connected` for this agent.
- For an existing agent, "Show config" opens the same tabs from `GET /agents/{id}/config` (with `<BATON_TOKEN>` placeholders and a note that the token was shown at creation).

### 4.9 Settings
`PATCH /api/rooms/{id}/settings`. Owner and mentors only; members see it read-only.

- **Verification checks:** checks 1–4 are listed as "Always on" (locked). Checks 5–7 are toggles with one-line explanations.
- **Minimum sources per draft:** number input (0–10).
- **Claim lease:** minutes (1–120).
- **Require approval for all agent work:** toggle (redone stale work always needs approval; say so under the toggle).
- **Invite code:** read-only with a copy button.
- Saves immediately per field, showing a small "Saved" tick.

## 5. Empty, loading and error states

- **Loading:** skeleton rows, never a full-screen spinner.
- **API errors:** show `error.message` in a toast. 401 → back to sign-in. 403 → disable the control with the message as a tooltip.
- **Backend down** (`/health` fails): a full-width red banner saying "Can't reach Baton at {url}. Is `./start.sh` running?"

## 6. Demo-critical checklist for the frontend

Make sure these work before anything else:

1. Sign in as a demo user → land in "Campus App Launch".
2. The Board shows tasks moving live as Claude Code and Codex work.
3. The Verification screen ticks checks live, and a stale submission shows a red "stale: based on Decision 2 v1, now v2".
4. Decisions: editing Decision 2 shows the stale preview, and saving flips cards to amber on the Board.
5. Task detail: approve corrected work with a before/after diff.
6. Recovery shows "Applied exactly once ✓" after `crash_demo.py`.
7. Trace shows Draft v2 → Decision 2 v2 → Asha, with the story panel.
8. The Connect an agent dialog shows working snippets.

## 7. v2 screens (v2)

### 7.1 Room tree (v2)
- In the sidebar, under the room name:
  ```
  ▾ Campus App Launch          (member)
     ▸ Launch Week   ⚠1        (member, child)
  ```
- Clicking a room switches the main area and the WebSocket to that room. Keep the tree expansion state in `localStorage`.
- **Create child room** dialog: name, plus parent (prefilled). On `201`, select the new room. A `room.created` event in the parent's stream adds the child live for everyone who can see it.
- Status dots per node: amber for `counts.stale > 0`, red for pending approvals or promotions.

### 7.2 Memory screen (v2)
`GET /api/rooms/{id}/memory?include_ancestors=true`

- **Header:** a search box (full-text; Enter runs `?q=`), a tag filter, and two toggles: "Include inherited" (default on) and "Show expired".
- **Category tabs with counts:** All · Briefs · Decisions · Sources · Facts · Lessons · Glossary · Notes · **Pending** (agent proposals, mentors only).
- **Item card:**
  - label (mono), title, the body (3 lines, expandable), tags as chips
  - confidence as a small bar (hidden at 1.0)
  - an expiry countdown when `expires_at` is set
  - provenance: "added by Asha" / "proposed by Asha's Claude (sub …)" / "promoted from Launch Week › Draft 1 v2"
- **Inherited items:** a left border in the ancestor room's colour, a chip "from Campus App Launch", read-only (an "Open in Campus App Launch" link instead of Edit).
- **Mentors:** **＋ Add memory** (category, title, body or term+definition, tags, optional expiry), plus **Edit**. Editing a brief, decision or source shows the same stale-impact preview as §4.3.
- **Pending proposals:** Approve / Reject (reject needs a comment), using `POST /api/approvals/{id}/decide` (`kind: "memory"`).
- Updates live on `memory.added`, `memory.proposed`, `revision.created` and `approval.decided`.

### 7.3 Inbox (v2)
`GET /api/rooms/{id}/promotions` and `GET /api/rooms/{id}/approvals`

- **Promotions in:** each card shows the from-room chip, the child revision rendered, its `based_on` pills (with room names), the target category and title, and **Approve into this room** / **Reject**. On approval, show a toast "Added as Note 1" with a link to Memory.
- **Promotions out** (owner/mentor of a child): status of the room's requests.
- **Approvals:** the v1 approvals list (outputs and memory proposals), for one place to work through.

### 7.4 Agent detail: profile, live session, private workspace (v2)
- **Profile:** harness, model, context window, format, connection, all editable by the owner or mentors.
- **Live session:** the running harness session's progress stream (`harness.progress`, ephemeral), start time, the task it's on, and a "Copy restart command" button.
- **Context packet preview:** `GET …/context-packet?task=` rendered in a mono panel, with "used / budget tokens" and any trimmed sections. It shows exactly what the agent sees.
- **Private workspace:** visible **only to the agent's owner** (`GET /api/agents/{id}/private`). List the keys, kind (draft/note), content and expiry. Read-only in the UI. Never show it to other members; the API returns 404 to them.

### 7.5 Demo-critical additions (v2)
1. The sidebar tree shows Campus App Launch › Launch Week.
2. The decision preview in the parent shows "1 output stale in Launch Week".
3. After saving, Launch Week's board turns amber live, through its own WebSocket stream.
4. The Connect dialog's baton-connect tab, and a live harness session line in the right panel.
5. The Memory screen with inherited items marked.
