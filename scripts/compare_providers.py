"""Anthropic vs OpenAI 영향도 분석 A/B 비교 — 로컬 dev DB 전용(운영 경로 불변).

실행: uv run python -m scripts.compare_providers --date YYYY-MM-DD
  [--max-clusters 150] [--model gpt-5.4-mini] [--anthropic-model claude-...]
  [--prompt-version v0] [--include-ids 1009,...] [--providers anthropic,openai] [--dump-dir DIR]

프로바이더별로 해당 날짜 분석 결과를 리셋(citations 삭제 + 분석 컬럼 NULL + status='empty')한
뒤 analyze_impact를 명시 주입 analyzer로 돌리고 메트릭을 스냅샷한다. 리셋이 파괴적이라
DATABASE_URL에 localhost가 없으면 거부한다(--force로 해제). 기본 순서 anthropic → openai —
마지막 실행 결과가 DB(대시보드)에 남으므로 최종 상태는 GPT 결과다.
analyze_impact는 status=empty만 분석하므로 각 실행 전 리셋이 필수다. run_pipeline이 아니라
analyze_impact 직접 호출인 이유: dedup/cluster 재실행·advisory lock이 불필요.

플랜 10 확장: --prompt-version(prompt_versions 레지스트리), --anthropic-model,
--include-ids(우선순위 상한 밖 프로브 아이템 강제 분석), 모델별 단가 테이블,
토큰 집계(gateway transport에 stats 주입 — 운영 무변경),
--dump-dir 지정 시 summary.json(args+메트릭) 기록.
"""

import argparse
import json
import logging
import statistics
import sys
import time
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.llm.gateway import AnalyzerStats, anthropic_messages, openai_responses
from app.models import BriefItem, Citation
from app.pipeline.citations import anthropic_analyzer
from app.pipeline.openai_citations import openai_analyzer
from app.pipeline.pipeline import _analyze_item, analyze_impact
from app.pipeline.prompt_versions import anthropic_prompts, openai_prompts

# 단가(USD / 1M tokens, input/output) — 2026-07 기준. 미등록 모델은 cost_usd를 n/a로 표기.
_OPENAI_PRICING: dict[str, tuple[float, float]] = {
    "gpt-5.4-mini": (0.75, 4.5),
    "gpt-5.4": (2.50, 15.0),
}
_ANTHROPIC_PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-4-8": (5.0, 25.0),
    "claude-sonnet-4-6": (3.0, 15.0),
}


def _cost_usd(model: str, pricing: dict[str, tuple[float, float]], stats: AnalyzerStats) -> Any:
    """모델 단가표 기반 비용. 미등록 모델은 'n/a' — 옛 상수처럼 mini 단가를 오적용하지 않는다."""
    if model not in pricing:
        return "n/a"
    usd_in, usd_out = pricing[model]
    return round(
        stats.input_tokens * usd_in / 1_000_000 + stats.output_tokens * usd_out / 1_000_000, 4
    )


def _reset(session: Session, brief_date: date) -> None:
    """해당 날짜 분석 결과 리셋 — analyze_impact가 전 아이템을 다시 분석하게(status=empty)."""
    item_ids = select(BriefItem.id).where(BriefItem.brief_date == brief_date)
    session.execute(delete(Citation).where(Citation.brief_item_id.in_(item_ids)))
    session.execute(
        update(BriefItem)
        .where(BriefItem.brief_date == brief_date)
        .values(
            event_type=None,
            direction=None,
            confidence=None,
            impact_score=None,
            analysis_text=None,
            status="empty",
        )
    )
    session.commit()


def _items(session: Session, brief_date: date) -> list[BriefItem]:
    return list(
        session.execute(
            select(BriefItem).where(BriefItem.brief_date == brief_date).order_by(BriefItem.id)
        ).scalars()
    )


