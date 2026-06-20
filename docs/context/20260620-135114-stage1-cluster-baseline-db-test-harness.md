---
status: in-progress
branch: main
timestamp: 2026-06-20T13:51:14+09:00
session_duration_s: unknown
files_modified:
  - app/pipeline/pipeline.py
  - tests/conftest.py
  - tests/test_pipeline.py
---

## Working on: Stage 1 — §6.3 cluster 단독문서 베이스라인 + 최초 DB 통합테스트 하니스 (커밋)

### Summary

복귀 후 "다음 action"을 ultracode 워크플로우(병렬 리더×4 → synth → adversarial verify)로
그라운딩 → **파이프라인이 일반(비중복) 뉴스에 대해 구조적으로 brief를 0건 생성**하던 핵심
결함 발견. `cluster()`(§6.3)가 `NotImplementedError` 스텁이라 호출조차 안 돼, 단독 문서가
클러스터가 못 되고 `generate_impact`가 볼 게 없었다. 체크포인트·docs 5건이 cluster를
"임베딩 §11.3 블록"으로 오분류했으나 임베딩은 **선택적 2차 병합**에만 필요. 베이스라인을
`dedup()` 미러로 구현·배선하고, 프로젝트 **최초 DB 통합테스트 하니스**(실 Postgres+alembic)
추가. 전 게이트 green(pytest 43→45). 피처 커밋 **2de6feb**.

### Decisions Made

- **다음 action 그라운딩:** ultracode 워크플로우(wf_7d67c86d-cad)로 design↔구현 맵·의존성
  그래프·진짜 unblocked 판정 → cluster 베이스라인이 최고가치 unblocked로 확정(adversarial
  verify: trulyUnblocked=true, confirmed). 체크포인트의 "§11.3 임베딩 블록" 라벨은 오분류.
- **cluster() 설계:** 임베딩 cosine 2차 병합(§6.3 후단, §11.3 미정)은 보류. 베이스라인 =
  `_candidate_docs`(이미 클러스터된 문서 제외 + 신선도 윈도우)마다 1-멤버 클러스터. `dedup()`
  정확한 미러라 ≥2 그룹 보존·단독만 새 클러스터(중복 적재 없음).
- **dedup flush 버그 (cluster가 노출):** dedup이 `cluster_row.id`용으로만 flush하고 멤버는
  `add_all` 후 미flush. `SessionLocal`은 autoflush=False라 cluster의 `_candidate_docs` SELECT가
  미flush 멤버를 못 봐 전 문서를 재클러스터링((4,4)). 수정: dedup 끝 `session.flush()` 1줄
  (generate_impact가 이미 따르는 관례). 멱등 테스트가 회귀 가드.
- **검증 깊이 (사용자 선택 = "구현 + DB 통합테스트 하니스"):** conftest가 실 Postgres+alembic로
  스키마 구축, `DATABASE_URL`을 `*_test` DB로 강제(개발 DB 불가침), 미연결 시 빠른 skip
  (`connect_timeout=2s` 전용 프로브 — dead-port 260s→4.4s). test_pipeline: 근접중복 2 + 고유 1
  → 클러스터 2·brief_item 2·멱등 재실행 검증.

### Remaining Work

1. **(미결정) CLAUDE.md 규칙 제안 대기:** "파이프라인 단계가 직전 단계가 같은 세션에서 쓴
   행을 읽으면, 그 단계 끝에서 `session.flush()`(SessionLocal autoflush=False)" — Measurable
   Conventions 추가 여부 **사용자 확인 대기**. 이번 dedup 버그의 재발 클래스.
2. **§7 Citations 2-패스 (다음 최고가치):** 이제 클러스터가 실제로 생겨 `generate_impact`가
   brief_item을 만든다(status=empty). 다음 = `analysis_text`/citations 채워 status ok/degraded.
   **blocked-code**(외부 블록 아님 — Citations API + Structured Outputs 사용 가능). 신설
   `app/pipeline/citations.py` → generate_impact 배선. pass1·pass2 1콜 결합 금지(§7).
3. **(옵션) /trigger 라이브 엔드투엔드:** 이제 DB 하니스가 있어 통합 스모크가 쉽다.
4. **#6.5 event-classify:** Stage0-블록(taxonomy 관찰 미완). 인터페이스만 고정(models). 값 범위 대기.
5. **유니버스 실데이터:** Stage0-블록. `load_dictionary` 준비됨, 운영자 CSV 대기. 코드 무변경.
6. **(옵션) #5 동시성 가드 통합테스트:** 두 연결로 advisory lock 충돌. 이제 하니스로 작성 가능.

### Notes

- **git:** 피처 커밋 **2de6feb**(cluster + 하니스, +176/-5, 신규 conftest.py·test_pipeline.py).
  이 docs 미러는 별도 `docs:` 커밋. 직전 HEAD=9440a2c.
- **푸시 정책 (재발 주의):** 자동모드가 `git push origin main`(기본 브랜치 직접 푸시) 차단 →
  사용자가 `! git push` 또는 승인 프롬프트 허용 필요.
- **테스트 하니스 운영:** Docker `fa_test_pg`(ankane/pgvector → Postgres 15.4, 포트 5433) 띄워둠.
  정리는 `docker rm -f fa_test_pg`. 하니스는 미연결 시 skip이라 컨테이너 없어도 단위 43건 green.
- **게이트:** pytest **45 passed**, ruff check ✓, ruff format ✓(27 files), mypy ✓(27 files).
  명령: `uv run pytest -q` / `uv run ruff check .` / `uv run ruff format --check .` / `uv run mypy .`.
- **체크포인트 정본:** `docs/context/`(커밋)가 단일 소스, gstack 미러는 보조.
- Windows uv 출력 파이프 주의(grep/head 필터 시 본문 소실 — 필터 없이 실행).
- truststore: 런타임 httpx는 OS 인증서 신뢰 필요(사내 TLS).
