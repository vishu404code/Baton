"""Baton's MCP server: the same nine tools for every agent tool (Claude Code, Codex, Gemini CLI...).

Served over Streamable HTTP at /mcp from the FastAPI app (stateless, JSON responses).
The agent's identity and role come from its bearer token on every request.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import anyio
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.types import Receive, Scope, Send

from app import __version__
from app.agent_instructions import MCP_INSTRUCTIONS
from app.auth import agent_from_token, bearer
from app.db import SessionLocal, read_session
from app.errors import AgentError
from app.models import Agent, Claim, Comment, Record, Room, User, utcnow
from app.record_views import based_on_out, comment_out, revision_out, sources_out
from app.serializers import actor_agent, agent_out
from app.services import claims as claim_svc
from app.services import context as context_svc
from app.services import ledger
from app.services import presence
from app.services import submissions as submission_svc
from app.services.events import append_event, iso

server = MCPServer(name="baton", title="Baton", instructions=MCP_INSTRUCTIONS, version=__version__)

_SEEN_THROTTLE = timedelta(seconds=10)


# --- Plumbing ---------------------------------------------------------------------------


def _touch(db: Session, agent: Agent) -> None:
    """Record activity for presence; announce the agent if it was offline."""
    was_online = presence.agent_online(agent)
    now = utcnow()
    if agent.last_seen_at is None or now - agent.last_seen_at > _SEEN_THROTTLE or not was_online:
        agent.last_seen_at = now
        if not was_online:
            append_event(
                db,
                agent.room_id,
                "agent.connected",
                actor_agent(agent, db.get(User, agent.user_id).display_name),
                f"{agent.name} connected ({agent.tool})",
                {"agent": agent_out(db, agent)},
            )
        db.commit()


async def _run(ctx: Context, fn: Callable[..., Any], *args: Any) -> Any:
    token = bearer((ctx.headers or {}).get("authorization"))

    def work():
        with SessionLocal() as db:
            if token:
                agent = agent_from_token(db, token)
            else:
                agent = db.execute(
                    select(Agent).where(Agent.tool == "antigravity", Agent.revoked_at.is_(None)).order_by(Agent.created_at.desc())
                ).scalars().first()
            if agent is None:
                raise ToolError("unauthorized: missing or revoked Baton agent token. Ask your mentor for a new one.")
            _touch(db, agent)
            try:
                result = fn(db, agent, *args)
                db.commit()
                return result
            except AgentError as e:
                db.rollback()
                raise ToolError(e.message) from None

    return await anyio.to_thread.run_sync(work)


def _rev_json(db: Session, record: Record) -> dict | None:
    rev = ledger.current_revision(db, record)
    if rev is None:
        return None
    return {
        "record_id": str(record.id),
        "label": ledger.label(record),
        "title": record.title,
        "revision": rev.number,
        "revision_id": str(rev.id),
        "status": record.status,
        "content": rev.content,
    }


def _of_type(db: Session, room_id: uuid.UUID, type_: str) -> list[Record]:
    return db.execute(
        select(Record).where(Record.room_id == room_id, Record.type == type_).order_by(Record.number)
    ).scalars().all()


def _my_claims(db: Session, agent: Agent) -> list[dict]:
    rows = db.execute(
        select(Claim, Record)
        .join(Record, Record.id == Claim.task_id)
        .where(Claim.agent_id == agent.id, Claim.status == "active", Claim.lease_expires_at > utcnow())
    ).all()
    return [
        {"task_id": str(t.id), "label": ledger.label(t), "title": t.title, "lease_expires_at": iso(c.lease_expires_at)}
        for c, t in rows
    ]


def _task_json(db: Session, task: Record) -> dict:
    content = ledger.current_revision(db, task).content or {}
    claim = claim_svc.active_claim(db, task)
    holder = db.get(Agent, claim.agent_id) if claim else None
    output = ledger.output_of(db, task)
    reviewed = None
    if content.get("review_of_task_id"):
        rt = db.get(Record, uuid.UUID(content["review_of_task_id"]))
        reviewed = ledger.label(rt) if rt else None
    return {
        "task_id": str(task.id),
        "label": ledger.label(task),
        "title": task.title,
        "status": task.status,
        "role": content.get("role"),
        "description": content.get("description"),
        "review_of": reviewed,
        "claimed_by": holder.name if holder else None,
        "lease_expires_at": iso(claim.lease_expires_at) if claim else None,
        "output": (
            {
                "record_id": str(output.id),
                "label": ledger.label(output),
                "revision": output.current_revision,
                "revision_id": str(output.current_revision_id),
                "status": output.status,
            }
            if output
            else None
        ),
    }


# --- Tool implementations (sync, given a DB session and the calling agent) -----------------


def _get_room_context(db: Session, agent: Agent) -> dict:
    room = db.get(Room, agent.room_id)
    brief = ledger.latest(db, room.id, "brief")
    sources = _of_type(db, room.id, "source")
    return {
        "room": {"id": str(room.id), "name": room.name},
        "me": {"agent_id": str(agent.id), "name": agent.name, "tool": agent.tool, "role": agent.role},
        "brief": _rev_json(db, brief) if brief else None,
        "decisions": [_rev_json(db, d) for d in _of_type(db, room.id, "decision")],
        "sources": [
            {"source_id": s["record_id"], **{k: v for k, v in s.items() if k != "record_id"}}
            for s in sources_out(db, [str(s.id) for s in sources])
        ],
        "my_claims": _my_claims(db, agent),
        "settings": room.settings,
        "next_step": (
            "Call list_tasks, then claim_task on one matching your role."
            if agent.role != "observer"
            else "You are an observer: read only."
        ),
    }


def _list_tasks(db: Session, agent: Agent, status: str | None) -> dict:
    tasks = _of_type(db, agent.room_id, "task")
    items = [_task_json(db, t) for t in tasks]
    if status:
        wanted = {s.strip() for s in status.split(",")}
        items = [t for t in items if t["status"] in wanted]
    mine = [t for t in items if t["role"] == agent.role and t["status"] in claim_svc.CLAIMABLE]
    return {"tasks": items, "claimable_by_you": [t["label"] for t in mine]}


def _read_record(db: Session, agent: Agent, record_id: str, revision: int | None) -> dict:
    record = ledger.resolve_record(db, agent.room_id, record_id)
    rev = ledger.get_revision(db, record, revision) if revision else ledger.current_revision(db, record)
    if rev is None:
        raise AgentError("not_found", f"{ledger.label(record)} has no revision {revision}; latest is v{record.current_revision}.")
    comments = db.execute(select(Comment).where(Comment.record_id == record.id).order_by(Comment.created_at)).scalars()
    out = revision_out(db, rev, record)
    return {
        "record_id": str(record.id),
        "label": ledger.label(record),
        "type": record.type,
        "title": rev.title,
        "status": record.status,
        "revision": rev.number,
        "revision_id": str(rev.id),
        "is_current": rev.id == record.current_revision_id,
        "latest_revision": record.current_revision,
        "content": rev.content,
        "author": out["author"],
        "based_on": based_on_out(db, rev.based_on or []),
        "sources": sources_out(db, rev.source_ids or []),
        "comments": [
            {"author": c["author"]["name"], "text": c["text"], "at": c["created_at"]}
            for c in (comment_out(db, c, record.room_id) for c in comments)
        ],
    }


def _claim_task(db: Session, agent: Agent, task_id: str) -> dict:
    claim = claim_svc.claim_task(db, agent, task_id)
    task = db.get(Record, claim.task_id)
    content = ledger.current_revision(db, task).content or {}
    ctx = _get_room_context(db, agent)
    inputs: dict[str, Any] = {"brief": ctx["brief"], "decisions": ctx["decisions"], "sources": ctx["sources"]}
    if content.get("review_of_task_id"):
        reviewed_task = db.get(Record, uuid.UUID(content["review_of_task_id"]))
        draft = ledger.output_of(db, reviewed_task)
        inputs["under_review"] = _read_record(db, agent, str(draft.id), None) if draft else None
    output = ledger.output_of(db, task)
    if output is not None:
        inputs["your_previous_output"] = _read_record(db, agent, str(output.id), None)
    return {
        "claim": {
            "task_id": str(task.id),
            "label": ledger.label(task),
            "lease_expires_at": iso(claim.lease_expires_at),
            "lease_minutes": claim_svc.lease_minutes(db.get(Room, agent.room_id)),
            "is_redo": claim.is_redo,
        },
        "task": {"label": ledger.label(task), "title": task.title, **content},
        "inputs": inputs,
        "how_to_submit": (
            "submit_result(task_id, content, based_on=[revision_id of every brief/decision/source/draft you used], "
            "sources=[source_id...], idempotency_key='<unique>'). "
            + ('Reviews: content={"verdict": "approve"|"request_changes", "comments": "..."}.'
               if content.get("role") == "reviewer" else 'Drafts: content={"body": "<markdown>"}.')
        ),
    }


def _heartbeat(db: Session, agent: Agent, task_id: str) -> dict:
    claim = claim_svc.heartbeat(db, agent, task_id)
    return {"lease_expires_at": iso(claim.lease_expires_at)}


def _release(db: Session, agent: Agent, task_id: str) -> dict:
    claim_svc.release_task(db, agent, task_id)
    return {"released": True}


def _add_source(db: Session, agent: Agent, title: str, url_or_text: str) -> dict:
    if agent.role == "observer":
        raise AgentError("forbidden", "permission: observers can't add sources.")
    value = (url_or_text or "").strip()
    if not value or not title.strip():
        raise AgentError("bad_request", "add_source needs a title and a URL or some text.")
    content = {"url": value} if value.startswith(("http://", "https://")) else {"text": value}
    record, rev = ledger.create_record(db, agent.room_id, "source", title.strip(), content, author_agent_id=agent.id)
    actor = actor_agent(agent, db.get(User, agent.user_id).display_name)
    append_event(
        db, agent.room_id, "revision.created", actor,
        f"{agent.name} added {ledger.label(record)} \"{record.title}\"",
        {"record": ledger.record_ref(record) | {"type": "source"}, "revision": revision_out(db, rev, record)},
        record_ids=[record.id],
    )
    return {"source_id": str(record.id), "label": ledger.label(record), "revision_id": str(rev.id)}


def _comment(db: Session, agent: Agent, record_id: str, text: str) -> dict:
    if agent.role == "observer":
        raise AgentError("forbidden", "permission: observers can't comment.")
    if not (text or "").strip():
        raise AgentError("bad_request", "comment text is empty.")
    record = ledger.resolve_record(db, agent.room_id, record_id)
    c = Comment(record_id=record.id, revision_number=record.current_revision, author_agent_id=agent.id, text=text.strip())
    db.add(c)
    db.flush()
    out = comment_out(db, c, record.room_id)
    append_event(
        db, agent.room_id, "comment.added", out["author"],
        f"{agent.name} commented on {ledger.label(record)}",
        {"comment": out, "record": ledger.record_ref(record)}, record_ids=[record.id],
    )
    return {"comment_id": out["id"], "record": ledger.label(record)}


def _submit(db, agent, task_id, content, based_on, sources, idempotency_key, title):
    if isinstance(content, str) and content.strip().startswith("{"):
        try:
            content = json.loads(content)
        except ValueError:
            pass
    return submission_svc.submit(db, agent, task_id, content, based_on, sources, idempotency_key, title)


def _get_handoff(db: Session, agent: Agent) -> dict:
    room = db.get(Room, agent.room_id)
    return context_svc.build_handoff(db, room, for_name=agent.name)


def _save_context(db: Session, agent: Agent, summary: str, next_steps: str | None, files: list[str] | None, kind: str) -> dict:
    if not (summary or "").strip():
        raise AgentError("bad_request", "summary is empty: write one or two sentences about what you did.")
    owner = db.get(User, agent.user_id).display_name
    e = context_svc.save_entry(
        db, agent.room_id, author=agent.name, tool=agent.tool, summary=summary, next_steps=next_steps,
        files=files, kind=kind, actor=actor_agent(agent, owner),
    )
    return {"saved": True, "entry_id": str(e.id), "message": "Saved. The next AI tool will see this in get_handoff."}


# --- Tool definitions ----------------------------------------------------------------------


@server.tool()
async def get_handoff(ctx: Context) -> dict:
    """Call this FIRST in every conversation. Returns a briefing (markdown) of the project goal, the binding
    decisions, the tasks and results so far, and what other AI tools did recently and suggest doing next.
    Continue from it instead of asking the user to re-explain."""
    return await _run(ctx, _get_handoff)


def _search_knowledge(db: Session, agent: Agent, query: str, limit: int) -> dict:
    from app.services import knowledge as kn

    docs = kn.search(db, query, max(1, min(limit, 8)))
    guide = [d.text for d in kn._all(db) if d.kind == "instructions"]
    return {"guidelines": guide, "results": [{"title": d.title, "kind": d.kind, "source": d.source, "text": d.text[:6000]} for d in docs]}


@server.tool()
async def search_knowledge(ctx: Context, query: str, limit: int = 5) -> dict:
    """Search the reference knowledge stored in Baton (for example the articles, places, itineraries and hotels of a
    website). Use it before answering questions about that subject, and quote what it returns."""
    return await _run(ctx, _search_knowledge, query, limit)


def _save_roadmap(db: Session, agent: Agent, tasks: list[dict], replace: bool) -> dict:
    from app.services import roadmap as rm

    room = db.get(Room, agent.room_id)
    owner = db.get(User, agent.user_id).display_name
    try:
        rows = rm.save_roadmap(db, room, tasks, replace=replace, actor=actor_agent(agent, owner))
    except rm.RoadmapError as e:
        raise AgentError("bad_request", str(e)) from None
    return {"saved": len(rows), "roadmap": rm.roadmap_lines(rows)}


def _get_roadmap(db: Session, agent: Agent) -> dict:
    from app.services import roadmap as rm

    rows = rm.list_tasks(db, agent.room_id)
    mine = rm.next_task_for(rows, agent.tool)
    return {"roadmap": rm.roadmap_lines(rows, agent.tool), "your_next_task": rm.task_out(mine) if mine else None}


def _update_task(db: Session, agent: Agent, number: int, status: str | None, note: str | None) -> dict:
    from app.services import roadmap as rm

    room = db.get(Room, agent.room_id)
    owner = db.get(User, agent.user_id).display_name
    try:
        t = rm.update_task(db, room, number, status=status, note=note, owner=None, actor=actor_agent(agent, owner))
    except rm.RoadmapError as e:
        raise AgentError("bad_request", str(e)) from None
    return rm.task_out(t)


@server.tool()
async def save_roadmap(ctx: Context, tasks: list[dict], replace: bool = False) -> dict:
    """Save the project roadmap so every AI tool on this Mac sees it. tasks: a list of {title, owner, description, done_when,
    depends_on (task numbers), area (folder like backend/)}. owner is one of claude, chatgpt, antigravity, gemini. Use replace=true
    for a brand-new roadmap. Tasks are numbered 1, 2, 3 in the order given."""
    return await _run(ctx, _save_roadmap, tasks, replace)


@server.tool()
async def get_roadmap(ctx: Context) -> dict:
    """The shared roadmap with each task's owner and status, plus the next task that is yours."""
    return await _run(ctx, _get_roadmap)


