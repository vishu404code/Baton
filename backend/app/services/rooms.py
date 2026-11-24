"""Rooms, invite codes, membership and agents. Shared by the REST API and scripts/seed_demo.py."""

from __future__ import annotations

import re
import secrets

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import AGENT_PREFIX, new_token
from app.config import get_settings
from app.models import Agent, Claim, Record, Room, RoomMember, User, utcnow
from app.serializers import AGENT_COLORS, actor_agent, actor_user, agent_out, user_out
from app.services.events import append_event

_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I


def default_settings() -> dict:
    s = get_settings()
    return {
        "checks": {"citations_present": True, "sources_exist": True, "content_schema": True},
        "min_sources": s.baton_default_min_sources,
        "lease_minutes": s.baton_default_lease_minutes,
        "require_approval": s.baton_default_require_approval,
    }


def normalize_code(code: str) -> str:
    return code.strip().upper()


def new_invite_code(db: Session, room_name: str) -> str:
    prefix = re.sub(r"[^A-Z0-9]", "", (room_name.split() or ["ROOM"])[0].upper())[:6] or "ROOM"
    while True:
        code = f"{prefix}-{''.join(secrets.choice(_CODE_ALPHABET) for _ in range(4))}"
        if db.execute(select(Room.id).where(Room.invite_code == code)).first() is None:
            return code


def create_room(db: Session, owner: User, name: str, *, is_demo: bool = False, invite_code: str | None = None) -> Room:
    room = Room(
        name=name,
        invite_code=invite_code or new_invite_code(db, name),
        owner_id=owner.id,
        settings=default_settings(),
        is_demo=is_demo,
    )
    db.add(room)
    db.flush()
    db.add(RoomMember(room_id=room.id, user_id=owner.id, role="owner"))
    db.flush()
    append_event(
        db,
        room.id,
        "member.joined",
        actor_user(owner, "owner"),
        f"{owner.display_name} created the room",
        {"user": user_out(owner), "role": "owner"},
    )
    return room


def add_member(db: Session, room: Room, user: User, role: str = "member") -> tuple[RoomMember, bool]:
    """Add a member. Returns (membership, created). Joining twice is a no-op."""
    existing = db.get(RoomMember, (room.id, user.id))
    if existing:
        return existing, False
    member = RoomMember(room_id=room.id, user_id=user.id, role=role)
    db.add(member)
    db.flush()
    append_event(
        db,
        room.id,
        "member.joined",
        actor_user(user, role),
        f"{user.display_name} joined the room",
        {"user": user_out(user), "role": role},
    )
    return member, True


def update_settings(room: Room, patch: dict) -> list[str]:
    """Apply a partial settings patch; return the changed keys (dotted for checks)."""
    current = {**default_settings(), **(room.settings or {})}
    checks = dict(current.get("checks", {}))
    changed: list[str] = []
    for name, value in (patch.get("checks") or {}).items():
        if value is not None and checks.get(name) != value:
            checks[name] = value
            changed.append(f"checks.{name}")
    current["checks"] = checks
    for key in ("min_sources", "lease_minutes", "require_approval"):
        value = patch.get(key)
        if value is not None and current.get(key) != value:
            current[key] = value
            changed.append(key)
    room.settings = current  # reassign so SQLAlchemy sees the JSONB change
    return changed


def create_agent(db: Session, room: Room, owner: User, name: str, tool: str, role: str) -> tuple[Agent, str]:
    """Create an agent and return it with its plaintext token (shown once; only the hash is stored)."""
    token, token_hash = new_token(AGENT_PREFIX)
    n = db.execute(select(func.count()).select_from(Agent).where(Agent.room_id == room.id)).scalar_one()
    agent = Agent(
        room_id=room.id,
        user_id=owner.id,
        name=name,
        tool=tool,
        role=role,
        color=AGENT_COLORS[n % len(AGENT_COLORS)],
        token_hash=token_hash,
    )
    db.add(agent)
    db.flush()
    append_event(
        db,
        room.id,
        "agent.created",
        actor_user(owner),
        f"{owner.display_name} added agent {name} ({tool}, {role})",
        {"agent": agent_out(db, agent, owner.display_name)},
    )
    return agent, token


def revoke_agent(db: Session, room: Room, agent: Agent, by: User, by_role: str) -> None:
    now = utcnow()
    agent.revoked_at = now
    active = db.execute(select(Claim).where(Claim.agent_id == agent.id, Claim.status == "active")).scalars().all()
    owner_name = db.get(User, agent.user_id).display_name
    for claim in active:
        claim.status = "released"
        claim.ended_at = now
        task = db.get(Record, claim.task_id)
        if task is not None and task.status == "claimed":
            task.status = "open"
        append_event(
            db,
            room.id,
            "task.released",
            actor_user(by, by_role),
            f"{agent.name}'s claim on Task {task.number if task else '?'} was released (agent revoked)",
            {
                "task": {"id": str(claim.task_id), "label": f"Task {task.number}" if task else None, "title": task.title if task else None},
                "agent": actor_agent(agent, owner_name),
                "reason": "revoked",
            },
            record_ids=[claim.task_id],
        )
    append_event(
        db,
        room.id,
        "agent.revoked",
        actor_user(by, by_role),
        f"{by.display_name} revoked agent {agent.name}",
        {"agent_id": str(agent.id)},
    )
