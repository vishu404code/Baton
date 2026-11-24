"""Live demo: four AI tools plan a trip together in one continuous conversation.

Each step goes through the same path real tools use: the tool reads the handoff briefing, answers, and saves
context. Replies are scripted (so the demo works offline and never fails on stage), but the briefing each step
reads and the entries it writes are real, so the Context screen and the handoff pane update exactly as they do
with live tools."""

from __future__ import annotations

import threading
import time

from sqlalchemy import delete, select

from app.db import SessionLocal
from app.models import Agent, ContextEntry, Room, utcnow
from app.serializers import actor_agent, actor_user
from app.services import context as context_svc
from app.services import rooms as room_svc

DEMO_ROOM_NAME = "Live demo: Jaipur trip"
BRIEF = ("Four friends want a 3-day trip to Jaipur in February. Total budget is 40,000 rupees. "
         "Plan it end to end: budget, itinerary, food, packing. Keep it practical.")

STEPS = [
    {
        "tool": "claude_code", "name": "Claude Code",
        "prompt": "I'm planning a 3-day Jaipur trip for 4 friends in February. Total budget is 40,000 rupees. Where do I start?",
        "reply": ("Start with the budget, then everything else fits inside it. For 4 people over 2 nights I'd split it like this: "
                  "stay 10,000 (two rooms at 2,500 a night near C-Scheme), travel 8,400 (train from Delhi plus local cabs), "
                  "food 8,000, entry tickets 2,100, one big dinner at Chokhi Dhani 4,400. That is 32,900 and leaves 7,100 as a buffer. "
                  "February is the best month to go, mornings are cool and the forts are not crowded yet."),
        "summary": "Set the budget for the Jaipur trip: 4 friends, 2 nights in February, 40,000 rupees total. Split: stay 10,000, travel 8,400, food 8,000, tickets 2,100, Chokhi Dhani dinner 4,400. Planned 32,900, buffer 7,100.",
        "next": "Build a day-by-day itinerary that fits this budget.", "kind": "decision", "files": [],
    },
    {
        "tool": "codex", "name": "Codex / ChatGPT",
        "prompt": "Great, now make the itinerary.",
        "reply": ("Building on Claude Code's budget (4 people, 32,900 planned). Day 1: Amer Fort at opening time, then Jaigarh Fort, "
                  "evening at Nahargarh for sunset. Day 2: City Palace, Jantar Mantar, Hawa Mahal, then Johari Bazaar for shopping. "
                  "Day 3: slow morning, Albert Hall Museum, and Chokhi Dhani for the big dinner before the night train. "
                  "Entry tickets for all of these come to about 520 per person, which matches the 2,100 line in the budget."),
        "summary": "Day-by-day itinerary within the 32,900 budget. Day 1: Amer Fort, Jaigarh Fort, Nahargarh sunset. Day 2: City Palace, Jantar Mantar, Hawa Mahal, Johari Bazaar. Day 3: Albert Hall Museum, Chokhi Dhani dinner, night train. Tickets about 520 per person.",
        "next": "Pick cheap places to eat near each day's stops, within the 8,000 food budget.", "kind": "progress", "files": ["itinerary.md"],
    },
    {
        "tool": "gemini_cli", "name": "Gemini CLI",
        "prompt": "Where should we eat? Keep it cheap.",
        "reply": ("Matching the itinerary stop by stop. Day 1 breakfast: pyaaz kachori at Rawat Mishthan Bhandar before Amer, lunch near Jaigarh is thali at a roadside dhaba. "
                  "Day 2: lassi at Lassiwala on MI Road, then dal baati at Laxmi Misthan Bhandar near Johari Bazaar. "
                  "Day 3: Tapri Central for chai and snacks, then Chokhi Dhani for dinner, already counted. "
                  "This keeps food at about 1,000 per person, so 4,000 for the group, well under the 8,000 line. That frees roughly 4,000 more."),
        "summary": "Cheap eats matched to each stop: Rawat Mishthan Bhandar (kachori), Lassiwala (lassi), Laxmi Misthan Bhandar (dal baati), Tapri Central (chai). About 1,000 per person, 4,000 for the group, so about 4,000 is free in the food budget.",
        "next": "Write the packing list and a final summary with the updated total.", "kind": "progress", "files": ["food.md"],
    },
    {
        "tool": "antigravity", "name": "Antigravity",
        "prompt": "Give me a packing list and a final summary.",
        "reply": ("Final plan, pulling from all three earlier steps. Pack for cool mornings and warm afternoons: a light jacket, cotton layers, comfortable walking shoes for the forts, "
                  "a scarf, sunscreen, a power bank and a reusable water bottle. "
                  "Updated cost: 32,900 planned minus 4,000 saved on food gives about 28,900, leaving 11,100 as buffer. "
                  "The only open item is booking: trains first, since February weekends fill up early, then the two rooms."),
        "summary": "Final trip plan: 3 days, 4 friends, about 28,900 after the food savings, 11,100 buffer. Packing list: light jacket, cotton layers, walking shoes, scarf, sunscreen, power bank, water bottle. Open item: book trains first, then two rooms.",
        "next": "Check the whole plan against the original 40,000 budget and the dates.", "kind": "progress", "files": ["packing.md", "summary.md"],
    },
    {
        "tool": "claude_code", "name": "Claude Code",
        "prompt": "Is everything still within budget?",
        "reply": ("Checked every step from the other tools against the original 40,000. Budget 32,900, itinerary tickets match the 2,100 line, "
                  "Gemini's food savings bring it to 28,900, and Antigravity's summary agrees. Nothing contradicts the budget decision. "
                  "One risk: weekend train tickets sell out, so book those first. Plan approved and ready to book."),
        "summary": "Reviewed the plan from Codex, Gemini and Antigravity against the original decision (40,000 budget, 2 nights, February). All consistent: 28,900 total, 11,100 buffer. Approved. Only risk: weekend trains sell out.",
        "next": "Book trains, then two rooms near C-Scheme.", "kind": "decision", "files": [],
    },
]

