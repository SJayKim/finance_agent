---
status: complete
branch: main
timestamp: 2026-06-28T13:55:36+09:00
files_modified:
  - migrations/env.py
  - CLAUDE.md
---

## Working on: 클라우드 daily를 Supabase에 연결 + 실작동 검증 (스케줄 실패 원인 제거)

### Summary

매니지드 DB(Supabase) 연결 → daily 워크플로 첫 green 실행까지 완료. 그 과정에서
**스케줄 cron이 매일 실패하던 진짜 원인**을 잡았다: (1) `migrations/env.py`의 configparser
`%`-보간 버그, (2) `DATABASE_URL` 시크릿 미설정. 둘 다 해소하고 클라우드 실행이 Supabase에
실제 적재하는 것까지 확인(raw_documents 224 · brief_items 24 · daily_digests 1). PR #2가
main에 머지돼(`febfc53`) **다음 cron(06:40 KST)부터 자동 성공**한다.

### Decisions Made

- **DB는 Supabase 채택.** Session pooler(포트 5432, IPv4) 사용 — GitHub Actions 러너는
  IPv4 전용인데 Supabase Direct(IPv6)는 못 붙고, Transaction pooler(6543)는 psycopg3
  prepared statement를 깨므로 Session 모드가 정답. 리전 ap-northeast-1(Tokyo),
  PostgreSQL 17.6, pgvector 설치됨.
- **env.py 근본 수정(`c7b3dff`).** 접속 문자열을 `config.set_main_option`/`get_section`
  (configparser)으로 왕복시키면 URL-인코딩된 비밀번호의 `%`(`%40` 등)를 BasicInterpolation이
  보간으로 오인해 `ValueError: invalid interpolation syntax`로 죽는다(특수문자 비밀번호면
  무조건 재현, 클라우드도 동일). configparser를 우회해 `create_engine(settings.database_url)`로
  직접 전달. CLAUDE.md Gotchas에 규칙 성문화(`5905632`).
- **시크릿은 DATABASE_URL만 설정.** `postgresql+psycopg://` 접두사 + 비밀번호 URL-인코딩.
  ANTHROPIC_API_KEY는 미설정(사용자 빌링 자격증명) → 수집·클러스터·임팩트보드·다이제스트는
  동작하나 AI 2-패스 citations만 스킵(citations=0).
- **검증 순서.** 로컬에서 Supabase로 `alembic upgrade head`→`alembic check`(clean) 선검증 후
  워크플로를 fix 브랜치 ref로 dispatch해 green 확인 → 머지. 즉 머지 전에 클라우드 실작동 입증.

### Remaining Work

1. **ANTHROPIC_API_KEY 추가(사용자):** `gh secret set ANTHROPIC_API_KEY` → AI 분석/citations 활성.
2. **(선택) Actions 버전 bump:** `actions/checkout@v4`·`astral-sh/setup-uv@v5`가 Node20
   deprecated 경고. 무해하나 추후 상위 버전으로.
3. **(선택) 임베딩:** 클라우드 daily는 embeddings extra 미설치라 RAG 코퍼스 적재 스킵(설계대로).

### Notes

- gh CLI를 `%LOCALAPPDATA%\Programs\gh-cli`에 포터블 설치(관리자 불필요)하고, 머신에 캐시된
  GCM GitHub 토큰(SJayKim)으로 인증해 시크릿·트리거·머지에 사용. `gh auth logout`으로 해제 가능.
- 첫 green 실행: run 28311342168, 3m13s. 직전 스케줄 실행(28303082110, main)은 위 2원인으로 failure였음.
- DATABASE_URL 실제 비밀번호는 GitHub Secrets에만 존재(이 문서·코드·메모리에 평문 금지).
