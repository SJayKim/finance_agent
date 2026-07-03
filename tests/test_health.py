from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.pipeline.pipeline import PipelineAlreadyRunning
from tests.conftest import DASHBOARD_AUTH

client = TestClient(app)


def test_health() -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_dashboard_root(db: sessionmaker) -> None:
    # GET /는 이제 DB(brief_items)를 읽는다 — db 픽스처로 격리(없으면 skip).
    resp = client.get("/", auth=DASHBOARD_AUTH)
    assert resp.status_code == 200
    assert "증거 브리프" in resp.text


def test_dashboard_root_requires_auth() -> None:
    resp = client.get("/")
    assert resp.status_code == 401
    assert resp.headers["www-authenticate"] == "Basic"


def test_dashboard_root_rejects_invalid_auth() -> None:
    resp = client.get("/", auth=("wrong", "credentials"))
    assert resp.status_code == 401
    assert resp.headers["www-authenticate"] == "Basic"


def test_dashboard_root_fails_closed_without_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.main.settings.dashboard_username", None)
    monkeypatch.setattr("app.main.settings.dashboard_password", None)
    resp = client.get("/", auth=DASHBOARD_AUTH)
    assert resp.status_code == 401
    assert resp.headers["www-authenticate"] == "Basic"


def test_protected_actions_require_auth() -> None:
    assert client.post("/chat").status_code == 401
    assert client.post("/trigger").status_code == 401
    assert client.post("/run-daily").status_code == 401


def test_trigger_runs_pipeline_for_today_kst(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[date] = []

    def fake_run(brief_date: date) -> None:
        calls.append(brief_date)

    monkeypatch.setattr("app.main.run_pipeline", fake_run)
    resp = client.post("/trigger", auth=DASHBOARD_AUTH)
    assert resp.status_code == 200
    assert len(calls) == 1
    assert resp.json() == {"status": "ok", "brief_date": calls[0].isoformat()}


def test_trigger_conflict_returns_409(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(brief_date: date) -> None:
        raise PipelineAlreadyRunning("already running")

    monkeypatch.setattr("app.main.run_pipeline", boom)
    resp = client.post("/trigger", auth=DASHBOARD_AUTH)
    assert resp.status_code == 409
    assert "already running" in resp.json()["detail"]
