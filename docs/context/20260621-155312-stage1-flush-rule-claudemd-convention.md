---
status: in-progress
branch: main
timestamp: 2026-06-21T15:53:12+09:00
session_duration_s: unknown
files_modified:
  - CLAUDE.md
---

## Working on: Stage 1 — flush 규칙을 CLAUDE.md Measurable Conventions에 성문화

### Summary

복귀(`/context-restore`) 후 직전 체크포인트(154109 §7 Citations)의 Remaining Work #1
"CLAUDE.md flush 규칙 제안 — 사용자 확인 대기"를 골라 닫음. dedup→cluster 중복 클러스터
(4,4) 회귀 버그(commit 2de6feb에서 수정)의 재발 클래스를 막는 한 줄 규칙을 코드 근거로
작성해 사용자 승인 후 `CLAUDE.md` Measurable Conventions에 추가. 코드 변경 없음(문서만).

### Decisions Made

- **규칙 그라운딩(메모리 아님):** commit 2de6feb의 `app/pipeline/pipeline.py` diff를 직접
  확인. 버그 메커니즘 = `SessionLocal` `autoflush=False` → `dedup()`이 `ClusterMember`를
  `add`만 하고 flush 안 함 → `cluster()._candidate_docs`의 "이미 클러스터된 문서 제외"
  SELECT가 미반영 행을 못 봐 전 문서 재클러스터링 (4,4)→정상 (2,2). 수정 = `dedup` 끝
  `session.flush()` 한 줄.
- **추가한 규칙(사용자 "이 문구 그대로 반영" 승인):** "같은 세션·트랜잭션에서 한 파이프라인
  단계가 직전 단계가 `add`한 행을 SELECT로 다시 읽으면(예: `cluster._candidate_docs`가
  `dedup`의 `ClusterMember`를 제외), 쓴 단계 끝에서 `session.flush()`를 명시 호출한다
  (`SessionLocal` `autoflush=False`라 안 하면 후속 SELECT가 미반영 행을 못 봐 중복 처리 —
  dedup→cluster 중복 클러스터 (4,4) 회귀). 커밋은 호출자가 일괄 처리. (2026-06-20,
  app/pipeline/pipeline.py dedup)"
- **배치:** 기존 마이그레이션 라운드트립 규칙 바로 아래(Measurable Conventions 두 번째 항목).

### Remaining Work

1. **(옵션) LLM 티커 후보:** 현재 모델은 티커를 만들지 않음(사전만). 사전 밖 후보를 LLM이
   제안하게 할지 별도 결정 — 사용자 판단 대기.
2. **(옵션) §7 라이브 엔드투엔드:** 실 ANTHROPIC_API_KEY로 run_pipeline 스모크. 현재는 가짜
   analyzer로만 검증(키·네트워크 불필요·결정론). DB 하니스 있어 쉬움.
3. **#6.5 event-classify:** Stage0-블록(taxonomy 관찰 미완). 인터페이스만 고정. 값 범위 대기.
4. **유니버스 실데이터:** Stage0-블록. load_dictionary 준비됨, 운영자 CSV 대기. 코드 무변경.
5. **(옵션) #5 동시성 가드 통합테스트:** 두 연결 advisory lock 충돌. 하니스로 작성 가능.

### Notes

- **git:** 이 세션 변경 = `CLAUDE.md` 1줄 추가(flush 규칙). docs 미러 + CLAUDE.md를 함께
  커밋·푸시(사용자 요청). 직전 HEAD=babbb72.
- **게이트:** 문서만 변경 — pytest/ruff/mypy 영향 없음(직전 세션 기준 57 passed).
- **체크포인트 정본:** docs/context/(커밋)가 단일 소스, gstack 미러는 보조.
- **이전 컨텍스트(154109):** §7 2-패스 Citations 구현 완료·푸시(커밋 1c077a5). Citations API와
  Structured Outputs 한 콜 동시 사용 불가(400) → 2-패스 분리. 영향 종목은 deterministic
  ticker_link(사전)이 결정, LLM 아님.
