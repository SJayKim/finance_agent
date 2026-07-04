"""SQLAlchemy 2.0 엔진/세션."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings

# pool_pre_ping: Fly auto-stop/재시작·Supabase 유휴 종료 후 풀에 남은 stale 커넥션이
# 첫 쿼리에서 500으로 터지는 것 방지(체크아웃 시 SELECT 1 확인).
engine = create_engine(settings.database_url, future=True, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, future=True)
