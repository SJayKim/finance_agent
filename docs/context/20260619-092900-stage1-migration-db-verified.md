---
status: in-progress
branch: main
timestamp: 2026-06-19T09:29:00+09:00
files_modified: []  # 작업 트리 클린 — 이번 세션 작업분 전부 커밋·푸시됨
prev_checkpoint: docs/context/20260619-082635-stage1-scaffold-tests-green.md
---

## Working on: Stage 1 스캐폴딩 커밋 + 마이그레이션 실DB 검증 (#1·#2 완료)

### Summary

직전 체크포인트(스캐폴딩 그린, 커밋 직전)에서 이어 **남은작업 #1·#2를 완료**.
#1 스캐폴딩 전체를 main에 커밋·푸시(`b1c4baa`). #2 마이그레이션을 **격리 Docker
pgvector에서 실DB 검증** — 게이트(pytest/ruff/mypy)가 못 잡던 결함 2건을 발견·수정해
커밋·푸시(`0899c9a`). 작업 트리 클린, origin 동기화됨. Stage 1은 여전히 골격
(커넥터·파이프라인 로직 0) — 다음은 #3 구현.

### Decisions Made

- **#2 검증을 격리 컨테이너로:** 로컬 5432에 정체불명 Postgres가 떠 있음(venv 경고가
  `crypto_deep_research`를 가리킴 — 그 프로젝트 DB로 추정). 거기에 DDL+CREATE EXTENSION
  실행은 오염 위험 + 일반 PG엔 pgvector 없음. → **Docker `ankane/pgvector:v0.5.1`**
  (캐시됨, 네트워크 pull 불필요/사내 TLS 회피)를 **포트 55432**에 띄워 검증, 끝나고 폐기.
  5432는 미접촉.
- **결함 1 — alembic.ini cp949 블로커:** configparser가 `.ini`를 로케일 코덱
  (Windows=cp949)으로 읽어 4행 UTF-8 한글 주석에서 `UnicodeDecodeError` → alembic
  로드 실패. **수정:** 주석을 ASCII로. (`.py`는 UTF-8로 읽혀 무관 — `.ini`만의 함정.)
- **결함 2 — nullable 드리프트:** `raw_documents.fetched_at`·`clusters.created_at`·
  `brief_items.generated_at`·`audit_log.ts`가 모델은 `Mapped[datetime]`(NOT NULL 의도)
  인데 마이그레이션이 `nullable=False` 누락 → NULL 허용 생성. **수정:** 4건 추가.
  `alembic check` "No new upgrade operations detected"(클린) 확인.
- **재발 방지 코드화:** CLAUDE.md에 Gotchas(configparser 파일 ASCII-only) +
  Conventions(마이그레이션은 실DB 라운드트립 검증) 2줄 추가. auto-memory
  `windows-cp949-config-encoding`(feedback) 저장.
- **기존 결함은 미접촉(Surgical):** ① `app/models.py` ruff-format 편차(b1c4baa에 이미
  존재, 직전 세션이 `ruff format --check` 미실행) ② CLAUDE.md line 68 stale 주석
  (`스택: Python 3.12` — 실제 3.13+). 둘 다 #2 무관이라 보고만.

### Remaining Work

1. **(선택, 1줄 클린업) 기존 결함 2건 정리:** `uv run ruff format .`(models.py) +
   CLAUDE.md line 68 주석 3.13+로. 한 커밋이면 충분.
2. **#3 구현 착수(§13 병렬 가능, Stage 0 무관):** §5 커넥터 1~2종 + §6.2 dedup
   (제목 SimHash → 임베딩 cosine). dedup 2차는 §11.3 임베딩 모델 결정 후.
3. **#4 잔여 조사:** Finnhub 크립토 커버리지 실측, NewsData.io 무료 한도, §11.3 KR
   임베딩 벤치, Stage 0 founder 숙제(애널리스트 07:00~09:00 관찰).

### Notes

- **마이그레이션 검증 레시피(Convention화됨):** `docker run -d --name fa_pgvector_verify
  -e POSTGRES_PASSWORD=verify -e POSTGRES_DB=finance_agent -p 55432:5432
  ankane/pgvector:v0.5.1` → `export DATABASE_URL='postgresql+psycopg://postgres:verify@localhost:55432/finance_agent'`
  → `uv run alembic upgrade head` → `uv run alembic check`(클린) → `downgrade base` →
  `docker rm -f fa_pgvector_verify`.
- **포트 5432 미접촉:** 정체불명 Postgres(crypto_deep_research 추정) — 격리 컨테이너만 사용.
- **uv 네트워크 명령은 `--system-certs` 필수**(이 머신, 사내 TLS). memory `uv-system-certs-tls`.
- **cp949 함정** memory `windows-cp949-config-encoding`. configparser 파일엔 비-ASCII 금지.
- gstack bin/* 일부만 동작(slug/paths OK). 체크포인트는 ~/.gstack + docs/context/ 미러링.
- 정적 적대적 리뷰 workflow(26 에이전트)가 #2 nullability 결함을 독립 교차검증 →
  conformant, blocker·major 0. 인덱스(published_at/brief_date) 미생성은 §8 미요구라 미조치.
- 읽기 순서(다음 세션): DESIGN.md → docs/STAGE1_DESIGN.md(§4·§8) → PAIN_POINT.md →
  app/models.py(§8 구현체).
