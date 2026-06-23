"""OpenDART 공시 본문 커넥터 (STAGE1.5_DESIGN §4 Track A, §5 운영표).

별칭 시더인 app/pipeline/opendart.py와 별개 모듈이다. 여기는 공시 *본문*을
채운다: 공시는 공개 법정공시라 본문 grounding이 합법(P5 — 뉴스/RSS는 요약까지,
공시만 body). list.json으로 공시 메타를 받고 document.xml(ZIP+XML)로 본문을
받아 태그를 벗겨 텍스트로 적재한다. parse_list/extract_body_from_zip/normalize는
순수 함수(네트워크·DB 없이 테스트 가능), fetch/upsert만 I/O.

운영 게이트(§5: 일 2만건 + throttling, 실적시즌 스파이크):
- document 호출 사이에 throttle_s 슬립 + 429/타임아웃에 백오프 재시도(최대 2회).
- 공시 본문은 한 번 제출되면 불변 → upsert가 자연히 멱등(on_conflict_do_nothing).
  이미 적재된 rcept_no 재요청은 충돌 무시로 스킵된다(캐싱/증분).

주의(CLAUDE.md gotcha): crtfc_key가 쿼리스트링에 실린다. 러너는 키 노출 방지를
위해 `logging.getLogger("httpx").setLevel(logging.WARNING)`로 httpx INFO 로깅을
억제할 것. 커넥터는 전역 로깅을 건드리지 않는다(러너 책임).
"""

from __future__ import annotations

import io
import logging
import re
import ssl
import time
import zipfile
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import truststore
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.collector.base import Connector, NormalizedDoc
from app.config import settings
from app.db import SessionLocal
from app.models import RawDocument, Source

_LIST_URL = "https://opendart.fss.or.kr/api/list.json"
_DOCUMENT_URL = "https://opendart.fss.or.kr/api/document.xml"
_VIEWER_URL = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"

_LEGAL_BASIS = "OpenDART 공시 본문 — 공개 법정공시(본문 grounding 합법)"

_KST = timezone(timedelta(hours=9))
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_STATUS_RE = re.compile(r"<status>([^<]*)</status>")
_MESSAGE_RE = re.compile(r"<message>([^<]*)</message>")
# 014=파일이 존재하지 않습니다(개별 공시에 다운로드 문서 없음) → 그 문서만 스킵.
# 그 외(010/011 키, 020 한도, 800 점검 등)는 전역 장애라 소스 전체를 멈춘다.
_SKIPPABLE_DOC_STATUSES = {"014"}

logger = logging.getLogger(__name__)


class OpenDartDocsError(RuntimeError):
    """OpenDART API가 에러 status(키 무효·한도·파일없음 등)를 반환."""

    def __init__(self, message: str, *, status: str | None = None) -> None:
        super().__init__(message)
        self.status = status


def _parse_document_error(content: bytes) -> tuple[str | None, str]:
    """document.xml이 ZIP 대신 준 에러 XML(<result><status>..</status><message>..)을 파싱."""
    text = content.decode("utf-8", "replace")
    status_m = _STATUS_RE.search(text)
    message_m = _MESSAGE_RE.search(text)
    return (
        status_m.group(1) if status_m else None,
        message_m.group(1).strip() if message_m else "",
    )


def _today_kst() -> str:
    return datetime.now(_KST).strftime("%Y%m%d")


def parse_list(payload_json: dict[str, Any]) -> list[dict[str, Any]]:
    """list.json 응답 -> 공시 메타 dict 리스트 (순수).

    status "000" = 정상, "013" = 데이터 없음(빈 리스트). 그 외는 OpenDartDocsError.
    """
    status = payload_json.get("status")
    if status == "013":
        return []
    if status != "000":
        message = payload_json.get("message", "")
        raise OpenDartDocsError(f"OpenDART list status={status} message={message}")
    return list(payload_json.get("list", []))


