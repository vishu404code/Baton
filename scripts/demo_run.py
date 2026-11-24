"""Autopilot: play the whole 3-minute demo (docs/DEMO.md) through Baton's real MCP and REST
endpoints, and check all six judging tests. Scripted stand-ins play Claude Code and Codex
using the seeded agents' tokens, so this needs no AI accounts. Use it to rehearse, as a
backup on stage, or to prove the stack end to end.

    ./reset-demo.sh -y && docker compose exec backend python scripts/demo_run.py [--pause 1.5]

Exits non-zero if any check fails.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from crash_demo import call as mcp  # noqa: E402  (same MCP client helper)

API = os.environ.get("BATON_INTERNAL_API_URL", "http://localhost:8000")
DEMO_FILE = Path("/app/.baton/demo.json" if Path("/app").exists() else ".baton/demo.json")
B, R, G, Y, D, X = "\033[1m", "\033[31m", "\033[32m", "\033[33m", "\033[2m", "\033[0m"

failures: list[str] = []
PAUSE = 0.0


def section(title: str, test: str) -> None:
    print(f"\n{B}━━ {title}{X}  {D}({test}){X}")
    time.sleep(PAUSE)


def check(ok: bool, text: str) -> None:
    print(f"  {G + '✔' if ok else R + '✘'}{X} {text}")
    if not ok:
        failures.append(text)


def say(text: str) -> None:
    print(f"  {D}·{X} {text}")


class Rest:
    def __init__(self, name: str):
        r = httpx.post(f"{API}/api/session/demo", json={"display_name": name})
        r.raise_for_status()
        self.h = {"Authorization": f"Bearer {r.json()['token']}"}

    def get(self, path, **kw):
        return httpx.get(f"{API}{path}", headers=self.h, timeout=30, **kw)

    def post(self, path, body):
        return httpx.post(f"{API}{path}", headers=self.h, json=body, timeout=30)


def tool_error(token, tool, args) -> str | None:
    try:
        mcp(token, tool, args)
        return None
    except RuntimeError as e:
        return str(e)


def main() -> None:
    global PAUSE
    p = argparse.ArgumentParser()
    p.add_argument("--pause", type=float, default=0.0, help="seconds to pause between sections (for presenting)")
    PAUSE = p.parse_args().pause

    demo = json.loads(DEMO_FILE.read_text())
    room = demo["room_id"]
    tok = {a["tool"]: a["token"] for a in demo["agents"]}
    claude, codex, gemini = tok["claude_code"], tok["codex"], tok["gemini_cli"]
    asha, ben = Rest("Asha"), Rest("Ben")

    board = {t["task"]["label"]: t for t in asha.get(f"/api/rooms/{room}/board").json()["tasks"]}
    if board["Task 1"]["task"]["status"] != "open":
        sys.exit(f"{R}The demo room isn't fresh (Task 1 is {board['Task 1']['task']['status']}). Run ./reset-demo.sh -y first.{X}")

    print(f"{B}Baton demo autopilot{X}  room={demo['room_name']}  invite={demo['invite_code']}")

    # ── Test 1 & 2 ────────────────────────────────────────────────────────────────────
    section("Two different tools, one team record", "tests 1 & 2")
    c_ctx, x_ctx = mcp(claude, "get_room_context"), mcp(codex, "get_room_context")
    check(c_ctx["me"]["tool"] == "claude_code" and x_ctx["me"]["tool"] == "codex", "Claude Code and Codex are both connected to the same room")
    check(c_ctx["decisions"] == x_ctx["decisions"], f"Both read the same {len(c_ctx['decisions'])} decisions, brief and sources")
    err = tool_error(codex, "claim_task", {"task_id": "Task 1"})
    check(bool(err) and "needs a planner" in err, f"Permission enforced via the Codex adapter: \"{err}\"")
    dec2 = next(d for d in c_ctx["decisions"] if d["label"] == "Decision 2")
    r = ben.post(f"/api/records/{dec2['record_id']}/revisions", {"content": {"statement": "x"}})
    check(r.status_code == 403, f"Permission enforced for people: Ben (member) can't edit Decision 2 → {r.status_code}")

    # ── Test 3 ────────────────────────────────────────────────────────────────────────
    section("Handoff: Claude Code drafts, Codex reviews", "test 3")
    mcp(claude, "claim_task", {"task_id": "Task 1"})
    based_on = [c_ctx["brief"]["revision_id"]] + [d["revision_id"] for d in c_ctx["decisions"]]
    cal = next(s for s in c_ctx["sources"] if "calendar" in s["title"].lower())
    out = mcp(claude, "submit_result", {
        "task_id": "Task 1", "title": "Launch plan",
        "content": {"body": "## Launch plan\n- 10 Jan: launch on iOS + Android (Decisions 1, 2)\n- Launch week: 12 volunteers, 2 shifts (Decision 3)\n- Channels: student email, union socials, info stands"},
        "based_on": based_on, "sources": [cal["source_id"]], "idempotency_key": "demo-claude-task1-1",
    })
    check(out["status"] == "completed" and all(c["passed"] for c in out["checks"]), f"Claude's draft passed all 7 checks → {out['result']['label']} v{out['result']['revision']} ({out['result']['status']})")
    approval = asha.get(f"/api/rooms/{room}/approvals").json()["approvals"][0]
    asha.post(f"/api/approvals/{approval['id']}/decide", {"decision": "approved", "comment": "Good first plan."})
    say("Asha approves Draft 1 v1")

    claimed = mcp(codex, "claim_task", {"task_id": "Task 2"})
    under = claimed["inputs"]["under_review"]
    check(under["label"] == "Draft 1" and "10 Jan" in under["content"]["body"], "Codex recovered the draft from Baton (no chat history copied)")
    check({b["label"] for b in under["based_on"]} >= {"Decision 2", "Brief 1"} and under["sources"][0]["label"] == cal["label"],
          f"…with its based_on links ({', '.join(b['label'] + ' v' + str(b['number']) for b in under['based_on'])}) and cited {under['sources'][0]['label']}")
    mcp(codex, "comment", {"record_id": "Draft 1", "text": "Launch date falls inside exams (Source 1: exams 2-12 Jan)."})
    rv = mcp(codex, "submit_result", {
        "task_id": "Task 2", "content": {"verdict": "request_changes", "comments": "10 Jan is during exams per Source 1; suggest launching after 12 Jan."},
        "based_on": [c_ctx["brief"]["revision_id"], under["revision_id"]], "idempotency_key": "demo-codex-task2-1",
    })
    check(rv["status"] == "completed", f"Codex's review accepted → {rv['result']['label']} (request_changes)")

    # ── Test 4 ────────────────────────────────────────────────────────────────────────
    section("A decision changes mid-run", "test 4")
    new = {"content": {"statement": "We launch on 15 January.", "rationale": "Exams end 12 January (Source 1)."}, "note": "Codex flagged the exam clash."}
    prev = asha.post(f"/api/records/{dec2['record_id']}/revisions/preview", new).json()
    would = {s["label"]: s for s in prev["would_go_stale"]}
    check(set(would) == {"Draft 1", "Review 2"}, f"Preview: would go stale → {', '.join(would)}")
    check(would["Review 2"]["path"] == ["Decision 2 v1", "Draft 1 v1", "Review 2 v1"], "Preview shows the transitive path Decision 2 v1 → Draft 1 v1 → Review 2 v1")
    check([u["label"] for u in prev["unaffected"]] == ["Draft 3"], "Preview: independent work (Draft 3, volunteer rota) is unaffected")
    saved = asha.post(f"/api/records/{dec2['record_id']}/revisions", new).json()
    check(saved["revision"]["number"] == 2 and len(saved["stale"]) == 2, "Asha saves Decision 2 v2 → 2 outputs flagged stale")
    board = {t["task"]["label"]: t for t in asha.get(f"/api/rooms/{room}/board").json()["tasks"]}
    check(board["Task 1"]["stale_reason"] == "based on Decision 2 v1, now v2", f"Board: Task 1 stale — \"{board['Task 1']['stale_reason']}\"")
    check(board["Task 3"]["task"]["status"] == "approved", "Board: Task 3 (rota) still approved — independent work preserved")

    mcp(claude, "claim_task", {"task_id": "Task 1"})
    stale_try = mcp(claude, "submit_result", {
        "task_id": "Task 1", "content": {"body": "plan"}, "based_on": based_on, "sources": [cal["source_id"]], "idempotency_key": "demo-claude-task1-2",
    })
    check(stale_try["status"] == "rejected" and "stale: based on Decision 2 v1, now v2" in stale_try["message"], f"Resubmitting on the old decision is rejected: \"{stale_try['message'][:70]}…\"")
    ctx2 = mcp(claude, "get_room_context")
    based_on2 = [ctx2["brief"]["revision_id"]] + [d["revision_id"] for d in ctx2["decisions"]]
    redo = mcp(claude, "submit_result", {
        "task_id": "Task 1", "title": "Launch plan",
        "content": {"body": "## Launch plan (v2)\n- 15 Jan: launch on iOS + Android, right after exams (Decisions 1, 2; Source 1)\n- Launch week: 12 volunteers, 2 shifts (Decision 3)\n- Channels: student email, union socials, info stands"},
        "based_on": based_on2, "sources": [cal["source_id"]], "idempotency_key": "demo-claude-task1-3",
    })
    check(redo["status"] == "completed" and redo["result"]["status"] == "in_review", f"Corrected draft → {redo['result']['label']} v{redo['result']['revision']}, waiting for human approval")

    pending = ben.get(f"/api/rooms/{room}/approvals").json()["approvals"][0]
    check(pending["reason"] == "redo_of_stale", "Approval reason: redo_of_stale (corrected work always needs a human)")
    cur = {b["label"]: b["is_current"] for b in pending["revision"]["based_on"]}
    old = {b["label"]: b["is_current"] for b in pending["previous_revision"]["based_on"]}
    check(cur.get("Decision 2") is True and old.get("Decision 2") is False, "Ben reviews the citations: v2 uses current Decision 2, v1 used the outdated one")
    r = ben.post(f"/api/approvals/{pending['id']}/decide", {"decision": "approved", "comment": "Dates now match Decision 2 v2."})
    check(r.status_code == 200 and r.json()["record"]["status"] == "approved", "Ben approves the correction → Draft 1 v2 approved")

    # ── Test 5 ────────────────────────────────────────────────────────────────────────
    section("Crash after save, resume, applied once", "test 5")
    key = "demo-gemini-task4-1"
    import uuid as _uuid

    sys.path.insert(0, "/app")
    from sqlalchemy import func, select

    from app.db import SessionLocal
    from app.models import Agent, Revision, Submission
    from app.services import submissions as sub_svc

    g_ctx = mcp(gemini, "get_room_context")
    mcp(gemini, "claim_task", {"task_id": "Task 4"})
    g_based = [g_ctx["brief"]["revision_id"]] + [d["revision_id"] for d in g_ctx["decisions"]]
    survey = next(s for s in g_ctx["sources"] if "survey" in s["title"].lower())
    faq = {"body": "## Help-desk FAQ\n**When?** 15 January (Decision 2). **Which phones?** iOS and Android (Decision 1)."}
    gem_id = next(a["id"] for a in demo["agents"] if a["tool"] == "gemini_cli")
    with SessionLocal() as db:
        agent = db.get(Agent, _uuid.UUID(gem_id))
        try:
            sub_svc.submit(db, agent, "Task 4", faq, g_based, [survey["source_id"]], key, "Help-desk FAQ", crash_after_save=True)
        except sub_svc.SimulatedCrash:
            sub_svc.record_crash(db, agent, key)
    rec = asha.get(f"/api/rooms/{room}/recovery").json()["items"][0]
    check(rec["state"] == "interrupted" and rec["revisions_created_for_key"] == 0, "Chen's Gemini crashed after `saved`: Recovery shows it interrupted, nothing applied")
    res = mcp(gemini, "submit_result", {"task_id": "Task 4", "content": faq, "based_on": g_based, "sources": [survey["source_id"]], "idempotency_key": key})
    check(res["resumed"] is True and res["status"] == "completed", f"Retry with the same key resumes it: \"{res['message']}\"")
    mcp(gemini, "submit_result", {"task_id": "Task 4", "content": faq, "based_on": g_based, "sources": [], "idempotency_key": key})
    with SessionLocal() as db:
        n = db.execute(select(func.count()).select_from(Revision).join(Submission, Submission.id == Revision.submission_id).where(Submission.idempotency_key == key)).scalar_one()
    rec = asha.get(f"/api/rooms/{room}/recovery").json()["items"][0]
    check(n == 1 and rec["applied_count"] == 1 and rec["attempts"] == 3, f"Proof from the database: 3 attempts, {n} revision, applied exactly once")

    # ── Test 6 ────────────────────────────────────────────────────────────────────────
    section("Evidence: who, when, which revision; trace the correction", "test 6")
    task1_id = board["Task 1"]["task"]["id"]
    t = asha.get(f"/api/records/{task1_id}/trace").json()
    nodes = {n["id"]: n for n in t["nodes"]}
    edges = {(nodes[e["from"]]["label"], nodes[e["to"]]["label"], e["kind"]) for e in t["edges"]}
    check(("Draft 1 v2", "Decision 2 v2", "based_on") in edges, "Trace: Draft 1 v2 → based on Decision 2 v2")
    check(("Decision 2 v2", "Asha", "authored_by") in edges, "Trace: Decision 2 v2 → authored by Asha (the teammate's decision)")
    check(("Draft 1 v2", "Ben", "approved_by") in edges and ("Asha's Claude", "Asha", "owned_by") in edges, "Trace: approved by Ben; written by Asha's Claude")
    for s in t["story"][-6:]:
        say(f"#{s['seq']} {s['text'][:96]}")
    ev = asha.get(f"/api/rooms/{room}/events", params={"types": "task.claimed,revision.created", "limit": 500}).json()["events"]
    owned = [e for e in ev if e["actor"]["kind"] == "agent"]
    check(len(owned) >= 6 and all(e["seq"] and e["created_at"] for e in owned), f"Timeline: {len(owned)} agent steps, each with owner, time and seq")

    print()
    if failures:
        print(f"{R + B}✘ {len(failures)} check(s) failed{X}")
        sys.exit(1)
    print(f"{G + B}✔ All six judging tests demonstrated{X}")


if __name__ == "__main__":
    main()
