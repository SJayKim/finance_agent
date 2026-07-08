"""용도별 분석기 factory 단위 테스트 (네트워크 없이).

provider 분기·모델 폴백·키 게이트(None)·미지 provider ValueError·chat_key_configured를
검증한다. 분석기 생성자는 monkeypatch로 스파이해 transport 배선(provider 프리픽스 부착 키)이
어느 생성자에 어떤 모델로 전달되는지만 본다 — 실 API 호출은 없다.
"""

from __future__ import annotations

from typing import Any

import pytest

import app.llm.factory as factory


def _spy(monkeypatch: pytest.MonkeyPatch, module: str, name: str) -> list[tuple[Any, ...]]:
    """지정 생성자를 인자 기록 스파이로 교체. 반환 리스트에 (args...)가 쌓인다."""
    calls: list[tuple[Any, ...]] = []

    def fake(*args: Any) -> str:
        calls.append(args)
        return f"{name}-analyzer"

    monkeypatch.setattr(f"{module}.{name}", fake)
    return calls


@pytest.fixture(autouse=True)
def _reset_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    """각 테스트가 provider·model·키를 명시 설정하도록 안전한 기본값으로 리셋."""
    monkeypatch.setattr(factory.settings, "impact_provider", "anthropic")
    monkeypatch.setattr(factory.settings, "digest_provider", "anthropic")
    monkeypatch.setattr(factory.settings, "chat_provider", "anthropic")
    monkeypatch.setattr(factory.settings, "impact_model", "claude-opus-4-8")
    monkeypatch.setattr(factory.settings, "digest_model", None)
    monkeypatch.setattr(factory.settings, "chat_model", None)
    monkeypatch.setattr(factory.settings, "anthropic_api_key", "ak")
    monkeypatch.setattr(factory.settings, "openai_api_key", "ok")


def test_impact_anthropic_branch_wires_transport_and_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _spy(monkeypatch, "app.pipeline.citations", "anthropic_analyzer")
    assert factory.make_impact_analyzer() == "anthropic_analyzer-analyzer"
    transport, model = calls[0]
    assert callable(transport)  # anthropic_messages(key) transport
    assert model == "claude-opus-4-8"


def test_impact_openai_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(factory.settings, "impact_provider", "openai")
    calls = _spy(monkeypatch, "app.pipeline.openai_citations", "openai_analyzer")
    assert factory.make_impact_analyzer() == "openai_analyzer-analyzer"
    transport, model = calls[0]
    assert callable(transport)
    assert model == "claude-opus-4-8"  # openai 용도도 impact_model 폴백


def test_impact_none_when_provider_key_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(factory.settings, "anthropic_api_key", None)
    assert factory.make_impact_analyzer() is None


def test_impact_openai_none_when_openai_key_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(factory.settings, "impact_provider", "openai")
    monkeypatch.setattr(factory.settings, "openai_api_key", "")
    assert factory.make_impact_analyzer() is None


def test_digester_anthropic_branch_model_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _spy(monkeypatch, "app.pipeline.digest", "anthropic_digester")
    factory.make_digester()
    _, model = calls[0]
    assert model == "claude-opus-4-8"  # digest_model None → impact_model


def test_digester_uses_digest_model_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(factory.settings, "digest_model", "claude-sonnet-4-6")
    calls = _spy(monkeypatch, "app.pipeline.digest", "anthropic_digester")
    factory.make_digester()
    _, model = calls[0]
    assert model == "claude-sonnet-4-6"


def test_digester_openai_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(factory.settings, "digest_provider", "openai")
    calls = _spy(monkeypatch, "app.pipeline.openai_digest", "openai_digester")
    assert factory.make_digester() == "openai_digester-analyzer"
    transport, model = calls[0]
    assert callable(transport)
    assert model == "claude-opus-4-8"  # digest_model None → impact_model 폴백


def test_digester_none_when_key_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(factory.settings, "anthropic_api_key", None)
    assert factory.make_digester() is None


def test_chat_analyzer_anthropic_branch_model_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _spy(monkeypatch, "app.web.chat", "anthropic_chat")
    factory.make_chat_analyzer()
    _, model = calls[0]
    assert model == "claude-opus-4-8"  # chat_model None → impact_model


def test_chat_analyzer_uses_chat_model_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(factory.settings, "chat_model", "claude-haiku-4-5")
    calls = _spy(monkeypatch, "app.web.chat", "anthropic_chat")
    factory.make_chat_analyzer()
    _, model = calls[0]
    assert model == "claude-haiku-4-5"


def test_chat_analyzer_openai_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(factory.settings, "chat_provider", "openai")
    calls = _spy(monkeypatch, "app.web.openai_chat", "openai_chat")
    assert factory.make_chat_analyzer() == "openai_chat-analyzer"
    transport, model = calls[0]
    assert callable(transport)
    assert model == "claude-opus-4-8"


def test_chat_analyzer_none_when_key_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(factory.settings, "chat_provider", "openai")
    monkeypatch.setattr(factory.settings, "openai_api_key", "")
    assert factory.make_chat_analyzer() is None


def test_rag_chat_analyzer_passes_embedder(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _spy(monkeypatch, "app.web.chat", "anthropic_rag_chat")
    sentinel = object()
    factory.make_rag_chat_analyzer(sentinel)  # type: ignore[arg-type]
    transport, model, embedder = calls[0]
    assert embedder is sentinel
    assert model == "claude-opus-4-8"


def test_rag_chat_analyzer_openai_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(factory.settings, "chat_provider", "openai")
    calls = _spy(monkeypatch, "app.web.openai_chat", "openai_rag_chat")
    sentinel = object()
    assert factory.make_rag_chat_analyzer(sentinel) == "openai_rag_chat-analyzer"  # type: ignore[arg-type]
    _, model, embedder = calls[0]
    assert embedder is sentinel
    assert model == "claude-opus-4-8"


def test_rag_chat_analyzer_none_when_key_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(factory.settings, "anthropic_api_key", "")
    assert factory.make_rag_chat_analyzer(object()) is None  # type: ignore[arg-type]


def test_chat_key_configured_true_when_key_set() -> None:
    assert factory.chat_key_configured() is True


def test_chat_key_configured_false_when_key_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(factory.settings, "anthropic_api_key", None)
    assert factory.chat_key_configured() is False


def test_chat_key_configured_reads_chat_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(factory.settings, "chat_provider", "openai")
    monkeypatch.setattr(factory.settings, "openai_api_key", "ok")
    monkeypatch.setattr(factory.settings, "anthropic_api_key", None)
    assert factory.chat_key_configured() is True


def test_unknown_provider_raises_valueerror(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(factory.settings, "impact_provider", "gemini")
    with pytest.raises(ValueError, match="unknown provider"):
        factory.make_impact_analyzer()
