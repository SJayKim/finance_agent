---
status: in-progress
branch: main
timestamp: 2026-06-19T13:32:44+09:00
prev_checkpoint: docs/context/20260619-131321-stage1-1-dedup-committed-pushed.md
files_modified:
  - app/config.py          # +1 openfigi_api_key
  - app/pipeline/openfigi.py    # new — live OpenFIGI /v3/mapping client
  - app/pipeline/ticker_link.py # new — pure resolver + openfigi_normalizer 어댑터
  - tests/test_openfigi.py      # new — 4 tests (MockTransport)
  - tests/test_ticker_link.py   # new — 7 tests
  # docs/context/20260619-131321-*.md 은 직전 증분 미러(미커밋), 이번 작업과 무관
---

## Working on: ticker-link 골격(§6.4) + 라이브 OpenFIGI 클라이언트 — 구현·게이트 그린, 미커밋

### Summary

/context-restore 로 직전 dedup 증분 복귀 → 다음 작업으로 ticker-link 골격(§6.4) 선택.
순수 리졸버 + 라이브 OpenFIGI 정규화 클라이언트 2개 모듈 신규 작성. ruff/format/mypy(22)
/pytest 그린(25 passed, +11 신규). **아직 커밋·푸시 안 함** — 워킹트리에 5개 변경 대기.
실제 OpenFIGI 라이브 호출은 안 했고 테스트는 httpx MockTransport로 결정론적.

### Decisions Made

- **OpenFIGI 범위 = 라이브 클라이언트(사용자 선택):** dictionary-only/run_pipeline 배선 대신
  실 HTTP 클라이언트(`/v3/mapping`)를 이번 증분에 포함. truststore SSLContext(rss.py 동일
  패턴), 선택적 `X-OPENFIGI-APIKEY`, 429→Retry-After 백오프+유한 재시도(max_retries 기본2)
  후 `OpenFIGIRateLimited` raise. `client` 주입 가능 → 테스트가 MockTransport로 네트워크 없이 검증.
- **run_pipeline 배선 안 함(의도):** `pipeline.py:ticker_link()` NotImplementedError 스텁
  그대로 둠(surgical). 출력 타깃 `brief_item_tickers`는 `brief_item_id` FK 필요 →
  brief_items는 영향도 생성 단계(§6.6/§7) 전엔 없음. cluster()와 동일 posture.
- **게이트 = 가드레일로만 구현:** precision≥95%는 라벨셋 대상 시스템 지표지 per-link 수치가
  아님. 그래서 모호 별칭/정규화 실패 → `is_candidate=True`(보류). per-link `link_precision`
  float은 **날조 안 함**(컬럼 null 유지, 실측 전까지).
- **매칭 = 부분문자열 포함(의도적 단순화):** 소문자 substring. 한국어 조사("테슬라가") 통과
  목적. 경계·형태소·중의성 정밀화는 §6.4 게이트 튜닝 작업으로 defer, is_candidate가 흡수.
- **사전·정규화기 둘 다 주입 인자:** KR/US/CRYPTO 유니버스 하드코딩 금지(§2). 라이브
  어댑터 `openfigi_normalizer`는 CRYPTO 건너뜀(OpenFIGI 비대상). _MARKET_EXCH={US:US, KR:KS},
  KOSDAQ(KQ)·다중거래소는 §6.4 데이터 작업으로 표기.

### Remaining Work

1. **커밋·푸시 결정(사용자 대기):** feat(코드 4파일)/docs(컨텍스트 미러) 분리 패턴.
   현재 워킹트리: M app/config.py + 신규 4파일 + 직전 미러 docs 1건(미커밋).
2. **라이브 OpenFIGI 스모크 테스트(선택):** 실제 `normalize("TICKER","AAPL","US")` 1회로
   엔드포인트+truststore E2E 확인. 사내 TLS·무료 한도(25/min) 주의.
3. **§6.4 게이트 정밀화(후속 증분):** 실 사전 데이터 + 라벨셋으로 precision 측정,
   매칭을 substring→경계/형태소 인지로, KOSDAQ exchCode 분기, link_precision 실측 적재.
4. **#1 두 defer 항목(여전히 열림):** §5.7 freshness 윈도우 필터 + 동시성 가드(cron/trigger 배선과 함께).
5. **파이프라인 전진 후보:** brief_items/영향도 생성(§6.6/§7) 골격 → ticker_link run_pipeline 배선 잠금 해제.

### Notes

- **게이트:** `uv run ruff check .` / `ruff format --check .` / `mypy .`(22 files) /
  `pytest -q`(25 passed, 1 warning). 직전 14 → +11(ticker_link 7 + openfigi 4).
- **VIRTUAL_ENV 경고 무해:** crypto_deep_research/.venv가 env에 떠 있어 경고만, uv는
  finance_agent/.venv 정상 사용.
- **신규 모듈 위치:** OpenFIGI는 source 커넥터 아님(raw_documents 비적재) → `app/pipeline/`에
  둠(collector/base.py 계약과 무관). ticker_link → openfigi 단방향 import.
- **테스트 패턴:** OpenFIGI는 httpx.MockTransport(handler)로 요청 body 모양(idType/idValue/
  exchCode)·429 재시도·no-match→None 검증. 네트워크 없음.
- 읽기 순서(다음 세션): `app/pipeline/ticker_link.py`(resolve + 어댑터) →
  `app/pipeline/openfigi.py`(normalize 재시도/파싱) → `docs/STAGE1_DESIGN.md` §6.4·§5.6 →
  `app/pipeline/pipeline.py`(ticker_link 스텁 — 배선 잠금 위치) → `app/models.py`(brief_item_tickers).
- 체크포인트는 `~/.gstack` + `docs/context/` 미러링(커밋 시).
