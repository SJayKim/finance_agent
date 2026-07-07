# 08 — OpenAI(gpt-5.4-mini) 영향도 분석 비교 경로

## Context

데일리 파이프라인의 LLM(claude-opus-4-8 단일)을 GPT로 테스트해 보기 위한 A/B 비교 경로.
사전 조사로 확인된 제약: **OpenAI에는 Anthropic Citations API 상응 기능이 없다**(인용
원문·원문 오프셋 미제공, file_search는 vector store 필수 + file_id만 반환). 따라서 OpenAI
경로는 **quote-and-verify**(모델이 인용문을 JSON으로 출력 → 코드가 원문 substring 검증 +
오프셋 계산)로 인용을 재구현한다.

결정사항:

- 모델: **gpt-5.4-mini** ($0.75/$4.5 per 1M tokens)
- 구현: **openai SDK 직결** (litellm 없음)
- 실행: **로컬 dev DB에서 수동 비교** — 운영 크론(daily.yml)·Anthropic 경로는 불변

## 설계 결정

- **단일 콜(2-패스 아님)**: Anthropic의 2-패스는 Citations API + Structured Outputs 동시
  사용 불가(400) 때문. OpenAI는 인용(quote)과 구조화 필드가 전부 JSON이라 한 콜로 충분.
  **무결성 규칙(§7) 비대칭**: Anthropic 경로의 direction/confidence/impact_score는 패스 1이
  실제 인용한 범위만 보고 산출되지만, OpenAI 경로는 전체 문서를 본 같은 콜이 산출한다 —
  구조화 필드의 근거 제한이 더 약하다. 비교 해석 시 유의.
- **프로바이더 스위치 없음**: `pipeline.py`/`runner.py`의 analyzer 게이트는 그대로. 기존
  주입 시임(`analyze_impact(session, date, analyzer, ...)`)에 비교 스크립트가 명시 주입.
  설정 추가는 `openai_api_key` 한 줄뿐(모델명은 스크립트 플래그).
- **analyzer만, digester는 보류**: 인용 수율·비용 메트릭은 전부 analyzer 산출물. digest는
  하루 1콜 다운스트림 — 비교가 유망하면 기계적 후속 작업.
- **비교는 `analyze_impact` 직접 호출**: `run_pipeline`은 dedup/cluster 재실행 + advisory
  lock이라 불필요. status=empty만 분석하는 특성 때문에 각 프로바이더 실행 전 해당 날짜
  아이템 리셋(citations 삭제 + 분석 컬럼 NULL + status='empty').

## 구성 파일

- `app/pipeline/openai_citations.py` — 핵심 모듈: `build_openai_client`(truststore TLS),
  `_docs_prompt`(`[문서 i]` 번호 블록, 본문은 정확히 `_document_text`),
  `verify_quotes`(순수: 정확 일치 → 오프셋, 공백 정규화 폴백 → 오프셋 None, 실패 → drop),
  `openai_analyzer`(Responses API 단일 콜 + strict json_schema, 계약은 anthropic_analyzer와
  동일), `AnalyzerStats`(수율·토큰 집계).
- `tests/test_openai_citations.py` — 네트워크 없는 단위 테스트(test_citations.py 컨벤션).
- `scripts/compare_providers.py` — A/B 비교 스크립트.
- `pyproject.toml`(`openai` 의존성) / `app/config.py`(`openai_api_key`).

## 실행

```
uv run python -m scripts.compare_providers --date YYYY-MM-DD
  [--max-clusters 150] [--model gpt-5.4-mini] [--providers anthropic,openai] [--dump-dir DIR]
```

1. 안전 가드: `DATABASE_URL`에 localhost 없으면 거부(`--force`로 해제) — 리셋이 파괴적
2. 프리플라이트: 해당 날짜 brief_items 0이면 `scripts/run_pipeline_for` 안내 후 종료; 키 확인
3. 프로바이더별(기본 anthropic → openai 순, 대시보드 최종 상태가 GPT 결과):
   리셋 → analyzer 빌드 → `analyze_impact(..., checkpoint=session.commit)` → 메트릭 스냅샷
   (ok/empty/degraded, 총 인용, ok당 평균 인용, impact_score 평균/중앙값, direction·confidence
   분포, 소요 시간; openai는 drop율 + 토큰→비용)
4. `--dump-dir`: 아이템별 JSON 덤프(`<dir>/<provider>/<brief_item_id>.json`) + 요약 표

## 결과 (2026-07-06, brief_date=2026-06-26, 150클러스터)

| 지표 | anthropic (opus-4-8) | openai (gpt-5.4-mini) |
|---|---|---|
| ok / empty / degraded | 150 / 240 / 0 | 150 / 240 / 0 |
| 인용 총수 / ok당 | 538 / 3.59 | 396 / 2.64 |
| impact 평균 / 중앙값 | 36.4 / 35 | 52.3 / 55 |
| confidence | HIGH 7 · MED 65 · LOW 78 | HIGH 22 · MED 123 · LOW 5 |
| direction | 긍정 61 · 중립 51 · 부정 38 | 긍정 77 · 중립 41 · 부정 32 |
| 소요 | 2,807s (~18.7s/클러스터) | 363s (~2.4s/클러스터) |
| quote drop율 | — | 0.5% (2건) |
| 비용 | — | $0.24 (79.9k in / 40.7k out) |

