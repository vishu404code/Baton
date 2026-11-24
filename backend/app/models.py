"""Baton data model. See docs/ARCHITECTURE.md.

All tables are created in milestone 2 so later milestones only add behaviour.
Revisions, events, verification results and dependencies are append-only.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    JSON,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
    Uuid,
    false,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """Timezone-aware UTC datetimes on SQLite.

    Stored as fixed-width ISO-8601 text (microseconds, +00:00), so SQL comparisons and ORDER BY on
    the text behave exactly like real timestamps, and values read back timezone-aware.
    """

    impl = String(32)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f+00:00")

    def process_result_value(self, value, dialect):
        return None if value is None else datetime.fromisoformat(value)


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


def _ts(nullable: bool = False) -> Mapped[datetime]:
    return mapped_column(UTCDateTime, nullable=nullable, default=None if nullable else utcnow)


# --- Enumerations (stored as strings, validated in code) ---------------------------------
MEMBER_ROLES = ("owner", "mentor", "member")
AGENT_TOOLS = ("claude_code", "codex", "gemini_cli", "cursor", "antigravity", "other")
AGENT_ROLES = ("planner", "reviewer", "observer")
RECORD_TYPES = ("brief", "decision", "task", "source", "draft", "review")
RECORD_STATUSES = ("open", "claimed", "in_review", "approved", "stale", "rejected")
OUTPUT_TYPES = ("draft", "review")
CLAIM_STATUSES = ("active", "released", "expired")
SUBMISSION_STATUSES = ("saved", "completed", "rejected")
APPROVAL_STATUSES = ("pending", "approved", "rejected")


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = _uuid_pk()
    display_name: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = _ts()


class UserSession(Base):
    __tablename__ = "user_sessions"
    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = _ts()


class Room(Base):
    __tablename__ = "rooms"
    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(80))
    invite_code: Mapped[str] = mapped_column(String(32), unique=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    # Last allocated event sequence number. Incremented under a row lock (services/events.py).
    last_seq: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    created_at: Mapped[datetime] = _ts()


class RoomMember(Base):
    __tablename__ = "room_members"
    room_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rooms.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True)
    role: Mapped[str] = mapped_column(String(16))
    joined_at: Mapped[datetime] = _ts()


class Agent(Base):
    __tablename__ = "agents"
    id: Mapped[uuid.UUID] = _uuid_pk()
    room_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rooms.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(60))
    tool: Mapped[str] = mapped_column(String(16))
    role: Mapped[str] = mapped_column(String(16))
    color: Mapped[str] = mapped_column(String(7))
    # Set for agents Baton runs itself through an AI provider's API (Claude, ChatGPT, DeepSeek, Gemini, demo).
    provider: Mapped[str | None] = mapped_column(String(16), nullable=True)
    model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    last_seen_at: Mapped[datetime | None] = _ts(nullable=True)
    revoked_at: Mapped[datetime | None] = _ts(nullable=True)
    created_at: Mapped[datetime] = _ts()


class Record(Base):
    __tablename__ = "records"
    __table_args__ = (UniqueConstraint("room_id", "type", "number", name="uq_records_room_type_number"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    room_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rooms.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(16))
    number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(16))
    current_revision: Mapped[int] = mapped_column(Integer, default=0)
    current_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("revisions.id", name="fk_records_current_revision"), nullable=True
    )
    parent_task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("records.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts()


class Revision(Base):
    __tablename__ = "revisions"
    __table_args__ = (UniqueConstraint("record_id", "number", name="uq_revisions_record_number"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    record_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("records.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[dict] = mapped_column(JSON)
    author_agent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agents.id"), nullable=True)
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    # Exact revision IDs this revision was based on, and the source record IDs it cites.
    based_on: Mapped[list] = mapped_column(JSON, default=list)
    source_ids: Mapped[list] = mapped_column(JSON, default=list)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    submission_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("submissions.id", name="fk_revisions_submission"), nullable=True
    )
    created_at: Mapped[datetime] = _ts()


class Dependency(Base):
    """Edge from an output revision to a revision it was based on (or a source it cites)."""

    __tablename__ = "dependencies"
    from_revision_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("revisions.id", ondelete="CASCADE"), primary_key=True)
    to_revision_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("revisions.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    kind: Mapped[str] = mapped_column(String(16), primary_key=True)  # based_on | cites


class Claim(Base):
    __tablename__ = "claims"
    __table_args__ = (
        # Two agents can never hold the same task: at most one active claim per task.
        Index("uq_claims_one_active_per_task", "task_id", unique=True, postgresql_where=text("status = 'active'"), sqlite_where=text("status = 'active'")),
    )
    id: Mapped[uuid.UUID] = _uuid_pk()
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("records.id", ondelete="CASCADE"), index=True)
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(16))
    lease_expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    # True when the task was stale when claimed, so the redo needs human approval.
    is_redo: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    created_at: Mapped[datetime] = _ts()
    ended_at: Mapped[datetime | None] = _ts(nullable=True)


class Submission(Base):
    __tablename__ = "submissions"
    id: Mapped[uuid.UUID] = _uuid_pk()
    room_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rooms.id", ondelete="CASCADE"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("records.id", ondelete="CASCADE"), index=True)
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    base_revision_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("revisions.id"), nullable=True)
    based_on: Mapped[list] = mapped_column(JSON, default=list)
    source_ids: Mapped[list] = mapped_column(JSON, default=list)
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16))
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_revision_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("revisions.id"), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    resumed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    interrupted: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    created_at: Mapped[datetime] = _ts()
    saved_at: Mapped[datetime | None] = _ts(nullable=True)
    completed_at: Mapped[datetime | None] = _ts(nullable=True)


class VerificationResult(Base):
    __tablename__ = "verification_results"
    id: Mapped[uuid.UUID] = _uuid_pk()
    submission_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("submissions.id", ondelete="CASCADE"), index=True)
    check_name: Mapped[str] = mapped_column(String(32))
    order: Mapped[int] = mapped_column(Integer)
    passed: Mapped[bool] = mapped_column(Boolean)
    skipped: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    detail: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = _ts()


class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[uuid.UUID] = _uuid_pk()
    room_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rooms.id", ondelete="CASCADE"), index=True)
    revision_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("revisions.id", ondelete="CASCADE"), index=True)
    record_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("records.id", ondelete="CASCADE"))
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("records.id", ondelete="CASCADE"))
    reason: Mapped[str] = mapped_column(String(32))  # require_approval | redo_of_stale
    status: Mapped[str] = mapped_column(String(16), default="pending")
    requested_at: Mapped[datetime] = _ts()
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = _ts(nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)


class Comment(Base):
    __tablename__ = "comments"
    id: Mapped[uuid.UUID] = _uuid_pk()
    record_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("records.id", ondelete="CASCADE"), index=True)
    revision_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    author_agent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agents.id"), nullable=True)
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = _ts()


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (UniqueConstraint("room_id", "seq", name="uq_events_room_seq"),)
    id: Mapped[uuid.UUID] = _uuid_pk()
    room_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rooms.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(40), index=True)
    # Snapshot of who acted, in the Actor shape from the API contract.
    actor: Mapped[dict] = mapped_column(JSON)
    summary: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    # Record IDs this event touches, for GET /events?record_id= filtering.
    record_ids: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = _ts()


class ContextEntry(Base):
    """Shared progress log: what each AI tool (or the user) did and what should happen next.
    Every connected tool reads this at the start (get_handoff) and writes to it when it finishes."""

    __tablename__ = "context_entries"
    id: Mapped[uuid.UUID] = _uuid_pk()
    room_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rooms.id", ondelete="CASCADE"), index=True)
    author: Mapped[str] = mapped_column(String(80))
    tool: Mapped[str] = mapped_column(String(24))  # claude_code | codex | antigravity | gemini_cli | user | other
    kind: Mapped[str] = mapped_column(String(16), default="progress")  # progress | decision | question | note
    summary: Mapped[str] = mapped_column(Text)
    next_steps: Mapped[str | None] = mapped_column(Text, nullable=True)
    files: Mapped[list] = mapped_column(JSON, default=list)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    created_at: Mapped[datetime] = _ts()
