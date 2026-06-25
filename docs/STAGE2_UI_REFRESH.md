# 대시보드 UI 직관화 — 카드형 보드 · 자산 배너 필터 · 날짜 칩

## Context

`/` 대시보드가 (1) 임팩트 보드를 전문 용어(G1 클러스터, 3중 인코딩) 위주 테이블로
보여줘 한눈에 안 들어오고, (2) 주식·암호화폐가 한 화면에 섞여 있고, (3) 날짜 이동이
prev/next 텍스트 링크뿐이라 특정 날짜로 점프가 불편하다. 사용자 요구 3건:

1. 임팩트 보드를 더 직관적으로 → **카드형 레이아웃**
2. 주식/암호화폐를 **배너(탭)로 구분, 해당 자산만** 표시 (보드 + 증거 브리프 전체)
3. 날짜를 **누를 수 있는 사각 칩**으로 → 클릭 시 그 날짜 보드로 이동

확정된 설계 결정(사용자 답변):
- 자산 분류: **주식 / 암호화폐 2분류** (KR+US=주식, CRYPTO=암호화폐) + `전체` 탭
- 필터 범위: **페이지 전체** (임팩트 보드 카드 + 증거 브리프)
- 보드: **카드형**
- 날짜 칩: **최근 14일 전부** (데이터 없는 날은 흐리게, 그래도 클릭 가능)

자산 구분의 단일 진실 소스는 `BriefItemTicker.market` (`KR|US|CRYPTO`,
`app/models.py:113-120`). 한 brief_item에 여러 티커가 붙어 자산이 섞일 수 있다 →
**"해당 자산 티커가 하나라도 있으면 그 탭에 노출"** 규칙(섞인 행은 양쪽 탭 모두 노출,
티커 없는 행은 `전체`에서만 노출).

## 변경 파일

### 1. `app/web/queries.py` — 파생 데이터만 추가 (순수 SELECT 경계 유지)
- 헬퍼 추가: `_asset_classes(tickers) -> list[str]` — 티커 market을 `"crypto"`(CRYPTO)
  / `"stock"`(그 외 KR·US)로 매핑해 정렬된 distinct 리스트 반환.
- `BriefView`·`BoardRow`에 `@property asset_classes` 추가 → `_asset_classes(self.tickers)`.
  (둘 다 `tickers` 보유. frozen dataclass에 property 추가는 안전.)
- `dates_with_briefs(session) -> set[date]` 추가:
  `select(BriefItem.brief_date).distinct()` → set. 날짜 칩의 has_data 판정용.

### 2. `app/main.py` — dashboard() 컨텍스트에 날짜 칩 추가
- `dates_with_briefs(session)`로 데이터 보유 날짜 set 조회(기존 SessionLocal 블록 안).
- 최근 14일 칩 리스트 생성: `today = datetime.now(_KST).date()` 기준 `today-13 … today`,
  각 항목 `{iso, label("MM-DD"), has_data(set 멤버십), is_current(==brief_date)}`.
  템플릿 컨텍스트에 `date_chips`로 전달.
- 기존 `prev_date`/`next_date`는 14일 밖 페이징용으로 유지.
- 주의: 이건 "최근 14일" 윈도(today 기준)라 별도 미해결 과제인 `_parse_date(None)=오늘`
  빈-보드 버그와 무관 — 이번 스코프에서 건드리지 않음.

### 3. `app/web/templates/_impact_board.html` — 테이블 → 카드 그리드
- `<table class="board">` 전체를 `<div class="board-cards">` + 카드 반복으로 교체.
- 카드 1개:
  ```
  <div class="board-card g{{r.group_index}}" data-brief="brief-{{r.brief_id}}"
       data-asset="{{ ' '.join(r.asset_classes) }}" data-dir="{{dk}}"
       tabindex="0" role="button" aria-label="...">
    <div class="bc-top">
      <span class="bc-tickers">{{ 티커들 · 구분, 없으면 '종목 미링크' }}</span>
      <span class="bc-impact" data-dir="{{dk}}">{부호}{{r.impact_score}}</span>
    </div>
    <div class="bc-dir" data-dir="{{dk}}">{{arrow}} {{r.direction or '중립'}}</div>
    <div class="bc-meta">
      <span class="grp g{{r.group_index}}">{{r.group_shape}} {{r.group_label}}</span>
      <span class="bc-event">{{ r.event_type or '이벤트' }}</span>
    </div>
  </div>
  ```
