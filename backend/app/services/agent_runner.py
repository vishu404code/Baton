"""Runs an AI agent on a task: Baton itself calls the agent's LLM provider and submits the result
through the same claim -> verify -> apply pipeline every other agent uses.

Three phases, so the (slow) model call never holds a database transaction:
  1. claim the task and build the prompt from the project record      (write session, short)
  2. ask the LLM                                                      (no database open)
  3. submit its answer with the revision IDs it was given             (write session, short)
"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid

from sqlalchemy import select

from app.db import SessionLocal
from app.errors import AgentError
from app.llm import registry, store
from app.llm.base import LLMError
from app.models import Agent, Record, User
from app.serializers import actor_agent
from app.services import claims as claim_svc
from app.services import ledger
from app.services import submissions as submission_svc
from app.services.events import append_event

SYSTEM = (
    "You are an AI teammate in Baton, a shared workspace where several AI agents and one human work on a "
    "project together. Do only the task you are given, using only the PROJECT RECORD in the message "
    "(brief, decisions, sources). Decisions are binding: never contradict them. Be concrete and concise. "
    "Reply with ONE JSON object and nothing else."
)

PLANNER_FORMAT = (
    'Reply with a single JSON object: {"title": "<short title>", "body": "<your answer in markdown>", '
    '"sources": ["Source 1", ...]}. "sources" lists the labels of the sources you used (it may be empty).'
)
REVIEWER_FORMAT = (
    'Reply with a single JSON object: {"verdict": "approve" or "request_changes", "comments": "<specific, '
    'concise feedback>"}. Approve only if the draft follows the brief and every decision.'
)

RUNS: dict[str, dict] = {}
_RUNS_LOCK = threading.Lock()


# ---- prompt context -----------------------------------------------------------------------------


def _current(db, record: Record):
    return ledger.current_revision(db, record)


def _records(db, room_id, type_):
    return db.execute(select(Record).where(Record.room_id == room_id, Record.type == type_).order_by(Record.number)).scalars().all()


def build_context(db, agent: Agent, task: Record, claim) -> dict:
    """Everything the model needs, plus the exact revision IDs the answer will be 'based on'."""
    room_id = agent.room_id
    task_rev = _current(db, task)
    tcontent = task_rev.content or {}
    role = tcontent.get("role", agent.role)
    based_on: list[str] = []
    ctx: dict = {"role": role}

    brief = ledger.latest(db, room_id, "brief")
    if brief:
        rev = _current(db, brief)
        ctx["brief"] = {"label": ledger.label(brief), "title": brief.title, "body": rev.content.get("body", "")}
        based_on.append(str(rev.id))
    ctx["decisions"] = []
    for d in _records(db, room_id, "decision"):
        rev = _current(db, d)
        ctx["decisions"].append({"label": ledger.label(d), "title": d.title,
                                 "statement": rev.content.get("statement", ""), "rationale": rev.content.get("rationale", "")})
        based_on.append(str(rev.id))
    ctx["sources"] = []
    for s in _records(db, room_id, "source"):
        rev = _current(db, s)
        c = rev.content or {}
        ctx["sources"].append({"label": ledger.label(s), "title": s.title, "url": c.get("url"), "text": c.get("text"), "summary": c.get("summary")})
        based_on.append(str(rev.id))

    ctx["task"] = {"label": ledger.label(task), "title": task.title, "description": tcontent.get("description", ""), "redo": bool(claim.is_redo)}

    review_of = tcontent.get("review_of_task_id")
    if review_of:
        reviewed = db.get(Record, uuid.UUID(review_of))
        draft = ledger.output_of(db, reviewed) if reviewed else None
        if draft is not None:
            drev = _current(db, draft)
            ctx["under_review"] = {"label": ledger.label(draft), "title": draft.title, "body": drev.content.get("body", "")}
            based_on.append(str(drev.id))
    previous = ledger.output_of(db, task)
    if previous is not None and claim.is_redo:
        ctx["your_previous_output"] = {"label": ledger.label(previous), "content": _current(db, previous).content}
    ctx["_based_on"] = based_on  # stripped before sending to the model
    return ctx


def build_prompts(ctx: dict) -> tuple[str, str]:
    visible = {k: v for k, v in ctx.items() if not k.startswith("_")}
    fmt = REVIEWER_FORMAT if ctx["role"] == "reviewer" else PLANNER_FORMAT
    redo = ""
    if ctx["task"]["redo"]:
        redo = ("\nNOTE: an earlier answer for this task is out of date because a decision changed. "
                "Write a corrected answer that follows the CURRENT decisions.\n")
    user = (f"TASK: {ctx['task']['title']}\n{ctx['task']['description']}\n{redo}\n"
            f"PROJECT RECORD (JSON):\n{json.dumps(visible, ensure_ascii=False, indent=2)}\n\nREPLY FORMAT:\n{fmt}")
    return SYSTEM, user


def parse_json_object(text: str) -> dict | None:
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.IGNORECASE).strip()
    for candidate in (t, t[t.find("{"): t.rfind("}") + 1] if "{" in t and "}" in t else ""):
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                return obj
        except ValueError:
            continue
    return None


def to_submission(role: str, text: str, ctx: dict) -> tuple[dict, str | None, list[str]]:
    """Turn the model's reply into (content, title, source labels)."""
    obj = parse_json_object(text)
    if role == "reviewer":
        if obj and obj.get("verdict") in ("approve", "request_changes"):
            return {"verdict": obj["verdict"], "comments": str(obj.get("comments") or "No comments.")}, None, []
        return {"verdict": "request_changes", "comments": text.strip()[:2000] or "No usable review returned."}, None, []
    known = {s["label"] for s in ctx.get("sources", [])}
    if obj and str(obj.get("body") or "").strip():
        srcs = [s for s in (obj.get("sources") or []) if isinstance(s, str) and s in known]
        return {"body": str(obj["body"])}, (str(obj["title"]) if obj.get("title") else None), srcs
    return {"body": text.strip()}, None, []


