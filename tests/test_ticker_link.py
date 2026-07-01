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


# --- §6.4 precision 게이트 회귀 (경계검사 + 후보강등) ---


def test_left_hangul_boundary_rejects_substring() -> None:
    # '이닉스'가 "하이닉스"의 접미 substring으로만 등장 → 매치 아님.
    # 한국어 조사는 오른쪽에만 붙으니, 별칭 왼쪽에 한글('하')이 붙으면 더 긴 단어의 일부다.
    dictionary = {"이닉스": [("000660", "KR")]}
    assert resolve("SK하이닉스 3분기 최대 실적", dictionary) == []


def test_left_boundary_rejects_english_substring() -> None:
    # 'ge'가 "exchange"의 substring으로 걸리면 안 된다(왼쪽 'n'이 알파벳).
    dictionary = {"ge": [("GE", "US")]}
    assert resolve("Stock exchange rally", dictionary) == []


def test_short_alias_demoted_to_candidate() -> None:
    # 2자 별칭은 경계를 통과해도 짧아서 중의적 → 단정 금지(is_candidate=True).
    dictionary = {"sk": [("003600", "KR")]}
    assert resolve("SK, 3분기 실적 발표", dictionary) == [
        TickerLink(ticker="003600", market="KR", is_candidate=True)
    ]


def test_short_common_word_alias_demoted() -> None:
    # '현대'는 보통명사('현대적')와 충돌. 문두 경계는 통과하지만 2자라 후보로 강등.
    dictionary = {"현대": [("005380", "KR")]}
    assert resolve("현대적인 감각의 신제품", dictionary) == [
        TickerLink(ticker="005380", market="KR", is_candidate=True)
    ]


def test_standalone_korean_alias_stays_confident() -> None:
    # 경계(공백)에서 시작하는 3자+ 별칭은 조사가 붙어도 confident 유지(과잉강등 방지).
    dictionary = {"삼성전자": [("005930", "KR")]}
    assert resolve("오늘 삼성전자는 신고가", dictionary) == [
        TickerLink(ticker="005930", market="KR", is_candidate=False)
    ]
