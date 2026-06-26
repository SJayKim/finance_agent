import io
import json
import zipfile
from datetime import timezone
from typing import Any

import httpx
import pytest

from app.collector.opendart_docs import (
    OpenDartDocsConnector,
    OpenDartDocsError,
    extract_body_from_zip,
    normalize,
    parse_list,
)
from app.config import settings

_SAMPLE_LIST: dict[str, Any] = {
    "status": "000",
    "message": "정상",
    "list": [
        {
            "rcept_no": "20240101000001",
            "corp_name": "삼성전자",
            "report_nm": "분기보고서",
            "rcept_dt": "20240101",
            "stock_code": "005930",
        },
        {
            "rcept_no": "20240101000002",
            "corp_name": "SK하이닉스",
            "report_nm": "주요사항보고서",
            "rcept_dt": "20240101",
            "stock_code": "000660",
        },
    ],
}
_SAMPLE_LIST_BYTES = json.dumps(_SAMPLE_LIST).encode("utf-8")

_NO_DATA = {"status": "013", "message": "조회된 데이터가 없습니다."}


def _sample_doc_zip(text: str) -> bytes:
    xml = f"<document><body><p>{text}</p></body></document>".encode("utf-8")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("20240101000001.xml", xml)
    return buf.getvalue()


def test_parse_list_extracts_filings() -> None:
    filings = parse_list(_SAMPLE_LIST)
    assert len(filings) == 2
    assert filings[0]["rcept_no"] == "20240101000001"
    assert filings[1]["corp_name"] == "SK하이닉스"


def test_parse_list_no_data_returns_empty() -> None:
    assert parse_list(_NO_DATA) == []


def test_parse_list_error_status_raises() -> None:
    with pytest.raises(OpenDartDocsError):
        parse_list({"status": "020", "message": "사용한도 초과"})


def test_extract_body_from_zip_strips_xml() -> None:
    body = extract_body_from_zip(_sample_doc_zip("당기 매출액은 전년 대비 증가하였습니다."))
    assert "당기 매출액은 전년 대비 증가하였습니다." in body
    assert "<" not in body
    assert ">" not in body


def test_normalize_fills_body_and_ko_lang() -> None:
    meta = _SAMPLE_LIST["list"][0]
    doc = normalize(meta, "본문 텍스트")
    assert doc.body == "본문 텍스트"
    assert doc.lang == "ko"
    assert doc.external_id == "20240101000001"
    assert doc.published_at is not None
    assert doc.published_at.tzinfo == timezone.utc
    assert doc.title == "분기보고서 (삼성전자)"
    assert doc.url == "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20240101000001"


def test_fetch_sends_key_and_parses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "opendart_api_key", "test-key")
    seen: dict[str, set[str]] = {"list_keys": set(), "doc_keys": set(), "rcept": set()}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("list.json"):
            seen["list_keys"].add(request.url.params.get("crtfc_key"))
            return httpx.Response(200, content=_SAMPLE_LIST_BYTES)
        # document.xml
        seen["doc_keys"].add(request.url.params.get("crtfc_key"))
        seen["rcept"].add(request.url.params.get("rcept_no"))
        return httpx.Response(200, content=_sample_doc_zip("본문"))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        connector = OpenDartDocsConnector(throttle_s=0.0, client=client)
        payloads = list(connector.fetch())

    assert seen["list_keys"] == {"test-key"}
    assert seen["doc_keys"] == {"test-key"}  # 키가 list와 document 양쪽에 모두 전송됨
    assert seen["rcept"] == {"20240101000001", "20240101000002"}
    assert len(payloads) == 2
    assert payloads[0]["meta"]["rcept_no"] == "20240101000001"
    assert "본문" in payloads[0]["body"]


_DOC_NO_FILE = (
    b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    b"<result><status>014</status><message>file</message></result>"
)


def test_fetch_skips_filings_without_original_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """document.xml이 ZIP 대신 XML 에러(status 014)면 그 공시만 건너뛰고 소스는 계속(BadZipFile 회귀)."""
    monkeypatch.setattr(settings, "opendart_api_key", "test-key")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("list.json"):
            return httpx.Response(200, content=_SAMPLE_LIST_BYTES)
        # 첫 공시는 원본파일 없음(014), 둘째는 정상 ZIP
        if request.url.params.get("rcept_no") == "20240101000001":
            return httpx.Response(200, content=_DOC_NO_FILE)
        return httpx.Response(200, content=_sample_doc_zip("본문"))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        connector = OpenDartDocsConnector(throttle_s=0.0, client=client)
        payloads = list(connector.fetch())

    assert len(payloads) == 1  # 014는 건너뛰고 ZIP 1건만
    assert payloads[0]["meta"]["rcept_no"] == "20240101000002"
    assert "본문" in payloads[0]["body"]


def test_fetch_missing_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "opendart_api_key", None)
    connector = OpenDartDocsConnector()
    with pytest.raises(OpenDartDocsError):
        list(connector.fetch())
