"""누적 RAG 채팅 테스트 (STAGE1.5_DESIGN §4 트랙 D2).

DB(실 Postgres): search_citation_spans가 코사인 유사도 순으로 정렬하고 임베딩 NULL인
문서의 인용을 제외하는지, 누적(전 날짜) 코퍼스를 가로질러 검색하는지. 채팅 거부 경계는
하루치 채팅과 동일(인용 0 → None) — FakeEmbedder + 가짜 anthropic 클라이언트로 네트워크·
모델 없이 검증한다. 라우트는 _rag_analyzer를 monkeypatch로 주입(키·임베더 불필요).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace
from typing import Any, cast

import anthropic
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.embed import FakeEmbedder
from app.main import app
from app.models import BriefItem, Citation, RawDocument, Source
from app.web.chat import ChatAnswer, ChatCitation, anthropic_rag_chat
from app.web.queries import search_citation_spans
from tests.conftest import DASHBOARD_AUTH

client = TestClient(app)

_PUB = datetime(2026, 6, 21, 9, tzinfo=timezone.utc)
_GEN = datetime(2026, 6, 21, 12, tzinfo=timezone.utc)

# search_citation_spans는 임베딩 텍스트(거리)만 보고, 인용 표시 텍스트(cited_text)는 따로.
_NEAR_TEXT = "Bitcoin tops $100K and miners rally hard"
_FAR_TEXT = "완전히 다른 주제: 농산물 작황과 기상 전망에 관한 긴 보고서"
_NEAR_CITED = "Bitcoin tops $100K"
_FAR_CITED = "농산물 작황 호조"


def _cite(document_index: int, cited_text: str) -> SimpleNamespace:
    return SimpleNamespace(
        type="char_location", document_index=document_index, cited_text=cited_text
    )


def _text_block(text: str, citations: list[SimpleNamespace] | None = None) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text, citations=citations)


def _fake_client(responses: list[Any]) -> anthropic.Anthropic:
    def create(**kwargs: Any) -> Any:
        return responses.pop(0)

    return cast(anthropic.Anthropic, SimpleNamespace(messages=SimpleNamespace(create=create)))


def _add_doc(s: Session, src_id: int, ext: str, embed_text: str | None, url: str) -> RawDocument:
    """raw_document 1건 추가. embed_text가 None이면 embedding NULL(검색 후보에서 제외)."""
    embedder = FakeEmbedder()
    doc = RawDocument(
        source_id=src_id,
        external_id=ext,
        title=ext,
        published_at=_PUB,
        url=url,
        embedding=(embedder.embed([embed_text])[0] if embed_text is not None else None),
    )
    s.add(doc)
    s.flush()
    return doc


def _add_brief_with_citation(s: Session, brief_date: date, doc_id: int, cited_text: str) -> None:
    item = BriefItem(brief_date=brief_date, cluster_id=None, status="ok", generated_at=_GEN)
    s.add(item)
    s.flush()
    s.add(
        Citation(
            brief_item_id=item.id,
            raw_document_id=doc_id,
            cited_text=cited_text,
            source_published_at=_PUB,
        )
    )


# --------------------------------------------------------------------------- DB: 벡터 검색


def test_search_citation_spans_orders_by_similarity_and_filters_null(db: sessionmaker) -> None:
    with db() as s:
        src = Source(name="seed-src", kind="news")
        s.add(src)
        s.flush()
        near = _add_doc(s, src.id, "near", _NEAR_TEXT, "http://near")
        far = _add_doc(s, src.id, "far", _FAR_TEXT, "http://far")
        null_doc = _add_doc(s, src.id, "null", None, "http://null")
        _add_brief_with_citation(s, date(2026, 6, 21), near.id, _NEAR_CITED)
        _add_brief_with_citation(s, date(2026, 6, 21), far.id, _FAR_CITED)
        _add_brief_with_citation(s, date(2026, 6, 21), null_doc.id, "임베딩 없는 인용")
        s.commit()

        query_vec = FakeEmbedder().embed([_NEAR_TEXT])[0]
        views = search_citation_spans(s, query_vec, top_k=8)

    urls = [v.url for v in views]
    assert "http://null" not in urls  # 임베딩 NULL 문서의 인용은 제외
    assert urls[0] == "http://near"  # 질의와 동일 텍스트 → 가장 가까움
    assert set(urls) == {"http://near", "http://far"}


def test_search_citation_spans_respects_top_k(db: sessionmaker) -> None:
    with db() as s:
        src = Source(name="seed-src", kind="news")
        s.add(src)
        s.flush()
        for i in range(5):
            doc = _add_doc(s, src.id, f"d{i}", f"distinct topic number {i}", f"http://d{i}")
            _add_brief_with_citation(s, date(2026, 6, 21), doc.id, f"cited {i}")
        s.commit()
        views = search_citation_spans(
            s, FakeEmbedder().embed(["distinct topic number 0"])[0], top_k=3
        )
    assert len(views) == 3


# --------------------------------------------------------------------------- DB: RAG 분석기


def test_rag_chat_grounded_answer_cross_date(db: sessionmaker) -> None:
    with db() as s:
        src = Source(name="seed-src", kind="news")
        s.add(src)
        s.flush()
        d1 = _add_doc(s, src.id, "d1", _NEAR_TEXT, "http://d1")
        d2 = _add_doc(s, src.id, "d2", "Ethereum upgrade ships on mainnet today", "http://d2")
        _add_brief_with_citation(s, date(2026, 6, 20), d1.id, "Bitcoin tops $100K")
        _add_brief_with_citation(s, date(2026, 6, 21), d2.id, "ETH upgrade live")  # 다른 날짜
        s.commit()

        # 검색은 거리순 — document_index가 sources 순서이므로 두 인덱스 모두 인용해 다중 날짜 검증.
        resp = SimpleNamespace(
            content=[
                _text_block(
                    "두 이벤트.",
                    [_cite(0, "Bitcoin tops $100K"), _cite(1, "ETH upgrade live")],
                )
            ]
        )
        analyzer = anthropic_rag_chat(_fake_client([resp]), "m", FakeEmbedder())
        answer = analyzer(s, "최근 무슨 일?")

    assert answer is not None
    cited = {c.cited_text for c in answer.citations}
    assert cited == {"Bitcoin tops $100K", "ETH upgrade live"}  # 두 날짜의 근거가 함께


def test_rag_chat_refuses_when_model_cites_nothing(db: sessionmaker) -> None:
    with db() as s:
        src = Source(name="seed-src", kind="news")
        s.add(src)
        s.flush()
        doc = _add_doc(s, src.id, "d", _NEAR_TEXT, "http://d")
        _add_brief_with_citation(s, date(2026, 6, 21), doc.id, "Bitcoin tops $100K")
        s.commit()
        resp = SimpleNamespace(content=[_text_block("추측입니다.", citations=None)])
        analyzer = anthropic_rag_chat(_fake_client([resp]), "m", FakeEmbedder())
        assert analyzer(s, "?") is None  # 인용 0 → 거부


def test_rag_chat_refuses_when_corpus_empty(db: sessionmaker) -> None:
    # 임베딩된 인용이 0건 → 검색 결과 없음 → 클라이언트 호출 없이 None.
    with db() as s:
        analyzer = anthropic_rag_chat(_fake_client([]), "m", FakeEmbedder())
        assert analyzer(s, "아무거나") is None  # _fake_client([]) → pop이 호출되면 IndexError


# --------------------------------------------------------------------------- 라우트: scope 분기


def test_chat_cumulative_scope_uses_rag(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_rag(session: Any, question: str) -> ChatAnswer:
        return ChatAnswer(
            text="누적 코퍼스 답변.",
            citations=[ChatCitation(cited_text="Bitcoin tops $100K", url="http://x", title="X")],
        )

    monkeypatch.setattr("app.main._rag_analyzer", lambda: fake_rag)
    resp = client.post(
        "/chat",
        data={"q": "전체에서 무슨 일?", "scope": "cumulative"},
        auth=DASHBOARD_AUTH,
    )
    assert resp.status_code == 200
    assert "누적 코퍼스 답변." in resp.text
    assert 'href="http://x"' in resp.text


def test_chat_cumulative_disabled_when_no_embedder(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.main._rag_analyzer", lambda: None)
    resp = client.post(
        "/chat",
        data={"q": "질문", "scope": "cumulative"},
        auth=DASHBOARD_AUTH,
    )
    assert resp.status_code == 200
    assert "채팅 비활성" in resp.text


def test_chat_cumulative_empty_input_refuses_without_calling_analyzer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(session: Any, question: str) -> None:
        raise AssertionError("빈 입력은 analyzer를 호출하면 안 된다")

    monkeypatch.setattr("app.main._rag_analyzer", lambda: boom)
    resp = client.post(
        "/chat",
        data={"q": "   ", "scope": "cumulative"},
        auth=DASHBOARD_AUTH,
    )
    assert resp.status_code == 200
    assert "관련 근거 없음" in resp.text
