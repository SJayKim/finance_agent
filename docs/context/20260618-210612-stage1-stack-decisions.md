---
status: in-progress
branch: main
timestamp: 2026-06-18T21:06:12+09:00
files_modified:
  - CLAUDE.md
  - docs/STAGE1_DESIGN.md
notes_on_env: gstack bin/* 셸 도구는 Windows에서 미동작 → 이 체크포인트는 수동 작성, 레포 docs/context/에 보관. /context-restore가 gstack 슬러그(SJayKim-finance_agent)에서 못 찾으면 이 경로를 직접 지정할 것.
prev_checkpoint: docs/context/20260618-164904-finance-agent-design-office-hours.md
---

## Working on: Stage 1 기술 상세 설계 + 스택 확정

### Summary

DESIGN.md(APPROVED, office-hours 산출물)의 **Stage 1(Approach A: 모닝미팅 증거
브리프 MVP)**을 실행 가능한 기술 스펙으로 내렸다. 신규 문서 `docs/STAGE1_DESIGN.md`
작성(13개 섹션) + 스택 확정 + CLAUDE.md Commands 채움. **코드는 여전히 0줄.**
핵심 원칙: "결정된 것 / Stage 0 관찰에 막힌 것 / 열린 기술선택"을 색(`[DECIDED]`/
`[STAGE0-BLOCKED]`/`[OPEN]`/`[GATE]`)으로 분리해, 관찰 못 한 갭을 코드로 굳히지 않음.

### Decisions Made

- **스택 확정(2026-06-18, AskUserQuestion 2건):**
  - 언어/환경: **Python 3.12 + uv**
  - 백엔드: **FastAPI + uvicorn** (07:00 cron + 온디맨드 트리거)
  - 프런트: **Jinja2 + HTMX 서버렌더 먼저** (클릭-투-소스만; UX 레이아웃은 여전히
    Stage 0에 막힘. 무거운 인터랙션 필요 시 추후 SPA 전환)
  - DB: **Postgres 16 + pgvector** + SQLAlchemy 2.0 + Alembic
  - 품질도구: **ruff**(lint+format), **mypy**, **pytest**
  - 배포: 단일 VM + Docker
  - 임베딩: **모델만 미정**(BGE-M3/multilingual-e5/text-embedding-3 중 KR dedup
    precision/recall 실측 후) — 인터페이스는 로컬↔API 교체 가능하게 추상화.
- **CLAUDE.md Commands 채움:** `uv sync` / `uv run uvicorn app.main:app`(watch 금지,
  --reload 빼라는 기존 노트 존중) / `uv run pytest` / `uv run ruff check .` /
  `uv run mypy .`.
- **STAGE1_DESIGN.md 핵심 스펙:**
  - 아키텍처: Collector(수집, 쿼터 병목) ↔ Pipeline(고정 단계) 분리. raw 적재 후에만
    파이프라인 실행. 멀티에이전트 없음(P6).
  - 파이프라인: normalize → dedup(제목 SimHash → 임베딩 cosine) → cluster →
    ticker-link(OpenFIGI+사전, precision≥95% 미달 시 "후보" 보류) → event-classify
    → 2-패스 Citations 생성.
  - **2-패스 Citations 무결성 규칙(가장 중요):** 패스2 입력을 패스1이 실제 인용한
    cited_text 범위로만 제한(안 그러면 zero-fabrication 재붕괴). 검증(swap/NLI)은
    패스2 최종 출력에 대해.
  - 스키마(§8): 모든 analysis_text 문장이 citations로 원문 char 범위까지 역추적.
    degraded/empty/후보가 1급 컬럼. audit_log 포함.
  - 빈/장애 UX: null-evidence refusal(근거 없으면 "근거 없음", 환각 금지).
  - 검증(§12): 조작 인용=0건(하드 게이트, CI 회귀), NLI 함의율≥98%, 티커 precision≥95%.

### Remaining Work

1. **(하드 게이트 / 착수 전 선결) §11.1 코인 뉴스 소스:** CryptoPanic 무료 끊김
   (2026-04). CoinGecko+Marketaux vs 유료 전환 결정. 정해지기 전 코인 브리프는 시세만.
2. **(하드 게이트) §11.2 arXiv 2606.12210 인용 재확인:** P1 근거 수치 원문 확인 후에야
   문서에 박을 수 있음. (방향성 결론은 이 한 편에 비의존)
3. **다음 갈림길(사용자에게 물어둠, 미선택):**
   - (a) 프로젝트 스캐폴딩 — pyproject.toml(uv) + FastAPI 골격 + Alembic + §8 스키마
     마이그레이션 + 디렉토리 구조. Stage 0 무관, 바로 가능.
   - (b) 하드 게이트 조사 먼저(위 1·2 웹조사).
   - (c) OpenDART 1개 수직 슬라이스(수집→정규화→저장)로 파이프라인 패턴 검증.
4. **§11.3 임베딩 모델 실측 벤치 후 확정.**
5. **Stage 0(founder 숙제, 코드 아님):** 애널리스트 3~5명 07:00~09:00 관찰 → 시간 누수
   1~2개 특정. STAGE1_DESIGN §2의 `[STAGE0-BLOCKED]` 칸(브리프 콘텐츠/이벤트 taxonomy/
   신뢰도 표기/커버리지 입력/전달 채널/UX 레이아웃)을 이 결과로 채움.

### Notes

- **미커밋 상태:** CLAUDE.md(수정), docs/STAGE1_DESIGN.md(신규) 둘 다 워킹트리에만 있음.
  스택 결정 묶어서 커밋하려면 사용자 승인 후. (도메인상 커밋은 사용자가 요청할 때만)
- **읽기 순서(다음 세션):** DESIGN.md(전체 근거·Open Questions) → docs/STAGE1_DESIGN.md
  (기술 스펙) 순. PAIN_POINT.md는 애널리스트 페인 원천(필터 needs, 환각 불신, 출처 추적).
- **Stage 0에 막힌 칸은 하드코딩 금지** — 파이프라인은 그 결정들을 설정/플러그인 경계로
  받게 설계해 두고 빈 채로 둔다(추측 채움 = Stage 0 의미 상실).
- **합법 경계 재확인:** KR 뉴스 본문 직접 크롤링 금지(P5) → 네이버 오픈API(헤드라인+요약)
  만. KR sentence-level grounding은 공시(OpenDART) 본문에서만. 본문 단위 KR 뉴스는
  Stage 3(BIGKINDS/좌석 연동).
- **환경:** gstack 스킬 ceremony(telemetry/learnings 등)는 Windows bin/* 미동작으로 생략.
- gstack 슬러그: SJayKim-finance_agent (네이티브 /context-restore가 못 찾으면 이 파일 직접 지정).
