"""Session tokens (bs_) for humans, agent tokens (bat_) for MCP. Only SHA-256 hashes are stored."""

from __future__ import annotations

import hashlib
import secrets
import uuid

from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import ApiError, forbidden, not_found
from app.models import Agent, Room, RoomMember, User, UserSession

SESSION_PREFIX = "bs_"
AGENT_PREFIX = "bat_"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_token(prefix: str) -> tuple[str, str]:
    token = prefix + secrets.token_urlsafe(32)
    return token, hash_token(token)


def bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return None
    return value.strip()


def user_from_token(db: Session, token: str | None) -> User | None:
    if not token or not token.startswith(SESSION_PREFIX):
        return None
    row = db.execute(
        select(User).join(UserSession, UserSession.user_id == User.id).where(UserSession.token_hash == hash_token(token))
    ).scalar_one_or_none()
    return row


def agent_from_token(db: Session, token: str | None) -> Agent | None:
    if not token or not token.startswith(AGENT_PREFIX):
        return None
    return db.execute(
        select(Agent).where(Agent.token_hash == hash_token(token), Agent.revoked_at.is_(None))
    ).scalar_one_or_none()


def current_user(authorization: str | None = Header(default=None), db: Session = Depends(get_db)) -> User:
    token = bearer(authorization)
    if token and token.startswith(AGENT_PREFIX):
        raise ApiError(401, "Agent tokens only work on /mcp. Use a session token from POST /api/session.")
    user = user_from_token(db, token)
    if user is None:
        raise ApiError(401, "Missing or invalid session token. Sign in with POST /api/session.")
    return user


def get_membership(db: Session, room_id: uuid.UUID, user: User) -> tuple[Room, RoomMember]:
    """Return the room and the caller's membership; 404 if either is missing (don't leak rooms)."""
    row = db.execute(
        select(Room, RoomMember)
        .join(RoomMember, RoomMember.room_id == Room.id)
        .where(Room.id == room_id, RoomMember.user_id == user.id)
    ).first()
    if row is None:
        raise not_found("Room not found, or you are not a member.")
    return row[0], row[1]


def is_mentor(member: RoomMember) -> bool:
    return member.role in ("owner", "mentor")


def require_mentor(member: RoomMember, action: str) -> None:
    if not is_mentor(member):
        raise forbidden(f"Only the owner or a mentor can {action}.")
