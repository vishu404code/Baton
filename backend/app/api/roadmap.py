"""Roadmap, live activity and the hook endpoints that the AI tools call by themselves."""

import json
import re
import uuid

from fastapi import APIRouter, Depends, Header, Request, Response
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import agent_from_token, bearer, current_user, current_user_ro, get_membership
from app.db import get_db
from app.errors import ApiError, bad_request
from app.models import Agent, Event, Room, User
from app.schemas import _In
from app.serializers import actor_user
from app.services import roadmap as rm
from app.services.events import event_out

router = APIRouter(tags=["roadmap"])


class TaskIn(_In):
    title: str = Field(min_length=1, max_length=200)
    owner: str
    number: int | None = None
    description: str = ""
    done_when: str = ""
    depends_on: list[int] = []
    area: str = ""
    status: str | None = None


class RoadmapIn(_In):
    tasks: list[TaskIn] = Field(min_length=1, max_length=40)
    replace: bool = False


class TaskPatch(_In):
    status: str | None = None
    note: str | None = None
    owner: str | None = None


class ImportIn(_In):
    text: str = Field(min_length=20, max_length=20000)


@router.get("/api/rooms/{room_id}/roadmap")
def get_roadmap(room_id: uuid.UUID, user: User = Depends(current_user_ro)) -> dict:
    from app.db import read_session

    with read_session() as db:
        get_membership(db, room_id, user)
        return {"tasks": [rm.task_out(t) for t in rm.list_tasks(db, room_id)]}


