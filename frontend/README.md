# Baton Frontend

Modern, dark developer-tool UI for **Baton** — multi-agent coordination for AI coding tools (Claude Code, Codex, Gemini CLI).

Built with **Vite + React + TypeScript + Tailwind CSS**, **TanStack Query**, **React Flow**, **Lucide Icons**, and **Framer Motion**.

---

## Quick Start

### 1. Install dependencies
```bash
npm install
```

### 2. Start the dev server
```bash
npm run dev
```

The app runs at [http://localhost:5173](http://localhost:5173).

---

## Environment Variables

Configure via `.env` in the `frontend/` folder:

| Variable | Default | Description |
|---|---|---|
| `VITE_API_URL` | `http://localhost:8000` | Base URL of the Baton FastAPI backend |
| `VITE_MOCK` | `false` | Force mock mode with simulated events |

### Mock Mode Fallback
- If the backend is down or unreachable, the frontend **automatically falls back to realistic mock mode**.
- An indicator badge **`MOCK`** is displayed at the bottom of the left rail when mock mode is active.
- To explicitly force mock mode for offline demonstration:
  ```bash
  VITE_MOCK=true npm run dev
  ```

---

## 3-Minute Hackathon Demo Flow

1. **Sign In**:
   - Click **Asha (owner)** on the welcome screen.
   - You land directly into **Campus App Launch** (`CAMPUS-7KQ2`).

2. **Members & Agents (Judges Test 1 & 2)**:
   - View human teammates (Asha, Ben, Chen) and registered agents (Asha's Claude, Ben's Codex).
   - Click **Connect an agent** to inspect ready-to-paste MCP configurations for Claude Code, Codex, and Gemini CLI.

3. **Decisions & Stale Propagation (Judges Test 4)**:
   - Go to **Decisions**. Click **Edit** on Decision 2 (*Launch date*).
   - Change date from 10 January to 15 January.
   - **Stale Preview**: Notice live notice: *"Saving this will mark 1 output stale; 3 stay approved"*.
   - Click **Save as v2**:
     - An amber banner appears across the room.
     - On the **Board**, Task 1 (*Write launch plan*) pulses amber live.

4. **Live Verification (Judges Test 3 & 4)**:
   - Open **Verification**.
   - As agents submit, the 7 checks (`claim_valid`, `permission`, `revisions_current`, `no_conflicting_edit`, `citations_present`, `sources_exist`, `content_schema`) tick live with explicit reasons.
   - Stale work triggers clear rejection: *"stale: based on Decision 2 v1, now v2"*.

5. **Crash Recovery (Judges Test 5)**:
   - Open **Recovery**.
   - Review interrupted agent submissions resuming with identical idempotency keys, showing the verified **"Applied once ✓"** badge.

6. **Evidence Trace (Judges Test 6)**:
   - Open **Trace**.
   - See an interactive, left-to-right graph linking the final output back to decisions, sources, and teammate approvals.

---

## Architecture & Code Structure

```
frontend/
├── src/
│   ├── api/
│   │   ├── types.ts          # Complete TypeScript types matching API_CONTRACT.md
│   │   ├── client.ts         # REST API client with auto-mock fallback
│   │   └── useWebSocket.ts   # Resilient WebSocket connection with since_seq resume
│   ├── components/
│   │   ├── common/           # AgentBadge, StatusChip, RevisionPill
│   │   └── layout/           # LeftRail, RoomSidebar, RightPanel, StaleBanner
│   ├── views/
│   │   ├── BoardView.tsx        # Tasks table with status & agent filters
│   │   ├── TaskDetailPanel.tsx  # Side panel with diff, citations, approvals
│   │   ├── DecisionsView.tsx    # Single source of truth with stale preview
│   │   ├── VerificationView.tsx # Live checklist of the 7 deterministic checks
│   │   ├── TraceView.tsx        # React Flow provenance graph & story
│   │   ├── RecoveryView.tsx     # Crash recovery & idempotency proof
│   │   ├── TimelineView.tsx     # Audit feed filterable by actor & event type
│   │   ├── MembersView.tsx      # Team members & "Connect an agent" dialog
│   │   ├── SettingsView.tsx     # Room settings & check toggles
│   │   └── WelcomeModal.tsx     # Fast-track demo sign-in & room join
│   ├── mocks/
│   │   └── mockData.ts       # Realistic mock data matching API contract
│   └── lib/
│       └── utils.ts          # Styling, date formatting, and badge helpers
```

---

## Production Build
```bash
npm run build
npm run preview
```
