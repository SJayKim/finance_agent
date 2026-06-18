# Stage 1 기술 상세 설계 — 인터랙티브 증거 브리프 대시보드

상위 문서: `../DESIGN.md` (Status: APPROVED). 본 문서는 그 중 **Stage 1(Approach A)**
의 기술 상세 설계다. 코드는 아직 없음. 이 문서는 착수 전 기술 결정을 확정하고,
Stage 0(애널리스트 관찰 숙제)에 막힌 부분을 명시적으로 빈칸 처리한다.

- 작성: 2026-06-18, branch main
- 상태: DRAFT (스택 결정 + 블로커 해소 후 → READY)

---

## 0. 범례

- `[DECIDED]` — DESIGN.md에서 합의된 결정. 변경하려면 상위 문서부터.
- `[STAGE0-BLOCKED]` — 애널리스트 관찰(Stage 0) 결과가 있어야 채울 수 있는 칸.
  관찰 전엔 가정만 적고 코드로 확정하지 않는다.
- `[OPEN]` — 본 문서에서 결정해야 할 기술 선택(스택 등). 아래 §11에 모음.
- `[GATE]` — 통과 못 하면 다음 단계로 못 가는 검증/선결 조건.

---

## 1. 범위와 비범위

**Stage 1이 하는 일 (`[DECIDED]`):**
장전 07:00 모닝미팅용 **일간 증거 브리프**. 합법 무료 소스에서 유니버스 이벤트만
수집 → dedup → 클러스터링 → 티커 링킹 → 이벤트 타입 분류 → **문장 단위 출처 추적
가능한** 영향도 분석을 Citations API로 생성. 결론은 얇게(영향 종목 후보 + 이벤트
타입 + 신뢰도 HIGH/MED/LOW), 증거는 두껍게(클릭 → 발행시각 찍힌 원문). 주간 리포트
= 일간 브리프 집계. 웹 대시보드 UI.

**Stage 1이 하지 않는 일 (`[DECIDED]`, Stage 2~3로 이연):**
- 이견 레이더(컨센서스 합성) → Stage 2
- 공급망 KG 기반 2차 영향주 추론 → Stage 3
- KR 뉴스 본문 단위 grounding(BIGKINDS/좌석 연동) → Stage 3. **Stage 1의 KR 종목
  추적성은 헤드라인+요약 단위로 제한**(P5). 본문 합법 수집은 공시(OpenDART/EDGAR)뿐.
- KR 실시간 시세 → Stage 1은 **EOD 확정**. 실시간은 Stage 3.
- 멀티에이전트 오케스트레이션 → Stage 1은 고정 파이프라인.
- 투자 권유/예측/매수의견 → 영구 비범위(P1, 컴플라이언스).

**한 줄 가치 명제:** "내 커버리지에 영향 줄 만한 것만, 출처와 발행시각과 함께,
장전에 5분 만에." (PAIN_POINT.md §1-1: 애널리스트가 원하는 건 추천이 아니라 필터.)

---

## 2. Stage 0 의존성 맵 (관찰 전엔 못 정하는 것)

DESIGN.md가 명시: 데이터 레이어/파이프라인 기술은 Stage 0과 병렬 착수 가능하나,
**"무엇을 브리프에 넣나"와 UX는 Stage 0 완료에 막힌다.** 아래는 그 경계선이다.

| 항목 | 상태 | 관찰로 채울 질문 |
| --- | --- | --- |
| 브리프 1면에 들어갈 항목 수·우선순위 | `[STAGE0-BLOCKED]` | 애널리스트가 07:00에 *먼저* 보는 게 뉴스냐 공시냐 컨센서스냐 |
| 이벤트 타입 분류 체계(taxonomy) | `[STAGE0-BLOCKED]` | 실무에서 구분하는 이벤트 범주가 무엇인가 (실적/가이던스/공급망/매크로/규제…) |
| 신뢰도 등급 표기 방식·임계 | `[STAGE0-BLOCKED]` | HIGH/MED/LOW를 색·아이콘·텍스트 중 무엇으로 신뢰하는가 |
| "놓치면 치명적" 알림 경계 | `[STAGE0-BLOCKED]` | 어떤 이벤트를 놓쳤을 때 모닝미팅에서 망신인가 (PAIN_POINT §1-1) |
| 커버리지 입력 방식(수동 입력 vs 사내 마스터 연동) | `[STAGE0-BLOCKED]` | 150명이 본인 커버 종목을 어떻게 관리 중인가 |
| 브리프 전달 채널(대시보드 only vs 메일/메신저 푸시) | `[STAGE0-BLOCKED]` | 아침에 실제로 여는 창이 무엇인가 (The Assignment) |

