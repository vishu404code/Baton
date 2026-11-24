"""The verification pipeline: 7 ordered checks, each pass/fail with a human-readable reason.

Runs before anything is applied. Stops at the first failure. Checks 5-7 can be turned
off in room settings (they are then reported as skipped). Each result is handed to
`on_result` as soon as it is known, so callers can stream it live.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.models import Agent, Claim, Record, Revision, Room, User
from app.services.claims import role_problem
from app.services.events import iso
from app.services.ledger import content_problems, label, output_of, required_fields, resolve_record, rev_label
from app.errors import AgentError

CHECKS = [
    "claim_valid",
    "permission",
    "revisions_current",
    "no_conflicting_edit",
    "citations_present",
    "sources_exist",
    "content_schema",
]
OPTIONAL_CHECKS = ("citations_present", "sources_exist", "content_schema")


@dataclass
class CheckResult:
    name: str
    order: int
    passed: bool
    detail: str
    skipped: bool = False

    def out(self) -> dict:
        d = {"name": self.name, "order": self.order, "passed": self.passed, "detail": self.detail}
        if self.skipped:
            d["skipped"] = True
        return d


@dataclass
class Context:
    db: Session
    room: Room
    agent: Agent
    task: Record
    task_content: dict
    output_type: str  # draft | review
    output: Record | None  # the task's existing output record, if any
    claim: Claim | None  # the task's active claim (any holder)
    content: dict
    based_on: list[str]
    source_refs: list[str]
    # Filled in by checks:
    resolved_source_ids: list[str] = field(default_factory=list)
    base_revision_id: uuid.UUID | None = None


def _check_claim_valid(c: Context) -> tuple[bool, str]:
    t = label(c.task)
    if c.claim is None:
        return False, f'not claimed: claim_task("{t}") first (or your lease expired).'
    if c.claim.agent_id != c.agent.id:
        holder = c.db.get(Agent, c.claim.agent_id)
        return False, f"{t} is claimed by {holder.name} until {iso(c.claim.lease_expires_at)}; you can't submit for it."
    return True, f"{c.agent.name} holds the lease on {t} until {iso(c.claim.lease_expires_at)}."


def _check_permission(c: Context) -> tuple[bool, str]:
    problem = role_problem(c.db, c.agent, c.task)
    if problem:
        return False, problem
    return True, f"{c.agent.role} may submit a {c.output_type} for a {c.task_content.get('role')} task."


def _resolve_rev(c: Context, rid: str) -> tuple[Revision, Record] | None:
    try:
        rev = c.db.get(Revision, uuid.UUID(str(rid)))
    except ValueError:
        return None
    if rev is None:
        return None
    rec = c.db.get(Record, rev.record_id)
    if rec is None or rec.room_id != c.room.id:
        return None
    return rev, rec


def _check_revisions_current(c: Context) -> tuple[bool, str]:
    if not c.based_on:
        return False, (
            "based_on is empty: list the revision_id of every brief, decision, source and draft you used "
            "(from get_room_context or read_record)."
        )
    checked = 0
    for rid in c.based_on:
        found = _resolve_rev(c, rid)
        if found is None:
            return False, f"unknown revision {rid} in based_on; use revision_id values from get_room_context or read_record."
        rev, rec = found
        if c.output is not None and rec.id == c.output.id:
            continue  # edits of this task's own output are checked by no_conflicting_edit
        if rec.current_revision_id != rev.id:
            return False, (
                f"stale: based on {rev_label(rec, rev.number)}, now v{rec.current_revision}; "
                f'call read_record("{label(rec)}") and resubmit with the new revision_id.'
            )
        if rec.status == "stale":
            return False, (
                f"stale: based on {rev_label(rec, rev.number)}, which is itself stale (built on an outdated decision); "
                "wait for the corrected version."
            )
        checked += 1
    # A review must be based on the current version of the draft it reviews.
    reviewed_id = c.task_content.get("review_of_task_id")
    if reviewed_id:
        reviewed_task = c.db.get(Record, uuid.UUID(reviewed_id))
        draft = output_of(c.db, reviewed_task) if reviewed_task else None
        if draft is not None and str(draft.current_revision_id) not in [str(b) for b in c.based_on]:
            return False, (
                f"based_on must include {rev_label(draft, draft.current_revision)}, the draft you are reviewing "
                f'(revision_id {draft.current_revision_id}); call read_record("{label(draft)}").'
            )
    return True, f"All {checked} based_on revision{'s are' if checked != 1 else ' is'} current."


def _check_no_conflicting_edit(c: Context) -> tuple[bool, str]:
    out = c.output
    if out is None:
        return True, f"First version of this task's {c.output_type}."
    c.base_revision_id = out.current_revision_id
    listed = [r for r in (_resolve_rev(c, b) for b in c.based_on) if r and r[1].id == out.id]
    current_rev = c.db.get(Revision, out.current_revision_id)
    author = current_rev.author_agent_id and c.db.get(Agent, current_rev.author_agent_id)
    by = author.name if author else "a teammate"
    if listed:
        base_rev = listed[0][0]
        if base_rev.id != out.current_revision_id:
            return False, (
                f"conflict: {label(out)} changed to v{out.current_revision} by {by} since your base v{base_rev.number}; "
                f'call read_record("{label(out)}"), merge, and resubmit.'
            )
        return True, f"Editing {rev_label(out, base_rev.number)}, which is still current."
    if c.claim is not None and current_rev.created_at > c.claim.created_at:
        return False, (
            f"conflict: {label(out)} was updated to v{out.current_revision} by {by} after you claimed the task; "
            f'call read_record("{label(out)}") and include its revision_id in based_on.'
        )
    return True, f"No other edits to {label(out)} since you claimed the task (current v{out.current_revision})."


def _check_citations_present(c: Context) -> tuple[bool, str]:
    minimum = int(c.room.settings.get("min_sources", 1))
    if c.output_type != "draft":
        return True, "Citations are not required for reviews."
    n = len(c.source_refs)
    if n < minimum:
        return False, f"cites {n} source{'s' if n != 1 else ''}, minimum is {minimum}; add sources (add_source) and list their IDs in sources."
    return True, f"{n} source{'s' if n != 1 else ''} cited (minimum {minimum})."


def _check_sources_exist(c: Context) -> tuple[bool, str]:
    ids = []
    for ref in c.source_refs:
        try:
            rec = resolve_record(c.db, c.room.id, ref)
        except AgentError:
            return False, f"source {ref} not found in this room; add it with add_source and cite the returned ID."
        if rec.type != "source":
            return False, f"{label(rec)} is a {rec.type}, not a source; cite source records only."
        ids.append(str(rec.id))
    c.resolved_source_ids = ids
    if not ids:
        return True, "No sources cited."
    return True, "All cited sources exist in this room."


def _check_content_schema(c: Context) -> tuple[bool, str]:
    problems = content_problems(c.output_type, c.content)
    if problems:
        return False, f"{c.output_type} content invalid: {'; '.join(problems)}."
    return True, f"{c.output_type} has the required field{'s' if ',' in required_fields(c.output_type) else ''}: {required_fields(c.output_type)}."


_IMPL: dict[str, Callable[[Context], tuple[bool, str]]] = {
    "claim_valid": _check_claim_valid,
    "permission": _check_permission,
    "revisions_current": _check_revisions_current,
    "no_conflicting_edit": _check_no_conflicting_edit,
    "citations_present": _check_citations_present,
    "sources_exist": _check_sources_exist,
    "content_schema": _check_content_schema,
}


def run_checks(c: Context, on_result: Callable[[CheckResult], None] | None = None) -> list[CheckResult]:
    enabled = (c.room.settings or {}).get("checks", {})
    results: list[CheckResult] = []
    for order, name in enumerate(CHECKS, start=1):
        if name in OPTIONAL_CHECKS and not enabled.get(name, True):
            res = CheckResult(name, order, True, "Disabled in room settings.", skipped=True)
            if name == "sources_exist":
                # Still resolve what we can so cited sources are recorded.
                try:
                    _check_sources_exist(c)
                except Exception:
                    c.resolved_source_ids = []
        else:
            passed, detail = _IMPL[name](c)
            res = CheckResult(name, order, passed, detail)
        results.append(res)
        if on_result:
            on_result(res)
        if not res.passed:
            break
    return results


def owner_name(db: Session, agent: Agent) -> str:
    return db.get(User, agent.user_id).display_name
