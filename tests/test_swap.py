"""Zero-fabrication swap test (STAGE1_DESIGN §12 하드게이트1 / plan 04).

인용(cited_text)이 실제로 원문 문서의 [char_start:char_end] 슬라이스와 글자 단위로
일치하는지 강제한다. Citations API의 핵심 보증("인용은 원문에서 그대로 온다")이
parse_pass1의 인덱스 매핑에서 보존되는지 회귀로 막는다 — 인덱스가 cited_text와 어긋나면
(=오매핑/환각) 추적성이 깨진다. 순수 단위테스트(네트워크·DB 불필요).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.pipeline.citations import SourceDoc, _document_text, parse_pass1

_PUB = datetime(2026, 6, 20, 12, tzinfo=timezone.utc)


def _doc(doc_id: int, title: str | None, summary: str | None) -> SourceDoc:
    return SourceDoc(raw_document_id=doc_id, title=title, summary=summary, published_at=_PUB)


def _cite_for(doc: SourceDoc, span: str) -> dict[str, Any]:
    """doc 본문에서 span의 실제 char 범위를 찾아 Citations API 응답 cite 블록(dict)을 흉내낸다."""
    text = _document_text(doc)
    start = text.index(span)
    return {
        "type": "char_location",
        "document_index": 0,
        "cited_text": span,
        "start_char_index": start,
        "end_char_index": start + len(span),
    }


def _block(citations: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "text", "text": "analysis", "citations": citations}


def test_every_citation_text_equals_source_span() -> None:
    """parse_pass1이 매핑한 모든 인용에서 cited_text == 원문[char_start:char_end]."""
    cases = [
        (_doc(10, "Bitcoin tops $100K", "ETF inflows surge"), "tops $100K"),
        (_doc(20, "삼성전자 4분기 실적 발표", "메모리 가격 반등"), "4분기 실적"),
        (_doc(30, None, "Fed holds rates steady amid data"), "holds rates"),
        (_doc(40, "현대차 미국 판매 호조", "전기차 라인업 확대"), "전기차 라인업"),
    ]
    for doc, span in cases:
        _, citations = parse_pass1([_block([_cite_for(doc, span)])], [doc])
        assert len(citations) == 1
        c = citations[0]
        assert c.char_start is not None and c.char_end is not None
        assert c.cited_text == _document_text(doc)[c.char_start : c.char_end]


def test_swap_detects_index_text_mismatch() -> None:
    """같은 불변식이 어긋난 인덱스를 잡아낸다(게이트에 이빨이 있음 — 의도적 red 1회)."""
    doc = _doc(10, "Bitcoin tops $100K", "ETF inflows surge")
    text = _document_text(doc)
    # cited_text는 "tops $100K"인데 인덱스는 엉뚱한 0:5("Bitco")를 가리킨다 → 불일치.
    bad = {
        "type": "char_location",
        "document_index": 0,
        "cited_text": "tops $100K",
        "start_char_index": 0,
        "end_char_index": 5,
    }
    _, citations = parse_pass1([_block([bad])], [doc])
    c = citations[0]
    assert c.char_start is not None and c.char_end is not None
    assert c.cited_text != text[c.char_start : c.char_end]
