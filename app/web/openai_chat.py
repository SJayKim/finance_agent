"""OpenAI 단일 콜 quote-and-verify 근거기반 채팅 (플랜 11).

운영 Anthropic 채팅(chat.anthropic_chat/anthropic_rag_chat)의 Citations 강제를 OpenAI에서는
quote-and-verify로 재구현한다: 모델이 답변 + 근거 인용문을 JSON으로 출력 → 코드가 근거
문서(cited_text) substring 검증. 검증 통과 인용 0 → 거부(None) — chat.py와 같은 신뢰 경계
(인용 유무가 유일 기준, LLM 텍스트로 판정 안 함).

sources·거부 규칙은 chat.py 재사용: _chat_sources / _sources_from_citation_views로 근거를
평탄화하고, 결과 계약(sources 0 → None, 검증 인용 0 → None, 장애 → None)을 그대로 지킨다.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from typing import Any

from sqlalchemy.orm import Session

from app.embed import Embedder
from app.llm.gateway import LLMError, OpenAIResponses
from app.web.chat import (
    ChatAnalyzer,
    ChatAnswer,
    ChatCitation,
    RagChatAnalyzer,
    _ChatSource,
    _chat_sources,
    _sources_from_citation_views,
)
from app.web.queries import BriefView, search_citation_spans

logger = logging.getLogger(__name__)

_CHAT_SYSTEM = (
    "너는 증거 브리프 보조다. 제공된 근거 문서만 사용해 질문에 간결히 답한다. 모든 주장은 "
    "문서 인용으로 뒷받침하라. 근거로 뒷받침할 수 없으면 추측하지 말고 모른다고 답하라. "
    "이것은 투자 권유가 아니라 뉴스 기준 영향도 해석이다. 각 인용문(quote)은 해당 문서 "
    "텍스트에서 그대로 복사한 연속된 문자열이어야 한다 — 의역·요약 금지. 원문에 없는 "
    "인용문은 검증에서 탈락한다."
)

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "answer_text": {"type": "string"},
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
    "required": ["answer_text", "citations"],
    "additionalProperties": False,
}


def _normalize_ws(s: str) -> str:
    return " ".join(s.split())


def _docs_prompt(sources: Sequence[_ChatSource], question: str) -> str:
    blocks = [f"[문서 {i}]\n{s.cited_text}" for i, s in enumerate(sources)]
    return "\n\n".join(blocks) + f"\n\n{question}"


def _verify_chat_citations(
    data: dict[str, Any], sources: Sequence[_ChatSource]
) -> list[ChatCitation]:
    """모델 인용 → 근거 cited_text substring 검증 (순수). verify_quotes(임팩트)의 채팅판.

    doc_index 범위 → quote가 근거 cited_text의 연속 부분문자열(정확 일치 → 공백 정규화 재시도)
    → (url, quote) dedupe. 검증 실패 인용은 조용히 drop(환각). url/title은 근거에서 붙인다.
    """
    citations: list[ChatCitation] = []
    seen: set[tuple[str | None, str]] = set()
    for cite in data.get("citations") or []:
        idx = cite.get("doc_index")
        quote = cite.get("quote") or ""
        if not isinstance(idx, int) or idx < 0 or idx >= len(sources) or not quote:
            continue
        src = sources[idx]
        if quote not in src.cited_text and _normalize_ws(quote) not in _normalize_ws(src.cited_text):
            continue  # 환각 인용 — drop
        key = (src.url, quote)
        if key in seen:
            continue
        seen.add(key)
        citations.append(ChatCitation(cited_text=quote, url=src.url, title=src.title))
    return citations


def _answer(
    transport: OpenAIResponses, model: str, sources: Sequence[_ChatSource], question: str
) -> ChatAnswer | None:
    """단일 콜 + 검증. 장애·JSON 잘림·검증 인용 0 → None(거부, chat.py 계약 미러)."""
    try:
        resp = transport(
            model=model,
            max_output_tokens=1024,
            instructions=_CHAT_SYSTEM,
            input=_docs_prompt(sources, question),
            text={
                "format": {
                    "type": "json_schema",
                    "name": "chat_answer",
                    "strict": True,
                    "schema": _SCHEMA,
                }
            },
        )
        if getattr(resp, "status", None) == "incomplete":
            logger.warning("openai chat response incomplete — JSON may be cut")
        data = json.loads(resp.output_text or "{}")
    except (LLMError, json.JSONDecodeError):
        return None
    citations = _verify_chat_citations(data, sources)
    if not citations:
        return None  # 근거 인용 0 → 거부(§7 정책 일관)
    return ChatAnswer(text=data.get("answer_text") or "", citations=citations)


def openai_chat(transport: OpenAIResponses, model: str) -> ChatAnalyzer:
    """실 OpenAI 근거기반 채팅 분석기. 계약은 anthropic_chat과 동일."""

    def answer(question: str, brief_views: Sequence[BriefView]) -> ChatAnswer | None:
        sources = _chat_sources(brief_views)
        if not sources:
            return None  # 그날 근거 자체가 없음
        return _answer(transport, model, sources, question)

    return answer


def openai_rag_chat(
    transport: OpenAIResponses, model: str, embedder: Embedder
) -> RagChatAnalyzer:
    """실 OpenAI 누적 RAG 근거기반 채팅 분석기. 계약은 anthropic_rag_chat과 동일(top_k=8)."""

    def answer(session: Session, question: str) -> ChatAnswer | None:
        vec = embedder.embed([question])[0]
        views = search_citation_spans(session, vec, top_k=8)
        if not views:
            return None  # 코퍼스에 임베딩된 인용이 없거나 관련 근거 없음
        sources = _sources_from_citation_views(views)
        return _answer(transport, model, sources, question)

    return answer
