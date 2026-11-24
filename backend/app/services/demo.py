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

def _step(tool, name, prompt, reply, summary, nxt, kind="progress", files=None):
    return {"tool": tool, "name": name, "prompt": prompt, "reply": reply, "summary": summary, "next": nxt, "kind": kind, "files": files or []}


C, X, G, A = ("claude_code", "Claude Code"), ("codex", "Codex / ChatGPT"), ("gemini_cli", "Gemini CLI"), ("antigravity", "Antigravity")

FOOD = [
    _step(*C, "I have one day in Jaipur and want to eat like a local. Where do I start?",
          "Start with breakfast before 10 a.m. at Rawat Mishthan Bhandar, famous for pyaaz kachori and mawa kachori, because the batches are hottest early. "
          "The Journals call pyaaz kachori Jaipur's breakfast religion, so order two and a glass of chai. Then keep the morning light for sightseeing and save the heavy meals for later.",
          "Food day plan, step 1: breakfast at Rawat Mishthan Bhandar before 10 a.m. (pyaaz kachori, mawa kachori, chai). Heavier meals after the morning sightseeing.",
          "Plan lunch and drinks around the old city.", "decision", []),
    _step(*X, "Now lunch and something cold to drink.",
          "Building on the kachori breakfast: lunch at LMB (Laxmi Misthan Bhandar) in Johari Bazar for the traditional Rajasthani thali, and finish with a sweet. "
          "Say thoda thoda if you want smaller portions of dal baati churma. Then cool down with lassi at Lassiwala on MI Road, served in clay cups. Drink it on the spot and discard the cup.",
          "Lunch at LMB, Johari Bazar (Rajasthani thali, then a sweet). Lassi at Lassiwala on MI Road in a clay cup. Tip: ask for thoda thoda portions of dal baati churma.",
          "Pick an evening chai or rooftop cafe spot.", "progress", ["food-day.md"]),
    _step(*G, "What about the evening? Something with a view.",
          "After the thali and lassi you will want something light. Book a window or terrace table at one of the new rooftop cafes in advance for sunset, since the best seats go early. "
          "Order chai and a small snack rather than a full dinner. The Journals suggest chai, lassi and rooftop cafes as the way to end a Jaipur day.",
          "Evening: reserve a rooftop cafe terrace for sunset, chai and a light snack instead of a full dinner, after the LMB lunch and the Lassiwala lassi.",
          "Write the final one-day food route with times.", "progress", ["food-day.md"]),
    _step(*A, "Give me the final food route with times.",
          "Final route. 07:45 Rawat Mishthan Bhandar for pyaaz and mawa kachori with chai. 12:45 thali and a sweet at LMB, Johari Bazar. 15:30 lassi at Lassiwala, MI Road. "
          "18:00 rooftop cafe for chai at sunset. Go early for the kachoris, say thoda thoda at lunch, and drink the lassi on the spot.",
          "Final one-day food route: 07:45 kachori at Rawat Mishthan Bhandar, 12:45 thali at LMB, 15:30 lassi at Lassiwala, 18:00 rooftop chai. Tips: go early, thoda thoda, drink lassi on the spot.",
          "Share the route with the group.", "decision", ["food-day.md"]),
]

