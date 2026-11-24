"""First launch of the desktop app: one local owner, a starter project and two offline demo agents,
so everything works before any API key is added."""

from __future__ import annotations

from sqlalchemy import select

from app.models import Room, RoomMember, User
from app.serializers import actor_user
from app.services import ledger
from app.services import rooms as room_svc
from app.services.events import append_event


def _add(db, room, user, type_, title, content):
    rec, rev = ledger.create_record(
        db, room.id, type_, title, content, author_user_id=user.id, status="open" if type_ == "task" else "approved"
    )
    append_event(db, room.id, "revision.created", actor_user(user, "owner"),
                 f"{user.display_name} created {ledger.label(rec)} \"{rec.title}\"",
                 {"record": ledger.record_ref(rec) | {"type": type_}}, record_ids=[rec.id])
    if type_ == "task":
        append_event(db, room.id, "task.created", actor_user(user, "owner"),
                     f"{user.display_name} created {ledger.label(rec)} \"{rec.title}\" for a {content['role']}",
                     {"task": ledger.record_ref(rec)}, record_ids=[rec.id])
    return rec


def ensure_local_workspace(db) -> tuple[User, Room]:
    user = db.execute(select(User).order_by(User.created_at).limit(1)).scalar_one_or_none()
    if user is not None:
        room = db.execute(
            select(Room).join(RoomMember, RoomMember.room_id == Room.id).where(RoomMember.user_id == user.id).order_by(Room.created_at).limit(1)
        ).scalar_one_or_none()
        if room is not None:
            return user, room

    user = user or User(display_name="You")
    db.add(user)
    db.flush()
    room = room_svc.create_room(db, user, "My Project")
    _add(db, room, user, "brief", "Product launch brief", {"body": "Plan the launch of our new app. Keep the plan short, practical and specific."})
    _add(db, room, user, "decision", "Launch date", {"statement": "We launch on 15 January.", "rationale": "Before the spring term starts."})
    _add(db, room, user, "decision", "Audience", {"statement": "The first audience is university students.", "rationale": "They are our early adopters."})
    _add(db, room, user, "source", "Market notes", {"text": "Students prefer apps that work on phones and share well in group chats."})
    plan = _add(db, room, user, "task", "Write the launch plan", {"description": "Write a short launch plan with dates, channels and owners.", "role": "planner"})
    _add(db, room, user, "task", "Review the launch plan",
         {"description": "Check the plan against the brief and every decision. Give a verdict and comments.", "role": "reviewer", "review_of_task_id": str(plan.id)})
    room_svc.create_agent(db, room, user, "Demo planner", "other", "planner", "mock", "demo-1")
    room_svc.create_agent(db, room, user, "Demo reviewer", "other", "reviewer", "mock", "demo-1")
    db.commit()
    return user, room
