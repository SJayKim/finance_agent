"""DB 통합테스트 하니스 (실 Postgres + pgvector, alembic 스키마).

앱 import보다 먼저 DATABASE_URL을 테스트 DB로 강제 오버라이드한다 → app.db.engine과
run_pipeline의 SessionLocal이 테스트 DB를 향한다(모킹 없이 엔드투엔드). 실 Postgres가
없으면 DB 픽스처를 쓰는 테스트는 skip되고 순수 단위 테스트는 영향받지 않는다.

테스트 DB URL은 TEST_DATABASE_URL로 덮어쓸 수 있다(기본
localhost:5433/finance_agent_test). *_test 데이터베이스만 가리키므로 개발 DB는
건드리지 않는다. 띄우는 법:
    docker run -d --name fa_test_pg -e POSTGRES_PASSWORD=postgres \\
      -e POSTGRES_DB=finance_agent_test -p 5433:5432 ankane/pgvector
"""

from __future__ import annotations

import os

# 앱 import 전에 설정해야 settings.database_url(→ app.db.engine)이 테스트 DB로 고정된다.
_TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@localhost:5433/finance_agent_test",
)
os.environ["DATABASE_URL"] = _TEST_DATABASE_URL
# 개발자 .env에 실 키가 있어도 테스트는 오프라인이어야 한다 — run_pipeline은 analyzer
# 미주입 시 키 유무로 실 Anthropic 분석기를 자동 생성한다(라이브 Opus 호출·과금 방지).
# env가 .env보다 우선하므로 빈 값으로 고정. 키가 필요한 테스트는 monkeypatch로 켠다.
os.environ["ANTHROPIC_API_KEY"] = ""
# provider 스위치(플랜 11) 도입 후 openai 용도가 켜져도 라이브 콜이 나가지 않게 빈 값 고정.
os.environ["OPENAI_API_KEY"] = ""
os.environ.setdefault("DASHBOARD_USERNAME", "test-dashboard")
os.environ.setdefault("DASHBOARD_PASSWORD", "test-password")
DASHBOARD_AUTH = (os.environ["DASHBOARD_USERNAME"], os.environ["DASHBOARD_PASSWORD"])

from collections.abc import Iterator  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

_ROOT = Path(__file__).resolve().parent.parent
# TRUNCATE 순서는 CASCADE라 무관하지만 전 테이블을 한 번에 비운다(멱등 격리).
_TABLES = (
    "digest_sources",
    "daily_digests",
    "brief_item_tickers",
    "citations",
    "brief_items",
    "cluster_members",
    "clusters",
    "raw_documents",
    "sources",
    "coverage",
    "security_aliases",
    "audit_log",
)


@pytest.fixture(scope="session")
def _migrated_db() -> None:
    """실 Postgres 연결 확인 → alembic upgrade head. 연결 불가면 DB 테스트 전체 skip.

    연결 확인은 짧은 connect_timeout(2s) 전용 엔진으로 한다 — DB가 응답 없는 호스트면
    libpq 기본 타임아웃이 수 분이라 pytest가 멎은 것처럼 보인다. 앱 엔진(app.db)은
    운영 설정이라 건드리지 않고, 프로브용 엔진만 따로 연다.
    """
    probe = create_engine(_TEST_DATABASE_URL, connect_args={"connect_timeout": 2})
    try:
        with probe.connect() as conn:
            conn.execute(text("SELECT 1"))
    except OperationalError as exc:
        pytest.skip(
            f"테스트 Postgres 연결 불가({_TEST_DATABASE_URL}). "
            f"Docker ankane/pgvector를 띄우거나 TEST_DATABASE_URL을 설정하라: {exc}"
        )
    finally:
        probe.dispose()

    from alembic import command
    from alembic.config import Config

    cfg = Config(str(_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_ROOT / "migrations"))
    command.upgrade(cfg, "head")


@pytest.fixture
def db(_migrated_db: None) -> Iterator[sessionmaker]:
    """매 테스트 전 모든 테이블 TRUNCATE(격리) 후 SessionLocal 팩토리를 준다."""
    from app.db import SessionLocal, engine

    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {', '.join(_TABLES)} RESTART IDENTITY CASCADE"))
    yield SessionLocal
