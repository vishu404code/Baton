"""Test setup: a real Postgres database named <db>_test, migrated with Alembic, truncated per test.

Run inside the container:  docker compose exec backend pytest -q
"""

import os
import re

import psycopg
import pytest

_base_url = os.environ.get("DATABASE_URL", "postgresql+psycopg://baton:baton@localhost:5432/baton")
TEST_DB_URL = re.sub(r"/([^/?]+)(\?.*)?$", lambda m: f"/{m.group(1)}_test{m.group(2) or ''}", _base_url)
os.environ["DATABASE_URL"] = TEST_DB_URL  # must happen before app modules are imported
os.environ["BATON_CHECK_DELAY_MS"] = "0"


def _admin_dsn(url: str) -> tuple[str, str]:
    plain = url.replace("postgresql+psycopg://", "postgresql://")
    dbname = re.search(r"/([^/?]+)(\?.*)?$", plain).group(1)
    return re.sub(r"/[^/?]+(\?.*)?$", "/postgres", plain), dbname


def _db_reachable() -> bool:
    admin, _ = _admin_dsn(TEST_DB_URL)
    try:
        psycopg.connect(admin, connect_timeout=2).close()
        return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def database():
    if not _db_reachable():
        pytest.skip("Postgres not reachable; run tests with `docker compose exec backend pytest`.")
    admin, dbname = _admin_dsn(TEST_DB_URL)
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)')
        conn.execute(f'CREATE DATABASE "{dbname}"')

    from alembic import command
    from alembic.config import Config

    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = Config(os.path.join(here, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(here, "alembic"))
    command.upgrade(cfg, "head")
    yield TEST_DB_URL


@pytest.fixture()
def db_clean(database):
    from sqlalchemy import text

    from app.db import Base, engine

    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    yield


@pytest.fixture()
def client(db_clean):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture()
def db(db_clean):
    from app.db import SessionLocal

    with SessionLocal() as s:
        yield s


class Api:
    """Small helper: sign up users and call the API with their token."""

    def __init__(self, client):
        self.c = client

    def signup(self, name: str) -> dict:
        r = self.c.post("/api/session", json={"display_name": name})
        assert r.status_code == 201, r.text
        body = r.json()
        return {"id": body["user"]["id"], "name": name, "token": body["token"], "h": {"Authorization": f"Bearer {body['token']}"}}

    def room(self, owner: dict, name: str = "Campus App Launch") -> dict:
        r = self.c.post("/api/rooms", json={"name": name}, headers=owner["h"])
        assert r.status_code == 201, r.text
        return r.json()

    def join(self, user: dict, code: str) -> dict:
        r = self.c.post("/api/rooms/join", json={"invite_code": code}, headers=user["h"])
        assert r.status_code == 200, r.text
        return r.json()


@pytest.fixture()
def api(client):
    return Api(client)


# --- A seeded room used by milestone 3+ tests ----------------------------------------------


class World:
    """Asha (owner) and Ben (member) in a room with a brief, 3 decisions, 2 sources,
    Task 1 (planner: write launch plan) and Task 2 (reviewer: review Task 1),
    plus Asha's Claude (planner) and Ben's Codex (reviewer)."""


@pytest.fixture()
def world(api, client):
    w = World()
    w.asha, w.ben = api.signup("Asha"), api.signup("Ben")
    w.room = api.room(w.asha)
    w.room_id = w.room["id"]
    api.join(w.ben, w.room["invite_code"])

    def create(type_, title, content, who=None):
        r = client.post(f"/api/rooms/{w.room_id}/records", json={"type": type_, "title": title, "content": content}, headers=(who or w.asha)["h"])
        assert r.status_code == 201, r.text
        return r.json()

    w.create = create
    w.brief = create("brief", "Campus app launch brief", {"body": "Launch the campus app to all students this term."})
    w.dec1 = create("decision", "Platform", {"statement": "We launch on iOS and Android."})
    w.dec2 = create("decision", "Launch date", {"statement": "We launch on 10 January.", "rationale": "Before term starts."})
    w.dec3 = create("decision", "Budget", {"statement": "Marketing budget is 2,000 EUR."})
    w.src1 = create("source", "Academic calendar", {"url": "https://example.edu/calendar", "summary": "Term starts 13 January."})
    w.src2 = create("source", "Student survey", {"text": "68% of students want the app before exams."})
    w.task1 = create("task", "Write launch plan", {"description": "Draft the launch plan.", "role": "planner"})
    w.task2 = create(
        "task", "Review launch plan",
        {"description": "Review the plan against the brief and decisions.", "role": "reviewer", "review_of_task_id": w.task1["record"]["id"]},
    )

    def agent(user, name, tool, role):
        r = client.post(f"/api/rooms/{w.room_id}/agents", json={"name": name, "tool": tool, "role": role}, headers=user["h"])
        assert r.status_code == 201, r.text
        return r.json()

    w.claude = agent(w.asha, "Asha's Claude", "claude_code", "planner")
    w.codex = agent(w.ben, "Ben's Codex", "codex", "reviewer")
    w.rev = lambda rec: rec["revision"]["id"]
    return w


@pytest.fixture()
def agent_of(db):
    """Load an Agent row from a create-agent response."""
    import uuid as _uuid

    from app.models import Agent

    def get(created):
        db.expire_all()
        return db.get(Agent, _uuid.UUID(created["agent"]["id"]))

    return get


@pytest.fixture()
def live_server(db_clean):
    """Run the real app with uvicorn on a free port so MCP can be tested over HTTP."""
    import socket
    import threading
    import time

    import uvicorn

    from app.main import app

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)
