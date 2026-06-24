# STAGE 2 — UI 자료조사: Evidence Terminal 대시보드

> 목적: 타깃 사용자(전문/액티브 트레이더)를 기준으로 동종 서비스 케이스 스터디 →
> 트렌드 매핑 → JTBD → 우선순위 개선안 → 스택 방향성 비교를 수행하고, 시각 시안
> (`docs/mockups/`)으로 연결한다. **본 문서는 조사·비교 자료이며 프로덕션 결정이 아니다.**
>
> 도메인 규칙(서비스 원칙과 동일): 모든 개선 제안은 케이스/트렌드/JTBD **근거로
> 역추적**되게 남긴다. 추천 근거를 항상 남기는 제품 철학을 디자인 제안에도 적용.

조사 방법: `firecrawl_search`(웹/뉴스) 1차, 핵심 페이지 `firecrawl_scrape`. 페이월 앱
내부는 공개 리뷰·문서·제품 페이지로 대체. 조사일 2026-06-24.

---

## 0. 베이스라인 — 현재 우리 UI

`app/web/templates/index.html` + `app/web/static/app.css` 기준.

- **레이아웃**: 단일 컬럼 `max-width: 56rem` 중앙 정렬. 헤더 → 소스 헬스 칩 →
  일일 다이제스트 카드 → 증거 브리프(접이식 `<details>`) → 근거 기반 채팅.
- **신뢰·근거**: `citations` **인용 트리**(CSS `::before/::after`로 트리 가지) —
  blockquote 인용문 + 발행시각(`pub`) + 원문 링크. 우리 시그니처.
- **종목 임팩트**: 브리프마다 `direction`(긍정/부정/중립, 좌측 보더 색) +
  `confidence`(HIGH/MED/LOW 배지) + `tickers` 칩(market·후보).
- **신선도**: 헤더 `last_updated`, 소스 헬스의 `ran_at`, 인용별 발행시각. 단
  "N분 전" 상대 신선도·decay·Live 배지는 없음.
- **실시간/인터랙션**: HTMX 서버 렌더. 채팅만 `hx-post`. 정렬·필터·저장된 뷰·
  키보드 내비·다중 비교 없음. 모션: reveal 페이드 + `prefers-reduced-motion` 대응.
- **강점(자산)**: 디자인 토큰(다크 기본 + 라이트 토글, 방향색, confidence 배지,
  모노스페이스 tabular 숫자), 인용 트리, 접근성 포커스 링.
- **갭(가설)**: 리테일 밀도 단일 컬럼 / 종목 중심 재구성·필터·저장된 뷰 부재 /
  상대 신선도·decay 부재 / 뉴스↔종목 인과의 정량 viz 약함 / 색 단독 방향 인코딩.

---

## Phase 1~2 — 케이스 스터디 (9개, 3 클러스터)

각 서비스를 동일 루브릭(정보밀도·신뢰표현·신선도·종목임팩트·탐색필터·AI통합·
취할점/버릴점)으로 분해. 출처 URL은 각 항목에 인라인.

### 클러스터 A — AI 근거/리서치 툴 (citation·신뢰·근거 추적)

#### A1. AlphaSense — 기관급 시장정보 검색
출처: alpha-sense.com/platform/smart-summaries, help.alpha-sense.com Navigation,
intuitionlabs.ai/articles/alphasense-platform-review

- **정보밀도**: 커스터마이즈 대시보드 착지 + 검색바 2개 좌우 분리(Keyword /
  Company&Ticker). 결과 리스트 + 좌측 소스 필터 사이드바, 멀티탭·saved searches.
- **신뢰·근거**: Smart Summaries가 **요약 문장마다 원문 정확한 스니펫으로
  deep-link 인용**(1클릭 검증). 우리 트리의 leaf를 "문장 단위"로 내릴 레퍼런스.
- **신선도**: real-time content + Smart Alerts(신규 파일링·트랜스크립트·뉴스 푸시).
- **종목 임팩트**: **Sentiment 델타 정렬**(전분기/전회 대비 Most/Least Change) +
  시계열 차트. 절대값이 아닌 "변화량"이 트레이더 임팩트 신호.
