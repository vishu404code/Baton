"""Evidence endpoints. Milestone 2: the event log. Trace and recovery arrive in milestone 6."""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import current_user, get_membership
from app.db import get_db
from app.models import Event, User
from app.services.events import event_out

router = APIRouter(prefix="/api", tags=["evidence"])


@router.get("/rooms/{room_id}/events")
def list_events(
    room_id: uuid.UUID,
    since_seq: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    types: str | None = None,
    record_id: uuid.UUID | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    room, _ = get_membership(db, room_id, user)
    stmt = select(Event).where(Event.room_id == room_id, Event.seq > since_seq)
    if types:
        stmt = stmt.where(Event.type.in_([t.strip() for t in types.split(",") if t.strip()]))
    stmt = stmt.order_by(Event.seq)
    if record_id:
        # record_ids is a JSON list; filter in Python (a room's event log is small on one device)
        rows = [e for e in db.execute(stmt).scalars() if str(record_id) in (e.record_ids or [])]
    else:
        rows = db.execute(stmt.limit(limit + 1)).scalars().all()
    has_more = len(rows) > limit
    return {"events": [event_out(e) for e in rows[:limit]], "latest_seq": room.last_seq, "has_more": has_more}


@router.get("/rooms/{room_id}/presence")
def get_presence(room_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    from app.services import presence

    get_membership(db, room_id, user)
    return presence.snapshot(room_id)


@router.get("/rooms/{room_id}/recovery")
def get_recovery(room_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    from app.services import evidence

    get_membership(db, room_id, user)
    return {"items": evidence.recovery(db, room_id)}


@router.get("/records/{record_id}/trace")
def get_trace(
    record_id: uuid.UUID,
    revision: int | None = Query(None, ge=1),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    from app.errors import not_found
    from app.models import Record
    from app.services import evidence

    record = db.get(Record, record_id)
    if record is None:
        raise not_found("Record not found.")
    get_membership(db, record.room_id, user)
    return evidence.trace(db, record, revision)
