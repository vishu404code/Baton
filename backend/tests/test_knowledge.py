"""The AIs know a website's content: it is seeded, searchable, can be added from a link, and reaches every prompt."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

SITE_DATA = {"articles": [{"id": 1, "title": "Quokka Cafe Guide", "category": "food", "tags": ["quokka", "coffee"], "body": ["The best flat white on Mars costs 4 credits."]}]}


class _Site(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/js/data.js":
            body, ctype = "window.SITE = " + json.dumps(SITE_DATA) + ";" + " " * 600, "application/javascript"
        else:
            body, ctype = '<html><head><title>Mars Magazine</title><script src="/js/data.js"></script></head><body><div id="app"></div></body></html>', "text/html"
        data = body.encode()
        self.send_response(200)
        self.send_header("content-type", ctype)
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture()
def site():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Site)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def test_seeded_site_is_searchable_and_reaches_prompts(client, monkeypatch):
    from app.config import get_settings
    from app.db import SessionLocal
    from app.services import knowledge as kn

    monkeypatch.setattr(get_settings(), "baton_local_mode", True)
    local = client.post("/api/session/local").json()
    h = {"Authorization": f"Bearer {local['token']}"}
    src = client.get("/api/knowledge", headers=h).json()["sources"]
    assert src[0]["source"] == "The Jaipur Journals" and src[0]["documents"] >= 40

    with SessionLocal() as db:
        assert "Hawa Mahal" in [d.title for d in kn.search(db, "photo spot hawa mahal sunrise", 3)]
        block, n = kn.prompt_block(db, "where to eat pyaaz kachori")
    assert n > 0 and "Never say you cannot access the website" in block and "Pyaaz Kachori" in block

    # The shared briefing every tool reads lists what is available.
    ho = client.get(f"/api/rooms/{local['room_id']}/context", headers=h).json()["handoff_markdown"]
    assert "## Knowledge base" in ho and "search_knowledge" in ho


def test_add_a_website_from_a_link(client, site):
    from app.api import knowledge  # noqa: F401
    from tests.test_providers_runner import _setup  # noqa: F401

    r = client.post("/api/session", json={"display_name": "Asha"})
    h = {"Authorization": f"Bearer {r.json()['token']}"}
    added = client.post("/api/knowledge/url", json={"url": site}, headers=h)
    assert added.status_code == 201 and added.json()["added"] == 1 and added.json()["source"] == "Mars Magazine"
    bad = client.post("/api/knowledge/url", json={"url": "http://127.0.0.1:9/nothing"}, headers=h)
    assert bad.status_code == 400 and "reach" in bad.json()["error"]["message"]
    assert client.delete("/api/knowledge/Mars Magazine", headers=h).status_code == 204
    assert client.get("/api/knowledge", headers=h).json()["sources"] == []
