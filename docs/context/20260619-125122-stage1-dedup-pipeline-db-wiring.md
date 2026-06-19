---
status: in-progress
branch: main
timestamp: 2026-06-19T12:51:22+09:00
prev_checkpoint: docs/context/20260619-123103-stage1-impl-vs-design-audit-pushed.md
files_modified:
  - app/pipeline/pipeline.py   # 미커밋 (M). 아직 commit 안 함.
---

## Working on: #1 run_pipeline 데이터 스레딩 — dedup 1차 DB 연결

### Summary

감사 체크포인트(123103) 복원 → Remaining #1 착수. `app/pipeline/pipeline.py`의
`dedup`을 실제 구현해 SimHash 근접중복 그룹을 `clusters`/`cluster_members`에 적재,
`run_pipeline(brief_date)`이 세션을 열어 dedup 호출 후 커밋하도록 스레딩. raw_documents
→ clusters end-to-end 경로의 첫 실DB 동작 구간이 생김. 어드버서리얼 리뷰(3렌즈/17에이전트)
완료 → confirmed 4/14건 중 in-scope 2건(① _candidate_docs 중복 NULL필터 제거, ② 날짜-스코프
한계 dedup docstring 문서화) 반영. 반영 후 4게이트 그린 + 실DB 라운드트립 재검증 통과. **아직 미커밋.**

### Decisions Made

- **파이프라인 형태 = A(최소·정직), 근거는 단순성이 아니라 설계 정합성:** 사용자가
  "프로젝트 목적에 맞게 선택"하라 함. 이 파이프라인은 **DB 중심 설계**(§3 "raw 적재 후에만
  파이프라인", §8 Postgres 단일 상태저장소) → 단계 간 데이터는 인메모리 ctx가 아니라
  **테이블로 흐른다**. 그래서 stage 계약 = `stage(session, brief_date)` (DB 매개).
  B안(PipelineContext 인메모리)은 DB와 상태 중복 + 대용량 시 전 문서 메모리 적재 안티패턴이라 기각.
- **STAGES 튜플+루프 제거:** 미구현 stub를 도는 루프는 `NotImplementedError`로 터지므로,
  run_pipeline이 구현된 단계만 명시 호출. 하류 4 stub(normalize/cluster/ticker_link/
  event_classify/generate_impact)은 §6 placeholder로 보존(surgical) — 구현 시 한 줄씩 추가.
- **dedup 적재 대상 = clusters/cluster_members:** §8 주석이 cluster_members를 "dedup/cluster
  결과"로 명시 → 정합적. 그룹당 Cluster 1행(centroid=None, representative_doc_id=min(group)),
  멤버 N행. near_duplicate_groups는 크기≥2만 반환 → 단독 문서는 cluster 단계(§6.3, 임베딩 블록) 몫.
- **멱등 전략 = "이미 cluster_members에 든 문서는 후보 제외":** 재실행이 중복 적재 안 함.
  커밋은 호출자(run_pipeline)만 — dedup은 flush만(cluster.id 확보용).
- **테스트 포즈 = rss.py 답습:** 순수 코어(near_duplicate_groups)는 pytest, DB I/O는 pytest에
  안 넣고 Docker pgvector 라운드트립으로 검증(CLAUDE.md Measurable Conventions: pytest는
  alembic/DB 미실행). pytest 순수 유지(컨벤션 보존).

### Remaining Work

1. **리뷰 완료(반영 끝)** — run `wf_2a794f08-fde`, confirmed 4/14. 처리:
   - ① nit(중복 NULL필터): `_candidate_docs`에서 SQL `title.is_not(None)` 제거, 컴프리헨션 단일화. **반영.**
   - ② 날짜-스코프 한계(리뷰 major/minor 평가 갈림): freshness 필터는 §5.7 컷오프 기준시각·null
     published_at 처리가 미확정 → 투기 회피 위해 **dedup docstring에 한계+TODO 문서화로 defer.**
     (사용자에게 "지금 freshness 필터 구현" 대안 제시함 — 요청 시 _candidate_docs에 추가.)
   - ③ 동시성(minor): 두 run_pipeline 동시 실행 시 중복 클러스터. 현재 동시 호출자 없음(/trigger
     스텁, cron 없음) → **cron/trigger 배선 증분 때** advisory lock 또는
     `cluster_members.raw_document_id` 유니크로 닫기. 지금 코드변경 없음.
   - rejected 10건은 불가능/범위밖(NOT IN NULL=PK라 불가, O(n²)=수초, min(group) 소비자 없음 등).
2. **커밋:** 게이트+리뷰 그린이면 `app/pipeline/pipeline.py` 단일 논리 커밋. docs/context 미러도 함께.
   (참고: `docs/context/20260619-123103-*.md`는 직전 체크포인트 미러로 아직 untracked → 같이 커밋 대상.)
3. **#1 후속 — 다음 stage 연결:** cluster(§6.3)는 임베딩(§11.3) 블록. 임베딩 무관하게 갈 수 있는
   다음 후보는 ticker-link(§6.4, OpenFIGI+사전, precision≥95% 게이트) 골격, 또는 본문 grounding
   소스(OpenDART/EDGAR) 커넥터. (직전 체크포인트 Remaining #2~#4와 동일 우선순위.)

### Notes

- **변경 파일은 `app/pipeline/pipeline.py` 1개뿐.** dedup.py(순수)·models.py·migrations 무변경.
- **게이트 결과(이번 세션):** ruff check ✅ / ruff format ✅(18 files) / mypy ✅(no issues, 18 files)
  / pytest ✅ 14 passed. 명령: `uv run ruff check .` / `ruff format --check .` / `mypy .` / `pytest -q`.
- **실DB 검증 방법(재현용):** ephemeral `ankane/pgvector` 컨테이너(포트 55433) →
  `$env:DATABASE_URL="postgresql+psycopg://postgres:postgres@localhost:55433/finance_agent"` →
  `uv run alembic upgrade head` → 시드(근접중복 3변형+무관 2+null제목 1) → run_pipeline →
  clusters=1/members=[1,2,3]/rep=1, 재실행 멱등(1/3) 확인 → `docker stop`. 검증 스크립트는 임시(미커밋).
- **함정 회피 기록:** 임시 검증 스크립트를 `%TEMP%`에 두면 그 폴더의 다른 `inspect.py`가
  stdlib를 가려(`sys.path[0]` 섀도잉) import 실패 → **검증 스크립트는 프로젝트 루트에서 실행**할 것.
- **DATABASE_URL은 env로 주입** → app.config(pydantic-settings, 대소문자 무시)가 읽어
  alembic env.py + SessionLocal 둘 다 같은 DB 가리킴. PowerShell 도구는 env가 호출 간 비유지 →
  컨테이너 기동+alembic+검증을 한 PowerShell 호출에 묶을 것.
- **표준 DB 접속**: `app/db.py` SessionLocal(`settings.database_url`, 기본 `postgresql+psycopg://localhost/finance_agent`).
- 체크포인트는 `~/.gstack` + `docs/context/` 미러링.
