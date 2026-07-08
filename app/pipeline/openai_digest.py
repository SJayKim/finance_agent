"""OpenAI 단일 콜 quote-and-verify 다이제스트 전략 (플랜 11).

운영 Anthropic 다이제스트(digest.anthropic_digester)의 2-패스를 OpenAI에서는 단일 콜
quote-and-verify로 재구현한다(openai_citations와 같은 전략): 모델이 섹션 + 근거 인용문을
JSON으로 출력 → 코드가 원문 substring 검증. 검증 실패 인용은 drop(환각 인용).

Digester 계약(digest.Digester)을 그대로 지킨다: 인용 가능 입력 0 → [](빈 다이제스트),
검증 인용 0 → [], API 장애·JSON 잘림 → None(호출자 → degraded).

verify_quotes(openai_citations) 재사용: DigestInput의 cited_text 모음을 summary로,
title=None으로 갖는 **합성 SourceDoc**을 만들어 `_document_text(doc) == _input_text(inp)`
정렬을 성립시킨다 — 그러면 openai_citations의 substring 검증이 그대로 작동한다.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from typing import Any

from app.llm.gateway import LLMError, OpenAIResponses
from app.pipeline.citations import SourceDoc, _document_text
from app.pipeline.digest import (
    _PASS1_SYSTEM,
    _PASS1_TASK,
    Digester,
    DigestInput,
    DigestSection,
    _input_text,
)
from app.pipeline.openai_citations import verify_quotes

logger = logging.getLogger(__name__)

_SYSTEM = (
    _PASS1_SYSTEM
    + " 모든 주장의 근거로 citations 배열에 인용문을 담아라. 각 인용문(quote)은 해당 문서"
    " 텍스트에서 그대로 복사한 연속된 문자열이어야 한다 — 의역·요약·여러 구절 조합 금지."
    " 원문에 없는 인용문은 검증에서 탈락한다. sections는 거시는 'macro', 섹터는"
    " 'sector:<섹터명>' 형식의 section 키로 나눈다. 새 사실·수치·종목·전망을 도입하지 마라."
)

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "section": {"type": "string"},  # 'macro' | 'sector:<name>'
                    "heading": {"type": "string"},
                    "body_text": {"type": "string"},
                },
                "required": ["section", "heading", "body_text"],
                "additionalProperties": False,
            },
        },
        "citations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "doc_index": {"type": "integer"},  # _docs_prompt의 [문서 i] 번호
                    "quote": {"type": "string"},
                },
                "required": ["doc_index", "quote"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["sections", "citations"],
    "additionalProperties": False,
}


def _synthetic_doc(inp: DigestInput) -> SourceDoc:
    """DigestInput → 합성 SourceDoc. title=None·summary=인용 모음이라 _document_text가
    _input_text(inp)과 정확히 같아진다(verify_quotes substring 정렬). raw_document_id·
    발행시각은 첫 citation에서(digest.parse_pass1의 ref 규칙 미러)."""
    ref = inp.citations[0]  # sent 입력은 _input_text 비어있지 않음 → citations ≥ 1
    return SourceDoc(
        raw_document_id=ref.raw_document_id,
        title=None,
        summary=_input_text(inp),
        published_at=ref.source_published_at,
    )


def _docs_prompt(docs: Sequence[SourceDoc]) -> str:
    blocks = [f"[문서 {i}]\n{_document_text(doc)}" for i, doc in enumerate(docs)]
    return "\n\n".join(blocks) + f"\n\n{_PASS1_TASK}"


def openai_digester(transport: OpenAIResponses, model: str) -> Digester:
    """실 OpenAI 단일 콜 다이제스트 생성기. 계약은 anthropic_digester와 동일."""

    def digest(inputs: Sequence[DigestInput]) -> list[DigestSection] | None:
        sent = [inp for inp in inputs if _input_text(inp)]
        if not sent:
            return []  # 인용할 본문이 없음 → 빈 다이제스트
        docs = [_synthetic_doc(inp) for inp in sent]
        try:
            resp = transport(
                model=model,
                max_output_tokens=8192,  # 브리프 많은 날 JSON 잘림 방지(digest 교훈) — 하루 1콜
                instructions=_SYSTEM,
                input=_docs_prompt(docs),
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "daily_digest",
                        "strict": True,
                        "schema": _SCHEMA,
                    }
                },
            )
            if getattr(resp, "status", None) == "incomplete":
                logger.warning("openai digest response incomplete — JSON may be cut")
            data = json.loads(resp.output_text or "{}")
        except (LLMError, json.JSONDecodeError) as exc:
            logger.warning("openai digester failed: %s: %s", type(exc).__name__, exc)
            return None
        citations, _, verified_doc_indices = verify_quotes(data, docs)
        if not citations:
            # 검증 통과 근거 없음 — 환각으로 채우지 않는다(§10). 빈 다이제스트.
            return []
        # verified_doc_indices는 sent 위치 → brief_item_id 역산(등장 순서 dedupe 유지).
        source_ids = [sent[idx].brief_item_id for idx in verified_doc_indices]
        # 섹션에는 전체 인용 + 전체 근거를 붙인다(anthropic 폴백 의미론 미러). 같은 section
        # 키는 하나로 병합(body 이어붙임, 첫 heading 유지) — uq_daily_digests_date_section 방지.
        sections: dict[str, DigestSection] = {}
        for raw in data.get("sections") or []:
            section = raw.get("section")
            body_text = raw.get("body_text")
            if not section or not body_text:
                continue
            if section in sections:
                prev = sections[section]
                body_text = f"{prev.body_text}\n\n{body_text}"
                heading = prev.heading
            else:
                heading = raw.get("heading")
            sections[section] = DigestSection(
                section=section,
                heading=heading,
                body_text=body_text,
                citations=list(citations),
                source_brief_item_ids=list(source_ids),
            )
        return list(sections.values())

    return digest
