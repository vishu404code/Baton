"""Append-only ledger: records and their revisions. Nothing is ever overwritten.

Each change appends revision N+1 and moves the record's current pointer. `based_on`
links are stored on the revision and mirrored into `dependencies` for graph queries.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import AgentError
from app.models import Dependency, Record, Revision, Room, utcnow

TYPE_LABEL = {
    "brief": "Brief",
    "decision": "Decision",
    "task": "Task",
    "source": "Source",
    "draft": "Draft",
    "review": "Review",
}
MENTOR_TYPES = ("brief", "decision", "task", "source")
_LABEL_RE = re.compile(r"^\s*(brief|decision|task|source|draft|review)\s*#?\s*(\d+)\s*$", re.IGNORECASE)


def label(record: Record) -> str:
    return f"{TYPE_LABEL[record.type]} {record.number}"


def rev_label(record: Record, number: int) -> str:
    return f"{label(record)} v{number}"


def record_ref(record: Record) -> dict:
    return {"id": str(record.id), "label": label(record), "title": record.title}


# --- Content rules (also used by the content_schema check) -------------------------------


def _text(v) -> bool:
    return isinstance(v, str) and v.strip() != ""


def content_problems(type_: str, content) -> list[str]:
    """Return a list of human-readable problems; empty means valid."""
    if not isinstance(content, dict):
        return ["content must be a JSON object"]
    p: list[str] = []
    if type_ in ("brief", "draft"):
        if not _text(content.get("body")):
            p.append("missing required field: body (markdown text)")
    elif type_ == "decision":
        if not _text(content.get("statement")):
            p.append("missing required field: statement")
    elif type_ == "source":
        if not (_text(content.get("url")) or _text(content.get("text"))):
            p.append("a source needs url or text")
    elif type_ == "task":
        if not _text(content.get("description")):
            p.append("missing required field: description")
        if content.get("role") not in ("planner", "reviewer"):
            p.append("role must be 'planner' or 'reviewer'")
    elif type_ == "review":
        if content.get("verdict") not in ("approve", "request_changes"):
            p.append("verdict must be 'approve' or 'request_changes'")
        if not _text(content.get("comments")):
            p.append("missing required field: comments (non-empty)")
    return p


def required_fields(type_: str) -> str:
    return {
        "brief": "body",
        "draft": "body",
        "decision": "statement",
        "source": "url or text",
        "task": "description, role",
        "review": "verdict, comments",
    }[type_]


# --- Lookup -------------------------------------------------------------------------------


def resolve_record(db: Session, room_id: uuid.UUID, ref: str | uuid.UUID, type_: str | None = None) -> Record:
    """Find a record by UUID or by label ("Decision 2", "task 1"). Raises AgentError if not found."""
    record: Record | None = None
    ref_s = str(ref).strip()
    m = _LABEL_RE.match(ref_s)
    if m:
        record = db.execute(
            select(Record).where(
                Record.room_id == room_id, Record.type == m.group(1).lower(), Record.number == int(m.group(2))
            )
        ).scalar_one_or_none()
    else:
        try:
            rid = uuid.UUID(ref_s)
        except ValueError:
            raise AgentError("not_found", f"{ref_s!r} is not a record ID or label like 'Decision 2'.")
        record = db.get(Record, rid)
        if record is not None and record.room_id != room_id:
            record = None
    if record is None:
        raise AgentError("not_found", f"{ref_s} not found in this room. Call list_tasks or get_room_context to see what exists.")
    if type_ and record.type != type_:
        raise AgentError("bad_request", f"{label(record)} is a {record.type}, not a {type_}.")
    return record


def current_revision(db: Session, record: Record) -> Revision | None:
    return db.get(Revision, record.current_revision_id) if record.current_revision_id else None


def get_revision(db: Session, record: Record, number: int) -> Revision | None:
    return db.execute(
        select(Revision).where(Revision.record_id == record.id, Revision.number == number)
    ).scalar_one_or_none()


def latest(db: Session, room_id: uuid.UUID, type_: str) -> Record | None:
    return db.execute(
        select(Record).where(Record.room_id == room_id, Record.type == type_).order_by(Record.number.desc()).limit(1)
    ).scalar_one_or_none()


def output_of(db: Session, task: Record) -> Record | None:
    """The draft/review record a task produced (one per task)."""
    return db.execute(
        select(Record).where(Record.parent_task_id == task.id).order_by(Record.created_at).limit(1)
    ).scalar_one_or_none()


# --- Writes -------------------------------------------------------------------------------


def _next_number(db: Session, room_id: uuid.UUID, type_: str) -> int:
    # Lock the room row so concurrent creates in one room get distinct numbers.
    db.execute(select(Room.id).where(Room.id == room_id).with_for_update())
    n = db.execute(
        select(func.max(Record.number)).where(Record.room_id == room_id, Record.type == type_)
    ).scalar_one_or_none()
    return (n or 0) + 1


def _add_dependencies(db: Session, rev: Revision, based_on: Iterable[str], source_revision_ids: Iterable[str]) -> None:
    seen: set[tuple[str, str]] = set()
    for kind, ids in (("based_on", based_on), ("cites", source_revision_ids)):
        for rid in ids:
            key = (kind, str(rid))
            if key in seen:
                continue
            seen.add(key)
            db.add(Dependency(from_revision_id=rev.id, to_revision_id=uuid.UUID(str(rid)), kind=kind))


def create_record(
    db: Session,
    room_id: uuid.UUID,
    type_: str,
    title: str,
    content: dict,
    *,
    author_user_id: uuid.UUID | None = None,
    author_agent_id: uuid.UUID | None = None,
    status: str = "approved",
    parent_task_id: uuid.UUID | None = None,
    based_on: Iterable[str] = (),
    source_ids: Iterable[str] = (),
    submission_id: uuid.UUID | None = None,
    note: str | None = None,
    number: int | None = None,
) -> tuple[Record, Revision]:
    now = utcnow()
    record = Record(
        room_id=room_id,
        type=type_,
        number=number if number is not None else _next_number(db, room_id, type_),
        title=title,
        status=status,
        current_revision=0,
        parent_task_id=parent_task_id,
        created_at=now,
        updated_at=now,
    )
    db.add(record)
    db.flush()
    rev = append_revision(
        db,
        record,
        content,
        title=title,
        author_user_id=author_user_id,
        author_agent_id=author_agent_id,
        based_on=based_on,
        source_ids=source_ids,
        submission_id=submission_id,
        note=note,
    )
    return record, rev


def append_revision(
    db: Session,
    record: Record,
    content: dict,
    *,
    title: str | None = None,
    author_user_id: uuid.UUID | None = None,
    author_agent_id: uuid.UUID | None = None,
    based_on: Iterable[str] = (),
    source_ids: Iterable[str] = (),
    submission_id: uuid.UUID | None = None,
    note: str | None = None,
) -> Revision:
    based_on = [str(b) for b in based_on]
    source_ids = [str(s) for s in source_ids]
    # Sources are cited at their current revision.
    source_revs = []
    for sid in source_ids:
        src = db.get(Record, uuid.UUID(sid))
        if src is not None and src.current_revision_id:
            source_revs.append(str(src.current_revision_id))

    number = record.current_revision + 1
    rev = Revision(
        record_id=record.id,
        number=number,
        title=title or record.title,
        content=content,
        author_user_id=author_user_id,
        author_agent_id=author_agent_id,
        based_on=based_on,
        source_ids=source_ids,
        submission_id=submission_id,
        note=note,
        created_at=utcnow(),
    )
    db.add(rev)
    db.flush()
    _add_dependencies(db, rev, based_on, source_revs)
    record.current_revision = number
    record.current_revision_id = rev.id
    if title:
        record.title = title
    record.updated_at = rev.created_at
    db.flush()
    return rev
