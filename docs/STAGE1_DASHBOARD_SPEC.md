# 증거 브리프 대시보드 — 추적성 뷰 + 근거기반 채팅

## Context
파이프라인이 라이브로 `brief_items`를 채우기 시작했지만(실측 8건/citations 20건) `/` 라우트는 플레이스홀더만 렌더한다(`app/main.py:41-43`, `index.html`). 애널리스트가 "이 종목 추천이 어떤 뉴스를 기준으로 어떤 근거(인용·발행시각·이벤트·방향·신뢰도)로 나왔는지" 확인할 화면이 없다. 추적성은 이 제품의 신뢰 1차 조건(§10, PAIN_POINT §3-1). 여기에 자유 자연어 질의에 근거기반으로 답하는 채팅을 더한다.

## Out-of-Design-Scope (명시적 일탈)
채팅(요구 #2)은 설계가 의도적으로 뒤로 미룬 것을 당긴다. 사용자 검토 후 강행 결정.
- §4/§11.4: "클릭-투-소스만 먼저, 무거운 인터랙션은 Stage 0 후" → 채팅이 그 무거운 인터랙션.
- 트레이드오프 수용: 쿼리당 Anthropic 비용(무제한), 환각 표면 증가. 완화책: §7과 동일한 Citations 강제·zero-fabrication 경계로 가둔다. 인용 0 = 거부.

## Current State (검증됨)
- `app/main.py`: `GET /health`, `POST /trigger`(오늘 KST run_pipeline), `GET /`(플레이스홀더 렌더).
- 데이터 사슬(`app/models.py`): `brief_items`(event_type/direction/confidence/analysis_text/status/generated_at) → `brief_item_tickers`(ticker/market/link_precision/is_candidate) → `citations`(cited_text/char_start/char_end/source_published_at/raw_document_id) → `raw_documents`(title/url/published_at).
- Anthropic 패턴 존재(`app/pipeline/citations.py`): `build_client`(truststore), Citations API document 블록, 인용 0 → 빈 결과 거부. `settings.impact_model="claude-opus-4-8"`, `settings.anthropic_api_key`.
- 웹 테스트·읽기 모듈 없음. `app/web/`엔 templates/static만.

## Proposed Change

### 라우트 (`app/main.py`)
| 메서드·경로 | 동작 |
|---|---|
| `GET /?date=YYYY-MM-DD` | 해당 날짜(기본 오늘 KST)의 `brief_items.brief_date` 행을 추적성 트리로 렌더. 기본값은 `main.py:33`과 동일 `datetime.now(_KST).date()`. |
| `POST /chat` (HTMX) | form `q`(자유 텍스트), `date`(선택). 해당 날짜 brief를 근거로 Citations 강제 답변 HTML 프래그먼트 반환. 인용 0/키 없음/오프토픽 → graceful 거부. |
| `GET /health`, `POST /trigger` | 변경 없음. |

### 읽기 모듈 (신규 `app/web/queries.py`)
프로젝트 I/O 경계 관례(rss.py/citations.py)대로 분리.
- `load_brief(session, brief_date) -> list[BriefView]`: brief_item + tickers + citations(+raw_documents url/published_at) 조립. 1쿼리셋, 메모리 그룹핑.
- `BriefView` dataclass: item 필드 + `tickers: list` + `citations: list[CitationView]`(cited_text/source_published_at/url/title). `last_updated` = max(generated_at, citation fetched).

### 채팅 모듈 (신규 `app/web/chat.py`)
- `citations.build_client` 재사용. brief의 분석문+인용을 document 블록으로 먹이고 `citations:{enabled}` 강제.
- `answer(client, model, question, brief_views) -> ChatAnswer | None`: 인용 ≥1이면 (답변텍스트, 인용→url) 반환, 인용 0이면 거부 신호. 단일 턴, 이력·스트리밍 없음.
- `anthropic_api_key` 없으면 라우트가 "채팅 비활성" 반환(§7 정책 일관).

구현 계약(codex 게이트 보강):
- 인용→URL 매핑: `citations.parse_pass1`과 동일 패턴 — document 블록 순서가 `document_index`, 그 인덱스로 입력 brief의 `raw_document_id`를 역참조 → `raw_documents.url`. 새 파싱 발명 금지, 기존 `getattr` 방어 접근 재사용.
- 거부 판정(요구 #2 정밀): `answer`가 `None`(analyzer 키 없음/APIError) **또는** 인용 0건이면 라우트는 "관련 근거 없음" 프래그먼트. LLM의 텍스트 자체로 거부 판정하지 않음 — 인용 유무가 유일 기준.

### 템플릿 (`app/web/templates/`)
- `index.html`: 상단 채팅 박스(HTMX `hx-post=/chat` → `#chat-answer`), 하단 brief 리스트.
- `_brief_item.html`: 항목 헤더(event_type/direction/confidence 있는 그대로, 색·아이콘 체계 미부과) + 펼침 시 analysis_text·tickers(`is_candidate`→"후보")·citations(cited_text+발행시각, 각 인용 → `raw_documents.url` click-to-source, url 없으면 "원문 링크 없음").
- `_chat_answer.html`: 답변 + 인용 링크, 또는 "관련 근거 없음".
- §10 상태: brief 0건 → "브리프 없음 + last_updated"; `status=degraded`→배지; `status=empty`→"근거 없음"(분석문 미렌더).

## Acceptance Criteria
1. `GET /`(오늘 brief 존재) → 모든 brief_items 렌더, 각 항목에 direction·confidence·event_type 표시·펼침 가능.
2. 펼치면 analysis_text + 모든 ticker(`is_candidate`면 "후보") + 모든 citation(cited_text+source_published_at) 표시.
3. 각 citation이 `raw_documents.url`로 링크(새 탭). url 없으면 "원문 링크 없음".
4. `status=empty` 항목은 "근거 없음" 렌더, analysis_text 환각 미표시.
5. 해당 날짜 brief 0건 → "브리프 없음" + last_updated.
6. `POST /chat`(오늘 brief에 근거 있는 질문) → 답변에 ≥1 인용 링크 포함.
7. `POST /chat`(의미없는/오프토픽/빈 입력) → "관련 근거 없음" graceful(HTTP 200, 에러·환각 없음).
8. `anthropic_api_key` 미설정 → 채팅 박스 비활성 표시, `POST /chat` → "채팅 비활성".
9. `?date=` 파라미터로 과거 brief_date 조회 가능, 기본 오늘(KST).
10. 기존 `/health`·`/trigger` 무변경, 테스트 통과.

## Testing Plan
| Layer | What | Count |
|---|---|---|
| Unit | `load_brief` 그룹핑, `BriefView.last_updated`, 채팅 인용 파싱·거부 로직(스텁) | +5 |
| Integration | 시드 DB → `GET /` HTML 단언; `POST /chat` 스텁 analyzer로 근거있음 vs 거부 | +4 |
| E2E | 대시보드 로드→항목 펼침→원문 클릭; 채팅에 헛소리→거부 표시 | +2 |

## Rollback Plan
스키마·마이그레이션 변경 없음(기존 테이블 읽기 전용). PR revert 시 `/`는 플레이스홀더로 복귀, 채팅은 추가 엔드포인트라 제거. 데이터 리스크 0.

## Effort Estimate
`queries.py` 2h + 템플릿/HTMX/CSS 3h + `chat.py` 3h + `main.py` 배선 1h + §10 상태 1h + 테스트 4h = ~14h.

## Files Reference
| File | Change |
|---|---|
| `app/main.py:41-43` | `GET /` 확장(`?date=`), `POST /chat` 신규 |
| `app/web/queries.py` | 신규: `load_brief`, `BriefView` |
| `app/web/chat.py` | 신규: `answer`, `build_client` 재사용 |
| `app/web/templates/index.html` | 채팅 박스 + brief 리스트 |
| `app/web/templates/_brief_item.html`, `_chat_answer.html` | 신규 partial |
| `app/web/static/app.css` | 추적성 트리·채팅 스타일 |
| `tests/test_web.py` | 신규 unit+integration |

## Out of Scope
커버리지 필터(§9 STAGE0), taxonomy·1면 우선순위(§2 STAGE0), 신뢰도 색·아이콘 체계(§10 STAGE0), 멀티턴·스트리밍·채팅이력 영속화, 인증, 히스토리 의미검색·임베딩(§11.3), 날짜 피커 UI(파라미터만), SPA 전환.

## Related
- STAGE1_DESIGN.md §3/§4/§7/§9/§10/§11.4
- 라이브 실측 체크포인트 20260622-155213