- **탐색·필터**: 소스/버티컬 필터, 정렬 6종, Smart Synonyms, annotation·clip.
- **AI 통합**: 사전 생성 Smart Summary 티어시트 + Prepackaged questions(SWOT/
  bull-bear 등 정형 질문 버튼화 → 매번 타이핑 제거).
- **취할 점**: ① 문장→스니펫 deep-link 인용 정밀도, ② **sentiment 델타 정렬·차트**.
  **버릴 점**: 검색바 2개 분리 + 방대한 필터 → 학습곡선·정보 과부하(반복 약점).

#### A2. Perplexity Finance — 실시간 인용 AI
출처: perplexity.ai/finance, sidsaladi.substack.com Perplexity Finance 101

- **정보밀도**: 상단 마켓 오버뷰 스트립(지수 선물 + VIX, 포인트·% 동시) + 탭(US/
  Crypto/Earnings) + 2025 추가 **섹터 히트맵**. 답변은 대화형 단일 컬럼이라 밀도 낮음.
- **신뢰·근거**: "모든 데이터 포인트가 원출처로 traceable, 환각이 아닌 auditable"
  프레이밍 + **명시적 소스 화이트리스트**(SEC/EDGAR, FactSet, S&P, Quartr 등).
- **신선도**: 선물·VIX 실시간, 라이브 트랜스크립트, Price Alerts, 반복 리서치 Tasks.
- **종목 임팩트**: Market Summary = AI 시황 + 인용 뉴스 직결. 정량 방향/conf viz는 약함.
- **탐색·필터**: 자연어 쿼리가 1차. Plaid 브로커리지 연결→Portfolio, 파워 프롬프트.
- **AI 통합**: AI-네이티브 — 링크 리스트 대신 합성된 cited·structured 답변.
- **취할 점**: ① 상단 마켓 스트립 + 섹터 히트맵(고밀도 즉시 스캔), ② **소스
  화이트리스트로 "환각 아님" 신뢰 프레이밍을 UI에 노출**. **버릴 점**: 대화형 단일
  컬럼 위주 → 멀티패널 동시성 약함(chat은 보조, 패널 그리드를 주력으로).

#### A3. FinChat / Fiscal.ai — 대화형 펀더멘털 리서치
출처: wallstreetzen.com/blog/finchat-io-fiscal-ai-review

- **정보밀도**: 좌측 6섹션 내비(Copilot/Dashboard/Analysis/Charting/Screener/
  Resources), clean 대시보드(학습곡선 완만), 커스터마이즈 행 제한(플랜별).
- **신뢰·근거**: Copilot 응답마다 citation, **Chat with Filings**(PDF 대신 disclosure
  직접 질문). 단 "추천→근거 트리"가 아니라 답변 하단 출처 나열형.
- **신선도**: 실시간 가격, 포트폴리오 알림. 펀더멘털 중심이라 "최신 파일링" 신선도.
- **종목 임팩트**: 직접 "뉴스→임팩트" viz 약함. estimates·revisions·consensus로 기대치.
- **AI 통합**: 자연어 프롬프트→**표·차트·인용 인라인 응답**, 프롬프트로 DCF/스크린 생성.
- **취할 점**: ① **도메인 특화 AI를 벤치마크 수치로 신뢰 마케팅**(FinanceBench 2~4배 →
  우리도 추천 정확도/근거 적중률 노출), ② 자연어→정량 산출물. **버릴 점**: 펀더멘털
  단일 포커스(크립토·실시간 뉴스 모멘텀 누락) — 우리 도메인과 정반대.

**클러스터 A 수렴 — 공통 패턴 / 차별 포인트**

