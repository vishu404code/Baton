"""Run AI agents on tasks (Baton calls the agent's model, then submits through the normal checks)."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.auth import current_user_ro, get_membership, require_mentor
from app.db import read_session
from app.errors import ApiError, not_found
from app.models import Agent, User
from app.schemas import _In
from app.serializers import _runnable
from app.services import agent_runner, ledger

router = APIRouter(prefix="/api", tags=["runs"])


class RunIn(_In):
    agent_id: uuid.UUID | None = None


@router.post("/rooms/{room_id}/tasks/{task_ref}/run", status_code=202)
def run_task(room_id: uuid.UUID, task_ref: str, body: RunIn | None = None, user: User = Depends(current_user_ro)) -> dict:
    body = body or RunIn()
    with read_session() as db:
        room, member = get_membership(db, room_id, user)
        require_mentor(member, "run agents")
        task = ledger.resolve_record(db, room.id, task_ref, "task")
        role = (ledger.current_revision(db, task).content or {}).get("role", "planner")
        if body.agent_id:
            agent = db.get(Agent, body.agent_id)
            if agent is None or agent.room_id != room.id or agent.revoked_at is not None:
                raise not_found("Agent not found in this room.")
            if not _runnable(agent):
                raise ApiError(409, f"{agent.name} isn't ready to run: choose an AI model and add its API key in Settings → AI models.")
        else:
            candidates = agent_runner.runnable_agents(db, room.id, role)
            if not candidates:
                raise ApiError(409, f"No ready {role} agent. Create one in Agents and add its API key in Settings → AI models.")
            agent = candidates[0]
        label, agent_id, agent_name = ledger.label(task), agent.id, agent.name
    run_id = agent_runner.start_run(agent_id, label, agent_name)
    return {"run_id": run_id, "agent": agent_name, "task": label, "status": "running"}


@router.post("/rooms/{room_id}/run-open", status_code=202)
def run_open_tasks(room_id: uuid.UUID, user: User = Depends(current_user_ro)) -> dict:
    with read_session() as db:
        room, member = get_membership(db, room_id, user)
        require_mentor(member, "run agents")
        rid = room.id
    return {"run_id": agent_runner.start_open_tasks(rid), "status": "running"}


@router.get("/runs/{run_id}")
def get_run(run_id: str, user: User = Depends(current_user_ro)) -> dict:
    run = agent_runner.RUNS.get(run_id)
    if run is None:
        raise not_found("Run not found.")
    return {k: v for k, v in run.items() if k != "started_at"} | {"seconds": round(__import__("time").time() - run["started_at"], 1)}
