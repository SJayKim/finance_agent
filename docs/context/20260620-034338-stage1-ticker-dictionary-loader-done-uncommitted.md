---
status: in-progress
branch: main
timestamp: 2026-06-20T03:43:38+09:00
session_duration_s: unknown
files_modified:
  - app/config.py
  - app/pipeline/pipeline.py
  - app/pipeline/dictionary.py
  - tests/test_dictionary.py
---

## Working on: #4 사전 실체화 — 티커 사전 로더(§2-순수) 구현 완료, 미커밋

### Summary

/context-restore(162657)로 복귀 → 남은작업 #4 "사전 주입 실체화" 착수. §2(유니버스
하드코딩 금지)와 체크포인트의 "실 데이터로 채워"가 충돌해 AskUserQuestion으로 범위 확정:
**A) 로더만(§2-순수)** 선택. 설정 경로 CSV에서 alias,ticker,market을 읽는 `load_dictionary`
로더 + 설정 경계 + run_pipeline 배선 + 단위테스트 11건을 구현. 게이트 전부 green.
**아직 커밋 안 함**(CHECKPOINT_MODE=explicit, 사용자 커밋 지시 대기 중).

### Decisions Made

- **§2 충돌 해소(범위 A):** 유니버스 데이터를 소스에 절대 담지 않는다. 코드는 *주입
  메커니즘*(로더)만 제공하고, 사전 데이터는 운영자가 설정 경로로 주입. §2의 "설정·플러그인
  경계로 받고 빈 채로 둔다"를 그대로 구현. 경로 미설정 → 빈 사전 → 링크 0건(기존 기본동작 불변).
- **포맷:** 헤더 정확히 `alias,ticker,market`인 UTF-8 CSV. `csv.DictReader`. market은
  KR/US/CRYPTO만 허용(BriefItemTicker.market·TickerLink.market과 일치).
- **로더 위치/설정:** `app/pipeline/dictionary.py::load_dictionary(path)` +
  `settings.ticker_dictionary_path: str | None = None`.
- **run_pipeline 배선:** `dictionary is None`이면 `load_dictionary(settings.ticker_dictionary_path)`로
  적재. 명시 dict 주입 시 그대로 사용(기존 `dictionary or {}` → `is None` 체크로 교체).
  파일 읽기는 락 획득 전(세션 밖)에서 수행.
- **닫은 정합성 함정 2건(로더에서):**
  1) **거짓 중의성:** resolve는 `len(mappings)>1`을 중의(is_candidate)로 본다. 같은
     (ticker,market) 행 중복이 이를 거짓 트립 → 로더가 별칭당 (ticker,market) 쌍 중복 접음.
  2) **대소문자 그룹핑:** 별칭 키를 소문자로 정규화 적재 → `SK`/`sk`가 한 중의 항목으로
     병합(resolve의 별칭=소문자 계약과 일치). 안 하면 둘 다 거짓 확신(is_candidate=False).
- **에러 정책(§10 정신):** market 오타·alias/ticker 빈칸은 ValueError로 시끄럽게(유니버스
  결함을 조용히 삼키지 않음). 빈 줄만 조용히 건너뜀.

### Remaining Work

1. **커밋(최우선, 사용자 지시 대기):** 기존 패턴대로 `feat:`(config.py + pipeline.py +
   dictionary.py + test_dictionary.py) → `docs:`(이 체크포인트 미러) 분리 커밋 후 푸시.
2. **유니버스 실 데이터:** 여전히 Stage0-블로킹(coverage 입력방식 §2). 메커니즘은
   준비됨 — 운영자가 CSV 주면 즉시 링크. 코드 변경 불필요.
3. **run_pipeline 라이브 호출자 없음:** `/trigger`(app/main.py:22)는 "not yet implemented"
   스텁. 온디맨드 트리거 배선이 다음 자연스러운 단계.
4. **#6.3 cluster** — 임베딩 모델 미확정(§11.3 OPEN)으로 블로킹. `STAGE1_DESIGN.md §6.3`.
5. **#6.5 event-classify** — Stage 0 관찰 데이터 부족으로 블로킹. `STAGE1_DESIGN.md §6.5`.
6. **§7 Citations 2-패스** — generate_impact 이후. 현재 brief_items.status="empty".
7. **(옵션) #5 동시성 가드 통합테스트** — Docker PG 두 연결로 advisory lock 충돌 확인.

### Notes

- **워킹트리:** 미커밋 4파일(위 files_modified). HEAD=80d695c, origin/main 동기.
- **게이트 결과:** pytest **42 passed**(31→42, +11 신규), ruff check ✓,
  ruff format --check ✓, mypy ✓(25 files). 명령: `uv run pytest -q` / `uv run ruff check .`
  / `uv run ruff format --check .` / `uv run mypy .`.
- **격리 주의(Surgical):** `uv run ruff format`이 pipeline.py의 **기존** 초과길이 2줄
  (`_freshness_cutoff` 116자, `raise PipelineAlreadyRunning`)도 정리함. 내가 만든 드리프트
  아님 — 이전 세션들이 `ruff check`만 돌리고 `ruff format --check`은 안 돌려 누적된 것
  (ruff 린터는 기본적으로 라인길이 E501 미플래그). 내가 편집한 파일이라 표준으로 맞춤.
  로직 변경 없음(공백만).
- **체크포인트 저장소 실태:** gstack `~/.gstack/.../checkpoints`는 비어 있음(restore 시
  NO_CHECKPOINTS). 실제 체크포인트는 **`docs/context/`(커밋됨)**가 단일 소스. 저장/복원 모두
  이 디렉터리 기준으로 본다. 이 파일도 gstack 미러를 함께 두지만 정본은 repo 쪽.
- **CSV 포맷 문서:** `app/pipeline/dictionary.py` 모듈 docstring에 계약 명시. `.env.example`
  없음(다른 옵션 설정들도 미문서화 — 일관). 운영자 문서가 필요하면 후속.
- **읽기 순서(다음 세션 커밋):** `git status` → `git diff` 확인 → feat 커밋 → 이 미러 docs 커밋.
- Windows uv 출력 파이프 주의: grep/head 필터 걸면 본문 사라짐, 필터 없이 실행.
- truststore: 런타임 httpx는 `truststore.SSLContext`로 OS 인증서 신뢰 필요(사내 TLS).
