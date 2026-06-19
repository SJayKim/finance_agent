---
status: in-progress
branch: main
timestamp: 2026-06-19T10:24:42+09:00
prev_checkpoint: docs/context/20260619-094722-stage1-cleanup-committed.md
files_modified:
  - pyproject.toml          # truststore 의존성 추가
  - uv.lock                 # truststore==0.10.4
  - app/collector/rss.py    # 신규 — RSS 커넥터
  - app/pipeline/dedup.py   # 신규 — SimHash dedup
  - tests/test_rss.py       # 신규
  - tests/test_dedup.py     # 신규
  # 미커밋. 853b6be(직전 세션)는 여전히 ahead 1 미푸시.
---

## Working on: #3 1차 증분 — RSS 커넥터 + SimHash dedup (게이트 그린, 미커밋)

### Summary

`/context-restore`로 094722(클린업 커밋) 복원 → 남은작업 #3 implementation 착수.
사용자 선택으로 **§5.8 코인 RSS 커넥터 + §6.2 dedup 1차(제목 SimHash)** 1종씩 구현.
순수 코어(parse/normalize/simhash)는 네트워크·DB 없이 pytest로 검증 — **14/14 통과,
ruff·format·mypy 클린**. live fetch도 실제로 돌려 **92건 수집**(CT30/CD25/Decrypt37).
전부 **미커밋**. 853b6be도 여전히 미푸시(ahead 1).

### Decisions Made

- **커넥터 1종 = Crypto RSS 선택(사용자):** 키 불필요 + 새 무거운 의존성 없음(stdlib XML)
  + 다중소스라 SimHash dedup의 자연스러운 입력 → 이번 세션 end-to-end 실행 가능.
  대안(SEC EDGAR=본문 grounding이나 더 큰 빌드+Citations는 #3 범위 밖, Naver/Finnhub=키 없음)은 보류.
- **dedup는 1차(SimHash)만:** 2차(임베딩 cosine 확정)는 §11.3 임베딩 모델 미결로 블록.
  가짜 stub 대신 명시적 seam으로 남김. `near_duplicate_groups(items, max_distance=3)`,
  64bit SimHash + union-find, 토큰 없는 제목은 짝짓기 제외(거짓군집 방지).
- **합법 경계(P5) 준수:** RSS는 `body=None`(헤드라인+요약+링크만). `sources.legal_basis`에 기록.
- **순수/IO 분리:** `parse_feed`/`normalize`는 순수(픽스처 테스트), `fetch`(httpx)/`upsert`
  (Postgres ON CONFLICT DO NOTHING 멱등)만 IO. upsert는 자동 테스트 없음(Docker DB 필요).
- **TLS 블로커 → truststore 도입:** live fetch가 `CERTIFICATE_VERIFY_FAILED`(사내 TLS
  가로채기, [[uv-system-certs-tls]]와 같은 root cause)로 실패. `truststore.SSLContext`를
  httpx `verify=`로 넘겨 OS 인증서 신뢰(fetch에만 스코프). `uv add --system-certs truststore`.
  메모리 `python-httpx-truststore-tls` 신규 기록.

### Remaining Work

1. **(대기) CLAUDE.md Gotcha 추가 승인:** httpx/requests TLS → truststore 1줄 규칙.
   제안만 했고 사용자 확인 대기(Self-Reflection 프로토콜).
2. **(대기) 커밋 여부:** 이번 #3 증분(rss.py/dedup.py/tests + pyproject/uv.lock) 미커밋.
   853b6be 푸시 여부도 여전히 미결.
3. **#3 후속:** `run_pipeline()` 데이터 스레딩 — 현재 stage들이 DB 문서를 안 받음.
   cluster 단계 + 세션 스레딩이 다음 증분. upsert를 Docker pgvector로 멱등 검증.
4. **dedup 임계 튜닝:** live 92건에서 근접중복 0군집(퍼블리셔별 헤드라인 리라이트).
   SimHash hamming≤3이 짧은 제목엔 빡빡 → §11.3 임베딩 2차가 의미상 중복을 잡아야 함.
5. **#4 잔여 조사:** Finnhub 크립토 커버리지 실측, NewsData.io 무료 한도, §11.3 KR 임베딩 벤치,
   Stage 0 founder 숙제.

### Notes

- 게이트 명령: `uv run ruff check .` / `uv run ruff format --check .` / `uv run mypy .` /
  `uv run pytest -q`. **네트워크 타는 uv 명령은 `--system-certs` 필수**(memory).
- `uv run`은 crypto_deep_research의 VIRTUAL_ENV 경고를 내지만 프로젝트 .venv를 정상 사용.
- live fetch 재현: `uv run python -c`로 `RssConnector().fetch()` → `near_duplicate_groups`.
  TLS는 truststore로 해소됨.
- 마이그레이션 검증 레시피(Docker ankane/pgvector:55432)는 094722 체크포인트 참조.
- 체크포인트는 `~/.gstack` + `docs/context/` 미러링.
- 읽기 순서(다음 세션): docs/STAGE1_DESIGN.md(§5.8·§6.2·§8) → app/collector/rss.py →
  app/pipeline/dedup.py → app/pipeline/pipeline.py(아직 골격, 스레딩 미구현).
