"""용도별 LLM 분석기 조립 (플랜 11).

settings의 용도별 provider·model 스위치를 읽어 gateway transport를 분석기에 주입한다.
전역 settings를 **호출 시점에** 읽는다(현행 main.py 패턴 보존 — settings monkeypatch 테스트
유효). provider 키 없으면 None(graceful 비활성 — 현행 키 게이트 의미), 미지 provider는
ValueError(오타를 조용한 비활성으로 오진 방지). 모델 폴백: digest/chat은 자기 필드 없으면
impact_model. 분석기 생성자는 지연 import(litellm 무거운 import·순환 회피).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.config import settings
from app.llm.gateway import anthropic_messages, openai_responses

if TYPE_CHECKING:
    from app.embed import Embedder
    from app.pipeline.citations import ImpactAnalyzer
    from app.pipeline.digest import Digester
    from app.web.chat import ChatAnalyzer, RagChatAnalyzer


def _provider_key(provider: str) -> str | None:
    """provider별 API 키. 미지 provider는 ValueError(오타 → 조용한 비활성 오진 방지)."""
    if provider == "anthropic":
        return settings.anthropic_api_key
    if provider == "openai":
        return settings.openai_api_key
    raise ValueError(f"unknown provider: {provider!r}")


def make_impact_analyzer() -> ImpactAnalyzer | None:
    """임팩트 분석기. 키 없으면 None(analyze_impact 비활성 → brief_item status=empty 유지)."""
    provider = settings.impact_provider
    key = _provider_key(provider)
    if not key:
        return None
    model = settings.impact_model
    if provider == "anthropic":
        from app.pipeline.citations import anthropic_analyzer

        return anthropic_analyzer(anthropic_messages(key), model)
    from app.pipeline.openai_citations import openai_analyzer

    return openai_analyzer(openai_responses(key), model)


def make_digester() -> Digester | None:
    """다이제스트 생성기. 키 없으면 None(build_digest → degraded)."""
    provider = settings.digest_provider
    key = _provider_key(provider)
    if not key:
        return None
    model = settings.digest_model or settings.impact_model
    if provider == "anthropic":
        from app.pipeline.digest import anthropic_digester

        return anthropic_digester(anthropic_messages(key), model)
    from app.pipeline.openai_digest import openai_digester

    return openai_digester(openai_responses(key), model)


def make_chat_analyzer() -> ChatAnalyzer | None:
    """날짜 챗 분석기. 키 없으면 None(채팅 비활성)."""
    provider = settings.chat_provider
    key = _provider_key(provider)
    if not key:
        return None
    model = settings.chat_model or settings.impact_model
    if provider == "anthropic":
        from app.web.chat import anthropic_chat

        return anthropic_chat(anthropic_messages(key), model)
    from app.web.openai_chat import openai_chat

    return openai_chat(openai_responses(key), model)


def make_rag_chat_analyzer(embedder: Embedder) -> RagChatAnalyzer | None:
    """누적 RAG 챗 분석기(§4 트랙 D2). 키 없으면 None(누적 검색 비활성)."""
    provider = settings.chat_provider
    key = _provider_key(provider)
    if not key:
        return None
    model = settings.chat_model or settings.impact_model
    if provider == "anthropic":
        from app.web.chat import anthropic_rag_chat

        return anthropic_rag_chat(anthropic_messages(key), model, embedder)
    from app.web.openai_chat import openai_rag_chat

    return openai_rag_chat(openai_responses(key), model, embedder)


def chat_key_configured() -> bool:
    """챗 provider 키 설정 여부(main.py chat_enabled·게이트용 — 임베더 로드 없이)."""
    return bool(_provider_key(settings.chat_provider))
