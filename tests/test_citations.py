"""§7 Citations 2-패스 단위 테스트 (네트워크 없이).

순수 함수(parse_pass1 등)와 anthropic_analyzer 오케스트레이션을 가짜 클라이언트로 덮는다.
실 Anthropic 호출은 하지 않는다(키·네트워크 불필요). SDK 응답 블록은 SimpleNamespace로
흉내낸다 — parse_pass1이 getattr 방어 접근이라 더미로 충분.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, cast

import anthropic
import httpx

from app.pipeline.citations import (
    _PASS2_SCHEMA,
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


def _cite(document_index: int, cited_text: str, start: int = 0, end: int = 5) -> SimpleNamespace:
    return SimpleNamespace(
        type="char_location",
        document_index=document_index,
        cited_text=cited_text,
        start_char_index=start,
        end_char_index=end,
    )


def _text_block(text: str, citations: list[SimpleNamespace] | None = None) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text, citations=citations)


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


def _fake_client(responses: list[Any]) -> tuple[anthropic.Anthropic, list[dict[str, Any]]]:
    calls: list[dict[str, Any]] = []

    def create(**kwargs: Any) -> Any:
        calls.append(kwargs)
        return responses.pop(0)

    client = SimpleNamespace(messages=SimpleNamespace(create=create))
    return cast(anthropic.Anthropic, client), calls


def test_analyzer_two_pass_happy_path() -> None:
    pass1 = SimpleNamespace(content=[_text_block("Bitcoin rally", [_cite(0, "tops $100K")])])
    pass2 = SimpleNamespace(
        content=[
            _text_block(
                '{"event_type": "price_move", "direction": "긍정", '
                '"confidence": "MED", "impact_score": 88}'
            )
        ]
    )
    client, calls = _fake_client([pass1, pass2])
    result = anthropic_analyzer(client, "claude-opus-4-8")([_doc(10, title="BTC tops $100K")])
    assert result is not None
    assert result.event_type == "price_move"
    assert result.direction == "긍정"
    assert result.confidence == "MED"
    assert result.impact_score == 88
    assert [c.raw_document_id for c in result.citations] == [10]
    assert result.analysis_text == "Bitcoin rally"
    assert len(calls) == 2  # 패스1 + 패스2


def test_analyzer_no_citations_skips_pass2() -> None:
    pass1 = SimpleNamespace(content=[_text_block("ungrounded guess", citations=None)])
    client, calls = _fake_client([pass1])
    result = anthropic_analyzer(client, "claude-opus-4-8")([_doc(10)])
    assert result is not None
    assert result.citations == []
    assert len(calls) == 1  # 패스2 호출 안 함(근거 없음)


def test_analyzer_returns_none_when_no_groundable_docs() -> None:
    client, calls = _fake_client([])
    assert anthropic_analyzer(client, "m")([_doc(10, title=None, summary=None)]) is None
    assert calls == []  # API 미호출


def test_analyzer_returns_none_on_api_error() -> None:
    def create(**kwargs: Any) -> Any:
        raise anthropic.APIConnectionError(request=httpx.Request("POST", "https://api"))

    client = cast(anthropic.Anthropic, SimpleNamespace(messages=SimpleNamespace(create=create)))
    assert anthropic_analyzer(client, "m")([_doc(10)]) is None


def test_pass2_schema_has_no_unsupported_integer_bounds() -> None:
    # Anthropic structured-output은 integer 타입에 minimum/maximum을 미지원(400 BadRequest).
    # 넣으면 pass2가 매번 APIError로 죽어 impact_score가 항상 None이 된다(라이브 회귀).
    score = _PASS2_SCHEMA["properties"]["impact_score"]
    assert score["type"] == "integer"
    assert "minimum" not in score
    assert "maximum" not in score
