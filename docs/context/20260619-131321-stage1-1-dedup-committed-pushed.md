---
status: in-progress
branch: main
timestamp: 2026-06-19T13:13:21+09:00
prev_checkpoint: docs/context/20260619-125122-stage1-dedup-pipeline-db-wiring.md
files_modified: []   # 워킹트리 클린 — main...origin/main (ahead 0), 전부 커밋·푸시됨
---

## Working on: #1 dedup 파이프라인 DB 연결 — 커밋·푸시 완료

### Summary

Remaining #1(run_pipeline 데이터 스레딩) 구현 → 어드버서리얼 리뷰 반영 → 2개 논리
커밋으로 분리해 `git push origin main` 완료. `f5a6894` feat(파이프라인 코드),
`a2078f2` docs(컨텍스트 미러 2건). raw_documents → clusters/cluster_members 경로의
첫 실DB 동작 구간이 main에 올라감. 워킹트리 클린, origin/main 최신.

### Decisions Made

- **파이프라인 형태 A(최소·정직), 설계 정합성 근거:** DB 중심 설계(§3·§8)라 단계 간
  데이터는 인메모리 ctx 아닌 테이블로 흐름. stage 계약 = `stage(session, brief_date)`.
  STAGES 루프 제거, 하류 4 stub은 §6 placeholder 보존. (상세: prev_checkpoint)
- **dedup 적재 = clusters/cluster_members:** 그룹당 Cluster 1행(centroid=None,
  representative_doc_id=min(group)) + 멤버 N행. 멱등 = 이미 클러스터된 문서 후보 제외.
- **리뷰 confirmed 4/14 처리:** ① 중복 NULL필터 제거(반영), ② 날짜-스코프 한계는
  freshness 컷오프·null published_at 미확정이라 docstring 문서화로 defer, ③ 동시성
  가드는 cron/trigger 배선 때. rejected 10건은 불가능/범위밖.
- **커밋·푸시(사용자 승인):** main 직접(솔로 프로젝트, 전 커밋 main). 코드/docs 분리
  커밋 — 직전 96b1f80(feat)/78bba2e(docs) 패턴 답습.

### Remaining Work

1. **#1 후속 두 defer 항목(다음 증분에서 닫기):**
   - **§5.7 freshness 윈도우 필터** — `_candidate_docs`에 `published_at` 기준 필터 추가.
     선결: 컷오프 기준시각(US장마감~07:00 KST 앵커)·null published_at 처리(제외 vs
     fetched_at 폴백) 확정. config `freshness_window_hours`(기본24) 이미 존재.
   - **동시성 가드** — cron/trigger 배선 증분과 함께. advisory lock(`pg_advisory_xact_lock`)
     또는 `cluster_members.raw_document_id` 유니크. 인터리브 2-run 회귀테스트로 고정.
2. **다음 stage 연결(파이프라인 전진):** cluster(§6.3)는 임베딩(§11.3) 블록 →
   임베딩 무관한 ticker-link(§6.4, OpenFIGI+사전, precision≥95% 게이트) 골격, 또는
   본문 grounding 커넥터(OpenDART §5.2 / SEC EDGAR §5.3)가 우선 후보.
3. **트리거 배선:** `/trigger`(현 스텁)이 run_pipeline(date.today()) 호출하도록 +
   07:00 cron. 동시성 가드와 같이 가는 게 자연스러움(위 1).

### Notes

- **커밋:** `f5a6894` feat: Stage 1 #1 — run_pipeline dedup 1차 DB 연결 /
  `a2078f2` docs: 컨텍스트 미러 2건. origin/main = a2078f2.
- **변경 코드 파일:** `app/pipeline/pipeline.py` 1개(+48/−17). dedup.py·models.py·migrations 무변경.
- **게이트:** ruff/format/mypy(18)/pytest 14 그린. `uv run ruff check .` / `ruff format --check .`
  / `mypy .` / `pytest -q`.
- **실DB 검증(컨벤션, pytest 아님):** ephemeral `ankane/pgvector`(포트 55433) →
  env `DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:55433/finance_agent` →
  `uv run alembic upgrade head` → 시드 → run_pipeline → clusters=1/members=[1,2,3]/멱등.
  컨테이너기동+alembic+검증을 한 PowerShell 호출에 묶을 것(env 호출 간 비유지).
  검증 스크립트는 임시(미커밋), **프로젝트 루트에서 실행**(%TEMP%엔 inspect.py 섀도잉 위험).
- **리뷰 도구:** Workflow 어드버서리얼 리뷰(3렌즈 sql/idempotency/design × 발견별 검증), 17 에이전트.
- 읽기 순서(다음 세션): `app/pipeline/pipeline.py`(dedup docstring의 §5.7 TODO) →
  `app/config.py`(freshness_window_hours) → `docs/STAGE1_DESIGN.md` §5.7·§6.4 →
  `app/collector/base.py`(다음 커넥터 계약) → `app/main.py`(/trigger 스텁).
- 체크포인트는 `~/.gstack` + `docs/context/` 미러링.
