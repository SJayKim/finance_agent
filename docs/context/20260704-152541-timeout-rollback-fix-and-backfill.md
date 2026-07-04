---
status: in-progress
branch: main
timestamp: 2026-07-04T15:25:41+09:00
files_modified:
  - scripts/run_pipeline_for.py
---

## Working on: timeout 전량 롤백 근본 수정 + 7/2~7/4 백필

### Summary

배포 대시보드의 7/3·7/4 데이터 소실(무상한 Opus/OpenFIGI 루프 → GitHub Actions
timeout 강제 취소 → 단일 트랜잭션 전량 롤백)의 근본 원인 수정을
`~/.claude/plans/polymorphic-jumping-firefly.md` 플랜대로 구현 완료(커밋 2개, 테스트
188 통과·ruff·mypy 클린). 라이브 Supabase DB 백필은 7/4 완료, 7/3이 25/150에서
세션 종료로 중단될 예정(재실행이 멱등하게 이어감), 7/2·다이제스트는 미실행.

### Decisions Made

- 분석 상한 150 유지(+Opus), env `IMPACT_ANALYZE_MAX_CLUSTERS` 오버라이드 — 사용자 확정.
- analyze_impact: 우선순위 정렬(클러스터 멤버 수 DESC → 대표문서 published_at DESC
  nulls_last → id), 10건마다 checkpoint 커밋, 골격(dedup/cluster/generate_impact) 선커밋.
  비원자화 안전 근거: advisory lock은 전용 lock_conn, 멱등 not_in 필터가 재실행 중복 방지.
- ticker_link: `cached_openfigi_normalizer(client)` 클로저로 교체 — 단일 클라이언트
  재사용, (ticker,market) 캐시, OpenFIGIRateLimited → 이후 전부 즉시 None(보류),
  OpenFIGIError → 해당 키만 None 캐시.
- naver display 100→30 (runner 주입, 커넥터 기본값 유지).
- digest 패스2 max_tokens 4096→8192, stop_reason=max_tokens 경고, 실패 warning 로그.
- citations.py도 JSONDecodeError 포착(분석 루프 크래시 경로 제거).
- 소스헬스: daily_run 없으면 source_fetch 행 fallback(incomplete=True) + "일일 실행
  미완료" 배너.
- 누적 채팅 비활성 문구 원인 구분: 키 미설정 vs 서버 임베더 미설치(_rag_available =
  find_spec 수준 싼 확인). 누적 라디오 disabled+툴팁, htmx responseError/sendError 표시.
- db.py `pool_pre_ping=True`.
- tests/conftest.py: `ANTHROPIC_API_KEY=""` 강제 — 개발자 .env에 실 키가 있어도
  테스트는 오프라인(run_pipeline이 키 유무로 실 분석기 자동 생성 → 과금 방지).

### Remaining Work

1. **7/3 백필 재개**: `uv run python -m scripts.run_pipeline_for --date 2026-07-03`
   (세션 종료로 25/150쯤에서 죽음. checkpoint 커밋 덕에 진행분 보존 — 같은 명령이
   멱등하게 이어서 분석. 골격 639 클러스터는 이미 커밋됨)
2. **7/2 백필**: `uv run python -m scripts.run_pipeline_for --date 2026-07-02`
   (반드시 7/3 완료 후 — 신선도 필터에 published_at 상한이 없어 과거 날짜 먼저 돌리면
   이후 날짜 문서를 흡수)
3. **다이제스트 3일치**: `uv run python -m scripts.build_digest_for --date 2026-07-04`
   → `--date 2026-07-03` → `--date 2026-07-02` (모두 -m 아님, 이 스크립트도 -m 필요:
   `python -m scripts.build_digest_for`)
4. **검증**: Supabase에서 7/2~7/4 clusters/brief_items/daily_digests 카운트 →
   실서버 `/?date=2026-07-03`, `/?date=2026-07-04` 렌더(브리프·다이제스트·소스헬스 배너).
5. **클라우드 검증**: 푸시 후 CI·deploy-dashboard 성공 확인 →
   `gh workflow run daily.yml` 1회 dispatch(새 INFO 로그 스트림, ~25분 완주 예상) →
   다음 크론(21:40 UTC) 자동 완주 확인.

### Notes

- 스크립트 실행은 **`-m` 필수**: `uv run python -m scripts.run_pipeline_for ...`
  (파일 경로 실행은 `ModuleNotFoundError: app`).
- `git push origin main`이 자동 권한 분류기에 1회 거부됨 → 사용자가 명시 지시("git
  push 진행")해 이 세션 마지막에 push 시도. 실패 시 사용자가 `! git push origin main`.
- 7/4 백필 결과(검증 완료): brief_items ok 150 / empty 106 (degraded 0), citations
  490, ticker links 81(고유 36), impact_score 최고 78("AI 데이터센터 CAPEX").
  7/3 골격: 클러스터 639. 7/2 예상 후보 ~240.
- 로컬 임베더(sentence-transformers) 미설치 → embed 단계 no-op(클라우드 daily와 동일,
  의도된 graceful). RAG 코퍼스는 늘지 않음.
- 배포 경로: main push → CI(pytest+ruff+mypy) → deploy-dashboard(workflow_run,
  main 성공 시)가 Fly `finance-agent-dashboard` 자동 배포.
- empty 106+489는 의도된 트레이드오프(상한) — `run_pipeline_for --date`로 언제든
  이어서 분석 가능.
