# 플랜 11: LLM 게이트웨이 도입 (LiteLLM 기반)

## Context

LLM 호출이 anthropic/openai SDK 직접 호출로 각 모듈에 흩어져 있어(클라이언트 생성 2곳,
키·모델 참조 10곳+) provider/모델 교체 시 여러 파일을 고쳐야 한다. 플랜 08~10의 provider
비교 실험에서 이 관리 비용이 실증됐다. 요구사항:

1. **LLM 게이트웨이 신설** — LiteLLM 라이브러리 기반(사용자 선택), 쉽게 교체 가능하게
2. **전체 파이프라인 고려** — 파급 수정(호출부·하네스·스크립트·테스트·문서) 필수 진행
3. **Agent 로직 동작 동일** — 기본 설정에서 현행과 같은 요청 페이로드/파싱/에러 계약

사용자 결정: LiteLLM 라이브러리 / **용도별 스위치**(임팩트·다이제스트·챗 각각
provider·model) / **.env + 재시작** / **다이제스트·챗의 OpenAI(quote-and-verify) 전략도
이번에 신규 구현**.

## LiteLLM 리서치 결론 (2026-07-08 웹 검증 — 설계를 결정지은 사실)

- **`litellm.completion` + `response_format` 사용 금지**: opus-4-8이 structured output
  네이티브 게이트(하드코딩 모델 목록)에 없어 **강제 툴콜 우회로 변환** → 출력 분포 상이,
  동작 동일성 위반. citations도 BETA 재구성 경로(구조 변경 이력). **항상 Anthropic 원생
  `output_config`를 kwarg passthrough로 전달한다.**
- **채택: `litellm.anthropic.messages.create()`** (네이티브 브리지, 동기 create 존재) —
  /v1/messages 스펙 그대로 전송(top-level 화이트리스트에 max_tokens/system/thinking/
  output_config 포함, v1.81.12+), 응답은 **raw Anthropic JSON dict**(content 블록별
  citations 원형 보존: cited_text/document_index/start·end_char_index).
- **채택: `litellm.responses()`** — OpenAI Responses API 전 파라미터 1:1(instructions/
  input/text json_schema strict/reasoning effort), `output_text`·`usage` 동일 접근
  (`output_tokens_details`는 Optional → None 가드).
