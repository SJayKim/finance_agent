"""ticker-link 1차 골격 (STAGE1_DESIGN §6.4): 텍스트 → 영향 종목 후보 매핑.

회사명·별칭·티커 사전(§5.6 OpenFIGI가 정규화 백본)으로 텍스트에서 종목을 뽑는다.
설계 핵심 규칙: precision 게이트(≥95%) 미달이면 단정 금지 → is_candidate=True로
"후보" 표기(오귀속이 추적성 신뢰를 깸, §6.4). 그래서 모호한 매치는 버리지 않고
보류로 남긴다. 임베딩·DB 무관(순수 함수). brief_item_tickers 적재는 brief_items가
생기는 영향도 생성 단계(§6.6/§7) 이후라 여기선 다루지 않는다.

경계:
- 사전은 주입 인자다. KR/US/CRYPTO 종목 유니버스를 하드코딩하지 않는다(§2 규칙).
- 정규화기(normalizer)도 주입. 라이브 OpenFIGI 어댑터는 openfigi_normalizer.
- 매칭은 부분문자열 포함(소문자)이다. 경계·형태소(한국어 조사)·중의성 정밀화는
  precision 게이트 튜닝 작업(§6.4)이라 골격에선 다루지 않고, 불확실은 is_candidate가 흡수.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from app.pipeline.openfigi import normalize as _openfigi_normalize

# market → OpenFIGI exchCode. KR=KOSPI(KS); KOSDAQ(KQ)·다중거래소는 §6.4 데이터 작업.
_MARKET_EXCH = {"US": "US", "KR": "KS"}


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
        if alias.lower() not in lowered:
            continue
        ambiguous = len(mappings) > 1
        for ticker, market in mappings:
            if (ticker, market) in seen:
                continue
            seen.add((ticker, market))
            is_candidate = ambiguous
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
