# 플랜: reasoning effort 지정 OpenAI 재비교 (플랜 08 후속)

## Context

플랜 08의 A/B 비교(v1·v2)는 gpt-5.4-mini를 `reasoning` 파라미터 없이 호출했다.
GPT-5 계열의 API 기본 effort는 `none`이라 사실상 reasoning 없이 돌았고, 실측이
이를 뒷받침한다(출력 40.7k토큰/150콜 ≈ 콜당 271토큰 — reasoning 토큰 0, 2.4s/클러스터).

따라서 "+16 점수 오프셋·HIGH 과다" 캘리브레이션 결론이 **모델 성향인지, reasoning을
안 해서인지 구분이 안 된다**. effort를 올려 1회 재비교해서 이 마지막 미검증 변수를
소거한다. 결과가 같으면 "교체 보류" 결론이 확정되고, 달라지면 교체 검토가 재개된다.

## 변경 내용

### 1. `app/pipeline/openai_citations.py` — reasoning effort 파라미터 지원

- `openai_analyzer(client, model, stats=None)` → `reasoning_effort: str | None = None`
  파라미터 추가 (기본 None = 현행 동작 불변).
- `responses.create` 호출에 effort 설정 시에만 `reasoning={"effort": reasoning_effort}` 추가.
- **max_output_tokens**: reasoning 토큰이 `max_output_tokens`를 소모하므로(OpenAI 문서),
  effort 설정 시 8192 → **16384**로 상향. 안 하면 reasoning이 예산을 먹고 JSON이 잘려
  `incomplete`/JSONDecodeError → degraded 폭증 위험(LLM JSON 잘림 견고화 교훈, CLAUDE.md).
- `AnalyzerStats`에 `reasoning_tokens: int = 0` 추가 —
  `usage.output_tokens_details.reasoning_tokens`를 집계(getattr 체인, 없으면 0).
  effort가 실제로 적용됐는지의 직접 증거이자 비용 해석 근거.

### 2. `scripts/compare_providers.py` — `--reasoning-effort` 플래그

- `parser.add_argument("--reasoning-effort", default=None, help="openai reasoning effort (none/low/medium/high)")`
- openai 분기에서 `openai_analyzer(..., reasoning_effort=args.reasoning_effort)` 전달.
- openai 스냅샷에 `reasoning_tokens` 표기 추가(`stats.reasoning_tokens`).
- 비용 계산은 변경 불필요 — reasoning 토큰은 `usage.output_tokens`에 포함돼 이미 반영됨.

### 3. `tests/test_openai_citations.py` — 단위 테스트 2건

기존 fake-client 컨벤션 그대로:
- effort 미지정 → create 호출 kwargs에 `reasoning` 키 없음 + max_output_tokens 8192.
- effort 지정 → `reasoning={"effort": "medium"}` 전달 + max_output_tokens 16384 +
  stats.reasoning_tokens 집계 확인.

## 실행 (구현 후)

1. 게이트: `uv run pytest -q` / `ruff check .` / `mypy .`
2. 스모크: `--providers openai --reasoning-effort medium --max-clusters 2 --dump-dir out_smoke_v3`
   (라이브 표면 검증 — reasoning 파라미터 400 여부, reasoning_tokens > 0 확인)
3. 본 실행 (백그라운드, ~10–20분 예상):
   ```
   DATABASE_URL=postgresql+psycopg://postgres:fa_local@localhost:55432/finance_agent
   uv run python -m scripts.compare_providers --date 2026-06-26 --providers openai \
     --reasoning-effort medium --max-clusters 150 --dump-dir out_compare_v3
   ```
   - Anthropic 재실행 없음(베이스라인 = `out_compare/anthropic` 덤프, v2와 동일 방식).
   - effort는 **medium** 1회(OpenAI 권장 균형점). low/high 추가 실행은 결과 보고 판단.
   - 예상 비용: reasoning 토큰 ~150–300k 추가 시 $0.9–1.6 (v2는 $0.25).
4. 분석: 검증된 쌍별 diff 방법(v2 때 +15.9 재현 확인한 스크립트 인라인 재사용) —
   vs anthropic 평균/중앙값/극값, confidence 분포, 1256·1009 추적, reasoning_tokens/콜.

## 산출물

- `docs/plans/08-openai-impact-comparison.md`에 "재비교 2 — reasoning effort medium" 절 추가:
  v1/v2/v3/anthropic 4열 표 + 소견 + 결론(오프셋 해소 여부 → 교체 검토 재개/확정 보류).
- 커밋 1개: 코드 + 테스트 + 문서, `[skip ci]` 아님(코드 변경이나 실험 전용 모듈이라 무해 —
  단 CI→deploy가 돌게 되므로 Fly 이미지가 main 최신으로 따라잡는 부수 효과, 문제 없음).
- dev DB 06-26은 v3 GPT 결과가 남음(기존과 동일한 상태 — 필요 시 `--providers anthropic` 복원).

## 검증 기준

- 스모크에서 `reasoning_tokens > 0` (effort 적용 증거) + degraded 0.
- 본 실행 ok/empty = 150/240 유지(v1·v2와 동일 분모), degraded 0, drop율 ~1% 이내.
- 쌍별 diff 표본 150쌍 전부 매칭(brief_item_id 기준).
