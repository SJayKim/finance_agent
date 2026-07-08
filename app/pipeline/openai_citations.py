"""OpenAI 단일 콜 quote-and-verify 영향도 분석 — 비교 실험 전용(scripts/compare_providers.py).

운영 파이프라인은 Anthropic 2-패스(citations.py)를 쓴다. OpenAI에는 Citations API 상응
기능이 없어(인용 원문·오프셋 미제공) 인용을 quote-and-verify로 재구현한다: 모델이 인용문을
JSON으로 출력 → 코드가 원문 substring 검증 + 오프셋 계산. 검증 실패 인용은 drop(환각 인용).

단일 콜(2-패스 아님): Anthropic의 2-패스는 Citations API + Structured Outputs 동시 사용
불가(400) 때문이었다. OpenAI는 인용(quote)과 구조화 필드가 전부 JSON이라 한 콜로 충분.
**무결성 규칙(§7) 비대칭**: Anthropic 경로의 direction/confidence/impact_score는 패스 1이
실제 인용한 범위만 보고 산출되지만, 이 경로는 전체 문서를 본 같은 콜이 산출한다 —
구조화 필드의 근거 제한이 더 약하다. 완화: _SYSTEM이 direction/confidence/impact_score를
citations에 담은 인용문만 근거로 산출하도록 지시한다(프롬프트 수준 — 구조적 보장 아님).
비교 해석 시 유의.

순수 함수(verify_quotes 등)와 I/O(openai_analyzer)를 분리한다 — citations.py와 같은 경계.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from typing import Any

from app.llm.gateway import AnalyzerStats, LLMError, OpenAIResponses
from app.pipeline.citations import (
    _PASS1_SYSTEM,
    CitedSpan,
    ImpactAnalyzer,
    ImpactResult,
    SourceDoc,
    _document_text,
)

# AnalyzerStats는 gateway로 이동(순환 import 회피). 기존 import 경로
# (from app.pipeline.openai_citations import AnalyzerStats)를 유지하기 위해 재수출한다.
__all__ = ["AnalyzerStats", "openai_analyzer", "verify_quotes"]

logger = logging.getLogger(__name__)

_SYSTEM = (
    _PASS1_SYSTEM
    + " 모든 주장의 근거로 citations 배열에 인용문을 담아라. 각 인용문(quote)은 해당 문서"
    " 텍스트에서 그대로 복사한 연속된 문자열이어야 한다 — 의역·요약·여러 구절 조합 금지."
    " 원문에 없는 인용문은 검증에서 탈락한다. impact_score는 이 이벤트가 영향 종목에 주는"
    " 임팩트의 크기(부호 없음)를 0~100으로 매긴다 — 인용된 근거가 시사하는 강도만 반영하고,"
    " 방향(상승/하락)은 direction이 따로 표현하므로 점수에 부호를 넣지 마라. 근거가 약하거나"
    " 중립이면 낮게, 다수 강한 근거가 한 방향을 가리키면 높게."
    " direction·confidence·impact_score는 citations에 담은 인용문만 근거로 산출하라 —"
    " 인용하지 않은 문서 내용은 이 세 필드에 반영하지 마라. 인용문이 뒷받침하지 못하는 값은"
    " 쓰지 마라."
)

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "analysis_text": {"type": "string"},
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
        "event_type": {"type": "string"},
        "direction": {"type": "string", "enum": ["긍정", "부정", "중립"]},
        "confidence": {"type": "string", "enum": ["HIGH", "MED", "LOW"]},
        # 0~100 범위는 프롬프트로 지시(_PASS2_SCHEMA와 동일 관례 — Anthropic과 표면 통일).
        "impact_score": {"type": "integer"},
    },
    "required": [
        "analysis_text",
        "citations",
        "event_type",
        "direction",
        "confidence",
        "impact_score",
    ],
    "additionalProperties": False,
}


def _docs_prompt(docs: Sequence[SourceDoc]) -> str:
    """[문서 i] 번호 블록. 본문은 정확히 _document_text(doc) — substring 검증 정렬을 위해."""
    blocks = [f"[문서 {i}]\n{_document_text(doc)}" for i, doc in enumerate(docs)]
    return "\n\n".join(blocks) + "\n\n이 뉴스 클러스터의 영향도를 분석하라."


def _normalize_ws(s: str) -> str:
    return " ".join(s.split())


def verify_quotes(
    data: Mapping[str, Any], sent_docs: Sequence[SourceDoc]
) -> tuple[list[CitedSpan], int, list[int]]:
    """모델 인용 → 원문 substring 검증 (순수).

    반환: (검증 통과 CitedSpan들, drop 수, 검증 통과 인용의 doc_index를 등장 순서 dedupe한
    리스트). 3번째는 digest의 source_brief_item_ids 역산용(anthropic parse_pass1의
    document_index dedupe 의미론 미러).

    1. doc_index 범위 검증(벗어나면 drop)
    2. doc_text.find(quote) 정확 일치 → char_start/end 채움
    3. 실패 시 공백 정규화 1회 재시도 → 성공 시 오프셋 None으로 유지
    4. 그래도 실패 → drop(환각 인용) + warning
    """
    spans: list[CitedSpan] = []
    dropped = 0
    verified_doc_indices: list[int] = []
    for cite in data.get("citations") or []:
        idx = cite.get("doc_index")
        quote = cite.get("quote") or ""
        if not isinstance(idx, int) or idx < 0 or idx >= len(sent_docs) or not quote:
            dropped += 1
            logger.warning("quote dropped (bad doc_index %r)", idx)
            continue
        doc = sent_docs[idx]
        doc_text = _document_text(doc)
        start = doc_text.find(quote)
        if start >= 0:
            char_start: int | None = start
            char_end: int | None = start + len(quote)
        elif _normalize_ws(quote) in _normalize_ws(doc_text):
            char_start = char_end = None  # 공백만 다른 인용 — 오프셋은 신뢰 불가라 비움
        else:
            dropped += 1
            logger.warning("quote dropped (not found in doc %d): %.80s", doc.raw_document_id, quote)
            continue
        spans.append(
            CitedSpan(
                raw_document_id=doc.raw_document_id,
                cited_text=quote,
                char_start=char_start,
                char_end=char_end,
                source_published_at=doc.published_at,
            )
        )
        if idx not in verified_doc_indices:
            verified_doc_indices.append(idx)
    return spans, dropped, verified_doc_indices


def openai_analyzer(
    transport: OpenAIResponses,
    model: str,
    stats: AnalyzerStats | None = None,
    reasoning_effort: str | None = None,
    system: str | None = None,
) -> ImpactAnalyzer:
    """실 OpenAI 단일 콜 분석기. 계약은 anthropic_analyzer와 동일:
    인용 가능 문서 0 → None(콜 없이), 검증 인용 0 → 빈 ImpactResult(empty 유지),
    API 장애·JSON 잘림 → None(호출자 → status=degraded).

    transport: gateway.openai_responses 콜러블 — 현행 client.responses.create와 같은 kwargs를
    받고 litellm ResponsesAPIResponse를 돌려준다. 토큰·calls 집계는 transport가 한다(D3);
    분석기는 quote 메트릭(quotes_returned/dropped)만 갱신한다.
    reasoning_effort 설정 시 reasoning 토큰이 max_output_tokens를 소모하므로 예산을
    16384로 상향한다 — 안 하면 JSON이 잘려 degraded 폭증(LLM JSON 잘림 견고화 교훈).
    system: 프롬프트 버전 실험용 오버라이드(prompt_versions, 플랜 10) — None이면 현행 상수.
    """
    sys_prompt = _SYSTEM if system is None else system

    def analyze(docs: Sequence[SourceDoc]) -> ImpactResult | None:
        sent = [doc for doc in docs if _document_text(doc)]
        if not sent:
            return None  # 인용할 본문이 없음
        try:
            payload: Any = {
                "format": {
                    "type": "json_schema",
                    "name": "impact_analysis",
                    "strict": True,
                    "schema": _SCHEMA,
                }
            }
            extra: dict[str, Any] = {}
            if reasoning_effort is not None:
                extra["reasoning"] = {"effort": reasoning_effort}
            resp = transport(
                model=model,
                max_output_tokens=16384 if reasoning_effort is not None else 8192,
                instructions=sys_prompt,
                input=_docs_prompt(sent),
                text=payload,
                **extra,
            )
            if getattr(resp, "status", None) == "incomplete":
                logger.warning("openai response incomplete — JSON may be cut")
            data = json.loads(resp.output_text or "{}")
            citations, dropped, _ = verify_quotes(data, sent)
            if stats is not None:
                stats.quotes_returned += len(data.get("citations") or [])
                stats.quotes_dropped += dropped
            if not citations:
                # 검증 통과 근거 없음 — 환각으로 채우지 않는다(§10). analysis는 버린다.
                return ImpactResult("", [], None, None, None)
            return ImpactResult(
                analysis_text=data.get("analysis_text") or "",
                citations=citations,
                event_type=data.get("event_type"),
                direction=data.get("direction"),
                confidence=data.get("confidence"),
                impact_score=data.get("impact_score"),
            )
        except (LLMError, json.JSONDecodeError) as exc:
            # LLMError: 쿼터 소진·장애(gateway 정규화). JSONDecodeError: 출력 잘림 —
            # citations.py와 동일하게 클러스터 하나의 실패가 분석 루프 전체를 죽이지 않게 한다.
            logger.warning("openai impact analyzer failed: %s: %s", type(exc).__name__, exc)
            return None

    return analyze
