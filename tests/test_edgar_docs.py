import json
from datetime import timezone

import httpx
import pytest

from app.collector.edgar_docs import (
    DEFAULT_FORMS,
    EdgarDocsConnector,
    EdgarDocsError,
    extract_text_from_html,
    normalize,
    parse_submissions,
)
from app.config import settings

# submissions JSON: filings.recent PARALLEL ARRAYS. 8-K · 10-Q + 필터아웃되는 폼 "4".
_SAMPLE_SUBMISSIONS = json.dumps(
    {
        "cik": 320193,
        "name": "Apple Inc.",
        "filings": {
            "recent": {
                "accessionNumber": [
                    "0000320193-26-000010",
                    "0000320193-26-000011",
                    "0000320193-26-000012",
                ],
                "form": ["8-K", "4", "10-Q"],
                "filingDate": ["2026-06-20", "2026-06-19", "2026-06-15"],
                "primaryDocument": ["aapl-8k.htm", "form4.xml", "aapl-10q.htm"],
                "reportDate": ["2026-06-20", "2026-06-19", "2026-03-31"],
            }
        },
    }
).encode("utf-8")

_SAMPLE_HTML = (
    "<html><head><style>.x{color:red}</style>"
    "<script>var a=1;</script></head><body>"
    "<p>Item 2.02 Results of Operations.</p>"
    "<div>Net sales were &amp; up.</div></body></html>"
)


def test_parse_submissions_filters_forms_and_builds_url() -> None:
    filings = parse_submissions(json.loads(_SAMPLE_SUBMISSIONS), DEFAULT_FORMS)
    assert [f["form"] for f in filings] == ["8-K", "10-Q"]  # "4" 필터아웃
    eight_k = filings[0]
    assert eight_k["external_id"] == "0000320193-26-000010"
    # accession 대시 제거 폴더 + cik 정수 + primaryDocument.
    assert eight_k["url"] == (
        "https://www.sec.gov/Archives/edgar/data/320193/000032019326000010/aapl-8k.htm"
    )
    assert eight_k["company"] == "Apple Inc."


def test_extract_text_from_html_strips_tags() -> None:
    text = extract_text_from_html(_SAMPLE_HTML)
    assert "Item 2.02 Results of Operations." in text
    assert "Net sales were & up." in text  # 엔티티 복원
    assert "<" not in text and ">" not in text  # 태그 제거
    assert "var a=1" not in text  # script 제거
    assert "color:red" not in text  # style 제거


def test_normalize_fills_body_and_en_lang() -> None:
    meta = parse_submissions(json.loads(_SAMPLE_SUBMISSIONS), DEFAULT_FORMS)[0]
    doc = normalize(meta, "Item 2.02 Results of Operations.")
    assert doc.body  # 본문 비어있지 않음(grounding 합법)
    assert doc.lang == "en"
    assert doc.external_id == "0000320193-26-000010"
    assert doc.source == "sec_edgar"
    assert doc.published_at is not None
    assert doc.published_at.tzinfo is not None  # tz-aware
    assert doc.published_at.utcoffset() == timezone.utc.utcoffset(None)  # UTC
    assert doc.title == "8-K — Apple Inc. (2026-06-20)"


def test_fetch_sends_user_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "sec_edgar_user_agent", "finance-agent test@example.com")
    seen_uas: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_uas.append(request.headers.get("User-Agent"))
        if "submissions" in str(request.url):
            return httpx.Response(200, content=_SAMPLE_SUBMISSIONS)
        return httpx.Response(200, text=_SAMPLE_HTML)

    transport = httpx.MockTransport(handler)
    with httpx.Client(
        transport=transport, headers={"User-Agent": "finance-agent test@example.com"}
    ) as client:
        conn = EdgarDocsConnector(["320193"], throttle_s=0.0, client=client)
        payloads = list(conn.fetch())

    # submissions 1건 + 문서 2건(8-K·10-Q) 요청 모두 UA 동반.
    assert len(seen_uas) == 3
    assert all(ua == "finance-agent test@example.com" for ua in seen_uas)
    assert all(ua for ua in seen_uas)  # 비어있지 않음
    assert len(payloads) == 2
    doc = conn.normalize(payloads[0])
    assert "Results of Operations" in (doc.body or "")


def test_fetch_missing_user_agent_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "sec_edgar_user_agent", None)
    conn = EdgarDocsConnector(["320193"], throttle_s=0.0)
    with pytest.raises(EdgarDocsError):
        list(conn.fetch())
