"""OpenAI 단일 콜 quote-and-verify 채팅 단위 테스트 (네트워크·DB 없이).

_verify_chat_citations 순수 함수와 openai_chat/openai_rag_chat 오케스트레이션을 가짜
transport로 덮는다. rag는 search_citation_spans를 monkeypatch해 DB 없이 검증한다.
계약은 anthropic_chat/anthropic_rag_chat과 동일(sources 0 → None, 검증 인용 0 → None, 장애 → None).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import app.web.openai_chat as openai_chat_mod
from app.llm.gateway import LLMError, OpenAIResponses
from app.web.chat import _ChatSource
from app.web.openai_chat import _verify_chat_citations, openai_chat, openai_rag_chat
from app.web.queries import BriefView, CitationView

_PUB = datetime(2026, 6, 21, 9, tzinfo=timezone.utc)
_GEN = datetime(2026, 6, 21, 12, tzinfo=timezone.utc)

_SOURCES = [
    _ChatSource(cited_text="Bitcoin tops $100K", url="http://a", title="A"),
    _ChatSource(cited_text="ETH upgrade ships", url="http://b", title="B"),
]


def _brief_with_citation(url: str | None, cited_text: str = "Bitcoin tops $100K") -> BriefView:
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
            CitationView(cited_text=cited_text, source_published_at=_PUB, url=url, title="A")
        ],
    )


def _response(payload: dict[str, Any], status: str = "completed") -> SimpleNamespace:
    return SimpleNamespace(status=status, output_text=json.dumps(payload, ensure_ascii=False))


def _fake_transport(responses: list[Any]) -> tuple[OpenAIResponses, list[dict[str, Any]]]:
    calls: list[dict[str, Any]] = []

    def transport(**kwargs: Any) -> Any:
        calls.append(kwargs)
        return responses.pop(0)

    return transport, calls


# --------------------------------------------------------------------------- 순수: 인용 검증


def test_verify_maps_and_dedupes_citations() -> None:
    data = {
        "citations": [
            {"doc_index": 0, "quote": "Bitcoin tops $100K"},
            {"doc_index": 0, "quote": "Bitcoin tops $100K"},  # 중복 → dedupe
            {"doc_index": 1, "quote": "ETH upgrade ships"},
        ]
    }
    citations = _verify_chat_citations(data, _SOURCES)
    assert [(c.url, c.cited_text) for c in citations] == [
        ("http://a", "Bitcoin tops $100K"),
        ("http://b", "ETH upgrade ships"),
    ]


def test_verify_accepts_substring_quote() -> None:
    data = {"citations": [{"doc_index": 0, "quote": "tops $100K"}]}  # 부분 인용
    citations = _verify_chat_citations(data, _SOURCES)
    assert [c.cited_text for c in citations] == ["tops $100K"]


def test_verify_whitespace_normalized_match() -> None:
    sources = [_ChatSource(cited_text="가격이 급등\n했다", url="http://a", title="A")]
    data = {"citations": [{"doc_index": 0, "quote": "가격이 급등 했다"}]}
    citations = _verify_chat_citations(data, sources)
    assert len(citations) == 1


def test_verify_drops_hallucinated_and_out_of_range() -> None:
    data = {
        "citations": [
            {"doc_index": 0, "quote": "원문에 없는 문장"},  # 환각
            {"doc_index": 9, "quote": "ghost"},  # 범위 밖
        ]
    }
    assert _verify_chat_citations(data, _SOURCES) == []


# --------------------------------------------------------------------------- openai_chat


def test_chat_grounded_answer() -> None:
    payload = {"answer_text": "BTC rallied.", "citations": [{"doc_index": 0, "quote": "tops $100K"}]}
    transport, calls = _fake_transport([_response(payload)])
    answer = openai_chat(transport, "gpt-5.4")("무슨 일?", [_brief_with_citation("http://a")])
    assert answer is not None
    assert answer.text == "BTC rallied."
    assert [c.url for c in answer.citations] == ["http://a"]
    assert calls[0]["max_output_tokens"] == 1024
    assert calls[0]["text"]["format"]["strict"] is True


def test_chat_refuses_when_model_cites_nothing() -> None:
    payload = {"answer_text": "추측입니다.", "citations": []}
    transport, _ = _fake_transport([_response(payload)])
    assert openai_chat(transport, "m")("?", [_brief_with_citation("http://a")]) is None


def test_chat_refuses_when_no_sources() -> None:
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
    transport, calls = _fake_transport([])
    assert openai_chat(transport, "m")("?", [empty]) is None
    assert calls == []  # 근거 0 → API 미호출


def test_chat_returns_none_on_api_error() -> None:
    def transport(**kwargs: Any) -> Any:
        raise LLMError("down")

    assert openai_chat(transport, "m")("?", [_brief_with_citation("http://a")]) is None


def test_chat_returns_none_on_truncated_json() -> None:
    resp = SimpleNamespace(status="incomplete", output_text='{"answer_text": "cut')
    transport, _ = _fake_transport([resp])
    assert openai_chat(transport, "m")("?", [_brief_with_citation("http://a")]) is None


# --------------------------------------------------------------------------- openai_rag_chat


class _FakeEmbedder:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0, 0.0, 0.0] for _ in texts]


def test_rag_chat_grounded_answer(monkeypatch: Any) -> None:
    views = [CitationView(cited_text="Bitcoin tops $100K", source_published_at=_PUB, url="http://a", title="A")]
    monkeypatch.setattr(openai_chat_mod, "search_citation_spans", lambda s, v, top_k: views)
    payload = {"answer_text": "BTC.", "citations": [{"doc_index": 0, "quote": "Bitcoin tops $100K"}]}
    transport, _ = _fake_transport([_response(payload)])
    analyzer = openai_rag_chat(transport, "m", _FakeEmbedder())  # type: ignore[arg-type]
    answer = analyzer(object(), "최근 무슨 일?")  # type: ignore[arg-type]
    assert answer is not None
    assert [c.url for c in answer.citations] == ["http://a"]


def test_rag_chat_refuses_when_corpus_empty(monkeypatch: Any) -> None:
    monkeypatch.setattr(openai_chat_mod, "search_citation_spans", lambda s, v, top_k: [])
    transport, calls = _fake_transport([])
    analyzer = openai_rag_chat(transport, "m", _FakeEmbedder())  # type: ignore[arg-type]
    assert analyzer(object(), "아무거나") is None  # type: ignore[arg-type]
    assert calls == []  # 검색 결과 0 → API 미호출


def test_rag_chat_uses_top_k_8(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}

    def fake_search(session: Any, vec: Any, top_k: int) -> list[CitationView]:
        captured["top_k"] = top_k
        return []

    monkeypatch.setattr(openai_chat_mod, "search_citation_spans", fake_search)
    transport, _ = _fake_transport([])
    openai_rag_chat(transport, "m", _FakeEmbedder())(object(), "q")  # type: ignore[arg-type]
    assert captured["top_k"] == 8  # anthropic_rag_chat과 동일 미러