HERITAGE = [
    _step(*C, "I want to see Jaipur's forts and take good photos. How should I order the day?",
          "Order it by light and distance. Start at Amer Fort when it opens, to beat the heat and the crowds, and pair it with Jaigarh Fort on the ridge above in one outing. "
          "Panna Meena ka Kund, the geometric stepwell near Amer, fits the same trip. Save the city sights for midday and Nahargarh for late afternoon.",
          "Heritage day order: Amer Fort at opening, Jaigarh Fort and Panna Meena ka Kund in the same outing, city sights at midday, Nahargarh late afternoon.",
          "Fit the city sights into midday and add photo timing.", "decision", []),
    _step(*X, "Add the city sights and the best time for each.",
          "Hawa Mahal comes first for a sunrise photo of the 953 jharokhas, ideally from a cafe across the road. After Amer, go to the City Palace and then Jantar Mantar mid-morning, when the shadows on the sundial are easy to read. "
          "That keeps the hill forts in the morning and the old city in the middle of the day.",
          "City sights slotted around the forts: Hawa Mahal at sunrise from a cafe across the road, City Palace then Jantar Mantar mid-morning when shadows are easy to read.",
          "Plan golden hour and night photos.", "progress", ["heritage-day.md"]),
    _step(*G, "Where do I shoot at golden hour and after dark?",
          "For golden hour, reach Nahargarh Fort by late afternoon to claim a spot on its sunset terrace over the old city. Stop at the Jal Mahal promenade to photograph the water palace in Man Sagar Lake. "
          "After dark, go to Albert Hall Museum to see the Indo-Saracenic building lit up from outside.",
          "Photo plan: Nahargarh sunset terrace by late afternoon, Jal Mahal from the promenade (view only), Albert Hall Museum after dark when it is lit up.",
          "Write the logistics and final schedule.", "progress", ["heritage-day.md"]),
    _step(*A, "Put it together with logistics.",
          "Final schedule. 06:30 Hawa Mahal. 09:00 Amer, Jaigarh and Panna Meena ka Kund. 14:15 City Palace and Jantar Mantar. 16:30 Nahargarh for sunset, with a Jal Mahal stop on the way. 20:00 Albert Hall lit up. "
          "The sites are spread out, so hire a driver for the day, take breaks in the afternoon heat, and check ticket prices before you go.",
          "Final heritage day: Hawa Mahal 06:30, Amer + Jaigarh + Panna Meena 09:00, City Palace + Jantar Mantar 14:15, Nahargarh sunset, Albert Hall at night. Hire a driver, rest in the afternoon heat, check ticket prices.",
          "Book a driver for the day.", "decision", ["heritage-day.md"]),
]

SHOP = [
    _step(*C, "I want to shop in Jaipur without getting overcharged. Where do I begin?",
          "Begin in Johari Bazar, the jewellers' market, famed for gemstones, kundan and meenakari. Evenings are lively, but many shops close one day a week, so check first. "
          "Just off it, Gopalji ka Rasta is the traditional lane for gemstone traders. Always ask for a written receipt for any gemstone, and compare prices across several shops before deciding.",
          "Shopping step 1: jewellery and gemstones in Johari Bazar and Gopalji ka Rasta. Get a written receipt, compare several shops, check which weekday shops close.",
          "Cover textiles and souvenirs next.", "decision", []),
    _step(*X, "Now textiles, bangles and souvenirs.",
          "Next is Bapu Bazar for textiles, mojari slippers, block prints and souvenirs. Walk its full length before you buy anything, since prices and quality vary. "
          "Then visit Maniharon ka Rasta near Tripolia Bazar, the lane of the lac-bangle makers, where you can watch the bangles being heated and shaped by hand.",
          "Bapu Bazar for textiles, mojari and block prints (walk the whole length first). Maniharon ka Rasta for hand-made lac bangles near Tripolia Bazar.",
          "Add a crafts half-day for block printing and pottery.", "progress", ["shopping.md"]),
    _step(*G, "Is there a way to see the crafts being made?",
          "Yes. Make a half-day trip to Sanganer for fine hand-block-printed cloth, or Bagru for mud-resist dabu printing in natural dyes, ideally with a driver. "
          "Choose a workshop that lets you try printing yourself. In Amer, the Anokhi Museum of Hand Printing tells the history, and for blue pottery ask whether a piece is food-safe and check for even glaze and no chips.",
          "Crafts half-day: Sanganer or Bagru workshops with a driver, Anokhi Museum of Hand Printing in Amer, and blue pottery checks (food-safe, even glaze, no chips).",
          "Finish with a checklist and scam-proof tips.", "progress", ["shopping.md"]),
    _step(*A, "Give me a checklist so I don't get tricked.",
          "Checklist. Gemstones: written receipt and several quotes. Pottery: food-safe question and a glaze check. Textiles: walk Bapu Bazar end to end first. Shops: many close one weekday, so verify. "
          "If a shopkeeper offers chai, accepting is polite and not an obligation to buy. Plan jewellery for the evening and crafts for a driver-led half-day.",
          "Shopping checklist: written receipts and several quotes for gemstones, food-safe check for pottery, walk Bapu Bazar first, verify closing days, chai is not an obligation. Jewellery in the evening, crafts on a half-day trip.",
          "Pick the shopping day.", "decision", ["shopping.md"]),
]