| 축 | 공통 패턴(A) | 우리 차별 기회 |
|---|---|---|
| 인용 | deep-link로 "검증 1클릭"이 기본기(깊이는 차등) | 평면 citation list가 한계 → **추천→이벤트→소스+발행시각 인과 트리**는 아무도 안 함 |
| 신뢰 | 명시적 소스 화이트리스트로 "환각 아님" 프레이밍 | 크롤링 소스 신뢰도·발행시각을 UI 1급 시민으로 |
| AI 진입 | 챗 1차 + 정형 질문/프롬프트 보조(타이핑 마찰 제거) | 추천 트리에 정형 질문 버튼(왜 이 종목?/어떤 뉴스?/반대 근거?) |
| 밀도 | 대화형은 밀도 낮고, 고밀도는 과부하 | **터미널 밀도 + AlphaSense급 인용 정밀도를 과부하 없이** |

### 클러스터 B — 프로 트레이더 뉴스 터미널 (밀도·실시간·임팩트)

#### B1. Benzinga Pro — 속도 + WIIM
출처: benzinga.com/pro/feature/newsfeed, traderhq.com Benzinga 리뷰, luxalgo.com 분석

- **정보밀도**: 멀티모니터 전제. 좁고 빠른 헤드라인 리스트 칼럼 중심 + 스캐너/
  Signals/캘린더/챗 묶음 워크스테이션.
- **신뢰·근거**: 헤드라인마다 소스 라벨(Benzinga Wire/SEC Filings/Press 등). **WIIM
  (Why Is It Moving)** = 급등락 이유 한 문장, 종목 상세 상단 + 필터 가능.
- **신선도**: **Audio Squawk**(브레이킹을 음성 낭독 — 킬러 기능), 사운드/데스크탑
  알림, 독점 스토리 최대 30분 선행 주장.
- **종목 임팩트**: 특허 **price sentiment engine**(뉴스의 종목 이동 확률·방향을
  헤드라인 옆 인디케이터), Signals(가격 스파이크·블록 트레이드·거래정지·52주 신고가).
- **탐색·필터**: sources/categories/screener/watchlists/price/mktcap/volume, 커스텀 저장.
- **취할 점**: ① **WIIM 패턴**(종목 카드 상단 "왜 움직이나" 한 문장 + 근거 뉴스 링크)
  → 우리 citation-tree 진입점으로 이상적, ② 방향·확률 인라인 배지. **버릴 점**:
  핵심 기능(스캐너·스쿽·AI)을 상위 티어 게이팅 → 근거를 페이월 뒤로 숨기지 말 것.

#### B2. TradingView — News Flow 스크리너 + AI 코퍼릿 뉴스
출처: tradingview.com/blog AI-powered news, news-flow 지원문서, fxnewsgroup.com 기사

- **정보밀도**: 3분할(필터 패널 / 발행시각 정렬 리스트 / 선택 뉴스를 **팝업 아닌
  split-screen 본문**). Split View로 스크리너·캘린더 병치.
- **신뢰·근거**: AI 요약 각 스토리에 **원본 파일링 직접 링크**(8-K/10-K/Form 4 등) —
  "Verification: 공식 문서에서 직접 추출한 사실 요약"(의견 아님) 명시.
- **신선도**: 새 헤드라인이 새로고침 없이 등장하며 **두 번 깜빡임(flashes twice)**,
  AI 요약은 파일링 후 몇 분 내, 커스텀 피드 매칭 푸시.
- **종목 임팩트**: 뉴스↔심볼 1급 시민(Symbol/Watchlist/Market 필터), 결과 다중선택→
  워치리스트 일괄 추가.
- **탐색·필터**: 다축 필터(Watchlist/Symbol/Market/Corporate/Region/Provider) +
  **풀 키보드 내비**(↓ 선택, Enter 본문, ↑↓/PgUp/PgDn/Home/End, Tab 포커스 전환,
  Esc 닫기 — split 열리면 본문 동기화), 필터 조합 저장·알림.
- **AI 통합**: 이벤트 유형별 구조화 요약(Earnings 매출·EPS / M&A 딜구조 / Management
  인사 테이블 / Insider).
