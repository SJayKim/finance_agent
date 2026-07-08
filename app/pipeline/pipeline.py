"""고정 파이프라인 단계 (STAGE1_DESIGN §6).

normalize → dedup(SimHash→임베딩 cosine) → cluster → ticker-link(OpenFIGI+사전)
→ event-classify → 영향도 생성(2-패스 Citations, §7).

단계 간 상태는 DB로 흐른다(§3·§8: Postgres가 단일 상태 저장소). run_pipeline은
구현된 단계만 명시 호출하고, 나머지는 구현될 때 한 줄씩 추가한다.
현재: dedup → cluster(단독 문서) → 영향도 골격(brief_items) → §7 2-패스 분석(analyze_impact)
→ ticker-link 배선까지.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal, engine
from app.embed import Embedder
from app.models import (
    BriefItem,
    BriefItemTicker,
    Citation,
    Cluster,
    ClusterMember,
    RawDocument,
    SecurityAlias,
)
from app.llm.factory import make_impact_analyzer
from app.pipeline.citations import (
    ImpactAnalyzer,
    SourceDoc,
)
from app.pipeline.dedup import near_duplicate_groups
from app.pipeline.embed import embed_documents
from app.pipeline.openfigi import make_client
from app.pipeline.ticker_link import cached_openfigi_normalizer, resolve


_PIPELINE_LOCK_KEY = 1_958_374_620  # arbitrary stable bigint for pg_try_advisory_lock

logger = logging.getLogger(__name__)


class PipelineAlreadyRunning(RuntimeError):
    """run_pipeline 동시 실행 방지 가드 위반."""


def normalize() -> None:
    raise NotImplementedError


_KST = timezone(timedelta(hours=9))  # brief_date는 KST 기준일(run_daily) — 컷오프도 KST로 앵커


def _freshness_cutoff(brief_date: date, hours: int) -> datetime:
    """brief_date 종일(KST 다음날 00:00)에서 hours를 뺀 신선도 컷오프 (§5.7).

    brief_date는 KST 기준일이므로(run_daily가 datetime.now(_KST).date()로 산출) 종일
    경계도 KST로 잡는다. UTC로 잡으면 KST 오전에 돌린 수집분(전날 저녁~당일 새벽 UTC
    발행)이 컷오프 위로 밀려 통째로 잘려 클러스터가 0이 된다. 반환은 published_at(UTC
    aware) 비교용으로 UTC aware로 정규화한다.
    """
    end_of_day = datetime(
        brief_date.year, brief_date.month, brief_date.day, tzinfo=_KST
    ) + timedelta(days=1)
    return (end_of_day - timedelta(hours=hours)).astimezone(timezone.utc)


def _candidate_docs(session: Session, cutoff: datetime) -> list[tuple[int, str]]:
    """아직 어떤 클러스터에도 안 들어간, 신선도 윈도우 내 제목 있는 raw_documents (멱등 재실행 대비).

    published_at IS NULL인 문서는 신선도를 알 수 없으므로 포함(배제 금지).
    """
    clustered = select(ClusterMember.raw_document_id)
    rows = session.execute(
        select(RawDocument.id, RawDocument.title).where(
            RawDocument.id.not_in(clustered),
            (RawDocument.published_at >= cutoff) | RawDocument.published_at.is_(None),
        )
    ).all()
    return [(doc_id, title) for doc_id, title in rows if title is not None]


def dedup(session: Session, brief_date: date, freshness_window_hours: int) -> None:
    """dedup 1차: 제목 SimHash 근접중복 그룹을 clusters/cluster_members로 적재 (§6.2).

    크기 ≥2 그룹만 클러스터가 된다(단독 문서는 cluster 단계(§6.3) 몫). 이미 클러스터에
    속한 문서는 후보에서 빠져 재실행이 중복 적재하지 않는다. 커밋은 호출자(run_pipeline).
    신선도 컷오프(§5.7): published_at >= _freshness_cutoff(brief_date, freshness_window_hours)
    또는 published_at IS NULL인 문서만 후보로 받는다.
    """
    cutoff = _freshness_cutoff(brief_date, freshness_window_hours)
    for group in near_duplicate_groups(_candidate_docs(session, cutoff)):
        cluster_row = Cluster(brief_date=brief_date, representative_doc_id=min(group))
        session.add(cluster_row)
        session.flush()  # cluster_row.id 확보 후 멤버 적재
        session.add_all(
            ClusterMember(cluster_id=cluster_row.id, raw_document_id=doc_id) for doc_id in group
        )
    session.flush()  # cluster 단계(§6.3)가 이 멤버를 후보에서 빼므로 끝에서 flush(autoflush=False)


def cluster(session: Session, brief_date: date, freshness_window_hours: int) -> None:
    """cluster 단계 (§6.3): dedup 후 남은 단독 문서를 1-멤버 클러스터로 적재.

    임베딩 cosine 2차 병합(§6.3 후단)은 §11.3 모델 미정이라 보류한다. 베이스라인은
    아직 어떤 클러스터에도 안 든, 신선도 윈도우 내 제목 있는 문서마다 1-멤버 클러스터를
    만든다 — 단독 뉴스도 brief_item이 될 자격을 얻는다(이게 없으면 dedup이 만든 크기 ≥2
    그룹만 통과해 고유 기사는 영원히 누락). _candidate_docs가 이미 클러스터된 문서를
    빼므로 dedup의 ≥2 그룹은 보존되고 단독 문서만 새 클러스터가 된다(중복 적재 없음).
    커밋은 호출자(run_pipeline).
    """
    cutoff = _freshness_cutoff(brief_date, freshness_window_hours)
    for doc_id, _title in _candidate_docs(session, cutoff):
        cluster_row = Cluster(brief_date=brief_date, representative_doc_id=doc_id)
        session.add(cluster_row)
        session.flush()  # cluster_row.id 확보 후 멤버 적재
        session.add(ClusterMember(cluster_id=cluster_row.id, raw_document_id=doc_id))


def _brief_items_without_tickers(session: Session, brief_date: date) -> list[BriefItem]:
    """이 brief_date의 brief_item 중 아직 티커가 안 붙은 것 (멱등 재실행 대비)."""
    linked = select(BriefItemTicker.brief_item_id)
    rows = session.execute(
        select(BriefItem).where(BriefItem.brief_date == brief_date, BriefItem.id.not_in(linked))
    ).scalars()
    return list(rows)


def _representative_title(session: Session, cluster_id: int) -> str | None:
    return session.execute(
        select(RawDocument.title)
        .join(Cluster, Cluster.representative_doc_id == RawDocument.id)
        .where(Cluster.id == cluster_id)
    ).scalar_one_or_none()


def ticker_link(
    session: Session,
    brief_date: date,
    dictionary: Mapping[str, list[tuple[str, str]]],
    normalizer: Callable[[str, str], str | None] | None = None,
) -> None:
    """ticker-link 배선 (§6.4): brief_item 대표문서 제목 → brief_item_tickers.

    순수 resolve()로 사전 별칭을 찾아 적재한다. link_precision은 §6.4 실측 전이라
    NULL(게이트 측정은 후속 작업). is_candidate는 resolve의 판단을 그대로 보존.
    사전이 비면(기본 빈 dict) 아무것도 적재하지 않는다 — 유니버스 하드코딩 금지(§2).
    """
    for item in _brief_items_without_tickers(session, brief_date):
        if item.cluster_id is None:
            continue
        title = _representative_title(session, item.cluster_id)
        if title is None:
            continue
        for link in resolve(title, dictionary, normalizer):
            session.add(
                BriefItemTicker(
                    brief_item_id=item.id,
                    ticker=link.ticker,
                    market=link.market,
                    is_candidate=link.is_candidate,
                )
            )


def load_aliases(session: Session) -> dict[str, list[tuple[str, str]]]:
    """security_aliases 테이블 → resolve()용 별칭 사전 (§6.4 배선 실체화).

    빈 테이블이면 빈 dict → 링크 0건(§2: 유니버스를 코드에 박지 않고 DB 상태로 흐르게).
    별칭은 소문자로 묶는다(resolve 계약). 같은 별칭이 여러 종목이면 중의적 후보 목록.
    """
    dictionary: dict[str, list[tuple[str, str]]] = {}
    rows = session.execute(select(SecurityAlias.alias, SecurityAlias.ticker, SecurityAlias.market))
    for alias, ticker, market in rows:
        dictionary.setdefault(alias.lower(), []).append((ticker, market))
    return dictionary


def event_classify() -> None:
    raise NotImplementedError


def _clusters_without_brief_item(session: Session, brief_date: date) -> list[Cluster]:
    """이 brief_date의 클러스터 중 아직 brief_item이 없는 것 (멱등 재실행 대비)."""
    has_item = select(BriefItem.cluster_id).where(BriefItem.cluster_id.is_not(None))
    rows = session.execute(
        select(Cluster).where(Cluster.brief_date == brief_date, Cluster.id.not_in(has_item))
    ).scalars()
    return list(rows)


def generate_impact(session: Session, brief_date: date) -> None:
    """영향도 생성 골격 (§6.6/§7): 클러스터 → brief_items.

    여기선 빈 brief_item만 만든다 — event_type·direction·confidence·analysis_text는 NULL,
    status=empty. 채우는 일은 다음 단계 analyze_impact(§7 2-패스 Citations) 몫이며, 분석기가
    없거나 근거가 없으면 status=empty가 그대로 남는다(§10 null-evidence: 환각으로 채우지
    않는다). 클러스터당 brief_item 1건, 멱등. ticker_link가 이 brief_item을 읽어 티커를
    붙이므로 끝에서 flush해 id를 확정한다.
    """
    for cluster_row in _clusters_without_brief_item(session, brief_date):
        session.add(BriefItem(brief_date=brief_date, cluster_id=cluster_row.id, status="empty"))
    session.flush()


def _empty_brief_items(
    session: Session, brief_date: date, limit: int | None = None
) -> list[BriefItem]:
    """이 brief_date의 아직 분석 안 된 brief_item (status=empty). 멱등 재시도용.

    분석 상한(limit)이 걸릴 때 가치 높은 것부터 소진하도록 정렬한다: 클러스터 멤버 수
    DESC(멀티소스 이벤트 우선) → 대표문서 published_at DESC(최신 우선) → id. Postgres의
    DESC 기본이 NULLS FIRST라 nulls_last()가 없으면 발행일 NULL 문서가 최우선이 되는 역전.
    """
    member_counts = (
        select(ClusterMember.cluster_id, func.count().label("member_count"))
        .group_by(ClusterMember.cluster_id)
        .subquery()
    )
    stmt = (
        select(BriefItem)
        .outerjoin(member_counts, member_counts.c.cluster_id == BriefItem.cluster_id)
        .outerjoin(Cluster, Cluster.id == BriefItem.cluster_id)
        .outerjoin(RawDocument, RawDocument.id == Cluster.representative_doc_id)
        .where(BriefItem.brief_date == brief_date, BriefItem.status == "empty")
        .order_by(
            member_counts.c.member_count.desc().nulls_last(),
            RawDocument.published_at.desc().nulls_last(),
            BriefItem.id,
        )
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(session.execute(stmt).scalars())


def _cluster_source_docs(session: Session, cluster_id: int) -> list[SourceDoc]:
    """클러스터 멤버 문서들을 패스 1 입력(SourceDoc)으로. body는 P5로 None일 수 있어 제목+요약만."""
    rows = session.execute(
        select(RawDocument.id, RawDocument.title, RawDocument.summary, RawDocument.published_at)
        .join(ClusterMember, ClusterMember.raw_document_id == RawDocument.id)
        .where(ClusterMember.cluster_id == cluster_id)
    ).all()
    return [
        SourceDoc(raw_document_id=doc_id, title=title, summary=summary, published_at=published_at)
        for doc_id, title, summary, published_at in rows
    ]


def _analyze_item(session: Session, item: BriefItem, analyzer: ImpactAnalyzer) -> None:
    """brief_item 1건 분석·적재 (analyze_impact 루프 본문).

    루프에서 함수로 뽑은 이유: 본문의 조기 반환(continue)이 호출자의 checkpoint/진행 로그를
    건너뛰지 않게. 상태 전이는 analyze_impact docstring 참조.
    """
    if item.cluster_id is None:
        return
    result = analyzer(_cluster_source_docs(session, item.cluster_id))
    if result is None:
        item.status = "degraded"
        return
    if not result.citations:
        return  # 근거 없음 → empty 유지
    item.event_type = result.event_type
    item.direction = result.direction
    item.confidence = result.confidence
    item.impact_score = result.impact_score
    item.analysis_text = result.analysis_text
    item.status = "ok"
    session.add_all(
        Citation(
            brief_item_id=item.id,
            raw_document_id=span.raw_document_id,
            cited_text=span.cited_text,
            char_start=span.char_start,
            char_end=span.char_end,
            source_published_at=span.source_published_at,
        )
        for span in result.citations
    )


def analyze_impact(
    session: Session,
    brief_date: date,
    analyzer: ImpactAnalyzer | None,
    *,
    max_clusters: int | None = None,
    checkpoint: Callable[[], None] | None = None,
    checkpoint_every: int = 10,
) -> None:
    """§7 2-패스 Citations 분석으로 status=empty brief_item을 채운다.

    analyzer가 None이면 비활성(골격만 유지 — 키 없거나 오프라인). 클러스터 소스 문서를 모아
    analyzer 호출 후 결과를 적재한다:
    - None 반환(API 장애·쿼터 소진) → status=degraded (§10: 어떤 소스가 빠졌는지 표기).
    - citations ≥1 → analysis_text·event_type·direction·confidence + citations 적재, status=ok.
    - citations 0(근거 없음) → status=empty 유지 (§10: 분석 텍스트를 환각으로 채우지 않는다).
    멱등: ok/degraded는 다음 실행에서 건너뛰고 남은 empty만 재시도한다. 영향 종목은 LLM이
    아니라 ticker_link(§6.4)가 결정하므로 여기서 brief_item_tickers는 건드리지 않는다.

    max_clusters: 클러스터당 외부 LLM을 부르는 이 루프의 상한(수집량 선형 폭주 → Actions
    timeout 방지, 2026-07-04). 상한 밖 아이템은 손대지 않음 → status=empty 유지(멱등 재시도
    계약 그대로 — 다음 실행이 우선순위 순으로 이어서 분석한다).
    checkpoint: 매 checkpoint_every건마다 호출(호출자가 session.commit 주입) — 실행이 도중에
    강제 종료돼도 그때까지의 분석·LLM 비용이 살아남는다.
    """
    if analyzer is None:
        return
    items = _empty_brief_items(session, brief_date, limit=max_clusters)
    for n, item in enumerate(items, start=1):
        _analyze_item(session, item, analyzer)
        if checkpoint is not None and n % checkpoint_every == 0:
            checkpoint()
        if n % 25 == 0:
            logger.info("analyze_impact progress: %d/%d", n, len(items))


def run_pipeline(
    brief_date: date,
    dictionary: Mapping[str, list[tuple[str, str]]] | None = None,
    freshness_window_hours: int = settings.freshness_window_hours,
    analyzer: ImpactAnalyzer | None = None,
    embedder: Embedder | None = None,
    impact_max_clusters: int | None = settings.impact_analyze_max_clusters,
) -> None:
    """일간 브리프 파이프라인 1회 실행: dedup → cluster → generate_impact(골격) → analyze_impact(§7) → ticker_link → embed.

    §6 설계 순서는 ticker-link → ... → 영향도생성이나, brief_item_tickers가 brief_items
    FK라 brief_items를 먼저 만들어야 한다 → generate_impact를 ticker_link보다 앞에 둔다.
    event_classify는 구현되는 대로 순서대로 추가한다.
    dictionary 미주입 시 security_aliases 테이블에서 적재(load_aliases, 빈 테이블 → 0건) —
    유니버스를 소스에 담지 않고 DB 상태로 흐르게 한다(§2). 명시 주입(테스트 등)은 그대로 사용.
    analyzer 미주입 시 factory.make_impact_analyzer()로 설정된 provider 분석기를 만든다 —
    키 없으면 None(analyze_impact 비활성 — brief_item status=empty 유지). 테스트는 가짜 분석기를
    주입해 네트워크 없이 적재를 검증한다.
    embedder는 analyzer와 달리 자동 생성하지 않는다 — 실 모델(~2GB)이 /trigger·테스트에서
    로드되지 않게. 일일 오케스트레이터가 get_embedder()로 명시 주입할 때만 embed 단계가
    돈다(None이면 no-op). embed는 영향도 분석에 의존하지 않으므로 마지막에 둔다.
    impact_max_clusters는 analyze_impact 상한(None=무상한). 기본은 설정값 —
    IMPACT_ANALYZE_MAX_CLUSTERS env로 오버라이드 가능(백필 시 상향).
    """
    if analyzer is None:
        analyzer = make_impact_analyzer()
    # 어드바이저리 락은 연결(세션) 단위다. 락은 전용 연결(lock_conn)에 고정해 잡고 푼다 —
    # 작업 세션에서 잡고 session.commit() 뒤 finally에서 풀면, 커밋이 연결을 풀에 반납하고
    # 언락이 다른 연결에서 돌아 락이 안 풀린 채 풀에 남는다(누수 → 후속 run_pipeline이
    # PipelineAlreadyRunning). lock_conn을 끝까지 열어두면 같은 연결에서 잡고/풀고, 닫힐 때
    # 남은 락도 정리된다. 작업은 별도 세션에서 한다.
    with engine.connect() as lock_conn:
        acquired = lock_conn.execute(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": _PIPELINE_LOCK_KEY}
        ).scalar()
        if not acquired:
            raise PipelineAlreadyRunning(
                f"run_pipeline already running (lock {_PIPELINE_LOCK_KEY})"
            )
        try:
            # 점진 커밋(비원자화) 안전 근거: 락은 위 전용 lock_conn에 있어 세션 커밋과 무관하게
            # 유지되고, 각 단계의 멱등 필터(not_in 서브쿼리 — 클러스터 멤버·brief_item·티커·
            # status=empty)가 부분 커밋 상태의 재실행 중복 적재를 이미 막는다. "커밋은 호출자"
            # 규약은 checkpoint 주입으로 유지(단계 함수는 계속 flush만). 단일 트랜잭션이던
            # 시절엔 Actions timeout 강제 종료가 76분치 분석을 전량 롤백시켰다(2026-07-04).
            with SessionLocal() as session:
                logger.info("run_pipeline start: brief_date=%s", brief_date)
                dedup(session, brief_date, freshness_window_hours)
                cluster(session, brief_date, freshness_window_hours)
                generate_impact(session, brief_date)
                session.commit()  # 골격 커밋 — 이후 단계가 죽어도 clusters/brief_items는 남는다
                clusters_n = session.execute(
                    select(func.count())
                    .select_from(Cluster)
                    .where(Cluster.brief_date == brief_date)
                ).scalar_one()
                empty_n = session.execute(
                    select(func.count())
                    .select_from(BriefItem)
                    .where(BriefItem.brief_date == brief_date, BriefItem.status == "empty")
                ).scalar_one()
                logger.info(
                    "skeleton committed: clusters=%d unanalyzed=%d cap=%s",
                    clusters_n,
                    empty_n,
                    impact_max_clusters,
                )
                analyze_impact(
                    session,
                    brief_date,
                    analyzer,
                    max_clusters=impact_max_clusters,
                    checkpoint=session.commit,
                )
                session.commit()
                logger.info("analyze_impact done")
                aliases = dictionary if dictionary is not None else load_aliases(session)
                logger.info("ticker_link start: aliases=%d", len(aliases))
                with make_client() as figi_client:
                    ticker_link(
                        session, brief_date, aliases, cached_openfigi_normalizer(figi_client)
                    )
                logger.info("ticker_link done — embed start")
                embed_documents(session, embedder)  # embedder 미주입 시 no-op(모델 미로드)
                session.commit()
                logger.info("run_pipeline done: brief_date=%s", brief_date)
        finally:
            lock_conn.execute(
                text("SELECT pg_advisory_unlock(:key)"), {"key": _PIPELINE_LOCK_KEY}
            )
