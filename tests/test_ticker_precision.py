"""티커 링킹 precision 게이트 (STAGE1_DESIGN §6.4 / plan 04).

수기 라벨셋으로 resolve()의 confident 링크(is_candidate=False)에 대한 precision을 측정해
≥0.95를 단언한다. §6.4 규칙: 모호/미확인 매치는 is_candidate=True(후보)로 빠지므로
precision은 '단정한 링크 중 맞은 비율'이다(오귀속이 추적성 신뢰를 깸). 스타터 게이트 —
라벨은 확장 대상이다. 실측치를 로그로 남긴다. 순수 단위테스트(네트워크·DB 불필요).
"""

from __future__ import annotations

from app.pipeline.ticker_link import resolve

# 별칭(소문자 매칭) → [(ticker, market)]. 'SK'는 의도적 중의 별칭(여러 종목) — confident에서
# 빠지는지(후보 처리) 검증용. 단일 매핑 별칭은 confident로 잡혀야 한다.
DICTIONARY: dict[str, list[tuple[str, str]]] = {
    "삼성전자": [("005930", "KR")],
    "SK하이닉스": [("000660", "KR")],
    "LG에너지솔루션": [("373220", "KR")],
    "현대차": [("005380", "KR")],
    "테슬라": [("TSLA", "US")],
    "apple": [("AAPL", "US")],
    "nvidia": [("NVDA", "US")],
    "microsoft": [("MSFT", "US")],
    "bitcoin": [("BTC", "CRYPTO")],
    "ethereum": [("ETH", "CRYPTO")],
    "SK": [("000660", "KR"), ("034730", "KR")],  # 중의 → 모두 후보(precision 분모서 제외)
}

# (텍스트, 기대 confident (ticker, market) 집합). 빈 집합 = confident 링크가 없어야 함.
LABELS: list[tuple[str, set[tuple[str, str]]]] = [
    ("삼성전자가 4분기 메모리 실적을 발표했다", {("005930", "KR")}),
    ("SK하이닉스 HBM 수요가 급증했다", {("000660", "KR")}),
    ("LG에너지솔루션 북미 증설 발표", {("373220", "KR")}),
    ("현대차 미국 판매 호조", {("005380", "KR")}),
    ("테슬라 주가가 급등했다", {("TSLA", "US")}),
    ("Apple unveils a new iPhone", {("AAPL", "US")}),
    ("Nvidia data center revenue jumps", {("NVDA", "US")}),
    ("Microsoft raises cloud guidance", {("MSFT", "US")}),
    ("Bitcoin tops $100K again", {("BTC", "CRYPTO")}),
    ("Ethereum upgrade goes live", {("ETH", "CRYPTO")}),
    ("금리 동결과 환율 변동성 확대", set()),  # 사전 별칭 없음 → confident 0
    ("SK 그룹 지배구조 개편 논의", set()),  # 중의 별칭 'SK'만 → 모두 후보, confident 0
]


def test_ticker_link_precision_meets_gate() -> None:
    """confident 링크 precision ≥ 0.95(스타터 게이트). 실측치 출력."""
    total = 0
    correct = 0
    for text, expected in LABELS:
        confident = {(link.ticker, link.market) for link in resolve(text, DICTIONARY) if not link.is_candidate}
        for pair in confident:
            total += 1
            if pair in expected:
                correct += 1
    precision = correct / total if total else 0.0
    print(f"\n[ticker-link precision] {precision:.3f} ({correct}/{total} confident links correct)")
    assert total >= 10  # 게이트가 공허하게 통과하지 않도록 충분한 confident 표본
    assert precision >= 0.95
