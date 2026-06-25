---
status: complete
branch: feat/seeding-ci-scheduler (→ main 머지 예정)
timestamp: 2026-06-25T21:17:11+09:00
files_modified:
  - app/pipeline/seed.py
  - app/runner.py
  - app/main.py
  - tests/test_seed.py
  - tests/test_runner.py
  - tests/conftest.py
  - .github/workflows/ci.yml
  - tests/test_swap.py
  - tests/test_ticker_precision.py
  - scripts/run_daily.cmd
  - scripts/schedule_daily.cmd
  - scripts/crontab.example
  - logs/.gitkeep
  - .gitignore
  - docs/STAGE1.5_OPERATIONS.md
---

## Working on: 완성도 blocker 실행 계획 plan 01·04·03 구현 (커밋후 1→4→3)

### Summary

완성도 감사에서 "계획만 있고 코드 0건"이던 plan 01(시딩 배선)·04(CI+하드게이트)·03(스케줄러)을
전부 구현했다. plan 02(임팩트 랭킹)는 이미 구현돼 있었음(0004 마이그레이션 + rank_board, 계획의
"정렬만"보다 진전된 방향). 전 구간 **147 tests green, ruff clean, mypy clean**(_seed_dev.py
3건은 untracked라 CI 클린 체크아웃엔 부재). 전용 브랜치 `feat/seeding-ci-scheduler`에 3커밋
(dfbd92f / 46815a8 / 0882720). 15파일 +421/-20.

### Decisions Made

- **plan 01 — 핵심 블로커 해소:** security_aliases가 비면 ticker_link 영구 0건 → "영향 큰 종목
  추천" 산출물이 안 나오던 문제. `app/pipeline/seed.py` 신규(seed_aliases: sec/opendart/coingecko
  sync를 소스 격리 try/except+rollback로 호출; seed_coverage: coverage 0행일 때만 STARTER_COVERAGE
  멱등 삽입; seed_universe: 진입점). run_daily에 `seeder` 주입 파라미터 추가(기존 embedder/digester
  패턴, None=off, 락 안 첫 단계 → run_pipeline ticker_link보다 먼저). main()/run-daily 엔드포인트가
  실 seed_universe 주입, 테스트는 None/가짜. AuditLog(action="seed") 기록.
- **plan 01 divergence:** plan이 근거로 든 `load_coverage_queries`(coverage→naver 쿼리 도출)가
  현 코드에 부재(naver는 DEFAULT_QUERIES 하드코딩). 무의미한 build_default_connectors 재배치는
  생략. seed_coverage는 소비자가 생길 때까지 멱등 시드만 확보(효력 제한적임을 코드·커밋에 명시).
- **plan 04 — 머지 게이트:** `.github/workflows/ci.yml`(push/PR, ubuntu+Python3.13 setup-uv +
  ankane/pgvector 서비스 5433:5432 → uv sync/pytest/ruff/mypy). 하드게이트1 swap test
  (tests/test_swap.py: parse_pass1 매핑 인용이 cited_text==원문[char_start:char_end]; 인덱스
  깨면 잡아내는 teeth 테스트). 하드게이트2 precision(tests/test_ticker_precision.py: 라벨 12건,
  confident 링크 precision≥0.95, 실측 1.000; 중의 별칭은 후보로 빠져 분모서 제외 검증).
- **plan 03 — 스케줄 산출물:** scripts/run_daily.cmd(잡 본체, %~dp0..로 루트 도출, logs append) +
  schedule_daily.cmd(schtasks 등록, /TR은 run_daily.cmd만 호출 → 따옴표·리다이렉션 깨짐 회피) +
  crontab.example(KST/UTC 2줄+TZ 주석). logs/.gitkeep + .gitignore. OPERATIONS.md를 스크립트
  실행 가리키도록 갱신.

### Remaining Work

1. **(이번에 진행) feat/seeding-ci-scheduler → main 머지 + origin push.** 기존 미푸시 2커밋
   (3283bf4, d614aca)도 함께 올라간다.
2. **스케줄 등록(부수효과, 사용자):** `scripts\schedule_daily.cmd` 실행(매일 06:40 로컬 TZ).
3. **API 키 주입:** 현재 키 없이는 RSS + CoinGecko 별칭(8종)만 동작. DART/SEC/Marketaux/Finnhub
   키 추가 시 즉시 라이브(소스 격리로 키 없는 소스는 skip).
4. **임베딩 활성화:** `uv sync --extra embeddings`(bge-m3 최초 1회 다운로드) — RAG 코퍼스 적재용.
5. **CI 첫 실행 확인:** push 후 GitHub Actions가 pgvector 서비스 포함 green인지.

### Notes

- 검증 인프라: Docker Desktop + `fa_test_pg`(ankane/pgvector, 5433) 사용. 통합테스트는
  FakeEmbedder라 embeddings extra(torch ~2GB) 불필요.
- conftest TRUNCATE에 security_aliases 추가(seed 테스트 격리).
- .gitignore 함정 수정: `logs/`(디렉터리)로 막으면 `!logs/.gitkeep` 부정이 무력화 → `logs/*`로
  내용만 막아 .gitkeep 추적. .cmd는 cp949 mojibake 방지로 ASCII만 사용.
