"""Shared progress log (REST side): what every AI tool did, plus the handoff briefing preview."""

import uuid

from fastapi import APIRouter, Depends
from pydantic import Field
from sqlalchemy.orm import Session

from app.auth import current_user, get_membership
from app.db import get_db
from app.models import User
from app.schemas import _In
from app.serializers import actor_user
from app.services import context as context_svc

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
