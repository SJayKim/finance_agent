"""일일 오케스트레이션 (STAGE1.5_DESIGN §3 + §4 트랙 B).

run_daily = [모든 커넥터 fetch→normalize→upsert] → run_pipeline(임베더 포함)
→ build_digest. /trigger는 파이프라인만 도는 빠른 경로로 남기고(수집 자동화 없음),
이 모듈이 "수집까지 포함한 일일 1회 실행"을 책임진다.

설계 제약(§4 트랙 B 검증):
- 소스 격리: 한 소스가 장애(타임아웃·쿼터·키 부재)나도 나머지 수집·파이프라인은
  계속한다. 실패 소스는 audit_log에 기록한다.
- 동시성 가드: run_pipeline의 내부 락(_PIPELINE_LOCK_KEY)과 다른 키
  (_DAILY_LOCK_KEY)를 써서 run_daily의 락이 run_pipeline 락과 충돌하지 않게 한다.
- 빈 수집일에도 크래시 없이 빈/degraded 다이제스트.

CLAUDE.md gotcha: opendart_docs가 crtfc_key를 쿼리스트링에 싣는다 → httpx INFO 로깅이
URL을 통째로 찍어 키를 노출한다. 수집을 트리거하는 이 러너에서 httpx 로깅을 WARNING으로
억제하는 게 맞다(커넥터는 전역 로깅을 건드리지 않는다).
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.collector.base import Connector
from app.collector.edgar_docs import EdgarDocsConnector
from app.collector.finnhub import FinnhubConnector
from app.collector.marketaux import MarketauxConnector
from app.collector.naver import NaverNewsConnector, load_coverage_queries
from app.collector.opendart_docs import OpenDartDocsConnector
from app.collector.rss import RssConnector
from app.db import SessionLocal, engine
from app.embed import Embedder, get_embedder
from app.llm.factory import make_digester
from app.models import AuditLog, DailyDigest, RawDocument
from app.pipeline.citations import ImpactAnalyzer
from app.pipeline.digest import Digester, build_digest
from app.pipeline.pipeline import run_pipeline
from app.pipeline.seed import seed_universe

# run_pipeline 내부 락(_PIPELINE_LOCK_KEY = 1_958_374_620)과 반드시 달라야 한다 — 같으면
# run_daily가 잡은 락 때문에 그 안에서 부르는 run_pipeline이 PipelineAlreadyRunning으로 죽는다.
_DAILY_LOCK_KEY = 1_958_374_621

_KST = timezone(timedelta(hours=9))  # 06:40/07:00 KST 크론과 같은 기준일(§3) — KST는 DST 없음

logger = logging.getLogger(__name__)


class DailyRunAlreadyRunning(RuntimeError):
    """run_daily 동시 실행 방지 가드 위반(다른 일일 실행이 진행 중)."""


@dataclass(frozen=True)
class SourceResult:
    name: str
    status: str  # "ok" | "error"
    attempted: int  # 처리한 페이로드 수
    error: str | None = None


@dataclass(frozen=True)
class DailyRunReport:
    brief_date: date
    sources: list[SourceResult]
    embedded: int  # 임베딩된 문서 수(임베더 없으면 0)
    digest_status: str  # "ok" | "empty" | "degraded" | "skipped"


def build_default_connectors() -> list[tuple[str, Connector]]:
    """일일 실행 기본 커넥터 묶음(이름 → 커넥터). 소스 격리 단위가 이 이름이다.

    EDGAR의 CIK 유니버스는 코드에 박지 않는다(§2: 유니버스는 DB/커버리지에서 흐른다).
    ciks=[]는 원칙적 placeholder — UA가 설정돼 있으면 빈 루프(no-op)이고, CIK 유니버스가
    DB/coverage에서 공급되기 전까지는 아무 문서도 가져오지 않는다. 무작위 CIK를 지어내지 않는다.

    네이버 쿼리도 같은 원칙: coverage/security_aliases에서 도출한다(하드코딩 금지). 빈 DB →
    빈 쿼리 → 네이버 no-op. 짧게 세션을 열어 읽는다(EDGAR ciks=[]와 대칭).
    """
    with SessionLocal() as session:
        naver_queries = load_coverage_queries(session)
    return [
        ("rss", RssConnector()),
        # display=30: 시딩 후 쿼리 7개 × display 100 = 일 ~700건이 분석 상한·Actions 시간을
        # 압도했다(7/2 timeout). 일일 실행의 수집량 정책은 runner 소관 — 커넥터 기본값은 유지.
        ("naver", NaverNewsConnector(naver_queries, display=30)),
        ("opendart_docs", OpenDartDocsConnector()),
        ("edgar_docs", EdgarDocsConnector(ciks=[])),  # CIK 유니버스는 DB/커버리지에서(§2)
        ("marketaux", MarketauxConnector()),
        ("finnhub", FinnhubConnector()),
    ]


def _collect(connectors: list[tuple[str, Connector]]) -> list[SourceResult]:
    """각 커넥터를 격리된 try/except로 돌려 raw_documents에 적재하고 결과를 audit_log에 남긴다.

    소스 격리(§4 트랙 B): 한 소스의 예외(타임아웃·쿼터·키 부재)는 그 소스의 SourceResult를
    "error"로 기록하고 다음 커넥터로 넘어간다 — 다른 소스 수집을 멈추지 않는다. 소스별로
    audit_log 1행(action="source_fetch")을 별도 세션에서 커밋한다.
    """
    results: list[SourceResult] = []
    for name, connector in connectors:
        attempted = 0
        try:
            for payload in connector.fetch():
                connector.upsert(connector.normalize(payload))
                attempted += 1
            result = SourceResult(name=name, status="ok", attempted=attempted)
        except Exception as exc:  # noqa: BLE001 — 소스 격리: 어떤 예외도 다음 소스를 막지 않는다
            logger.warning("source_fetch failed: %s: %s", name, exc)
            result = SourceResult(
                name=name, status="error", attempted=attempted, error=str(exc)[:300]
            )
        results.append(result)
        with SessionLocal() as session:
            session.add(
                AuditLog(
                    actor="run_daily",
                    action="source_fetch",
                    payload={
                        "name": result.name,
                        "status": result.status,
                        "attempted": result.attempted,
                        "error": result.error,
                    },
                )
            )
            session.commit()
    return results


def _count_embedded(brief_date: date) -> int:
    """그날 fetch된 raw_documents 중 embedding이 채워진 행 수(임베더 적재 결과 확인용).

    fetched_at(server-side now)가 brief_date(KST 기준 종일)에 든 문서만 센다 — 누적 코퍼스
    전체가 아니라 이번 실행이 영향을 준 범위. 임베더 없으면 호출자가 0을 쓴다.
    """
    start_utc = datetime(brief_date.year, brief_date.month, brief_date.day, tzinfo=_KST).astimezone(
        timezone.utc
    )
    end_utc = start_utc + timedelta(days=1)
    with SessionLocal() as session:
        return session.execute(
            select(func.count())
            .select_from(RawDocument)
            .where(
                RawDocument.embedding.is_not(None),
                RawDocument.fetched_at >= start_utc,
                RawDocument.fetched_at < end_utc,
            )
        ).scalar_one()


def _digest_status(brief_date: date) -> str:
    """그날 DailyDigest 행들에서 다이제스트 상태를 도출한다.

    하나라도 ok면 "ok", 전부 empty면 "empty", degraded가 섞였으면 "degraded", 행이
    아예 없으면 "skipped"(build_digest는 최소 1행을 쓰므로 정상 경로에선 발생하지 않는다).
    """
    with SessionLocal() as session:
        statuses = (
            session.execute(select(DailyDigest.status).where(DailyDigest.brief_date == brief_date))
            .scalars()
            .all()
        )
    if not statuses:
        return "skipped"
    if "ok" in statuses:
        return "ok"
    if "degraded" in statuses:
        return "degraded"
    return "empty"


def run_daily(
    brief_date: date,
    *,
    connectors: list[tuple[str, Connector]] | None = None,
    embedder: Embedder | None = None,
    digester: Digester | None = None,
    analyzer: ImpactAnalyzer | None = None,
    seeder: Callable[[Session], dict[str, int]] | None = None,
) -> DailyRunReport:
    """일일 1회 실행: 유니버스 시딩 → 모든 커넥터 수집 → run_pipeline → build_digest (§4 트랙 B).

    동시성 가드는 run_pipeline 내부 락과 다른 _DAILY_LOCK_KEY를 쓴다 — 안에서 부르는
    run_pipeline이 자기 락을 따로 잡으므로 둘이 충돌하면 안 된다. 락 미획득 시
    DailyRunAlreadyRunning. embedder/analyzer/digester/seeder는 호출자가 실/가짜를 주입한다
    (None이면 각 단계가 graceful 비활성: 임베딩 0, 분석 골격만, 다이제스트 degraded, 시딩 skip).
    seeder는 run_pipeline의 ticker_link보다 먼저(락 안 첫 단계) 돌아 별칭 사전을 채운다 — 비면
    링크 0건. main()/엔드포인트가 실 seed_universe(외부 API 호출)를 주입하고, 테스트는 None/가짜.
    """
    logging.getLogger("httpx").setLevel(logging.WARNING)  # crtfc_key 노출 방지(CLAUDE.md)
    if connectors is None:
        connectors = build_default_connectors()

    # 락은 전용 연결에 고정한다(같은 연결에서 잡고/풀기). 작업 세션에서 잡고 커밋 뒤 풀면
    # 커밋이 연결을 풀에 반납해 언락이 다른 연결에서 돌아 락이 누수된다 — run_pipeline과 동일.
    with engine.connect() as lock_conn:
        acquired = lock_conn.execute(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": _DAILY_LOCK_KEY}
        ).scalar()
        if not acquired:
            raise DailyRunAlreadyRunning(f"run_daily already running (lock {_DAILY_LOCK_KEY})")
        try:
            if seeder is not None:
                with SessionLocal() as session:
                    seeded = seeder(session)
                with SessionLocal() as session:
                    session.add(AuditLog(actor="run_daily", action="seed", payload=seeded))
                    session.commit()
            sources = _collect(connectors)
            # run_pipeline은 자기 세션·락·analyzer 자동생성을 관리한다(여기서 락을 안 잡음).
            run_pipeline(brief_date, analyzer=analyzer, embedder=embedder)
            embedded = _count_embedded(brief_date) if embedder is not None else 0
            with SessionLocal() as session:
                build_digest(session, brief_date, digester=digester)
                session.commit()
            digest_status = _digest_status(brief_date)
            report = DailyRunReport(
                brief_date=brief_date,
                sources=sources,
                embedded=embedded,
                digest_status=digest_status,
            )
            with SessionLocal() as session:
                session.add(
                    AuditLog(
                        actor="run_daily",
                        action="daily_run",
                        payload={
                            "brief_date": report.brief_date.isoformat(),
                            "sources": [asdict(s) for s in report.sources],
                            "embedded": report.embedded,
                            "digest_status": report.digest_status,
                        },
                    )
                )
                session.commit()
            return report
        finally:
            lock_conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": _DAILY_LOCK_KEY})


def main() -> int:
    """CLI: python -m app.runner [--date YYYY-MM-DD]. cron/작업 스케줄러가 매일 부른다.

    실 임베더(get_embedder, bge-m3 lazy-load)와 실 디제스터(키 있을 때)를 주입한다.
    analyzer는 주입하지 않는다 — run_pipeline이 키 유무로 알아서 만든다(빠른 경로와 일관).
    종료코드: 정상 0, 다른 일일 실행이 진행 중이면 비0(DailyRunAlreadyRunning).
    """
    # Windows cp949 stdout이 비-ASCII(한글·em dash) print에 죽는 것 방지. typeshed가 sys.stdout을
    # TextIO로 봐 reconfigure를 모름(TextIOWrapper엔 있음) → union-attr 무시.
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)  # crtfc_key 노출 방지(CLAUDE.md)

    parser = argparse.ArgumentParser(description="일일 수집→파이프라인→다이제스트 1회 실행")
    parser.add_argument("--date", help="기준일 YYYY-MM-DD (기본: 오늘 KST)")
    args = parser.parse_args()
    brief_date = date.fromisoformat(args.date) if args.date else datetime.now(_KST).date()

    digester = make_digester()

    try:
        report = run_daily(
            brief_date, embedder=get_embedder(), digester=digester, seeder=seed_universe
        )
    except DailyRunAlreadyRunning as exc:
        print(f"[run_daily] 거절: {exc}")
        return 1

    print(f"[run_daily] brief_date={report.brief_date.isoformat()}")
    for s in report.sources:
        line = f"  - {s.name}: {s.status} (attempted={s.attempted})"
        if s.error:
            line += f" error={s.error}"
        print(line)
    print(f"  embedded={report.embedded}  digest_status={report.digest_status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
