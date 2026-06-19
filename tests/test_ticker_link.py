from app.pipeline.ticker_link import TickerLink, resolve


def test_resolves_exact_dictionary_hit() -> None:
    dictionary = {"apple": [("AAPL", "US")]}
    assert resolve("Apple beats earnings", dictionary) == [
        TickerLink(ticker="AAPL", market="US", is_candidate=False)
    ]


def test_ambiguous_alias_marked_candidate() -> None:
    # 한 별칭이 두 종목으로 가면 단정 금지 → 둘 다 후보(§6.4).
    dictionary = {"sk": [("000660", "KR"), ("034730", "KR")]}
    links = resolve("SK 관련 뉴스", dictionary)
    assert {link.ticker for link in links} == {"000660", "034730"}
    assert all(link.is_candidate for link in links)


def test_no_match_returns_empty() -> None:
    assert resolve("무관한 헤드라인", {"apple": [("AAPL", "US")]}) == []


def test_substring_match_handles_korean_particle() -> None:
    # "테슬라가"의 조사 '가'가 붙어도 부분문자열 포함으로 잡힌다.
    dictionary = {"테슬라": [("TSLA", "US")]}
    assert resolve("오늘 테슬라가 급등", dictionary) == [
        TickerLink(ticker="TSLA", market="US", is_candidate=False)
    ]


def test_normalizer_confirms_ticker() -> None:
    # 정규화기가 표준 티커를 돌려주면 그 값을 쓴다(확인됨, 후보 아님).
    dictionary = {"apple": [("aapl", "US")]}
    links = resolve("Apple news", dictionary, normalizer=lambda t, m: t.upper())
    assert links == [TickerLink(ticker="AAPL", market="US", is_candidate=False)]


def test_normalizer_failure_marks_candidate() -> None:
    # 정규화 확인 실패(None) → 보류.
    dictionary = {"apple": [("AAPL", "US")]}
    links = resolve("Apple news", dictionary, normalizer=lambda t, m: None)
    assert links == [TickerLink(ticker="AAPL", market="US", is_candidate=True)]


def test_crypto_skips_normalizer() -> None:
    # CRYPTO는 OpenFIGI 비대상 → normalizer 호출 안 됨, 사전 티커 유지.
    def boom(ticker: str, market: str) -> str | None:
        raise AssertionError("CRYPTO는 정규화기를 부르면 안 된다")

    dictionary = {"bitcoin": [("BTC", "CRYPTO")]}
    assert resolve("Bitcoin tops $100K", dictionary, normalizer=boom) == [
        TickerLink(ticker="BTC", market="CRYPTO", is_candidate=False)
    ]