> **규칙:** 위 칸들은 관찰 결과가 오기 전까지 **하드코딩하지 않는다.** 파이프라인은
> 이 결정들을 **설정값/플러그인 경계**로 받도록 설계해 두고(아래 §6 event classifier,
> §10 UX), 빈 채로 둔다. 추측으로 채우면 Stage 0의 의미가 사라진다.

---

## 3. 아키텍처 개요 `[DECIDED: 고정 파이프라인, 단일 VM + 07:00 크론]`

```
                         [07:00 KST cron]  + [온디맨드 트리거 API]
                                  │
   ┌──────────────────────────────┴───────────────────────────────┐
   │                       Collector 서비스 (분리)                  │
   │  네이버 오픈API · OpenDART · SEC EDGAR · KRX(EOD)              │
   │  코인: CoinGecko · Marketaux · Finnhub · 퍼블리셔 RSS          │
   │  → raw_documents 적재 (멱등, 발행시각·소스·URL 보존)            │
   └──────────────────────────────┬───────────────────────────────┘
                                  │  (불변 raw 저장 후)
   ┌──────────────────────────────┴───────────────────────────────┐
   │                  Pipeline 서비스 (고정 단계)                   │
   │  normalize → dedup(SimHash→임베딩 cosine) → cluster            │
   │  → ticker-link(OpenFIGI+사전) → event-classify                 │
   │  → 영향도 생성 (2-패스 Citations API)                          │
   │  → brief_items 적재                                            │
   └──────────────────────────────┬───────────────────────────────┘
                                  │
   ┌──────────────────────────────┴───────────────────────────────┐
   │     Web 대시보드 (커버리지 필터 → 브리프 → 클릭-투-소스)        │
   └────────────────────────────────────────────────────────────────┘

   저장소: Postgres + pgvector (raw_documents, clusters, brief_items, citations,
            coverage, sources, audit_log)
```

**Collector와 Pipeline을 분리하는 이유 (`[DECIDED]`, DESIGN.md Distribution):**
공시 수집은 쿼터·throttling이 병목이고 raw는 불변이라, 수집 실패가 분석 단계를
오염시키지 않게 경계를 둔다. raw 적재가 끝난 뒤에만 파이프라인이 돈다.

---

## 4. 스택 `[DECIDED]` (2026-06-18 확정)

| 레이어 | 결정 | 근거 / 메모 |
| --- | --- | --- |
| 언어 | **Python 3.13+** | 금융 데이터·공시 파싱·Anthropic SDK·임베딩/NLI 생태계 최강. 로컬 3.14 사용, `requires-python=">=3.13"` (2026-06-19 변경: 3.12 핀 → 로컬 설치본 허용) |
| 패키지/환경 | **uv** | 빠른 락파일·가상환경. `pyproject.toml` 단일 소스 |
| API/백엔드 | **FastAPI + uvicorn** | 온디맨드 트리거 API + 대시보드 백엔드 겸용 |
| 프런트 | **서버렌더: Jinja2 + HTMX** | 클릭-투-소스만 먼저. Stage 0 UX 확정 후 필요시 SPA 전환(§11.4) |
| 수집/파이프라인 | **단일 프로세스 + 내장 작업 큐** | 멀티에이전트 없음(P6). 스케일 전 Celery/RQ 불필요 |
| 스케줄 | **OS cron**(07:00) + FastAPI 온디맨드 | 단일 VM이라 cron으로 충분 |
| DB | **Postgres 16 + pgvector** | DESIGN.md 명시. 임베딩·관계형 한 곳 |
| DB 접근/마이그레이션 | **SQLAlchemy 2.0 + Alembic** | pgvector 타입 지원. 스키마 버전관리 |
| 임베딩 | `[OPEN]` 모델만 미정(§11.3), **인터페이스는 추상화** | 로컬(sentence-transformers) ↔ API 교체 가능하게. KR 품질 실측 후 확정 |
| 린트/포맷 | **ruff** | lint + format 단일 도구 |
| 타입체크 | **mypy** | CI 게이트 |
| 테스트 | **pytest** | swap test·NLI 회귀(§12)를 CI로 |
| 배포 | **단일 VM + 컨테이너(Docker)** | DESIGN.md. 스케일 시 K8s/ECS(Stage 3) |

