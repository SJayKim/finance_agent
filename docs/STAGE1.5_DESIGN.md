# Stage 1.5 설계 — 소스 확장 · 일일 다이제스트 · 누적 RAG 챗봇

상위 문서: `DESIGN.md`(APPROVED), `STAGE1_DESIGN.md`(증거 브리프 파이프라인),
`STAGE1_DASHBOARD_SPEC.md`(날짜별 추적성 뷰 + 근거기반 채팅). 본 문서는 그 위에
사용자 요청 5건을 얹는 **증분 설계**다. 코드는 아직 없음.

- 작성: 2026-06-22, branch main
- 상태: DRAFT — 방향 3개 확정(아래 §0), 모델/쿼터 실측 후 READY

---

## 0. 확정된 결정 (office-hours 2026-06-22)

이 3개가 작업 순서·난이도를 결정한다. 사용자 답으로 확정.

| # | 결정 | 함의 |
| --- | --- | --- |
| D1 | **기존 컴플라이언스 경계 유지**(애널리스트 도구) | 일일 다이제스트(거시·섹터·인사이트)도 **그날 brief_items의 인용 근거에 묶인다.** "투자권유 아님"·zero-fabrication 유지. 거시/섹터는 "주목 후보"·"영향 가능성"으로만 표기. 자유로운 LLM 거시 전망은 **금지**. |
| D2 | **전체 코퍼스 의미검색(pgvector RAG)** | §11.3 임베딩 모델을 확정하고 임베딩 레이어를 구축해야 한다. 누적 채팅은 검색으로 고른 인용 span을 Citations API에 먹여 **여전히 인용에 묶인다**(현재 하루치 채팅의 코퍼스를 retrieval로 확장한 것). |
| D3 | **소스 4영역 전부 확장** | KR 주식·경제 뉴스 / 글로벌 매크로 / 공시 본문(DART·SEC) / 코인 구조화 뉴스(Marketaux·Finnhub). 각각 §5 Connector 패턴으로 흡수. |

> **D1이 가장 중요하다.** 사용자가 쓴 "투자관련 인사이트"를 액면대로 자유 서술로 풀면
> 프로젝트의 핵심 자산(추적가능성·전문가 신뢰, PAIN_POINT §3)이 무너진다. 그래서
> 일일 다이제스트는 "새 LLM 거시 전망"이 아니라 **그날 수집·분석된 brief_items를
> 거시/섹터 축으로 집계·요약한 것**으로 정의한다. 모든 문장은 brief_item → citation으로
> 역추적된다. 이게 이 증분의 설계 제약 1번.

---

## 1. 범위 / 비범위

