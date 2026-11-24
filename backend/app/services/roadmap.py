"""The roadmap and live activity: what each AI tool owns, what it is doing right now, and the briefing it receives.

Nothing here talks to a chatbot. Tools report through hooks (every edit or command) and MCP (task status), and receive a
short briefing at the start of a session and whenever something changed since they last looked."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, select

from app.models import Agent, Event, RoadmapTask, Room, utcnow
from app.serializers import actor_agent, actor_user
from app.services.events import append_event, iso

TOOLS = {"claude_code": "Claude", "codex": "ChatGPT (Codex)", "antigravity": "Antigravity", "gemini_cli": "Gemini"}
ALIASES = {"claude": "claude_code", "claude code": "claude_code", "claude_code": "claude_code", "gpt": "codex", "chatgpt": "codex", "openai": "codex",
           "codex": "codex", "antigravity": "antigravity", "agy": "antigravity", "gemini": "gemini_cli", "gemini cli": "gemini_cli", "gemini_cli": "gemini_cli"}
STATUSES = ("waiting", "in_progress", "done", "blocked")
EDIT_VERBS = ("edited", "created", "wrote")


class RoadmapError(ValueError):
    pass


def normalize_owner(value: str) -> str:
    key = (value or "").strip().lower()
    if key not in ALIASES:
        raise RoadmapError(f"Unknown tool '{value}'. Use one of: claude, chatgpt (codex), antigravity, gemini.")
    return ALIASES[key]


def task_out(t: RoadmapTask) -> dict:
    return {"id": str(t.id), "number": t.number, "title": t.title, "owner_tool": t.owner_tool, "owner": TOOLS.get(t.owner_tool, t.owner_tool),
            "description": t.description, "done_when": t.done_when, "depends_on": list(t.depends_on or []), "area": t.area,
            "status": t.status, "note": t.note, "updated_at": iso(t.updated_at)}


def list_tasks(db, room_id) -> list[RoadmapTask]:
    return list(db.execute(select(RoadmapTask).where(RoadmapTask.room_id == room_id).order_by(RoadmapTask.number)).scalars())


def _int_list(v) -> list[int]:
    out = []
    for x in v or []:
        m = re.search(r"\d+", str(x))
        if m:
            out.append(int(m.group()))
    return out


def save_roadmap(db, room: Room, tasks: list[dict], *, replace: bool, actor: dict) -> list[RoadmapTask]:
    if not tasks:
        raise RoadmapError("The roadmap has no tasks.")
    existing = {t.number: t for t in list_tasks(db, room.id)}
    if replace:
        db.execute(delete(RoadmapTask).where(RoadmapTask.room_id == room.id))
        db.flush()
        existing = {}
    next_no = max(existing, default=0) + 1
    for raw in tasks:
        title = str(raw.get("title") or "").strip()
        if not title:
            raise RoadmapError("Every task needs a title.")
        owner = normalize_owner(str(raw.get("owner") or raw.get("owner_tool") or ""))
        number = int(raw["number"]) if str(raw.get("number") or "").isdigit() else next_no
        row = existing.get(number)
        if row is None:
            row = RoadmapTask(room_id=room.id, number=number, title=title[:200], owner_tool=owner)
            db.add(row)
            existing[number] = row
        row.title, row.owner_tool = title[:200], owner
        row.description = str(raw.get("description") or "")[:2000]
        row.done_when = str(raw.get("done_when") or "")[:600]
        row.depends_on = _int_list(raw.get("depends_on"))
        row.area = str(raw.get("area") or "")[:200]
        if raw.get("status") in STATUSES:
            row.status = raw["status"]
        row.updated_at = utcnow()
        next_no = max(next_no, number + 1)
    db.flush()
    rows = list_tasks(db, room.id)
    owners = sorted({TOOLS[t.owner_tool] for t in rows})
    append_event(db, room.id, "roadmap.saved", actor, f"Roadmap saved: {len(rows)} tasks for {', '.join(owners)}", {"tasks": len(rows)})
    return rows


def update_task(db, room: Room, number: int, *, status: str | None, note: str | None, owner: str | None, actor: dict) -> RoadmapTask:
    t = db.execute(select(RoadmapTask).where(RoadmapTask.room_id == room.id, RoadmapTask.number == number)).scalar_one_or_none()
    if t is None:
        raise RoadmapError(f"There is no task {number} in the roadmap.")
    if status is not None:
        if status not in STATUSES:
            raise RoadmapError(f"Status must be one of: {', '.join(STATUSES)}.")
        t.status = status
    if note is not None:
        t.note = note[:1000]
    if owner:
        t.owner_tool = normalize_owner(owner)
    t.updated_at = utcnow()
    append_event(db, room.id, "task.updated", actor, f"Task {t.number} \"{t.title}\" is now {t.status.replace('_', ' ')}" + (f": {t.note[:100]}" if t.note else ""),
                 {"task": task_out(t)})
    return t


def delete_task(db, room: Room, number: int) -> None:
    db.execute(delete(RoadmapTask).where(RoadmapTask.room_id == room.id, RoadmapTask.number == number))


def _blocked_by(t: RoadmapTask, by_no: dict[int, RoadmapTask]) -> list[int]:
    return [n for n in (t.depends_on or []) if n in by_no and by_no[n].status != "done"]


def roadmap_lines(tasks: list[RoadmapTask], for_tool: str | None = None) -> list[str]:
    by_no = {t.number: t for t in tasks}
    lines = []
    for t in tasks:
        waiting = _blocked_by(t, by_no)
        status = t.status.replace("_", " ")
        extra = f", waits for task {', '.join(map(str, waiting))}" if waiting and t.status != "done" else ""
        mine = "  <- YOURS" if for_tool and t.owner_tool == for_tool and t.status != "done" else ""
        area = f" [folder: {t.area}]" if t.area else ""
        lines.append(f"{t.number}. [{status}{extra}] {t.title} ({TOOLS.get(t.owner_tool)}){area}{mine}")
        if t.note and t.status in ("in_progress", "done", "blocked"):
            lines.append(f"     note: {t.note[:160]}")
    return lines


def next_task_for(tasks: list[RoadmapTask], tool: str) -> RoadmapTask | None:
    by_no = {t.number: t for t in tasks}
    mine = [t for t in tasks if t.owner_tool == tool and t.status in ("waiting", "in_progress", "blocked")]
    mine.sort(key=lambda t: (t.status != "in_progress", t.number))
    for t in mine:
        if t.status == "in_progress" or not _blocked_by(t, by_no):
            return t
    return mine[0] if mine else None


def _age(dt: datetime) -> str:
    s = int((datetime.now(timezone.utc) - dt.replace(tzinfo=dt.tzinfo or timezone.utc)).total_seconds())
    return "just now" if s < 10 else f"{s}s ago" if s < 90 else f"{s // 60}m ago" if s < 5400 else f"{s // 3600}h ago"


def recent_activity(db, room_id, *, since_seq: int = 0, exclude_tool: str | None = None, limit: int = 8) -> list[Event]:
    rows = db.execute(select(Event).where(Event.room_id == room_id, Event.type.in_(("activity.logged", "task.updated", "roadmap.saved", "context.saved")),
                                          Event.seq > since_seq).order_by(Event.seq.desc()).limit(60)).scalars()
    out = []
    for e in rows:
        if exclude_tool and ((e.payload or {}).get("tool") == exclude_tool or (e.actor or {}).get("tool") == exclude_tool):
            continue
        out.append(e)
        if len(out) >= limit:
            break
    return out


def latest_seq(db, room_id) -> int:
    return db.execute(select(Room.last_seq).where(Room.id == room_id)).scalar_one()


def briefing(db, room: Room, tool: str, *, since_seq: int, first: bool) -> tuple[str, int]:
    """Text a tool receives. Empty when nothing changed (so it costs nothing on most prompts)."""
    tasks = list_tasks(db, room.id)
    seq = latest_seq(db, room.id)
    events = recent_activity(db, room.id, since_seq=0 if first else since_seq, exclude_tool=tool, limit=8 if first else 6)
    if not first and not events:
        return "", seq
    parts = [f"[Baton live briefing for {TOOLS.get(tool, tool)} | project: {room.name}]"]
    if tasks and (first or any(e.type in ("task.updated", "roadmap.saved") for e in events)):
        parts += ["Roadmap (shared by every AI tool on this Mac):"] + roadmap_lines(tasks, tool)
    mine = next_task_for(tasks, tool)
    if first and mine:
        t = mine
        parts.append(f"YOUR TASK: {t.number}. {t.title}. {t.description}".strip())
        if t.done_when:
            parts.append(f"Done when: {t.done_when}")
        by_no = {x.number: x for x in tasks}
        w = _blocked_by(t, by_no)
        parts.append(("It waits for task " + ", ".join(map(str, w)) + " to finish; check those notes first. ") if w else
                     "Start on it unless the user asks for something else. When finished, call update_task(number, 'done', note) and save_context.")
    if events:
        parts.append("What the other AI tools did" + (" recently:" if first else " since you last looked:"))
        for e in reversed(events):
            parts.append(f"- {_age(e.created_at)}: {e.summary[:180]}")
    text = "\n".join(parts)
    return text[:2600], seq


def log_activity(db, room: Room, agent: Agent, *, event: str, summary: str, path: str | None) -> None:
    from app.models import User

    owner = db.get(User, agent.user_id)
    agent.last_seen_at = utcnow()
    append_event(db, room.id, "activity.logged", actor_agent(agent, owner.display_name if owner else None), f"{TOOLS.get(agent.tool, agent.name)}: {summary}",
                 {"tool": agent.tool, "event": event, "path": path})
    if path and event == "edit":
        _auto_progress(db, room, agent.tool, path)


def _auto_progress(db, room: Room, tool: str, path: str) -> None:
    """The first edit a tool makes inside its task's folder marks that task as in progress."""
    tasks = list_tasks(db, room.id)
    for t in tasks:
        if t.owner_tool == tool and t.status == "waiting" and (not t.area or f"/{t.area.strip('/')}/" in f"/{path}"):
            t.status = "in_progress"
            t.updated_at = utcnow()
            append_event(db, room.id, "task.updated", actor_user_stub(), f"Task {t.number} \"{t.title}\" started ({TOOLS.get(tool)})", {"task": task_out(t)})
            return


def actor_user_stub() -> dict:
    return {"kind": "system", "id": "baton", "name": "Baton"}
