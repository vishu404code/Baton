"""Submitting work: verify, save, then apply. Exactly once per idempotency_key.

Step A (save): run the 7 checks (each streamed live as an event), then store the
  submission as `saved` (or `rejected`) with its check results. Committed.
Step B (apply): under a row lock, if still `saved`: create the output revision, update
  the task, request approval if needed, mark `completed`. Committed.

A retry with the same key never re-applies: `completed` returns the stored result,
`saved` (interrupted between A and B) is finished by running step B once.
"""

from __future__ import annotations

import time
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import AgentError
from app.models import Agent, Approval, Claim, Record, Revision, Room, Submission, VerificationResult, utcnow
from app.record_views import approval_out, revision_out, submission_out
from app.serializers import actor_agent
from app.services import claims as claim_svc
from app.services import ledger, staleness
from app.services.events import SYSTEM_ACTOR, append_event
from app.services.verification import CHECKS, CheckResult, Context, owner_name, run_checks


class SimulatedCrash(RuntimeError):
    """Raised by the crash demo between `saved` and `completed`."""


def _normalize_content(output_type: str, content) -> dict:
    if isinstance(content, str):
        return {"body": content} if output_type == "draft" else {"comments": content}
    return dict(content or {})


def submit(
    db: Session,
    agent: Agent,
    task_ref: str,
    content,
    based_on: list[str],
    sources: list[str],
    idempotency_key: str,
    title: str | None = None,
    *,
    crash_after_save: bool = False,
) -> dict:
    key = (idempotency_key or "").strip()
    if not key:
        raise AgentError("bad_request", "idempotency_key is required: pick a unique string and reuse it if you retry.")

    existing = db.execute(select(Submission).where(Submission.idempotency_key == key)).scalar_one_or_none()
    if existing is not None:
        return _retry(db, agent, existing)

    task = ledger.resolve_record(db, agent.room_id, task_ref, "task")
    room = db.get(Room, agent.room_id)
    task_content = ledger.current_revision(db, task).content or {}
    output_type = "review" if task_content.get("role") == "reviewer" else "draft"
    content = _normalize_content(output_type, content)
    owner = owner_name(db, agent)
    actor = actor_agent(agent, owner)
    sub_id = uuid.uuid4()

    ctx = Context(
        db=db,
        room=room,
        agent=agent,
        task=task,
        task_content=task_content,
        output_type=output_type,
        output=ledger.output_of(db, task),
        claim=claim_svc.active_claim(db, task),
        content=content,
        based_on=[str(b) for b in (based_on or [])],
        source_refs=[str(s) for s in (sources or [])],
    )
    db.commit()  # persist any lease expiry found while loading the claim

    delay = get_settings().baton_check_delay_ms / 1000

    def stream(res: CheckResult) -> None:
        append_event(
            db,
            room.id,
            "verification.check",
            actor,
            f"{agent.name} · {ledger.label(task)} · {res.name} "
            + ("skipped" if res.skipped else "passed" if res.passed else f"FAILED: {res.detail}"),
            {
                "submission_id": str(sub_id),
                "task": ledger.record_ref(task),
                "agent": actor,
                "check": res.out(),
                "total_checks": len(CHECKS),
            },
            record_ids=[task.id],
        )
        db.commit()  # each check is visible to the room as soon as it runs
        if delay:
            time.sleep(delay)

    results = run_checks(ctx, stream)
    failed = next((r for r in results if not r.passed), None)
    now = utcnow()

    sub = Submission(
        id=sub_id,
        room_id=room.id,
        idempotency_key=key,
        task_id=task.id,
        agent_id=agent.id,
        base_revision_id=ctx.base_revision_id,
        based_on=ctx.based_on,
        source_ids=ctx.resolved_source_ids,
        payload={"title": title, "content": content, "is_redo": bool(ctx.claim and ctx.claim.is_redo)},
        status="rejected" if failed else "saved",
        rejection_reason=failed.detail if failed else None,
        created_at=now,
        saved_at=None if failed else now,
    )
    db.add(sub)
    try:
        db.flush()
    except IntegrityError:
        # Same key raced in from a parallel retry: treat this call as the retry.
        db.rollback()
        existing = db.execute(select(Submission).where(Submission.idempotency_key == key)).scalar_one()
        return _retry(db, agent, existing)
    for r in results:
        db.add(
            VerificationResult(
                submission_id=sub.id, check_name=r.name, order=r.order, passed=r.passed, skipped=r.skipped, detail=r.detail
            )
        )
    db.flush()

    if failed:
        append_event(
            db,
            room.id,
            "submission.rejected",
            actor,
            f"{agent.name}'s submission for {ledger.label(task)} was rejected: {failed.detail}",
            {"submission": submission_out(db, sub), "failed_check": failed.name, "reason": failed.detail},
            record_ids=[task.id],
        )
        db.commit()
        return _result(db, sub, message=f"Rejected by {failed.name}: {failed.detail}")

    append_event(
        db,
        room.id,
        "submission.saved",
        actor,
        f"{agent.name}'s submission for {ledger.label(task)} passed all checks and was saved",
        {"submission": submission_out(db, sub)},
        record_ids=[task.id],
    )
    db.commit()  # ---- durable point: `saved` ----

    if crash_after_save:
        raise SimulatedCrash(f"simulated crash after saving submission {sub.id}")

    apply_submission(db, sub.id)
    db.refresh(sub)
    return _result(db, sub)