@server.tool()
async def update_task(ctx: Context, number: int, status: str | None = None, note: str | None = None) -> dict:
    """Update a roadmap task: status is waiting | in_progress | done | blocked. note: one line others should know (for example the
    API endpoints you built). Call it with 'done' when your task is finished."""
    return await _run(ctx, _update_task, number, status, note)


@server.tool()
async def save_context(ctx: Context, summary: str, next_steps: str | None = None, files: list[str] | None = None, kind: str = "progress") -> dict:
    """Record what you just did so the next AI tool can continue from exactly here. Call it when you finish a
    meaningful chunk of work, make a decision, hit a blocker, or when the user says they are switching tools.
    summary: 1-3 sentences. next_steps: what should happen next. files: paths you touched.
    kind: progress | decision | question | note."""
    return await _run(ctx, _save_context, summary, next_steps, files, kind)


@server.tool()
async def get_room_context(ctx: Context) -> dict:
    """Call this FIRST. Returns the room, the latest brief and every current decision (each with
    the revision_id to cite in based_on), the sources, your agent name/role and your active claims."""
    return await _run(ctx, _get_room_context)


@server.tool()
async def list_tasks(ctx: Context, status: str | None = None) -> dict:
    """List tasks with their status, required role, current holder and output.
    Optional status filter, comma-separated: open, claimed, in_review, approved, stale, rejected."""
    return await _run(ctx, _list_tasks, status)


