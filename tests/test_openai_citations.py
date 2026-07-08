"""OpenAI quote-and-verify 단일 콜 분석 단위 테스트 (네트워크 없이).

순수 함수(verify_quotes 등)와 openai_analyzer 오케스트레이션을 가짜 transport로 덮는다.
실 OpenAI 호출은 하지 않는다(키·네트워크 불필요). transport가 돌려주는 응답은 litellm
ResponsesAPIResponse를 흉내낸 SimpleNamespace다(analyzer가 output_text/status 속성 접근).
토큰·calls 집계는 transport 책임(D3, test_gateway에서 검증)이라 여기선 quote 메트릭만 본다.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from app.llm.gateway import LLMError, OpenAIResponses
from app.pipeline.citations import SourceDoc, _document_text
from app.pipeline.openai_citations import (
    _SYSTEM,
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
    return SimpleNamespace(status=status, output_text=json.dumps(payload, ensure_ascii=False))


def _fake_transport(responses: list[Any]) -> tuple[OpenAIResponses, list[dict[str, Any]]]:
    calls: list[dict[str, Any]] = []

    def transport(**kwargs: Any) -> Any:
        calls.append(kwargs)
        return responses.pop(0)

    return transport, calls


def test_docs_prompt_numbers_and_exact_document_text() -> None:
    docs = [_doc(10, title="첫 제목", summary="첫 요약"), _doc(20, title="둘째", summary=None)]
    prompt = _docs_prompt(docs)
    assert f"[문서 0]\n{_document_text(docs[0])}" in prompt
    assert f"[문서 1]\n{_document_text(docs[1])}" in prompt
    assert prompt.index("[문서 0]") < prompt.index("[문서 1]")


def test_verify_quotes_exact_match_fills_offsets() -> None:
    doc = _doc(10, title="BTC tops $100K", summary="details")
    spans, dropped, verified = verify_quotes(
        {"citations": [{"doc_index": 0, "quote": "tops $100K"}]}, [doc]
    )
    assert dropped == 0
    assert verified == [0]
    assert len(spans) == 1
    span = spans[0]
    assert span.raw_document_id == 10
    assert span.cited_text == "tops $100K"
    text = _document_text(doc)
    assert text[span.char_start : span.char_end] == "tops $100K"
    assert span.source_published_at == _PUB


def test_verify_quotes_returns_deduped_doc_indices() -> None:
    """3번째 반환값: 검증 통과 인용의 doc_index를 등장 순서로 dedupe(digest source 역산용)."""
    docs = [_doc(10, title="BTC tops $100K", summary="rally"), _doc(20, title="ETH gains up")]
    data = {
        "citations": [
            {"doc_index": 0, "quote": "tops $100K"},
            {"doc_index": 0, "quote": "rally"},  # 같은 doc 재인용 — dedupe
            {"doc_index": 1, "quote": "ETH gains up"},
        ]
    }
    spans, dropped, verified = verify_quotes(data, docs)
    assert dropped == 0
    assert len(spans) == 3
    assert verified == [0, 1]


def test_verify_quotes_whitespace_fallback_keeps_none_offsets() -> None:
    doc = _doc(10, title=None, summary="가격이 급등\n했다")
    spans, dropped, verified = verify_quotes(
        {"citations": [{"doc_index": 0, "quote": "가격이 급등 했다"}]}, [doc]
    )
    assert dropped == 0
    assert verified == [0]
    assert len(spans) == 1
    assert spans[0].char_start is None
    assert spans[0].char_end is None


def test_verify_quotes_drops_hallucinated_quote(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        spans, dropped, verified = verify_quotes(
            {"citations": [{"doc_index": 0, "quote": "원문에 없는 문장"}]}, [_doc(10)]
        )
    assert spans == []
    assert dropped == 1
    assert verified == []
    assert "quote dropped" in caplog.text


def test_verify_quotes_drops_out_of_range_index() -> None:
    spans, dropped, verified = verify_quotes(
        {"citations": [{"doc_index": 5, "quote": "t"}]}, [_doc(10)]
    )
    assert spans == []
    assert dropped == 1
    assert verified == []


def test_analyzer_single_call_happy_path() -> None:
    stats = AnalyzerStats()
    transport, calls = _fake_transport([_response(_payload())])
    result = openai_analyzer(transport, "gpt-5.4-mini", stats)([_doc(10, title="BTC tops $100K")])
    assert result is not None
    assert result.analysis_text == "Bitcoin rally"
    assert result.event_type == "price_move"
    assert result.direction == "긍정"
    assert result.confidence == "MED"
    assert result.impact_score == 88
    assert [c.raw_document_id for c in result.citations] == [10]
    assert len(calls) == 1  # 단일 콜
    call = calls[0]
    assert call["model"] == "gpt-5.4-mini"  # provider 프리픽스는 transport가 붙임
    fmt = call["text"]["format"]
    assert fmt["type"] == "json_schema"
    assert fmt["name"] == "impact_analysis"
    assert fmt["strict"] is True
    # 토큰·calls는 transport 책임(D3) — 분석기는 quote 메트릭만 갱신.
    assert stats.quotes_returned == 1
    assert stats.quotes_dropped == 0


def test_analyzer_without_effort_omits_reasoning_and_keeps_budget() -> None:
    transport, calls = _fake_transport([_response(_payload())])
    assert openai_analyzer(transport, "m")([_doc(10, title="BTC tops $100K")]) is not None
    call = calls[0]
    assert "reasoning" not in call
    assert call["max_output_tokens"] == 8192


def test_analyzer_with_effort_sends_reasoning_and_raises_budget() -> None:
    transport, calls = _fake_transport([_response(_payload())])
    analyzer = openai_analyzer(transport, "m", reasoning_effort="medium")
    assert analyzer([_doc(10, title="BTC tops $100K")]) is not None
    call = calls[0]
    assert call["reasoning"] == {"effort": "medium"}
    assert call["max_output_tokens"] == 16384


def test_analyzer_system_override_reaches_api_call() -> None:
    """프롬프트 버전 오버라이드(플랜 10)가 instructions에 도달하는지."""
    transport, calls = _fake_transport([_response(_payload())])
    analyzer = openai_analyzer(transport, "m", system="SYS OVERRIDE")
    assert analyzer([_doc(10, title="BTC tops $100K")]) is not None
    assert calls[0]["instructions"] == "SYS OVERRIDE"


def test_analyzer_default_system_is_production_constant() -> None:
    """오버라이드 미지정 시 현행 상수 그대로 — 운영 경로 불변 증명."""
    transport, calls = _fake_transport([_response(_payload())])
    assert openai_analyzer(transport, "m")([_doc(10, title="BTC tops $100K")]) is not None
    assert calls[0]["instructions"] is _SYSTEM


def test_analyzer_all_quotes_dropped_returns_empty_result() -> None:
    stats = AnalyzerStats()
    payload = _payload(citations=[{"doc_index": 0, "quote": "환각 인용"}])
    transport, _ = _fake_transport([_response(payload)])
    result = openai_analyzer(transport, "m", stats)([_doc(10)])
    assert result is not None  # degraded가 아니라 empty 유지
    assert result.citations == []
    assert result.analysis_text == ""
    assert result.event_type is None
    assert stats.quotes_returned == 1
    assert stats.quotes_dropped == 1


def test_analyzer_returns_none_when_no_groundable_docs() -> None:
    transport, calls = _fake_transport([])
    assert openai_analyzer(transport, "m")([_doc(10, title=None, summary=None)]) is None
    assert calls == []  # API 미호출


def test_analyzer_returns_none_on_api_error(caplog: pytest.LogCaptureFixture) -> None:
    def transport(**kwargs: Any) -> Any:
        raise LLMError("APIConnectionError: down")

    with caplog.at_level(logging.WARNING):
        assert openai_analyzer(transport, "m")([_doc(10)]) is None
    assert "openai impact analyzer failed" in caplog.text


def test_analyzer_returns_none_on_truncated_json(caplog: pytest.LogCaptureFixture) -> None:
    resp = SimpleNamespace(status="incomplete", output_text='{"analysis_text": "cut')
    transport, _ = _fake_transport([resp])
    with caplog.at_level(logging.WARNING):
        assert openai_analyzer(transport, "m")([_doc(10)]) is None
    assert "incomplete" in caplog.text
    assert "JSONDecodeError" in caplog.text
