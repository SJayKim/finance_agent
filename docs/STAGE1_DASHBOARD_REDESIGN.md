# 대시보드 리디자인 플랜 — "Evidence Terminal" (옵션 B: CSS + 마크업 재배치)

## Context

현재 `/` 대시보드(증거 브리프)는 기능·시맨틱은 멀쩡하나 `font-family: system-ui`
+ 흰 배경 + 회색 보더의 "브라우저 기본값" 룩이다. 금융·근거추적이라는 도메인이
줄 수 있는 신뢰감·밀도·진지함이 시각적으로 표현되지 않는다. 구체적 결함:

- 타이포: 단일 system-ui, 데이터용 모노/탭형 숫자 없음, 타입 스케일 부재(8종 폰트 크기 산재)
- 컬러: CSS 변수 0개, 회색 8종 하드코딩, **`dir-*` 클래스에 CSS가 없어 상승/하락이 시각 구분 안 됨**
- 위계/순서: 핵심 콘텐츠(브리프 추적성)가 맨 아래, 입력창이 위 → 읽기 순서 역전
- 추적성(인용 트리)이 제품의 영혼인데 `border-left:3px` 한 줄로만 표현
- 다크모드·모션 0

목표: 마크업의 시맨틱·상태 클래스 자산을 살린 채, **다크 기본 + 라이트 토글**의
에디토리얼×금융터미널 톤으로 재디자인하고, 읽기 순서를 바로잡고, 추적성 트리를
시그니처 요소로 강화한다. HTML 구조는 최소 변경, CSS는 토큰 기반으로 전면 재작성.

확정된 결정(사용자):
- 테마: **다크 기본 + 라이트 토글**(localStorage 기억, prefers-color-scheme 존중)
- 폰트: **Google Fonts CDN** (오프라인/사내망 차단 시 시스템 폰트 폴백)

## 디자인 방향

콘텐츠가 한국어라 디스플레이 폰트도 Hangul을 커버해야 한다. IBM Plex 패밀리로
통일감 + Noto Serif KR로 에디토리얼 대비:

- **디스플레이(헤더 h1/h2)**: Noto Serif KR 700 — 에디토리얼 무게, 한글 렌더
- **본문/UI**: IBM Plex Sans KR — 한글 커버, Inter/Roboto 아닌 특색
- **데이터(티커·날짜·시각·신뢰도)**: IBM Plex Mono — tabular figures, 터미널 질감
- 폴백: `'Noto Serif KR', Georgia, serif` / `'IBM Plex Sans KR', system-ui, sans-serif`
  / `'IBM Plex Mono', ui-monospace, monospace`

색 의미 인코딩(가장 큰 누락분 복구):
- 방향: 긍정→`--up`(green), 부정→`--down`(red), 중립→`--neutral`(muted)
- 신뢰도: HIGH/MED/LOW 채도·테두리 등급
- 브랜드 액센트: amber/gold(추적·하이라이트). 보라 그라데이션 금지.

## 변경 파일

### 1. `app/web/static/app.css` — 전면 재작성 (토큰 기반)
- `:root`에 디자인 토큰 정의: 색(bg/surface/border/text 3단계/up/down/neutral/accent),
  타입 스케일(--fs-1..6), 간격, radius, shadow, font 변수 3종.
- 다크가 `:root` 기본. `:root[data-theme="light"]`가 색 토큰만 오버라이드.
  `@media (prefers-color-scheme: light)`로 저장된 선호 없을 때 초기값 보정.
- 기존 셀렉터(.brief-item/.digest-card/.source-chips/.citations 등) 토큰으로 재구현.
- **신규: 방향/신뢰도 색** — `[data-dir="up|down|neutral"]`, `[data-conf="HIGH|MED|LOW"]`.
- **추적성 트리 강화**: 인용 리스트를 연결선(좌측 트리 가지)+출처 칩+발행시각(mono)로.
- 모션: 페이지 로드 staggered reveal(`@keyframes` + `animation-delay`, prefers-reduced-motion 가드),
  `<details>` open 트랜지션, htmx 요청 중 로딩 인디케이터(`.htmx-request`).
