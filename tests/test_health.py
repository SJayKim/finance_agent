from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health() -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_dashboard_root() -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert "증거 브리프" in resp.text


def test_trigger_stub() -> None:
    resp = client.post("/trigger")
    assert resp.status_code == 200
    assert resp.json()["status"] == "accepted"
