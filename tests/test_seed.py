"""유니버스 시딩 단위·통합 테스트.

seed_aliases: 세 시더를 소스 격리로 호출(한 소스 실패가 나머지를 막지 않음). 실제 외부 API를
치지 않도록 sync 함수를 monkeypatch한다. seed_coverage/seed_universe: 빈 테이블→삽입,
재실행→0(멱등)을 실 DB(db 픽스처)로 검증한다.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

import app.pipeline.seed as seed
from app.models import Coverage


def test_seed_aliases_isolates_failures(db: sessionmaker, monkeypatch) -> None:
    """한 시더가 키 부재(ValueError)로 실패해도 나머지는 정상 적재 수를 돌려준다."""
    monkeypatch.setattr(seed.sec, "sync", lambda session: 5)
    monkeypatch.setattr(
        seed.opendart,
        "sync",
        lambda session: (_ for _ in ()).throw(ValueError("opendart_api_key 미설정")),
    )
    monkeypatch.setattr(seed.coingecko, "sync", lambda session: 3)

    with db() as session:
        counts = seed.seed_aliases(session)

    assert counts == {"sec": 5, "opendart": 0, "coingecko": 3}


def test_seed_coverage_idempotent(db: sessionmaker) -> None:
    """빈 coverage → STARTER_COVERAGE 삽입, 재실행 → 0(이미 있으면 안 넣음)."""
    with db() as session:
        first = seed.seed_coverage(session)
        assert first == len(seed.STARTER_COVERAGE)

    with db() as session:
        rows = session.execute(select(func.count()).select_from(Coverage)).scalar_one()
        assert rows == len(seed.STARTER_COVERAGE)
        second = seed.seed_coverage(session)
        assert second == 0  # 이미 있으므로 추가 삽입 없음
        rows_after = session.execute(select(func.count()).select_from(Coverage)).scalar_one()
        assert rows_after == len(seed.STARTER_COVERAGE)


def test_seed_universe_combines_aliases_and_coverage(db: sessionmaker, monkeypatch) -> None:
    """seed_universe는 별칭 시더 결과 + coverage 키를 합친 dict를 돌려준다."""
    monkeypatch.setattr(seed.sec, "sync", lambda session: 0)
    monkeypatch.setattr(seed.opendart, "sync", lambda session: 0)
    monkeypatch.setattr(seed.coingecko, "sync", lambda session: 2)

    with db() as session:
        counts = seed.seed_universe(session)

    assert counts == {"sec": 0, "opendart": 0, "coingecko": 2, "coverage": len(seed.STARTER_COVERAGE)}
