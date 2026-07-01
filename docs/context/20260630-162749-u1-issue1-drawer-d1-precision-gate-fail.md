---
status: in-progress
branch: feat/impact-ranking-board
timestamp: 2026-06-30T16:27:49+09:00
files_modified: []
---

## Working on: U1 + 이슈1 인라인 드로어 완료 · D1 정밀도 게이트 실패로 재링크 보류

### Summary

docs/plans/06 UX 잔여 두 건(U1 자산 탭 카운트·빈 상태, 이슈1 근거 클릭 페이지 점프)을
구현·라이브 검증·커밋·푸시 완료. D1(KR 별칭 적재 + 재링크)은 **별칭 3,972건 적재까지만** 하고,
재링크는 정밀도 dry-run에서 **≈50%(게이트 ≥95% 대폭 미달)**로 측정돼 **의도적으로 적재 보류**.
브랜치는 origin과 동기화됨(ahead 0). 서버 종료 완료.

### Decisions Made

- **U1·이슈1 둘 다 라이브 검증 후 커밋.** 빈 상태 토글·인라인 드로어는 클라이언트 JS라
  Playwright로 실측(스크롤 불변·드로어 위치·복제 콘텐츠·토글/Esc/탭전환 정리 전부 통과).
- **이슈1 = 인라인 드로어(사용자 선택 B).** 근거 클릭 시 `scrollIntoView` 점프 제거 →
  클릭한 보드 카드 행 바로 아래 `grid-column: 1/-1` 풀폭 드로어로 브리프 본문 복제 표시.
  다이제스트 `근거 #N` 링크도 같은 메커니즘(앵커 점프 preventDefault). 백엔드 0, DOM 클론.
- **D1 재링크 보류(핵심 결정).** `opendart.sync`로 KR 별칭 3,972건 적재(US 10,400·CRYPTO 8).
  하지만 `ticker_link.resolve`는 부분문자열 매칭이라, ≤3자 별칭(765건: 1자×1·2자×284·3자×480)이
  대표제목에 substring으로 걸려 오탐 폭증. 06-26 390건 dry-run: KR 매치 211건 중 105건(≤3자)이
  오탐(`'이닉스'`가 "하이**닉스**"에, `'sk'`가 엉뚱한 SK지주(003600)를 SK하이닉스 기사에). 167/211은
  is_candidate=False로 단정까지 됨 → 오귀속이 추적성 신뢰를 깸(프로젝트 핵심 규칙 위반)이라 적재 안 함.
- **별칭은 유지(롤백 안 함).** 사용자가 "KR 별칭 적재"를 명시 요청했고, 참조 테이블 자체는 무해·가역.
  단 다음 run_pipeline/run_daily가 돌면 이 부정확 링크를 자동 적재하는 점은 미해결로 남김.
- **푸시는 사용자 지시로 실행.** 직전 체크포인트의 보류 사유(mk.co.kr Chrome UA 클라우드 미검증)는
  여전히 미검증이나, 사용자가 푸시를 선택해 코드만 origin에 올림.

### Remaining Work

1. **(결정 대기) D1 정밀도 게이트(§6.4) 구현 후 재링크, 또는 별칭 롤백.**
   - A: 별칭 유지 + 정밀도 게이트 구현(단어경계/한글 형태소·길이 필터 + SK·신한 패밀리 중의성 해소)
     후 06-26 재링크. ← 권장. `'이닉스'∈'하이닉스'` 같은 substring 문제는 길이만으론 해결 안 됨(설계 필요).
   - B: `DELETE FROM security_aliases WHERE market='KR'`로 KR=0 복귀(정밀도 작업 전까지 자동 오적재 차단).
2. **(주의) 별칭 적재로 "무장된" 상태:** 다음 파이프라인 실행이 06-26(또는 타 날짜)을 돌면
   부정확 KR 링크가 자동 적재됨. 정밀도 게이트 전엔 KR 대상 파이프라인 재실행 주의.
3. **(이월) 머지 푸시 보류 사유 미해결:** mk.co.kr Chrome UA 클라우드(origin/Actions) 미검증.
4. **(미착수) docs/plans/06 잔여 UX 항목**이 더 있으면 그것.

### Notes

- **이번 세션 커밋(전부 origin 푸시 완료, feat/impact-ranking-board):**
  - `58a29e5` feat(web): 자산 탭 카운트 + 빈 상태(U1) — 6파일 +52/-3
  - `f9fe5f2` fix(web): 근거 클릭 페이지 점프 제거, 제자리 인라인 드로어(이슈1) — 2파일 +75/-10
  - `0d74eae` style(web): 미사용 .brief-flash CSS 제거(이슈1 인라인 드로어로 대체) — -22
- **인라인 드로어 구현 위치:** `index.html` 첫 `<script>`(toggleDrawer + 보드/다이제스트 리스너 + Esc),
  둘째 `<script>` 탭 핸들러에 드로어 정리 1줄. `app.css` `.board-cards > .evidence-drawer{grid-column:1/-1}`
  + `.evidence-drawer`/`.ed-head`/`.ed-close`. 드로어는 `#brief-N .brief-body` innerHTML 복제(IDs 없음, 안전).
- **검증:** pytest 159 passed · ruff clean · mypy clean(67 files). 드로어/빈상태 Playwright 실측.
- **dev DB 상태(:55432 finance_agent):** security_aliases US 10,400·KR 3,972·CRYPTO 8.
  brief_items 최신일=2026-06-26(390건, 전부 미링크). brief_item_tickers CRYPTO 19·US 10(구날짜분).
  openfigi_api_key 미설정(무료 25 req/min) → 라이브 재링크 시 느림/레이트리밋.
- **gotcha 재확인:** ad-hoc python `print`의 em dash `—` → cp949 UnicodeEncodeError. 스크립트 진입부
  `sys.stdout.reconfigure(encoding="utf-8")` 필수(기존 windows-cp949-stdout-print 그대로). 앱 HTTP·템플릿은 무해.
- **서버 종료:** uvicorn(:8000, PID 39016) PowerShell Stop-Process로 종료(pkill 무효 gotcha).
- **미러:** gstack 체크포인트 ~/.gstack/projects/SJayKim-finance_agent/checkpoints/20260630-162749-u1-issue1-drawer-d1-precision-gate-fail.md
