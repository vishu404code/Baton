import uuid

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import current_user, get_membership, is_mentor
from app.db import get_db
from app.errors import forbidden, not_found
from app.models import Agent, User
from app.schemas import AgentCreateIn
from app.serializers import agent_out
from app.services import rooms as room_svc
from app.services.agent_config import build_config

router = APIRouter(prefix="/api/rooms/{room_id}/agents", tags=["agents"])


def _agent_in_room(db: Session, room_id: uuid.UUID, agent_id: uuid.UUID) -> Agent:
    agent = db.get(Agent, agent_id)
    if agent is None or agent.room_id != room_id:
        raise not_found("Agent not found in this room.")
    return agent


@router.get("")
def list_agents(
    room_id: uuid.UUID,
    include_revoked: bool = False,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    get_membership(db, room_id, user)
    stmt = select(Agent, User.display_name).join(User, User.id == Agent.user_id).where(Agent.room_id == room_id)
    if not include_revoked:
        stmt = stmt.where(Agent.revoked_at.is_(None))
    rows = db.execute(stmt.order_by(Agent.created_at)).all()
    return {"agents": [agent_out(db, a, name) for a, name in rows]}


@router.post("", status_code=201)
def create_agent(
    room_id: uuid.UUID, body: AgentCreateIn, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict:
    room, _ = get_membership(db, room_id, user)
    from app.llm import registry, store

    tool, model = body.tool, body.model
    if body.provider:
        if tool == "other":
            tool = registry.TOOL_FOR_PROVIDER.get(body.provider, "other")
        model = model or store.get(registry.PROVIDERS[body.provider].info)["model"]
    agent, token = room_svc.create_agent(db, room, user, body.name, tool, body.role, body.provider, model)
    db.commit()
    return {"agent": agent_out(db, agent, user.display_name), "token": token, "config": build_config(agent, token)}


@router.get("/{agent_id}/config")
def agent_config(
    room_id: uuid.UUID, agent_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict:
    get_membership(db, room_id, user)
    return build_config(_agent_in_room(db, room_id, agent_id))


@router.delete("/{agent_id}", status_code=204)
def revoke_agent(
    room_id: uuid.UUID, agent_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> Response:
    room, member = get_membership(db, room_id, user)
    agent = _agent_in_room(db, room_id, agent_id)
    if agent.user_id != user.id and not is_mentor(member):
        raise forbidden("You can only revoke your own agents (mentors can revoke any).")
    if agent.revoked_at is None:
        room_svc.revoke_agent(db, room, agent, user, member.role)
        db.commit()
    return Response(status_code=204)
