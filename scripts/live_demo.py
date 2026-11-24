"""Trigger the demo's live moments one at a time, while the UI is open.

    ./scripts/live_demo.sh handoff    # Claude Code drafts Task 1, then Codex reviews it (Task 2)
    ./scripts/live_demo.sh decision   # Asha changes Decision 2 -> the plan and review go stale
    ./scripts/live_demo.sh redo       # (optional) Claude resubmits: old decision rejected, corrected plan waits for approval
    ./scripts/live_demo.sh crash      # an agent crashes after `saved`, retries, applied exactly once

Scripted stand-ins play the agents over the real MCP endpoint with the seeded tokens.
Start from a fresh room: ./reset-demo.sh -y
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from crash_demo import call as mcp  # noqa: E402
from demo_run import DEMO_FILE, Rest  # noqa: E402

B, R, G, Y, D, X = "\033[1m", "\033[31m", "\033[32m", "\033[33m", "\033[2m", "\033[0m"


def did(text: str) -> None:
    print(f"  {G}✔{X} {text}")


def note(text: str) -> None:
    print(f"  {D}→ {text}{X}")


def ctx_ids(ctx: dict) -> list[str]:
    return [ctx["brief"]["revision_id"]] + [d["revision_id"] for d in ctx["decisions"]]


def handoff(demo, tok, asha) -> None:
    print(f"{B}Live moment: handoff{X}")
    claude, codex = tok["claude_code"], tok["codex"]
    ctx = mcp(claude, "get_room_context")
    mcp(claude, "claim_task", {"task_id": "Task 1"})
    did("Asha's Claude (claude_code) claimed Task 1 \"Write launch plan\"")
    cal = next(s for s in ctx["sources"] if "calendar" in s["title"].lower())
    out = mcp(claude, "submit_result", {
        "task_id": "Task 1", "title": "Launch plan",
        "content": {"body": "## Launch plan\n- 10 Jan: launch on iOS + Android (Decisions 1, 2)\n- Launch week: 12 volunteers, 2 shifts (Decision 3)\n- Channels: student email, union socials, info stands"},
        "based_on": ctx_ids(ctx), "sources": [cal["source_id"]], "idempotency_key": "live-claude-task1-1",
    })
    if out["status"] != "completed":
        sys.exit(f"{R}Claude's submission: {out['message']}{X}")
    did(f"Claude submitted: 7/7 checks passed → {out['result']['label']} v{out['result']['revision']} ({out['result']['status']})")

    claimed = mcp(codex, "claim_task", {"task_id": "Task 2"})
    under = claimed["inputs"]["under_review"]
    did(f"Ben's Codex (codex) claimed Task 2 and received {under['label']} v{under['revision']} with its based_on "
        f"({', '.join(b['label'] for b in under['based_on'])}) and sources — no chat copied")
    mcp(codex, "comment", {"record_id": under["label"], "text": "Launch date falls inside exams (Source 1: exams 2-12 Jan)."})
    did("Codex commented on the draft: the launch date clashes with exams")
    rv = mcp(codex, "submit_result", {
        "task_id": "Task 2",
        "content": {"verdict": "request_changes", "comments": "10 Jan is during exams per Source 1; suggest launching after 12 Jan."},
        "based_on": [ctx["brief"]["revision_id"], under["revision_id"]], "idempotency_key": "live-codex-task2-1",
    })
    did(f"Codex submitted its review: 7/7 checks → {rv['result']['label']} (request_changes)")
    note("In the UI: Board, Verification and Task 1 detail. You can approve Draft 1 from Task 1 now.")


def decision(demo, tok, asha) -> None:
    print(f"{B}Live moment: change Decision 2{X}")
    room = demo["room_id"]
    dec2 = next(r for r in asha.get(f"/api/rooms/{room}/records", params={"type": "decision"}).json()["records"] if r["number"] == 2)
    if dec2["current_revision"] != 1:
        sys.exit(f"{Y}Decision 2 is already v{dec2['current_revision']}. Run ./reset-demo.sh -y to start over.{X}")
    body = {"content": {"statement": "We launch on 15 January.", "rationale": "Exams end 12 January (Source 1)."},
            "note": "Codex flagged the exam clash."}
    prev = asha.post(f"/api/records/{dec2['id']}/revisions/preview", body).json()
    did("Preview: would go stale → " + (", ".join(f"{s['label']} ({s['reason']})" for s in prev["would_go_stale"]) or "nothing"))
    did("Preview: unaffected → " + (", ".join(f"{u['label']} {u['title']}" for u in prev["unaffected"]) or "nothing"))
    saved = asha.post(f"/api/records/{dec2['id']}/revisions", body).json()
    did(f"Asha saved Decision 2 v{saved['revision']['number']}: \"We launch on 15 January.\"")
    for s in saved["stale"]:
        did(f"{s['label']} ({s['task_label']}) marked stale: {s['reason']}")
    note("In the UI: the Board turns amber for Tasks 1 and 2; Task 3 (rota) stays green.")


def redo(demo, tok, asha) -> None:
    print(f"{B}Live moment: redo the stale plan{X}")
    claude = tok["claude_code"]
    mcp(claude, "claim_task", {"task_id": "Task 1"})
    did("Asha's Claude re-claimed Task 1 (redo of stale work)")
    old_ctx_ids = None
    ctx = mcp(claude, "get_room_context")
    rec = mcp(claude, "read_record", {"record_id": "Decision 2", "revision": 1})
    old_ctx_ids = [ctx["brief"]["revision_id"]] + [rec["revision_id"] if d["label"] == "Decision 2" else d["revision_id"] for d in ctx["decisions"]]
    cal = next(s for s in ctx["sources"] if "calendar" in s["title"].lower())
    bad = mcp(claude, "submit_result", {"task_id": "Task 1", "content": {"body": "plan"}, "based_on": old_ctx_ids,
                                        "sources": [cal["source_id"]], "idempotency_key": "live-claude-task1-2"})
    did(f"Submit on the OLD decision → {R}{bad['status']}{X}: {bad['message']}")
    good = mcp(claude, "submit_result", {
        "task_id": "Task 1", "title": "Launch plan",
        "content": {"body": "## Launch plan (v2)\n- 15 Jan: launch on iOS + Android, right after exams (Decisions 1, 2; Source 1)\n- Launch week: 12 volunteers, 2 shifts (Decision 3)"},
        "based_on": ctx_ids(ctx), "sources": [cal["source_id"]], "idempotency_key": "live-claude-task1-3",
    })
    did(f"Corrected plan → {good['result']['label']} v{good['result']['revision']} ({good['result']['status']}), waiting for human approval")
    note("In the UI: Task 1 → compare based_on pills (v1 amber, v2 green) → Approve.")


def crash(demo, tok, asha) -> None:
    print(f"{B}Live moment: crash and resume{X}")
    subprocess.run([sys.executable, str(Path(__file__).resolve().parent / "crash_demo.py"), "--pause", "6"], check=False)
    note("In the UI: Recovery shows interrupted → resumed → Applied exactly once.")


STEPS = {"handoff": handoff, "decision": decision, "redo": redo, "crash": crash}


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in STEPS:
        sys.exit(f"usage: live_demo.sh {{{'|'.join(STEPS)}}}")
    demo = json.loads(DEMO_FILE.read_text())
    tok = {a["tool"]: a["token"] for a in demo["agents"]}
    try:
        STEPS[sys.argv[1]](demo, tok, Rest("Asha"))
    except RuntimeError as e:
        sys.exit(f"{R}{e}{X}\n{Y}Tip: run the moments in order (handoff, decision, redo, crash) after ./reset-demo.sh -y{X}")


if __name__ == "__main__":
    main()
