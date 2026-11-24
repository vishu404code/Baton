"""Live chat inside Baton: you talk to Claude, ChatGPT, Gemini or DeepSeek one after another, and every AI
starts from the same shared briefing (goal, decisions, what the other AIs just did). Each answer is saved as a
context entry, so the next AI (here or in an outside tool such as Claude Code) already knows it."""

from __future__ import annotations

import threading
import time
import uuid

from sqlalchemy import select

from app.db import SessionLocal
from app.llm import registry, store
from app.llm.base import LLMError
from app.models import ChatMessage, Room
from app.serializers import actor_user
from app.services import context as context_svc
from app.services.events import iso

SEATS = {  # provider id -> (short name shown in the chat, tool id used on the Context screen)
    "anthropic": ("Claude", "claude_code"),
    "openai": ("ChatGPT", "codex"),
    "gemini": ("Gemini", "gemini_cli"),
    "deepseek": ("DeepSeek", "other"),
}
HISTORY = 8  # recent messages included verbatim

_lock = threading.Lock()
_pending: dict[str, dict] = {}


def message_out(m: ChatMessage) -> dict:
    return {"id": str(m.id), "role": m.role, "provider": m.provider, "label": m.label, "model": m.model,
            "content": m.content, "created_at": iso(m.created_at)}


def seats() -> list[dict]:
    out = []
    for pid, (label, tool) in SEATS.items():
        info = registry.PROVIDERS[pid].info
        cfg = store.get(info)
        out.append({"provider": pid, "label": label, "tool": tool, "model": cfg["model"], "ready": bool(cfg["api_key"])})
    return out


def state(db, room_id: uuid.UUID) -> dict:
    rows = list(db.execute(select(ChatMessage).where(ChatMessage.room_id == room_id).order_by(ChatMessage.created_at.desc()).limit(60)).scalars())
    with _lock:
        pending = dict(_pending.get(str(room_id)) or {})
    return {"messages": [message_out(m) for m in reversed(rows)], "pending": pending or None, "seats": seats()}


def _set(room_id: str, **kw) -> None:
    with _lock:
        if room_id in _pending:
            _pending[room_id].update(kw)


def send(db, room: Room, user, provider: str, text: str) -> dict:
    """Validate, store the user's message, and answer in the background."""
    if provider not in SEATS:
        raise LLMError("Pick Claude, ChatGPT, Gemini or DeepSeek.")
    info = registry.PROVIDERS[provider].info
    cfg = store.config(info)
    label, tool = SEATS[provider]
    if not cfg.api_key:
        raise LLMError(f"No API key for {label} yet. Add it under Tools & keys, then ask again.")
    rid = str(room.id)
    with _lock:
        if rid in _pending:
            raise LLMError("An AI is still answering. Wait for it to finish.")
        _pending[rid] = {"provider": provider, "label": label, "tool": tool, "prompt": text, "phase": "connecting", "reply": "", "read_count": 0, "error": None}
    msg = ChatMessage(room_id=room.id, role="user", provider=provider, label=label, content=text)
    db.add(msg)
    db.flush()
    out = message_out(msg)
    db.commit()
    threading.Thread(target=_answer, args=(room.id, user.id, user.display_name, provider, text), daemon=True, name="baton-chat").start()
    return out


def _transcript(db, room_id, exclude_id=None) -> str:
    rows = list(db.execute(select(ChatMessage).where(ChatMessage.room_id == room_id, ChatMessage.role != "error").order_by(ChatMessage.created_at.desc()).limit(HISTORY + 1)).scalars())
    rows = [m for m in reversed(rows)][:-1]  # drop the message being answered (it is the last user message)
    lines = []
    for m in rows:
        who = "User" if m.role == "user" else (m.label or "AI")
        suffix = f" (to {m.label})" if m.role == "user" and m.label else ""
        lines.append(f"{who}{suffix}: {m.content}")
    return "\n\n".join(lines)


def _answer(room_id, user_id, user_name, provider, text) -> None:
    rid = str(room_id)
    label, tool = SEATS[provider]
    info = registry.PROVIDERS[provider].info
    try:
        time.sleep(0.4)
        with SessionLocal() as db:
            room = db.get(Room, room_id)
            h = context_svc.build_handoff(db, room, for_name=label)
            history = _transcript(db, room_id)
        _set(rid, phase="reading", read_count=len(h["entries"]))
        time.sleep(0.7)
        system = (f"You are {label}, one of several AI assistants the user switches between inside an app called Baton. "
                  "All of them share the same memory, shown below. Use it: continue naturally from what the other assistants already "
                  "said and decided, never ask the user to repeat it, and keep your answer clear and reasonably short.\n\n" + h["markdown"])
        user_prompt = (("Recent conversation across all assistants:\n\n" + history + "\n\n---\n\n") if history else "") + f"User's new message to you ({label}):\n{text}"
        _set(rid, phase="answering")
        cfg = store.config(info)
        completion = registry.get(provider).complete(cfg, system, user_prompt, max_tokens=2000)
        reply = (completion.text or "").strip() or "(empty answer)"
        words = reply.split(" ")
        step = max(1, len(words) // 120)  # reveal quickly, whatever the length
        for k in range(step, len(words) + step, step):
            _set(rid, reply=" ".join(words[:k]))
            time.sleep(0.02)
        _set(rid, reply=reply, phase="saving")
        with SessionLocal() as db:
            db.add(ChatMessage(room_id=room_id, role="ai", provider=provider, label=label, model=cfg.model, content=reply))
            snippet = " ".join(reply.split())
            snippet = snippet if len(snippet) <= 700 else snippet[:699] + "…"
            asked = " ".join(text.split())[:240]
            context_svc.save_entry(db, room_id, author=label, tool=tool, summary=f'Asked: "{asked}" Answered: {snippet}',
                                   actor=actor_user_by_id(db, user_id, user_name), kind="progress")
            db.commit()
        _set(rid, phase="saved")
        time.sleep(0.6)
    except LLMError as e:
        _save_error(room_id, provider, label, str(e))
    except Exception as e:  # noqa: BLE001 - never leave the chat spinning
        _save_error(room_id, provider, label, f"Something went wrong: {e}")
    finally:
        with _lock:
            _pending.pop(rid, None)


def actor_user_by_id(db, user_id, name):
    from app.models import RoomMember, User

    user = db.get(User, user_id)
    return actor_user(user, "owner") if user else {"kind": "user", "id": str(user_id), "name": name, "room_role": "owner"}


def _save_error(room_id, provider, label, message) -> None:
    with SessionLocal() as db:
        db.add(ChatMessage(room_id=room_id, role="error", provider=provider, label=label, content=message))
        db.commit()
