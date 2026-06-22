from pathlib import Path

import pytest

from app.pipeline.dictionary import load_dictionary
from app.pipeline.ticker_link import TickerLink, resolve


def _write_csv(tmp_path: Path, body: str) -> str:
    path = tmp_path / "dict.csv"
    path.write_text(body, encoding="utf-8")
    return str(path)


def test_none_path_returns_empty() -> None:
    # 경로 미설정 → 빈 사전(링크 0건, §2 "빈 채로 둔다").
    assert load_dictionary(None) == {}


def test_loads_single_mapping(tmp_path: Path) -> None:
    path = _write_csv(tmp_path, "alias,ticker,market\napple,AAPL,US\n")
    assert load_dictionary(path) == {"apple": [("AAPL", "US")]}


def test_alias_lowercased_as_key(tmp_path: Path) -> None:
    # 별칭 키는 소문자로 정규화(resolve의 별칭=소문자 계약과 일치).
    path = _write_csv(tmp_path, "alias,ticker,market\nTESLA,TSLA,US\n")
    d = load_dictionary(path)
    assert "tesla" in d and "TESLA" not in d


def test_market_uppercased(tmp_path: Path) -> None:
    path = _write_csv(tmp_path, "alias,ticker,market\napple,AAPL,us\n")
    assert load_dictionary(path) == {"apple": [("AAPL", "US")]}


def test_groups_ambiguous_alias(tmp_path: Path) -> None:
    # 같은 별칭이 두 종목으로 → 리스트 길이 2 → resolve가 둘 다 후보로(§6.4).
    path = _write_csv(tmp_path, "alias,ticker,market\nsk,000660,KR\nsk,034730,KR\n")
    d = load_dictionary(path)
    assert d == {"sk": [("000660", "KR"), ("034730", "KR")]}
    links = resolve("SK 관련 뉴스", d)
    assert {link.ticker for link in links} == {"000660", "034730"}
    assert all(link.is_candidate for link in links)


def test_dedupes_duplicate_pair(tmp_path: Path) -> None:
    # 같은 (ticker, market) 행 중복은 1회로 접어 거짓 중의성(len>1)을 막는다.
    path = _write_csv(tmp_path, "alias,ticker,market\napple,AAPL,US\nApple,AAPL,US\n")
    d = load_dictionary(path)
    assert d == {"apple": [("AAPL", "US")]}
    assert resolve("Apple earnings", d)[0].is_candidate is False


def test_blank_lines_skipped(tmp_path: Path) -> None:
    path = _write_csv(tmp_path, "alias,ticker,market\napple,AAPL,US\n\ntesla,TSLA,US\n")
    assert load_dictionary(path) == {"apple": [("AAPL", "US")], "tesla": [("TSLA", "US")]}


def test_invalid_market_raises(tmp_path: Path) -> None:
    path = _write_csv(tmp_path, "alias,ticker,market\napple,AAPL,XX\n")
    with pytest.raises(ValueError, match="market"):
        load_dictionary(path)


def test_blank_alias_raises(tmp_path: Path) -> None:
    path = _write_csv(tmp_path, "alias,ticker,market\n,AAPL,US\n")
    with pytest.raises(ValueError, match="alias/ticker"):
        load_dictionary(path)


def test_missing_header_raises(tmp_path: Path) -> None:
    path = _write_csv(tmp_path, "name,ticker,market\napple,AAPL,US\n")
    with pytest.raises(ValueError, match="alias,ticker,market"):
        load_dictionary(path)


def test_integration_with_resolve(tmp_path: Path) -> None:
    # 로더 → resolve 끝단까지: 적재한 사전으로 제목에서 티커가 나온다.
    path = _write_csv(tmp_path, "alias,ticker,market\n테슬라,TSLA,US\nbitcoin,BTC,CRYPTO\n")
    d = load_dictionary(path)
    assert resolve("오늘 테슬라가 급등", d) == [
        TickerLink(ticker="TSLA", market="US", is_candidate=False)
    ]
