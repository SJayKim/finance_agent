# 04 — CI + 설계 하드게이트 (swap test · ticker precision)

## Context
테스트 스위트(25개 파일)는 풍부하나 **머지/배포 게이트로 강제되지 않는다**(`.github/` 부재) — 그래서 날짜 결합 회귀(time-bomb 테스트)도 머지 시점에 못 잡혔다. 또한 설계 §12·STAGE1.5 §9의 하드게이트 두 개가 코드로 강제되지 않는다: ① zero-fabrication 인용(인용↔원문 char 범위 일치), ② 티커 링킹 precision ≥95%(`link_precision` 항상 NULL). 이 문서는 CI 파이프라인 + 두 게이트 회귀 테스트를 추가한다.

근거(탐색 확인):
- 테스트는 실 Postgres+pgvector(테스트 DB 5433), `tests/conftest.py`가 TRUNCATE 격리+alembic upgrade, 미연결 시 skip. **통합테스트는 `FakeEmbedder`라 embeddings extra(torch ~2GB) 불필요.**
- `pyproject.toml`: dev 그룹 `ruff`/`mypy`/`pytest`, pytest 마커 없음.
- `Citation`(models.py:120): `cited_text, char_start?, char_end?`. 원문 = `_document_text(doc)` = `title + "\n\n" + summary`(citations.py:94) → `cited_text == 원문[char_start:char_end]` 검증 가능. `parse_pass1`(citations.py)이 char 범위 보존.
- `ticker_link`(pipeline.py:146)는 `link_precision`을 NULL로 둠(§6.4 실측 전). 모호 매치는 `resolve()`(ticker_link.py:34)가 `is_candidate=True`로 보존.

## 변경

### 1. `.github/workflows/ci.yml` (신규)
push/PR 트리거. `ubuntu-latest` + Python 3.13 + `astral-sh/setup-uv` + `ankane/pgvector` service(5433, health-check). 스텝:
- `uv sync`(dev 그룹; **embeddings extra 불필요** — 테스트는 FakeEmbedder)
- `uv run pytest` (env `TEST_DATABASE_URL`/`DATABASE_URL` = 테스트 DB)
- `uv run ruff check .`
- `uv run mypy .`

### 2. swap test — §12 하드게이트1
`tests/test_swap.py`(신규) 또는 `tests/test_citations.py` 확장: fake client `_cite()` 헬퍼가 `char_start`/`char_end`를 주입하도록 확장 → `parse_pass1` 후 **모든 인용이 `cited_text == _document_text(doc)[char_start:char_end]`인지 단언**. 순수 단위테스트(DB·네트워크 불필요). 의도적 char 범위 깨기 주입 시 red 되는지 1회 확인.

### 3. ticker precision 게이트 — §6.4
`tests/test_ticker_precision.py`(신규) + 소형 수기 라벨셋(텍스트→기대 `(ticker, market)` 수십 건). `resolve()`(ticker_link.py)로 precision 계산해 **≥0.95 단언**(스타터 게이트, 라벨 확장 가능). 실측치를 로그로 남긴다. `link_precision` 컬럼 채움은 별도(측정 코드 우선).

## 영향 파일
- `.github/workflows/ci.yml` (신규)
- `tests/test_swap.py` 또는 `tests/test_citations.py` (swap)
- `tests/test_ticker_precision.py` + 라벨 픽스처 (신규)

## 검증
- 로컬: 새 swap/precision 테스트 `uv run pytest` 그린(precision 실측치 로그 확인).
- CI: 브랜치 push → GitHub Actions가 pytest+ruff+mypy 그린(Postgres service 포함) 확인. 인용 char 범위를 일부러 깨면 swap test가 red 되는지 1회 확인.

## 스코프 밖
NLI 함의율 ≥98%(설계상 배포 비차단 약한 게이트)는 후순위 — 본 문서 제외.