def record_crash(db: Session, agent: Agent, idempotency_key: str) -> Submission:
    """Crash demo: note that the agent died after `saved` and before `completed`."""
    sub = db.execute(select(Submission).where(Submission.idempotency_key == idempotency_key)).scalar_one()
    task = db.get(Record, sub.task_id)
    sub.interrupted = True
    append_event(
        db,
        sub.room_id,
        "agent.crashed",
        actor_agent(agent, owner_name(db, agent)),
        f"{agent.name} crashed after its submission for {ledger.label(task)} was saved, before it was applied",
        {"agent": actor_agent(agent, owner_name(db, agent)), "submission_id": str(sub.id), "task": ledger.record_ref(task)},
        record_ids=[task.id],
    )
    db.commit()
    return sub


def _retry(db: Session, agent: Agent, sub: Submission) -> dict:
    if sub.agent_id != agent.id:
        raise AgentError("conflict", "idempotency_key already used by another agent; choose a different key.")
    task = db.get(Record, sub.task_id)
    actor = actor_agent(agent, owner_name(db, agent))
    sub = db.execute(select(Submission).where(Submission.id == sub.id).with_for_update()).scalar_one()
    sub.attempts += 1

    if sub.status == "saved":
        sub.resumed = True
        sub.interrupted = True
        append_event(
            db,
            sub.room_id,
            "submission.resumed",
            actor,
            f"{agent.name} retried with the same key; finishing its interrupted submission for {ledger.label(task)}",
            {
                "submission_id": str(sub.id),
                "idempotency_key": sub.idempotency_key,
                "attempt": sub.attempts,
                "previous_status": "saved",
            },
            record_ids=[task.id],
        )
        db.commit()
        apply_submission(db, sub.id)
        db.refresh(sub)
        return _result(db, sub, message="Resumed: your earlier submission was saved but not applied; it is now applied once.")

    if sub.status == "completed":
        append_event(
            db,
            sub.room_id,
            "submission.duplicate",
            actor,
            f"{agent.name} retried a completed submission for {ledger.label(task)}; nothing was applied twice",
            {"submission_id": str(sub.id), "idempotency_key": sub.idempotency_key, "attempt": sub.attempts},
            record_ids=[task.id],
        )
        db.commit()
        return _result(db, sub, message="Already applied earlier with this idempotency_key; returning the existing result.")

    db.commit()
    return _result(
        db,
        sub,
        message=f"This idempotency_key was already rejected ({sub.rejection_reason}). Fix the problem and submit with a NEW key.",
    )