**이 증분이 하는 일:**
1. (#1) 수집 소스를 코인 RSS 1종 → KR 뉴스·글로벌 매크로·공시 본문·코인 구조화로 확장.
2. (#2) 매일 정해진 시각에 **수집기 전체 → 파이프라인**을 자동 실행하고 DB에 적재(오케스트레이션 + 스케줄).
3. (#3) 그날 brief_items를 **거시상황·영향 섹터 축으로 집계한 일일 다이제스트**를 인용 근거에 묶어 생성.
4. (#4) 날짜별 다이제스트 뷰 + **누적 코퍼스 전체에 대한 RAG 채팅**(임베딩 레이어 신설).

**비범위(이연):**
- 이견 레이더(컨센서스 합성) → Stage 2 (기존 경계 유지).
- 공급망 KG 2차 영향주 추론 → Stage 3.
- 실시간 시세 → Stage 1은 EOD 확정 유지.
- 자유로운 거시 전망·매수의견·목표가 → **영구 비범위**(D1, P1 컴플라이언스).

---

## 2. 프리미스 체크 (착수 전 동의 필요)

1. **일일 다이제스트는 합성이 아니라 집계다.** 그날 brief_items가 0건이거나 status=empty뿐이면
   다이제스트도 "오늘은 추적 가능한 근거가 없음"으로 비운다. **빈 날을 그럴듯한 거시 서술로
   채우지 않는다**(§10 null-evidence 연장). — 동의?
2. **RAG 채팅도 인용이 유일한 거부 기준이다.** 검색으로 후보 span을 고르되, 최종 답변은
   현재 채팅(`web/chat.py`)과 똑같이 "인용 0건 → 거부(None)". 검색은 **무엇을 먹일지**만
   바꾸고 **무엇을 신뢰할지**는 안 바꾼다. — 동의?
3. **임베딩 차원 고정은 비가역 결정이다.** 모델을 고르면 `Vector(dim)`이 고정되고 마이그레이션이
   필요하다. 모델 교체 시 전체 재임베딩. 그래서 §6에서 모델을 **실측 후** 확정한다(추측 금지). — 동의?
4. **소스 확장의 진짜 비용은 코드가 아니라 쿼터·합법 경계·발행시각 정확도다.** 네이버는 일 한도,
   DART는 일 2만 건+throttling(실적시즌 스파이크), SEC는 fair-access UA 필수. 커넥터를 늘리는
   순간 이 운영 부담이 같이 는다. — 동의?
5. **본문 grounding은 여전히 공시(DART·SEC)뿐이다.** KR/글로벌 뉴스·RSS는 P5 경계로
   헤드라인+요약+링크까지만. 즉 거시 다이제스트의 인용 깊이는 뉴스에선 얕고 공시에선 깊다.
   이 비대칭을 UI가 숨기지 말 것. — 동의?

---

## 3. 아키텍처 델타

기존(STAGE1 §3)에 굵게 표시한 것이 이 증분의 신규/확장.

```
           [매일 06:40 KST 수집 → 07:00 다이제스트]  + [온디맨드 /trigger]
                                  │
   ┌──────────────────────────────┴───────────────────────────────┐
   │  Collector (확장)                                              │
   │  기존: 코인 RSS 3종                                            │
   │  신규: ★네이버 뉴스API · ★KR 경제지 RSS · ★글로벌 매크로 RSS  │
   │        ★OpenDART 공시본문 · ★SEC EDGAR filing본문             │
   │        ★Marketaux · ★Finnhub (코인 구조화)                    │
   │  → raw_documents 멱등 적재                                     │
   └──────────────────────────────┬───────────────────────────────┘
                                  │
   ┌──────────────────────────────┴───────────────────────────────┐
   │  Pipeline (기존 고정 단계)                                     │
   │  dedup → cluster → generate_impact → analyze_impact(2-패스)    │
   │  → ticker_link                                                │
   │  ★+ embed: raw_documents.embedding 채움 (신규 단계)           │
   │  ★+ daily_digest: 그날 brief_items 집계 → 거시·섹터 요약       │
   └──────────────────────────────┬───────────────────────────────┘
                                  │
   ┌──────────────────────────────┴───────────────────────────────┐
   │  Web                                                          │
   │  기존: 날짜별 추적성 뷰 + 하루치 근거 채팅                     │
   │  ★+ 날짜별 다이제스트 뷰(거시·섹터 요약 카드)                  │
   │  ★+ 누적 RAG 채팅: 임베딩 검색 → 인용 span → Citations API     │
   └────────────────────────────────────────────────────────────────┘

   저장소: 기존 테이블 + ★daily_digests + ★embedding 차원 고정
```

---

## 4. 작업 트랙 (검증 게이트 포함)

순서는 의존성 기준. A·B는 병렬 가능, C는 A·B 후, D·E는 임베딩 게이트 후.

### 트랙 A — 수집 소스 확장 (#1, #3 재료)
각 소스는 `Connector`(fetch→normalize→upsert) 패턴으로, `rss.py`가 레퍼런스.

| 소스 | 유형 | 본문? | 신규 커넥터 | 비고 |
| --- | --- | --- | --- | --- |
| 네이버 검색 오픈API | KR 뉴스 | ✗(요약만) | `collector/naver.py` | 키 2개 이미 config에 있음. 쿼터 = 키워드수×예산. **구현됨:** 쿼리는 `load_coverage_queries`가 coverage 섹터 ∪ 커버 종목 별칭에서 도출(하드코딩 없음, 빈 DB → no-op). |
| KR 경제지 RSS | KR 뉴스 | ✗ | `rss.py` 피드 추가 | 한경·매경 등 공개 RSS. `DEFAULT_FEEDS`에 KR 피드 dict 추가, `lang="ko"` 분기. |
| 글로벌 매크로 RSS | 매크로 | ✗ | `rss.py` 피드 추가 | 연준/ECB 보도자료 RSS, 로이터/주요 매체 공개 RSS. `lang="en"`. |
| OpenDART 공시 | KR 공시 | **✓ 본문** | `collector/opendart_docs.py` | **현 opendart.py는 별칭 시더라 별개 모듈.** list+document 엔드포인트. 일 2만건+throttling 게이트. 불변→캐싱/증분. |
| SEC EDGAR filing | US 공시 | **✓ 본문** | `collector/edgar_docs.py` | 8-K/10-Q 우선. UA 필수(sec.py 패턴 재사용). |
| Marketaux | 코인 뉴스 | ✗ | `collector/marketaux.py` | 무료 100/일. 엔티티·감성 태깅. |
| Finnhub | 코인 뉴스 | ✗ | `collector/finnhub.py` | 무료 60/분, 주력. |

> **검증 A:** 각 커넥터 `parse/normalize`는 순수함수 단위테스트(고정 샘플 페이로드 →
> NormalizedDoc). upsert 멱등성은 같은 페이로드 2회 → raw_documents 1행. `published_at`
> TZ 보존 회귀 테스트(신선도 §5.7 의존). 새 소스마다 `sources.legal_basis` 기록.

> **합법 게이트:** 뉴스·RSS는 body=None 강제(P5). 공시만 body 채움. 커넥터 코드리뷰에서
> 본문 크롤링 여부를 게이트로.

### 트랙 B — 일일 오케스트레이션 + 스케줄 (#2)
현재 `/trigger`는 파이프라인만 돈다. 수집기를 안 부른다 → **수집 자동화가 통째로 없음.**

- 신규 `app/runner.py`(또는 `pipeline/orchestrate.py`): `run_daily(brief_date)` =
  `[모든 커넥터.fetch→normalize→upsert]` → `run_pipeline(brief_date)` → `build_digest(brief_date)`.
- 동시성 가드는 기존 `pg_try_advisory_lock` 재사용(중복 실행 차단).
- 스케줄: STAGE1 §3대로 **OS cron**. 수집 06:40 KST(야간 미국장 이벤트 포함, §5.7) →
  다이제스트 07:00. Windows 로컬이면 작업 스케줄러, 배포 VM이면 cron.
- **채택:** `/trigger`(파이프라인 전용 빠른 경로) **유지** + `/run-daily` **신설**(수집까지
  포함한 일일 1회 실행). 승격/분리 대신 두 라우트 병존(`main.py`).

> **검증 B:** 한 소스가 장애(타임아웃·쿼터)나도 나머지 수집·파이프라인은 계속(소스 격리,
> STAGE1 §3 Collector/Pipeline 분리 취지). 실패 소스는 `audit_log`에 기록 + 다이제스트에
> "OpenDART 제외" 같은 degraded 표기(§10). 빈 수집일에도 크래시 없이 빈 다이제스트.

### 트랙 C — 일일 다이제스트 (#3) · **인용에 묶임(D1)**
새 합성 altitude. 자유 거시 서술 금지. 그날 brief_items를 거시·섹터 축으로 **집계**.

- 신규 테이블 `daily_digests(id, brief_date, section[macro|sector|...], heading, body_text,
  status[ok|degraded|empty], generated_at)` + `digest_citations` 또는 brief_item 참조로
  역추적. (정확 스키마는 §7.)
- 생성: 그날 status=ok brief_items + 그 citations를 입력으로, **2-패스 Citations와 같은
  경계**(citations.py 재사용)로 "거시 테마 / 영향 섹터" 요약 생성. 인용 0 → 해당 섹션 empty.
- 표현 가드레일(PAIN_POINT §3-2): "매수"·"상승 전망" ❌ → "주목 섹터 후보"·"긍정 요인으로
  분류" ✅. citations.py의 시스템 프롬프트 경계 재사용.

> **검증 C:** brief_items 0건/empty뿐인 날 → 다이제스트 empty(지어내지 않음). 다이제스트
> 문장이 인용한 cited_text가 실제 그날 citations에 존재(swap test 연장). NLI 함의율 게이트
> (STAGE1 §12)를 다이제스트에도 적용.

### 트랙 D — 임베딩 레이어 + 누적 RAG 채팅 (#4) · **§11.3 게이트**
현재 `embedding=Vector()` 차원 미고정, dedup도 SimHash만. RAG의 선결 블로커.

1. **모델 확정(§6)** → `Vector(dim)` 고정 마이그레이션 + ivfflat/hnsw 인덱스.
2. 파이프라인에 `embed` 단계: 신규 raw_documents의 (title+summary, 공시는 body 청크) 임베딩.
   멱등 — `embedding IS NULL`인 행만.
3. **RAG 채팅**(`web/chat.py` 확장): 질문 임베딩 → pgvector 유사도 top-k **citations/brief_items**
   검색(전 날짜) → 그 cited_text span을 citable document로 Citations API에 주입 → 현재와
   동일하게 인용 0이면 거부. 즉 현재 "그날 전체 인용" 대신 "검색으로 고른 인용"을 먹인다.
   - **구현:** 랭킹은 `raw_documents`의 **문서 임베딩(제목+요약, `document_embed_text`)** 코사인
     유사도로 하고(`search_citation_spans`), 가까운 문서의 **citation span(cited_text)을 Citations
     API에 먹인다**. 인용 span 자체에 임베딩을 두지 않고 문서 임베딩으로 검색 → 그 문서의 인용을
     주입하는 구조. 인용은 zero-fabrication ground truth라 경계가 안 깨짐.

> **검증 D:** "이번 주 반도체 흐름" 류 cross-date 질문에 여러 날짜 인용이 섞여 답변+인용.
> 코퍼스에 없는 주제 질문 → "관련 근거 없음"(거부). 검색 top-k가 인용 0개만 물어오면 거부.
> 한국어 질문↔한국어 헤드라인 검색 recall 실측(임베딩 모델 선정 근거).

### 트랙 E — 대시보드 다이제스트 뷰 (#4)
- `/`(또는 `/digest?date=`)에 그날 거시·섹터 요약 카드 추가. 각 카드 클릭 → 근거 brief_item/원문
  (기존 추적성 뷰 재사용). 날짜 네비게이션.
- 채팅 위젯을 "이 날짜" / "전체 누적" 토글로(트랙 D 라우트 연결).
- Stage 0 UX 미확정(§2 STAGE0-BLOCKED) 존중 — 레이아웃은 최소(서버렌더 Jinja2+HTMX 유지).

---

## 5. 소스별 합법 · 쿼터 운영표 (착수 시 실측 게이트)

| 소스 | 키 | 쿼터 | 합법 경계 | 실측할 것 |
| --- | --- | --- | --- | --- |
| 네이버 오픈API | 있음(config) | 일 한도 | 요약만(P5) | 키워드수×호출 예산이 일 한도 내인지 |
| KR/글로벌 RSS | 불필요 | 관대 | 신디케이션, 요약만 | 발행시각 파싱 정확도(매체별 pubDate 포맷) |
| OpenDART | 필요 | **일 2만+throttling** | 본문 합법 | 실적시즌 스파이크 백오프, 다중키 ToS |
| SEC EDGAR | UA만 | fair-access | 본문 합법 | UA 차단 여부, rate limit 준수 |
| Marketaux | 필요 | 100/일 | 무료 API | 코인 커버리지 폭 |
| Finnhub | 필요 | 60/분 | 무료 API | 크립토 뉴스 실제 폭(STAGE1 §5.8 게이트) |

---

## 6. 임베딩 모델 결정 (D2 선결, §11.3 해소안)

KR 헤드라인이 dedup·검색 품질을 좌우. **실측 후 확정**(추측 금지). 후보:

| 옵션 | 장점 | 단점 | dim |
| --- | --- | --- | --- |
| **bge-m3**(로컬, 다국어) | KR 강함·무료·오프라인·긴 문맥 | GPU 없으면 느림, 운영 부담 | 1024 |
| **multilingual-e5-large**(로컬) | KR 양호·무료 | 〃 | 1024 |
| OpenAI text-embedding-3-large(API) | 운영 간단·고품질 | 비용·외부의존·KR 상대 약 | 3072 |
| Voyage-3(API) | 검색 특화 고품질 | 비용·외부의존 | 1024 |

- **권장 시작점:** 로컬 **bge-m3**. 이유: 이 제품의 코퍼스가 KR 비중 높고, zero-fabrication
  제품이라 외부 API 의존을 줄이는 게 신뢰·비용·합법 모두에 유리. 단 GPU/속도 실측 후 확정.
- **결정 산출물:** dedup precision/recall(KR 헤드라인 라벨셋) + 검색 recall@k 실측표 →
  `embedding_model`/`embedding_dim` config 확정 → `Vector(dim)` 마이그레이션.

> **게이트:** 모델 미확정 상태로 RAG 코드를 먼저 짜지 말 것. dim이 안 정해지면 인덱스·마이그
> 레이션이 안 선다. 트랙 D는 이 표가 채워진 뒤 착수.

---

## 7. 일일 다이제스트 grounding 계약 (D1 실체화)

```
daily_digests(
  id, brief_date,
  section,          -- 'macro' | 'sector:<섹터명>'  (자유문자열, taxonomy STAGE0-BLOCKED)
  heading,          -- 예: "미국 금리 인하 기대 확대"
  body_text,        -- 요약. 모든 주장은 아래 인용에 묶임
  status,           -- ok | degraded | empty
  generated_at
)
digest_sources(digest_id, brief_item_id)   -- 다이제스트 ↔ 근거 brief_item 역추적
```

- **입력:** 그날 status=ok인 brief_items + 그 citations(cited_text). LLM은 이 집합만 본다.
- **2-패스:** 패스1 Citations로 "거시 테마·영향 섹터" 문장 생성(인용 강제), 패스2 구조화
  (section/heading/body). **패스2는 패스1 인용 범위 밖 사실 도입 금지**(STAGE1 §7 무결성 규칙).
- **거부 규칙:** 인용 가능한 brief_item 0 → status=empty(빈 다이제스트, 정직).
- **추적:** 다이제스트 카드 → digest_sources → brief_item → citation → 원문 char 범위.
  (제품 본체 P2를 거시 altitude로 그대로 연장.)

---

## 8. 추가 제품 아이디어 (#5) — 경계 안에서 가치 큰 것 순

기존 컴플라이언스 경계(D1)를 깨지 않으면서 PAIN_POINT를 직접 때리는 것만.

1. **커버리지 필터 푸시(가장 큰 미충족 가치).** DESIGN의 "The Assignment"이자 PAIN_POINT
   §1-1의 핵심: "내 커버리지에 영향 줄 만한 것만". 애널리스트별 coverage로 그날 brief_items를
   필터해 **아침에 실제 여는 창(메신저/메일)으로 푸시**. 대시보드를 안 열어도 가치 전달.
2. **"놓치면 치명적" 알림.** coverage 종목에 confidence=HIGH 부정 이벤트 → 즉시 알림.
   PAIN_POINT §1-1 "모닝미팅 망신" 직접 해소. 임계·경계는 STAGE0-BLOCKED라 설정값으로.
3. **모닝미팅 포맷 내보내기.** 그날 다이제스트+근거를 복붙 가능한 표/마크다운으로 export.
   PAIN_POINT §1-3 "재료 패키징" 가치(완성 리포트 아님).
4. **주간 롤업.** DESIGN대로 "주간 = 일간 다이제스트 집계". daily_digests 있으면 거의 공짜.
5. **실적시즌 모드(2·3·5·8·11월).** 공시 본문 수집이 들어오면 컨센서스 없이도 "발표 확인 +
   가이던스 변화 문구 추출" 1차 정리 초안. PAIN_POINT §2-3.
6. **소스 헬스/degraded 패널.** 어떤 소스가 빠졌는지 투명 표기(§10). 전문가 신뢰의 조건.
7. **워치리스트/저장 질의.** RAG 채팅 위에 자주 묻는 질의 저장.

> 의도적으로 **뺀 것:** 종목 점수/랭킹, 매수 시그널, 목표가 — D1·P1 위반. "좋아 보이는
> 기능"이라도 추천처럼 보이면 이 시장에선 신뢰를 잃는다(PAIN_POINT §3).

---

## 9. 리스크 · 검증 게이트 요약 · 다음 액션

**리스크:**
- D1 침범 위험: 다이제스트/RAG가 슬그머니 자유 서술로 새는 것. → §7·§2 인용 거부 규칙을
  CI 회귀(swap test + 인용 0 거부)로 강제.
- 임베딩 dim 비가역: 모델 성급 확정 → 재임베딩 비용. → §6 실측 게이트.
- 쿼터/합법: 소스 7개로 늘며 운영 부담 증가. → 소스 격리(트랙 B) + 캐싱/증분.

**하드 게이트(통과 못 하면 진행 금지):**
1. 조작/존재하지 않는 인용 = 0 (다이제스트·RAG 포함, CI 회귀).
2. 티커 링킹 precision ≥ 95%(미달 "후보" 표기) — 기존 §6.4 유지.
3. 임베딩 모델 dedup/검색 실측표 채움 → dim 확정 → 그 후에만 트랙 D.

**다음 액션(권장 순서):**
1. **트랙 B 먼저** — 일일 오케스트레이션 골격(`run_daily`) + cron. 수집 자동화가 통째로
   없는 게 가장 큰 구멍. 기존 코인 RSS만으로도 매일 도는 걸 먼저 검증.
2. **트랙 A** — 소스를 RSS(키 불필요)부터 추가(KR 경제지·글로벌 매크로). 그다음 네이버,
   마지막에 공시 본문(쿼터 부담 큼).
3. **트랙 C** — 코퍼스가 쌓이면 일일 다이제스트(인용 묶음).
4. **§6 임베딩 실측** → 확정 → **트랙 D/E**(RAG + 뷰).

> **The Assignment(실무 검증):** 코드 전에, 트랙 A 소스 우선순위를 실제 사용자(애널리스트)
> 한 명에게 물어라 — "아침에 *먼저* 여는 창이 뉴스냐 공시냐 컨센서스냐"(STAGE1 §2
> STAGE0-BLOCKED). 그 답이 트랙 A 순서와 다이제스트 1면 우선순위를 정한다. 지금은 추측 중.