덤프 쌍 검토(점수 격차 최대 +53 / 역전 -36 / 동률 3쌍) 소견:

- **quote-and-verify 검증됨**: drop 0.5%, 오프셋 정확, 인용 스팬이 Anthropic 블록 인용보다
  세분화(제목/리드/본문 분리). 한국어 구두점 정규화는 불필요 확인.
- **점수 인플레이션 실재**: 쌍별 diff 평균 +15.9. 예: 1256(은행 ESG 대출 헤드라인 스텁)을
  78/HIGH로 — Anthropic은 25/LOW + 정량 정보 부재 명시. §7 비대칭(단일 콜이 전체 문서 보고
  산출) 예측과 일치. 프로바이더 전환 시 랭킹 보드 점수 분포가 통째로 위로 밀림.
- **다만 일방적 우열 아님**: 1009(링크 모음 스텁)는 OpenAI가 "본문 없는 링크 제목"임을
  인식해 중립/LOW/24로 정확히 보수적 — Anthropic은 헤드라인을 실신호로 보고 60/MED.
- **Anthropic 인용 중복 존재**(같은 스팬 3~4회, 1009·1245·1256에서 관찰) — 인용 수 538은
  중복 포함이라 실질 격차는 표보다 작다. OpenAI 쪽은 중복 없음.
- **품질 흠**: OpenAI 분석문에 타언어 토큰 혼입 1건 관찰(1009, 힌디어 단어). 분석문이
  Anthropic 대비 짧고 평면적(섹터별 구조화 없음).

**결론**: 인용 파이프라인은 이식 가능. 속도 7.7배·비용 $0.24/일 이점은 뚜렷하나,
impact_score·confidence 캘리브레이션이 달라 그대로 교체하면 랭킹 의미가 바뀐다.
교체를 진행하려면 점수 산출을 인용 범위로 제한하는 프롬프트 보강(§7 비대칭 완화) 후
재비교가 선행 조건. digester 비교는 그때 함께.

## 재비교 — 점수 인용 범위 제약 프롬프트 (2026-07-07, 동일 06-26·150클러스터)

변경: `_SYSTEM`에 "direction·confidence·impact_score는 citations에 담은 인용문만 근거로
산출하라" 제약 추가(§7 비대칭의 프롬프트 수준 완화 — Anthropic 패스 2의 정보 제한 미러링).
Anthropic은 재실행하지 않음(프롬프트 불변 — `out_compare/anthropic` 덤프가 그대로 베이스라인,
재실행은 비용+비결정성 노이즈만 추가). OpenAI만 단독 재실행, 덤프는 `out_compare_v2/`.

| 지표 | openai v1 (구 프롬프트) | openai v2 (보강) | anthropic |
|---|---|---|---|
| ok / empty / degraded | 150 / 240 / 0 | 150 / 240 / 0 | 150 / 240 / 0 |
| 인용 총수 / ok당 | 396 / 2.64 | 399 / 2.66 | 538 / 3.59 |
| impact 평균 / 중앙값 | 52.3 / 55 | 52.8 / 54.5 | 36.4 / 35 |
| confidence | HIGH 22 · MED 123 · LOW 5 | HIGH 27 · MED 117 · LOW 6 | HIGH 7 · MED 65 · LOW 78 |
| 쌍별 diff vs anthropic | +15.9 / +17 (극값 +53/-36) | +16.4 / +17 (극값 +48/-24) | — |
| 소요 / drop율 / 비용 | 363s / 0.5% / $0.24 | 376s / 0.7% / $0.25 | 2,807s / — / — |

소견:

- **분포 수준 캘리브레이션 격차는 해소 안 됨**: 쌍별 diff 평균 +16.4(v1 +15.9와 동일 수준),
  HIGH 과다·LOW 기피도 그대로. 프롬프트 제약이 점수 스케일 자체를 내리지 못했다.
- **극값(꼬리)은 압축**: +53/-36 → +48/-24. 지목됐던 최악 케이스 1256(은행 ESG 대출
  헤드라인 스텁)은 78/HIGH → 46/MED로 개선(정량 정보 부재도 분석문에 명시). 반면
  1009(링크팜 스텁)는 24/LOW → 42/MED로 v1의 정확한 보수 처리가 후퇴.
- **아이템 수준 변동 큼, 순변화 0**: v2−v1 쌍별 diff 평균 +0.5인데 |diff|>5 이동이
  82/150 — 개별 점수는 런 간 비결정성이 크고, +16 오프셋만 체계적으로 남는다.

