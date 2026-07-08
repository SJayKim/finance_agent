"""기존 brief_items에 impact_score만 백필.

impact_score 컬럼은 alembic 0004에서 추가돼 그 이전 분석(status=ok)엔 NULL이다.
외부 뉴스 수집 없이, 이미 적재된 클러스터 소스 문서를 LLM(anthropic_analyzer)에
다시 넣어 impact_score만 UPDATE한다. analysis_text/citations 등 기존 결과는 보존.
"""

import argparse
import sys
from datetime import date

from sqlalchemy import select

from app.db import SessionLocal
from app.llm.factory import make_impact_analyzer
from app.models import BriefItem
from app.pipeline.pipeline import _cluster_source_docs


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    parser = argparse.ArgumentParser(description="기존 brief_items의 impact_score만 백필")
    parser.add_argument("--date", required=True, help="대상 brief_date YYYY-MM-DD")
    brief_date = date.fromisoformat(parser.parse_args().date)
    analyzer = make_impact_analyzer()
    assert analyzer is not None, "impact provider 키 미설정 (IMPACT_PROVIDER·해당 키 확인)"
    session = SessionLocal()
    items = (
        session.execute(
            select(BriefItem).where(
                BriefItem.brief_date == brief_date,
                BriefItem.impact_score.is_(None),
                BriefItem.cluster_id.is_not(None),
            )
        )
        .scalars()
        .all()
    )
    total = len(items)
    print(f"backfill start: {total} items", flush=True)
    filled = 0
    for i, item in enumerate(items, 1):
        assert item.cluster_id is not None  # 쿼리에서 cluster_id.is_not(None)로 필터됨
        result = analyzer(_cluster_source_docs(session, item.cluster_id))
        score = result.impact_score if result else None
        if score is not None:
            item.impact_score = score
            filled += 1
        print(f"{i}/{total} item={item.id} score={score}", flush=True)
        if i % 10 == 0:
            session.commit()
    session.commit()
    print(f"backfill done: filled {filled}/{total}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
