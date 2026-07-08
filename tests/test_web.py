"""대시보드 웹 계층 테스트 (STAGE1_DASHBOARD_SPEC).

단위(네트워크·DB 없이): 채팅 인용 파싱·거부 로직, BriefView.last_updated.
통합(실 Postgres): load_brief 그룹핑, GET / HTML 단언, POST /chat 스텁 analyzer로
근거있음 vs 거부. 채팅 analyzer는 monkeypatch로 주입 — 네트워크·키 불필요.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.llm.gateway import AnthropicMessages
from app.main import app
from app.models import (
    BriefItem,
    BriefItemTicker,
    Citation,
    Cluster,
    RawDocument,
    Source,
)
from app.web.chat import ChatAnswer, ChatCitation, _ChatSource, _parse_chat, anthropic_chat
from app.web.queries import (
    BriefView,
    CitationView,
    TickerView,
    board_asset_counts,
    dates_with_briefs,
    load_brief,
    rank_board,
)
from tests.conftest import DASHBOARD_AUTH

client = TestClient(app)

_BRIEF_DATE = date(2026, 6, 21)
_PUB = datetime(2026, 6, 21, 9, tzinfo=timezone.utc)
_GEN = datetime(2026, 6, 21, 12, tzinfo=timezone.utc)


# --------------------------------------------------------------------------- 단위: BriefView


def _citation_view(pub: datetime | None) -> CitationView:
    return CitationView(cited_text="c", source_published_at=pub, url=None, title=None)


def test_last_updated_takes_max_of_generated_and_citation() -> None:
    later = datetime(2026, 6, 21, 18, tzinfo=timezone.utc)
    view = BriefView(
        id=1,
        event_type=None,
        direction=None,
        confidence=None,
        analysis_text=None,
        status="ok",
        generated_at=_GEN,
        tickers=[],
        citations=[_citation_view(later)],
    )
    assert view.last_updated == later


def test_last_updated_falls_back_to_generated_when_no_citation_times() -> None:
    view = BriefView(
        id=1,
        event_type=None,
        direction=None,
        confidence=None,
        analysis_text=None,
        status="empty",
        generated_at=_GEN,
        tickers=[],
        citations=[_citation_view(None)],
    )
    assert view.last_updated == _GEN


def _scored_brief(id: int, score: int | None, cluster: int | None, status: str = "ok") -> BriefView:
    return BriefView(
        id=id,
        event_type="e",
        direction="긍정",
        confidence="MED",
        analysis_text="a",
        status=status,
        generated_at=_GEN,
        tickers=[],
        citations=[],
        impact_score=score,
        cluster_id=cluster,
    )


def test_rank_board_sorts_by_impact_desc_and_labels_groups() -> None:
    briefs = [
        _scored_brief(1, 40, cluster=7),
        _scored_brief(2, 90, cluster=3),
        _scored_brief(3, 70, cluster=3),  # 같은 클러스터 → 같은 그룹
    ]
    rows = rank_board(briefs)
    assert [r.brief_id for r in rows] == [2, 3, 1]  # 임팩트 내림차순
    assert [r.impact_score for r in rows] == [90, 70, 40]
    assert rows[0].group_label == "G1" and rows[1].group_label == "G1"  # cluster 3 공유
    assert rows[2].group_label == "G2"  # cluster 7
    assert rows[0].group_shape == "●" and rows[2].group_shape == "▲"


def test_rank_board_group_index_wraps_to_palette() -> None:
    # Regression: 임팩트 보드 그룹 색 인코딩이 6번째 그룹부터 사라지는 버그
    # Found by /qa on 2026-06-25
    # group_index가 g6.. CSS 클래스를 내보내면 색 정의(g1~g5)가 없어 칩이 저대비로 떨어짐.
    # 색 클래스는 모양(% 5)과 같은 주기로 순환해야 한다 — group_index는 1..5를 벗어나면 안 됨.
    briefs = [_scored_brief(i, 100 - i, cluster=i) for i in range(1, 8)]  # 클러스터 7개(>5)
    rows = rank_board(briefs)
    assert [r.group_label for r in rows] == [f"G{i}" for i in range(1, 8)]  # 라벨은 고유
    assert [r.group_index for r in rows] == [1, 2, 3, 4, 5, 1, 2]  # 색 클래스는 순환
    # 6번째 그룹은 색·모양 모두 1번째와 동일(라벨만 다름)
    assert rows[5].group_index == rows[0].group_index
    assert rows[5].group_shape == rows[0].group_shape


def test_rank_board_excludes_unscored_and_non_ok() -> None:
    briefs = [
        _scored_brief(1, None, cluster=1),  # 미분석(impact_score 없음)
        _scored_brief(2, 50, cluster=1, status="degraded"),  # ok 아님
        _scored_brief(3, 60, cluster=2, status="ok"),
    ]
    rows = rank_board(briefs)
    assert [r.brief_id for r in rows] == [3]


# --------------------------------------------------------------------------- 단위: 자산 분류


def _ticker(market: str) -> TickerView:
    return TickerView(ticker="X", market=market, is_candidate=False)


def test_asset_classes_maps_market_to_class() -> None:
    crypto = BriefView(
        id=1, event_type=None, direction=None, confidence=None, analysis_text=None,
        status="ok", generated_at=_GEN, tickers=[_ticker("CRYPTO")], citations=[],
    )
    stock = BriefView(
        id=2, event_type=None, direction=None, confidence=None, analysis_text=None,
        status="ok", generated_at=_GEN, tickers=[_ticker("KR"), _ticker("US")], citations=[],
    )
    mixed = BriefView(
        id=3, event_type=None, direction=None, confidence=None, analysis_text=None,
        status="ok", generated_at=_GEN, tickers=[_ticker("CRYPTO"), _ticker("KR")], citations=[],
    )
    none = BriefView(
        id=4, event_type=None, direction=None, confidence=None, analysis_text=None,
        status="ok", generated_at=_GEN, tickers=[], citations=[],
    )
    assert crypto.asset_classes == ["crypto"]
    assert stock.asset_classes == ["stock"]
    assert mixed.asset_classes == ["crypto", "stock"]
    assert none.asset_classes == []


def test_board_asset_counts_per_class() -> None:
    def _b(id: int, markets: list[str], score: int) -> BriefView:
        return BriefView(
            id=id, event_type="e", direction="긍정", confidence="MED", analysis_text="a",
            status="ok", generated_at=_GEN, tickers=[_ticker(m) for m in markets],
            citations=[], impact_score=score, cluster_id=id,
        )

    board = rank_board([
        _b(1, ["CRYPTO"], 90),  # crypto only
        _b(2, ["KR", "US"], 80),  # stock only
        _b(3, ["CRYPTO", "KR"], 70),  # 양쪽 다 링크
        _b(4, [], 60),  # 미링크 → all에만
    ])
    assert board_asset_counts(board) == {"all": 4, "stock": 2, "crypto": 2}


# --------------------------------------------------------------------------- 단위: 채팅 파싱


def _cite(document_index: int, cited_text: str) -> dict[str, Any]:
    return {"type": "char_location", "document_index": document_index, "cited_text": cited_text}


def _text_block(text: str, citations: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"type": "text", "text": text, "citations": citations}


_SOURCES = [
    _ChatSource(cited_text="tops $100K", url="http://a", title="A"),
    _ChatSource(cited_text="ETH upgrade", url="http://b", title="B"),
]


def test_parse_chat_maps_and_dedupes_citations() -> None:
    content = [
        _text_block("BTC up. ", [_cite(0, "tops $100K"), _cite(0, "tops $100K")]),  # 중복
        _text_block("ETH live.", [_cite(1, "ETH upgrade")]),
    ]
    text, citations = _parse_chat(content, _SOURCES)
    assert text == "BTC up. ETH live."
    assert [(c.url, c.cited_text) for c in citations] == [
        ("http://a", "tops $100K"),
        ("http://b", "ETH upgrade"),
    ]


def test_parse_chat_drops_out_of_range_index() -> None:
    _, citations = _parse_chat([_text_block("x", [_cite(9, "ghost")])], _SOURCES)
    assert citations == []


def _fake_transport(responses: list[dict[str, Any]]) -> AnthropicMessages:
    def transport(**kwargs: Any) -> dict[str, Any]:
        return responses.pop(0)

    return transport


def _brief_with_citation(url: str | None) -> BriefView:
    return BriefView(
        id=1,
        event_type="price_move",
        direction="긍정",
        confidence="MED",
        analysis_text="impact",
        status="ok",
        generated_at=_GEN,
        tickers=[],
        citations=[
            CitationView(cited_text="tops $100K", source_published_at=_PUB, url=url, title="A")
        ],
    )


def test_anthropic_chat_grounded_answer() -> None:
    resp = {"content": [_text_block("BTC rallied.", [_cite(0, "tops $100K")])]}
    answer = anthropic_chat(_fake_transport([resp]), "m")(
        "무슨 일?", [_brief_with_citation("http://a")]
    )
    assert answer is not None
    assert answer.text == "BTC rallied."
    assert [c.url for c in answer.citations] == ["http://a"]


def test_anthropic_chat_refuses_when_no_citation() -> None:
    resp = {"content": [_text_block("추측입니다.", citations=None)]}
    assert (
        anthropic_chat(_fake_transport([resp]), "m")("?", [_brief_with_citation("http://a")])
        is None
    )


def test_anthropic_chat_refuses_when_no_sources() -> None:
    empty = BriefView(
        id=1,
        event_type=None,
        direction=None,
        confidence=None,
        analysis_text=None,
        status="empty",
        generated_at=_GEN,
        tickers=[],
        citations=[],
    )
    # 근거 0 → API 미호출, None 반환
    assert anthropic_chat(_fake_transport([]), "m")("?", [empty]) is None


# --------------------------------------------------------------------------- 통합: DB + 라우트


def _seed_brief(db: sessionmaker) -> None:
    """ok 브리프(티커 2 + 인용 1) + empty 브리프 1건을 시드."""
    with db() as s:
        src = Source(name="seed-src", kind="news")
        s.add(src)
        s.flush()
        doc = RawDocument(
            source_id=src.id,
            external_id="x",
            title="Bitcoin tops $100K",
            published_at=_PUB,
            url="http://news/btc",
        )
        s.add(doc)
        cluster = Cluster(brief_date=_BRIEF_DATE, representative_doc_id=None)
        s.add(cluster)
        s.flush()
        ok = BriefItem(
            brief_date=_BRIEF_DATE,
            cluster_id=cluster.id,
            event_type="price_move",
            direction="긍정",
            confidence="MED",
            analysis_text="BTC 영향 분석",
            status="ok",
            generated_at=_GEN,
        )
        empty = BriefItem(
            brief_date=_BRIEF_DATE, cluster_id=None, status="empty", generated_at=_GEN
        )
        s.add_all([ok, empty])
        s.flush()
        s.add_all(
            [
                BriefItemTicker(
                    brief_item_id=ok.id, ticker="BTC", market="CRYPTO", is_candidate=False
                ),
                BriefItemTicker(brief_item_id=ok.id, ticker="MSTR", market="US", is_candidate=True),
                Citation(
                    brief_item_id=ok.id,
                    raw_document_id=doc.id,
                    cited_text="Bitcoin tops $100K",
                    source_published_at=_PUB,
                ),
            ]
        )
        s.commit()


def test_load_brief_groups_tickers_and_citations(db: sessionmaker) -> None:
    _seed_brief(db)
    with db() as s:
        views = load_brief(s, _BRIEF_DATE)
    assert [v.status for v in views] == ["ok", "empty"]
    ok = views[0]
    assert {t.ticker for t in ok.tickers} == {"BTC", "MSTR"}
    assert any(t.is_candidate for t in ok.tickers)
    assert len(ok.citations) == 1
    assert ok.citations[0].url == "http://news/btc"
    assert views[1].tickers == [] and views[1].citations == []


def test_load_brief_empty_when_no_briefs(db: sessionmaker) -> None:
    with db() as s:
        assert load_brief(s, date(2099, 1, 1)) == []


def test_dashboard_renders_briefs_and_citation_links(db: sessionmaker) -> None:
    _seed_brief(db)
    resp = client.get(f"/?date={_BRIEF_DATE.isoformat()}", auth=DASHBOARD_AUTH)
    assert resp.status_code == 200
    body = resp.text
    assert "price_move" in body and "긍정" in body and "MED" in body
    assert "Bitcoin tops $100K" in body
    assert 'href="http://news/btc"' in body
    assert "후보" in body  # MSTR is_candidate
    assert "근거 없음" in body  # status=empty 항목


def test_dates_with_briefs_includes_seeded_dates(db: sessionmaker) -> None:
    _seed_brief(db)
    with db() as s:
        assert _BRIEF_DATE in dates_with_briefs(s)


def test_dashboard_renders_asset_and_date_chip_markup(db: sessionmaker) -> None:
    _seed_brief(db)
    body = client.get(f"/?date={_BRIEF_DATE.isoformat()}", auth=DASHBOARD_AUTH).text
    assert "asset-tabs" in body
    assert "board-card" in body
    assert "date-chip" in body
    assert 'data-asset="crypto stock"' in body  # ok 브리프: BTC(crypto)+MSTR(us=stock)
    assert "tab-count" in body  # U1: 탭 카운트 라벨
    assert "board-empty" in body  # U1: 빈 상태 안내 요소


def test_dashboard_empty_date_shows_no_brief(db: sessionmaker) -> None:
    resp = client.get("/?date=2099-01-01", auth=DASHBOARD_AUTH)
    assert resp.status_code == 200
    assert "브리프 없음" in resp.text


def test_dashboard_default_date_falls_back_to_latest_data(db: sessionmaker) -> None:
    """?date 미지정 + 오늘 데이터 없음 → 데이터 있는 최신일로 폴백(빈 보드 방지). P4 회귀."""
    _seed_brief(db)  # 과거 _BRIEF_DATE에만 시드, 오늘(KST)엔 데이터 없음
    resp = client.get("/", auth=DASHBOARD_AUTH)
    assert resp.status_code == 200
    body = resp.text
    assert "브리프 없음" not in body  # 오늘(빈 보드)이 아니라 최신 데이터일로 떨어져야
    assert "price_move" in body  # _BRIEF_DATE에 시드된 브리프가 렌더됨


def test_dashboard_rejects_bad_date(db: sessionmaker) -> None:
    assert client.get("/?date=not-a-date", auth=DASHBOARD_AUTH).status_code == 400


def test_chat_grounded(db: sessionmaker, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_brief(db)

    def fake_analyzer(question: str, briefs: Any) -> ChatAnswer:
        return ChatAnswer(
            text="BTC가 10만 달러를 넘었습니다.",
            citations=[
                ChatCitation(cited_text="Bitcoin tops $100K", url="http://news/btc", title="A")
            ],
        )

    monkeypatch.setattr("app.main._chat_analyzer", lambda: fake_analyzer)
    resp = client.post(
        "/chat",
        data={"q": "비트코인 무슨 일?", "date": _BRIEF_DATE.isoformat()},
        auth=DASHBOARD_AUTH,
    )
    assert resp.status_code == 200
    assert "BTC가 10만 달러를 넘었습니다." in resp.text
    assert 'href="http://news/btc"' in resp.text


def test_chat_refusal(db: sessionmaker, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_brief(db)
    monkeypatch.setattr("app.main._chat_analyzer", lambda: lambda q, b: None)
    resp = client.post(
        "/chat",
        data={"q": "헛소리", "date": _BRIEF_DATE.isoformat()},
        auth=DASHBOARD_AUTH,
    )
    assert resp.status_code == 200
    assert "관련 근거 없음" in resp.text


def test_chat_empty_input_refuses_without_calling_analyzer(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(q: str, b: Any) -> None:
        raise AssertionError("빈 입력은 analyzer를 호출하면 안 된다")

    monkeypatch.setattr("app.main._chat_analyzer", lambda: boom)
    resp = client.post(
        "/chat",
        data={"q": "   ", "date": _BRIEF_DATE.isoformat()},
        auth=DASHBOARD_AUTH,
    )
    assert resp.status_code == 200
    assert "관련 근거 없음" in resp.text


def test_chat_disabled_when_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.main._chat_analyzer", lambda: None)
    resp = client.post(
        "/chat",
        data={"q": "질문", "date": _BRIEF_DATE.isoformat()},
        auth=DASHBOARD_AUTH,
    )
    assert resp.status_code == 200
    assert "채팅 비활성" in resp.text
