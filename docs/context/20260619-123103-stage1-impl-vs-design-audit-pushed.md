---
status: in-progress
branch: main
timestamp: 2026-06-19T12:31:03+09:00
prev_checkpoint: docs/context/20260619-102441-stage1-rss-connector-simhash-dedup.md
files_modified: []   # 워킹트리 클린 — 전부 커밋·푸시됨 (main...origin/main, ahead 0)
---

## Working on: #3 증분 커밋·푸시 완료 + Stage 1 구현 vs 설계 감사

### Summary

`/context-restore`로 102441(RSS+dedup, 미커밋) 복원 → 대기 중이던 두 결정을
사용자 승인받아 처리: ① CLAUDE.md truststore Gotcha 1줄 추가, ② #3 증분 커밋 +
푸시. 이후 사용자 요청으로 **전체 구현 상태를 초반 설계(DESIGN.md, STAGE1_DESIGN.md)
와 대조 감사**했다. 결론: 골격은 설계 충실하게 완성, 제품 본체는 ~10-15%만 구현.
워킹트리 클린, origin/main 최신(78bba2e).

### Decisions Made

- **CLAUDE.md Gotcha 추가(사용자 승인):** `## Project-Specific Gotchas`에 한 줄 —
  "런타임 httpx/requests는 truststore로 OS 인증서 신뢰(사내 TLS 가로채기 →
  CERTIFICATE_VERIFY_FAILED). `ctx=truststore.SSLContext(...)` → `httpx.Client(verify=ctx)`."
  메모리 [[python-httpx-truststore-tls]]는 개인용이라 팀 공유 규칙은 CLAUDE.md에 둠.
- **커밋 + 푸시(사용자 승인):** 2개 논리 커밋으로 분리 —
  `96b1f80` feat(rss.py/dedup.py/tests + pyproject/uv.lock + CLAUDE.md),
  `78bba2e` docs(context 미러 3건). 게이트 재확인 그린(ruff/format/mypy/pytest 14).
  `git push origin main`으로 853b6be까지 함께 푸시(0899c9a..78bba2e). main 직접 작업
  유지(이 repo 5커밋 전부 main, 솔로 프로젝트 → 브랜치/PR 의식 불필요).
- **docs/context/ 미러는 커밋 대상:** 기존 미러 5건 이미 tracked → 관례대로 새 3건도 커밋.

### Remaining Work

1. **#3 후속 — `run_pipeline()` 데이터 스레딩:** 현재 `app/pipeline/pipeline.py`의
   6단계는 전부 `raise NotImplementedError`, stage가 인자·DB를 안 받음. dedup 1차
   (`app/pipeline/dedup.py`)를 실제 연결 + DB 문서 스레딩이 다음 증분.
2. **본문 grounding 소스 1종(OpenDART 또는 SEC EDGAR):** §5.2/§5.3. KR/US 추적성
   (P2 제품 본체)의 실제 시작점. 현재 커넥터는 RSS 1종뿐(8종 중 1).
3. **2-패스 Citations 생성(§7):** 제품 핵심 가치(문장단위 추적성). Anthropic 연동 전무.
   cluster → ticker-link(§6.4 precision≥95% 게이트) → generate-impact 순.
4. **검증 게이트(§12):** swap test(인용 조작 0건)·NLI≥98%·티커 precision≥95%·
   null-evidence refusal — 전부 generate-impact 의존, 미구현. 현재 테스트는 순수 코어만.
5. **dedup 2차(임베딩 cosine) + §11.3 KR 임베딩 모델 벤치:** 임베딩 미결로 블록.
6. **Stage 0(애널리스트 관찰 숙제):** 설계상 의도적 빈칸. taxonomy·UX·커버리지 입력은
   결과 도착 후 확정.

### Notes

- **구현 vs 설계 감사 결과(요약):**
  - 스택(§4) ✅ 결정대로. 데이터모델(§8) ✅ 9개 테이블 1:1 + 실DB 라운드트립 검증.
  - 커넥터(§5) ⚠️ 8종 중 1종(코인 RSS §5.8). OpenDART/EDGAR(본문 grounding) 0%.
  - 파이프라인(§6) ⚠️ dedup 1차만 독립 함수로 존재, **pipeline 미연결**. 나머지 스텁.
  - 웹 대시보드(§3·§10) ⚠️ 플레이스홀더. `/health` ✅, `/trigger` 스텁, `/` 더미 HTML.
  - 핵심 갭: raw_documents → brief_items end-to-end 경로 0%. "증거 브리프" 미존재.
- **충실도 좋음:** STAGE0-BLOCKED/OPEN 칸 추측으로 안 채움(event_type 자유문자열,
  Vector() 차원 미고정, config 빈 키). P5 합법경계 코드 강제(RSS body=None + legal_basis).
- 마이그레이션 위치: `migrations/`(alembic.ini `script_location=migrations`), `alembic/` 아님.
- 게이트 명령: `uv run ruff check .` / `ruff format --check .` / `mypy .` / `pytest -q`.
  네트워크 타는 uv 명령은 `--system-certs` 필수([[uv-system-certs-tls]]).
- 읽기 순서(다음 세션): docs/STAGE1_DESIGN.md(§6 파이프라인·§7 Citations) →
  app/pipeline/pipeline.py(스레딩 미구현) → app/pipeline/dedup.py(연결 대상) →
  app/collector/base.py(다음 커넥터 계약) → app/models.py(brief_items 적재 타겟).
- 체크포인트는 `~/.gstack` + `docs/context/` 미러링.