---

## 5. 데이터 레이어 / 커넥터 스펙 `[DECIDED: 소스 5종 + OpenFIGI]`

각 커넥터의 책임: **수집 → 정규화(공통 스키마) → raw_documents 멱등 upsert**.
공통 정규화 필드: `source`, `external_id`, `published_at`(원본 발행시각, TZ 보존),
`fetched_at`, `title`, `summary`, `body`(합법 수집 가능할 때만), `url`, `lang`,
`raw_payload`(jsonb 원본).

### 5.1 네이버 검색 오픈API (KR 뉴스) `[DECIDED: 헤드라인+요약+URL만]`
- **합법 경계(P5):** 본문 직접 크롤링 금지. 오픈API가 주는 헤드라인·요약·링크만.
  → KR 종목 추적성은 **요약 단위**로 제한(§1 비범위 재확인).
- 쿼리: 커버리지 종목/섹터 키워드 + 별칭 사전. `sort=date`.
- 쿼터: 일 한도 존재 → 키워드 수 × 호출 예산 산정 필요. 캐싱은 `external_id`(링크)
  기준 dedup.
- 리스크: 요약이 짧아 영향 해석 깊이 얕음 → Citations 인용 범위가 요약 텍스트로 한정됨.

### 5.2 OpenDART (KR 공시) `[DECIDED: 본문까지 합법 수집]`
- **이게 Stage 1 KR 추적성의 핵심.** 공시 원문은 합법 수집 가능 → sentence-level
  grounding 가능.
- 엔드포인트: 공시검색(list) + 문서원문(document). 유니버스 종목 corp_code 매핑 선행.
- 쿼터 `[GATE]`: **일 20,000건 + 분/초 throttling**이 실제 병목. 대응(DESIGN.md):
  - 캐싱·증분수집 1차 수단 — 공시는 불변, 한 번 받으면 재호출 금지.
  - 실적시즌(2·3·5·8·11월) 대량 제출 스파이크 대비 백오프·재시도.
  - **인증키 풀링은 ToS 다중키 허용 확인 전 의존 금지**(약관 리스크).

### 5.3 SEC EDGAR (US 공시) `[DECIDED: 본문까지 합법 수집]`
- full-text search + filing 문서. fair-access 정책 준수(User-Agent 명시, rate limit).
- 8-K/10-Q 등 이벤트성 filing 우선.

### 5.4 CoinGecko (코인 시세·트렌딩) `[DECIDED: 무료 Demo, 시세·트렌드만]`
- 유니버스: BTC/ETH/SOL + RWA 내러티브 토큰. EOD·trending·categories.
- 무료 Demo(월 10k 콜)로 시세·트렌드 충당. **news 엔드포인트는 무료에 없음**
  (Analyst $129/월) → CoinGecko로는 뉴스 텍스트를 안 받는다.
- 시세 백업: **CoinPaprika**(무료·키불필요) — CoinGecko 장애 시 fallback.
- 코인 뉴스 텍스트는 §5.8(3-티어 무료 레이어)에서 별도 수집. (§11.1 게이트 해소)

### 5.5 KRX (KR 시세 EOD) `[DECIDED: EOD 확정]`
- OpenAPI로 일별 종가/거래량. 실시간 아님(Stage 1).

### 5.6 OpenFIGI (티커 매핑) `[DECIDED]`
- 회사명/식별자 → 표준 티커. KR(6자리)·US 심볼 정규화. 티커 링킹(§6.4)의 사전 백본.

### 5.7 신선도 컷오프 `[DECIDED]`
- **미국장 마감(~06:00 KST) ~ 07:00 사이 야간 이벤트를 반드시 포함**하는 수집 컷오프.
- 브리프에 `last_updated_at`(마지막 갱신 시각) 항상 표기.
- 오래된 뉴스로 현재 시황 판단 금지(CLAUDE.md 도메인 규칙) → `published_at` 기준
  신선도 윈도우 필터.