@server.tool()
async def read_record(ctx: Context, record_id: str, revision: int | None = None) -> dict:
    """Read a record by ID or label (e.g. "Decision 2", "Draft 1", "Task 3"): content, revision
    number and revision_id, what it was based_on, status, cited sources and comments.
    Pass revision to read an older version."""
    return await _run(ctx, _read_record, record_id, revision)


@server.tool()
async def claim_task(ctx: Context, task_id: str) -> dict:
    """Claim a task (ID or label like "Task 1") for exclusive work. Returns the lease expiry and
    everything you need: the brief, decisions, sources and, for reviews, the draft under review."""
    return await _run(ctx, _claim_task, task_id)


@server.tool()
async def heartbeat(ctx: Context, task_id: str) -> dict:
    """Extend your lease on a task you hold. Call every few minutes while working."""
    return await _run(ctx, _heartbeat, task_id)


@server.tool()
async def submit_result(
    ctx: Context,
    task_id: str,
    content: dict[str, Any] | str,
    based_on: list[str],
    idempotency_key: str,
    sources: list[str] | None = None,
    title: str | None = None,
) -> dict:
    """Submit your work for a task you hold. It is verified (7 checks) before being applied.
    - content: drafts {"body": "<markdown>"}; reviews {"verdict": "approve"|"request_changes", "comments": "..."}
    - based_on: revision_id of every brief, decision, source and draft you relied on
    - sources: source IDs (or labels like "Source 1") you cite
    - idempotency_key: unique per submission; REUSE the same key when retrying after an error or crash
    Returns every check result. If rejected, follow the message, then resubmit with a NEW key."""
    return await _run(ctx, _submit, task_id, content, based_on, sources or [], idempotency_key, title)


