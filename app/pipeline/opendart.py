"""OpenDART corp_code 동기화 (STAGE1_DESIGN §6.4 security_aliases 시딩 소스).

OpenDART corpCode.xml은 전체 등록 법인의 corp_code·corp_name·stock_code를
ZIP(CORPCODE.xml) 한 방에 내려준다. stock_code가 있는(상장) 법인만 별칭 사전
행으로 적재한다: corp_name -> (stock_code, "KR"). 사내 TLS 가로채기 대비
truststore로 OS 인증서 신뢰(CLAUDE.md gotcha). 키 없으면 호출 불가(빈 키 거부).
유니버스를 코드에 박지 않고 OpenDART -> DB로 흐르게(§2).
"""

from __future__ import annotations

import io
import logging
import ssl
import zipfile
from xml.etree import ElementTree

from typing import cast

import httpx
import truststore
from sqlalchemy import CursorResult
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.models import SecurityAlias

_CORPCODE_URL = "https://opendart.fss.or.kr/api/corpCode.xml"
_log = logging.getLogger(__name__)


class OpenDARTError(Exception):
    """OpenDART가 ZIP 대신 에러 XML을 반환(키 무효·한도 등)."""


def _client() -> httpx.Client:
    # OS 인증서 저장소 신뢰(사내 TLS 가로채기 대응; openfigi.py와 동일 패턴).
    ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    return httpx.Client(timeout=30.0, verify=ctx)


def _parse_corpcode_zip(blob: bytes) -> list[tuple[str, str]]:
    """CORPCODE.zip 바이트 -> 상장(stock_code 있는) 법인의 (corp_name, stock_code)."""
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        xml = zf.read(zf.namelist()[0])
    root = ElementTree.fromstring(xml)
    pairs: list[tuple[str, str]] = []
    for node in root.iter("list"):
        name = (node.findtext("corp_name") or "").strip()
        code = (node.findtext("stock_code") or "").strip()
        if name and code:
            pairs.append((name, code))
    return pairs


def fetch_corp_codes(*, client: httpx.Client | None = None) -> list[tuple[str, str]]:
    """OpenDART에서 상장 법인 (corp_name, stock_code) 목록을 받는다.

    키 없으면 ValueError. 응답이 ZIP이 아니면(에러 XML) OpenDARTError.
    client 주입 시 그걸 쓴다(테스트). 미주입 시 truststore 클라이언트 1회용.
    """
    if not settings.opendart_api_key:
        raise ValueError("opendart_api_key 미설정 — OpenDART 동기화 불가")
    owns = client is None
    http = client or _client()
    try:
        resp = http.get(_CORPCODE_URL, params={"crtfc_key": settings.opendart_api_key})
        resp.raise_for_status()
        blob = resp.content
    finally:
        if owns:
            http.close()
    try:
        return _parse_corpcode_zip(blob)
    except zipfile.BadZipFile as exc:
        raise OpenDARTError(blob[:200].decode("utf-8", "replace")) from exc


def sync(session: Session, *, client: httpx.Client | None = None) -> int:
    """OpenDART 상장 법인을 security_aliases에 upsert. 신규 적재 행 수 반환.

    같은 (alias, ticker, market) 재실행은 무시(ON CONFLICT DO NOTHING). 멱등.
    """
    pairs = fetch_corp_codes(client=client)
    if not pairs:
        return 0
    rows = [{"alias": name, "ticker": code, "market": "KR"} for name, code in pairs]
    stmt = pg_insert(SecurityAlias).values(rows).on_conflict_do_nothing()
    result = cast(CursorResult, session.execute(stmt))
    session.commit()
    return result.rowcount


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    with SessionLocal() as session:
        inserted = sync(session)
    _log.info("OpenDART 동기화: security_aliases %d행 신규 적재", inserted)


if __name__ == "__main__":
    main()