### 5.8 코인 뉴스 3-티어 무료 레이어 `[DECIDED: 2026-06-18, §11.1 게이트 해소]`
CryptoPanic 무료(2026-04 종료)·CryptoCompare/CoinDesk Data 무료(2026-05 종료)·
CoinGecko news(유료)가 다 막힌 상황에서, **무료로 단일 장애점 없이** 코인 뉴스를
받기 위한 3-티어. 다중 소스 redundancy는 §6.2 dedup→§6.3 cluster의 입력 전제와 일치.

| 티어 | 소스 | 역할 | 합법근거 |
| --- | --- | --- | --- |
| 구조화+감성 | **Marketaux**(무료 100/일) + **Finnhub**(무료 60/분) | 엔티티 태깅·감성 붙은 1급 뉴스 입력. Finnhub가 한도 넉넉해 주력 | 공식 무료 API |
| RSS 폭 | **CoinTelegraph · CoinDesk · Decrypt** RSS (보조: ChainGPT 공개 RSS) | 커버리지·redundancy. dedup 먹잇감 | 퍼블리셔 신디케이션, **헤드라인+요약+링크만**(P5와 동일 posture) |
| 시세·트렌드 | CoinGecko Demo (백업 CoinPaprika) | 가격·트렌딩 (§5.4) | 무료 API |

- **합법 경계:** RSS는 발행사 신디케이션 피드라 합법이나, **본문 직접 크롤링 금지** —
  피드가 주는 헤드라인+요약+링크까지만(§5.1 네이버와 동일). → 코인 뉴스의 Citations
  인용 범위는 요약 텍스트로 제한. 본문 grounding은 공시(OpenDART/EDGAR)뿐.
- **인터페이스:** 각 소스는 §5 공통 커넥터 패턴(수집→normalize→raw_documents 멱등
  upsert)으로 흡수. `sources` 행에 소스별 `legal_basis` 기록.
- **버리는 소스(무료 끊김/부적합):** CryptoCompare·CoinDesk Data(무료 2026-05 종료),
  CryptoPanic 무료(2026-04 종료), CoinGecko news(Analyst $129), Alpha Vantage
  NEWS_SENTIMENT(25/일·크립토 약함), Messari 뉴스(Enterprise).
- **`[GATE]` 착수 시 실측:** Finnhub 크립토 뉴스의 실제 코인 커버리지 폭, NewsData.io
  무료 일일 한도 정확값(이번 조사에서 미확정).

---

## 6. 파이프라인 단계 상세 `[DECIDED: 고정 단계]`

### 6.1 normalize
소스별 페이로드 → 공통 스키마(§5). 시각은 전부 UTC 저장 + 원본 TZ 보존.

### 6.2 dedup `[DECIDED: 제목 SimHash → 임베딩 cosine]`
- 1차: 제목 SimHash 해밍거리로 근접 중복 후보 군집(저비용).
- 2차: 후보 내 임베딩 cosine 유사도로 확정 dedup.
- 목적: PAIN_POINT §1-3 "중복 기사 많음" 직접 해소.

### 6.3 cluster
dedup 후 같은 사건(event)을 하나로 묶음. 임베딩 기반. 클러스터 = 브리프의 한 항목 후보.

### 6.4 ticker-link `[DECIDED]` / `[GATE: precision ≥ 95%]`
- 회사명·별칭·티커 사전 + OpenFIGI 정규화로 이벤트 → 영향 종목 매핑.
- **임계 미달이면 단정 금지** → "후보" 표기 또는 보류(오귀속이 추적성 신뢰를 깸).
- 성공 기준: 매핑 precision ≥ 95%(DESIGN.md Success Criteria).

### 6.5 event-classify `[STAGE0-BLOCKED: taxonomy]`
- 분류기 자체는 만들되, **범주 체계는 Stage 0 관찰로 확정.** 인터페이스만 고정:
  입력=클러스터, 출력=`event_type`(enum, 관찰 후 채움) + `direction`(긍정/부정/중립,
  단정 아님) + `confidence`(HIGH/MED/LOW).
- 표현 가드레일(PAIN_POINT §3-2): "매수 추천" ❌ → "영향 가능성/긍정 요인으로 분류" ✅.

### 6.6 영향도 생성 → §7 (2-패스 Citations)

