"""ticker-link 1차 골격 (STAGE1_DESIGN §6.4): 텍스트 → 영향 종목 후보 매핑.

회사명·별칭·티커 사전(§5.6 OpenFIGI가 정규화 백본)으로 텍스트에서 종목을 뽑는다.
설계 핵심 규칙: precision 게이트(≥95%) 미달이면 단정 금지 → is_candidate=True로
"후보" 표기(오귀속이 추적성 신뢰를 깸, §6.4). 그래서 모호한 매치는 버리지 않고
보류로 남긴다. 임베딩·DB 무관(순수 함수). brief_item_tickers 적재는 brief_items가
생기는 영향도 생성 단계(§6.6/§7) 이후라 여기선 다루지 않는다.

경계:
- 사전은 주입 인자다. KR/US/CRYPTO 종목 유니버스를 하드코딩하지 않는다(§2 규칙).
- 정규화기(normalizer)도 주입. 라이브 OpenFIGI 어댑터는 openfigi_normalizer.
- 매칭은 왼쪽 경계 인식(소문자)이다: 별칭 왼쪽에 문자/숫자가 붙으면 더 긴 단어의 일부라
  매치 안 함(§6.4 precision, '이닉스'가 '하이닉스' 안). 한국어 조사는 오른쪽에만 붙어 접미는
  허용. 짧은(≤2자) 별칭과 큐레이션 모호어(_AMBIGUOUS_ALIASES)는 경계를 통과해도 중의성
  위험이 커 is_candidate=True로 강등(단정 금지). 잔여 불확실은 is_candidate가 흡수.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from app.pipeline.openfigi import normalize as _openfigi_normalize

# market → OpenFIGI exchCode. KR=KOSPI(KS); KOSDAQ(KQ)·다중거래소는 §6.4 데이터 작업.
_MARKET_EXCH = {"US": "US", "KR": "KS"}

# 이 길이 이하 별칭은 경계를 통과해도 confident 단정 금지(§6.4). 2자로 잡은 근거:
# 기존 계약이 3자 '테슬라'를 confident로 규정 → 임계는 ≤2. 3자 substring 오탐('이닉스')은
# 길이가 아니라 왼쪽 경계 검사가 잡는다.
_SHORT_ALIAS_LEN = 2

# 큐레이션 모호어 데니리스트(소문자): 상장사 별칭이지만 일상어이기도 해 경계·길이론 못
# 거르는 것. 단정 금지(is_candidate=True)로만 강등하고 버리진 않는다(§6.4 후보). 유니버스가
# 아니라 stopword 성격이라 §2와 무관. 06-26 dry-run에서 '오로라'(039830, 여행 기사 오탐) 발견.
# 새 dry-run이 같은 유형을 드러내면 여기 추가한다.
_AMBIGUOUS_ALIASES = frozenset({"오로라"})


def _alias_occurs(text_lower: str, alias_lower: str) -> bool:
    """별칭이 왼쪽 경계에서 시작하는 출현이 하나라도 있으면 True.

    왼쪽 경계 = 문자열 시작 또는 앞 글자가 문자/숫자가 아님(공백·문장부호 등). 한국어 조사는
    오른쪽에만 붙으므로 왼쪽에 글자가 붙은 출현은 더 긴 단어의 일부다('이닉스'가 '하이닉스' 안).
    오른쪽은 검사 안 함 — 조사·복합어 접미('테슬라가','삼성전자우')를 허용해야 하기 때문.
    """
    idx = text_lower.find(alias_lower)
    while idx != -1:
        if idx == 0 or not text_lower[idx - 1].isalnum():
            return True
        idx = text_lower.find(alias_lower, idx + 1)
    return False


@dataclass(frozen=True)
class TickerLink:
    ticker: str
    market: str  # KR | US | CRYPTO
    is_candidate: bool  # §6.4: 게이트 미달/모호 → 단정 금지(후보 표기)


def resolve(
    text: str,
    dictionary: Mapping[str, list[tuple[str, str]]],
    normalizer: Callable[[str, str], str | None] | None = None,
) -> list[TickerLink]:
    """텍스트에서 사전 별칭을 찾아 TickerLink 목록을 만든다.

    dictionary: 별칭(소문자) → [(ticker, market), ...]. 같은 별칭이 여러 종목으로
    가면 중의적 → is_candidate=True. normalizer 주입 시 KR/US는 표준 티커로 확인:
    None 반환(확인 실패)이면 is_candidate=True로 보류. CRYPTO는 OpenFIGI 비대상이라 건너뛴다.
    """
    lowered = text.lower()
    links: list[TickerLink] = []
    seen: set[tuple[str, str]] = set()
    for alias, mappings in dictionary.items():
        if not _alias_occurs(lowered, alias.lower()):
            continue
        # 짧은 별칭·큐레이션 모호어는 경계를 통과해도 중의성 위험이 커 단정 금지(§6.4).
        short = len(alias) <= _SHORT_ALIAS_LEN
        denylisted = alias.lower() in _AMBIGUOUS_ALIASES
        ambiguous = len(mappings) > 1
        for ticker, market in mappings:
            if (ticker, market) in seen:
                continue
            seen.add((ticker, market))
            is_candidate = ambiguous or short or denylisted
            resolved = ticker
            if normalizer is not None and market in ("KR", "US"):
                std = normalizer(ticker, market)
                if std is None:
                    is_candidate = True  # 정규화 확인 실패 → 보류
                else:
                    resolved = std
            links.append(TickerLink(ticker=resolved, market=market, is_candidate=is_candidate))
    return links


def openfigi_normalizer(ticker: str, market: str) -> str | None:
    """resolve의 normalizer로 쓰는 라이브 OpenFIGI 어댑터. 표준 티커 or None(보류).

    종목마다 클라이언트를 1회용으로 연다. 배치에서 한 클라이언트를 재사용하려면
    openfigi.normalize(..., client=...)로 직접 클로저를 짜라(골격은 단순 우선).
    """
    exch = _MARKET_EXCH.get(market)
    if exch is None:
        return None
    result = _openfigi_normalize("TICKER", ticker, exch)
    return result.ticker if result else None
