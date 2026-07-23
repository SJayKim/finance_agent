# 플랜 10: 프롬프트 최적화 라운드 — 모델별 베스트 프랙티스 기반 10+ 버전 비교

## Context

v1~v4 비교(플랜 08·09)에서 GPT-5.4 계열의 +16~18 점수 오프셋이 프롬프트 제약·reasoning effort·모델
업그레이드로 해소되지 않아 "Anthropic(Opus) 유지"로 보류했다. 최종 결정 전 마지막 라운드로,
**모델별 프롬프트 베스트 프랙티스를 자료조사해 최소 10개 프롬프트 버전을 설계·테스트**하고 나서
provider/모델을 확정한다.

확정된 실험 조건:

- **버전 범위**: 하이브리드 — 공통 기법 버전 + 모델별 특화 버전, 총 10개+
- **평가**: 이중 게이트 — 1차 캘리브레이션(Opus 대비 오프셋·confidence 분포 정합),
  2차 품질(프로브 1256/1009, 인용 무결성, 점수 분별력)
- **후보 모델**: gpt-5.4-mini(effort medium), gpt-5.4(effort medium), **claude-sonnet-4-6** —
  셋 다 Opus 교체 후보. Opus는 기준으로 150클러스터 1회 재실행(유실 덤프 복원). 비용 무관.
- **실행**: 2단계 — 전 버전 50클러스터 스크리닝 → 상위 3~4개 150클러스터 파이널
- **데이터셋**: brief_date 2026-06-26 (dev DB), 플랜 08과 동일

사전 확인 사항:

- 프로브 brief_item **1256은 top-50 안(rank 32)**, **1009는 rank 118** → 스크리닝에서 1009 강제
  포함(`--include-ids`) 필요
- Anthropic 모델은 CLI 파라미터 불가였음(`settings.impact_model` 고정) → `--anthropic-model` 추가
- 프롬프트는 코드 내 고정 상수(버저닝 없음) → 버전 레지스트리 신설. **프로덕션 기본 경로는
  바이트 단위 불변이 원칙**(v0 항등 테스트로 증명)
- Anthropic structured output은 integer min/max 미지원 → 0~100 범위는 모든 버전의 프롬프트
  텍스트에 유지(테스트 불변식)

## Research notes (Phase A)

### LLM-judge 캘리브레이션 기법 (문헌 조사, 2026-07-07)

- **판정 오프셋은 모델 고유 성향**으로 문헌이 확인(Evaluative Fingerprints arXiv:2601.05114 —
  점수만으로 judge 모델 식별 77%; alignment 튜닝 자체가 선호 점수 토큰 유발 arXiv:2601.16444).
  프롬프트로 완전 해소 안 되면 사후 선형/isotonic 매핑이 문헌상 확실한 백스톱(arXiv:2605.09227,
  2506.02945) — 플랜 08 결론과 일치.
