# Baton

**A desktop workspace where several AI models work on one project together.** Claude, ChatGPT, DeepSeek and Gemini (plus tools like Antigravity, Claude Code and Codex) share one project record: a brief, decisions, sources and tasks. Each AI claims a task, reads the same record, and submits its work. Every submission passes three checks before it is applied, and a change to a decision automatically flags only the work that depended on it.

Everything runs on your computer. There is no server, no Docker and no account: one app, one SQLite file.

## Run it

You need **macOS**, **Node 20+** and **[uv](https://docs.astral.sh/uv/)** (`curl -LsSf https://astral.sh/uv/install.sh | sh`).

```bash
cd desktop
npm install            # once
npm run ui             # builds the interface (once, and after UI changes)
npm start              # opens the Baton window
```

The first launch installs Baton's Python packages (about a minute). After that it opens in seconds. You are signed in automatically and land in **My Project**, a starter project with two tasks and two offline demo agents, so you can press **Run all open tasks** right away.

To get a double-clickable app:

```bash
cd desktop && npm run pack      # creates desktop/dist/mac-arm64/Baton.app
```

Your data lives in `~/Library/Application Support/Baton/` (`data/baton.db`, `logs/`). Help → *Open data folder* shows it.

## One roadmap, every AI in sync (the main feature)

Baton is a local hub that keeps Claude, ChatGPT (Codex), Antigravity and Gemini on the same page about one project, on this Mac only.

1. **Roadmap**: make a plan anywhere (ChatGPT, Codex...), paste it in or let Codex save it. Each task has one owner tool, dependencies and a folder.
2. **Hooks**: Claude Code, Codex and Antigravity run a tiny script (`baton_hook.py`) by themselves on every edit and prompt. It reports the activity to Baton and prints a short briefing back into the tool when something changed. Only work inside your project folder counts.
3. **Live**: one card per tool showing what it is doing now, plus a feed of everything that happened.
4. **Setup**: press **Connect all tools**. Then restart each tool once. In Codex, type `/hooks` once and trust the Baton hooks.

Open Claude or Antigravity, say "continue", and it already knows its task and what the others built. The old chat and scripted demos live under **Demo**.

## Chat with several AIs in one place

On the **Context** screen, pick **Claude, ChatGPT, Gemini or Antigravity** and type a message. No setup: Baton uses the Claude, ChatGPT (Codex) and Antigravity apps already signed in on your computer. An API key under **Tools & keys** is optional and, if added, is used instead (DeepSeek only works with a key). Every AI you ask reads the same shared memory first, so you can ask Claude, then ChatGPT, then Gemini and nobody needs the project explained again. Each answer is saved to the shared memory, so tools such as Claude Code, Codex and Antigravity (connected over MCP) see it too, and the other way round.

The project **Live demo: Jaipur trip** has five one-click scripted demos of the same flow (trip plan, food route, forts and photos, bazaars and crafts, palace stay), each about 20 seconds.

## What the AIs know

Baton ships with the Jaipur Journals site (articles, places, itineraries, hotels) plus Wikipedia and Wikivoyage background on Jaipur, about 80 documents. Before each answer, Baton finds the documents that match the question and gives them to the AI. Add any website from the Context screen, or paste a link in a chat message. Tools connected over MCP can call `search_knowledge`.

## Switch between AI tools without re-explaining

Baton connects Claude Code, Codex (ChatGPT app), Antigravity and Gemini CLI over MCP and gives them one shared memory.

- Each tool calls **`get_handoff`** when a conversation starts: the goal, the binding decisions, the tasks and results so far, and what the *other* tools did and suggest next.
- Each tool calls **`save_context`** when it finishes a chunk of work or you say you're switching: a summary, next steps and files touched.
- You can add your own notes too. Everything shows live on the **Context** screen.

To wire your tools on this computer (adds only the `baton` entry to each tool's MCP config plus a short standing instruction, after making a `.baton-backup` copy):

```bash
cd backend && BATON_DATA_DIR="$HOME/Library/Application Support/Baton/data" uv run --python 3.12 python -m app.tool_connect
```

Then restart each tool once so it loads the new config. Baton must be running (the desktop app) for the tools to reach it.

## Use several AIs

1. **AI Models** (left menu): paste an API key for each AI you want, press **Test**, pick a model. Keys stay on this computer in a private file and are never shown again.
2. **Members & Agents → Connect an Agent**: choose *Which AI?*, a role (planner writes drafts, reviewer reviews them) and a name.
3. **Board**: press **Run** on a task, or **Run all open tasks**. Baton gives the AI the project record, then submits its answer through the checks.

| AI | How it joins | Needs |
|---|---|---|
| Claude (Anthropic) | Baton calls the API | API key |
| ChatGPT (OpenAI) | Baton calls the API | API key |
| DeepSeek | Baton calls the API | API key |
| Gemini (Google) | Baton calls the API | API key |
| Demo model | Runs offline on your computer | nothing |
| Antigravity, Claude Code, Codex, Gemini CLI, Cursor | They connect to Baton over MCP and work tasks themselves | the config Baton shows in *Connect an Agent* |

## How it works

- **One shared record.** Briefs, decisions, sources, tasks, drafts and reviews. Nothing is overwritten: every edit is a new revision.
- **Claims.** An agent claims a task for 15 minutes; nobody else can work on it, and an abandoned claim expires.
- **Three checks** on every submission:
  1. *Holds the claim*: only the claiming agent can submit.
  2. *Based on current revisions*: work built on an outdated decision is rejected with `stale: based on Decision 2 v1, now v2`.
  3. *Content complete*: the output has the fields its type needs, and every cited source exists.
- **Stale flags.** Change a decision and only the work built on it turns amber. Independent work stays green. A preview shows the impact before you save, and corrected work waits for your approval.
- **Exactly once.** A retried submission is never applied twice, even after a crash.
- **Evidence.** Every step is logged with who did it, when and from which revisions (Timeline, Trace, Recovery).

## Repository

| Path | What |
|---|---|
| `desktop/` | The Electron app: starts the backend and shows the UI |
| `backend/` | FastAPI app: REST API, WebSocket, MCP server, AI providers, agent runner, tests |
| `frontend/` | React + Vite + Tailwind interface |
| `agent-configs/` | MCP config templates for tools that connect themselves |
| `docs/` | `API_CONTRACT.md`, `UI_SPEC.md`, `ARCHITECTURE.md` |

## Develop

```bash
cd backend && uv run --python 3.12 --extra dev pytest -q      # 85 tests, no network needed
cd backend && BATON_LOCAL_MODE=1 BATON_STATIC_DIR=../frontend/dist uv run --python 3.12 uvicorn app.main:app --port 8765
cd frontend && npm run dev                                     # UI with hot reload against a backend on :8000
```

Settings come from environment variables (see `.env.example`).