def _snapshot(session: Session, brief_date: date) -> dict[str, Any]:
    """실행 직후 DB 상태에서 비교 메트릭 산출."""
    items = _items(session, brief_date)
    status = Counter(item.status for item in items)
    ok_items = [item for item in items if item.status == "ok"]
    cite_count = session.execute(
        select(func.count())
        .select_from(Citation)
        .join(BriefItem, Citation.brief_item_id == BriefItem.id)
        .where(BriefItem.brief_date == brief_date)
    ).scalar_one()
    scores = [item.impact_score for item in ok_items if item.impact_score is not None]
    return {
        "ok": status.get("ok", 0),
        "empty": status.get("empty", 0),
        "degraded": status.get("degraded", 0),
        "citations": cite_count,
        "citations_per_ok": round(cite_count / len(ok_items), 2) if ok_items else None,
        "impact_mean": round(statistics.mean(scores), 1) if scores else None,
        "impact_median": statistics.median(scores) if scores else None,
        "direction": dict(Counter(item.direction for item in ok_items if item.direction)),
        "confidence": dict(Counter(item.confidence for item in ok_items if item.confidence)),
    }


def _dump(session: Session, brief_date: date, provider: str, dump_dir: Path) -> None:
    """아이템별 JSON 덤프(수동 품질 비교용) — dump_dir/<provider>/<brief_item_id>.json."""
    out = dump_dir / provider
    out.mkdir(parents=True, exist_ok=True)
    for item in _items(session, brief_date):
        cites = session.execute(
            select(Citation).where(Citation.brief_item_id == item.id).order_by(Citation.id)
        ).scalars()
        payload = {
            "brief_item_id": item.id,
            "cluster_id": item.cluster_id,
            "status": item.status,
            "event_type": item.event_type,
            "direction": item.direction,
            "confidence": item.confidence,
            "impact_score": item.impact_score,
            "analysis_text": item.analysis_text,
            "citations": [
                {
                    "raw_document_id": c.raw_document_id,
                    "cited_text": c.cited_text,
                    "char_start": c.char_start,
                    "char_end": c.char_end,
                }
                for c in cites
            ],
        }
        (out / f"{item.id}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def _print_table(results: dict[str, dict[str, Any]]) -> None:
    """프로바이더 사이드바이사이드 요약 표."""
    providers = list(results)
    keys: list[str] = []
    for snap in results.values():
        keys.extend(k for k in snap if k not in keys)
    width = max(len(k) for k in keys) + 2
    col = 28
    print("\n" + " " * width + "".join(p.ljust(col) for p in providers))
    for key in keys:
        cells = "".join(str(results[p].get(key, "-")).ljust(col) for p in providers)
        print(key.ljust(width) + cells)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)  # 키 노출 방지(CLAUDE.md)
    parser = argparse.ArgumentParser(description="Anthropic vs OpenAI 영향도 분석 A/B 비교")
    parser.add_argument("--date", required=True, help="대상 brief_date YYYY-MM-DD")
    parser.add_argument("--max-clusters", type=int, default=150)
    parser.add_argument("--model", default="gpt-5.4-mini", help="OpenAI 모델명")
    parser.add_argument(
        "--anthropic-model", default=None, help="Anthropic 모델명(기본: settings.impact_model)"
    )
    parser.add_argument(
        "--reasoning-effort", default=None, help="openai reasoning effort (none/low/medium/high)"
    )
    parser.add_argument(
        "--prompt-version", default="v0", help="prompt_versions 레지스트리 키(기본 v0=현행)"
    )
    parser.add_argument(
        "--include-ids",
        default=None,
        help="쉼표 구분 brief_item id — 우선순위 상한 밖이어도 강제 분석(프로브용)",
    )
    parser.add_argument("--providers", default="anthropic,openai", help="쉼표 구분, 실행 순서대로")
    parser.add_argument("--dump-dir", default=None, help="아이템별 JSON 덤프 디렉터리")
    parser.add_argument("--force", action="store_true", help="localhost 아닌 DB에도 실행(파괴적)")
    args = parser.parse_args()
    brief_date = date.fromisoformat(args.date)
    include_ids = (
        [int(x) for x in args.include_ids.split(",") if x.strip()] if args.include_ids else []
    )
    anthropic_model = args.anthropic_model or settings.impact_model

    if "localhost" not in settings.database_url and not args.force:
        print(f"refusing: DATABASE_URL is not localhost ({settings.database_url.split('@')[-1]})")
        print("이 스크립트는 해당 날짜 분석 결과를 리셋한다. 로컬 dev DB에서만, 또는 --force.")
        return 1

    providers = [p.strip() for p in args.providers.split(",") if p.strip()]
    for provider in providers:
        if provider == "anthropic" and not settings.anthropic_api_key:
            print("ANTHROPIC_API_KEY 미설정")
            return 1
        if provider == "openai" and not settings.openai_api_key:
            print("OPENAI_API_KEY 미설정")
            return 1
        if provider not in ("anthropic", "openai"):
            print(f"unknown provider: {provider}")
            return 1
        try:  # 버전 미등록은 리셋(파괴적) 전에 거른다
            if provider == "anthropic":
                anthropic_prompts(args.prompt_version)
            else:
                openai_prompts(args.prompt_version)
        except KeyError as exc:
            print(exc.args[0])
            return 1

    session = SessionLocal()
    total = session.execute(
        select(func.count()).select_from(BriefItem).where(BriefItem.brief_date == brief_date)
    ).scalar_one()
    if total == 0:
        print(f"brief_items 0건 ({brief_date}) — 먼저 파이프라인을 돌릴 것:")
        print(f"  uv run python -m scripts.run_pipeline_for --date {brief_date.isoformat()}")
        return 1
    print(f"{brief_date}: brief_items {total}건, providers={providers}", flush=True)

    results: dict[str, dict[str, Any]] = {}
    for provider in providers:
        _reset(session, brief_date)
        stats = AnalyzerStats()
        if provider == "anthropic":
            assert settings.anthropic_api_key
            prompts_a = anthropic_prompts(args.prompt_version)
            # transport에 stats 주입 → 토큰·calls 집계(운영 경로는 stats=None). anthropic
            # analyzer는 quote 메트릭이 없어 transport 한쪽만 주입.
            analyzer = anthropic_analyzer(
                anthropic_messages(settings.anthropic_api_key, stats),
                anthropic_model,
                pass1_system=prompts_a.pass1_system,
                pass2_system=prompts_a.pass2_system,
            )
        else:
            assert settings.openai_api_key
            # openai는 stats 이중 주입: transport가 토큰·calls, analyzer가 quote 메트릭(D3).
            analyzer = openai_analyzer(
                openai_responses(settings.openai_api_key, stats),
                args.model,
                stats,
                reasoning_effort=args.reasoning_effort,
                system=openai_prompts(args.prompt_version).system,
            )
        started = time.monotonic()
        analyze_impact(
            session,
            brief_date,
            analyzer,
            max_clusters=args.max_clusters,
            checkpoint=session.commit,
        )
        session.commit()
        for item_id in include_ids:  # 우선순위 상한 밖 프로브 강제 분석(스크리닝용)
            item = session.get(BriefItem, item_id)
            if item is None or item.brief_date != brief_date:
                print(f"include-id {item_id}: {brief_date} brief_item 아님 — 건너뜀")
                continue
            if item.status != "empty":
                continue  # 상한 안에서 이미 분석됨
            _analyze_item(session, item, analyzer)
            session.commit()
        snap: dict[str, Any] = {
            "model": anthropic_model if provider == "anthropic" else args.model,
            "prompt_version": args.prompt_version,
        }
        snap.update(_snapshot(session, brief_date))
        snap["elapsed_s"] = round(time.monotonic() - started, 1)
        if provider == "openai":
            # 검증 통과분만 남는 하한값 — drop율 없이 인용 수만 보면 오독한다(플랜 리스크).
            returned = stats.quotes_returned
            snap["quote_drop_rate"] = (
                round(stats.quotes_dropped / returned, 3) if returned else None
            )
            snap["tokens_in/out"] = f"{stats.input_tokens}/{stats.output_tokens}"
            snap["reasoning_tokens"] = stats.reasoning_tokens
            snap["cost_usd"] = _cost_usd(args.model, _OPENAI_PRICING, stats)
        else:
            snap["tokens_in/out"] = f"{stats.input_tokens}/{stats.output_tokens}"
            snap["cost_usd"] = _cost_usd(anthropic_model, _ANTHROPIC_PRICING, stats)
        results[provider] = snap
        if args.dump_dir:
            _dump(session, brief_date, provider, Path(args.dump_dir))
            summary = {"args": vars(args), "results": results}
            (Path(args.dump_dir) / "summary.json").write_text(
                json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
            )
        print(f"{provider} done in {snap['elapsed_s']}s", flush=True)

    _print_table(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
