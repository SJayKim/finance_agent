"""프롬프트 버전 레지스트리 단위 테스트 (플랜 10).

핵심 계약 둘: (1) v0은 운영 상수와 항등(`is`) — 레지스트리 도입이 운영 경로를 못 바꾼다는 증명,
(2) 등록된 모든 버전이 공통 불변식을 지킨다 — 0~100 범위는 프롬프트가 유일한 강제 수단
(Anthropic structured output integer min/max 미지원)이고, direction 무부호·인용 범위 제약이
빠지면 비교가 프롬프트 기법이 아니라 규칙 누락을 측정하게 된다.
"""

from __future__ import annotations

import pytest

from app.pipeline.citations import _PASS1_SYSTEM, _PASS2_SYSTEM
from app.pipeline.openai_citations import _SYSTEM
from app.pipeline.prompt_versions import (
    ANTHROPIC_VERSIONS,
    OPENAI_VERSIONS,
    anthropic_prompts,
    openai_prompts,
)


def test_v0_is_identical_to_production_constants() -> None:
    assert anthropic_prompts("v0").pass1_system is _PASS1_SYSTEM
    assert anthropic_prompts("v0").pass2_system is _PASS2_SYSTEM
    assert openai_prompts("v0").system is _SYSTEM


def test_unknown_version_raises_with_valid_keys() -> None:
    with pytest.raises(KeyError, match="v0"):
        anthropic_prompts("nope")
    with pytest.raises(KeyError, match="v0"):
        openai_prompts("nope")


def test_all_anthropic_versions_keep_invariants() -> None:
    for version, prompts in ANTHROPIC_VERSIONS.items():
        scoring = prompts.pass2_system
        assert "0~100" in scoring, f"{version}: 점수 범위 명시 누락"
        assert "direction" in scoring, f"{version}: direction 규칙 누락"
        assert "부호" in scoring, f"{version}: 무부호 규칙 누락"


def test_all_openai_versions_keep_invariants() -> None:
    for version, prompts in OPENAI_VERSIONS.items():
        assert "0~100" in prompts.system, f"{version}: 점수 범위 명시 누락"
        assert "direction" in prompts.system, f"{version}: direction 규칙 누락"
        assert "부호" in prompts.system, f"{version}: 무부호 규칙 누락"
        assert "citations" in prompts.system, f"{version}: 인용 범위 제약 누락"
