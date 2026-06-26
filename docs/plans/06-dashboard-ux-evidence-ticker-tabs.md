# 06 · 대시보드 UX 3종 — 근거 제자리보기 + 종목 링크 + 자산 탭

## Context (왜 이 작업을 하는가)

대시보드 사용 중 발견된 UX 문제 3가지에 대한 조사·진단·아이디어 정리. 워크플로(2개 심층
조사 에이전트 + 1개 적대적 검증)로 코드·실DB까지 확인했다. **이 문서는 진단 + 아이디어
정리이며, 구현은 아직 안 함**(어디부터 칠지 결정 대기).

사용자 보고:
1. 일일 다이제스트 원문을 읽다가 `근거 #nnn`을 누르면 갑자기 스크롤돼서 읽던 위치를 놓침.
   → 근거를 누르면 **그 자리에서** 어떤 근거인지 볼 수 있게 개선하고 싶음.
2. "전체" 탭의 임팩트 랭킹에 종목이 미링크되어 어떤 종목이 영향받는지 파악 안 됨.
3. "전체"에서 "주식"/"암호화폐" 탭을 누르면 빈 값으로 보임.

## 핵심 진단 (검증 완료)

**이슈 2와 3은 같은 뿌리다 — UI가 아니라 데이터 문제.**

- 오늘(06-26): 390개 이벤트 전부 임팩트 점수 매김, **티커 링크 0개**.
- `security_aliases`(종목 매칭 사전): US=10,400 / CRYPTO=8 / **KR=0**.
- KR 로더(`app/pipeline/opendart.py:78` `sync`, corp_name→stock_code, market="KR")는
  **이미 구현·테스트돼 있는데 한 번도 안 돌렸음**. 시딩을 `run_daily`에 엮는 작업이
  `docs/plans/01-seeding-wiring.md`에 계획만 있고 미구현(`app/pipeline/seed.py` 없음,
  `runner.py`에 seed 호출 없음).
- `ticker_link`(`app/pipeline/pipeline.py:143-149`)는 **대표 문서 "제목"만**, 그것도
  부분문자열로 매칭(`ticker_link.py:45` `alias.lower() not in text.lower()`). 오늘
  388/390건이 한국어 제목(코스피·한미반도체·가온전선…). 한국어 제목 × 한국 별칭 0개 = 매칭 0.
- **검증 확정:** 06-26 daily_run은 정상 완료(audit_log 04:03), `ticker_link`도 **돌긴
  돌았는데 매칭이 0**(스킵 아님 — `pipeline.py:307`에서 무조건 호출, commit은 그 뒤 `:309`).
  심지어 `analysis_text`엔 "가온전선·한미반도체"가 한국어로 적혀 있는데 매칭 대상에서 빠짐
  (brief_items 881/883에서 확인).

결과:
- 보드 카드 전부 "종목 미링크"(`_impact_board.html:13-17`, `r.tickers` 비면 표시).
- 주식/코인 탭 클릭 시 `data-asset`가 빈 카드를 전부 `display:none`
  (`index.html:108-125`, `_asset_classes`가 티커 없으면 `[]` → `data-asset=""`).
  **탭 필터에 카운트·빈 상태 처리가 없는 건 데이터와 무관한 독립 UI 버그** — 커버리지
  낮은 날엔 영원히 깨져 보임.

**이슈 1은 완전 별개:** 다이제스트의 `근거 #nnn`은 그냥 `<a href="#brief-{{ id }}">`
앵커(`_digest.html:15`)라 브라우저가 아래로 네이티브 점프. 게다가 도착지가 *접힌*
`<details>`(JS `openBrief`는 `.board-card`에만 바인딩, 디제스트 링크는 미개입).
미리보기에 필요한 데이터(event_type·방향·분석문·인용)는 **이미 그 페이지 DOM에 다 있음**
(`#brief-{id}` 노드) → 백엔드 추가 불필요. `app.css`에 `:target`/popover/modal 규칙 전무
(클린 슬레이트).

## 이슈 1 — 근거를 제자리에서 보기 (아이디어)