@server.tool()
async def release_task(ctx: Context, task_id: str) -> dict:
    """Give a task back without submitting, so a teammate can claim it."""
    return await _run(ctx, _release, task_id)


@server.tool()
async def add_source(ctx: Context, title: str, url_or_text: str) -> dict:
    """Add a supporting source (a URL or a short quoted text). Returns the source_id to cite."""
    return await _run(ctx, _add_source, title, url_or_text)


@server.tool()
async def comment(ctx: Context, record_id: str, text: str) -> dict:
    """Comment on a record (e.g. a draft you are reviewing). Visible to the whole room."""
    return await _run(ctx, _comment, record_id, text)


# --- ASGI wiring -------------------------------------------------------------------------------


class MCPEndpoint:
    """ASGI endpoint for /mcp: rejects bad tokens with 401, then forwards to the MCP transport.

    The transport's session manager can only run once, so a fresh one is created for every
    app lifespan (this matters for tests, which start the app many times).
    """

    def __init__(self) -> None:
        self._app = None

    def new_app(self):
        starlette_app = server.streamable_http_app(
            streamable_http_path="/mcp",
            stateless_http=True,
            json_response=True,
            # Agents on teammates' laptops connect via the LAN IP, so don't pin the Host header.
            transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
            host="0.0.0.0",
        )
        self._app = starlette_app
        return server.session_manager

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        token = bearer(headers.get("authorization"))

        def check() -> bool:
            with read_session() as db:
                if token:
                    return agent_from_token(db, token) is not None
                client_ip = (scope.get("client") or ("127.0.0.1", 0))[0]
                if client_ip in ("127.0.0.1", "::1", "localhost"):
                    return db.execute(
                        select(Agent).where(Agent.tool == "antigravity", Agent.revoked_at.is_(None))
                    ).scalars().first() is not None
                return False

        if not await anyio.to_thread.run_sync(check):
            body = json.dumps(
                {"error": {"code": "unauthorized", "message": "Missing or invalid Baton agent token (Authorization: Bearer bat_...).", "details": {}}}
            ).encode()
            await send({
                "type": "http.response.start",
                "status": 401,
                "headers": [(b"content-type", b"application/json"), (b"www-authenticate", b'Bearer realm="baton"')],
            })
            await send({"type": "http.response.body", "body": body})
            return
        scope = dict(scope)
        scope["path"] = "/mcp"
        await self._app(scope, receive, send)


mcp_endpoint = MCPEndpoint()
