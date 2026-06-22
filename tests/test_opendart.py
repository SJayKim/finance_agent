import io
import zipfile

import httpx
import pytest

from app.config import settings
from app.pipeline.opendart import OpenDARTError, _parse_corpcode_zip, fetch_corp_codes

_SAMPLE_XML = (
    "<result>"
    "<list><corp_code>00126380</corp_code><corp_name>삼성전자</corp_name>"
    "<stock_code>005930</stock_code><modify_date>20240101</modify_date></list>"
    "<list><corp_code>00164779</corp_code><corp_name>SK하이닉스</corp_name>"
    "<stock_code>000660</stock_code><modify_date>20240101</modify_date></list>"
    "<list><corp_code>00999999</corp_code><corp_name>비상장유한회사</corp_name>"
    "<stock_code> </stock_code><modify_date>20240101</modify_date></list>"
    "</result>"
)


def _sample_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("CORPCODE.xml", _SAMPLE_XML.encode("utf-8"))
    return buf.getvalue()


def test_parse_filters_unlisted() -> None:
    pairs = _parse_corpcode_zip(_sample_zip())
    assert pairs == [("삼성전자", "005930"), ("SK하이닉스", "000660")]


def test_fetch_corp_codes_sends_key_and_parses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "opendart_api_key", "test-key")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["key"] = request.url.params.get("crtfc_key")
        return httpx.Response(200, content=_sample_zip())

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        pairs = fetch_corp_codes(client=client)

    assert seen["key"] == "test-key"
    assert pairs == [("삼성전자", "005930"), ("SK하이닉스", "000660")]


def test_fetch_corp_codes_no_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "opendart_api_key", None)
    with pytest.raises(ValueError):
        fetch_corp_codes()


def test_fetch_corp_codes_error_xml_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """ZIP 아닌 에러 XML(키 무효) -> OpenDARTError."""
    monkeypatch.setattr(settings, "opendart_api_key", "bad-key")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"<result><status>013</status><message>no data</message></result>",
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(OpenDARTError):
            fetch_corp_codes(client=client)
