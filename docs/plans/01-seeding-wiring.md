# 01 — 종목 유니버스 시딩 배선 (blocker 1·2·4)

## Context
완성도 감사 결과, 핵심 루프의 코드는 구현됐으나 **종목 별칭 사전(`security_aliases`)과 커버리지(`coverage`)가 비어 있어** `ticker_link`가 영구 0건 → **"영향 큰 종목 추천"이라는 산출물이 나오지 않는다.** 세 시더(`sec`/`opendart`/`coingecko`)는 멱등 `sync()`로 이미 구현돼 있으나 각자 `__main__`으로만 호출되고 `run_daily`에 배선돼 있지 않다. 이 문서는 시딩을 일일 실행에 멱등 배선하고 coverage 최소 시드를 넣어 추천을 0→실제로 전환한다. blocker 4(openfigi/coingecko 정규화 도달 불가)는 별칭이 차면 자동 해소된다.

근거(탐색 확인):
- `app/pipeline/sec.py:79` `sync(session, *, client=None) -> int` — `SecurityAlias`((alias,ticker,market) 복합 PK)에 `ON CONFLICT DO NOTHING + RETURNING`. **`sec_edgar_user_agent` 미설정 시 ValueError.**
- `app/pipeline/opendart.py:78` 동일 시그니처 — corpcode→`SecurityAlias`(market="KR"). **`opendart_api_key` 미설정 시 ValueError.**
- `app/pipeline/coingecko.py:88` 동일 — `_UNIVERSE` 8종→`SecurityAlias`(market="CRYPTO"). **키 선택(없어도 동작).**
- `app/runner.py:73` `build_default_connectors()`가 `load_coverage_queries(session)`로 naver 쿼리 도출 → coverage 비면 naver no-op.
- `app/runner.py:176` `run_daily()`: 전용 연결 advisory lock(`_DAILY_LOCK_KEY`) → `_collect` → `run_pipeline` → `build_digest`.
- `app/pipeline/pipeline.py:169` `load_aliases()` → `dict[alias.lower(), list[(ticker,market)]]`을 `ticker_link`에 공급.
- `Coverage`(models.py:134): `id PK, analyst_id, ticker?, sector?, market` — **unique 제약·cik 컬럼 없음.**

## 변경

### 1. `app/pipeline/seed.py` (신규)
유니버스 시딩을 한 곳에 모은다.
- `seed_aliases(session) -> dict[str, int]`: `sec.sync`·`opendart.sync`·`coingecko.sync`를 **각각 try/except로 격리** 호출. 키 없음/`ValueError`/네트워크 예외는 `logger.warning` 후 0으로 skip(소스 격리). 소스명→신규 적재 수 dict 반환.
- `STARTER_COVERAGE: list[dict]` + `seed_coverage(session) -> int`: **coverage 행이 0개일 때만** 대표 KR 섹터/종목 소량 삽입(예: sector `반도체`·`2차전지`·`금융` + ticker `005930`/`000660`, market `KR`). unique 제약이 없으므로 "비었을 때만 삽입"으로 멱등(마이그레이션 회피). 이미 있으면 0 반환. 행 내용 주석에 **"운영자 편집 대상"** 명시.

### 2. `app/runner.py` (배선)
`run_daily` 안에서 advisory lock 획득 직후·`build_default_connectors()` 호출 **이전**에 `seed_aliases`+`seed_coverage`를 실행한다. 같은 실행에서 naver 쿼리가 시드된 coverage를 보도록 `if connectors is None: connectors = build_default_connectors()` 블록을 **lock 안·시딩 뒤로 이동**한다. 결과는 `AuditLog(action="seed")` 1행 + `logger`로 기록(소스헬스 패널의 수집 sources 목록과는 분리). httpx 로깅 WARNING 억제는 기존 유지(`runner.py:191`, opendart crtfc_key 노출 방지).

### 3. (메모) 일일 부하
매일 대용량 목록 다운로드(SEC ~10k·OpenDART corpcode ~100k·CoinGecko list) 부담 → 별칭 시딩을 "별칭 테이블 비었거나 N일 경과 시에만" 실행하는 리프레시 가드로 추후 최적화. 1차는 단순 매일 멱등.

## 영향 파일
- `app/pipeline/seed.py` (신규)
- `app/runner.py` (시딩 배선 + 커넥터 빌드 순서)
- `tests/test_seed.py` (신규)
- `tests/test_runner.py` (시딩 step 반영)

## 검증
- 단위: fake client로 `seed_aliases`가 세 시더 호출·키 없음 graceful skip 검증; `seed_coverage` 빈 테이블→N행, 재실행→0행(멱등).
- e2e(실 DB): `uv run python -m app.runner --date <오늘>` 후 `security_aliases`>0, `coverage`>0, 알려진 기업명이 든 브리프에 `brief_item_tickers`>0 확인.
- `uv run pytest tests/test_seed.py tests/test_runner.py` + `ruff` + `mypy` 그린.

## 스코프 밖
EDGAR CIK 배선(blocker 3)은 별도(`coverage.cik` 컬럼 마이그레이션 + SEC UA 키 필요). 본 문서는 별칭 시딩만.
