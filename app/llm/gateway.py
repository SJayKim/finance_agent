"""LLM 게이트웨이 — 이 저장소에서 유일한 litellm import 지점 (플랜 11).

전송 계층만 담당한다: provider 호출을 콜러블(transport)로 감싸 분석기에 주입하고, API
실패를 단일 LLMError로 정규화하며, 토큰·콜 수를 AnalyzerStats에 in-place 집계한다(D3).
요청 페이로드는 만들지 않는다 — 분석기(citations/digest/chat)가 현행 SDK kwargs를 그대로
넘기고, Anthropic 응답은 raw /v1/messages JSON dict로 돌려받는다(citations 원형 보존).

litellm 1.91.0 실측 근거(핀 변경 시 재검증 — pyproject 주석·플랜 11 참조):
- anthropic 네이티브 브리지는 async 전용: 동기 litellm.anthropic.messages.create()는
  디스패치에서 ValueError("not implemented for sync calls"). 그래서 transport가
  asyncio.run(acreate(...))로 감싼다 — 호출자는 전부 sync(CLI, FastAPI sync-def 라우트는
  threadpool 실행이라 실행 중인 루프 없음)이고, 연속·동시(3스레드) 호출 실측 통과.
- anthropic 경로 예외는 openai 계열로 매핑되지 않고 BaseLLMException(plain Exception)이
  그대로 샌다. openai(litellm.responses) 경로는 openai.OpenAIError 계열로 매핑된다.
- litellm.ssl_verify=SSLContext는 조용히 무시되는 오픈 버그(#14396) → truststore 전역
  주입이 강제된다("스코프 좁게" 관례의 예외). 기존 커넥터(rss 등)는 자체 SSLContext를
  명시하므로 동작 불변.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

import httpx
import truststore

# litellm import 전에 실행돼야 하는 초기화(순서 고정): 원격 단가맵 fetch 차단(import 시
# 네트워크 금지) → OS 인증서 신뢰. 모든 LLM 모듈이 이 모듈에서 transport/LLMError를
# import하므로, 모듈 캐싱으로 litellm 사용 전 1회 실행이 이행적으로 보장된다.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
truststore.inject_into_ssl()

import litellm  # noqa: E402
import openai  # noqa: E402
from litellm.llms.base_llm.chat.transformation import BaseLLMException  # noqa: E402

litellm.telemetry = False
litellm.suppress_debug_info = True
# litellm 로거가 요청 상세를 INFO로 찍지 않게 억제(API 키 노출 방지 — httpx WARNING 관례).
logging.getLogger("LiteLLM").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# 전송 계층 per-call 타임아웃(초). litellm은 timeout을 명시 안 하면 스톨된 콜이 무한
# 블록해 daily 잡이 GitHub 90분 guillotine까지 매달린다(2026-07-08 digest 콜 57분 hang →
# build_digest 미완 → 그날 브리프 통째 손실). 정상 digest 패스 ~25s·impact 콜 ~9s라 120s는
# 넉넉한 여유이면서 hang을 2분에 끊는다. 타임아웃은 openai.APITimeoutError(→ _TRANSPORT_ERRORS)
# 로 정규화돼 각 분석기의 graceful degrade(degraded 다이제스트 등)로 떨어진다.
_REQUEST_TIMEOUT_S = 120


class LLMError(Exception):
    """transport 계층 API 실패의 단일 정규화 예외(연결·타임아웃·쿼터·장애 포함)."""


@dataclass
class AnalyzerStats:
    """비교 스크립트가 주입하는 콜별 집계 — 인용 수율(drop율)·토큰(비용) 산출용.

    토큰·calls는 transport가 성공 응답마다, quotes_*는 분석기가 갱신한다(플랜 11 D3).
    """

    calls: int = 0
    quotes_returned: int = 0  # 모델이 돌려준 인용 수(검증 전)
    quotes_dropped: int = 0  # substring 검증 탈락(환각 인용)
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0  # effort 적용 증거 + 비용 해석 근거(output_tokens에 포함)


# 분석기가 주입받는 transport 경계. 현행 anthropic SDK client.messages.create kwargs를
# 그대로 받고(model 포함 — provider 프리픽스는 transport 내부) raw 응답 JSON dict 반환.
AnthropicMessages = Callable[..., dict[str, Any]]
# OpenAI Responses API kwargs를 그대로 받고 litellm ResponsesAPIResponse 반환
# (output_text/status/usage 접근은 openai SDK 응답과 동일 표면).
OpenAIResponses = Callable[..., Any]

# openai.OpenAIError: litellm 매핑 예외(연결·타임아웃·쿼터 포함 — 실측).
# BaseLLMException: anthropic 네이티브 경로에서 매핑 없이 새는 원시 예외(실측).
# httpx.HTTPError: 매핑 밖 원시 전송 실패. 그 외는 프로그래밍 오류로 보고 전파시킨다.
_TRANSPORT_ERRORS = (openai.OpenAIError, BaseLLMException, httpx.HTTPError)


def anthropic_messages(api_key: str, stats: AnalyzerStats | None = None) -> AnthropicMessages:
    """Anthropic /v1/messages transport 팩토리."""

    def transport(*, model: str, **kwargs: Any) -> dict[str, Any]:
        try:
            resp = asyncio.run(
                litellm.anthropic.messages.acreate(
                    model=f"anthropic/{model}",
                    api_key=api_key,
                    timeout=_REQUEST_TIMEOUT_S,
                    **kwargs,
                )
            )
        except _TRANSPORT_ERRORS as exc:
            raise LLMError(f"{type(exc).__name__}: {exc}") from exc
        out = cast("dict[str, Any]", resp)
        if stats is not None:
            stats.calls += 1
            usage = out.get("usage") or {}
            stats.input_tokens += usage.get("input_tokens") or 0
            stats.output_tokens += usage.get("output_tokens") or 0
        return out

    return transport


def openai_responses(api_key: str, stats: AnalyzerStats | None = None) -> OpenAIResponses:
    """OpenAI Responses API transport 팩토리(litellm.responses 동기 경로)."""

    def transport(*, model: str, **kwargs: Any) -> Any:
        try:
            resp = litellm.responses(
                model=f"openai/{model}", api_key=api_key, timeout=_REQUEST_TIMEOUT_S, **kwargs
            )
        except _TRANSPORT_ERRORS as exc:
            raise LLMError(f"{type(exc).__name__}: {exc}") from exc
        if stats is not None:
            stats.calls += 1
            usage = getattr(resp, "usage", None)
            stats.input_tokens += getattr(usage, "input_tokens", 0) or 0
            stats.output_tokens += getattr(usage, "output_tokens", 0) or 0
            details = getattr(usage, "output_tokens_details", None)
            stats.reasoning_tokens += getattr(details, "reasoning_tokens", 0) or 0
        return resp

    return transport
