"""Shared progress log (REST side): what every AI tool did, plus the handoff briefing preview."""

import uuid

from fastapi import APIRouter, Depends, Response
from pydantic import Field
from sqlalchemy.orm import Session

from app.auth import current_user, current_user_ro, get_membership
from app.db import get_db
from app.errors import bad_request, forbidden
from app.llm.base import LLMError
from app.models import Room, User
from app.schemas import _In
from app.serializers import actor_user
from app.services import context as context_svc
from app.services import chat as chat_svc
from app.services import demo as demo_svc

router = APIRouter(prefix="/api/rooms/{room_id}/context", tags=["context"])


class NoteIn(_In):
    summary: str = Field(min_length=1, max_length=4000)
    next_steps: str | None = Field(default=None, max_length=2000)


@router.get("")
def get_context(room_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    room, _ = get_membership(db, room_id, user)
    h = context_svc.build_handoff(db, room, for_name="the next AI tool")
    return {"entries": h["entries"], "handoff_markdown": h["markdown"]}


@router.post("", status_code=201)
def add_note(room_id: uuid.UUID, body: NoteIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    room, member = get_membership(db, room_id, user)
    e = context_svc.save_entry(
        db, room.id, author=user.display_name, tool="user", summary=body.summary, next_steps=body.next_steps,
        kind="note", actor=actor_user(user, member.role),
    )
    db.commit()
    return context_svc.entry_out(e)


@router.get("/demo")
def demo_status(room_id: uuid.UUID, user: User = Depends(current_user_ro), db: Session = Depends(get_db)) -> dict:
    get_membership(db, room_id, user)
    return {**demo_svc.status(room_id), "is_demo_room": db.get(Room, room_id).name == demo_svc.DEMO_ROOM_NAME}


class DemoStartIn(_In):
    scenario: str = "trip"


@router.post("/demo/start")
def demo_start(room_id: uuid.UUID, body: DemoStartIn | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    room, _ = get_membership(db, room_id, user)
    if room.name != demo_svc.DEMO_ROOM_NAME:
        raise forbidden("The live demo runs in the demo project.")
    db.commit()
    return {"started": demo_svc.start(room_id, (body.scenario if body else "trip"))}


@router.post("/demo/reset")
def demo_reset(room_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    room, _ = get_membership(db, room_id, user)
    if room.name != demo_svc.DEMO_ROOM_NAME:
        raise forbidden("Only the demo project can be reset.")
    db.commit()
    demo_svc.reset(room_id)
    return {"ok": True}


class ChatIn(_In):
    provider: str = Field(min_length=1, max_length=24)
    text: str = Field(min_length=1, max_length=6000)


@router.get("/chat")
def chat_state(room_id: uuid.UUID, user: User = Depends(current_user_ro), db: Session = Depends(get_db)) -> dict:
    get_membership(db, room_id, user)
    return chat_svc.state(db, room_id)


@router.post("/chat", status_code=202)
def chat_send(room_id: uuid.UUID, body: ChatIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    room, _ = get_membership(db, room_id, user)
    try:
        return chat_svc.send(db, room, user, body.provider, body.text)
    except LLMError as e:
        raise bad_request(str(e)) from None


@router.delete("/chat", status_code=204)
def chat_clear(room_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> Response:
    get_membership(db, room_id, user)
    from sqlalchemy import delete as _del

    from app.models import ChatMessage

    db.execute(_del(ChatMessage).where(ChatMessage.room_id == room_id))
    return Response(status_code=204)
