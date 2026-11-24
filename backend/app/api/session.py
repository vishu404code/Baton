from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import SESSION_PREFIX, current_user, new_token
from app.db import get_db
from app.errors import not_found
from app.models import Room, RoomMember, User, UserSession
from app.schemas import SessionIn
from app.serializers import user_out

router = APIRouter(prefix="/api", tags=["session"])


def _issue(db: Session, user: User) -> dict:
    token, token_hash = new_token(SESSION_PREFIX)
    db.add(UserSession(user_id=user.id, token_hash=token_hash))
    db.commit()
    return {"user": user_out(user), "token": token}


@router.post("/session", status_code=201)
def create_session(body: SessionIn, db: Session = Depends(get_db)) -> dict:
    user = User(display_name=body.display_name)
    db.add(user)
    db.flush()
    return _issue(db, user)


@router.post("/session/demo")
def demo_session(body: SessionIn, db: Session = Depends(get_db)) -> dict:
    """Sign in as a seeded demo user by name (for one-click judging)."""
    user = db.execute(
        select(User)
        .join(RoomMember, RoomMember.user_id == User.id)
        .join(Room, Room.id == RoomMember.room_id)
        .where(Room.is_demo.is_(True), User.display_name.ilike(body.display_name))
        .order_by(User.created_at)
        .limit(1)
    ).scalar_one_or_none()
    if user is None:
        raise not_found(f"No demo user named {body.display_name!r}. Run ./start.sh to seed the demo.")
    return _issue(db, user)


@router.post("/session/local")
def local_session(db: Session = Depends(get_db)) -> dict:
    """Desktop mode: sign in as the one local owner (created with a starter project on first launch)."""
    from app.config import get_settings
    from app.services import bootstrap

    if not get_settings().baton_local_mode:
        raise not_found("Local mode is off.")
    from app.services import demo as demo_svc

    user, room = bootstrap.ensure_local_workspace(db)
    demo_svc.ensure_demo_room(db, user)
    from app.services import knowledge as kn

    kn.seed_defaults(db)
    db.commit()
    return {**_issue(db, user), "room_id": str(room.id)}


@router.get("/me")
def me(user: User = Depends(current_user)) -> dict:
    return {"user": user_out(user)}
