"""Test setup (SQLite): a fresh temporary data directory (one baton.db) for every test.

Run:  cd backend && uv run --python 3.12 --extra dev pytest -q

SQLite has one writer. A test's own `db` session is committed before every API call the test makes
(see _Client), so the test never holds the writer while the server waits for it.
"""

import os
import tempfile

import pytest

_TMP = tempfile.mkdtemp(prefix="baton-test-")
os.environ["BATON_DATA_DIR"] = os.path.join(_TMP, "data")  # must be set before app modules import
os.environ["BATON_CHECK_DELAY_MS"] = "0"
os.environ["BATON_DEFAULT_REQUIRE_APPROVAL"] = "true"  # most tests exercise the approval flow
os.environ["BATON_PUBLIC_URL"] = "http://localhost:8000"
os.environ["BATON_PROVIDER_KEYS_FILE"] = os.path.join(_TMP, "providers.json")

_open_sessions: list = []


def _flush_test_sessions() -> None:
    for s in list(_open_sessions):
        if s.in_transaction():
            s.commit()


@pytest.fixture(scope="session")
def database():
    yield os.environ["BATON_DATA_DIR"]


@pytest.fixture()
def db_clean(database):
    import shutil

    from app.db import data_dir, init_db, reset_engines

    reset_engines()
    shutil.rmtree(data_dir(), ignore_errors=True)
    init_db()
    keys = os.environ["BATON_PROVIDER_KEYS_FILE"]
    if os.path.exists(keys):
        os.remove(keys)
    yield


@pytest.fixture()
def client(db_clean):
    from fastapi.testclient import TestClient

    from app.main import app

    class _Client(TestClient):
        def request(self, *args, **kwargs):
            _flush_test_sessions()
            return super().request(*args, **kwargs)

        def websocket_connect(self, *args, **kwargs):
            _flush_test_sessions()
            return super().websocket_connect(*args, **kwargs)

    with _Client(app) as c:
        yield c


@pytest.fixture()
def db(db_clean):
    from app.db import SessionLocal

    s = SessionLocal()
    _open_sessions.append(s)
    try:
        yield s
    finally:
        _open_sessions.remove(s)
        s.close()


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