- 방향 표기는 **기존 데이터값 유지**(긍정/부정/중립 + ▲▼■ + 방향색). 프리뷰의 "상승/하락"
  문구를 새로 만들지 않음(zero-fabrication, 앱 일관성).
- 그룹(클러스터) 인코딩은 카드 좌측 색 보더(`g{n}`) + 작은 `.grp` 칩으로 보조 유지.
- 범례(`.board-legend`)는 카드 기준으로 한 줄 단순화.

### 4. `app/web/templates/_brief_item.html` — 루트에 자산 태그
- `<details class="brief-item ...">`(1행)에 `data-asset="{{ ' '.join(b.asset_classes) }}"`
  추가. 그 외 변경 없음.

### 5. `app/web/templates/index.html` — 자산 탭 바 + 날짜 칩 + JS
- 헤더의 `.date-nav`(32-35행)를 **날짜 칩 행**으로 교체:
  prev 화살표 + `date_chips` 반복(`<a class="date-chip {current}{no-data}" href="/?date={{iso}}">`)
  + next 화살표.
- `_impact_board` include **직전**에 자산 탭 바 추가:
  `<div class="asset-tabs"><button data-asset="all" class="active">전체</button>
   <button data-asset="stock">주식</button><button data-asset="crypto">암호화폐</button></div>`
- 하단 board-row 클릭 스크립트(86행)의 셀렉터 `.board-row` → `.board-card`로 변경.
- 자산 탭 필터 JS 추가: 탭 클릭 시 active 토글 후 `.board-card`·`.brief-item` 각 요소를
  `dataset.asset`(공백분리)에 선택 자산 포함 여부로 show/hide. `all`이면 전부 표시;
  특정 자산 선택 시 `data-asset` 빈 요소는 숨김. (날짜 칩은 순수 `<a>` 링크라 JS 불필요.)

### 6. `app/web/static/app.css` — 카드/탭/칩 스타일
- `table.board` 관련 규칙(727-791행, `.board-row`·`td.impact` 등 테이블 전용)을
  카드 스타일로 교체. `.grp.g1~g5` 색은 **재사용**(카드 보더·칩) → 유지.
- 추가: `.board-cards`(반응형 grid), `.board-card`(좌측 색보더=그룹, hover/focus,
  `.bc-impact` Mono 대형 + 방향색, `.bc-dir`, `.bc-meta`),
  `.asset-tabs`/`.asset-tabs button.active`,
  `.date-chips`/`.date-chip`(사각형, 현재=강조, `.no-data`=흐림).
- `.brief-flash`·키프레임은 유지(클릭 강조 재사용).

## 재사용 (새로 안 만듦)
- 자산 판정: `BriefItemTicker.market` (`app/models.py:113`).
- 방향→키 매핑 `{'긍정':'up','부정':'down','중립':'neutral'}`: 기존 템플릿 패턴 그대로.
- 클릭→브리프 펼침 `openBrief()` + `.brief-flash`: `index.html` 기존 스크립트 셀렉터만 변경.
- 그룹 색 `.grp.gN`: 기존 CSS 재사용.

## 검증 (end-to-end)
1. `uv run pytest` — 기존 136 테스트 그린 유지. `tests/test_web.py`에 회귀 추가:
   - `asset_classes`: CRYPTO 티커 brief→`["crypto"]`, KR+US→`["stock"]`, 혼합→둘 다,
     티커 없음→`[]`.
   - `dates_with_briefs`: 시드한 brief_date들이 set에 포함.
   - dashboard 렌더에 `data-asset`·`date-chip`·`asset-tabs`·`board-card` 마크업 존재.
2. `uv run ruff check .` / `uv run mypy .` 클린.
3. 라이브: 서버 재기동(DATABASE_URL 인라인 + HF_HUB_OFFLINE=1) 후 `/?date=2026-06-23`
   - 보드가 카드로 렌더, 카드 클릭 → 해당 증거 브리프 펼침/스크롤.
   - `주식` 탭 → CRYPTO 전용 카드·브리프 숨김, `암호화폐` 탭 → 반대, `전체` → 복원.
   - 날짜 칩 14개 노출, 06-23 강조, 데이터 없는 날 흐림, 칩 클릭 → 그 날짜로 이동.
   - 모바일 폭(<480px)에서 카드·칩 깨짐 없음.

## 메모
- 디지털 다이제스트·소스 헬스 섹션은 자산 필터 대상 아님(요구 = 보드+증거 브리프).