- `summary:focus-visible` 등 포커스 링 추가(접근성).
- 데이터 요소(.market/.pub/.confidence/.meta 날짜)에 mono + `font-variant-numeric: tabular-nums`.

### 2. `app/web/templates/index.html` — 헤드/순서/토글
- `<head>`: Google Fonts `<link>`(preconnect+stylesheet) 추가.
- `<head>` 끝에 **플래시 방지 인라인 스크립트**(localStorage→`data-theme` 적용, paint 전).
- 헤더에 테마 토글 버튼(`<button id="theme-toggle">`) + 클릭 시 토글·저장 인라인 스크립트.
- **읽기 순서 재배치**: 헤더 → 소스헬스(접힌/축소 바) → **다이제스트(요약, 상단)** →
  **브리프(추적성 상세)** → 채팅(하단 보조). 현재 채팅이 최상단인 것을 내림.
  (텍스트 문자열·`{% include %}`·`id`는 보존, 순서만 변경)

### 3. `app/web/templates/_brief_item.html` — ASCII 시맨틱 훅 추가
- direction span에 `data-dir` 부여(한글 클래스 셀렉터 회피):
  `data-dir="{{ {'긍정':'up','부정':'down','중립':'neutral'}.get(b.direction,'neutral') }}"`
- confidence span에 `data-conf="{{ b.confidence }}"`(이미 ASCII HIGH/MED/LOW).
- 인용 `<li>` 구조에 트리 가지용 래퍼 클래스 1개 추가(텍스트·href·blockquote 보존).

### 4. `app/web/templates/_digest.html`, `_source_health.html`, `_chat_answer.html`
- 신규 토큰/클래스에 맞춘 최소 클래스 조정만. **모든 텍스트·href·`#brief-{id}` 앵커 보존.**

## 재사용 / 보존 제약 (테스트 깨지지 않게)

`tests/test_web.py`가 HTML 본문 문자열을 단언한다. 다음을 **반드시 보존**:
- 문자열: `price_move`, `긍정`, `MED`, `Bitcoin tops $100K`, `후보`, `근거 없음`,
  `브리프 없음`, `관련 근거 없음`, `채팅 비활성`, `다이제스트 없음`
- 속성: `href="..."`(원문 링크), `id="brief-{id}"`(다이제스트 딥링크 타깃 `#brief-{id}`)
- direction/confidence 값 자체는 표시 텍스트로 유지(클래스가 아닌 `data-*`로 색 인코딩하므로 안전)

direction enum은 `app/pipeline/citations.py:86`에서 `긍정/부정/중립` 고정,
confidence는 `HIGH/MED/LOW` 고정 — 매핑 안전.

## 검증

1. **테스트**: `uv run pytest tests/test_web.py` — 전부 통과(문자열·href 단언 보존 확인).
2. **린트**: `uv run ruff check .` (CSS/HTML은 대상 아님; 파이썬 무변경이라 통과 유지).
3. **라이브 육안 확인**: `uv run uvicorn app.main:app` 후
   `http://localhost:8000/?date=2026-06-23`(시딩 DB 55432, env로 DATABASE_URL 주입) 접속해서:
   - 다크 기본 렌더, 토글 클릭 시 라이트 전환·새로고침 후 선호 유지(localStorage)
   - 긍정/부정/중립 브리프의 방향 색 구분, 신뢰도 등급 표시
   - 다이제스트 `근거 #N` 클릭 → 해당 브리프로 스크롤(앵커 동작)
   - 인용 트리 + 원문 링크, 소스헬스 칩
   - 채팅(키 있으면) 응답·로딩 인디케이터
4. **모바일 폭**(≤480px)에서 폼·칩·티커 wrap 정상.
5. **reduced-motion**: OS 설정 on이면 reveal 애니메이션 비활성 확인.

## 비고 / 범위 밖

- 누적 RAG 채팅은 임베딩(`embedded=0`) 설치 전까지 비활성 — 이 플랜 범위 밖(별도 작업).
- 파이썬 로직(`main.py`/`queries.py`/`chat.py`) 무변경 — 순수 프론트(템플릿+CSS) 작업.
