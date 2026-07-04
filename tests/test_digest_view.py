"""일일 다이제스트 뷰 + 소스 헬스 패널 테스트 (STAGE1.5_DESIGN §4 트랙 E / §8.6).

단위는 없음 — load_digest/load_source_health는 DB 조립이라 실 Postgres 통합으로만 검증한다.
채팅 범위 토글은 settings.anthropic_api_key를 monkeypatch로 켜서 GET / HTML을 단언한다.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.models import AuditLog, BriefItem, DailyDigest, DigestSource
from app.web.queries import load_digest, load_source_health
from tests.conftest import DASHBOARD_AUTH

client = TestClient(app)

_BRIEF_DATE = date(2026, 6, 21)
_GEN = datetime(2026, 6, 21, 12, tzinfo=timezone.utc)
_T_OLD = datetime(2026, 6, 21, 7, tzinfo=timezone.utc)
_T_NEW = datetime(2026, 6, 21, 8, tzinfo=timezone.utc)


def _daily_run_payload(digest_status: str) -> dict[str, object]:
    return {
        "brief_date": _BRIEF_DATE.isoformat(),
        "sources": [
            {"name": "rss", "status": "ok", "attempted": 5, "error": None},
            {"name": "opendart", "status": "error", "attempted": 0, "error": "key missing"},
        ],
        "embedded": 0,
        "digest_status": digest_status,
    }


# --------------------------------------------------------------------------- load_digest


def test_load_digest_orders_macro_first_and_maps_sources(db: sessionmaker) -> None:
    with db() as s:
        brief = BriefItem(brief_date=_BRIEF_DATE, status="ok", generated_at=_GEN)
        s.add(brief)
        s.flush()
        sector = DailyDigest(
            brief_date=_BRIEF_DATE,
            section="sector:반도체",
            heading="반도체 강세",
            body_text="반도체 섹터 주목 후보",
            status="ok",
            generated_at=_GEN,
        )
        macro = DailyDigest(
            brief_date=_BRIEF_DATE,
            section="macro",
            heading="금리 인하 기대",
            body_text="거시 요약",
            status="ok",
            generated_at=_GEN,
        )
        s.add_all([sector, macro])  # 섹터를 먼저 add — 정렬이 add 순서가 아님을 검증
        s.flush()
        s.add_all(
            [
                DigestSource(digest_id=macro.id, brief_item_id=brief.id),
                DigestSource(digest_id=sector.id, brief_item_id=brief.id),
            ]
        )
        s.commit()
        brief_id = brief.id

    with db() as s:
        views = load_digest(s, _BRIEF_DATE)

    assert [v.raw_section for v in views] == ["macro", "sector:반도체"]  # 거시 먼저
    assert views[0].section_label == "거시"
    assert views[1].section_label == "반도체"
    assert views[0].source_brief_item_ids == [brief_id]
    assert views[1].source_brief_item_ids == [brief_id]


def test_load_digest_empty_when_none(db: sessionmaker) -> None:
    with db() as s:
        assert load_digest(s, date(2099, 1, 1)) == []


# --------------------------------------------------------------------------- load_source_health


def test_load_source_health_reads_latest_daily_run(db: sessionmaker) -> None:
    with db() as s:
        assert load_source_health(s, _BRIEF_DATE) is None  # 없으면 None
        s.add_all(
            [
                AuditLog(
                    ts=_T_OLD,
                    actor="run_daily",
                    action="daily_run",
                    payload=_daily_run_payload("empty"),
                ),
                AuditLog(
                    ts=_T_NEW,
                    actor="run_daily",
                    action="daily_run",
                    payload=_daily_run_payload("ok"),
                ),
            ]
        )
        s.commit()

    with db() as s:  # db 픽스처는 매 테스트 1회만 TRUNCATE라 위 commit은 유지된다
        health = load_source_health(s, _BRIEF_DATE)
    assert health is not None
    assert health.digest_status == "ok"  # 최신(_T_NEW) 행
    assert health.ran_at == _T_NEW
    assert health.incomplete is False  # 완주한 날 — fallback 아님
    names = {src.name: src for src in health.sources}
    assert names["rss"].status == "ok"
    assert names["opendart"].status == "error"
    assert names["opendart"].error == "key missing"


def _source_fetch_row(ts: datetime, name: str, status: str, attempted: int) -> AuditLog:
    return AuditLog(
        ts=ts,
        actor="run_daily",
        action="source_fetch",
        payload={"name": name, "status": status, "attempted": attempted, "error": None},
    )


def test_load_source_health_falls_back_to_source_fetch(db: sessionmaker) -> None:
    """daily_run이 없는 날(실행 미완주) → source_fetch 이름별 최신 병합 + incomplete=True."""
    with db() as s:
        s.add_all(
            [
                _source_fetch_row(_T_OLD, "rss", "error", 0),
                _source_fetch_row(_T_NEW, "rss", "ok", 5),  # 같은 이름 — 최신이 이긴다
                _source_fetch_row(_T_NEW, "naver", "ok", 7),
            ]
        )
        s.commit()
    with db() as s:
        health = load_source_health(s, _BRIEF_DATE)
    assert health is not None
    assert health.incomplete is True
    assert health.ran_at == _T_NEW  # 마지막 수집 시각
    names = {src.name: src for src in health.sources}
    assert set(names) == {"rss", "naver"}
    assert names["rss"].status == "ok" and names["rss"].attempted == 5


def test_load_source_health_fallback_ignores_out_of_window(db: sessionmaker) -> None:
    """KST 종일 윈도우 밖 source_fetch만 있으면 기존대로 None(패널 숨김)."""
    with db() as s:
        # 6/21 KST 윈도우는 [6/20 15:00, 6/21 15:00) UTC — 15:00 UTC는 KST로 이미 6/22.
        s.add(_source_fetch_row(datetime(2026, 6, 21, 16, tzinfo=timezone.utc), "rss", "ok", 3))
        s.commit()
    with db() as s:
        assert load_source_health(s, _BRIEF_DATE) is None


# --------------------------------------------------------------------------- GET / 통합


def test_dashboard_renders_digest_cards_and_source_health(db: sessionmaker) -> None:
    with db() as s:
        brief = BriefItem(
            brief_date=_BRIEF_DATE,
            status="ok",
            event_type="price_move",
            generated_at=_GEN,
        )
        s.add(brief)
        s.flush()
        macro = DailyDigest(
            brief_date=_BRIEF_DATE,
            section="macro",
            heading="금리 인하 기대",
            body_text="거시 요약",
            status="ok",
            generated_at=_GEN,
        )
        s.add(macro)
        s.flush()
        s.add(DigestSource(digest_id=macro.id, brief_item_id=brief.id))
        s.add(
            AuditLog(
                ts=_T_NEW,
                actor="run_daily",
                action="daily_run",
                payload=_daily_run_payload("ok"),
            )
        )
        s.commit()
        brief_id = brief.id

    resp = client.get(f"/?date={_BRIEF_DATE.isoformat()}", auth=DASHBOARD_AUTH)
    assert resp.status_code == 200
    body = resp.text
    assert "일일 다이제스트" in body
    assert "거시" in body and "금리 인하 기대" in body
    assert "opendart" in body and "key missing" in body  # 소스 헬스 칩
    assert f'id="brief-{brief_id}"' in body  # 브리프 앵커
    assert f'href="#brief-{brief_id}"' in body  # 다이제스트 → 브리프 링크
    assert "2026-06-20" in body and "2026-06-22" in body  # prev/next 날짜 네비


def test_dashboard_chat_form_has_scope_toggle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.main.settings.anthropic_api_key", "test-key")
    resp = client.get("/?date=2099-01-01", auth=DASHBOARD_AUTH)
    assert resp.status_code == 200
    body = resp.text
    assert 'value="date"' in body
    assert 'value="cumulative"' in body
    assert "이 날짜" in body and "전체 누적" in body


def test_dashboard_cumulative_radio_disabled_without_embedder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """임베더 없는 서버(Fly 이미지)는 누적 라디오가 disabled + 툴팁으로 렌더된다."""
    monkeypatch.setattr("app.main.settings.anthropic_api_key", "test-key")
    monkeypatch.setattr("app.main._rag_available", lambda: False)
    body = client.get("/?date=2099-01-01", auth=DASHBOARD_AUTH).text
    assert 'value="cumulative" disabled' in body
    assert "임베딩 모델이 설치되지 않아" in body


def test_dashboard_cumulative_radio_enabled_with_embedder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.main.settings.anthropic_api_key", "test-key")
    monkeypatch.setattr("app.main._rag_available", lambda: True)
    body = client.get("/?date=2099-01-01", auth=DASHBOARD_AUTH).text
    assert 'value="cumulative"' in body
    assert 'value="cumulative" disabled' not in body


def test_dashboard_renders_incomplete_run_banner(db: sessionmaker) -> None:
    """daily_run 없이 source_fetch만 있는 날 — 소스 칩 + '실행 미완료' 배너 렌더."""
    with db() as s:
        s.add(_source_fetch_row(_T_NEW, "rss", "ok", 5))
        s.commit()
    resp = client.get(f"/?date={_BRIEF_DATE.isoformat()}", auth=DASHBOARD_AUTH)
    assert resp.status_code == 200
    body = resp.text
    assert "일일 실행 미완료" in body
    assert "rss" in body
