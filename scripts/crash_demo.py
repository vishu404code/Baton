"""Crash-recovery demo (judging test 5): an agent's submission is saved, the agent crashes
before it is applied, then it retries with the SAME idempotency key. Baton finishes the
interrupted submission exactly once; a further retry changes nothing.

Run after ./start.sh (inside the backend container):
    docker compose exec backend python scripts/crash_demo.py [--pause 8]

Uses the seeded agent "Chen's Gemini" (planner) and Task 4 "Write help-desk FAQ"
(or a fresh copy of that task if Task 4 was already done).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
sys.path.insert(0, "/app")

from sqlalchemy import func, select  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.models import Agent, Record, Revision, Room, Submission, User  # noqa: E402
from app.serializers import actor_user  # noqa: E402
from app.services import ledger  # noqa: E402
from app.services import submissions as sub_svc  # noqa: E402
from app.services.events import append_event  # noqa: E402

DEMO_FILE = Path("/app/.baton/demo.json" if Path("/app").exists() else ".baton/demo.json")
MCP_URL = os.environ.get("BATON_INTERNAL_MCP_URL", "http://localhost:8000/mcp")
FAQ = """## Help-desk FAQ: campus app

**When does the app launch?** On the date in Decision 2.
**Which phones?** iOS and Android from day one; no web version at launch (Decision 1).
**Who can help me at launch?** Student volunteers at the info stands all launch week (Decision 3).
**Why an app?** 92% of students own a smartphone (Source 2)."""

B, R, G, Y, D, X = "\033[1m", "\033[31m", "\033[32m", "\033[33m", "\033[2m", "\033[0m"


def step(n: int, text: str) -> None:
    print(f"\n{B}[{n}]{X} {text}")


async def mcp_call(token: str, tool: str, args: dict) -> dict:
    import httpx2
    from mcp import Client
    from mcp.client.streamable_http import streamable_http_client

    async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"}, timeout=60) as http:
        async with Client(streamable_http_client(MCP_URL, http_client=http)) as client:
            res = await client.call_tool(tool, args)
    if res.is_error:
        raise RuntimeError(" ".join(getattr(c, "text", "") for c in res.content))
    data = res.structured_content or json.loads(res.content[0].text)
    return data.get("result", data) if set(data) == {"result"} else data


def call(token, tool, args=None):
    return asyncio.run(mcp_call(token, tool, args or {}))


def pick_task(db, room: Room) -> Record:
    """Task 4 if it's open, otherwise a fresh copy so the demo can be re-run."""
    tasks = db.execute(
        select(Record).where(Record.room_id == room.id, Record.type == "task", Record.title.like("Write help-desk FAQ%"))
        .order_by(Record.number)
    ).scalars().all()
    for t in tasks:
        if t.status == "open":
            return t
    owner = db.get(User, room.owner_id)
    rec, _ = ledger.create_record(
        db, room.id, "task", f"Write help-desk FAQ (crash demo {len(tasks) + 1})",
        {"description": "Write a short FAQ for the help desk about the new app.", "role": "planner"},
        author_user_id=owner.id, status="open",
    )
    append_event(db, room.id, "task.created", actor_user(owner, "owner"),
                 f"{owner.display_name} created {ledger.label(rec)} \"{rec.title}\" for a planner",
                 {"task": ledger.record_ref(rec)}, record_ids=[rec.id])
    db.commit()
    return rec


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--pause", type=float, default=6.0, help="seconds to stay 'crashed' before retrying")
    args = p.parse_args()
    if not DEMO_FILE.exists():
        sys.exit("No demo data. Run ./start.sh (or ./reset-demo.sh) first.")
    demo = json.loads(DEMO_FILE.read_text())
    agent_info = next(a for a in demo["agents"] if a["tool"] == "gemini_cli")
    token = agent_info["token"]
    key = f"crash-demo-{secrets.token_hex(3)}"

    with SessionLocal() as db:
        room = db.get(Room, uuid.UUID(demo["room_id"]))
        agent = db.get(Agent, uuid.UUID(agent_info["id"]))
        task = pick_task(db, room)
        task_label = ledger.label(task)

    print(f"{B}Baton crash-recovery demo{X}  agent={agent.name}  task={task_label}  key={key}")

    step(1, f"{agent.name} reads the room and claims {task_label} (over MCP)")
    ctx = call(token, "get_room_context")
    call(token, "claim_task", {"task_id": task_label})
    based_on = [ctx["brief"]["revision_id"]] + [d["revision_id"] for d in ctx["decisions"]]
    survey = next(s for s in ctx["sources"] if "survey" in s["title"].lower())
    print(f"    based_on: Brief + {len(ctx['decisions'])} decisions; cites {survey['label']}")

    step(2, "It submits. Baton verifies and SAVES the submission, then the agent process dies")
    with SessionLocal() as db:
        agent = db.get(Agent, agent.id)
        try:
            sub_svc.submit(db, agent, task_label, {"body": FAQ}, based_on, [survey["source_id"]], key, "Help-desk FAQ", crash_after_save=True)
        except sub_svc.SimulatedCrash:
            sub_svc.record_crash(db, agent, key)
            print(f"    {R}💥 crashed after `saved`, before `completed`{X}")

    with SessionLocal() as db:
        sub = db.execute(select(Submission).where(Submission.idempotency_key == key)).scalar_one()
        n = db.execute(select(func.count()).select_from(Revision).where(Revision.submission_id == sub.id)).scalar_one()
        print(f"    database: submission status={Y}{sub.status}{X}, revisions created={n}")

    step(3, f"Agent is down for {args.pause:.0f}s (watch Recovery in the UI: 'interrupted')")
    time.sleep(args.pause)

    step(4, "The agent restarts and retries with the SAME idempotency key (over MCP)")
    out = call(token, "submit_result", {"task_id": task_label, "content": {"body": FAQ}, "based_on": based_on,
                                        "sources": [survey["source_id"]], "idempotency_key": key, "title": "Help-desk FAQ"})
    print(f"    {G}{out['message']}{X}")
    print(f"    status={out['status']} resumed={out['resumed']} attempts={out['attempts']} result={out['result']['label']} v{out['result']['revision']}")

    step(5, "A duplicate retry (e.g. a network replay) with the same key")
    dup = call(token, "submit_result", {"task_id": task_label, "content": {"body": FAQ}, "based_on": based_on,
                                        "sources": [survey["source_id"]], "idempotency_key": key})
    print(f"    {dup['message']}  attempts={dup['attempts']}")

    with SessionLocal() as db:
        sub = db.execute(select(Submission).where(Submission.idempotency_key == key)).scalar_one()
        n = db.execute(select(func.count()).select_from(Revision).where(Revision.submission_id == sub.id)).scalar_one()
        subs = db.execute(select(func.count()).select_from(Submission).where(Submission.idempotency_key == key)).scalar_one()
    ok = n == 1 and subs == 1 and sub.status == "completed"
    step(6, "Proof, counted from the database")
    print(f"    submissions with this key: {subs}   revisions created: {n}   attempts: {sub.attempts}")
    print(f"    {G + B}✔ Applied exactly once{X}" if ok else f"    {R + B}✘ NOT exactly once{X}")
    print(f"\n{D}See it in the UI under Recovery, or GET /api/rooms/{demo['room_id']}/recovery{X}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