# ---- running ------------------------------------------------------------------------------------


def _emit(agent_id: uuid.UUID, type_: str, summary: str, payload: dict, record_ids=()):
    with SessionLocal() as db:
        agent = db.get(Agent, agent_id)
        owner = db.get(User, agent.user_id).display_name
        append_event(db, agent.room_id, type_, actor_agent(agent, owner), summary, payload, record_ids=record_ids)
        db.commit()


def _release(agent_id: uuid.UUID, task_ref: str) -> None:
    try:
        with SessionLocal() as db:
            agent = db.get(Agent, agent_id)
            claim_svc.release_task(db, agent, task_ref)
            db.commit()
    except Exception:
        pass


def run_task(agent_id: uuid.UUID, task_ref: str, run_id: str | None = None, attempts: int = 2) -> dict:
    run_id = run_id or uuid.uuid4().hex[:12]
    with SessionLocal() as db:
        agent = db.get(Agent, agent_id)
        if agent is None or agent.revoked_at is not None or not agent.provider:
            raise LLMError("This agent isn't set up to run on an AI model.")
        provider = registry.get(agent.provider)
        cfg = store.config(provider.info)
        if agent.model:
            cfg.model = agent.model
        name, role_label = agent.name, agent.role
    if provider.info.needs_key and not cfg.api_key:
        raise LLMError(f"No API key for {provider.info.label}. Add it in Settings → AI models.")

    last: dict = {}
    for attempt in range(1, attempts + 1):
        # 1) claim + prompt
        with SessionLocal() as db:
            agent = db.get(Agent, agent_id)
            claim = claim_svc.claim_task(db, agent, task_ref)
            task = db.get(Record, claim.task_id)
            ctx = build_context(db, agent, task, claim)
            task_label, task_title, task_id = ledger.label(task), task.title, task.id
            db.commit()
        if attempt == 1:
            _emit(agent_id, "agent.run_started", f"{name} ({provider.info.label}, {cfg.model}) started {task_label} \"{task_title}\"",
                  {"provider": provider.info.id, "model": cfg.model, "task": {"id": str(task_id), "label": task_label}, "run_id": run_id},
                  record_ids=[task_id])
        system, user = build_prompts(ctx)

        # 2) ask the model (no database open)
        t0 = time.time()
        try:
            completion = provider.complete(cfg, system, user)
        except LLMError as e:
            _release(agent_id, task_ref)
            _emit(agent_id, "agent.run_failed", f"{name} couldn't run {task_label}: {e}", {"error": str(e), "run_id": run_id}, record_ids=[task_id])
            raise
        content, title, sources = to_submission(ctx["role"], completion.text, ctx)

        # 3) submit through the verification pipeline
        try:
            with SessionLocal() as db:
                agent = db.get(Agent, agent_id)
                out = submission_svc.submit(db, agent, task_ref, content, ctx["_based_on"], sources, f"run-{run_id}-{attempt}", title)
        except AgentError as e:
            _release(agent_id, task_ref)
            _emit(agent_id, "agent.run_failed", f"{name} couldn't submit {task_label}: {e.message}", {"error": e.message, "run_id": run_id}, record_ids=[task_id])
            raise LLMError(e.message) from None
        last = {**out, "provider": provider.info.id, "model": cfg.model, "seconds": round(time.time() - t0, 1),
                "input_tokens": completion.input_tokens, "output_tokens": completion.output_tokens, "task": task_label, "attempt": attempt}
        if out["status"] != "rejected":
            _emit(agent_id, "agent.run_finished", f"{name} finished {task_label}: {out['message']}",
                  {"run_id": run_id, "result": out.get("result"), "model": cfg.model, "input_tokens": completion.input_tokens,
                   "output_tokens": completion.output_tokens}, record_ids=[task_id])
            return last
        failed = next((c for c in out["checks"] if not c["passed"]), {})
        if failed.get("name") == "revisions_current" and attempt < attempts:
            continue  # a decision changed while the model was thinking: read the record again and retry once
        break

    _release(agent_id, task_ref)
    _emit(agent_id, "agent.run_failed", f"{name}'s answer for {last.get('task')} was rejected: {last.get('message')}",
          {"run_id": run_id, "message": last.get("message")}, record_ids=[task_id])
    return last