- **취할 점**: ① **"AI 요약 + 원문 직링크"를 한 카드에**(citation-tree 최소 단위),
  ② **풀 키보드 내비 + split-view**(팝업 금지, 리스트↔본문 동기화), ③ 이벤트 유형별
  구조화 요약. **버릴 점**: 필터 축 6개+ 초기 인지부하 → 기본 "임팩트순" 한 화면 +
  필터 점진 노출.

#### B3. Koyfin — 위젯 그리드 + 컬러 그룹 링크
출처: koyfin.com/help my-dashboards-groups, mydashboards-myd, my-views

- **정보밀도**: 한 대시보드에 watchlist 테이블/차트/뉴스/scatter 위젯 자유 배치.
  **My Views**로 칼럼 세트 저장·재사용.
- **종목 임팩트**: **Market Movers**(우측바) 드래그&드롭으로 위젯에 종목 투입,
  종목↔뉴스/차트를 **컬러 그룹(1~7)으로 동기화** — 한 위젯에서 종목 바꾸면 같은
  그룹 전체 갱신.
- **신선도**: Market Movers 실시간, 워치리스트 실시간 시세.
- **탐색·필터**: Security Selection(Single/Multiple/Watchlist) 위젯별 토글, Shift
  일괄 선택, 대시보드·뷰 저장·공유.
- **취할 점**: ① **컬러 그룹 링크**(추천 종목 클릭 → 같은 그룹 근거뉴스·타임라인·
  차트 동시 갱신 — citation-tree 탐색에 응용), ② 저장 가능한 View(칼럼 프리셋).
  **버릴 점**: 완전 자유 위젯 배치 = 빈 캔버스 진입장벽 → 기본 레이아웃 고정 제공.

**클러스터 B 수렴**: "한 줄 요약 + 원문 직링크"가 신뢰 표준 단위(둘 다 뉴스→종목
1단계만; 우리는 다단 트리로 앞섬) · 종목이 동기화 축(linkage 1급 시민) · 신선도는
**저자극 모션(행 플래시) + 패시브 알림** · 밀도/진입장벽 트레이드오프 → **단일 디폴트
화면 후 필터 점진 노출** · 터미널다움 = 키보드 + split-view + 저장된 뷰.

### 클러스터 C — 크립토 리서치 (코인 커버리지·온체인 근거)

#### C1. Messari — AI 어시스턴트 + 인용된 리서치
출처: messari.io/products/copilot, messari.io/ai

- **정보밀도**: Copilot 챗(밀도 낮음) + 별도 데이터 뷰(Screeners/Watchlists/Datasets)
  표·그리드 고밀도 — "대화형 AI"와 "터미널형 데이터" 듀얼 모드 분리.
- **신뢰·근거**: **라인별 인용(line-by-line citations)** + "Fresh Data → Data Experts →
  Messari Research" 출처 계보 라벨. 범용 AI와 비교표로 "큐레이팅 출처/인용" 세일즈.
- **신선도**: **"15분 이내 신선도" 정량 보장**, 500+ 뉴스 소스, AI Daily Recaps,
  Watchlist AI Digests.
- **종목 임팩트**: Signals·Asset Monitoring·Project Recaps로 자산별 이벤트 집계.
- **AI 통합**: Copilot(즉답) + Deep Research(구조화 리포트) + Scheduled Tasks(정기 자동).
- **취할 점**: ① **라인별 인용 + 출처 계보 라벨**, ② **"15분 이내" 정량 신선도 배지**.
  **버릴 점**: 챗 단독 화면은 트레이더에게 밀도 부족 → 챗만 단독으로 띄우지 말 것.

#### C2. The Tie (Terminal) — 위젯 기반 institutional 터미널
출처: thetie.io/solutions/terminal

- **정보밀도**: 최고 밀도. **400 커스터마이즈 위젯** 격자 배치, institutional 프리셋
  + 커스텀, 차트 옆 SEC filings 사이드바 식 맥락 동시 표시.
