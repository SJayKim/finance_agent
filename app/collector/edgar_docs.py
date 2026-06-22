"""SEC EDGAR filing 본문 커넥터 (STAGE1.5_DESIGN §4 Track A, §표 collector/edgar_docs.py).

SEC가 공개하는 per-company submissions JSON(`data.sec.gov/submissions/CIK{10}.json`)에서
최근 공시 목록을 받아 8-K/10-Q 본문 문서(HTML)를 가져와 텍스트로 푼다. 공개 법정공시라
본문 grounding이 합법(P5) — RSS와 달리 body를 채운다. SEC fair-access 정책상 식별용
User-Agent가 매 요청 필수(§5.3, sec.py 패턴 재사용) — 없으면 호출 거부. ≤10 req/s 한도를
지키려 요청 사이 짧은 throttle + 429 백오프. 사내 TLS 가로채기 대비 truststore로 OS
인증서 신뢰(CLAUDE.md gotcha). parse_submissions/extract_text_from_html/normalize는 순수
함수(네트워크·DB 없이 테스트 가능), fetch/upsert만 I/O.
"""

from __future__ import annotations

import html
import re
import ssl
import time
from collections.abc import Iterable
from datetime import date, datetime, timezone
from typing import Any

import httpx
import truststore
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.collector.base import Connector, NormalizedDoc
from app.config import settings
from app.db import SessionLocal
from app.models import RawDocument, Source

# §표: 8-K/10-Q 우선. set으로 두어 커넥터 생성 시 교체 가능.
DEFAULT_FORMS: set[str] = {"8-K", "10-Q"}

_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik10}.json"
_DOC_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{primary}"
_SOURCE_NAME = "sec_edgar"
_LEGAL_BASIS = "SEC EDGAR filing 본문 — 공개 법정공시(본문 grounding 합법, fair-access UA 준수)"

_SCRIPT_STYLE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t\r\f\v]+")
_BLANKLINES = re.compile(r"\n\s*\n\s*\n+")


class EdgarDocsError(RuntimeError):
    """SEC EDGAR가 JSON/문서 대신 에러 페이지(차단 등)를 주거나 UA 미설정."""


def parse_submissions(payload_json: dict[str, Any], forms: set[str]) -> list[dict[str, Any]]:
    """submissions JSON -> 폼 필터된 per-filing meta dict 리스트 (순수).

    `filings.recent`는 PARALLEL ARRAYS(accessionNumber[]·form[]·filingDate[]·
    primaryDocument[]·reportDate[])라 인덱스로 zip한다. forms에 든 폼만 남기고
    본문 문서 URL을 빌드한다. accession은 폴더용으로 대시 제거.
    """
    recent = payload_json.get("filings", {}).get("recent", {})
    accessions = recent.get("accessionNumber", [])
    form_list = recent.get("form", [])
    filing_dates = recent.get("filingDate", [])
    primaries = recent.get("primaryDocument", [])
    report_dates = recent.get("reportDate", [])

    cik_raw = payload_json.get("cik")
    cik_int = int(cik_raw) if cik_raw is not None else None
    company = (payload_json.get("name") or "").strip()

    out: list[dict[str, Any]] = []
    for i, form in enumerate(form_list):
        if form not in forms:
            continue
        accession = accessions[i] if i < len(accessions) else None
        primary = primaries[i] if i < len(primaries) else None
        if not accession or not primary or cik_int is None:
            continue
        accession_nodashes = accession.replace("-", "")
        url = _DOC_URL.format(cik=cik_int, accession=accession_nodashes, primary=primary)
        out.append(
            {
                "source": _SOURCE_NAME,
                "external_id": accession,
                "form": form,
                "cik": cik_int,
                "company": company or str(cik_int),
                "filing_date": filing_dates[i] if i < len(filing_dates) else None,
                "report_date": report_dates[i] if i < len(report_dates) else None,
                "primary_document": primary,
                "url": url,
            }
        )
    return out