STAY = [
    _step(*C, "We want one palace stay in Jaipur. What are the options?",
          "The Journals feature three. Rambagh Palace, run by Taj Hotels since 1972, was a maharaja's home set in 47 acres of gardens. The Oberoi Rajvilas is a walled estate with tents and a temple. "
          "Jai Mahal Palace is an eighteenth-century residence in Mughal gardens. All three are palaces, but they feel different, so the right pick depends on who is travelling.",
          "Three palace stays: Rambagh Palace (Taj, since 1972, 47 acres), The Oberoi Rajvilas (walled estate with tents and a temple), Jai Mahal Palace (18th-century Mughal-garden residence).",
          "Match each hotel to a type of traveller.", "decision", []),
    _step(*X, "Which one fits which kind of traveller?",
          "Matching them. Rambagh Palace is the first splurge: best for history lovers and anyone who wants the full palace experience. "
          "The Oberoi Rajvilas suits people who want quiet, privacy and long breakfasts, a good base if you would rather leave the crowds behind. "
          "Jai Mahal Palace is for garden lovers who want a palace stay with a quieter feel.",
          "Best fit: Rambagh for a first splurge and history lovers, Oberoi Rajvilas for quiet and privacy, Jai Mahal Palace for garden lovers wanting a quieter palace stay.",
          "Think about location and when to travel.", "progress", ["stays.md"]),
    _step(*G, "What about location and the best time to go?",
          "Rambagh sits on Bhawani Singh Road in central Jaipur, so the old city and the forts are a short drive away, which helps with the early starts the Journals recommend for Amer. "
          "The 7-day itinerary notes that travel is easiest in the cooler months, roughly October to March, so book a palace stay for those months well ahead.",
          "Location and timing: Rambagh is central on Bhawani Singh Road, good for early starts. Cooler months, roughly October to March, are the easiest time, so book early.",
          "Decide and write a short booking checklist.", "progress", ["stays.md"]),
    _step(*A, "Make the call and give me a booking checklist.",
          "My pick for a first visit is Rambagh Palace: central, historic and the full palace experience. Choose the Oberoi Rajvilas instead if privacy matters most. "
          "Checklist: book between October and March well ahead, confirm dates with the itinerary, ask about breakfast and spa, and plan a driver for the forts.",
          "Decision: Rambagh Palace for a first visit (central, historic); Oberoi Rajvilas if privacy matters most. Checklist: book Oct to March early, confirm dates, ask about breakfast and spa, arrange a driver for the forts.",
          "Confirm dates and book.", "decision", ["stays.md"]),
]

SCENARIOS = {
    "trip": {"title": "Plan a Jaipur trip", "blurb": "Budget, itinerary, food and packing for four friends.",
             "brief": BRIEF, "steps": STEPS},
    "food": {"title": "Eat like a local", "blurb": "A one-day food route from kachori to lassi to rooftop chai.",
             "brief": "One day in Jaipur, eating like a local. Plan a food route with real places, times and tips from the magazine.", "steps": FOOD},
    "heritage": {"title": "Forts and photos", "blurb": "Order the forts and palaces by light and plan golden hour.",
                 "brief": "Plan a day of Jaipur's forts and palaces with the best photo timing, using the magazine's places and tips.", "steps": HERITAGE},
    "shopping": {"title": "Bazaars and crafts", "blurb": "Where to shop for gemstones, textiles and crafts without being overcharged.",
                 "brief": "Plan a shopping day in Jaipur's bazaars and craft workshops, avoiding overpaying, using the magazine's guides.", "steps": SHOP},
    "stay": {"title": "Choose a palace stay", "blurb": "Compare three palace hotels and decide.",
             "brief": "Choose one palace hotel in Jaipur for a first visit and write a booking checklist, using the magazine's hotel guides.", "steps": STAY},
}

