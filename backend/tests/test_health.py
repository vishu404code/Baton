from fastapi.testclient import TestClient

from app import main


def test_health_ok(monkeypatch):
    monkeypatch.setattr(main, "db_ok", lambda: True)
    r = TestClient(main.app).get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_health_reports_db_down(monkeypatch):
    monkeypatch.setattr(main, "db_ok", lambda: False)
    r = TestClient(main.app).get("/health")
    assert r.status_code == 503
    assert r.json()["db"] == "unreachable"


def test_cors_allows_frontend_dev_server(monkeypatch):
    monkeypatch.setattr(main, "db_ok", lambda: True)
    r = TestClient(main.app).options(
        "/health",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
    )
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"
