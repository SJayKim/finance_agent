---
status: completed
branch: main
timestamp: 2026-07-02T15:04:53+0900
files_modified: []
---

## Working on: /qa 드로어 무이동 검증 + Medium 2건 수정(마크다운 렌더·인용 중복) → push

### Summary

로컬 서버(:8000, dev DB 06-26 데이터 390건)에서 병합된 대시보드를 /qa로 검증. 사용자
요청 핵심 시나리오(근거 브리프 클릭 시 무이동 인라인 표시)는 6개 변형 전부 PASS.
발견 4건 중 Medium 2건 수정·검증(커밋 4개) + CLAUDE.md 라우팅 1커밋, 총 5커밋을
이 체크포인트 커밋과 함께 origin/main에 push. Health 97→99.

### Decisions Made

- **무이동 측정 방법론**: `scrollIntoView({block:'center'})` + **JS `.click()`**(드라이버
  클릭 아님)로 Playwright 자동 스크롤을 배제하고 scrollY·rowTop 픽셀 비교. 보드 카드/
  전환/닫기/모바일/다이제스트 칩/타 날짜 6개 변형 전부 불변 확인.
- **Standard 티어** → Medium 2건 수정(사용자 D1 확인: "둘 다 수정"), Low 2건 deferred.
- **ISSUE-002(인용 중복)** = 렌더단 dedupe 선택: `load_brief`에 (brief_item, raw_document,
  cited_text) seen-set — `search_citation_spans` 기존 패턴 미러. DB의 중복 646/1558행(41%)
  포함 전 날짜 즉시 해결. 적재단(analyze) 병합은 후속 별건.
- **ISSUE-001(마크다운 원문 노출)** = escape→markdown 변환 Jinja `md` 필터(app/web/render.py,
  의존성 `markdown` 추가). escape 선행이라 LLM발 원시 HTML은 엔티티로 잔존(XSS 안전, 테스트
  고정). **nl2br** 채택 — LLM이 문단에 붙여 쓰는 리스트를 python-markdown이 인식 못 해
  기본 변환 시 한 문단으로 뭉개짐(실측) → 단일 개행 <br>로 이전 pre-wrap 가독성 유지.
- **CLAUDE.md에 gstack Skill routing 섹션 추가**(88b06e0, 사용자 D2 확인).

### Remaining Work

1. **(이월) 클라우드 API 키 GitHub Secrets 등록** — naver·opendart_docs·edgar_docs·
   marketaux·finnhub 전부 미설정 error(attempted=0). 로컬 .env 값 대조 → `gh secret set`
   → workflow_dispatch 1회 검증.
2. **(이월) prod(Supabase) 과거 티커 재링크 백필** — dev만 새 게이트 반영됨.
3. **(이월) Fly 재배포** — 티커링크·탭카운트·드로어 + 이번 QA 수정 2건 반영.
   `/static/app.css` 캐시버스팅 없음 → 배포 후 브라우저가 낡은 CSS를 수일 물 수 있음(실측).
4. **(신규) 인용 중복 적재단 병합** — 렌더는 막았지만 DB 중복 적재는 계속됨(analyze
   파이프라인). 클라우드 Supabase 데이터도 동일 중복 추정.
5. **(신규·Low deferred)** 보드 카드 aria-expanded 부재, `_impact_board.html:32` 범례
   "아래 근거 브리프로 이동" 낡은 카피, cited_text 잔여물("사진=").
6. **(선택) D2**(분석문·인용 매칭 리콜↑), **U2**(코드 대신 회사명 표시).

### Notes

- **게이트**: pytest **169 passed**(기존 165 + 신규 회귀 4: dedupe 1·markdown 3) · ruff ·
  mypy(69 files) clean. 리버트 0. WTF ~5%.
- **커밋**: `88b06e0`(routing) `b287476`(fix 002) `6f11b3c`(test 002) `1c912ee`(fix 001)
  `2670a66`(test 001) + 이 체크포인트 docs 커밋.
- **리포트**: `.gstack/qa-reports/qa-report-localhost-8000-2026-07-02.md` (스크린샷 10장,
  baseline.json healthScore 97 → 최종 99).
- **QA 방법론 함정**은 auto memory `gstack-browse-qa-windows`에 저장: $B 한글 인라인 인자
  깨짐→UTF-8 파일+eval, async 미대기→동기 스텝, 드라이버 자동스크롤이 무이동 측정 오염,
  정적 CSS 재검증은 캐시버스터.
- **dev DB 데이터 분포**: 06-22(8)·06-23(153)·06-26(390)만 존재 — 날짜 칩 no-data 플래그와
  정확히 일치(칩=DB 교차검증 완료). 기본 날짜 = 06-26(데이터 있는 최신).
- **DOM 구조**(다음 QA용): 보드 행 = `div.board-card[role=button]`, 드로어 =
  `div.evidence-drawer`(brief-body 복제), 브리프 = `details#brief-N`, 다이제스트 칩 =
  `a[href^="#brief-"]`(JS 인터셉트→드로어).
- **미러**: 레포 `docs/context/20260702-150453-qa-drawer-nojump-verified-md-render-citation-dedupe.md`,
  gstack 원본 = `~/.gstack/projects/SJayKim-finance_agent/checkpoints/` 동일 파일명.