---

## 7. 2-패스 Citations API 계약 `[DECIDED + 무결성 규칙]`

**왜 2-패스인가:** Anthropic Citations API와 Structured Outputs는 동시 사용 불가
(400 에러). 그래서 분리한다.

- **패스 1 — 인용 생성:** Citations API(claude-opus-4-8)로 클러스터의 1차 소스
  (공시 본문 / 뉴스 요약)에서 `cited_text`를 강제 추출하며 영향도 분석 문장을 생성.
  zero-fabrication: 인용 없는 주장 금지.
- **패스 2 — JSON 추출:** 패스1 출력을 구조화(brief_item JSON: 영향 종목, event_type,
  direction, confidence, citations[]).

> **무결성 규칙 (`[DECIDED]`, 가장 중요):** **패스 2의 입력은 패스 1이 실제 인용한
> `cited_text` 범위로만 제한한다.** 패스 2에서 모델이 새 사실·수치를 끌어오면
> zero-fabrication이 다시 깨진다. 패스 2는 재구조화만, 새 정보 도입 금지.

- **검증은 패스 2 최종 출력에 대해:** swap test(인용↔원문 일치) + 인용 정확도.

---

## 8. 데이터 모델 (Postgres + pgvector)

```
sources(id, name, kind[news|filing|price], legal_basis, default_rate_limit)
raw_documents(id, source_id, external_id UNIQUE(source_id,external_id),
              published_at, fetched_at, lang, title, summary, body, url,
              raw_payload jsonb, embedding vector)
clusters(id, brief_date, centroid vector, representative_doc_id, created_at)
cluster_members(cluster_id, raw_document_id)         -- dedup/cluster 결과
brief_items(id, brief_date, cluster_id, event_type, direction, confidence,
            analysis_text, status[ok|degraded|empty], generated_at)
brief_item_tickers(brief_item_id, ticker, market[KR|US|CRYPTO],
                   link_precision, is_candidate bool)  -- §6.4 보류 표기
citations(id, brief_item_id, raw_document_id, cited_text, char_start, char_end,
          source_published_at)                       -- 문장 단위 클릭-투-소스
coverage(analyst_id, ticker|sector, market)          -- §9
audit_log(id, ts, actor, action, payload jsonb)      -- 컴플라이언스 추적
```

핵심: 모든 `brief_items.analysis_text` 문장은 `citations`로 원문 char 범위까지
역추적 가능(P2 제품 본체). 신뢰도·후보 표기·degraded 상태가 스키마에 1급으로 존재.

---

## 9. 커버리지 온보딩 `[DECIDED 골격 / STAGE0-BLOCKED 입력 UX]`
- 모델: `coverage(analyst_id, ticker|sector, market)`. 애널리스트별 커버 종목/섹터가
  분석 대상과 브리프 필터를 정의.
- **입력 방식**(수동 입력 / CSV / 사내 마스터 연동)은 `[STAGE0-BLOCKED]` — 150명이
  지금 커버리지를 어떻게 관리하는지 관찰 후 결정.

---

## 10. 빈/장애 상태 UX `[DECIDED: null-evidence refusal]`
- 소스 다운·쿼터 소진·해당 종목 무이벤트 시 **명시적 degraded/empty 표기.**
- **지어내지 않는다.** 근거 없으면 "근거 없음"으로 표기(brief_items.status=empty),
  분석 텍스트를 환각으로 채우지 않음. 이것이 전문가 신뢰의 1차 조건(PAIN_POINT §3-1).
- degraded 시 어떤 소스가 빠졌는지 사용자에게 노출(예: "OpenDART 쿼터 소진, 공시 제외").
- **표시 레이아웃/우선순위는 `[STAGE0-BLOCKED]`.**

---

## 11. 열린 결정 / 선결 블로커

### 11.1 ~~`[GATE]` 코인 뉴스 소스 대체~~ → `[DECIDED]` (2026-06-18, 게이트 해소)
무료 소스 조사 후 **3-티어 무료 레이어로 확정**(상세 §5.8). 외부비용 $0.
- 구조화+감성: Marketaux(100/일) + Finnhub(60/분)
- RSS 폭: CoinTelegraph·CoinDesk·Decrypt(헤드라인+요약+링크만)
- 시세·트렌드: CoinGecko Demo(백업 CoinPaprika)
- 유료(CryptoPanic) 전환은 무료 쿼터가 실측상 부족할 때로 이연.

