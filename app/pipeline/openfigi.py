"""OpenFIGI 매핑 클라이언트 (STAGE1_DESIGN §5.6): 식별자 → 표준 티커 정규화.

티커 링킹(§6.4)에서 사전이 뽑은 후보 식별자(US 심볼·KR 6자리)를 OpenFIGI
/v3/mapping으로 표준 티커·거래소로 정규화·검증한다. 사내 TLS 가로채기 대비
truststore로 OS 인증서 신뢰(CLAUDE.md gotcha). 키 없으면 무료 한도(25 req/min),
있으면 X-OPENFIGI-APIKEY로 상향. 크립토는 OpenFIGI 대상이 아니라 사전만 쓴다(§6.4).
"""

from __future__ import annotations

import ssl
import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx
import truststore

from app.config import settings

_MAPPING_URL = "https://api.openfigi.com/v3/mapping"


@dataclass(frozen=True)
class NormalizedTicker:
    """OpenFIGI가 확인한 표준 식별자."""

    ticker: str
    exch_code: str | None
    name: str | None


class OpenFIGIRateLimited(Exception):
    """OpenFIGI 429. 재시도 소진 후 호출자에게 전달(일배치라 다음 실행에서 회복)."""

    def __init__(self, retry_after: float | None) -> None:
        super().__init__(f"OpenFIGI rate limited (retry_after={retry_after})")
        self.retry_after = retry_after


def _client() -> httpx.Client:
    # OS 인증서 저장소 신뢰(사내 TLS 가로채기 대응; rss.py와 동일 패턴).
    ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    headers = {"Content-Type": "application/json"}
    if settings.openfigi_api_key:
        headers["X-OPENFIGI-APIKEY"] = settings.openfigi_api_key
    return httpx.Client(timeout=10.0, verify=ctx, headers=headers)


def _retry_after(resp: httpx.Response) -> float | None:
    value = resp.headers.get("Retry-After")
    return float(value) if value else None


def normalize(
    id_type: str,
    id_value: str,
    exch_code: str | None = None,
    *,
    client: httpx.Client | None = None,
    max_retries: int = 2,
    sleep: Callable[[float], None] = time.sleep,
) -> NormalizedTicker | None:
    """식별자 → 표준 티커. 매치 없으면 None(보류 판단은 호출자 §6.4).

    429는 Retry-After만큼 쉬고 max_retries까지 재시도, 끝내 막히면 OpenFIGIRateLimited.
    client 주입 시 그걸 쓴다(테스트·배치 재사용). 미주입 시 truststore 클라이언트 1회용.
    """
    job: dict[str, str] = {"idType": id_type, "idValue": id_value}
    if exch_code:
        job["exchCode"] = exch_code

    owns = client is None
    http = client or _client()
    last: httpx.Response | None = None
    try:
        for attempt in range(max_retries + 1):
            last = http.post(_MAPPING_URL, json=[job])
            if last.status_code != 429:
                break
            if attempt < max_retries:
                sleep(_retry_after(last) or 1.0)
        assert last is not None
        if last.status_code == 429:
            raise OpenFIGIRateLimited(_retry_after(last))
        last.raise_for_status()
        records = last.json()[0].get("data")
    finally:
        if owns:
            http.close()

    if not records:
        return None
    top = records[0]
    return NormalizedTicker(
        ticker=top["ticker"],
        exch_code=top.get("exchCode"),
        name=top.get("name"),
    )
