"""특정일 파이프라인만 재실행(신규 수집 없음) — timeout으로 죽은 날 백필용.

build_digest_for.py의 거울: 이미 수집된 raw_documents로 dedup→cluster→분석→ticker_link→
embed를 돌린다. 상한(IMPACT_ANALYZE_MAX_CLUSTERS) 초과분은 같은 명령 재실행이 멱등하게
이어서 분석한다. 여러 날짜를 백필할 땐 반드시 최신 날짜부터 내림차순으로 — _candidate_docs의
신선도 필터에 published_at 상한이 없어, 과거 날짜를 먼저 돌리면 이후 날짜 발행 문서를 흡수한다.
"""

import argparse
import logging
import sys
from datetime import date

from app.embed import get_embedder
from app.pipeline.pipeline import run_pipeline


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)  # 키 노출 방지(CLAUDE.md)
    parser = argparse.ArgumentParser(description="특정일 파이프라인만 재실행(수집 없음)")
    parser.add_argument("--date", required=True, help="대상 brief_date YYYY-MM-DD")
    brief_date = date.fromisoformat(parser.parse_args().date)
    run_pipeline(brief_date, embedder=get_embedder())  # analyzer는 키에서 자동 생성
    print(f"pipeline ran for {brief_date.isoformat()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
