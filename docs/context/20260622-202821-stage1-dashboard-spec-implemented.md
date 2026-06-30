---
status: in-progress
branch: main
timestamp: 2026-06-22T20:28:21+09:00
session_duration_s: unknown
files_modified:
  - app/main.py
  - app/web/queries.py
  - app/web/chat.py
  - app/web/templates/index.html
  - app/web/templates/_brief_item.html
  - app/web/templates/_chat_answer.html
  - app/web/static/app.css
  - pyproject.toml
  - tests/test_web.py
  - tests/test_health.py
  - uv.lock
---

## Working on: Stage 1 증거 브리프 대시보드 spec 구현

### Summary

`docs/STAGE1_DASHBOARD_SPEC.md`(커밋 9c4fc33, spec만 존재)를 코드로 구현. `/` 플레이스홀더를
추적성 뷰로 교체하고 근거기반 LLM 채팅(`POST /chat`)을 추가. 게이트 전부 통과 —
ruff/mypy clean, **pytest 72 passed**(직전 57 → +15 신규). 미커밋 상태.

### Decisions Made

- **읽기 모듈 분리(`app/web/queries.py`):** rss.py/citations.py I/O 경계 관례대로 라우트에서
  분리. `load_brief`는 brief_items + tickers + citations(+raw_documents **outer join**)를
  세 쿼리로 읽어 메모리 그룹핑 — 티커×인용 카티전 폭발 회피. `BriefView.last_updated`는
  generated_at·인용 source_published_at의 max(property). citation outer join이라 원문 삭제 시
  url/title None 가능(템플릿 '원문 링크 없음' 처리).
- **채팅 zero-fabrication 경계(`app/web/chat.py`):** §7과 동일 — 그날 브리프의 **실제 인용
  근거(cited_text)만** citable document 블록으로 먹이고 Citations 강제. analysis_text는 LLM
  생성물이라 citable 대상에서 제외(1차 근거만). `citations.parse_pass1` 패턴·getattr 방어
  접근 재사용, 순수 `_parse_chat`와 I/O `anthropic_chat` 분리(네트워크 없이 단위 테스트).
  거부 판정 = **인용 유무가 유일 기준**(LLM 텍스트로 판정 안 함). 인용 0/APIError/근거 0 → None.
- **거부 매핑(`POST /chat`):** 키 없음 → '채팅 비활성'; 빈 입력 → analyzer 미호출 후 '관련
  근거 없음'; analyzer None → '관련 근거 없음'. 전부 HTTP 200 graceful. `_chat_analyzer()`를
  모듈 함수로 빼 테스트가 monkeypatch(네트워크·키 불필요).
- **python-multipart 의존성 추가:** FastAPI `Form` 파싱 필수(uvicorn[standard]에 없음).
- **HTMX는 CDN**(unpkg 2.0.3). `index.html` 채팅 박스 `hx-post=/chat` → `#chat-answer`.
- **기존 test_health.test_dashboard_root에 db 픽스처 부착:** `GET /`가 이제 DB를 읽으므로
  무-DB 환경에선 skip(이전엔 플레이스홀더라 DB 불필요). surgical — 라우트 변경에서 직접 파생.
- **ruff format은 내가 만진 파일만**(main.py, test_web.py). pipeline.py도 format 대상에
  떴으나 이번 변경과 무관(pre-existing)이라 안 건드림.

### Remaining Work

1. **커밋·푸시 대기:** 사용자 확인 후. 변경 = queries.py/chat.py/templates 3개 신규 +
   main.py/css/pyproject/test_health 수정 + test_web.py 신규. docs/context 미러도 함께.
2. **(미구현, spec Out of Scope)** 브라우저 E2E(+2): TestClient 통합이 렌더 HTML·인용 링크·
   거부를 이미 단언해 핵심 커버. 멀티턴·스트리밍·채팅이력, taxonomy 색/아이콘, 날짜 피커 UI.
3. **(옵션)** 실 ANTHROPIC_API_KEY로 `POST /chat` 라이브 스모크(현재 가짜 analyzer만).
4. **(Stage0-블록, 이전부터)** §6.5 event-classify(taxonomy 값 범위 대기), 유니버스 실데이터 CSV.

### Notes

- **검증 인프라:** DB 통합테스트용 `fa_test_pg`(ankane/pgvector, localhost:5433,
  finance_agent_test) 컨테이너를 이 세션에 새로 띄움(이미지 pull 포함). 계속 떠 있음 —
  pytest DB 게이트가 이걸 씀. Docker Desktop도 이 세션에서 기동.
- **AC 10/10 검증:** 1-5 대시보드 렌더(direction·confidence·event_type·인용 링크·empty→
  '근거 없음'·0건→'브리프 없음'), 6-8 채팅(근거→인용링크/오프토픽·빈입력→거부/키없음→비활성),
  9 `?date=` 과거조회+잘못된 형식 400, 10 기존 라우트 무변경.
- **게이트 경고(무해):** TestClient httpx deprecation, alembic path_separator deprecation —
  기존부터 있던 것, 이번 변경과 무관.
- **체크포인트 정본:** docs/context/(커밋)가 단일 소스, 이 gstack 미러는 보조.
