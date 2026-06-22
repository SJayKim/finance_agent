"""SEC company_tickers 동기화 (STAGE1_DESIGN §6.4 security_aliases 시딩 — US 소스).

SEC가 공개하는 company_tickers.json은 상장사 전체의 cik·ticker·title(회사명)을
한 파일로 준다. title -> (ticker, "US")로 별칭 사전 행을 적재한다(OpenDART KR
대칭). SEC fair-access 정책상 식별용 User-Agent가 필수(§5.3) — 없으면 호출 거부.
사내 TLS 가로채기 대비 truststore로 OS 인증서 신뢰(CLAUDE.md gotcha). 유니버스를
코드에 박지 않고 SEC -> DB로 흐르게(§2).
"""

from __future__ import annotations

import json
import logging
import ssl

import httpx
import truststore
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.models import SecurityAlias

_COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_log = logging.getLogger(__name__)


class SECError(Exception):
    """SEC가 JSON 대신 에러 페이지(403 차단 등)를 반환."""


def _client() -> httpx.Client:
    # OS 인증서 저장소 신뢰(사내 TLS 가로채기 대응; opendart.py와 동일 패턴).
    ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    return httpx.Client(timeout=30.0, verify=ctx)


def _parse_company_tickers(blob: bytes) -> list[tuple[str, str]]:
    """company_tickers.json 바이트 -> (title, ticker) 목록.

    형식: {"0": {"cik_str": int, "ticker": str, "title": str}, ...}.
    """
    data = json.loads(blob)
    pairs: list[tuple[str, str]] = []
    for row in data.values():
        title = (row.get("title") or "").strip()
        ticker = (row.get("ticker") or "").strip()
        if title and ticker:
            pairs.append((title, ticker))
    return pairs


def fetch_company_tickers(*, client: httpx.Client | None = None) -> list[tuple[str, str]]:
    """SEC에서 상장사 (title, ticker) 목록을 받는다.

    User-Agent 미설정 시 ValueError. 응답이 JSON이 아니면(차단 페이지) SECError.
    client 주입 시 그걸 쓴다(테스트). 미주입 시 truststore 클라이언트 1회용.
    """
    if not settings.sec_edgar_user_agent:
        raise ValueError("sec_edgar_user_agent 미설정 — SEC 접근에 식별 UA 필수(§5.3)")
    owns = client is None
    http = client or _client()
    # UA를 매 요청 헤더로 보낸다(주입 클라이언트에도 적용 — opendart가 키를 params로 보내듯).
    headers = {"User-Agent": settings.sec_edgar_user_agent}
    try:
        resp = http.get(_COMPANY_TICKERS_URL, headers=headers)
        resp.raise_for_status()
        blob = resp.content
    finally:
        if owns:
            http.close()
    try:
        return _parse_company_tickers(blob)
    except json.JSONDecodeError as exc:
        raise SECError(blob[:200].decode("utf-8", "replace")) from exc


def sync(session: Session, *, client: httpx.Client | None = None) -> int:
    """SEC 상장사를 security_aliases에 upsert. 신규 적재 행 수 반환.

    같은 (alias, ticker, market) 재실행은 무시(ON CONFLICT DO NOTHING). 멱등.
    """
    pairs = fetch_company_tickers(client=client)
    if not pairs:
        return 0
    rows = [{"alias": title, "ticker": ticker, "market": "US"} for title, ticker in pairs]
    # ON CONFLICT DO NOTHING은 rowcount를 -1(신뢰 불가)로 보고한다. RETURNING은
    # 실제 삽입된 행만 돌려주므로 "신규 적재 수"와 정확히 일치한다.
    stmt = (
        pg_insert(SecurityAlias)
        .values(rows)
        .on_conflict_do_nothing()
        .returning(SecurityAlias.alias)
    )
    inserted = len(session.execute(stmt).fetchall())
    session.commit()
    return inserted


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    with SessionLocal() as session:
        inserted = sync(session)
    _log.info("SEC 동기화: security_aliases %d행 신규 적재", inserted)


if __name__ == "__main__":
    main()
