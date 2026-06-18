"""고정 파이프라인 단계 (STAGE1_DESIGN §6). 골격 — 단계 순서만 고정, 로직 미구현.

normalize → dedup(SimHash→임베딩 cosine) → cluster → ticker-link(OpenFIGI+사전)
→ event-classify → 영향도 생성(2-패스 Citations, §7).
"""

from __future__ import annotations


def normalize() -> None:
    raise NotImplementedError


def dedup() -> None:
    raise NotImplementedError


def cluster() -> None:
    raise NotImplementedError


def ticker_link() -> None:
    raise NotImplementedError


def event_classify() -> None:
    raise NotImplementedError


def generate_impact() -> None:
    raise NotImplementedError


# 고정 단계 순서 (§6).
STAGES = (
    normalize,
    dedup,
    cluster,
    ticker_link,
    event_classify,
    generate_impact,
)


def run_pipeline() -> None:
    """일간 브리프 파이프라인 1회 실행. 골격 — 단계 호출만, 미구현."""
    for stage in STAGES:
        stage()
