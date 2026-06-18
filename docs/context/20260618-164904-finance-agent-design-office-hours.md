---
status: in-progress
branch: main
timestamp: 2026-06-18T16:49:04+0900
files_modified:
  - DESIGN.md
notes_on_env: gstack 셸 도구(bin/*)는 Windows에서 미동작 → 이 체크포인트는 수동 작성. /context-restore가 슬러그를 못 찾으면 이 파일 경로를 직접 지정할 것.
---

## Working on: 증권사 애널리스트 리서치 가속기 설계 (office-hours)

### Summary

빈 레포(finance_agent)에서 `/office-hours` 스타트업 모드로 제품 설계를 끝냈다.
표면적으로는 "뉴스 크롤링→AI 분석→종목 추천" 프로젝트였으나, 진단 결과 실제로는
**중견 증권사(이미 계약 체결, 실사용자 ~150명 애널리스트)를 위한 B2B 리서치
가속 도구**임이 확정됐다. 5개 영역 병렬 웹조사 → 전제 6개 합의 → 아키텍처 3안
중 단계적 트랙 선택 → 설계 문서 작성 → 적대적 리뷰 2라운드(7→9/10) → APPROVED.
산출물은 레포 루트 `DESIGN.md`(Status: APPROVED). 아직 코드는 한 줄도 없음.

### Decisions Made

- **제품 재정의:** "리테일 종목 추천 앱" ❌ → "애널리스트 리서치 가속기(추적
  가능한 영향도 분석)" ✅. 구매자(임원)≠사용자(150명 애널리스트), 채택 결정권은
  애널리스트에게 있음.
- **전제 P1~P6 (전부 동의):**
  - P1 예측·추천 ❌ → 추적 가능한 영향도 분석 + 신뢰도 등급(HIGH/MED/LOW).
    (뉴스→단기 주가 방향 예측은 베이스라인도 못 넘는다는 조사 근거; arXiv
    2606.12210 인용은 착수 전 재확인 필요로 표기됨)
  - P2 추적성이 제품 본체 (결론 얇게, 증거 두껍게; Anthropic Citations API).
  - P3 AI 단독 저자 불가 → 애널리스트 실명 검토 후 발간하는 보조 초안 생성기로
    한정 → 인허가 회피. **단 법적 결론은 자문 변호사 확인 대상으로 강등됨.**
  - P4 "모든 정보" 범위 트랩 → 정의된 합법 소스 + 유니버스(KR/US 주식 + BTC/ETH/
    SOL/RWA).
  - P5 한국 뉴스 본문 직접 크롤링 금지(저작권법 §93, 잡코리아 vs 사람인 4.5억) →
    네이버 검색 오픈API/BIGKINDS 경유. FnGuide·인포맥스·Bloomberg는 고객 좌석 읽기
    연동만 합법.
  - P6 차별화 = 합성·속도·교차커버·추적성·이견 가시화·컴플라이언스(뉴스 수집 ❌).
- **아키텍처: 단계적 트랙 선택.** A(모닝미팅 증거 브리프 MVP, M) → C의 이견
  레이더 슬라이스로 차별화(+2~3주) → 검증 후 B(공급망 KG·평가 이중화·라이선스
  데이터, XL)로 확장.
- **무료·합법 데이터 백본:** OpenDART + SEC EDGAR + 네이버 오픈API + CoinGecko +
  KRX(EOD). 초기 비용 ≈ 0.
- **핵심 기술 함정:** Citations API ↔ Structured Outputs 동시 불가(400) → 2-패스
  분리. 무결성 규칙: 패스2 입력을 패스1 인용 범위로 제한(안 그러면 환각 재유입).

### Remaining Work

1. **(숙제, 코드 아님 / 최우선) Stage 0:** 애널리스트 3~5명 아침 07:00~09:00
   워크플로를 조용히 관찰 → 가장 큰 시간 누수 1~2개 특정 + 놀란 점 1개 기록.
   founder가 현재 워크플로를 모른다는 게 최대 리스크.
2. **Stage 1 상세 설계:** 관찰 결과로 MVP 범위 확정. 합법 소스 4종 커넥터 +
   dedup/클러스터 + 티커 링킹 + Citations 기반 인터랙티브 브리프 대시보드. EOD 확정.
   신선도 컷오프(미국장 마감~07:00), 커버리지 온보딩, 빈/장애 상태 UX, sentence-level
   인용 포함.
3. **Stage 2:** C의 "이견 레이더"만 (한경 컨센서스/인포스탁 합성). 한경 PDF RAG
   저작권 검토 통과가 선결 게이트.
4. **Stage 3:** 공급망 KG(2차 영향), RAGAS faithfulness CI + event study CAR
   백테스트, 고객 좌석/BIGKINDS 라이선스 연동, MCP/API 노출.

### Notes

- **설계 문서:** `finance_agent/DESIGN.md` (Status: APPROVED). 전체 근거·성공지표·
  Open Questions가 여기 있음. 다음 세션은 이 파일부터 읽을 것.
- **미해결 Open Questions (DESIGN.md 참조):** ① 애널리스트 최대 시간누수 구간
  ② 산출물 책임 경계(검토 초안 vs 자사 명의 발간 → BIGKINDS 대외/영리 라이선스 +
  KOFIA 실명확인 필요) ③ 고객 인포맥스/FnGuide 좌석 읽기연동 권리 ④ 한경 PDF 저작권
  ⑤ KR 실시간 시세 필요 여부(Stage 1은 EOD) ⑥ OpenDART 20k/일 제한 대응(캐싱/증분이
  1차) ⑦ 성공지표 합의(faithfulness/인용정확도 + CAR + 채택률) ⑧ 코인 영향분석
  방식 + **CryptoPanic 무료 API 이미 끊김(2026-04) → 대체 확정 필요(CoinGecko+Marketaux)**.
- **법무:** P3(인허가 회피)는 합리적 해석이나 착수/계약 이행 전 자문 변호사 확인 필요.
- **환경:** gstack 스킬들은 Windows PowerShell에서 bin/* 셸 도구가 안 돌아 ceremony는
  생략하고 핵심만 실행해 왔음. /plan-eng-review 등 다운스트림 gstack 스킬도 동일 제약
  가능 → 안 되면 그냥 "Stage 1 상세 설계하자"로 진행.
- **YC:** 사용자가 지원 관심 표명, apply 페이지 안내함(ycombinator.com/apply?ref=gstack).
- 리뷰 점수 최종 9/10, 잔여는 표현 nit뿐(모두 수정 완료).