# ---- background runs ----------------------------------------------------------------------------


def _set(run_id: str, **kw) -> None:
    with _RUNS_LOCK:
        RUNS[run_id].update(kw)


def start_run(agent_id: uuid.UUID, task_ref: str, agent_name: str = "") -> str:
    run_id = uuid.uuid4().hex[:12]
    RUNS[run_id] = {"run_id": run_id, "status": "running", "agent": agent_name, "task": task_ref, "started_at": time.time()}

    def work():
        try:
            result = run_task(agent_id, task_ref, run_id)
            _set(run_id, status="done" if result.get("status") != "rejected" else "rejected", result=result, message=result.get("message"))
        except (LLMError, AgentError) as e:
            _set(run_id, status="failed", message=getattr(e, "message", None) or str(e))
        except Exception as e:  # pragma: no cover - last resort so the UI never waits forever
            _set(run_id, status="failed", message=f"Unexpected error: {e}")

    threading.Thread(target=work, daemon=True, name=f"run-{run_id}").start()
    return run_id


def runnable_agents(db, room_id, role: str) -> list[Agent]:
    from app.serializers import _runnable

    agents = db.execute(select(Agent).where(Agent.room_id == room_id, Agent.role == role, Agent.revoked_at.is_(None)).order_by(Agent.created_at)).scalars().all()
    return [a for a in agents if _runnable(a)]


def start_open_tasks(room_id: uuid.UUID) -> str:
    """Run every open or stale task in order, each with a suitable AI agent (planners first, then reviewers)."""
    run_id = uuid.uuid4().hex[:12]
    RUNS[run_id] = {"run_id": run_id, "status": "running", "agent": "", "task": "all open tasks", "steps": [], "started_at": time.time()}

    def work():
        steps = RUNS[run_id]["steps"]
        with SessionLocal() as db:
            tasks = db.execute(select(Record).where(Record.room_id == room_id, Record.type == "task", Record.status.in_(("open", "stale"))).order_by(Record.number)).scalars().all()
            plan = []
            for t in tasks:
                role = (ledger.current_revision(db, t).content or {}).get("role", "planner")
                agents = runnable_agents(db, room_id, role)
                plan.append((ledger.label(t), role, agents[0].id if agents else None, agents[0].name if agents else None))
        for label, role, agent_id, agent_name in plan:
            if agent_id is None:
                steps.append({"task": label, "status": "skipped", "message": f"No ready {role} agent. Create one in Agents."})
                continue
            try:
                res = run_task(agent_id, label, run_id=f"{run_id}-{label.replace(' ', '')}")
                steps.append({"task": label, "agent": agent_name, "status": "done" if res.get("status") != "rejected" else "rejected", "message": res.get("message")})
            except (LLMError, AgentError) as e:
                steps.append({"task": label, "agent": agent_name, "status": "failed", "message": getattr(e, "message", None) or str(e)})
        _set(run_id, status="done")

    threading.Thread(target=work, daemon=True, name=f"runall-{run_id}").start()
    return run_id
