---
status: in-progress
branch: main
timestamp: 2026-06-21T15:41:09+09:00
session_duration_s: unknown
files_modified:
  - app/config.py
  - app/pipeline/citations.py
  - app/pipeline/pipeline.py
  - tests/test_citations.py
  - tests/test_pipeline.py
---

## Working on: Stage 1 — §7 2-패스 Citations 영향도 분석 (커밋·푸시 완료)

### Summary

복귀 후 체크포인트의 "다음 최고가치 = §7 Citations"를 골라 구현. claude-api 스킬로 API
계약을 그라운딩(메모리 아님) → **Citations API와 Structured Outputs는 한 콜 동시 사용
불가(400)**라 2-패스 분리가 설계 §7의 근거임을 확인. 패스1(Citations로 cited_text 강제
추출 분석) → 패스2(Structured Outputs로 event_type/direction/confidence 재구조화, 무결성
규칙: 패스1 인용 범위로만 입력 제한). brief_item이 status=empty → ok로 채워진다. 전 게이트
green(pytest 45→57). 피처 커밋 **1c077a5** main 푸시 완료(origin/main).

### Decisions Made

- **다음 action:** 사용자 AskUserQuestion에서 "§7 Citations 2-pass" 선택. 체크포인트가
  최고가치 unblocked로 지목한 작업.
- **2-패스 설계 그라운딩:** claude-api 스킬 로드 → §7의 "동시 사용 불가" 근거가 실제 API
  제약임을 확인. 패스1 `citations:{enabled:true}` document 블록 → 응답 text 블록의
  citations 배열(`cited_text`+`document_index`+char 범위). 패스2 `output_config.format`
  json_schema. 모델 claude-opus-4-8(설계 §7 고정), 패스1 thinking adaptive.
- **무결성 규칙 강제 (§7 가장 중요):** 패스2 입력은 패스1 분석 텍스트 + 실제 cited_text만.
  **원문 본문(title/summary)은 패스2에 미주입** — 새 사실 도입 차단. 테스트
  `test_pass2_input_contains_only_cited_spans_not_documents`가 가드.
- **영향 종목은 LLM이 아님 (내 결정, 사용자 미반대):** 패스2는 event/direction/confidence만
  반환. 티커는 deterministic `ticker_link`(§6.4) 사전 기반이 결정 — 추천 근거·유니버스를
  감사가능하게 유지(§2). citations는 패스1 산출.
- **status 매핑 (§10 null-evidence):** 인용 ≥1 → ok(analysis_text+citations 적재) /
  analyzer None(API장애·쿼터) → degraded / 인용 0건 → empty 유지(환각으로 안 채움).
- **주입형 analyzer:** `run_pipeline(analyzer=...)` 기본 None. 키 있으면 실 분석기 자동 생성,
  없으면 비활성(골격 유지). 테스트는 가짜 analyzer 주입 → 네트워크 없이 DB 적재 검증.
- **truststore:** Anthropic 클라이언트도 OS 인증서 신뢰(`build_client`) — rss.py와 동일
  사내 TLS 경계.

### Remaining Work

1. **(미결정·이월) CLAUDE.md flush 규칙 제안:** "파이프라인 단계가 직전 단계가 같은 세션에서
   쓴 행을 읽으면 그 단계 끝 `session.flush()`(SessionLocal autoflush=False)" — Measurable
   Conventions 추가 여부 **사용자 확인 대기**. dedup 버그의 재발 클래스. 이번 세션 미반영.
2. **(옵션) LLM 티커 후보:** 현재 모델은 티커를 만들지 않음(사전만). 사전 밖 후보를 LLM이
   제안하게 할지는 별도 결정 — 사용자 판단 대기.
3. **(옵션) §7 라이브 엔드투엔드:** 실 ANTHROPIC_API_KEY로 run_pipeline 스모크. 현재는 가짜
   analyzer로만 검증(키·네트워크 불필요·결정론). DB 하니스 있어 쉬움.
4. **#6.5 event-classify:** Stage0-블록(taxonomy 관찰 미완). 인터페이스만 고정. 값 범위 대기.
   (참고: §7 패스2 schema의 event_type은 자유 문자열·direction/confidence는 enum 고정.)
5. **유니버스 실데이터:** Stage0-블록. load_dictionary 준비됨, 운영자 CSV 대기. 코드 무변경.
6. **(옵션) #5 동시성 가드 통합테스트:** 두 연결 advisory lock 충돌. 하니스로 작성 가능.

### Notes

- **git:** 피처 커밋 **1c077a5**(+499/-9, 신규 app/pipeline/citations.py·tests/test_citations.py)
  **origin/main 푸시 완료**(3bd8d47..1c077a5). 이번엔 직접 푸시가 막히지 않음 — 세션 중
  `/login` 후 통과. 직전 HEAD=3bd8d47.
- **이 docs 미러는 별도 docs: 커밋 필요**(정본 docs/context/, gstack는 보조).
- **게이트:** pytest **57 passed**(+12: 파서·2패스 오케스트레이션·DB 적재 ok/degraded/멱등),
  ruff check ✓, ruff format ✓, mypy ✓(29 files).
  명령: `uv run pytest -q` / `uv run ruff check .` / `uv run ruff format --check .` / `uv run mypy .`.
- **테스트 하니스:** Docker `fa_test_pg`(ankane/pgvector, 포트 5433) 이번 세션에 재기동
  (`docker start fa_test_pg`). 정리 `docker rm -f fa_test_pg`. 미연결 시 DB 테스트 skip.
- **mypy 경계:** anthropic SDK `messages.create`의 messages 인자는 `cast("list[MessageParam]")`
  필요(패스1, content가 dict 블록 리스트라). 패스2는 content가 str이라 캐스트 불필요.
- **새 설정:** config.anthropic_api_key(키 없으면 §7 비활성), config.impact_model=claude-opus-4-8.
- Windows uv 출력 파이프 주의(grep/head 필터 시 본문 소실 — 필터 없이 실행).
- **체크포인트 정본:** docs/context/(커밋)가 단일 소스, gstack 미러는 보조.