- **신뢰·근거**: 뉴스 소스 **카테고리 태깅**(Central Banks/Court Cases/SEC filings 등)
  으로 출처 유형을 필터·표시.
- **종목 임팩트**: **차트 위에 뉴스·언락·토큰이동 이벤트 오버레이**로 "퍼포먼스
  드라이버" 시각 귀속, 자산 taxonomy(Sectors/Ecosystems).
- **AI 통합**: **AI Narrative Engine**(마켓 테마 진화 실시간 추적 — 우리 클러스터/
  내러티브 개념과 직결), AI Widget Studio(자연어 위젯 생성).
- **취할 점**: ① **차트 위 뉴스/이벤트 오버레이로 가격↔뉴스 인과 시각화**, ② 소스
  유형 태깅 필터. **버릴 점**: 400위젯 + SQL 빈 캔버스 자유도 → 큐레이팅 프리셋 필수.

#### C3. Nansen — 온체인 증거 + Smart Money 신호
출처: nansen.ai, nansen.ai/post smart-money guide

- **정보밀도**: Smart Money Leaderboard, **Token God Mode**(한 토큰의 보유자·거래·
  잔고 변동 종합), Portfolio(크로스체인 PnL) — 표·랭킹 고밀도.
- **신뢰·근거**: **라벨링이 곧 근거**(Smart Money Funds/LPs 등 지갑 라벨로 "누가"
  움직였는지 귀속), 검증된 트랙레코드가 신뢰 장치.
- **신선도**: 500M+ 지갑 real-time, 실시간 커스텀 알림(대량 inflow/신규 매수).
- **종목 임팩트**: **net inflow/outflow·집중도·누적 vs 매도** 방향 신호 + 귀속 엔티티.
- **취할 점**: ① **신호에 "귀속 엔티티/근거"를 항상 동반**, ② 방향성+집중도 viz.
  **버릴 점**: **agentic trading(즉시 거래 실행)은 우리 도메인 원칙(투자 권유 아님)과
  충돌 → 절대 도입 금지.**

**클러스터 C 수렴**: 근거 표면화가 공통 신뢰 장치(라인별 인용/소스 태깅/지갑 라벨 —
우리 인용 트리가 정석) · **신선도를 정량 약속으로**("15분 이내", real-time) ·
이벤트↔자산을 **차트 위 시점 마커 오버레이**로 인과 시각화 · 큐레이팅 프리셋 + 제한적
커스텀 · AI는 "챗 단독"이 아닌 **데이터 뷰 + 챗 + 정기 리포트 삼각편대**.

---

## Phase 3 — 트렌드 매핑 (2025~2026)

조사한 트렌드를 **현재 우리 UI 상태 → 갭 → 개선 방향** 3열로 매핑. (출처: Smashing
2025.09 realtime / 2025.12 XAI, Bloomberg Terminal UX, datawrapper colorblindness,
IxDF progressive disclosure, daily.dev HTMX vs React.)