- **앵커 밴드 루브릭: STRONG** — 루브릭 구체성이 점수 *레벨*을 직접 움직임("Rubric Is All You
  Need" arXiv:2503.23989: leniency −0.233→±0.1; Prometheus arXiv:2310.08491: Pearson 0.392→0.897).
  **이진 분해 체크로 점수를 유도하면 judge 불변성 달성**(Prosa arXiv:2605.01630: 3 judge 가족
  랭킹 일치 7/16→16/16) — "judge 모델보다 판정 분해가 중요".
- **few-shot 캘리브레이션: STRONG** — 기준 스케일을 이식하는 유일한 프롬프트 수단(Hamel Husain:
  3예시+전문가 비평→일치율 >90%; AutoCalibrate arXiv:2309.13308). 4~6개: 밴드당 1개 + 인플레
  존(55-65를 ~45로) 경계 사례 1-2개, 섹터·방향 다양화, 각 예시에 "왜 더 높지 않은가" 비평 첨부.
  리스크: 예시 순서·주제 앵커링 → 구분자·다양화로 완화.
- **분포 prior(히스토그램 제시): 근거 없음/역효과 위험** — 분포 강제(distribution-forcing)로
  아이템 순서 개선 없이 주변분포만 왜곡. 희소성 언어를 밴드 정의 *안에* 녹이는 것만 안전.
  → 원안 V2(분포 prior) 폐기, 분해 체크+상한 규칙으로 재설계.
- **percentile/reference-class 프레이밍: 근거 없음** — 작동하는 percentile은 채점된 참조 코퍼스
  대비 사후 계산(WebNovelBench)이지 프롬프트가 아님. → 원안 V7 폐기, 반(反)관대함 셀프 비평으로
  재설계.
- **justify-then-score: MODERATE** — 자유 서술 선행만으로는 약함; *구조화된 근거 등급*(범위/
  신규성/정량성 판정 + 등급 연동 상한)이 인플레를 실제로 제약(arXiv:2310.05657, 2601.08654).
- **verbalized confidence는 체계적 과신**(arXiv:2502.11028) — HIGH 남발은 훈계가 아니라
  **체크 가능한 조건 정의**로 고침("HIGH = 독립 복수 소스 + 정량 수치 + 직접 노출 명시").

### Anthropic Claude 4.x 프롬프팅 (공식 문서, 2026-07-07)

출처: platform.claude.com/docs — prompt-engineering best practices(통합 페이지), develop-tests,
structured-outputs, migration-guide, multilingual-support.

- **명시적·직접적 지시** + 지시의 동기 설명이 일반화를 도움. 순서·완전성이 중요하면 번호 목록.
- **few-shot은 `<example>`/`<examples>` 태그로 3~5개**, 다양·경계 사례 포함(의도치 않은 패턴
  학습 방지).
- **XML 태그 구조화**(`<instructions>`, `<scoring_rubric>` 등 영문 태그+한국어 본문)가 오해석
  감소. 롱컨텍스트는 문서를 위, 지시를 아래에.
- **adaptive thinking 켠 상태(우리 PASS1)에서는 단계 처방형 CoT보다 일반 지시가 우수** —
  "prefer general instructions over prescriptive steps" + 셀프 체크 지시("확정 전 근거 대조").
- **4.6+ 세대는 지시를 더 문자 그대로 따름** — "반드시/CRITICAL" 류 공격적 언어를 완화할 것.
  포괄적 보수화 지시("확신 없으면 낮게")는 문자 그대로 실행돼 분포를 압축(recall 하락과 동형) —
  보수성은 톤이 아니라 **밴드 정의에 인코딩**할 것.
- **grader 가이드**: 루브릭은 규칙형·결정론적 문장으로("X 없으면 자동 incorrect" 스타일),
  reasoning 먼저 시킨 뒤 버리기, Likert 양 끝점 앵커.
- structured outputs: integer min/max 미지원 재확인 — 공식 SDK 우회가 **범위를 필드
  description에 기입**하는 것(+프롬프트 본문). required 필드는 스키마 순서 유지 → 필드 순서로
  grade-before-score 강제 가능(스키마 변경은 이번 라운드 범위 밖, 기록만).
- Citations API + structured outputs 동시 사용 불가(400) 재확인 — 2-패스 설계 유효.
- 한국어: 영어 대비 ~96.6% 성능(translated-MMLU), 시스템 프롬프트에 대상 언어 명시 권장.
- Sonnet 4.6 특기: `effort` 기본값 **high**(4.5와 다름 — 비용·행동 함의), adaptive thinking 지원.
- **단가 확인**: claude-opus-4-8 $5/$25, claude-sonnet-4-6 $3/$15 (per 1M in/out) —
  compare_providers.py 단가표와 일치.

### OpenAI GPT-5.x 프롬프팅 (공식 가이드, 2026-07-07)

출처: developers.openai.com/api/docs/guides/prompt-guidance (GPT-5~5.5 가이드 통합),
structured-outputs, text(역할 계층), openai.com/index/why-language-models-hallucinate.

- **GPT-5는 지시를 "수술적 정밀도"로 따름** — 모순·모호 지시가 다른 모델보다 더 해로움
  (모순 조정에 reasoning 토큰 소모). 모순 감사 + 명시적 타이브레이크("두 밴드 사이면 낮은
  밴드") 필수.
- **GPT-5.4 강점**: "계약이 명시적일 때 블록 구조 프롬프트의 지시 준수", 금융 워크플로.
  권장 블록: `<instruction_priority>`, `<citation_rules>`("인용문·URL·ID를 지어내지 마라",
  "인용은 그것이 뒷받침하는 주장에 붙여라"), `<grounding_rules>`, `<verification_loop>`.
- **reasoning effort는 "last-mile knob"** — 캘리브레이션을 effort로 고치려 하지 말 것.
  "medium + 잘 설계된 프롬프트"가 권장 조합(우리 설정과 일치).
- **gpt-5.4-mini**: 더 문자적, 가정 안 함 — 핵심 규칙 앞배치, 구조적 스캐폴딩(번호 단계·결정
  규칙), "One correct example"(few-shot) 공식 권장. 작은 모델 프롬프트는 더 길고 명시적이어야.
- **confidence 과신의 공식 완화책 = 페널티 프레이밍**: "t 이상 확신할 때만 답하라, 오답은
  t/(1−t)배 감점"(hallucination 논문). → V7에 "잘못된 HIGH는 잘못된 LOW의 9배 비용" 채택.
- **GPT-5.2 `<high_risk_self_check>`**(금융 명시): 확정 전 근거 없는 수치·과강한 언어 재스캔.
- **structured outputs는 스키마 키 순서대로 출력**(공식) — reasoning 필드가 답 필드보다 앞에
  와야 함(실증 +13pp). 현행 _SCHEMA는 analysis_text·citations가 impact_score보다 앞 —
  이미 justify-then-score 순서 충족.
- `instructions` 파라미터는 developer 역할로 user보다 우선 — 루브릭이 기사 본문에 밀리지 않음
  (현행 설계 유지).
- 분포 prior: judge 점수가 코퍼스 난이도에 표류한다는 외부 근거(arXiv:2510.12462)는 있으나
  공식 근거 아님 — 캘리브레이션 문헌 조사의 "분포 강제 위험" 판정과 종합해 **독립 버전은 미채택**,
  희소성 언어를 밴드 정의에 내장하는 것으로 갈음.
- **단가 확인**: gpt-5.4 $2.50/$15.00, gpt-5.4-mini $0.75/$4.50 (per 1M in/out, Standard) —
  compare_providers.py 단가표와 일치.

### 버전 텍스트 확정

V1~V9 텍스트는 `app/pipeline/prompt_versions.py`에 확정 반영(2026-07-07). 요지:
- 공용 조각: `_BANDS`(앵커 밴드+희소성 언어+타이브레이크), `_DECOMP`(범위/신규성/정량성 판정+
  상한 규칙), `_CONF_RULES`(HIGH/MED/LOW 체크 조건), `_STUB_RULE`(스텁 상한 30/LOW),
  `_COUNTER_LENIENCY`(반문+9배 페널티 프레이밍).
- v0의 모호한 강도 문장("근거가 약하거나 중립이면 낮게…")은 V1+ 버전에서 밴드/규칙으로 **대체**
  (모순 감사 — GPT-5 가이드; 포괄 보수화 지시의 분포 압축 — Claude 4.6+ 문자적 해석).
- OpenAI 전 버전에 인용문 원문 복사 메커니즘 유지(verify_quotes 전제), Anthropic 전 버전에
  "0~100"·무부호 규칙 유지 — 테스트 불변식으로 강제.

## 버전 매트릭스 (Phase B — 조사 반영 개정)

| ID | 기법 | 적용 모델 | 근거 |
|---|---|---|---|
| V0 | 현행 프롬프트 그대로 (control) | 3모델 전부 | — |
| V1 | 0~100 앵커 밴드 루브릭(밴드별 구체 기술+희소성 언어 내장) | 3모델 | STRONG(2503.23989) |
| V2 | V1 + 분해 체크(범위/신규성/정량성) + 등급 연동 상한 규칙 | 3모델 | STRONG(Prosa 2605.01630) |
| V3 | V1 + few-shot 캘리브레이션 4~6예시(Opus 덤프 기반, Run 0 이후) | 3모델 | STRONG(Hamel/AutoCalibrate) |
| V4 | 구조화 근거 등급화 후 점수(justify-then-score, 밴드 없음 — 효과 분리) | 3모델 | MODERATE |
| V5 | confidence 체크 조건 정의 + 스텁/헤드라인 상한 규칙(밴드 없음) | 3모델 | STRONG(과신 문헌) |
| V6 | GPT 특화: instruction-hierarchy/spec 포맷 + V1 내용 | GPT만 | GPT-5 가이드 |
| V7 | GPT 특화: V1 + 반(反)관대함 셀프 비평("한 밴드 낮을 이유 먼저 검토") | GPT만 | 관대함 편향 문헌 |
| V8 | Claude 특화: XML 구조화 PASS1+PASS2 + 루브릭 태그 | Sonnet만 | Claude 문서 |
| V9 | Sonnet 콤보(V2+V5) — V0-sonnet 드리프트 시에만 | Sonnet만 | 조건부 |
| V10 | 스크리닝 승자 조합 combined-best | 파이널만 | — |

스크리닝 배정(개정): mini V0~V7(8런) / gpt-5.4 V0·V6·V7+mini 상위 공통 2(5런) /
sonnet V0·V2·V5·V8(+조건부 V3·V9)(4~6런).

공통 불변식: 0~100 범위 명시, direction 무부호 규칙, (OpenAI) 인용 범위 제약(+인용문 원문 복사
메커니즘 전 버전 유지 — verify_quotes 전제), 무근거 값 금지.

## 하네스 확장 (Phase C)

- `app/pipeline/prompt_versions.py` 신규: `AnthropicPrompts`/`OpenAIPrompts` + 버전 레지스트리.
  v0은 기존 상수를 import 참조(단방향 의존, 순환 없음).
- `app/pipeline/citations.py`: `anthropic_analyzer(..., pass1_system=None, pass2_system=None)` —
  None이면 기존 상수(프로덕션 무변경).
- `app/pipeline/openai_citations.py`: `openai_analyzer(..., system=None)` — 동일.
- `scripts/compare_providers.py`: `--prompt-version`(기본 v0)·`--anthropic-model`·`--include-ids`,
  모델별 단가 테이블(미등록 모델 n/a), Anthropic 토큰/비용 캡처(스크립트 측 클라이언트 래퍼,
  프로덕션 무변경), 런 종료 시 `<dump_dir>/summary.json`(args+메트릭+elapsed) 기록,
  테이블에 model/prompt_version 행 추가.
- `scripts/analyze_prompt_runs.py` 신규(읽기 전용): 기준 덤프 vs 후보 덤프 — 공유 ok-set
  pairwise 오프셋, 점수 stddev, confidence 분포 L1, 프로브 나란히 비교.
- 테스트: v0 항등, 버전 불변식, analyzer override 전달, CLI 경로.

## 실행 프로토콜 (Phase D)

- 덤프 위치: **OneDrive 밖** `C:\fa_runs\p10\<model>-<version>[-screen|-full]`.
  런 직후 summary.json 확인 + 집계치 본 문서 전사 + `Compress-Archive` zip 백업.
- 전 런 순차(공유 dev DB, 런마다 destructive reset). `--date 2026-06-26`,
  GPT 런은 `--reasoning-effort medium`, 스크리닝은 `--max-clusters 50 --include-ids 1009`.
- 순서: 스모크 3종 → Run 0(Opus v0 150) → V3 작성 → 스크리닝 ~18런 → 컷 → 파이널 3-4런(150)
  → DB 최종 상태 지정.

스크리닝 컷 기준(n≈51 노이즈 ±2-3 감안, 복수 신호로만 컷): |오프셋| 최소군 AND confidence L1이
해당 모델 V0 대비 명확 개선 AND 점수 stddev ≥ Opus의 ~70% AND 프로브 미회귀(1256 ≤~40/not-HIGH,
1009 LOW/보수적) AND drop rate ≤1%(GPT).

## 결정 게이트 (Phase E — 파이널 실행 전 선등록)

- 1차(캘리브): 150클러스터 파이널에서 |pairwise 평균 오프셋| ≤ 5 AND confidence 분포 L1 ≤ 0.25
  (정규화 HIGH/MED/LOW)
- 2차(품질): 프로브 1256/1009가 Opus 25/LOW·gpt-5.4-v4 38/LOW 이상 수준, drop ≤1%(0 선호),
  stddev 붕괴 없음, analysis_text 스팟체크(언어 혼입 없음)
- 둘 다 통과 → 교체 권고(속도/비용 가중). sonnet만 통과 → 최저 마찰 교체(`IMPACT_MODEL`만 변경).
  전부 탈락 → Opus 유지 + "프롬프트 수준 캘리브레이션 소진" 확정 기록.

## 결과 (Phase D/E 기록)

### Run 0 — Opus 베이스라인 재실행

2026-07-07 17:20 완료(2,850.1s). 덤프 `C:\fa_runs\p10\opus48-v0-full`(+동명 zip 백업).

| 항목 | 값 |
|---|---|
| ok / empty / degraded | 150 / 240 / 0 |
| citations (per ok) | 525 (3.5) |
| impact mean / median | 35.4 / 35.0 |
| direction 긍정/중립/부정 | 57 / 52 / 41 |
| confidence HIGH/MED/LOW | 10 / 50 / 90 |
| tokens in/out | 457,764 / 151,005 |
| cost | $6.06 |

- 구 문서 집계치 평균 36.4 대비 드리프트 **-1.0**(±3 이내 → 플래그 없음). 이후 오프셋·stddev
  비교 기준은 본 덤프(리스크 2 프로토콜).
- 프로브: 1256 = **25/LOW**(구 베이스라인과 동일), 1009 = **45/LOW**(구 60/MED 대비 보수적 —
  비결정성 범위 내, 스크리닝 판정 기준은 본 런 값 사용).
- dev DB 06-26은 본 런으로 anthropic(v0) 결과로 복원된 상태.

### 스크리닝 (50+1 클러스터)

(진행 중)

### 파이널 (150 클러스터)

(진행 중)

### 결론

(진행 중)

## 리스크

1. n≈51 스크리닝 노이즈 → 복수 신호 컷, 오프셋 단독 판정 금지
2. Opus 재실행이 문서 집계치(36.4)를 정확히 재현 못 함(비결정성) → 신규 덤프를 기준으로 쓰되
   ±3 초과 드리프트면 플래그
3. 분별력 붕괴(전부 25-35로 눌러 오프셋만 "해결") → stddev 가드 필수
4. V3 few-shot 누출(예시가 event_type/direction 편향) → 예시 구분자 명확화 + 방향 다양화
5. 덤프 유실 재발 → OneDrive 밖 + zip + 즉시 문서 전사