_lock = threading.Lock()
_state: dict[str, dict] = {}
SPEED = 1.0  # tests set this to 0


def _sleep(sec: float) -> None:
    time.sleep(sec * SPEED)


def scenario_list() -> list[dict]:
    return [{"id": k, "title": v["title"], "blurb": v["blurb"], "steps": len(v["steps"])} for k, v in SCENARIOS.items()]


def _blank(room_id: str, scenario: str = "trip") -> dict:
    return {"room_id": room_id, "scenario": scenario, "running": False, "done": False, "step": 0, "total": len(SCENARIOS[scenario]["steps"]),
            "tool": None, "name": None, "prompt": "", "reply": "", "phase": "idle", "read_count": 0, "transcript": []}


def status(room_id) -> dict:
    with _lock:
        out = dict(_state.get(str(room_id)) or _blank(str(room_id)))
    out["scenarios"] = scenario_list()
    return out


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
    rec, _ = ledger.create_record(db, room.id, "brief", "Brief", {"body": BRIEF}, author_user_id=user.id, status="approved")
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
        _state[rid] = _blank(rid, (_state.get(rid) or {}).get("scenario", "trip"))


def _set_brief(room_id, text: str) -> None:
    from app.services import ledger

    with SessionLocal() as db:
        room = db.get(Room, room_id)
        rec = ledger.latest(db, room_id, "brief")
        if rec is None or room is None:
            return
        cur = (ledger.current_revision(db, rec).content or {}).get("body")
        if cur != text:
            ledger.append_revision(db, rec, {"body": text}, author_user_id=room.owner_id)
            db.commit()


def start(room_id, scenario: str = "trip") -> bool:
    rid = str(room_id)
    if scenario not in SCENARIOS:
        scenario = "trip"
    with _lock:
        if _state.get(rid, {}).get("running"):
            return False
        _state[rid] = _blank(rid, scenario)
    reset(room_id)
    _set(rid, scenario=scenario, total=len(SCENARIOS[scenario]["steps"]), running=True, done=False)
    _set_brief(room_id, SCENARIOS[scenario]["brief"])
    threading.Thread(target=_run, args=(room_id, scenario), daemon=True, name="baton-demo").start()
    return True


def _run(room_id, scenario: str) -> None:
    rid = str(room_id)
    steps = SCENARIOS[scenario]["steps"]
    try:
        for i, s in enumerate(steps, start=1):
            _set(rid, step=i, tool=s["tool"], name=s["name"], prompt=s["prompt"], reply="", phase="connecting", read_count=0)
            _sleep(0.5)
            with SessionLocal() as db:
                room = db.get(Room, room_id)
                h = context_svc.build_handoff(db, room, for_name=s["name"])
            _set(rid, phase="reading", read_count=len(h["entries"]))
            _sleep(1.0)
            _set(rid, phase="answering")
            words = s["reply"].split(" ")
            for k in range(0, len(words), 2):
                _set(rid, reply=" ".join(words[: k + 2]))
                _sleep(0.05)
            _set(rid, reply=s["reply"])
            _sleep(0.3)
            _set(rid, phase="saving")
            _sleep(0.4)
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
            _sleep(0.8)
        _set(rid, running=False, done=True, phase="done")
    except Exception:  # never leave the UI spinning
        _set(rid, running=False, phase="error")
        raise
