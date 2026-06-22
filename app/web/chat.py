"""근거기반 채팅 (STAGE1_DASHBOARD_SPEC 요구 #2).

§7과 같은 zero-fabrication 경계로 가둔다: 해당 날짜 브리프의 **실제 인용 근거(cited_text)**
만 citable document 블록으로 먹이고 Citations API를 강제한다. 모델이 인용한 근거가
0건이면 거부(None) — LLM 텍스트로 판정하지 않고 인용 유무가 유일 기준이다.

citations.py와 같은 경계: 순수 파싱(_parse_chat)과 I/O(anthropic_chat)를 분리해 네트워크
없이 테스트한다. 클라이언트는 citations.build_client를 재사용한다(truststore OS 인증서).
영향 분석문(analysis_text)은 LLM 생성물이라 인용 대상으로 두지 않는다 — 1차 근거만 citable.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any, cast

import anthropic
from anthropic.types import MessageParam

from app.web.queries import BriefView


@dataclass(frozen=True)
class _ChatSource:
    """채팅에 먹이는 citable 근거 1건: 브리프 인용 span + 그 원문 링크."""

    cited_text: str
    url: str | None
    title: str | None


@dataclass(frozen=True)
class ChatCitation:
    """답변이 인용한 근거 + 원문 링크(없으면 None)."""

    cited_text: str
    url: str | None
    title: str | None


@dataclass(frozen=True)
class ChatAnswer:
    """근거기반 답변. citations는 항상 ≥1 (0이면 라우트가 거부 처리)."""

    text: str
    citations: list[ChatCitation]


# 라우트·테스트가 주입하는 I/O 경계. 키 없으면 None(=비활성).
ChatAnalyzer = Callable[[str, Sequence[BriefView]], ChatAnswer | None]


_CHAT_SYSTEM = (
    "너는 증거 브리프 보조다. 제공된 근거 문서만 사용해 질문에 간결히 답한다. 모든 주장은 "
    "문서 인용으로 뒷받침하라. 근거로 뒷받침할 수 없으면 추측하지 말고 모른다고 답하라. "
    "이것은 투자 권유가 아니라 뉴스 기준 영향도 해석이다."
)


def _chat_sources(brief_views: Sequence[BriefView]) -> list[_ChatSource]:
    """브리프들의 모든 인용 근거를 평탄화 — document_index가 이 순서를 따른다."""
    return [
        _ChatSource(cited_text=c.cited_text, url=c.url, title=c.title)
        for view in brief_views
        for c in view.citations
    ]


def _chat_documents(sources: Sequence[_ChatSource]) -> list[dict[str, Any]]:
    """citable document 블록들(citations 활성). 순서가 document_index가 된다(_chat_sources와 동일)."""
    return [
        {
            "type": "document",
            "source": {"type": "text", "media_type": "text/plain", "data": s.cited_text},
            "title": s.title or "근거",
            "citations": {"enabled": True},
        }
        for s in sources
    ]


def _parse_chat(
    content: Iterable[Any], sources: Sequence[_ChatSource]
) -> tuple[str, list[ChatCitation]]:
    """응답 content 블록들 → (답변 텍스트, 인용들) (순수). parse_pass1과 같은 패턴.

    cited 블록의 document_index로 sources를 역참조해 url/title을 붙인다. SDK 타입에 묶이지
    않게 getattr 방어 접근. 같은 (url, cited_text)는 한 번만(링크 중복 제거).
    """
    texts: list[str] = []
    citations: list[ChatCitation] = []
    seen: set[tuple[str | None, str]] = set()
    for block in content:
        if getattr(block, "type", None) != "text":
            continue
        texts.append(getattr(block, "text", "") or "")
        for cite in getattr(block, "citations", None) or []:
            idx = getattr(cite, "document_index", None)
            if idx is None or idx < 0 or idx >= len(sources):
                continue
            src = sources[idx]
            cited_text = getattr(cite, "cited_text", "") or src.cited_text
            key = (src.url, cited_text)
            if key in seen:
                continue
            seen.add(key)
            citations.append(ChatCitation(cited_text=cited_text, url=src.url, title=src.title))
    return "".join(texts).strip(), citations


def anthropic_chat(client: anthropic.Anthropic, model: str) -> ChatAnalyzer:
    """실 Anthropic 근거기반 채팅 분석기. 인용 0/장애 시 None(라우트 → '관련 근거 없음')."""

    def answer(question: str, brief_views: Sequence[BriefView]) -> ChatAnswer | None:
        sources = _chat_sources(brief_views)
        if not sources:
            return None  # 그날 근거 자체가 없음
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=1024,
                system=_CHAT_SYSTEM,
                messages=cast(
                    "list[MessageParam]",
                    [
                        {
                            "role": "user",
                            "content": [
                                *_chat_documents(sources),
                                {"type": "text", "text": question},
                            ],
                        }
                    ],
                ),
            )
        except anthropic.APIError:
            return None
        text, citations = _parse_chat(resp.content, sources)
        if not citations:
            return None  # 근거 인용 0 → 거부(§7 정책 일관)
        return ChatAnswer(text=text, citations=citations)

    return answer
