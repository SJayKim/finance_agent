"""유니버스 시딩 배선.

핵심 가치: security_aliases가 비면 ticker_link가 영구 0건 → "현 시황에서 영향 큰 종목
추천"이라는 산출물이 안 나온다. 세 시더(sec/opendart/coingecko)는 멱등 sync()로 이미
구현돼 있으나 각자 __main__으로만 호출됐다 — 여기서 소스 격리(try/except)로 묶어 한 곳에서
부른다. 키 없음(sec/opendart)·네트워크 장애는 warning 후 0으로 skip한다(run_daily의 소스
격리와 같은 원칙: 한 소스 실패가 나머지를 막지 않음).

coverage 주의: 현재 coverage를 읽는 소비자가 없다(naver는 DEFAULT_QUERIES 하드코딩,
coverage→쿼리 도출 미배선). seed_coverage는 그 배선이 생길 때를 위한 멱등 최소 시드다 —
행이 0개일 때만 STARTER_COVERAGE를 삽입한다(coverage엔 unique 제약이 없어 "비었을 때만"으로
멱등 보장, 마이그레이션 회피).
"""

from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Coverage
from app.pipeline import coingecko, opendart, sec

logger = logging.getLogger(__name__)

# 운영자 편집 대상: 대표 KR 섹터/종목 최소 시드. 현재 coverage 소비자가 없어 효력은 제한적이며,
# coverage→쿼리 도출이 배선되면 의미를 갖는다. ticker는 KRX 6자리 종목코드.
STARTER_COVERAGE: list[dict[str, str]] = [
    {"analyst_id": "default", "sector": "반도체", "ticker": "005930", "market": "KR"},  # 삼성전자
    {"analyst_id": "default", "sector": "반도체", "ticker": "000660", "market": "KR"},  # SK하이닉스
    {"analyst_id": "default", "sector": "2차전지", "ticker": "373220", "market": "KR"},  # LG에너지솔루션
    {"analyst_id": "default", "sector": "금융", "ticker": "105560", "market": "KR"},  # KB금융
]


def seed_aliases(session: Session) -> dict[str, int]:
    """sec/opendart/coingecko 별칭 시더를 소스 격리로 호출. 소스명→신규 적재 수 dict.

    각 sync()는 자체적으로 commit한다(멱등 ON CONFLICT DO NOTHING + RETURNING). 한 소스가
    키 부재(ValueError)·네트워크 예외로 실패하면 rollback 후 0으로 기록하고 다음 소스로 넘어간다.
    """
    counts: dict[str, int] = {}
    for name, syncer in (("sec", sec.sync), ("opendart", opendart.sync), ("coingecko", coingecko.sync)):
        try:
            counts[name] = syncer(session)
        except Exception as exc:  # noqa: BLE001 — 소스 격리: 어떤 예외도 다음 시더를 막지 않는다
            session.rollback()
            logger.warning("seed_aliases %s skipped: %s", name, exc)
            counts[name] = 0
    return counts


def seed_coverage(session: Session) -> int:
    """coverage 행이 0개일 때만 STARTER_COVERAGE를 삽입. 삽입 행 수 반환(이미 있으면 0). 멱등."""
    existing = session.execute(select(func.count()).select_from(Coverage)).scalar_one()
    if existing:
        return 0
    session.add_all([Coverage(**row) for row in STARTER_COVERAGE])
    session.commit()
    return len(STARTER_COVERAGE)


def seed_universe(session: Session) -> dict[str, int]:
    """일일 실행이 부르는 진입점: 별칭 시딩 + 커버리지 최소 시드. 소스별 신규 적재 수 dict."""
    counts = seed_aliases(session)
    counts["coverage"] = seed_coverage(session)
    return counts