| 트렌드 | 현재 우리 UI | 갭 | 개선 방향 |
|---|---|---|---|
| **1. Source-grounded 인용 + "왜 이 추천" 기여도 분해** (XAI) | 인용 트리 보유(평면) | "왜 이 종목"을 ▲올린/▼내린 근거로 분해 안 함 | 추천마다 기여 요인 분해(▲상승 뉴스/▼하락 뉴스) + 트리 드릴다운 |
| **2. Data freshness 명시 + 시점 decay** | 발행시각·last_updated 절대시각만 | "N분 전" 상대·Live/Stale 배지·decay 없음 | "as of HH:MM" + 상대 신선도 배지, 오래된 근거 흐림 |
| **3. 델타 인디케이터 + 스파크라인** | direction 색 + confidence 배지 | 영향도 추세·변화량 시각화 없음 | 임팩트 델타(▲/▼) + 미니 스파크라인, 행 단위 비교 |
| **4. 터미널 미학 / 모노스페이스 tabular 숫자 + 고대비** | 모노 폰트·tabular-nums·다크 보유 | 숫자 컬럼 정렬·"통제된 밀도" 그리드 부재(단일 컬럼) | 가격·델타·티커·시각을 모노 컬럼 정렬, 멀티패널 그리드 |
| **5. Progressive disclosure (retail→pro) + 밀도 토글** | `<details>` 접이식 부분 적용 | 밀도 토글(compact/comfortable)·단계 노출 부재 | 기본 한 줄 근거 → 펼치면 풀 트리·원문·점수, 밀도 토글 설정 |
| **6. Colorblind-safe 이중 인코딩 (색+화살표/부호)** | direction 색 단독 | 색 제거 시 방향 구분 불가 | 상승=▲+초록 / 하락=▼+빨강 항상 부호·아이콘 동반 |
| **7. Reduced-motion + ARIA live 갱신** | reduced-motion 대응됨 | 실시간 갱신 ARIA live·갱신 모션 토글 미비 | 행 플래시 갱신 + ARIA live, reduced-motion 시 정적 폴백 |
| **8. 스택: HTMX 유지 + 고밀도 인터랙션만 JS island** | HTMX 서버 렌더(채팅만 동적) | 다중 필터 교차·동시 비교 클라 상태 없음 | 피드·트리는 HTMX 유지, 다중 비교만 Alpine/JS island |

---

## Phase 4 — 소비자 관점 JTBD (전문/액티브 트레이더)

페르소나: 하루 여러 번 열어 빠르게 스캔, 노이즈를 거르고, 근거를 즉시 확인하려는
액티브 트레이더. 각 JTBD는 Phase 2~3 관찰 패턴 기반(추측 아님). 현재 충족도(상/중/하)
+ 마찰점.

| # | Job-to-be-done | 근거(케이스/트렌드) | 현재 충족도 | 마찰점 |
|---|---|---|---|---|
| J1 | **"장 열리기 전 오늘 무엇이 중요한지 30초 안에"** | Messari Daily Recap, Perplexity Market Summary, 트렌드3 델타 | 중 | 다이제스트 있으나 임팩트 랭킹·델타 스캔 없음; 단일 컬럼 스크롤 |
| J2 | **"이 추천을 믿어도 되나? 근거가 신선한가?"** | AlphaSense deep-link, Messari "15분 신선도", 트렌드1·2 | 중 | 인용 트리 있으나 상대 신선도·decay·소스 신뢰 라벨 없음 |
| J3 | **"왜 이 종목이 움직이나"를 한 줄로** | Benzinga WIIM, TradingView AI요약+직링크 | 하 | 브리프를 펼쳐야 분석 보임; 카드 상단 한 줄 "왜" 없음 |
| J4 | **"내 관심 종목/섹터만 빠르게"** | TV Symbol 필터, Koyfin 워치리스트·My Views | 하 | 필터·워치리스트·저장된 뷰 전무; 종목 중심 재구성 불가 |
| J5 | **"뉴스↔종목 인과를 눈으로"** | The Tie 차트 오버레이, Nansen 방향 신호+귀속 | 하 | 뉴스→종목 정량 방향·시점 인과 viz 없음 |
| J6 | **"더 깊게 파고싶다"(근거 기반 Q&A)** | Messari Copilot, FinChat 프롬프트, Perplexity | 상 | 채팅 보유. 단 추천 트리와 분리(정형 질문 버튼 없음) |

---

## Phase 5 — 개선안 (임팩트 × 노력)

Phase 2~4 종합. 각 항목: 무엇 · 왜(근거) · 현 스택 난이도. 우선순위 = 임팩트/노력.

### Quick win (높은 임팩트 · 낮은 노력) — 현 스택에서 바로