**재비교 결론**: 프롬프트 수준 제약으로는 선행 조건(캘리브레이션 정합) 미충족.
gpt-5.4-mini의 점수 스케일이 구조적으로 높다. 교체를 진행하려면 (a) 점수 사후
리캘리브레이션(예: 분포 정합 선형 재조정) 또는 (b) 랭킹 보드 임계값 재베이스라인이
필요하다 — 둘 다 별도 작업이므로 **현행 Anthropic 유지**. digester 비교도 보류.
프롬프트 제약 자체는 꼬리 케이스를 개선하므로 코드에 유지한다.

## 재비교 2 — reasoning effort medium (2026-07-07, 동일 06-26·150클러스터)

v1·v2는 `reasoning` 파라미터 없이 호출 — GPT-5 계열 API 기본 effort가 `none`이라 사실상
reasoning 없이 돌았다(실측: 출력 271토큰/콜, reasoning 0). "+16 오프셋이 모델 성향인지
reasoning 부재 탓인지" 구분을 위해 `--reasoning-effort medium`으로 1회 재실행
(`openai_analyzer`에 effort 파라미터 추가, effort 시 max_output_tokens 8192→16384).
덤프는 `out_compare_v3/`. Anthropic 재실행 없음(베이스라인 불변).

| 지표 | openai v1 | openai v2 | openai v3 (effort medium) | anthropic |
|---|---|---|---|---|
| ok / empty / degraded | 150 / 240 / 0 | 150 / 240 / 0 | 150 / 240 / 0 | 150 / 240 / 0 |
| 인용 총수 / ok당 | 396 / 2.64 | 399 / 2.66 | 393 / 2.62 | 538 / 3.59 |
| impact 평균 / 중앙값 | 52.3 / 55 | 52.8 / 54.5 | 54.4 / 58 | 36.4 / 35 |
| confidence | HIGH 22 · MED 123 · LOW 5 | HIGH 27 · MED 117 · LOW 6 | HIGH 34 · MED 111 · LOW 5 | HIGH 7 · MED 65 · LOW 78 |
| 쌍별 diff 평균 vs anthropic | +15.9 | +16.4 | +18.0¹ | — |
| reasoning 토큰/콜 | 0 | 0 | ~796 (총 119.4k) | — |
| 소요 / drop율 / 비용 | 363s / 0.5% / $0.24 | 376s / 0.7% / $0.25 | 1,150s / 1.0% / $0.77 | 2,807s / — / — |

¹ v3 실행 직전 `out_compare/`·`out_compare_v2/` 덤프가 로컬에서 유실돼(휴지통·전체 검색에도
없음 — 원인 불명, OneDrive 동기화 추정) 아이템 수준 쌍별 diff(중앙값·극값)는 산출 불가.
단 세 실행 모두 ok가 동일한 "분석된 150클러스터" 전체이므로(150/240/0, v1·v2에서 150쌍
전부 매칭 확인) 쌍별 diff **평균**은 평균 차이와 일치한다: 54.4 − 36.4 = +18.0.
추적 아이템의 anthropic 값은 본 문서 기록치 사용.

소견:

- **effort는 실제 적용됨**: reasoning ~796토큰/콜(v1·v2는 0), 소요 3.1배, 비용 3.2배.
  스모크에서 reasoning 파라미터 400 없음·degraded 0 확인 후 본 실행.
- **캘리브레이션 격차는 해소 안 됨 — 오히려 소폭 확대**: 평균 오프셋 +18.0(v2 +16.4),
  HIGH 34로 과다 심화(v2 27, anthropic 7), LOW 기피 그대로(5 vs 78). reasoning을 시켜도
  점수 스케일은 내려오지 않는다.
- **추적 케이스는 개선**: 1256(은행 ESG 헤드라인 스텁) 78/HIGH(v1) → 46/MED(v2) →
  38/MED(v3, anthropic 25/LOW에 근접). 1009(링크팜 스텁)는 22/MED로 v1의 정확한 보수
  처리(24/LOW)를 회복(v2에서 42/MED로 후퇴했던 것). 꼬리 케이스 판단력은 reasoning으로
  좋아지나, 분포 전체의 상향 편향은 그대로.

**결론**: "+16 오프셋·HIGH 과다"는 reasoning 부재 탓이 아니라 **gpt-5.4-mini의 모델
성향으로 확정**. 마지막 미검증 변수가 소거됐으므로 플랜 08·재비교 1의 "교체 보류" 결론
확정 — 교체하려면 사후 리캘리브레이션 또는 랭킹 임계값 재베이스라인이 선행돼야 하며,
프롬프트·effort 조정으로는 달성 불가. effort medium은 비용 3.2배·속도 이점 축소
(2.4s→7.7s/클러스터, 그래도 Anthropic 18.7s의 2.4배)로 매력도도 하락.

## 리스크

- OpenAI 인용 수는 검증 통과분만 남는 **하한값** — drop율을 수율과 함께 보고해야 오독 방지
- 단일 콜 설계의 무결성 규칙 비대칭 — 모듈 docstring에 명기
- gpt-5.4-mini structured-output 표면은 스모크(`--providers openai --max-clusters 2`)에서
  라이브 검증 후 본 실행. 한국어 구두점 정규화는 drop율 관찰 후 필요 시 추가(선구현 금지)