@router.post("/api/rooms/{room_id}/roadmap", status_code=201)
def save_roadmap(room_id: uuid.UUID, body: RoadmapIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    room, m = get_membership(db, room_id, user)
    try:
        rows = rm.save_roadmap(db, room, [t.model_dump() for t in body.tasks], replace=body.replace, actor=actor_user(user, m.role))
    except rm.RoadmapError as e:
        raise bad_request(str(e)) from None
    db.commit()
    return {"tasks": [rm.task_out(t) for t in rows]}


@router.patch("/api/rooms/{room_id}/roadmap/{number}")
def patch_task(room_id: uuid.UUID, number: int, body: TaskPatch, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    room, m = get_membership(db, room_id, user)
    try:
        t = rm.update_task(db, room, number, status=body.status, note=body.note, owner=body.owner, actor=actor_user(user, m.role))
    except rm.RoadmapError as e:
        raise bad_request(str(e)) from None
    db.commit()
    return rm.task_out(t)


@router.delete("/api/rooms/{room_id}/roadmap/{number}", status_code=204)
def remove_task(room_id: uuid.UUID, number: int, user: User = Depends(current_user), db: Session = Depends(get_db)) -> Response:
    room, _ = get_membership(db, room_id, user)
    rm.delete_task(db, room, number)
    db.commit()
    return Response(status_code=204)


IMPORT_PROMPT = """Convert this project roadmap into JSON for a tool that assigns each task to one AI tool.
Return ONLY a JSON array (no prose, no code fences). Each item: {{"title": str, "owner": "claude"|"chatgpt"|"antigravity"|"gemini", "description": str,
"done_when": str, "depends_on": [task numbers, starting at 1 in the order listed], "area": folder such as "backend/" or "frontend/" or ""}}.
Pick the owner from the text (research/planning -> chatgpt, backend/server/database -> claude, frontend/UI -> antigravity) when it is not stated.

ROADMAP:
{text}"""


@router.post("/api/rooms/{room_id}/roadmap/import", status_code=201)
def import_roadmap(room_id: uuid.UUID, body: ImportIn, user: User = Depends(current_user_ro)) -> dict:
    """Paste a roadmap written anywhere (for example in ChatGPT in a browser). Baton turns it into tasks."""
    from app.db import SessionLocal, read_session
    from app.llm import cli_provider
    from app.llm.base import LLMError, ProviderConfig

    with read_session() as db:
        get_membership(db, room_id, user)
    prov = None
    for pid in ("anthropic", "openai", "antigravity"):
        seat = cli_provider.CLI_SEATS[pid]
        if seat.available():
            prov = seat
            break
    if prov is None:
        raise bad_request("No AI app is available to read the roadmap. Use the Add task button instead.")
    try:
        out = prov.complete(ProviderConfig(api_key="", model=prov.model_label), "You convert text to JSON.", IMPORT_PROMPT.format(text=body.text))
    except LLMError as e:
        raise bad_request(str(e)) from None
    m = re.search(r"\[.*\]", out.text, re.S)
    try:
        tasks = json.loads(m.group(0)) if m else None
    except ValueError:
        tasks = None
    if not isinstance(tasks, list) or not tasks:
        raise bad_request("Couldn't read that as a roadmap. Try fewer details, one task per line.")
    with SessionLocal() as db:
        room = db.get(Room, room_id)
        u = db.get(User, user.id)
        try:
            rows = rm.save_roadmap(db, room, [t for t in tasks if isinstance(t, dict)], replace=True, actor=actor_user(u, "owner"))
        except rm.RoadmapError as e:
            raise bad_request(str(e)) from None
        db.commit()
        return {"tasks": [rm.task_out(t) for t in rows], "read_by": prov.label}


@router.get("/api/rooms/{room_id}/activity")
def get_activity(room_id: uuid.UUID, limit: int = 40, user: User = Depends(current_user_ro)) -> dict:
    from app.db import read_session

    with read_session() as db:
        get_membership(db, room_id, user)
        rows = db.execute(select(Event).where(Event.room_id == room_id, Event.type.in_(("activity.logged", "task.updated", "roadmap.saved", "context.saved")))
                          .order_by(Event.seq.desc()).limit(min(limit, 100))).scalars()
        events = [event_out(e) for e in rows]
        agents = db.execute(select(Agent).where(Agent.room_id == room_id, Agent.revoked_at.is_(None)).order_by(Agent.created_at)).scalars().all()
        last_by_tool: dict[str, dict] = {}
        boring = ("finished its turn", "started a session")
        for e in events:  # newest first: prefer a real action over "finished its turn"
            tool = (e.get("payload") or {}).get("tool") or (e.get("actor") or {}).get("tool")
            if not tool or e["type"] == "roadmap.saved":
                continue
            cur = last_by_tool.get(tool)
            is_boring = e["summary"].endswith(boring)
            if cur is None or (cur["boring"] and not is_boring and (e["created_at"] or "") > "" and cur["recent"]):
                last_by_tool[tool] = {"summary": e["summary"], "at": e["created_at"], "type": e["type"], "boring": is_boring, "recent": True}
        for v in last_by_tool.values():
            v.pop("boring", None), v.pop("recent", None)
        seen = {}
        for a in agents:
            if a.tool in rm.TOOLS and (a.tool not in seen or (a.last_seen_at and (seen[a.tool] is None or a.last_seen_at > seen[a.tool]))):
                seen[a.tool] = a.last_seen_at
        from app.services.events import iso

        tools = [{"tool": t, "label": rm.TOOLS[t], "last_seen_at": iso(seen.get(t)), "last": last_by_tool.get(t)} for t in rm.TOOLS]
        return {"events": events, "tools": tools}


# --- Called by the hook script (agent token) --------------------------------------------------------------------


def _agent(authorization: str | None, db: Session) -> Agent:
    agent = agent_from_token(db, bearer(authorization))
    if agent is None:
        raise ApiError(401, "Missing or revoked Baton agent token.")
    return agent


class ActivityIn(_In):
    event: str = Field(max_length=24)  # edit | command | prompt | start | stop
    summary: str = Field(max_length=400)
    path: str | None = Field(default=None, max_length=500)


@router.post("/api/hooks/activity", status_code=202)
def hook_activity(body: ActivityIn, authorization: str | None = Header(default=None), db: Session = Depends(get_db)) -> dict:
    agent = _agent(authorization, db)
    room = db.get(Room, agent.room_id)
    rm.log_activity(db, room, agent, event=body.event, summary=body.summary, path=body.path)
    db.commit()
    return {"ok": True}


@router.get("/api/hooks/briefing")
def hook_briefing(since: int = 0, first: bool = False, authorization: str | None = Header(default=None), db: Session = Depends(get_db)) -> dict:
    agent = _agent(authorization, db)
    room = db.get(Room, agent.room_id)
    text, seq = rm.briefing(db, room, agent.tool, since_seq=since, first=first)
    agent_seen = agent  # noqa: F841
    from app.models import utcnow

    agent.last_seen_at = utcnow()
    db.commit()
    return {"text": text, "seq": seq}


# --- Setup screen: are the tools hooked up? ----------------------------------------------------------------------


class InstallIn(_In):
    project_dir: str = Field(min_length=1, max_length=400)


def _primary_room(db: Session, user: User) -> Room:
    from app.models import RoomMember
    from app.services.demo import DEMO_ROOM_NAME

    rooms = db.execute(select(Room).join(RoomMember, RoomMember.room_id == Room.id).where(RoomMember.user_id == user.id, Room.name != DEMO_ROOM_NAME)
                       .order_by(Room.created_at)).scalars().all()
    if not rooms:
        raise bad_request("Create a project first.")
    return rooms[0]


@router.get("/api/hooks/status")
def hooks_status(user: User = Depends(current_user_ro)) -> dict:
    import json

    from app import tool_connect as tc
    from app.db import read_session

    cfg = tc._load_json(tc.hook_script_path().parent / "config.json")
    with read_session() as db:
        agents = db.execute(select(Agent).where(Agent.revoked_at.is_(None))).scalars().all()
        seen = {}
        for a in agents:
            if a.last_seen_at and (a.tool not in seen or a.last_seen_at > seen[a.tool]):
                seen[a.tool] = a.last_seen_at
        from app.services.events import iso

        return {"project_dir": cfg.get("project"), "installed": tc.hooks_installed(), "connected": {t: t in (cfg.get("tokens") or {}) for t in tc.HOOK_TOOLS},
                "last_seen": {t: iso(seen.get(t)) for t in rm.TOOLS}}


@router.post("/api/hooks/install")
def hooks_install(body: InstallIn, request: Request, user: User = Depends(current_user_ro)) -> dict:
    """Connect every tool (MCP + standing instructions + hooks) to the project in the folder given."""
    import os

    from app import tool_connect as tc
    from app.db import SessionLocal

    folder = os.path.expanduser(body.project_dir.strip())
    if not os.path.isdir(folder):
        raise bad_request(f"That folder doesn't exist: {folder}")
    url = f"{request.url.scheme}://{request.url.netloc}/mcp"
    with SessionLocal() as db:
        u = db.get(User, user.id)
        room = _primary_room(db, u)
        results = tc.connect_all(db, room, u, url, project=folder)
    return {"project_dir": folder, "room": room.name, "results": results}
