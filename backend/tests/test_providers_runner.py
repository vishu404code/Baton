"""AI providers (Claude, ChatGPT, DeepSeek, Gemini), the agent runner, and local desktop mode.

A small fake "AI server" speaks each provider's real request/response format, so the requests Baton
sends (headers, body fields) and the answers it parses are checked without any real API key.
"""

import json
import os
import stat
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

REQUESTS: list[dict] = []
FAIL_AUTH = {"on": False}


def _planner_or_reviewer(text: str) -> str:
    if '"verdict"' in text:
        return json.dumps({"verdict": "approve", "comments": "Matches the brief and all decisions."})
    return json.dumps({"title": "Launch plan", "body": "## Plan\n- Launch on 15 January\n- Target students", "sources": ["Source 1"]})


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # silence
        pass

    def _send(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("content-length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        REQUESTS.append({"method": "GET", "path": self.path, "headers": dict(self.headers)})
        if FAIL_AUTH["on"]:
            return self._send(401, {"error": {"message": "bad key"}})
        if self.path.startswith("/v1/models"):  # Anthropic
            return self._send(200, {"data": [{"type": "model", "id": "claude-test-1", "display_name": "T", "created_at": "2025-01-01T00:00:00Z"}],
                                    "has_more": False, "first_id": "claude-test-1", "last_id": "claude-test-1"})
        if self.path.startswith(("/openai/models", "/deepseek/models")):
            return self._send(200, {"data": [{"id": "gpt-test"}, {"id": "text-embedding-x"}, {"id": "whisper-1"}]})
        if self.path.startswith("/gemini/models"):
            return self._send(200, {"models": [{"name": "models/gemini-test", "supportedGenerationMethods": ["generateContent"]},
                                               {"name": "models/embed-x", "supportedGenerationMethods": ["embedContent"]}]})
        self._send(404, {})

    def do_POST(self):
        body = self._body()
        REQUESTS.append({"method": "POST", "path": self.path, "headers": dict(self.headers), "body": body})
        if FAIL_AUTH["on"]:
            return self._send(401, {"error": {"message": "bad key"}})
        if self.path.startswith("/v1/messages"):  # Anthropic Messages
            text = _planner_or_reviewer(body["messages"][0]["content"])
            return self._send(200, {"id": "msg_1", "type": "message", "role": "assistant", "model": body["model"],
                                    "content": [{"type": "text", "text": text}], "stop_reason": "end_turn", "stop_sequence": None,
                                    "usage": {"input_tokens": 11, "output_tokens": 22}})
        if self.path.startswith(("/openai/chat/completions", "/deepseek/chat/completions")):
            text = _planner_or_reviewer(body["messages"][-1]["content"])
            return self._send(200, {"model": body["model"], "choices": [{"message": {"role": "assistant", "content": text}}],
                                    "usage": {"prompt_tokens": 7, "completion_tokens": 9}})
        if self.path.startswith("/gemini/models/") and self.path.split("?")[0].endswith(":generateContent"):
            text = _planner_or_reviewer(body["contents"][0]["parts"][0]["text"])
            return self._send(200, {"candidates": [{"content": {"parts": [{"text": text}]}}],
                                    "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 6}})
        self._send(404, {})


@pytest.fixture()
def fake_ai():
    REQUESTS.clear()
    FAIL_AUTH["on"] = False
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def _setup(client, user, pid, base, model, key="test-key-123456"):
    r = client.put(f"/api/providers/{pid}", json={"api_key": key, "model": model, "base_url": base}, headers=user["h"])
    assert r.status_code == 200, r.text
    return r.json()


def _add_agent(client, user, room_id, name, role, provider, model):
    r = client.post(f"/api/rooms/{room_id}/agents", json={"name": name, "role": role, "provider": provider, "model": model}, headers=user["h"])
    assert r.status_code == 201, r.text
    return r.json()["agent"]


def _wait(client, user, run_id, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        run = client.get(f"/api/runs/{run_id}", headers=user["h"]).json()
        if run["status"] != "running":
            return run
        time.sleep(0.2)
    raise AssertionError("run did not finish")


# --- Providers -------------------------------------------------------------------------------------


def test_provider_list_hides_keys_and_stores_them_privately(client, api):
    asha = api.signup("Asha")
    r = client.put("/api/providers/anthropic", json={"api_key": "sk-ant-SECRET-1234567890"}, headers=asha["h"])
    assert r.json()["has_key"] is True and r.json()["key_hint"] == "…7890"
    listing = client.get("/api/providers", headers=asha["h"])
    assert "SECRET" not in listing.text
    by_id = {p["id"]: p for p in listing.json()["providers"]}
    assert set(by_id) == {"anthropic", "openai", "deepseek", "gemini", "mock"}
    assert by_id["anthropic"]["model"] == "claude-opus-5-5" and by_id["mock"]["ready"] is True and by_id["openai"]["ready"] is False
    assert {c["id"] for c in listing.json()["connect"]} == {"antigravity", "claude_code", "codex", "gemini_cli"}
    mode = stat.S_IMODE(os.stat(os.environ["BATON_PROVIDER_KEYS_FILE"]).st_mode)
    assert mode == 0o600
    # An empty key removes it.
    assert client.put("/api/providers/anthropic", json={"api_key": ""}, headers=asha["h"]).json()["has_key"] is False


def test_providers_need_sign_in(client):
    assert client.get("/api/providers").status_code == 401


@pytest.mark.parametrize("pid,model,base,auth_header", [
    ("anthropic", "claude-test-1", "", "authorization"),  # SDK 2.x sends the key as a Bearer token
    ("openai", "gpt-test", "/openai", "authorization"),
    ("deepseek", "deepseek-test", "/deepseek", "authorization"),
    ("gemini", "gemini-test", "/gemini", "x-goog-api-key"),
])
def test_each_provider_sends_the_right_request_and_parses_the_answer(fake_ai, pid, model, base, auth_header):
    from app.llm import registry, store

    provider = registry.PROVIDERS[pid]
    store.update(provider.info, api_key="key-abc-123456", model=model, base_url=fake_ai + base)
    cfg = store.config(provider.info)
    done = provider.complete(cfg, "SYSTEM TEXT", "hello REPLY FORMAT planner", max_tokens=777)
    assert json.loads(done.text)["title"] == "Launch plan"
    assert done.input_tokens and done.output_tokens
    req = [r for r in REQUESTS if r["method"] == "POST"][-1]
    headers = {k.lower(): v for k, v in req["headers"].items()}
    assert "key-abc-123456" in headers[auth_header]
    body = req["body"]
    if pid == "anthropic":
        assert body["model"] == model and body["max_tokens"] == 777 and body["system"] == "SYSTEM TEXT"
        assert "anthropic-version" in headers
    elif pid == "openai":
        assert body["max_completion_tokens"] == 777 and body["messages"][0] == {"role": "system", "content": "SYSTEM TEXT"}
    elif pid == "deepseek":
        assert body["max_tokens"] == 777 and body["model"] == model
    else:
        assert body["generationConfig"]["maxOutputTokens"] == 777 and body["systemInstruction"]["parts"][0]["text"] == "SYSTEM TEXT"


def test_model_listing_per_provider(client, api, fake_ai):
    asha = api.signup("Asha")
    for pid, model, base, expect in [("anthropic", "x", "", ["claude-test-1"]), ("openai", "gpt-test", "/openai", ["gpt-test"]),
                                     ("gemini", "gemini-test", "/gemini", ["gemini-test"])]:
        _setup(client, asha, pid, fake_ai + base, model)
        r = client.post(f"/api/providers/{pid}/test", headers=asha["h"]).json()
        assert r["ok"] is True and r["models"] == expect, r
    # The embedding/audio models are filtered out of the ChatGPT list.
    assert client.get("/api/providers", headers=asha["h"]).json()["providers"][1]["models"] == ["gpt-test"]


def test_bad_key_gives_a_helpful_message(client, api, fake_ai):
    asha = api.signup("Asha")
    for pid, base in [("openai", "/openai"), ("gemini", "/gemini"), ("anthropic", "")]:
        _setup(client, asha, pid, fake_ai + base, "m")
    FAIL_AUTH["on"] = True
    for pid in ("openai", "gemini", "anthropic"):
        r = client.post(f"/api/providers/{pid}/test", headers=asha["h"]).json()
        assert r["ok"] is False and "key" in r["error"].lower(), (pid, r)
    assert client.post("/api/providers/nope/test", headers=asha["h"]).status_code == 404
    assert client.post("/api/providers/deepseek/test", headers=asha["h"]).json()["error"].startswith("No API key")


# --- Running agents on tasks ---------------------------------------------------------------------------


def test_two_different_llms_work_one_project(world, client, fake_ai):
    """Claude plans, ChatGPT reviews: two providers, one shared record, same checks."""
    w = world
    _setup(client, w.asha, "anthropic", fake_ai, "claude-test-1")
    _setup(client, w.asha, "openai", fake_ai + "/openai", "gpt-test")
    planner = _add_agent(client, w.asha, w.room_id, "Claude planner", "planner", "anthropic", "claude-test-1")
    reviewer = _add_agent(client, w.asha, w.room_id, "ChatGPT reviewer", "reviewer", "openai", "gpt-test")
    assert planner["runnable"] and planner["provider"] == "anthropic" and planner["tool"] == "claude_code"
    assert reviewer["runnable"] and reviewer["tool"] == "codex"

    r = client.post(f"/api/rooms/{w.room_id}/tasks/Task 1/run", json={}, headers=w.asha["h"])
    assert r.status_code == 202, r.text
    assert r.json()["agent"] == "Claude planner"
    run = _wait(client, w.asha, r.json()["run_id"])
    assert run["status"] == "done", run
    assert [c["name"] for c in run["result"]["checks"]] == ["claim_valid", "revisions_current", "content_schema"]
    assert run["result"]["result"]["label"] == "Draft 1" and run["result"]["input_tokens"] == 11

    r = client.post(f"/api/rooms/{w.room_id}/tasks/Task 2/run", json={"agent_id": reviewer["id"]}, headers=w.asha["h"])
    run = _wait(client, w.asha, r.json()["run_id"])
    assert run["status"] == "done", run
    assert run["result"]["result"]["label"] == "Review 2"

    board = {t["task"]["label"]: t for t in client.get(f"/api/rooms/{w.room_id}/board", headers=w.asha["h"]).json()["tasks"]}
    assert board["Task 1"]["output"]["author"]["name"] == "Claude planner"
    assert board["Task 2"]["output"]["author"]["name"] == "ChatGPT reviewer"
    draft = client.get(f"/api/records/{board['Task 1']['output']['record_id']}", headers=w.asha["h"]).json()
    assert "Launch on 15 January" in draft["record"]["content"]["body"]
    assert [b["label"] for b in draft["revisions"][0]["based_on"]] == ["Brief 1", "Decision 1", "Decision 2", "Decision 3", "Source 1", "Source 2"]
    assert [s["label"] for s in draft["revisions"][0]["sources"]] == ["Source 1"]
    types = [e["type"] for e in client.get(f"/api/rooms/{w.room_id}/events?limit=500", headers=w.asha["h"]).json()["events"]]
    assert types.count("agent.run_started") == 2 and types.count("agent.run_finished") == 2


def test_run_without_a_ready_agent_or_key_is_refused_clearly(world, client):
    r = client.post(f"/api/rooms/{world.room_id}/tasks/Task 1/run", json={}, headers=world.asha["h"])
    assert r.status_code == 409 and "No ready planner agent" in r.json()["error"]["message"]
    agent = _add_agent(client, world.asha, world.room_id, "No-key Claude", "planner", "anthropic", "claude-test-1")
    assert agent["runnable"] is False
    r = client.post(f"/api/rooms/{world.room_id}/tasks/Task 1/run", json={"agent_id": agent["id"]}, headers=world.asha["h"])
    assert r.status_code == 409 and "API key" in r.json()["error"]["message"]
    # Only mentors can run agents.
    r = client.post(f"/api/rooms/{world.room_id}/tasks/Task 1/run", json={}, headers=world.ben["h"])
    assert r.status_code == 403


def test_provider_failure_releases_the_task_and_is_reported(world, client, fake_ai):
    w = world
    _setup(client, w.asha, "anthropic", fake_ai, "claude-test-1")
    agent = _add_agent(client, w.asha, w.room_id, "Claude planner", "planner", "anthropic", "claude-test-1")
    FAIL_AUTH["on"] = True
    r = client.post(f"/api/rooms/{w.room_id}/tasks/Task 1/run", json={"agent_id": agent["id"]}, headers=w.asha["h"])
    run = _wait(client, w.asha, r.json()["run_id"])
    assert run["status"] == "failed" and "rejected the API key" in run["message"]
    board = {t["task"]["label"]: t for t in client.get(f"/api/rooms/{w.room_id}/board", headers=w.asha["h"]).json()["tasks"]}
    assert board["Task 1"]["task"]["status"] == "open" and board["Task 1"]["claim"] is None
    ev = client.get(f"/api/rooms/{w.room_id}/events?types=agent.run_failed", headers=w.asha["h"]).json()["events"]
    assert "couldn't run Task 1" in ev[-1]["summary"]


def test_run_all_open_tasks_with_the_offline_demo_model(world, client):
    w = world
    _add_agent(client, w.asha, w.room_id, "Demo planner", "planner", "mock", "demo-1")
    _add_agent(client, w.asha, w.room_id, "Demo reviewer", "reviewer", "mock", "demo-1")
    r = client.post(f"/api/rooms/{w.room_id}/run-open", headers=w.asha["h"])
    assert r.status_code == 202
    run = _wait(client, w.asha, r.json()["run_id"])
    assert [(s["task"], s["status"]) for s in run["steps"]] == [("Task 1", "done"), ("Task 2", "done")], run["steps"]
    board = {t["task"]["label"]: t for t in client.get(f"/api/rooms/{w.room_id}/board", headers=w.asha["h"]).json()["tasks"]}
    assert board["Task 1"]["output"]["label"] == "Draft 1" and board["Task 2"]["output"]["label"] == "Review 2"


def test_decision_change_then_rerun_corrects_the_stale_plan(world, client):
    w = world
    _add_agent(client, w.asha, w.room_id, "Demo planner", "planner", "mock", "demo-1")
    run = _wait(client, w.asha, client.post(f"/api/rooms/{w.room_id}/tasks/Task 1/run", json={}, headers=w.asha["h"]).json()["run_id"])
    assert run["status"] == "done"
    client.post(f"/api/records/{w.dec2['record']['id']}/revisions", json={"content": {"statement": "We launch on 20 January."}}, headers=w.asha["h"])
    board = {t["task"]["label"]: t for t in client.get(f"/api/rooms/{w.room_id}/board", headers=w.asha["h"]).json()["tasks"]}
    assert board["Task 1"]["task"]["status"] == "stale"
    run = _wait(client, w.asha, client.post(f"/api/rooms/{w.room_id}/tasks/Task 1/run", json={}, headers=w.asha["h"]).json()["run_id"])
    assert run["status"] == "done" and run["result"]["result"]["revision"] == 2
    assert run["result"]["result"]["status"] == "in_review"  # corrected work always waits for a human
    draft = client.get(f"/api/records/{run['result']['result']['record_id']}", headers=w.asha["h"]).json()
    assert "20 January" in draft["record"]["content"]["body"]


# --- Local desktop mode --------------------------------------------------------------------------------


def test_local_mode_signs_in_and_creates_a_ready_to_use_project(client, monkeypatch):
    from app.config import get_settings

    assert client.post("/api/session/local").status_code == 404  # off by default
    monkeypatch.setattr(get_settings(), "baton_local_mode", True)
    r = client.post("/api/session/local")
    assert r.status_code == 200
    body = r.json()
    h = {"Authorization": f"Bearer {body['token']}"}
    room = client.get(f"/api/rooms/{body['room_id']}", headers=h).json()
    assert room["name"] == "My Project" and room["settings"]["require_approval"] is True or room["settings"]["require_approval"] is False
    tasks = client.get(f"/api/rooms/{body['room_id']}/board", headers=h).json()["tasks"]
    assert [t["task"]["label"] for t in tasks] == ["Task 1", "Task 2"]
    agents = client.get(f"/api/rooms/{body['room_id']}/agents", headers=h).json()["agents"]
    assert sorted(a["name"] for a in agents) == ["Demo planner", "Demo reviewer"] and all(a["runnable"] for a in agents)
    again = client.post("/api/session/local").json()
    assert again["room_id"] == body["room_id"] and again["user"]["id"] == body["user"]["id"]
    run = _wait(client, {"h": h}, client.post(f"/api/rooms/{body['room_id']}/run-open", headers=h).json()["run_id"])
    assert [s["status"] for s in run["steps"]] == ["done", "done"]


def test_antigravity_connect_snippet(world, client):
    r = client.post(f"/api/rooms/{world.room_id}/agents", json={"name": "Antigravity agent", "role": "planner", "tool": "antigravity"}, headers=world.asha["h"])
    assert r.status_code == 201
    snip = r.json()["config"]["snippets"]["antigravity"]
    cfg = json.loads(snip["mcp_config_json"])["mcpServers"]["baton"]
    assert cfg["serverUrl"].endswith("/mcp") and cfg["headers"]["Authorization"] == f"Bearer {r.json()['token']}"