### 11.2 ~~`[GATE]` arXiv 2606.12210 인용 재확인~~ → `[VERIFIED]` (2026-06-18, 단 수치 프레이밍 수정)
원문 확인: "Can News Predict the Market? Limits of Zero-Shot Financial NLP and
the Role of Explainable AI" (Karaoglu & Gowda, arXiv:2606.12210). 방향성 결론
("zero-shot 예측력 약함, 설명가능성/영향도 해석이 실질 가치")은 초록에서 확인됨.
- **수치 프레이밍 정정(중요):** 기존 `37.5% vs 48.4%` 묶음은 원문에 그렇게 없음.
  둘은 별개 표의 별개 값:
  - **48.4%** = 홀드아웃 중립 클래스 비중(Table 7) = **다수결 베이스라인**.
    인용 가능한 한 줄: *"No model exceeds the majority-class baseline of 48.4%."*
  - **37.5%**(0.3750) = RoBERTa **단일 모델**의 홀드아웃 192건 전체 정확도(Table 9).
    zero-shot LLM 수치가 아님 → 깔끔한 대조처럼 쓰지 말 것.
- **문서 표기 규칙:** 베이스라인 48.4% + "모든 모델 미달"로만 인용. 37.5%는 빼거나
  "RoBERTa 단일 모델 예시"로만 표기.

### 11.3 `[OPEN]` 한국어 임베딩 모델 선택
KR 헤드라인 dedup·클러스터 품질을 좌우. 후보(다국어/한국어 특화) 벤치 필요.
실측 데이터로 dedup precision/recall 측정 후 확정.

### 11.4 ~~`[OPEN]` 프런트엔드 방식~~ → `[DECIDED]`
**경량 서버렌더(Jinja2 + HTMX) 먼저**(2026-06-18 확정, §4). 클릭-투-소스만 빠르게
검증. UX 레이아웃·우선순위는 여전히 `[STAGE0-BLOCKED]`(§2, §10) — 틀만 서버렌더로
정한 것. Stage 0 결과가 무거운 인터랙션을 요구하면 그때 SPA 전환 재검토.

### 11.5 ~~`[OPEN]` 빌드/테스트/린트 명령~~ → `[DECIDED]`
CLAUDE.md Commands 채움(2026-06-18). uv 기반:
- 설치: `uv sync`
- 테스트: `uv run pytest`
- 린트: `uv run ruff check .` / 포맷 `uv run ruff format .`
- 타입체크: `uv run mypy .`

---

## 12. 검증 계획 (Success Criteria 매핑)

| 검증 | 방법 | 게이트 |
| --- | --- | --- |
| 조작/존재하지 않는 인용 = 0건 | swap test + null-evidence refusal을 **CI 회귀 테스트** | 하드 게이트(절대 0) |
| claim이 인용을 과장 안 함 | NLI 함의율 ≥ 98% | 미달분 자동 플래그→검토, 배포는 차단 안 함 |
| 티커 링킹 정밀도 | precision ≥ 95%, 미달 시 "후보"/보류 | §6.4 |
| 신선도 | 야간(US 마감~07:00) 이벤트 포함 + last_updated 표기 | §5.7 |
| 채택(상위 지표) | 모닝미팅 전 주간 활성 애널리스트 비율 ≥ 30%→50% | Stage 1 출시 후 측정 |

(RAGAS faithfulness, event study CAR은 Stage 3 게이트 — Stage 1 비범위.)

---

## 13. 다음 액션

1. ~~`[GATE]` §11.1 코인 소스 + §11.2 arXiv 재확인~~ → **해소(2026-06-18)**:
   §11.1 3-티어 무료 레이어 확정(§5.8), §11.2 검증 완료(수치 프레이밍 정정).
2. `[OPEN]` §4/§11.3/§11.4 스택 확정 → CLAUDE.md Commands 채움.
3. **병렬 가능(Stage 0 무관):** §5 커넥터 + §8 스키마 + §6.2 dedup 구현 착수.
4. `[STAGE0-BLOCKED]` §2 표의 칸들 — 관찰 결과 도착 후 채움. 그 전엔 설정 경계만.
