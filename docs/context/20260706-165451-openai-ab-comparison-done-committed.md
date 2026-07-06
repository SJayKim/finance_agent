---
status: completed
branch: main
timestamp: 2026-07-06T16:54:51+09:00
files_modified: []
---

## Working on: OpenAI A/B 비교 완료·커밋 (플랜 08)

### Summary

플랜 08(OpenAI gpt-5.4-mini 영향도 분석 비교)의 본 A/B 비교를 완료하고 결과를 문서에 반영해 커밋했다. `684bdba`(구현+결과, +730줄) / `de9c636`(migrations/env.py 로거 수정) 두 커밋이 main에 있다. 결과 상세는 리포 `docs/plans/08-openai-impact-comparison.md`의 "결과" 절이 단일 소스.

### Decisions Made

- **즉시 프로바이더 교체 보류.** 06-26, 150클러스터 비교에서 quote-and-verify는 검증됨(drop 0.5%, 오프셋 정확, 스팬이 Anthropic보다 세분화). 속도 7.7배(363s vs 2,807s), 비용 $0.24/일. 그러나 impact_score 캘리브레이션이 다름(쌍별 diff 평균 +15.9, confidence HIGH 22 vs 7) — §7 무결성 비대칭(단일 콜이 전체 문서 보고 점수 산출) 때문으로 판단. 그대로 교체하면 랭킹 보드 점수 분포가 통째로 위로 밀림.
- **교체 선행 조건**: 점수 산출을 인용 범위로 제한하는 프롬프트 보강 후 재비교. digester 비교는 그때 함께.
- **한국어 구두점 정규화 불필요 확인**(drop 2건뿐) — 플랜의 "선구현 금지" 판단이 맞았음.
- 커밋은 구현/마이그레이션 수정으로 분리. 실험 산출물(`out_smoke/`, `out_compare/`, `compare_0626.log`)은 커밋하지 않음.

### Remaining Work

1. (선택) OpenAI 프롬프트에 "점수는 인용 범위 근거로만" 제약 추가 후 재비교 — 교체 검토의 선행 조건
2. dev DB 06-26은 현재 **GPT 결과가 남아 있는 상태**(설계대로 마지막 실행 결과). Anthropic 결과로 되돌리려면 `--providers anthropic` 단독 재실행
3. 대시보드 프로덕션 배포(`docs/plans/07-dashboard-production-deploy.md`)는 여전히 미착수 — Basic Auth → 로컬 검증 → Fly 배포
4. `out_smoke/`·`out_compare/`·`compare_0626.log` 정리 또는 .gitignore 추가

### Notes

- 덤프 쌍 검토 소견: 1256(+53)은 OpenAI 인플레이션 명백(헤드라인 스텁에 78/HIGH), 1009(-36)는 반대로 OpenAI가 링크팜 스텁을 정확히 보수 처리 — 일방적 우열 아님. Anthropic은 같은 인용 스팬 3~4회 중복(538 vs 396 격차는 표보다 실질 작음). OpenAI 분석문에 힌디어 토큰 혼입 1건(1009).
- 비교 재실행법: `DATABASE_URL=<localhost dev> uv run python -m scripts.compare_providers --date 2026-06-26 --dump-dir out_compare` (localhost 가드 있음, 리셋 파괴적)
- ruff·mypy·pytest 198개 통과 확인 후 커밋함.