def extract_text_from_html(html_text: str) -> str:
    """공시 HTML -> 읽을 수 있는 텍스트 (순수). script/style 제거 후 태그 제거·엔티티 복원."""
    no_scripts = _SCRIPT_STYLE.sub(" ", html_text)
    # 블록 경계를 개행으로 보존(태그가 통째로 한 줄로 뭉치는 것 방지).
    spaced = re.sub(r"<(br|/p|/div|/tr|/h[1-6]|/li)\b[^>]*>", "\n", no_scripts, flags=re.IGNORECASE)
    no_tags = _TAG.sub("", spaced)
    text = html.unescape(no_tags)
    text = _WS.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    text = _BLANKLINES.sub("\n\n", text)
    return text.strip()


def _published_at(filing_date: str | None) -> datetime | None:
    """filingDate(YYYY-MM-DD) -> 자정 UTC tz-aware. SEC는 US/Eastern 제출일이나
    자정 UTC 근사 허용(설계 §문서화). 파싱 실패 시 None."""
    if not filing_date:
        return None
    try:
        d = date.fromisoformat(filing_date)
    except ValueError:
        return None
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def normalize(meta: dict[str, Any], body: str) -> NormalizedDoc:
    """per-filing meta + 본문 텍스트 -> NormalizedDoc (순수)."""
    form = meta["form"]
    title = f"{form} — {meta['company']} ({meta.get('filing_date')})"
    return NormalizedDoc(
        source=_SOURCE_NAME,
        external_id=meta["external_id"],
        published_at=_published_at(meta.get("filing_date")),
        title=title,
        summary=f"{form} filing",
        body=body,  # P5: 공개 법정공시 본문 — grounding 합법
        url=meta.get("url"),
        lang="en",
        raw_payload=meta,
    )


def _client() -> httpx.Client:
    # OS 인증서 저장소 신뢰(사내 TLS 가로채기 대응; sec.py와 동일 패턴).
    ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    headers = {"User-Agent": settings.sec_edgar_user_agent or ""}
    return httpx.Client(timeout=30.0, follow_redirects=True, verify=ctx, headers=headers)


class EdgarDocsConnector(Connector):
    def __init__(
        self,
        ciks: list[str],
        *,
        forms: set[str] | None = None,
        throttle_s: float = 0.15,
        client: httpx.Client | None = None,
    ) -> None:
        self.ciks = ciks
        self.forms = forms if forms is not None else set(DEFAULT_FORMS)
        self.throttle_s = throttle_s
        self._client = client

    def _get(self, http: httpx.Client, url: str) -> httpx.Response:
        """throttle + 429 백오프(≤10 req/s, fair-access)."""
        backoff = 1.0
        for attempt in range(4):
            if self.throttle_s:
                time.sleep(self.throttle_s)
            resp = http.get(url)
            if resp.status_code == 429 and attempt < 3:
                time.sleep(backoff)
                backoff *= 2
                continue
            resp.raise_for_status()
            return resp
        resp.raise_for_status()
        return resp

    def fetch(self) -> Iterable[dict[str, Any]]:
        if not settings.sec_edgar_user_agent:
            raise EdgarDocsError("sec_edgar_user_agent 미설정 — SEC 접근에 식별 UA 필수(§5.3)")
        owns = self._client is None
        http = self._client or _client()
        try:
            for cik in self.ciks:
                cik10 = str(cik).lstrip("CIK").strip().zfill(10)
                sub_url = _SUBMISSIONS_URL.format(cik10=cik10)
                resp = self._get(http, sub_url)
                try:
                    payload_json = resp.json()
                except ValueError as exc:
                    raise EdgarDocsError(
                        resp.text[:200] if resp.text else "submissions JSON 파싱 실패"
                    ) from exc
                for meta in parse_submissions(payload_json, self.forms):
                    doc_resp = self._get(http, meta["url"])
                    body = extract_text_from_html(doc_resp.text)
                    yield {"meta": meta, "body": body}
        finally:
            if owns:
                http.close()

    def normalize(self, payload: dict[str, Any]) -> NormalizedDoc:
        return normalize(payload["meta"], payload["body"])

    def upsert(self, doc: NormalizedDoc) -> None:
        """raw_documents 멱등 upsert. (source_id, external_id) 충돌 시 무시. body 포함."""
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
