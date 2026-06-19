---
status: in-progress
branch: main
timestamp: 2026-06-19T16:26:57+09:00
session_duration_s: unknown
files_modified: []
---

## Working on: Stage 1 동시성 가드 완료 — 다음: §6.3 cluster·§6.5 event-classify

### Summary

이번 세션에서 §5.7 freshness 필터 커밋(40c835e)과 run_pipeline 동시성 가드(2554842)를 완료하고
main에 푸시했다. 워킹트리는 클린 상태. 다음 구현 대상은 §6.3 cluster(임베딩 모델 확정 선행 필요)와
§6.5 event-classify(Stage 0 관찰 후).

### Decisions Made

- **동시성 가드 전략:** DB Advisory Lock (`pg_try_advisory_lock`) 선택.
  파일락 대비 멀티 인스턴스 안전, 크래시 시 DB 자동 해제, 의존성 추가 없음.
- **락 키:** `_PIPELINE_LOCK_KEY = 1_958_374_620` (임의 안정 bigint, 충돌 없음).
- **해제 방식:** `finally` 블록에서 `pg_advisory_unlock` 명시 호출 — 커밋/롤백 모두 보장.
  커넥션 풀 반환 후에도 락이 남는 문제 방지.
- **§5.7 cutoff 앵커:** `brief_date + 1일 00:00 UTC - freshness_window_hours`.
  결정론적, 재실행 시 동일 결과 보장.
- **NULL published_at:** 포함(배제 금지). 신선도 불명 문서 제거 = 정보 손실.

### Remaining Work

1. **§6.3 cluster (블로커: 임베딩 모델 미확정):**
   - 임베딩 모델 선택이 `[STAGE0-BLOCKED]`. 모델 확정 후 진행.
   - `STAGE1_DESIGN.md §6.3` 읽고 설계 확인 필요.

2. **§6.5 event-classify (블로커: Stage 0 관찰 데이터 부족):**
   - Stage 0 실사용 데이터 관찰 후 분류 체계 확정.

3. **§7 Citations 2-패스 분석:**
   - generate_impact 이후 단계. 현재 brief_items.status="empty".

4. **사전 주입 실체화:**
   - KR/US 유니버스 별칭 사전을 실 데이터로 채워 run_pipeline 연결.
   - 현재 빈 dict 주입 → ticker_link 0건.

5. **동시성 가드 통합 테스트 (옵션):**
   - Docker PostgreSQL에서 두 연결로 락 충돌 확인. CLAUDE.md 컨벤션 기준 별도 실행 필요.

### Notes

- **HEAD:** 2554842 (main), 워킹트리 클린.
- **최근 커밋:**
  - `2554842` feat: run_pipeline 동시성 가드 — pg_try_advisory_lock
  - `40c835e` feat: §5.7 freshness 윈도우 필터 — _candidate_docs cutoff 필터
  - `69b0afa` fix: §6.4 OpenFIGI 하드닝 — 결함 3건 수정
- **테스트 상태:** 31 passed, ruff ✓, mypy ✓.
- **다음 세션 진입점:** `STAGE1_DESIGN.md §6.3` 읽고 임베딩 모델 결정 여부 확인.
- **읽기 순서(다음 세션):**
  - cluster: `STAGE1_DESIGN.md §6.3` → 임베딩 모델 결정 선행 필요.
  - event-classify: `STAGE1_DESIGN.md §6.5` → Stage 0 데이터 관찰 선행 필요.
- Windows uv 출력 파이프 주의: grep/head 필터 걸면 본문 사라짐, 필터 없이 실행.
- truststore: 런타임 httpx는 `truststore.SSLContext`로 OS 인증서 신뢰 필요(사내 TLS).
