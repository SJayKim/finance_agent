---
status: in-progress
branch: main
timestamp: 2026-06-19T15:18:40+09:00
prev_checkpoint: ~/.gstack/projects/SJayKim-finance_agent/checkpoints/20260619-134805-stage1-ticker-link-committed-openfigi-live-smoke-passed.md
files_modified:
  - app/pipeline/pipeline.py  # generate_impact + ticker_link 배선, run_pipeline 확장 (미커밋)
---

## Working on: Stage 1 #3 — generate_impact(골격) + ticker_link 배선 완료, 미커밋

### Summary

이번 세션은 /context-restore(134805)로 복귀 → **#3 파이프라인 전진 (honest-empty 골격 +
ticker_link 배선)** 를 구현 완료했다. `app/pipeline/pipeline.py` 단일 파일 수정,
실DB 스모크(ankane/pgvector 에피머럴 컨테이너) 포함 모든 게이트 통과. **미커밋 상태.**

### Decisions Made

- **honest-empty 골격(범위 선택):** §6.3 cluster(임베딩 미정·§11.3) / §6.5 event-classify
  (STAGE0-BLOCKED) / §7 Citations 분석(미구현) 등 막힌 게이트 3개를 건너뛰고,
  `generate_impact`가 brief_items를 `status='empty'` / 분석필드 NULL로 생성하는 정직한
  빈 골격을 선택. §10 null-evidence 설계(근거 없으면 환각으로 채우지 않는다)와 일치.
- **run_pipeline 실행 순서 역전(설계 필요):** 설계 §6 순서는 ticker-link 먼저이나,
  `brief_item_tickers`가 `brief_items` FK라 `generate_impact`를 앞에 둔다. 주석으로 명시.
- **사전 주입 인자(유니버스 하드코딩 없음):** `run_pipeline(brief_date, dictionary=None)`.
  빈 dict 기본값 → 링크 0건, 유니버스 하드코딩 금지(§2 규칙).
- **link_precision=NULL(의도):** §6.4 실측 전이라 NULL로 두고, 게이트 측정은 후속 작업.
- **워킹트리에 미커밋 상태로 종료:** 사용자가 커밋을 요청하지 않아 unstaged 유지.

### 실DB 스모크 결과 (검증된 사실)

- 에피머럴 `ankane/pgvector` 컨테이너(5433) + alembic upgrade head → 스모크 통과.
- `generate_impact` + `ticker_link` 결과: brief_item 1건 `status='empty'`,
  `analysis_text`/`event_type`=NULL, ticker `(BTC, CRYPTO, is_candidate=False,
  link_precision=None)`.
- 멱등성 재실행(RUN2): items=1, tickers=1 유지 — `not_in` 서브쿼리 정상 작동.
- `run_pipeline` end-to-end(빈 dict): 오류 없음.
- 게이트 전부 그린: `ruff check` ✓ / `ruff format --check`(22) ✓ / `mypy`(22) ✓ /
  `pytest -q` **25 passed** (회귀 없음).

### Remaining Work

1. **커밋(즉시 가능):** `app/pipeline/pipeline.py` feat 커밋 → docs 미러 커밋 → 푸시.
   이전 패턴: feat(코드) + docs(체크포인트 미러) 분리.
2. **§6.4 하드닝(이전 체크포인트 #1 열림):** 감사가 짚은 잠재결함 3건 처리:
   - `openfigi.py:87` — 200 응답에 `error` 객체 → `.get("data")`=None → no-match 혼동.
     실 오류를 매치 실패로 오인. MockTransport 사각.
   - `records[0]` 정규성 미보장 (US 복합거래소, 순서 무보장). 명시적 선택 로직 필요.
   - `openfigi.py:47` 10s 타임아웃 — batch에서 `TimeoutException` 전파 처리 필요.
3. **#1 defer 2건 (여전히 열림):** §5.7 freshness 윈도우 필터 + 동시성 가드 (cron/trigger).
4. **파이프라인 다음 단계:** cluster(§6.3, 임베딩 모델 확정 후) → event-classify(§6.5,
   Stage 0 관찰 후) → §7 Citations 2-패스 분석.
5. **사전 주입 실체화:** KR/US 유니버스 별칭 사전을 실 데이터로 채워 run_pipeline에 연결.

### Notes

- **읽기 순서(다음 세션):** `app/pipeline/pipeline.py`(전체 확인) → `openfigi.py:87`
  (error-객체 버그) → `tests/test_openfigi.py`(MockTransport 사각 확인) →
  `docs/STAGE1_DESIGN.md` §6.4 게이트 기준 재확인.
- **변경된 함수/클래스(pipeline.py):**
  - `generate_impact(session, brief_date)` — 신규 구현 (라인 121-131)
  - `ticker_link(session, brief_date, dictionary, normalizer)` — 스텁→구현 (라인 79-105)
  - `_brief_items_without_tickers(session, brief_date)` — 신규 헬퍼 (라인 62-68)
  - `_representative_title(session, cluster_id)` — 신규 헬퍼 (라인 71-76)
  - `_clusters_without_brief_item(session, brief_date)` — 신규 헬퍼 (라인 112-118)
  - `run_pipeline(brief_date, dictionary=None)` — 시그니처 + 배선 변경 (라인 134-149)
- gstack 업그레이드 대기: 1.58.1.0 → 1.58.3.0 (이번 작업 무관).
- 체크포인트는 `~/.gstack` + `docs/context/` 미러링(커밋 시) 패턴 유지.
- Windows uv 출력 파이프 주의: `uv` 출력에 grep -v/head 걸면 git-bash 바이너리 판정으로
  본문 사라짐. 필터 없이 실행할 것 (auto memory에 저장됨).