| # | 개선안 | 왜(근거) | 현 스택 난이도 |
|---|---|---|---|
| P1 | **카드 상단 "왜 움직이나" 한 줄(WIIM형)** — 펼치기 전에 분석 요지 1문장 | J3, Benzinga WIIM, TV 요약 | 하(템플릿 1줄, 분석 첫 문장 노출) |
| P2 | **상대 신선도 배지 + decay** — "12분 전" + 오래된 근거 흐림, Live/Stale | J2, 트렌드2, Messari/도메인 규칙 | 하(서버서 상대시간 계산 + CSS opacity) |
| P3 | **방향 이중 인코딩(색+부호/아이콘)** — ▲상승/▼하락 항상 부호 동반 | 트렌드6, 접근성 | 하(템플릿+CSS, 자산 토큰 재사용) |
| P4 | **소스 신뢰 라벨 표면화** — 인용에 소스 유형/신뢰 칩(SEC/언론/블로그) | A2·C2, 도메인 규칙(소스 신뢰도 반영) | 중(소스 메타 분류 필요) |
| P5 | **정형 질문 버튼** — 트리에 "어떤 뉴스?/반대 근거?/관련 종목?" 칩→채팅 | J6, A1 Prepackaged, A3 프롬프트 | 하(채팅 prefill 링크) |

### Big bet (높은 임팩트 · 높은 노력) — 시안으로 검증

| # | 개선안 | 왜(근거) | 현 스택 난이도 |
|---|---|---|---|
| P6 | **임팩트 랭킹 보드(델타+스파크라인)** — 종목/이벤트를 임팩트순 정렬 테이블 | J1·J5, 트렌드3·4, AlphaSense 델타 정렬 | 중~상(랭킹 산출 + 스파크라인) |
| P7 | **종목 중심 재구성 + 컬러 그룹 링크** — 종목 클릭→근거·타임라인 동시 점등 | J4·J5, Koyfin 컬러 그룹, TV 심볼 동기화 | 상(클라 상태→JS island) |
| P8 | **필터 + 워치리스트 + 저장된 뷰** — 관심 종목/섹터/이벤트 유형 필터·저장 | J4, TV 다축 필터, Koyfin My Views | 상(다중 필터 교차→JS island) |
| P9 | **뉴스↔종목 인과 오버레이** — 추천 카드/미니차트에 트리거 뉴스 시점 마커 | J5, The Tie 오버레이, Nansen 귀속 | 상(차트 컴포넌트 필요) |
| P10 | **멀티패널 터미널 레이아웃(밀도 토글)** — 단일 컬럼→그리드, compact/comfortable | J1·트렌드4·5, B 전반(Koyfin/The Tie) | 상(레이아웃 재설계) |

### 보류 / 안티골 (도메인 원칙 충돌·과함)

- agentic trading(Nansen) — 투자 권유 아님 원칙 위배, **도입 금지**.
- 400위젯·SQL 빈 캔버스(The Tie) — 1인 운영 과함; 큐레이팅 프리셋으로 대체.
- 핵심 근거의 페이월 게이팅(Benzinga) — 우리는 근거가 시그니처, 숨기지 말 것.

**상위 3개(시안 연결, Phase 7):** P1(WIIM 한 줄) + P6(임팩트 랭킹 보드) + P7/P10
(종목 중심·멀티패널). 시안 3안으로 비교.

---

## Phase 6 — 스택 방향성 비교

Phase 5 개선안(특히 P6~P10의 다중 필터·실시간·밀집 인터랙션)을 감당할 스택 비교.
**결정이 아니라 비교 자료.**

