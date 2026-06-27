---
status: in-progress
branch: main
timestamp: 2026-06-27T11:54:07+09:00
files_modified:
  - .github/workflows/daily.yml
---

## Working on: 일일 실행을 로컬 schtasks → GitHub Actions 클라우드 cron으로 이전

### Summary

로컬 PC 의존(schtasks)이던 일일 파이프라인을 클라우드 자동 실행으로 옮기는 작업. API 키는
GitHub Secrets로 주입. `.github/workflows/daily.yml`을 신규 작성했고(cron 21:40 UTC =
06:40 KST + workflow_dispatch 수동 트리거), 코드 변경은 0건 — config가 전부 env 기반이라
워크플로만으로 동작한다.

### Decisions Made

- **DB는 매니지드 Postgres+pgvector(Supabase/Neon).** Actions `services:` 컨테이너(현 ci.yml의
  ankane/pgvector)는 job 종료 시 삭제돼 일일 누적(dedup·랭킹)에 못 쓴다. 영속 DB 접속 문자열을
  `DATABASE_URL` 시크릿으로 주입. 사용자가 Supabase/Neon 선택.
- **임베딩은 클라우드에서 스킵.** `app/embed/__init__.py:108` get_embedder()가 라이브러리 부재 시
  graceful None 반환 → `uv sync`만 하면(extra 없이) 임베딩 자동 비활성, torch ~2GB 다운로드 회피.
  코드 변경 불필요. RAG 코퍼스 적재가 클라우드에서 필요해지면 별도 워크플로로 분리.
- **마이그레이션은 워크플로가 직접.** `alembic upgrade head` 스텝 추가. `migrations/env.py:10`이
  settings.database_url을 읽고, `0001_initial.py:23`이 `CREATE EXTENSION IF NOT EXISTS vector`를
  실행 → 매니지드 DB에 확장까지 자동 설치(롤 권한 있으면).
- **시크릿 매핑은 대문자 그대로.** pydantic-settings가 대소문자 무시라 `ANTHROPIC_API_KEY` 식
  대문자 시크릿이 config 소문자 필드에 매핑됨(현 ci.yml이 이미 그렇게 동작). 미설정 키는 빈 값 →
  소스 격리로 skip(무해).

### Remaining Work

1. **(이번에 진행) daily.yml + 컨텍스트 커밋 후 main에 push.** schedule은 default 브랜치(main)에
   있어야 활성화됨.
2. **매니지드 DB 생성(사용자):** Supabase/Neon에서 DB 만들고 접속 문자열을 `postgresql+psycopg://`
   접두사로 변환해 `DATABASE_URL` 시크릿 등록.
3. **나머지 시크릿 등록(사용자):** 있는 API 키만 GitHub Secrets에 추가.
4. **수동 트리거로 검증:** Actions 탭 → daily → Run workflow로 즉시 1회 green 확인(cron 안 기다림).

### Notes

- GitHub cron은 UTC·best-effort(고부하 시 지연·드물게 스킵). repo 60일 무활동 시 스케줄 자동 비활성.
- 06:40 KST = 21:40 UTC(전날) → `40 21 * * *`.
- docs/learnings/ 디렉터리가 untracked로 떠 있으나 이번 작업과 무관(건드리지 않음).