| 안 | 방식 | 장점 | 단점 | 완성도 |
|---|---|---|---|---|
| **A. 앵커 팝오버**(추천) | 클릭한 링크 바로 아래 작은 카드. 기존 `#brief-{id}` DOM에서 event_type·방향·첫 인용 스니펫 읽어 표시 | 가장 "제자리", 스크롤 0, 백엔드 0 | 화면 끝 위치 보정·닫기(Esc·바깥클릭) 손이 감 | 9 |
| **B. 인라인 드로어**(추천) | 디제스트 카드 바로 아래 펼침. `brief-body` 클론(분석+인용 전부) | 시선 고정, 위치계산 없음, 가장 견고, 모바일 OK | 아래 밀림(보던 지점은 유지) | 9 |
| C. htmx 사이드패널 | 새 라우트로 brief 파셜을 고정 패널 로드 | htmx 일관성 | **백엔드 신설 = DOM에 이미 있는 걸 중복**, 단일 컬럼·모바일에 자리 없음 | 9 |
| D. 모달/라이트박스 | 가운데 오버레이 | 공간 넉넉 | 읽던 텍스트를 덮음 → "제자리" 취지 어긋남 | 7 |

추천: **A 또는 B** (둘 다 백엔드 0, 기존 인라인 IIFE+CSS 토큰 패턴에 맞음).
주의: 스크롤 방식은 탭 필터로 숨겨진 brief에 착지 가능 → DOM 클론 방식 A/B가 그 함정도
피함. 클론 시 `id` 중복 제거 필수.

## 이슈 2 & 3 — 종목 링크 + 탭 (아이디어)

**데이터 쪽**
- **D1. KR 별칭 시딩**(즉효, 추천 1순위): `opendart.sync` 1회 실행 → 상장 한국 종목을
  `security_aliases`에 적재. 오늘 388/390건이 KR이라 즉시 링크 살아남. 로더·테스트 존재,
  멱등. *영구 해결*은 `seed.py` 만들어 `run_daily`에 엮기.
- **D2. 제목 말고 분석문+인용까지 매칭**: `analysis_text`·`cited_text`에 종목명이 한국어로
  이미 있음. 외부호출 0, 리콜 대폭↑. (D1 없으면 KR 0이라 둘이 같이 가야 함)

**UI 쪽**
- **U1. 탭 카운트 + 빈 상태**(오늘 바로 고침, 추천): 버튼에 `전체 N · 주식 X · 암호화폐 Y`,
  0건이면 "이 탭에 링크된 종목 없음 — 전체에서 N건" 안내. **데이터 커버리지와 무관**하게
  "탭이 깨져 보이는" 문제 제거. 수술적(템플릿+쿼리 헬퍼+JS 몇 줄).
- **U2. 코드 대신 회사명 + 클릭**: `042700` 대신 `한미반도체`. 단 `brief_item_tickers`에
  name 컬럼 없어 마이그레이션/조인 필요 — 범위 확장.

**경고(검증에서 확인된 실제 리스크)**
- D1은 §6.4 정밀도 게이트가 deferred라 **짧은 한국 종목명 오탐** 위험(단일 매핑 오탐은
  `is_candidate`로도 안 걸러짐). 또 KR 매치마다 **라이브 OpenFIGI 호출**(KS)이 일어나
  느리거나 None→전부 "후보" 표기될 수 있음.
- 옛 시딩 플랜(`docs/plans/01`)을 *그대로* 따르지 말 것 — 그 플랜의 커넥터 재배치 단계는
  현재 `runner.py`(`DEFAULT_QUERIES` 사용)와 안 맞아 불필요한 변경. KR 시딩 코어만 유효.
- D3(LLM이 종목 직접 출력)은 `pipeline.py:230`의 "영향 종목은 LLM 아니라 ticker_link가
  결정" 제로-허구 경계와 충돌 → 별도 승인 필요.

## 추천 실행 순서

1. **U1** — 탭이 안 깨져 보이게(오늘 바로, 데이터 무관).
2. **D1 1회 실행** — KR 별칭 적재 후 오늘치 재링크 → "종목 미링크" 대량 해소. 정밀도는
   라이브 1회 검증.
3. **이슈 1 = A 또는 B** — 백엔드 0, 독립 진행 가능.
4. 이후 여유되면 D2(매칭 면 확대), U2(회사명).

## 실행 환경

dev DB(컨테이너 `finance_agent_db`, 55432, DB명 `finance_agent`) 가동 필요. 빠른 진단은
`docker exec finance_agent_db psql -U postgres -d finance_agent -P pager=off -c "<SQL>"`.
runner/스크립트는 인라인 env:

```
DATABASE_URL="postgresql+psycopg://postgres:fa_local@localhost:55432/finance_agent" \
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
uv run python -m app.runner [--date YYYY-MM-DD]
```

D1 1회 실행은 `opendart_api_key`(.env) + 위 DATABASE_URL로
`uv run python -m app.pipeline.opendart`.
