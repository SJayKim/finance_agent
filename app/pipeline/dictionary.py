"""티커 사전 로더 (STAGE1_DESIGN §6.4 / §2 설정·플러그인 경계).

유니버스를 소스에 하드코딩하지 않는다(§2). 사전은 운영자가 주는 CSV(설정 경로
`settings.ticker_dictionary_path`)에서만 적재한다. 경로 미설정 → 빈 사전(링크 0건)으로
§2 "빈 채로 둔다"를 그대로 따른다. 즉 이 모듈은 유니버스를 담지 않고, 주입 메커니즘만 준다.

포맷: 헤더가 정확히 `alias,ticker,market`인 UTF-8 CSV. market은 KR|US|CRYPTO만 허용.
같은 별칭(소문자 기준)이 여러 종목으로 가면 중의적 → resolve가 is_candidate로 흡수한다(§6.4).
"""

from __future__ import annotations

import csv
from pathlib import Path

_VALID_MARKETS = {"KR", "US", "CRYPTO"}


def load_dictionary(path: str | None) -> dict[str, list[tuple[str, str]]]:
    """CSV(alias,ticker,market) → {별칭(소문자): [(ticker, market), ...]}.

    경로 None → 빈 사전(링크 0건, §2). 별칭은 소문자로 정규화해 그룹핑한다
    (대소문자 변형·중의어 병합 — resolve의 별칭=소문자 계약과 일치). 같은 별칭 안의
    (ticker, market) 중복은 1회로 접는다(거짓 중의성 방지: resolve는 len>1을 중의로 본다).
    빈 줄은 건너뛰고, market이 KR/US/CRYPTO가 아니거나 alias/ticker가 비면 오타로 보고
    ValueError를 던진다(§10: 유니버스 결함을 조용히 삼키지 않는다).
    """
    if path is None:
        return {}
    dictionary: dict[str, list[tuple[str, str]]] = {}
    required = {"alias", "ticker", "market"}
    with Path(path).open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise ValueError(
                f"ticker dictionary {path}: 헤더는 정확히 alias,ticker,market 여야 함 "
                f"(got {reader.fieldnames})"
            )
        for lineno, row in enumerate(reader, start=2):  # 2 = 헤더 다음 행
            alias = (row.get("alias") or "").strip()
            ticker = (row.get("ticker") or "").strip()
            market = (row.get("market") or "").strip().upper()
            if not alias and not ticker and not market:
                continue  # 빈 줄
            if not alias or not ticker:
                raise ValueError(f"ticker dictionary {path}:{lineno}: alias/ticker 비어 있음")
            if market not in _VALID_MARKETS:
                raise ValueError(
                    f"ticker dictionary {path}:{lineno}: market '{market}' 미허용 (KR|US|CRYPTO)"
                )
            mappings = dictionary.setdefault(alias.lower(), [])
            pair = (ticker, market)
            if pair not in mappings:
                mappings.append(pair)
    return dictionary
