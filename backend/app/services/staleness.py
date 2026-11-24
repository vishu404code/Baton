"""Stale propagation. When a decision, brief or source gets a new revision, every output whose
current revision was based on an older revision of it, directly or through other outputs, is
marked stale. Outputs that don't depend on it are untouched (and reported as `unaffected`).

`find_affected` is pure (no writes), so the same walk powers the edit preview.
"""

from __future__ import annotations

import uuid
from collections import deque
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Approval, Claim, Dependency, Record, Revision, utcnow
from app.services.events import SYSTEM_ACTOR, append_event
from app.services.ledger import label, record_ref, rev_label

OUTPUTS = ("draft", "review")
# Editing one of these can make outputs stale (tasks are instructions, not inputs).
SOURCES_OF_TRUTH = ("brief", "decision", "source")


@dataclass
class Affected:
    record: Record
    revision: Revision
    path: list[str] = field(default_factory=list)  # e.g. ["Decision 2 v1", "Draft 2 v1", "Review 1 v1"]
    reason: str = ""


def _old_revision_ids(db: Session, record: Record, *, preview: bool) -> list[uuid.UUID]:
    """Revisions that are (or, in a preview, are about to become) out of date."""
    stmt = select(Revision.id).where(Revision.record_id == record.id)
    if not preview:
        stmt = stmt.where(Revision.id != record.current_revision_id)
    return list(db.execute(stmt).scalars())


def find_affected(db: Session, record: Record, *, preview: bool = False) -> list[Affected]:
    """Breadth-first walk from the outdated revisions of `record` to dependent current outputs."""
    next_number = record.current_revision + (1 if preview else 0)

    frontier: deque[tuple[uuid.UUID, list[str]]] = deque()
    for rid in _old_revision_ids(db, record, preview=preview):
        rev = db.get(Revision, rid)
        frontier.append((rid, [rev_label(record, rev.number)]))

    seen: set[uuid.UUID] = set()
    found: dict[uuid.UUID, Affected] = {}
    while frontier:
        target_id, path = frontier.popleft()
        dependents = db.execute(
            select(Revision, Record)
            .join(Dependency, Dependency.from_revision_id == Revision.id)
            .join(Record, Record.id == Revision.record_id)
            .where(Dependency.to_revision_id == target_id)  # based_on and cites both count
        ).all()
        for rev, rec in dependents:
            if rev.id in seen:
                continue
            seen.add(rev.id)
            # Only the current revision of an output matters; superseded ones are history.
            if rec.type not in OUTPUTS or rec.current_revision_id != rev.id:
                continue
            new_path = path + [rev_label(rec, rev.number)]
            if rec.id not in found:
                if len(path) == 1:
                    reason = f"based on {path[0]}, now v{next_number}"
                else:
                    reason = f"based on {path[-1]}, which is stale ({path[0]}, now v{next_number})"
                found[rec.id] = Affected(rec, rev, new_path, reason)
            frontier.append((rev.id, new_path))
    return list(found.values())


def unaffected_outputs(db: Session, room_id: uuid.UUID, affected: list[Affected]) -> list[Record]:
    skip = {a.record.id for a in affected}
    rows = db.execute(
        select(Record).where(Record.room_id == room_id, Record.type.in_(OUTPUTS)).order_by(Record.type, Record.number)
    ).scalars().all()
    return [r for r in rows if r.id not in skip and r.status != "stale"]


def affected_out(db: Session, a: Affected) -> dict:
    task = db.get(Record, a.record.parent_task_id) if a.record.parent_task_id else None
    return {
        "record_id": str(a.record.id),
        "label": label(a.record),
        "type": a.record.type,
        "title": a.record.title,
        "revision": a.revision.number,
        "task_id": str(task.id) if task else None,
        "task_label": label(task) if task else None,
        "status_before": a.record.status,
        "reason": a.reason,
        "path": a.path,
    }


def unaffected_out(db: Session, r: Record) -> dict:
    task = db.get(Record, r.parent_task_id) if r.parent_task_id else None
    return {
        "record_id": str(r.id),
        "label": label(r),
        "type": r.type,
        "title": r.title,
        "revision": r.current_revision,
        "task_id": str(task.id) if task else None,
        "task_label": label(task) if task else None,
        "status": r.status,
    }


def propagate(db: Session, record: Record, from_revision: int, to_revision: int) -> list[dict]:
    """Mark everything affected by `record`'s new revision as stale. Emits one record.stale each."""
    affected = [a for a in find_affected(db, record) if a.record.status != "stale"]
    now = utcnow()
    results = []
    for a in affected:
        out = affected_out(db, a)
        a.record.status = "stale"
        task = db.get(Record, a.record.parent_task_id) if a.record.parent_task_id else None
        if task is not None:
            claim = db.execute(
                select(Claim).where(Claim.task_id == task.id, Claim.status == "active")
            ).scalar_one_or_none()
            if claim is not None:
                claim.is_redo = True  # the holder keeps working; releasing returns the task to stale
            else:
                task.status = "stale"
        # A pending approval for work that just went stale can no longer be approved.
        for approval in db.execute(
            select(Approval).where(Approval.revision_id == a.revision.id, Approval.status == "pending")
        ).scalars():
            approval.status = "rejected"
            approval.decided_at = now
            approval.comment = f"Closed automatically: {a.reason}."
            append_event(
                db, record.room_id, "approval.decided", SYSTEM_ACTOR,
                f"Approval for {rev_label(a.record, a.revision.number)} closed: it went stale",
                {"approval": {"id": str(approval.id), "status": "rejected", "comment": approval.comment, "automatic": True}},
                record_ids=[a.record.id] + ([task.id] if task else []),
            )
        append_event(
            db,
            record.room_id,
            "record.stale",
            SYSTEM_ACTOR,
            f"{rev_label(a.record, a.revision.number)} marked stale ({a.reason})",
            {
                "record": record_ref(a.record) | {"type": a.record.type},
                "revision": a.revision.number,
                "task": record_ref(task) if task else None,
                "reason": a.reason,
                "caused_by": {"record": record_ref(record), "from_revision": from_revision, "to_revision": to_revision},
                "path": a.path,
            },
            record_ids=[a.record.id, record.id] + ([task.id] if task else []),
        )
        results.append(out)
    return results


def mark_if_built_on_outdated(db: Session, output: Record, rev: Revision) -> str | None:
    """After a late apply (crash resume), flag the new revision if an input changed meanwhile."""
    for rid in rev.based_on or []:
        base = db.get(Revision, uuid.UUID(str(rid)))
        if base is None:
            continue
        rec = db.get(Record, base.record_id)
        if rec.id != output.id and rec.current_revision_id != base.id:
            return f"based on {rev_label(rec, base.number)}, now v{rec.current_revision}"
    return None