_lock = threading.Lock()
_state: dict[str, dict] = {}


def _blank(room_id: str) -> dict:
    return {"room_id": room_id, "running": False, "done": False, "step": 0, "total": len(STEPS), "tool": None, "name": None,
            "prompt": "", "reply": "", "phase": "idle", "read_count": 0, "transcript": []}


def status(room_id) -> dict:
    with _lock:
        return dict(_state.get(str(room_id)) or _blank(str(room_id)))


def _set(room_id: str, **kw) -> None:
    with _lock:
        _state.setdefault(room_id, _blank(room_id)).update(kw)


def ensure_demo_room(db, user) -> Room:
    room = db.execute(select(Room).where(Room.name == DEMO_ROOM_NAME, Room.owner_id == user.id)).scalar_one_or_none()
    if room is not None:
        return room
    from app.services import ledger
    from app.services.events import append_event

    room = room_svc.create_room(db, user, DEMO_ROOM_NAME)
    rec, _ = ledger.create_record(db, room.id, "brief", "Trip brief", {"body": BRIEF}, author_user_id=user.id, status="approved")
    append_event(db, room.id, "revision.created", actor_user(user, "owner"), f"{user.display_name} created {ledger.label(rec)} \"{rec.title}\"",
                 {"record": ledger.record_ref(rec) | {"type": "brief"}}, record_ids=[rec.id])
    for step in {s["tool"]: s for s in STEPS}.values():
        room_svc.create_agent(db, room, user, step["name"], step["tool"], "observer")
    db.commit()
    return room


def reset(room_id) -> None:
    rid = str(room_id)
    with _lock:
        if _state.get(rid, {}).get("running"):
            return
    with SessionLocal() as db:
        db.execute(delete(ContextEntry).where(ContextEntry.room_id == room_id, ContextEntry.is_demo.is_(True)))
        db.commit()
    with _lock:
        _state[rid] = _blank(rid)


def start(room_id) -> bool:
    rid = str(room_id)
    with _lock:
        if _state.get(rid, {}).get("running"):
            return False
    reset(room_id)
    _set(rid, running=True, done=False)
    threading.Thread(target=_run, args=(room_id,), daemon=True, name="baton-demo").start()
    return True


def _run(room_id) -> None:
    rid = str(room_id)
    try:
        for i, s in enumerate(STEPS, start=1):
            _set(rid, step=i, tool=s["tool"], name=s["name"], prompt=s["prompt"], reply="", phase="connecting", read_count=0)
            time.sleep(1.2)
            with SessionLocal() as db:
                room = db.get(Room, room_id)
                h = context_svc.build_handoff(db, room, for_name=s["name"])
            _set(rid, phase="reading", read_count=len(h["entries"]))
            time.sleep(2.2)
            _set(rid, phase="answering")
            words = s["reply"].split(" ")
            for k in range(len(words)):
                _set(rid, reply=" ".join(words[: k + 1]))
                time.sleep(0.07)
            time.sleep(0.6)
            _set(rid, phase="saving")
            time.sleep(0.8)
            with SessionLocal() as db:
                agent = db.execute(select(Agent).where(Agent.room_id == room_id, Agent.tool == s["tool"], Agent.revoked_at.is_(None))).scalars().first()
                agent.last_seen_at = utcnow()
                actor = actor_agent(agent, "You")
                e = context_svc.save_entry(db, room_id, author=s["name"], tool=s["tool"], summary=s["summary"], next_steps=s["next"],
                                           files=s["files"], kind=s["kind"], actor=actor)
                e.is_demo = True
                db.commit()
            with _lock:
                st = _state[rid]
                st["transcript"] = st["transcript"] + [{"tool": s["tool"], "name": s["name"], "prompt": s["prompt"], "reply": s["reply"]}]
                st.update(phase="saved")
            time.sleep(1.8)
        _set(rid, running=False, done=True, phase="done")
    except Exception:  # never leave the UI spinning
        _set(rid, running=False, phase="error")
        raise
