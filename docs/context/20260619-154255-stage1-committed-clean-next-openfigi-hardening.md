---
status: in-progress
branch: main
timestamp: 2026-06-19T15:42:55+09:00
files_modified: []
---

## Working on: Stage 1 #3 커밋 완료 — 다음: §6.4 OpenFIGI 하드닝

### Summary

이번 세션은 /context-restore(151840)로 복귀 → **미커밋 상태였던 `app/pipeline/pipeline.py`를
feat + docs 미러 커밋 후 푸시**로 마무리했다. 워킹트리는 완전히 클린(변경 파일 없음).
다음 작업 대상은 §6.4 OpenFIGI 하드닝 — 감사에서 짚은 잠재결함 3건.

### Decisions Made

- **커밋 순서 유지:** feat(pipeline.py) → docs(체크포인트 미러) 분리 커밋 패턴 그대로.
  커밋 `f9c38f9` + `c29da81`, 푸시 완료.
- **§6.4 하드닝 다음 세션으로:** 이번 세션은 커밋/푸시에서 종료. 결함 3건은 미착수.

### Remaining Work

1. **§6.4 OpenFIGI 하드닝 — 잠재결함 3건 (최우선):**
   - `openfigi.py:87` — 200 응답에 `error` 객체가 포함된 경우 `.get("data")`=None →
     실 오류를 no-match로 오인. MockTransport 사각지대. 재현 테스트 작성 → 수정.
   - `records[0]` 정규성 미보장 — US 복합거래소(NYSE+NASDAQ 동시 상장), 순서 무보장.
     명시적 선택 로직(우선순위 거래소) 필요.
   - `openfigi.py:47` 10s 타임아웃 — batch에서 `TimeoutException` 전파 처리 누락.
2. **#1 defer 2건 (여전히 열림):** §5.7 freshness 윈도우 필터 + 동시성 가드 (cron/trigger).
3. **파이프라인 다음 단계:** cluster(§6.3, 임베딩 모델 확정 후) → event-classify(§6.5,
   Stage 0 관찰 후) → §7 Citations 2-패스 분석.
4. **사전 주입 실체화:** KR/US 유니버스 별칭 사전을 실 데이터로 채워 run_pipeline 연결.

### Notes

- **워킹트리 상태:** 완전히 클린. 변경 파일 없음, HEAD=c29da81, origin/main 동기.
- **읽기 순서(다음 세션 §6.4):** `app/collector/openfigi.py`(전체) →
  `tests/test_openfigi.py`(MockTransport 커버리지 확인) →
  `docs/STAGE1_DESIGN.md §6.4` 게이트 기준 재확인.
- **변경된 함수/클래스(pipeline.py, 이미 커밋):**
  - `generate_impact(session, brief_date)` — 신규 구현 (라인 121-131)
  - `ticker_link(session, brief_date, dictionary, normalizer)` — 스텁→구현 (라인 79-105)
  - `_brief_items_without_tickers(session, brief_date)` — 신규 헬퍼 (라인 62-68)
  - `_representative_title(session, cluster_id)` — 신규 헬퍼 (라인 71-76)
  - `_clusters_without_brief_item(session, brief_date)` — 신규 헬퍼 (라인 112-118)
  - `run_pipeline(brief_date, dictionary=None)` — 시그니처 + 배선 변경 (라인 134-149)
- **실DB 스모크(이전 세션 결과):** pytest 25 passed, ruff ✓, mypy ✓. 회귀 없음.
- Windows uv 출력 파이프 주의: grep -v/head 필터 걸면 본문 사라짐. 필터 없이 실행.
- 체크포인트 `~/.gstack` + `docs/context/` 미러링(커밋 시) 패턴 유지.