def apply_submission(db: Session, submission_id: uuid.UUID) -> bool:
    """Step B. Applies a saved submission exactly once. Returns True if it applied now."""
    sub = db.execute(select(Submission).where(Submission.id == submission_id).with_for_update()).scalar_one()
    if sub.status != "saved":
        db.rollback()
        return False

    task = db.execute(select(Record).where(Record.id == sub.task_id).with_for_update()).scalar_one()
    room = db.get(Room, sub.room_id)
    agent = db.get(Agent, sub.agent_id)
    actor = actor_agent(agent, owner_name(db, agent))
    task_content = ledger.current_revision(db, task).content or {}
    output_type = "review" if task_content.get("role") == "reviewer" else "draft"
    is_redo = bool(sub.payload.get("is_redo"))
    needs_approval = is_redo or bool(room.settings.get("require_approval", True))
    status = "in_review" if needs_approval else "approved"
    content = sub.payload["content"]
    title = sub.payload.get("title")

    output = ledger.output_of(db, task)
    if output is None:
        if not title:
            if output_type == "review" and task_content.get("review_of_task_id"):
                reviewed = db.get(Record, uuid.UUID(task_content["review_of_task_id"]))
                title = f"Review of {reviewed.title}" if reviewed else f"Review for {task.title}"
            else:
                title = task.title
        output, rev = ledger.create_record(
            db,
            room.id,
            output_type,
            title,
            content,
            author_agent_id=agent.id,
            status=status,
            parent_task_id=task.id,
            based_on=sub.based_on,
            source_ids=sub.source_ids,
            submission_id=sub.id,
            number=task.number,  # an output shares its task's number: Task 1 -> Draft 1, Task 2 -> Review 2
        )
    else:
        rev = ledger.append_revision(
            db,
            output,
            content,
            title=title,
            author_agent_id=agent.id,
            based_on=sub.based_on,
            source_ids=sub.source_ids,
            submission_id=sub.id,
        )
        output.status = status
    task.status = status

    now = utcnow()
    sub.status = "completed"
    sub.result_revision_id = rev.id
    sub.completed_at = now
    db.flush()

    append_event(
        db,
        room.id,
        "revision.created",
        actor,
        f"{agent.name} wrote {ledger.rev_label(output, rev.number)} for {ledger.label(task)}",
        {"record": ledger.record_ref(output) | {"type": output.type, "status": output.status}, "revision": revision_out(db, rev, output)},
        record_ids=[task.id, output.id],
    )
    append_event(
        db,
        room.id,
        "submission.completed",
        actor,
        f"{agent.name}'s submission was applied as {ledger.rev_label(output, rev.number)}",
        {"submission": submission_out(db, sub), "revision": revision_out(db, rev, output), "record": ledger.record_ref(output)},
        record_ids=[task.id, output.id],
    )

    claim = db.execute(
        select(Claim).where(Claim.task_id == task.id, Claim.status == "active", Claim.agent_id == agent.id)
    ).scalar_one_or_none()
    if claim is not None:
        claim_svc.end_claim(db, agent, task, claim, "submitted")

    # A resumed submission was verified when it was saved. If an input changed while it was
    # interrupted, it is still applied exactly once, but immediately flagged stale for a redo.
    late_reason = staleness.mark_if_built_on_outdated(db, output, rev)
    if late_reason:
        output.status = "stale"
        task.status = "stale"
        needs_approval = False
        append_event(
            db,
            room.id,
            "record.stale",
            SYSTEM_ACTOR,
            f"{ledger.rev_label(output, rev.number)} marked stale on arrival ({late_reason})",
            {
                "record": ledger.record_ref(output) | {"type": output.type},
                "revision": rev.number,
                "task": ledger.record_ref(task),
                "reason": late_reason,
                "caused_by": None,
                "path": [late_reason.split("based on ")[-1].split(",")[0], ledger.rev_label(output, rev.number)],
            },
            record_ids=[task.id, output.id],
        )

    if needs_approval:
        approval = Approval(
            room_id=room.id,
            revision_id=rev.id,
            record_id=output.id,
            task_id=task.id,
            reason="redo_of_stale" if is_redo else "require_approval",
            status="pending",
            requested_at=now,
        )
        db.add(approval)
        db.flush()
        append_event(
            db,
            room.id,
            "approval.requested",
            actor,
            f"{ledger.rev_label(output, rev.number)} needs approval"
            + (" (corrected work after a decision changed)" if is_redo else ""),
            {"approval": approval_out(db, approval)},
            record_ids=[task.id, output.id],
        )
    db.commit()
    return True


def _result(db: Session, sub: Submission, message: str | None = None) -> dict:
    """The MCP-facing result: status, every check, and what was created."""
    out = submission_out(db, sub)
    result = None
    if sub.result_revision_id:
        rev = db.get(Revision, sub.result_revision_id)
        rec = db.get(Record, rev.record_id)
        result = {
            "record_id": str(rec.id),
            "label": ledger.label(rec),
            "revision": rev.number,
            "revision_id": str(rev.id),
            "status": rec.status,
        }
    if message is None:
        if sub.status == "completed" and result:
            message = f"Applied as {result['label']} v{result['revision']}" + (
                " and waiting for human approval." if result["status"] == "in_review" else "."
            )
        else:
            message = sub.rejection_reason or sub.status
    return {
        "ok": sub.status != "rejected",
        "submission_id": out["id"],
        "status": sub.status,
        "message": message,
        "checks": out["checks"],
        "result": result,
        "attempts": sub.attempts,
        "resumed": sub.resumed,
    }
