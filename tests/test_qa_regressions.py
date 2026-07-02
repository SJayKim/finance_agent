"""/qa 발견 이슈 회귀 테스트 (Report: .gstack/qa-reports/qa-report-localhost-8000-2026-07-02.md).

통합(실 Postgres): load_brief 인용 중복 제거. 픽스처·시드 관례는 test_web.py를 따른다.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy.orm import sessionmaker

from app.models import BriefItem, Citation, Cluster, RawDocument, Source
from app.web.queries import load_brief

_BRIEF_DATE = date(2026, 6, 21)
_PUB = datetime(2026, 6, 21, 9, tzinfo=timezone.utc)
_GEN = datetime(2026, 6, 21, 12, tzinfo=timezone.utc)


def _seed_brief_with_duplicate_citations(db: sessionmaker) -> None:
    """ok 브리프 1건 + 같은 (문서, 인용문) 3회 중복 + 고유 인용 1건을 시드."""
    with db() as s:
        src = Source(name="seed-src", kind="news")
        s.add(src)
        s.flush()
        doc = RawDocument(
            source_id=src.id,
            external_id="x",
            title="코스피 급락",
            published_at=_PUB,
            url="http://news/kospi",
        )
        s.add(doc)
        cluster = Cluster(brief_date=_BRIEF_DATE, representative_doc_id=None)
        s.add(cluster)
        s.flush()
        ok = BriefItem(
            brief_date=_BRIEF_DATE,
            cluster_id=cluster.id,
            event_type="index_move",
            direction="부정",
            confidence="MED",
            analysis_text="지수 영향 분석",
            status="ok",
            generated_at=_GEN,
        )
        s.add(ok)
        s.flush()
        dup = dict(
            brief_item_id=ok.id,
            raw_document_id=doc.id,
            cited_text="코스피, 8680선으로 밀려",
            source_published_at=_PUB,
        )
        s.add_all(
            [
                Citation(**dup),
                Citation(**dup),
                Citation(**dup),
                Citation(
                    brief_item_id=ok.id,
                    raw_document_id=doc.id,
                    cited_text="외국인 투자자는 1조원을 순매도했다",
                    source_published_at=_PUB,
                ),
            ]
        )
        s.commit()


def test_load_brief_dedupes_identical_citations(db: sessionmaker) -> None:
    # Regression: ISSUE-002 — LLM이 같은 인용을 여러 번 출력해 적재된 중복 행이
    # 브리프·드로어에 3~4회 반복 표시됨 (같은 인용문+원문 링크 반복).
    # Found by /qa on 2026-07-02
    # Report: .gstack/qa-reports/qa-report-localhost-8000-2026-07-02.md
    _seed_brief_with_duplicate_citations(db)
    with db() as s:
        views = load_brief(s, _BRIEF_DATE)
    assert len(views) == 1
    texts = [c.cited_text for c in views[0].citations]
    assert texts == ["코스피, 8680선으로 밀려", "외국인 투자자는 1조원을 순매도했다"]
