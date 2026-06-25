# 02 — 영향도 랭킹/정렬 (blocker 5)

## Context
프로젝트 핵심가치는 "현 시황에서 **영향 큰 종목** 추천"인데, 대시보드는 `brief_item.id`순으로만 표시한다(`app/web/queries.py:78` `.order_by(BriefItem.id)`). confidence·direction을 정렬에 반영하지 않아 중요한 브리프가 위로 오지 않는다. **마이그레이션 없이** 쿼리 정렬만으로 영향도순 노출을 구현한다(사용자 결정: 정렬만).

근거(탐색 확인):
- `BriefItem`(models.py:92): `direction?`/`confidence?` 자유문자열 nullable. 영향도 점수 컬럼 없음.
- `_PASS2_SCHEMA`(citations.py:82) enum — direction `["긍정","부정","중립"]`, confidence `["HIGH","MED","LOW"]`. analyze_impact가 brief_item에 채움.
- `load_brief()`(queries.py:70)가 유일한 정렬 지점. 템플릿(`_brief_item.html`)은 정렬 안 함(쿼리 의존).
- `case`는 이미 import(`queries.py:15`) — 추가 의존성 없음.

## 변경

### 1. `app/web/queries.py` `load_brief()`
`.order_by(BriefItem.id)`를 영향도 정렬로 교체. 의미 = **"확신 큰 + 방향성 뚜렷한 것 먼저"**:
- 1차 `confidence`: HIGH(0) > MED(1) > LOW(2) > NULL(3) — `case`
- 2차 `direction`: 긍정/부정(0) > 중립(1) > NULL(2) — **영향도=불확실성의 반대라 중립을 뒤로**(긍정·부정은 동급, 둘 다 영향 큼)
- 3차 `BriefItem.id` — 안정 정렬(동점 결정)

docstring에 정렬 의미("영향도 = 확신 우선, 중립 후순위")를 명시한다.

## 영향 파일
- `app/web/queries.py` (order_by)
- `tests/test_web.py` — `test_load_brief_groups_tickers_and_citations`의 순서 단언(`[v.status for v in views] == ["ok","empty"]`)이 깨지므로, confidence/direction을 가진 브리프를 시드해 **새 순서**를 검증하도록 갱신.

## 검증
- 단위: confidence/direction 조합이 섞인 브리프 시드 → `load_brief` 순서가 HIGH·비중립 먼저인지 단언. NULL confidence가 맨 뒤인지 포함.
- 대시보드 렌더 테스트(`test_dashboard_renders_briefs...`)는 콘텐츠만 검증이라 영향 적음(확인만).
- `uv run pytest tests/test_web.py` + `ruff` + `mypy` 그린.

## 스코프 밖
- "오늘의 영향 종목 Top N" 브리프 횡단 집계 뷰(core, 별건)는 본 문서 범위 밖 — 정렬만 한다.
- 추후 `impact_score` 컬럼 도입 시 정렬식만 교체하면 됨(마이그레이션 + pipeline 점수 계산 필요해 이번엔 제외).