- **SSL**: 전역 `litellm.ssl_verify=SSLContext`는 조용히 무시되는 오픈 버그(#14396) →
  `truststore.inject_into_ssl()`을 게이트웨이 모듈에서 litellm import 전 1회(모듈 캐싱으로
  프로세스당 1회 보장).
- **import 시 원격 단가맵 fetch** → `LITELLM_LOCAL_MODEL_COST_MAP=True` 선설정.
- **버전 정확 핀: `litellm==1.91.0`**(2026-07-04 stable; 주간 릴리스 회귀 잦음).
- litellm 예외는 openai 예외 상속 계열(연결·타임아웃 포함) → 게이트웨이가 단일
  `LLMError`로 정규화.

## 현황 인벤토리

### 운영 LLM 경로 (전부 Anthropic Citations API, settings.anthropic_api_key 게이트)

| 경로 | 파일:심볼 | 형태 |
|---|---|---|
| 임팩트 분석 | `app/pipeline/citations.py:anthropic_analyzer` | 2-패스: P1 citations+thinking adaptive(4096) → P2 output_config json_schema(1024) |
| 다이제스트 | `app/pipeline/digest.py:anthropic_digester` | 동일 2-패스(P2 8192, stop_reason 경고) |
| 날짜 챗 / RAG 챗 | `app/web/chat.py:anthropic_chat / anthropic_rag_chat` | 단일 패스 citations(1024) |
| (실험) OpenAI 임팩트 | `app/pipeline/openai_citations.py:openai_analyzer` | Responses API, json_schema strict, quote-and-verify, reasoning.effort |

### 주입 지점
`pipeline.py:350-353`(분석기 자동 생성), `runner.py:270-274`(digester),
`main.py:88-90/116-122/157-158/218/245`(챗·RAG·digester·chat_enabled 게이트),
`scripts/backfill_impact_score.py:27`, `scripts/build_digest_for.py:23`,
`scripts/compare_providers.py:253-258`(+`_RecordingMessages` 토큰 프록시)

### 재사용할 기존 추상화
`ImpactAnalyzer`/`Digester`/`ChatAnalyzer`/`RagChatAnalyzer` 콜러블 타입, `SourceDoc`/
`CitedSpan`/`ImpactResult`/`DigestInput`/`DigestSection`/`ChatAnswer` dataclass,
`AnalyzerStats`, `prompt_versions.py` 레지스트리(v0 항등), 순수 파서(`parse_pass1`/
`verify_quotes`/`_parse_chat`)

## 설계

### 아키텍처 결정
- **D1. Transport = 콜러블 클로저**(기존 스타일 동형).
  - `AnthropicMessages = Callable[..., dict[str, Any]]` — 분석기는
    `transport(model=model, max_tokens=4096, thinking=..., system=..., messages=...)`처럼
    **현행 `client.messages.create` kwargs를 바이트 동일하게** 호출. transport 내부에서
    api_key 부착 + `model`을 `f"anthropic/{model}"`로 프리픽스 후
    `litellm.anthropic.messages.create` 호출, raw dict 반환, 주입된 stats를 in-place 갱신.
  - `OpenAIResponses = Callable[..., Any]` — 동일 패턴으로 `litellm.responses` 래핑
    (`openai/` 프리픽스), litellm `ResponsesAPIResponse` 반환(output_text/status/usage 접근
    현행과 동일).
- **D2. `AnalyzerStats`를 gateway로 이동**(순환 import 회피), `openai_citations.py`에서
  재수출(기존 import 경로·compare_providers 무수정 유지).
- **D3. 토큰·calls 집계를 transport로 이동**(in-place 갱신) — `_RecordingMessages` 프록시
  제거의 귀결. 분석기에는 quote 메트릭(quotes_returned/dropped)만 남김. compare는 같은
  stats 인스턴스를 transport와 analyzer 양쪽 주입. openai `calls` 의미가 "성공 파싱 수"→
  "성공 API 응답 수"로 이동(compare 출력에 calls 미표기 — 무영향).
- **D4. `verify_quotes` → 3-튜플** `(spans, dropped, verified_doc_indices)` —
  3번째는 검증 통과 인용의 doc_index를 **등장 순서 dedupe**한 리스트(digest의
  source_brief_item_ids 역산용, anthropic parse_pass1 의미론 미러). 기존 호출부
  `openai_citations.py:203`은 `citations, dropped, _ =`로, 테스트 언패킹도 함께 수정.
- **파서는 dict 전용으로 전환**: `getattr(block, ...)` → `block.get(...)`
  (시그니처 `Iterable[Any]` 유지, text 아닌 블록—thinking 포함—스킵 의미 동일).
  **모든 테스트 목킹을 SimpleNamespace → dict 리터럴로 전면 전환**(오히려 단순해짐).
- **에러 정규화**: transport가 `except openai.OpenAIError → raise LLMError from exc`
  (litellm의 연결·타임아웃 예외 포함 — 현행 anthropic.APIConnectionError⊂APIError 계약과
  등가). 분석기 except 절은 `(LLMError, json.JSONDecodeError)` — None 반환 계약 불변.
- **초기화 보장**: gateway.py 모듈 레벨에서
  `os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP","True")` →
  `truststore.inject_into_ssl()` → `import litellm`(noqa: E402) → telemetry off·
  suppress_debug_info·LiteLLM 로거 WARNING. **gateway가 repo 유일의 litellm import
  지점**(단계 7에서 grep로 강제)이고 모든 LLM 모듈이 gateway에서 LLMError/transport를
  import하므로, litellm 사용 전 초기화가 이행적으로 보장된다.

### 신규 파일
- `app/llm/gateway.py` — 위 초기화 + `LLMError` + `AnalyzerStats`(이동) +
  `anthropic_messages(api_key, stats=None) -> AnthropicMessages` /
  `openai_responses(api_key, stats=None) -> OpenAIResponses`.
- `app/llm/factory.py` — `make_impact_analyzer() / make_digester() / make_chat_analyzer()
  / make_rag_chat_analyzer(embedder) / chat_key_configured()`. 전역 settings를 **호출
  시점에** 읽음(현행 main.py 패턴 보존 — settings monkeypatch 테스트 유효). provider 분기
  → 해당 키 없으면 None(graceful 게이트), 미지 provider는 ValueError(오타를 조용한
  비활성으로 오진 방지). 모델 폴백: `digest_model or impact_model` 등.
  compare_providers는 factory 미사용(모델·프롬프트 오버라이드가 인자 기반 — gateway 직결).
- `app/pipeline/openai_digest.py` — OpenAI 다이제스트 전략(단일 콜 quote-and-verify).
  합성 SourceDoc(`summary=_input_text(inp)`, raw_document_id/published_at은 첫 citation에서)
  으로 `_document_text(doc) == _input_text(inp)` 정렬을 만들어 `verify_quotes` 재사용.
  sections+citations JSON 스키마(strict), `max_output_tokens=8192`, 검증 인용 0 → `[]`,
  source_ids는 verified_doc_indices 등장 순서 dedupe, 섹션에는 전체 인용+전체 소스 부착
  (anthropic 폴백 의미론 미러), 에러 → None. Digester 계약 완전 동일.
- `app/web/openai_chat.py` — `_verify_chat_citations`(순수: doc_index 범위 → cited_text
  substring 정확 일치 → `_normalize_ws` 재시도 → (url,quote) dedupe → ChatCitation) +
  `openai_chat` / `openai_rag_chat`(top_k=8 미러). sources 0 → None(콜 없이), 검증 인용
  0 → None, 에러 → None.

### 설정 확장 (app/config.py — 기본값 조합 = 현행 항등)

| 필드 | 기본값 | 의미 |
|---|---|---|
| `impact_provider` | `"anthropic"` | 임팩트 분석 provider (anthropic \| openai) |
| `digest_provider` | `"anthropic"` | 다이제스트 provider |
| `chat_provider` | `"anthropic"` | 챗(날짜+RAG 공통) provider |
| `impact_model` | `"claude-opus-4-8"` | 기존 필드 유지 — 임팩트 모델 + 전 용도 폴백 |
| `digest_model` | `None` | None → impact_model 폴백 |
| `chat_model` | `None` | None → impact_model 폴백 |

`openai_api_key` 기존 필드 재사용(주석만 갱신). reasoning_effort는 운영 설정에 넣지 않음
(compare 플래그로만 유지 — 요청 범위 밖).

### 수정 파일
- `citations.py`/`digest.py`/`chat.py`: `client` → `transport` 파라미터(내부 호출 1:1
  치환, **요청 kwargs 불변**), 파서 dict 접근 전환, `except (LLMError,
  json.JSONDecodeError)`, `build_client`·`import anthropic`·truststore/ssl import 삭제,
  응답 접근 `pass1.content`→`pass1["content"]`, `stop_reason`은 `.get()`.
- `openai_citations.py`: `litellm.responses` transport 전환(요청 kwargs 불변,
  `resp.output_text`/`resp.status` 접근 불변), stats 토큰 갱신 4줄 삭제(D3),
  verify_quotes 3-튜플(D4), `AnalyzerStats` 재수출, `build_openai_client` 삭제.
- 호출부: `pipeline.py:350-353` → `make_impact_analyzer()`, `runner.py` →
  `make_digester()`(지연 import 블록 삭제), `main.py` — `_chat_analyzer()`/`_rag_analyzer()`
  **함수 껍데기 유지**(테스트 monkeypatch 표면 보존, 내부만 factory 호출), chat_enabled·
  `_rag_available` 게이트 → `chat_key_configured()`, `_NO_KEY_MSG` →
  `f"채팅 비활성 ({settings.chat_provider.upper()}_API_KEY 미설정)"` 산출(기본 설정에서
  현행 문자열 `"채팅 비활성 (ANTHROPIC_API_KEY 미설정)"`과 바이트 동일 — 확인 완료).
  `scripts/backfill_impact_score.py`·`build_digest_for.py` → factory + assert.
- `compare_providers.py`: `_RecordingMessages` 삭제 → `anthropic_messages(key, stats)`
  transport 주입(openai는 stats 이중 주입). **CLI 플래그·출력 표·단가표·summary.json
  전부 불변**(플랜 10 하네스 보존).
- `pyproject.toml`: `litellm==1.91.0` 추가. 마지막 단계에서 `import anthropic` 0건 +
  `uv tree`로 litellm의 anthropic 미의존 확인 후 `anthropic` 의존성 제거(`openai`는
  gateway가 직접 씀 — 명시 유지).
- `tests/conftest.py`: `OPENAI_API_KEY=""` 추가(provider 스위치 도입 후 라이브 콜 차단).
- `docs/learnings/04-citations-and-ai-analysis.md`: build_client → 게이트웨이 참조 갱신
  (파급 수정 요구사항의 일부). CI/GitHub Actions는 시크릿·워크플로 변경 불필요
  (신규 설정 전부 기본값 = 현행 동작).

### 테스트 플랜
- 기존 테스트: SimpleNamespace → dict 목킹 전면 전환, `_fake_client` → `_fake_transport`
  (kwargs 기록 콜러블), API 에러 테스트는 `LLMError` raise로.
- **요청 항등 테스트(동작 동일성의 핵심 증거)**: P1 kwargs가
  `{model: "claude-opus-4-8", max_tokens: 4096, thinking: {"type":"adaptive"},
  system: _PASS1_SYSTEM(is), messages: [정확한 document 블록+태스크]}`와, P2가
  `{max_tokens: 1024|8192, output_config: {"format":{"type":"json_schema","schema":...}}}`와,
  챗이 `{max_tokens: 1024, system: _CHAT_SYSTEM}`과 **정확 일치**함을 단언.
- `test_prompt_versions.py` **무수정 통과** = v0 상수 보존 증거.
- 신규: `test_gateway.py`(litellm monkeypatch — 프리픽스·키 부착, kwargs 원형 통과,
  LLMError 정규화, stats in-place 집계+None 가드, LITELLM_LOCAL_MODEL_COST_MAP),
  `test_factory.py`(분기·모델 폴백·키 게이트 None·ValueError·chat_key_configured),
  `test_openai_digest.py`(계약 전체 + 합성 SourceDoc 정렬 단언),
  `test_openai_chat.py`(검증·dedupe·거부 계약 + rag 변형).

## 구현 순서 (단계별 verify)

1. deps+게이트웨이: `litellm==1.91.0` → `uv sync`(--system-certs, --extra embeddings 유지),
   gateway.py, test_gateway.py
   → verify: 해당 pytest + `uv run python -c "import app.llm.gateway"` 즉시 반환(원격 fetch
   없음) + `uv tree`에서 litellm이 anthropic을 안 끌어오는지 + litellm 화이트리스트에
   output_config 포함 확인
2. config+factory(+conftest OPENAI_API_KEY) → verify: test_factory
3. citations.py 전환 → verify: test_citations + test_prompt_versions + test_pipeline
4. openai_citations.py 전환 → verify: test_openai_citations
5. digest.py/chat.py 전환 → verify: test_digest + test_web + test_rag_chat(pgvector 기동)
6. 신규 OpenAI 전략 2종 + factory 배선 → verify: 신규 테스트 2종 + test_factory
7. 호출부 전환 + orphan 정리(anthropic 제거) + docs/learnings 갱신
   → verify: 전체 `uv run pytest && uv run ruff check . && uv run mypy .` + grep
   `import anthropic` 0건
8. compare_providers.py 전환 → verify: `--help` + 아래 라이브 스모크

## Verification (라이브, dev DB — .env는 훅 보호라 인라인 env 사용)

```powershell
# (1) anthropic 스모크 — output_config/thinking/citations passthrough 실검증
#     (화이트리스트 드롭 시 degraded 전멸·citations=0으로 가시화됨)
uv run python -m scripts.compare_providers --date 2026-06-26 --providers anthropic --max-clusters 2
# (2) openai 스모크
uv run python -m scripts.compare_providers --date 2026-06-26 --providers openai --max-clusters 2
# (3) 다이제스트: 기본(anthropic) → $env:DIGEST_PROVIDER="openai" 후 신규 전략
uv run python -m scripts.build_digest_for --date 2026-06-26
# (4) /chat 스모크(날짜+누적 각 1회) → $env:CHAT_PROVIDER="openai" + 재시작 후 재확인
# (5) 선택: 프로브 1009/1256 재실행 — 플랜 10 Run 0 대비 비결정성 범위(±수 점) 내 확인
uv run python -m scripts.compare_providers --date 2026-06-26 --providers anthropic --max-clusters 2 --include-ids 1009,1256 --prompt-version v0
```

## 리스크·완화

- 화이트리스트 밖 top-level 파라미터 **조용한 드롭** → 1.91.0 핀(output_config 포함 확인) +
  스모크 (1)이 드롭을 가시화. litellm 업그레이드 시 스모크 재실행 관례화.
- raw dict 응답 스키마 변경(passthrough 경로) → 정확 핀, 업그레이드는 별도 PR.
- truststore 전역 주입(기존 "스코프 좁게" 관례와 상충) → litellm 버그(#14396)로 강제된
  사항, gateway 주석에 근거 기록. 기존 커넥터는 자체 SSLContext 명시라 동작 불변.
- litellm 로그 키 노출 → telemetry off + suppress_debug_info + 로거 WARNING.
- 플랜 10 간섭 → compare CLI·prompt_versions 불변 + **요청 항등이 증명되면 Run 0
  베이스라인과 비교 가능성 유지**(전송 계층만 교체). 스크리닝 착수 전 본 리팩터를 먼저
  머지할지 여부는 사용자 판단(프로브 (5)로 드리프트 확인 가능).
- 신규 OpenAI 다이제스트/챗 JSON 잘림 → max_output_tokens 8192 + incomplete 경고(기존 교훈).
- 롤백 → 기본 설정=현행 동작, 단계별 커밋 revert로 즉시 복귀(설정 마이그레이션 없음).

## 적대적 감사 반영 (2 에이전트 교차 검증 완료)

- 반영: D1 transport 시그니처 명시(model은 분석기 kwargs에 유지, 프리픽스는 transport
  내부), verify_quotes 3-튜플의 기존 호출부/3번째 원소 의미 명시, 파서 dict 전용+테스트
  목킹 전면 전환 명시, LLMError 래핑 범위(연결·타임아웃 포함) 명시, gateway 초기화의
  이행적 보장 논증, litellm 핀 검증 스텝(uv tree·화이트리스트) 추가, docs/learnings 갱신
  추가, _NO_KEY_MSG 기본값 바이트 동일 실확인.
- 기각(사실 확인 결과): "SimpleNamespace 목킹 깨짐"은 테스트 전면 전환이 원래 플랜 범위,
  "response_format 툴콜 우회"는 output_config-only 규칙으로 이미 차단, CI 시크릿 추가
  불필요(기본값=현행), truststore inject 중복 실행 없음(모듈 캐싱).
