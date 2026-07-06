"""OpenAI quote-and-verify 단일 콜 분석 단위 테스트 (네트워크 없이).

순수 함수(verify_quotes 등)와 openai_analyzer 오케스트레이션을 가짜 클라이언트로 덮는다.
실 OpenAI 호출은 하지 않는다(키·네트워크 불필요). Responses API 응답은 SimpleNamespace로
흉내낸다 — 방어적 getattr 접근이라 더미로 충분. test_citations.py와 같은 컨벤션.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, cast

import httpx
import openai
import pytest

from app.pipeline.citations import SourceDoc, _document_text
from app.pipeline.openai_citations import (
    AnalyzerStats,
    _docs_prompt,
    openai_analyzer,
    verify_quotes,
)

_PUB = datetime(2026, 6, 20, 12, tzinfo=timezone.utc)


def _doc(doc_id: int, title: str | None = "t", summary: str | None = "s") -> SourceDoc:
    return SourceDoc(raw_document_id=doc_id, title=title, summary=summary, published_at=_PUB)


def _payload(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "analysis_text": "Bitcoin rally",
        "citations": [{"doc_index": 0, "quote": "tops $100K"}],
        "event_type": "price_move",
        "direction": "긍정",
        "confidence": "MED",
        "impact_score": 88,
    }
    base.update(overrides)
    return base


def _response(payload: dict[str, Any], status: str = "completed") -> SimpleNamespace:
    return SimpleNamespace(
        status=status,
        output_text=json.dumps(payload, ensure_ascii=False),
        usage=SimpleNamespace(input_tokens=100, output_tokens=50),
    )


def _fake_client(responses: list[Any]) -> tuple[openai.OpenAI, list[dict[str, Any]]]:
    calls: list[dict[str, Any]] = []

    def create(**kwargs: Any) -> Any:
        calls.append(kwargs)
        return responses.pop(0)

    client = SimpleNamespace(responses=SimpleNamespace(create=create))
    return cast(openai.OpenAI, client), calls


def test_docs_prompt_numbers_and_exact_document_text() -> None:
    docs = [_doc(10, title="첫 제목", summary="첫 요약"), _doc(20, title="둘째", summary=None)]
    prompt = _docs_prompt(docs)
    assert f"[문서 0]\n{_document_text(docs[0])}" in prompt
    assert f"[문서 1]\n{_document_text(docs[1])}" in prompt
    assert prompt.index("[문서 0]") < prompt.index("[문서 1]")


def test_verify_quotes_exact_match_fills_offsets() -> None:
    doc = _doc(10, title="BTC tops $100K", summary="details")
    spans, dropped = verify_quotes({"citations": [{"doc_index": 0, "quote": "tops $100K"}]}, [doc])
    assert dropped == 0
    assert len(spans) == 1
    span = spans[0]
    assert span.raw_document_id == 10
    assert span.cited_text == "tops $100K"
    text = _document_text(doc)
    assert text[span.char_start : span.char_end] == "tops $100K"
    assert span.source_published_at == _PUB


def test_verify_quotes_whitespace_fallback_keeps_none_offsets() -> None:
    doc = _doc(10, title=None, summary="가격이 급등\n했다")
    spans, dropped = verify_quotes(
        {"citations": [{"doc_index": 0, "quote": "가격이 급등 했다"}]}, [doc]
    )
    assert dropped == 0
    assert len(spans) == 1
    assert spans[0].char_start is None
    assert spans[0].char_end is None


def test_verify_quotes_drops_hallucinated_quote(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        spans, dropped = verify_quotes(
            {"citations": [{"doc_index": 0, "quote": "원문에 없는 문장"}]}, [_doc(10)]
        )
    assert spans == []
    assert dropped == 1
    assert "quote dropped" in caplog.text


def test_verify_quotes_drops_out_of_range_index() -> None:
    spans, dropped = verify_quotes({"citations": [{"doc_index": 5, "quote": "t"}]}, [_doc(10)])
    assert spans == []
    assert dropped == 1


def test_analyzer_single_call_happy_path() -> None:
    stats = AnalyzerStats()
    client, calls = _fake_client([_response(_payload())])
    result = openai_analyzer(client, "gpt-5.4-mini", stats)([_doc(10, title="BTC tops $100K")])
    assert result is not None
    assert result.analysis_text == "Bitcoin rally"
    assert result.event_type == "price_move"
    assert result.direction == "긍정"
    assert result.confidence == "MED"
    assert result.impact_score == 88
    assert [c.raw_document_id for c in result.citations] == [10]
    assert len(calls) == 1  # 단일 콜
    call = calls[0]
    assert call["model"] == "gpt-5.4-mini"
    fmt = call["text"]["format"]
    assert fmt["type"] == "json_schema"
    assert fmt["name"] == "impact_analysis"
    assert fmt["strict"] is True
    assert stats.calls == 1
    assert stats.quotes_returned == 1
    assert stats.quotes_dropped == 0
    assert stats.input_tokens == 100
    assert stats.output_tokens == 50


def test_analyzer_all_quotes_dropped_returns_empty_result() -> None:
    stats = AnalyzerStats()
    payload = _payload(citations=[{"doc_index": 0, "quote": "환각 인용"}])
    client, _ = _fake_client([_response(payload)])
    result = openai_analyzer(client, "m", stats)([_doc(10)])
    assert result is not None  # degraded가 아니라 empty 유지
    assert result.citations == []
    assert result.analysis_text == ""
    assert result.event_type is None
    assert stats.quotes_returned == 1
    assert stats.quotes_dropped == 1


def test_analyzer_returns_none_when_no_groundable_docs() -> None:
    client, calls = _fake_client([])
    assert openai_analyzer(client, "m")([_doc(10, title=None, summary=None)]) is None
    assert calls == []  # API 미호출


def test_analyzer_returns_none_on_api_error(caplog: pytest.LogCaptureFixture) -> None:
    def create(**kwargs: Any) -> Any:
        raise openai.APIConnectionError(request=httpx.Request("POST", "https://api"))

    client = cast(openai.OpenAI, SimpleNamespace(responses=SimpleNamespace(create=create)))
    with caplog.at_level(logging.WARNING):
        assert openai_analyzer(client, "m")([_doc(10)]) is None
    assert "openai impact analyzer failed" in caplog.text


def test_analyzer_returns_none_on_truncated_json(caplog: pytest.LogCaptureFixture) -> None:
    resp = SimpleNamespace(status="incomplete", output_text='{"analysis_text": "cut', usage=None)
    client, _ = _fake_client([resp])
    with caplog.at_level(logging.WARNING):
        assert openai_analyzer(client, "m")([_doc(10)]) is None
    assert "incomplete" in caplog.text
    assert "JSONDecodeError" in caplog.text
