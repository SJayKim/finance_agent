"""LLM 게이트웨이(transport) 단위 테스트 (네트워크 없이).

litellm 진입점을 monkeypatch로 덮어 프리픽스·키 부착, kwargs 원형 통과, raw 응답 반환,
LLMError 정규화, stats in-place 집계를 검증한다. 실 API 호출은 하지 않는다.
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Any

import httpx
import openai
import pytest

import app.llm.gateway as gateway
from app.llm.gateway import AnalyzerStats, LLMError, anthropic_messages, openai_responses


def test_local_cost_map_env_set_before_litellm_import() -> None:
    """import 시 원격 단가맵 fetch 차단 — gateway import가 env를 선설정했는지."""
    assert os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] == "True"


def _fake_acreate(
    monkeypatch: pytest.MonkeyPatch, response: dict[str, Any] | Exception
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def acreate(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(gateway.litellm.anthropic.messages, "acreate", acreate)
    return calls


def _fake_responses(
    monkeypatch: pytest.MonkeyPatch, response: Any | Exception
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def responses(**kwargs: Any) -> Any:
        calls.append(kwargs)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(gateway.litellm, "responses", responses)
    return calls


def test_anthropic_transport_prefixes_model_attaches_key_passes_kwargs_verbatim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = {"content": [{"type": "text", "text": "hi"}], "stop_reason": "end_turn"}
    calls = _fake_acreate(monkeypatch, raw)
    transport = anthropic_messages("key-1")
    messages = [{"role": "user", "content": [{"type": "text", "text": "질문"}]}]
    output_config = {"format": {"type": "json_schema", "schema": {"type": "object"}}}
    out = transport(
        model="claude-opus-4-8",
        max_tokens=4096,
        thinking={"type": "adaptive"},
        system="SYS",
        output_config=output_config,
        messages=messages,
    )
    assert out is raw  # raw Anthropic JSON dict 그대로 반환
    assert len(calls) == 1
    call = calls[0]
    assert call["model"] == "anthropic/claude-opus-4-8"
    assert call["api_key"] == "key-1"
    assert call["max_tokens"] == 4096
    assert call["thinking"] == {"type": "adaptive"}
    assert call["system"] == "SYS"
    assert call["output_config"] is output_config  # 변형 없이 원형 통과
    assert call["messages"] is messages


def test_anthropic_transport_updates_stats_in_place(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = {"content": [], "usage": {"input_tokens": 100, "output_tokens": 50}}
    _fake_acreate(monkeypatch, raw)
    stats = AnalyzerStats()
    transport = anthropic_messages("k", stats)
    transport(model="m", max_tokens=16, messages=[])
    transport(model="m", max_tokens=16, messages=[])
    assert stats.calls == 2
    assert stats.input_tokens == 200
    assert stats.output_tokens == 100
    assert stats.reasoning_tokens == 0


def test_anthropic_transport_without_stats_and_without_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_acreate(monkeypatch, {"content": []})  # usage 없음 + stats=None — 둘 다 가드
    assert anthropic_messages("k")(model="m", max_tokens=16, messages=[]) == {"content": []}


def test_anthropic_transport_normalizes_leaked_base_llm_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """anthropic 네이티브 경로는 BaseLLMException(plain Exception)이 그대로 샌다(실측)."""
    leak = gateway.BaseLLMException(status_code=401, message="invalid x-api-key")
    _fake_acreate(monkeypatch, leak)
    with pytest.raises(LLMError) as exc_info:
        anthropic_messages("k")(model="m", max_tokens=16, messages=[])
    assert exc_info.value.__cause__ is leak
    assert "invalid x-api-key" in str(exc_info.value)


def test_anthropic_transport_normalizes_openai_mapped_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    err = openai.APIConnectionError(request=httpx.Request("POST", "https://api"))
    _fake_acreate(monkeypatch, err)
    with pytest.raises(LLMError):
        anthropic_messages("k")(model="m", max_tokens=16, messages=[])


def test_anthropic_transport_propagates_programming_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """전송 실패 계열만 LLMError로 — 그 외(코딩 오류)는 삼키지 않고 전파."""
    _fake_acreate(monkeypatch, TypeError("bad kwargs"))
    with pytest.raises(TypeError):
        anthropic_messages("k")(model="m", max_tokens=16, messages=[])


def test_openai_transport_prefixes_model_attaches_key_passes_kwargs_verbatim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resp = SimpleNamespace(output_text="{}", status="completed", usage=None)
    calls = _fake_responses(monkeypatch, resp)
    text_payload = {"format": {"type": "json_schema", "name": "n", "strict": True, "schema": {}}}
    out = openai_responses("key-2")(
        model="gpt-5.4-mini",
        max_output_tokens=8192,
        instructions="SYS",
        input="본문",
        text=text_payload,
        reasoning={"effort": "medium"},
    )
    assert out is resp
    call = calls[0]
    assert call["model"] == "openai/gpt-5.4-mini"
    assert call["api_key"] == "key-2"
    assert call["max_output_tokens"] == 8192
    assert call["instructions"] == "SYS"
    assert call["input"] == "본문"
    assert call["text"] is text_payload
    assert call["reasoning"] == {"effort": "medium"}


def test_openai_transport_updates_stats_with_reasoning_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resp = SimpleNamespace(
        output_text="{}",
        status="completed",
        usage=SimpleNamespace(
            input_tokens=100,
            output_tokens=50,
            output_tokens_details=SimpleNamespace(reasoning_tokens=30),
        ),
    )
    _fake_responses(monkeypatch, resp)
    stats = AnalyzerStats()
    openai_responses("k", stats)(model="m", input="q")
    assert stats.calls == 1
    assert stats.input_tokens == 100
    assert stats.output_tokens == 50
    assert stats.reasoning_tokens == 30


def test_openai_transport_guards_optional_usage_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """output_tokens_details는 Optional(None) — 실측 가드."""
    resp = SimpleNamespace(
        output_text="{}",
        status="completed",
        usage=SimpleNamespace(input_tokens=1, output_tokens=2, output_tokens_details=None),
    )
    _fake_responses(monkeypatch, resp)
    stats = AnalyzerStats()
    openai_responses("k", stats)(model="m", input="q")
    assert stats.reasoning_tokens == 0


def test_openai_transport_normalizes_api_error(monkeypatch: pytest.MonkeyPatch) -> None:
    err = openai.APIConnectionError(request=httpx.Request("POST", "https://api"))
    _fake_responses(monkeypatch, err)
    with pytest.raises(LLMError) as exc_info:
        openai_responses("k")(model="m", input="q")
    assert exc_info.value.__cause__ is err
