import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import current_user, get_membership, require_mentor
from app.db import get_db
from app.errors import ApiError, forbidden, not_found
from app.models import Room, RoomMember, User
from app.schemas import JoinIn, MemberRoleIn, RoomCreateIn, SettingsIn
from app.serializers import actor_user, member_out, room_out, room_summary_out, user_out
from app.services import rooms as room_svc
from app.services.events import append_event

router = APIRouter(prefix="/api/rooms", tags=["rooms"])


@router.post("", status_code=201)
def create_room(body: RoomCreateIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    room = room_svc.create_room(db, user, body.name)
    db.commit()
    return room_out(db, room, "owner")


@router.get("")
def list_my_rooms(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    rows = db.execute(
        select(Room, RoomMember.role)
        .join(RoomMember, RoomMember.room_id == Room.id)
        .where(RoomMember.user_id == user.id)
        .order_by(RoomMember.joined_at)
    ).all()
    return {"rooms": [room_summary_out(db, room, role) for room, role in rows]}


@router.post("/join")
def join_room(body: JoinIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    room = db.execute(
        select(Room).where(Room.invite_code == room_svc.normalize_code(body.invite_code))
    ).scalar_one_or_none()
    if room is None:
        raise not_found("Invite code not found. Check it with the room's mentor.")
    member, _ = room_svc.add_member(db, room, user)
    db.commit()
    return room_out(db, room, member.role)


@router.get("/{room_id}")
def get_room(room_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    room, member = get_membership(db, room_id, user)
    return room_out(db, room, member.role)


@router.patch("/{room_id}/settings")
def update_settings(
    room_id: uuid.UUID, body: SettingsIn, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> dict:
    room, member = get_membership(db, room_id, user)
    require_mentor(member, "change room settings")
    changed = room_svc.update_settings(room, body.model_dump(exclude_none=True))
    if changed:
        append_event(
            db,
            room.id,
            "room.settings_changed",
            actor_user(user, member.role),
            f"{user.display_name} changed room settings: {', '.join(changed)}",
            {"settings": room.settings, "changed": changed},
        )
    db.commit()
    return room_out(db, room, member.role)


@router.get("/{room_id}/members")
def list_members(room_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    get_membership(db, room_id, user)
    rows = db.execute(
        select(RoomMember, User)
        .join(User, User.id == RoomMember.user_id)
        .where(RoomMember.room_id == room_id)
        .order_by(RoomMember.joined_at)
    ).all()
    return {"members": [member_out(db, m, u) for m, u in rows]}


@router.patch("/{room_id}/members/{user_id}")
def change_member_role(
    room_id: uuid.UUID,
    user_id: uuid.UUID,
    body: MemberRoleIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> dict:
    room, me = get_membership(db, room_id, user)
    if me.role != "owner":
        raise forbidden("Only the room owner can change member roles.")
    target = db.get(RoomMember, (room_id, user_id))
    if target is None:
        raise not_found("That user is not a member of this room.")
    if target.role == "owner":
        raise ApiError(409, "The owner's role can't be changed.")
    target_user = db.get(User, user_id)
    if target.role != body.role:
        previous = target.role
        target.role = body.role
        append_event(
            db,
            room.id,
            "member.role_changed",
            actor_user(user, "owner"),
            f"{user.display_name} made {target_user.display_name} a {body.role}",
            {"user": user_out(target_user), "from": previous, "to": body.role},
        )
    db.commit()
    return member_out(db, target, target_user)