| 평가축 | A. 현 스택 유지 (HTMX+Jinja2 강화) | B. 부분 리플랫폼 (셸만 SPA) | C. 전면 리플랫폼 (Next.js 등) |
|---|---|---|---|
| 개선안 적합도 | Quick win(P1~P5)·랭킹 보드(P6)·트리 펼침 ◎. 다중 필터 교차(P8)·동시 비교(P7) △ | 대시보드 셸만 SPA, 데이터는 현 API. P7~P10 ◎, 인용 트리는 서버 조각 재사용 | 전 화면 SPA. 모든 개선안 ◎, 인터랙션 최상 |
| 개발/유지비용 | 최저(기존 템플릿·토큰 그대로) | 중(SPA 셸 + API 계약 추가) | 높음(별도 프론트·빌드·배포·인증 재구축) |
| 인터랙션 품질 | 중(서버 왕복; HTMX 부분 swap) | 상(클라 상태로 즉시 필터·비교) | 최상 |
| 1인 운영 현실성 | ◎(스택 단순, 배포 1개) | ○(경계 명확하면 관리 가능) | △(풀스택 2개·CI·SSR 복잡) |
| 기존 자산 재사용 | ◎(토큰·템플릿 100%) | ○(토큰 재사용, 템플릿 일부) | △(토큰 CSS만, 템플릿 재작성) |
| 트렌드8 정합 | "HTMX 적합" 구간(피드·트리) | "고밀도만 JS island" 권고와 정합 | 과투자(우리 규모엔 오버킬) |

**권고: A를 기본으로, P7~P9의 고밀도 인터랙션만 Alpine.js/경량 JS island로 보강
(사실상 A↔B 사이의 "A+").** 근거:
- 트렌드8(2025 합의): 피드·추천 리스트·citation tree 펼침은 HTMX 서버 렌더에
  정확히 맞음 — 유지가 합리적. 다중 티커 교차 필터·동시 비교만 클라 상태가 필요.
- 1인 운영 + 기존 토큰/템플릿 자산(Phase 0 강점)을 100% 살리면서, 비싼 개선안만
  국소적으로 JS island를 얹는 게 비용/효과 최적.
- 전면 리플랫폼(C)은 현재 데이터 규모·운영 인력 대비 오버킬. P6~P10이 실사용으로
  검증되고 클라 상태가 전면화되면 그때 B→C 재평가.
- **마이그레이션 개략(필요 시 B):** ① 현 Jinja 부분(`_brief_item`·`citations`)을
  HTMX 조각 엔드포인트로 유지 → ② 대시보드 셸(필터·랭킹 보드·종목 그룹 링크)만
  Alpine 또는 경량 Svelte island로 → ③ 데이터는 현 `queries.py` 뷰모델 JSON화.

---

## Phase 7 — 시각 시안 (목업)

`docs/mockups/`에 정적 HTML 3안(현 디자인 토큰 재사용, 실데이터 불필요).
브라우저로 열어 베이스라인과 비교. 각 안에 "반영한 개선안" 캡션 포함.

| 안 | 컨셉 | 반영 개선안 |
|---|---|---|
| `mockup-1-enhanced.html` | **현 스택 강화형** — 단일 컬럼 유지 + WIIM 한 줄·신선도 배지·이중 인코딩·정형 질문 | P1·P2·P3·P5 (전부 Quick win, 현 스택 그대로) |
| `mockup-2-terminal.html` | **터미널 밀집형** — 멀티패널 그리드(임팩트 랭킹 보드 + 종목 중심 + 근거 패널) | P6·P7·P8·P10 (Big bet, A+ 스택) |
| `mockup-3-evidence.html` | **근거-퍼스트형** — citation tree를 전면 시그니처화 + 인과 오버레이 | P1·P4·P9 + 트리 드릴다운 |

> 목업은 **의사결정용 비주얼**이며 프로덕션 코드 아님. 토큰(`app.css` 변수)을
> 인라인 복제해 실제감 유지.

---

## Verification

- [x] 케이스 스터디 9개(클러스터 A/B/C 각 3) — 각 루브릭·출처·취할점/버릴점.
- [x] 트렌드 매핑표(현재→갭→방향) 8행.
- [x] JTBD 6개 — 각 충족도(상/중/하) + 마찰점.
- [x] 우선순위 개선안 10개(Quick win 5 + Big bet 5) + 보류/안티골, 상위 3개 시안 연결.
- [x] 스택 3옵션 비교표 + 권고(A+, 근거 명시, B 마이그레이션 개략).
- [x] 모든 개선안이 케이스/트렌드/JTBD로 역추적(서비스 도메인 규칙 적용).
- [ ] 목업 3안 — `docs/mockups/` (Phase 7, 별도 파일).
