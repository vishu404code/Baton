"""Live chat inside Baton: you talk to Claude, ChatGPT, Gemini or DeepSeek one after another, and every AI
starts from the same shared briefing (goal, decisions, what the other AIs just did). Each answer is saved as a
context entry, so the next AI (here or in an outside tool such as Claude Code) already knows it."""

from __future__ import annotations

import re
import threading
import time
import uuid

from sqlalchemy import select

from app.db import SessionLocal
from app.llm import cli_provider, registry, store
from app.llm.base import LLMError, ProviderConfig
from app.models import ChatMessage, Room
from app.serializers import actor_user
from app.services import context as context_svc
from app.services import knowledge as kn
from app.services.events import iso

SEATS = {  # seat id -> (short name shown in the chat, tool id used on the Context screen)
    "anthropic": ("Claude", "claude_code"),
    "openai": ("ChatGPT", "codex"),
    "gemini": ("Gemini", "gemini_cli"),
    "antigravity": ("Antigravity", "antigravity"),
    "deepseek": ("DeepSeek", "other"),
}
HISTORY = 8  # recent messages included verbatim

_lock = threading.Lock()
_pending: dict[str, dict] = {}


def message_out(m: ChatMessage) -> dict:
    return {"id": str(m.id), "role": m.role, "provider": m.provider, "label": m.label, "model": m.model,
            "content": m.content, "created_at": iso(m.created_at)}


def resolve(pid: str):
    """How a seat is answered: an API key if the user added one, else the app already signed in on this computer."""
    label, _ = SEATS[pid]
    if pid in registry.PROVIDERS:
        cfg = store.config(registry.PROVIDERS[pid].info)
        if cfg.api_key:
            return registry.PROVIDERS[pid], cfg, cfg.model, "api key"
    cli = cli_provider.CLI_SEATS.get(pid)
    if cli is not None and cli.available():
        return cli, ProviderConfig(api_key="", model=cli.model_label), cli.model_label, "your login"
    return None, None, None, None


def seats() -> list[dict]:
    out = []
    for pid, (label, tool) in SEATS.items():
        prov, _cfg, model, via = resolve(pid)
        out.append({"provider": pid, "label": label, "tool": tool, "model": model or "", "ready": prov is not None, "via": via})
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
    label, tool = SEATS[provider]
    prov, _cfg, _model, _via = resolve(provider)
    if prov is None:
        raise LLMError(f"{label} isn't available on this computer yet. Add an API key for it under Tools & keys.")
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
    try:
        time.sleep(0.4)
        note = _ingest_links(rid, text)
        with SessionLocal() as db:
            room = db.get(Room, room_id)
            h = context_svc.build_handoff(db, room, for_name=label)
            history = _transcript(db, room_id)
            kblock, kcount = kn.prompt_block(db, text + " " + _recent_user_text(db, room_id))
        _set(rid, phase="reading", read_count=len(h["entries"]), knowledge_count=kcount)
        time.sleep(0.7)
        system = (f"You are {label}, one of several AI assistants the user switches between inside an app called Baton. "
                  "All of them share the same memory, shown below. Use it: continue naturally from what the other assistants already "
                  "said and decided, never ask the user to repeat it, and keep your answer clear and reasonably short. The shared memory may also contain notes from unrelated "
                  "projects: ignore them unless the user's question is about them.\n\n" + h["markdown"]
                  + (("\n\n" + kblock) if kblock else "") + (("\n\n" + note) if note else ""))
        user_prompt = (("Recent conversation across all assistants:\n\n" + history + "\n\n---\n\n") if history else "") + f"User's new message to you ({label}):\n{text}"
        _set(rid, phase="answering")
        prov, cfg, model_name, _via = resolve(provider)
        if prov is None:
            raise LLMError(f"{label} isn't available on this computer yet. Add an API key for it under Tools & keys.")
        completion = prov.complete(cfg, system, user_prompt, max_tokens=2000)
        reply = (completion.text or "").strip() or "(empty answer)"
        words = reply.split(" ")
        step = max(1, len(words) // 120)  # reveal quickly, whatever the length
        for k in range(step, len(words) + step, step):
            _set(rid, reply=" ".join(words[:k]))
            time.sleep(0.02)
        _set(rid, reply=reply, phase="saving")
        with SessionLocal() as db:
            db.add(ChatMessage(room_id=room_id, role="ai", provider=provider, label=label, model=model_name, content=reply))
            snippet = " ".join(reply.split())
            snippet = snippet if len(snippet) <= 700 else snippet[:699] + "…"
            asked = " ".join(text.split())[:240]
            context_svc.save_entry(db, room_id, author=label, tool=tool, summary=f'Asked: "{asked}" Answered: {snippet}',
                                   actor=actor_user_by_id(db, user_id, user_name), kind="progress")
            _touch_agent(db, room_id, tool)
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


def _touch_agent(db, room_id, tool) -> None:
    from app.models import Agent, utcnow

    for a in db.execute(select(Agent).where(Agent.room_id == room_id, Agent.tool == tool, Agent.revoked_at.is_(None))).scalars():
        a.last_seen_at = utcnow()


URL_RE = re.compile(r"https?://[^\s<>\")]+")


def _recent_user_text(db, room_id) -> str:
    rows = db.execute(select(ChatMessage.content).where(ChatMessage.room_id == room_id, ChatMessage.role == "user").order_by(ChatMessage.created_at.desc()).limit(3)).scalars()
    return " ".join(rows)


def _ingest_links(rid: str, text: str) -> str:
    """If the message contains web addresses Baton hasn't read yet, read them now and remember them for every AI."""
    notes = []
    for url in dict.fromkeys(URL_RE.findall(text)):
        url = url.rstrip(".,;")
        with SessionLocal() as db:
            known = any(x["url"] and x["url"].rstrip("/") == url.rstrip("/") for x in kn.sources(db))
        if known:
            notes.append(f"{url} is already in the knowledge base above, so answer from it. Do not say you cannot open the site.")
            continue
        _set(rid, phase="reading_site", site=url)
        try:
            docs = kn.fetch_site(url)
            with SessionLocal() as db:
                kn.save_docs(db, docs)
                db.commit()
            notes.append(f"Baton just read {url} ({len(docs)} documents) and added it to the knowledge base above.")
        except ValueError as e:
            notes.append(f"Baton tried to read {url} but could not: {e} Tell the user plainly and ask them to paste the text instead.")
    return "\n".join(notes)
