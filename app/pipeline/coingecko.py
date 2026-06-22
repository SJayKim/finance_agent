"""CoinGecko 코인 동기화 (STAGE1_DESIGN §6.4 security_aliases 시딩 — CRYPTO 소스).

CoinGecko /coins/list는 전체 코인의 id·symbol·name을 키 없이 준다(~15k). 설계
§5.4가 크립토 유니버스를 "BTC/ETH/SOL + RWA 내러티브 토큰"으로 좁게 고정했으므로
_UNIVERSE 화이트리스트에 든 id만 골라 name -> (SYMBOL, "CRYPTO")로 적재한다. 전체
덤프는 심볼·이름 충돌로 별칭이 중의적이 되어 §6.4 precision 게이트를 깬다(의도적 협소).
사내 TLS 가로채기 대비 truststore로 OS 인증서 신뢰(CLAUDE.md gotcha).
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

_COINS_LIST_URL = "https://api.coingecko.com/api/v3/coins/list"
_log = logging.getLogger(__name__)

# §5.4 크립토 유니버스(좁게 고정): BTC/ETH/SOL + RWA 내러티브 토큰. CoinGecko id 기준.
# 운영자가 내러티브 변화에 맞춰 이 집합을 늘린다(전체 리스트 시딩은 중의성으로 금지).
_UNIVERSE = frozenset(
    {
        "bitcoin",
        "ethereum",
        "solana",
        "chainlink",
        "ondo-finance",
        "pendle",
        "mantra-dao",
        "centrifuge",
    }
)


def _client() -> httpx.Client:
    # OS 인증서 저장소 신뢰(사내 TLS 가로채기 대응; opendart.py와 동일 패턴).
    ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    headers = {}
    if settings.coingecko_api_key:
        headers["x-cg-demo-api-key"] = settings.coingecko_api_key
    return httpx.Client(timeout=30.0, verify=ctx, headers=headers)


def _parse_coins(blob: bytes) -> list[tuple[str, str]]:
    """/coins/list 바이트 -> 유니버스에 든 코인의 (name, SYMBOL).

    형식: [{"id": str, "symbol": str, "name": str}, ...]. symbol은 대문자 정규화.
    """
    data = json.loads(blob)
    pairs: list[tuple[str, str]] = []
    for row in data:
        if row.get("id") not in _UNIVERSE:
            continue
        name = (row.get("name") or "").strip()
        symbol = (row.get("symbol") or "").strip().upper()
        if name and symbol:
            pairs.append((name, symbol))
    return pairs


def fetch_universe_coins(*, client: httpx.Client | None = None) -> list[tuple[str, str]]:
    """CoinGecko에서 유니버스 코인 (name, SYMBOL) 목록을 받는다.

    키 불필요(있으면 Demo 한도 상향). client 주입 시 그걸 쓴다(테스트).
    미주입 시 truststore 클라이언트 1회용.
    """
    owns = client is None
    http = client or _client()
    try:
        resp = http.get(_COINS_LIST_URL)
        resp.raise_for_status()
        blob = resp.content
    finally:
        if owns:
            http.close()
    return _parse_coins(blob)


def sync(session: Session, *, client: httpx.Client | None = None) -> int:
    """CoinGecko 유니버스 코인을 security_aliases에 upsert. 신규 적재 행 수 반환.

    같은 (alias, ticker, market) 재실행은 무시(ON CONFLICT DO NOTHING). 멱등.
    """
    pairs = fetch_universe_coins(client=client)
    if not pairs:
        return 0
    rows = [{"alias": name, "ticker": symbol, "market": "CRYPTO"} for name, symbol in pairs]
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
    _log.info("CoinGecko 동기화: security_aliases %d행 신규 적재", inserted)


if __name__ == "__main__":
    main()
