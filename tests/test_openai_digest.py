"""OpenAI 단일 콜 quote-and-verify 다이제스트 단위 테스트 (네트워크 없이).

Digester 계약(digest.anthropic_digester와 동일)과 합성 SourceDoc 정렬(verify_quotes 재사용)을
가짜 transport로 덮는다. 실 OpenAI 호출은 없다. 응답은 litellm ResponsesAPIResponse를 흉내낸
SimpleNamespace(analyzer가 output_text/status 속성 접근).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from app.llm.gateway import LLMError, OpenAIResponses
from app.pipeline.citations import CitedSpan, _document_text
from app.pipeline.digest import DigestInput, _input_text
from app.pipeline.openai_digest import _synthetic_doc, openai_digester

_PUB = datetime(2026, 6, 20, 12, tzinfo=timezone.utc)


def _span(doc_id: int, cited_text: str) -> CitedSpan:
    return CitedSpan(
        raw_document_id=doc_id,
        cited_text=cited_text,
        char_start=0,
        char_end=len(cited_text),
        source_published_at=_PUB,
    )


def _input(brief_item_id: int, cited_texts: list[str]) -> DigestInput:
    return DigestInput(
        brief_item_id=brief_item_id,
        analysis_text="uncited analysis",
        citations=[_span(brief_item_id * 10, t) for t in cited_texts],
    )


def _response(payload: dict[str, Any], status: str = "completed") -> SimpleNamespace:
    return SimpleNamespace(status=status, output_text=json.dumps(payload, ensure_ascii=False))


def _fake_transport(responses: list[Any]) -> tuple[OpenAIResponses, list[dict[str, Any]]]:
    calls: list[dict[str, Any]] = []

    def transport(**kwargs: Any) -> Any:
        calls.append(kwargs)
        return responses.pop(0)

    return transport, calls


def test_synthetic_doc_aligns_document_text_with_input_text() -> None:
    """합성 SourceDoc의 _document_text가 _input_text(inp)과 정확히 같아야 verify_quotes가 작동."""
    inp = _input(11, ["Bitcoin tops $100K", "miners rally"])
    doc = _synthetic_doc(inp)
    assert _document_text(doc) == _input_text(inp)
    assert doc.raw_document_id == 110  # 첫 citation의 raw_document_id
    assert doc.published_at == _PUB


def _payload(sections: list[dict[str, Any]], citations: list[dict[str, Any]]) -> dict[str, Any]:
    return {"sections": sections, "citations": citations}


def test_digester_grounded_sections_map_source_and_citations() -> None:
    payload = _payload(
        sections=[{"section": "macro", "heading": "금리", "body_text": "긍정 요인으로 분류"}],
        citations=[
            {"doc_index": 0, "quote": "evidence one"},
            {"doc_index": 1, "quote": "evidence two"},
        ],
    )
    transport, calls = _fake_transport([_response(payload)])
    sections = openai_digester(transport, "gpt-5.4")(
        [_input(11, ["evidence one"]), _input(22, ["evidence two"])]
    )
    assert sections is not None and len(sections) == 1
    sec = sections[0]
    assert sec.section == "macro"
    assert sec.heading == "금리"
    assert [c.cited_text for c in sec.citations] == ["evidence one", "evidence two"]
    assert [c.raw_document_id for c in sec.citations] == [110, 220]
    assert sec.source_brief_item_ids == [11, 22]  # verified_doc_indices → brief_item_id
    assert len(calls) == 1  # 단일 콜
    assert calls[0]["max_output_tokens"] == 8192
    assert calls[0]["text"]["format"]["strict"] is True


def test_digester_drops_hallucinated_quote() -> None:
    payload = _payload(
        sections=[{"section": "macro", "heading": "h", "body_text": "b"}],
        citations=[
            {"doc_index": 0, "quote": "evidence one"},
            {"doc_index": 0, "quote": "원문에 없는 인용"},  # 환각 → drop
        ],
    )
    transport, _ = _fake_transport([_response(payload)])
    sections = openai_digester(transport, "m")([_input(11, ["evidence one"])])
    assert sections is not None and len(sections) == 1
    assert [c.cited_text for c in sections[0].citations] == ["evidence one"]


def test_digester_merges_duplicate_section_keys() -> None:
    payload = _payload(
        sections=[
            {"section": "macro", "heading": "금리", "body_text": "첫째 테마"},
            {"section": "macro", "heading": "환율", "body_text": "둘째 테마"},
        ],
        citations=[{"doc_index": 0, "quote": "evidence"}],
    )
    transport, _ = _fake_transport([_response(payload)])
    sections = openai_digester(transport, "m")([_input(1, ["evidence"])])
    assert sections is not None and len(sections) == 1
    sec = sections[0]
    assert sec.heading == "금리"  # 첫 heading 유지
    assert "첫째 테마" in sec.body_text and "둘째 테마" in sec.body_text


def test_digester_empty_inputs_returns_empty_list() -> None:
    transport, calls = _fake_transport([])
    # 인용 가능한 본문 없음 → [](빈 다이제스트), API 미호출
    assert openai_digester(transport, "m")([_input(1, [])]) == []
    assert calls == []


def test_digester_zero_verified_citations_returns_empty_list() -> None:
    payload = _payload(
        sections=[{"section": "macro", "heading": "h", "body_text": "b"}],
        citations=[{"doc_index": 0, "quote": "전부 환각"}],
    )
    transport, _ = _fake_transport([_response(payload)])
    assert openai_digester(transport, "m")([_input(1, ["real evidence"])]) == []


def test_digester_returns_none_on_api_error(caplog: pytest.LogCaptureFixture) -> None:
    def transport(**kwargs: Any) -> Any:
        raise LLMError("APIConnectionError: down")

    with caplog.at_level(logging.WARNING):
        assert openai_digester(transport, "m")([_input(1, ["a"])]) is None
    assert "openai digester failed" in caplog.text


def test_digester_returns_none_on_truncated_json(caplog: pytest.LogCaptureFixture) -> None:
    resp = SimpleNamespace(status="incomplete", output_text='{"sections": [{"section": "ma')
    transport, _ = _fake_transport([resp])
    with caplog.at_level(logging.WARNING):
        assert openai_digester(transport, "m")([_input(1, ["a"])]) is None
    assert "incomplete" in caplog.text
