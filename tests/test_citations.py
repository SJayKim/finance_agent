"""§7 Citations 2-패스 단위 테스트 (네트워크 없이).

순수 함수(parse_pass1 등)와 anthropic_analyzer 오케스트레이션을 가짜 transport로 덮는다.
실 Anthropic 호출은 하지 않는다(키·네트워크 불필요). transport가 돌려주는 응답은 raw
/v1/messages JSON dict를 흉내낸 dict 리터럴이다(파서가 dict 접근이라 그대로 충분).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import pytest

from app.llm.gateway import AnthropicMessages, LLMError
from app.pipeline.citations import (
    _PASS1_SYSTEM,
    _PASS1_TASK,
    _PASS2_SCHEMA,
    _PASS2_SYSTEM,
    SourceDoc,
    _build_documents,
    _document_text,
    _pass2_input,
    anthropic_analyzer,
    parse_pass1,
)

_PUB = datetime(2026, 6, 20, 12, tzinfo=timezone.utc)


def _doc(doc_id: int, title: str | None = "t", summary: str | None = "s") -> SourceDoc:
    return SourceDoc(raw_document_id=doc_id, title=title, summary=summary, published_at=_PUB)


def _cite(document_index: int, cited_text: str, start: int = 0, end: int = 5) -> dict[str, Any]:
    return {
        "type": "char_location",
        "document_index": document_index,
        "cited_text": cited_text,
        "start_char_index": start,
        "end_char_index": end,
    }


def _text_block(text: str, citations: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"type": "text", "text": text, "citations": citations}


def _pass2_body(impact_score: int = 88) -> dict[str, Any]:
    return {
        "content": [
            _text_block(
                '{"event_type": "price_move", "direction": "긍정", '
                f'"confidence": "MED", "impact_score": {impact_score}}}'
            )
        ]
    }


def test_document_text_skips_missing_parts() -> None:
    assert _document_text(_doc(1, title="Title", summary="Body")) == "Title\n\nBody"
    assert _document_text(_doc(1, title=None, summary="only summary")) == "only summary"
    assert _document_text(_doc(1, title=None, summary=None)) == ""


def test_build_documents_enables_citations_and_orders() -> None:
    blocks = _build_documents([_doc(10), _doc(20)])
    assert [b["source"]["data"] for b in blocks] == ["t\n\ns", "t\n\ns"]
    assert all(b["citations"] == {"enabled": True} for b in blocks)
    assert all(b["source"]["type"] == "text" for b in blocks)


def test_parse_pass1_maps_citations_to_source_docs() -> None:
    sent = [_doc(10), _doc(20)]
    content = [
        _text_block("Impact: ", [_cite(0, "doc-ten span")]),
        _text_block("more.", [_cite(1, "doc-twenty span")]),
        _text_block(" tail"),  # 인용 없는 블록
    ]
    analysis, citations = parse_pass1(content, sent)
    assert analysis == "Impact: more. tail"
    assert [(c.raw_document_id, c.cited_text) for c in citations] == [
        (10, "doc-ten span"),
        (20, "doc-twenty span"),
    ]
    assert all(c.source_published_at == _PUB for c in citations)


def test_parse_pass1_skips_non_text_blocks() -> None:
    """thinking 등 text 아닌 블록은 건너뛴다(dict 접근에서도 의미 동일)."""
    content = [
        {"type": "thinking", "thinking": "internal"},
        _text_block("visible", [_cite(0, "span")]),
    ]
    analysis, citations = parse_pass1(content, [_doc(10)])
    assert analysis == "visible"
    assert len(citations) == 1


def test_parse_pass1_drops_out_of_range_index() -> None:
    _, citations = parse_pass1([_text_block("x", [_cite(5, "ghost")])], [_doc(10)])
    assert citations == []


def test_pass2_input_contains_only_cited_spans_not_documents() -> None:
    """무결성 규칙: 패스 2 입력에는 cited_text만, 원문 본문은 없어야 한다."""
    sent = [_doc(10, title="SECRET HEADLINE", summary="SECRET BODY")]
    _, citations = parse_pass1([_text_block("a", [_cite(0, "only this span")])], sent)
    payload = _pass2_input("analysis here", citations)
    assert "only this span" in payload
    assert "SECRET BODY" not in payload
    assert "SECRET HEADLINE" not in payload


def _fake_transport(
    responses: list[dict[str, Any]],
) -> tuple[AnthropicMessages, list[dict[str, Any]]]:
    calls: list[dict[str, Any]] = []

    def transport(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return responses.pop(0)

    return transport, calls


def test_analyzer_two_pass_happy_path() -> None:
    pass1 = {"content": [_text_block("Bitcoin rally", [_cite(0, "tops $100K")])]}
    transport, calls = _fake_transport([pass1, _pass2_body()])
    result = anthropic_analyzer(transport, "claude-opus-4-8")([_doc(10, title="BTC tops $100K")])
    assert result is not None
    assert result.event_type == "price_move"
    assert result.direction == "긍정"
    assert result.confidence == "MED"
    assert result.impact_score == 88
    assert [c.raw_document_id for c in result.citations] == [10]
    assert result.analysis_text == "Bitcoin rally"
    assert len(calls) == 2  # 패스1 + 패스2


def test_request_payload_identity_both_passes() -> None:
    """동작 동일성의 핵심 증거: transport에 넘기는 요청 kwargs가 현행 SDK 호출과 바이트 동일."""
    doc = _doc(10, title="BTC tops $100K", summary=None)
    pass1 = {"content": [_text_block("Bitcoin rally", [_cite(0, "tops $100K")])]}
    transport, calls = _fake_transport([pass1, _pass2_body(50)])
    anthropic_analyzer(transport, "claude-opus-4-8")([doc])

    assert calls[0] == {
        "model": "claude-opus-4-8",
        "max_tokens": 4096,
        "thinking": {"type": "adaptive"},
        "system": _PASS1_SYSTEM,
        "messages": [
            {
                "role": "user",
                "content": [*_build_documents([doc]), {"type": "text", "text": _PASS1_TASK}],
            }
        ],
    }
    _, citations = parse_pass1(pass1["content"], [doc])
    assert calls[1] == {
        "model": "claude-opus-4-8",
        "max_tokens": 1024,
        "system": _PASS2_SYSTEM,
        "output_config": {"format": {"type": "json_schema", "schema": _PASS2_SCHEMA}},
        "messages": [{"role": "user", "content": _pass2_input("Bitcoin rally", citations)}],
    }


def test_analyzer_prompt_overrides_reach_both_passes() -> None:
    """프롬프트 버전 오버라이드(플랜 10)가 실제 API 콜 system에 도달하는지."""
    pass1 = {"content": [_text_block("Bitcoin rally", [_cite(0, "tops $100K")])]}
    transport, calls = _fake_transport([pass1, _pass2_body()])
    analyzer = anthropic_analyzer(
        transport, "m", pass1_system="P1 OVERRIDE", pass2_system="P2 OVERRIDE"
    )
    assert analyzer([_doc(10, title="BTC tops $100K")]) is not None
    assert calls[0]["system"] == "P1 OVERRIDE"
    assert calls[1]["system"] == "P2 OVERRIDE"


def test_analyzer_default_prompts_are_production_constants() -> None:
    """오버라이드 미지정 시 현행 상수 그대로 — 운영 경로 불변 증명."""
    pass1 = {"content": [_text_block("Bitcoin rally", [_cite(0, "tops $100K")])]}
    transport, calls = _fake_transport([pass1, _pass2_body()])
    assert anthropic_analyzer(transport, "m")([_doc(10, title="BTC tops $100K")]) is not None
    assert calls[0]["system"] is _PASS1_SYSTEM
    assert calls[1]["system"] is _PASS2_SYSTEM


def test_analyzer_no_citations_skips_pass2() -> None:
    pass1 = {"content": [_text_block("ungrounded guess", citations=None)]}
    transport, calls = _fake_transport([pass1])
    result = anthropic_analyzer(transport, "claude-opus-4-8")([_doc(10)])
    assert result is not None
    assert result.citations == []
    assert len(calls) == 1  # 패스2 호출 안 함(근거 없음)


def test_analyzer_returns_none_when_no_groundable_docs() -> None:
    transport, calls = _fake_transport([])
    assert anthropic_analyzer(transport, "m")([_doc(10, title=None, summary=None)]) is None
    assert calls == []  # API 미호출


def test_analyzer_returns_none_on_api_error(caplog: pytest.LogCaptureFixture) -> None:
    def transport(**kwargs: Any) -> dict[str, Any]:
        raise LLMError("APIConnectionError: down")

    with caplog.at_level(logging.WARNING):
        assert anthropic_analyzer(transport, "m")([_doc(10)]) is None
    assert "impact analyzer failed" in caplog.text  # 예외 무기록(진단 불가) 회귀 방지


def test_analyzer_returns_none_on_pass2_json_truncation(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """패스2 JSON 잘림(JSONDecodeError) → 분석 루프 크래시 대신 None(degraded) + warning."""
    pass1 = {"content": [_text_block("Bitcoin rally", [_cite(0, "tops $100K")])]}
    pass2 = {"content": [_text_block('{"event_type": "price_mo')]}  # 잘린 JSON
    transport, _ = _fake_transport([pass1, pass2])
    with caplog.at_level(logging.WARNING):
        assert anthropic_analyzer(transport, "m")([_doc(10)]) is None
    assert "JSONDecodeError" in caplog.text


def test_pass2_schema_has_no_unsupported_integer_bounds() -> None:
    # Anthropic structured-output은 integer 타입에 minimum/maximum을 미지원(400 BadRequest).
    # 넣으면 pass2가 매번 APIError로 죽어 impact_score가 항상 None이 된다(라이브 회귀).
    score = _PASS2_SCHEMA["properties"]["impact_score"]
    assert score["type"] == "integer"
    assert "minimum" not in score
    assert "maximum" not in score