def extract_body_from_zip(zip_bytes: bytes) -> str:
    """document.xml ZIP 바이트 -> 본문 텍스트 (순수). XML 태그를 벗기고 공백 정규화."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        xml = zf.read(zf.namelist()[0])
    # itertext()는 인코딩 선언이 깨진 공시 XML에서 실패할 수 있어 태그 정규식으로 벗긴다.
    text = xml.decode("utf-8", "replace")
    text = _TAG.sub(" ", text)
    return _WS.sub(" ", text).strip()


def normalize(meta: dict[str, Any], body: str) -> NormalizedDoc:
    """공시 메타 + 본문 -> NormalizedDoc. published_at은 rcept_dt(KST 자정) -> UTC."""
    rcept_no = meta["rcept_no"]
    corp_name = meta.get("corp_name", "")
    report_nm = meta.get("report_nm", "")
    rcept_dt = (meta.get("rcept_dt") or "").strip()
    published_at = None
    if rcept_dt:
        # rcept_dt(YYYYMMDD)를 KST 자정으로 해석 -> UTC aware (신선도 §5.7 의존).
        published_at = (
            datetime.strptime(rcept_dt, "%Y%m%d").replace(tzinfo=_KST).astimezone(timezone.utc)
        )
    return NormalizedDoc(
        source="opendart",
        external_id=rcept_no,
        published_at=published_at,
        title=f"{report_nm} ({corp_name})",
        summary=report_nm,
        body=body,  # 공시 본문 — P5 합법 grounding
        url=_VIEWER_URL.format(rcept_no=rcept_no),
        lang="ko",
        raw_payload=meta,
    )


class OpenDartDocsConnector(Connector):
    def __init__(
        self,
        *,
        bgn_de: str | None = None,
        end_de: str | None = None,
        page_count: int = 100,
        throttle_s: float = 0.2,
        client: httpx.Client | None = None,
    ) -> None:
        today = _today_kst()
        self.bgn_de = bgn_de or today
        self.end_de = end_de or today
        self.page_count = page_count
        self.throttle_s = throttle_s
        self._client = client

    def _make_client(self) -> httpx.Client:
        # OS 인증서 저장소 신뢰(사내 TLS 가로채기 대응; opendart.py와 동일 패턴).
        ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        return httpx.Client(timeout=30.0, verify=ctx)

    def _get_document_zip(self, http: httpx.Client, rcept_no: str) -> bytes:
        """document.xml ZIP을 받는다. 429/타임아웃에 백오프 재시도(최대 2회)."""
        params = {"crtfc_key": settings.opendart_api_key, "rcept_no": rcept_no}
        for attempt in range(3):  # 최초 1회 + 재시도 2회
            try:
                resp = http.get(_DOCUMENT_URL, params=params)
                if resp.status_code == 429:
                    raise httpx.HTTPStatusError(
                        "429 Too Many Requests", request=resp.request, response=resp
                    )
                resp.raise_for_status()
                # OpenDART는 에러를 HTTP 200 + XML(ZIP 아님)로 준다 → ZIP 매직(PK) 확인.
                # 결정적 에러라 재시도 대상(Timeout/HTTPStatusError)과 분리해 즉시 raise.
                if resp.content[:2] != b"PK":
                    status, message = _parse_document_error(resp.content)
                    raise OpenDartDocsError(
                        f"document.xml status={status} message={message} rcept_no={rcept_no}",
                        status=status,
                    )
                return resp.content
            except (httpx.TimeoutException, httpx.HTTPStatusError):
                if attempt == 2:
                    raise
                # 선형 백오프: throttle_s 기준으로 점증.
                time.sleep(self.throttle_s * (attempt + 1))
        raise OpenDartDocsError(f"document.xml fetch 실패: {rcept_no}")  # pragma: no cover

    def fetch(self) -> Iterable[dict[str, Any]]:
        if not settings.opendart_api_key:
            raise OpenDartDocsError("opendart_api_key 미설정 — OpenDART 공시 본문 수집 불가")
        owns = self._client is None
        http = self._client or self._make_client()
        try:
            resp = http.get(
                _LIST_URL,
                params={
                    "crtfc_key": settings.opendart_api_key,
                    "bgn_de": self.bgn_de,
                    "end_de": self.end_de,
                    "page_count": self.page_count,
                },
            )
            resp.raise_for_status()
            filings = parse_list(resp.json())
            for i, meta in enumerate(filings):
                if i > 0:
                    time.sleep(self.throttle_s)  # document 호출 사이 throttle(§5)
                try:
                    zip_bytes = self._get_document_zip(http, meta["rcept_no"])
                except OpenDartDocsError as exc:
                    # 개별 문서 문제(014=파일 없음)는 그 문서만 스킵하고 나머지 공시는 계속.
                    # 전역 에러(키·한도·점검)는 re-raise해 소스 전체를 멈춘다(원인 표면화).
                    if exc.status in _SKIPPABLE_DOC_STATUSES:
                        logger.warning("opendart document skipped: %s: %s", meta["rcept_no"], exc)
                        continue
                    raise
                body = extract_body_from_zip(zip_bytes)
                yield {"meta": meta, "body": body}
        finally:
            if owns:
                http.close()

    def normalize(self, payload: dict[str, Any]) -> NormalizedDoc:
        return normalize(payload["meta"], payload["body"])

    def upsert(self, doc: NormalizedDoc) -> None:
        """raw_documents 멱등 upsert. (source_id, external_id) 충돌 시 무시.

        공시 본문은 불변이라 이미 적재된 rcept_no는 충돌 무시로 스킵(캐싱/증분).
        """
        with SessionLocal() as session:
            source = session.scalar(select(Source).where(Source.name == doc.source))
            if source is None:
                source = Source(name=doc.source, kind="filing", legal_basis=_LEGAL_BASIS)
                session.add(source)
                session.flush()
            stmt = (
                insert(RawDocument)
                .values(
                    source_id=source.id,
                    external_id=doc.external_id,
                    published_at=doc.published_at,
                    lang=doc.lang,
                    title=doc.title,
                    summary=doc.summary,
                    body=doc.body,
                    url=doc.url,
                    raw_payload=doc.raw_payload,
                )
                .on_conflict_do_nothing(constraint="uq_raw_documents_source_external")
            )
            session.execute(stmt)
            session.commit()
