---
status: in-progress
branch: main
timestamp: 2026-06-18T21:23:25+09:00
files_modified:
  - CLAUDE.md
  - docs/STAGE1_DESIGN.md
notes_on_env: gstack bin/* 셸 도구는 Windows에서 미동작 → 이 체크포인트는 수동 작성. gstack 사본은 ~/.gstack/projects/SJayKim-finance_agent/checkpoints/ 에도 있음.
prev_checkpoint: docs/context/20260618-210612-stage1-stack-decisions.md
---

## Working on: Stage 1 두 하드 게이트 해소 (코인 소스 + arXiv 인용 검증)

### Summary

STAGE1_DESIGN.md의 **착수 전 선결 하드 게이트 2건(§11.1, §11.2)**을 웹조사로 해소.
두 게이트가 다 풀려서 이제 "착수 전 블로커"가 없음 → 바로 코드 착수 가능 상태.
검증 결과를 docs/STAGE1_DESIGN.md에 반영. **코드는 여전히 0줄, 전부 워킹트리 미커밋.**

### Decisions Made

- **§11.1 코인 뉴스 소스 → `[DECIDED]` 3-티어 무료 레이어 (외부비용 $0):**
  - 구조화+감성: **Marketaux**(무료 100/일) + **Finnhub**(무료 60/분, 주력)
  - RSS 폭: **CoinTelegraph·CoinDesk·Decrypt** RSS (보조 ChainGPT) — 퍼블리셔
    신디케이션이라 합법이나 **헤드라인+요약+링크만**(P5와 동일 posture, 본문 크롤 금지)
  - 시세·트렌드: **CoinGecko Demo** (백업 CoinPaprika)
  - 사용자 의사: "무료 위주로 다양하게" → 단일 소스(Marketaux) 대신 3-티어 확정.
    다중 소스 redundancy는 §6.2 dedup→§6.3 cluster 입력 전제와 일치.
  - 유료 CryptoPanic 전환은 무료 쿼터가 실측상 부족할 때로 이연.
- **무료 끊긴 소스(배제 확정):** CryptoPanic 무료(2026-04 종료), CryptoCompare/
  CoinDesk Data 무료(2026-05 종료), CoinGecko news 엔드포인트(Analyst $129/월).
  보조도 부적합: Alpha Vantage NEWS_SENTIMENT(25/일·크립토 약함), Messari(Enterprise).
- **§11.2 arXiv 2606.12210 → `[VERIFIED]` (단 수치 프레이밍 정정):**
  - 논문 실재 확인: "Can News Predict the Market? Limits of Zero-Shot Financial
    NLP and the Role of Explainable AI" (Karaoglu & Gowda). 방향성 결론(예측력
    약함, 설명가능성/영향도 해석이 실질 가치) 유효.
  - **`37.5% vs 48.4%`는 틀린 인용이었음.** 둘은 별개 표의 별개 값:
    - 48.4% = 홀드아웃 중립 클래스 비중(Table 7) = **다수결 베이스라인**.
      인용 가능: "No model exceeds the majority-class baseline of 48.4%."
    - 37.5%(0.3750) = RoBERTa **단일 모델** 홀드아웃 정확도(Table 9). LLM 수치 아님.
  - 문서 표기 규칙: 베이스라인 48.4% + "모든 모델 미달"로만 인용. 37.5%는 빼거나
    "RoBERTa 단일 모델 예시"로만.

### Remaining Work

1. **다음 갈림길(미선택, 사용자에게 물어둠) — 이제 둘 다 바로 착수 가능:**
   - (a) 프로젝트 스캐폴딩 — pyproject.toml(uv) + FastAPI 골격 + Alembic + §8 스키마
     마이그레이션 + 디렉토리 구조.
   - (c) OpenDART 1개 수직 슬라이스(수집→정규화→저장)로 파이프라인 패턴 검증.
2. **커밋 여부 결정(사용자):** CLAUDE.md(수정) + docs/STAGE1_DESIGN.md(신규)를 스택
   결정 + 게이트 해소로 묶어 커밋할지. (도메인 규칙상 커밋은 사용자 요청 시에만)
3. **착수 시 실측으로 남긴 것:** Finnhub 크립토 뉴스 실제 코인 커버리지 폭,
   NewsData.io 무료 일일 한도 정확값(이번 조사 미확정).
4. **§11.3 임베딩 모델 실측 벤치 후 확정**(KR dedup precision/recall).
5. **Stage 0(founder 숙제, 코드 아님):** 애널리스트 07:00~09:00 관찰 → STAGE1_DESIGN
   §2 `[STAGE0-BLOCKED]` 칸(브리프 콘텐츠/이벤트 taxonomy/신뢰도 표기/커버리지 입력/
   전달 채널/UX 레이아웃) 채움. 그 전엔 설정/플러그인 경계만.

### Notes

- **이번 세션 STAGE1_DESIGN.md 변경(미커밋):** §3 아키텍처 다이어그램(코인 소스 줄),
  §5.4(CoinGecko=시세·트렌드만 명시), **§5.8 신규**(3-티어 무료 레이어 표),
  §11.1/§11.2 게이트 해소 표기, §13.1 갱신.
- **읽기 순서(다음 세션):** DESIGN.md(전체 근거) → docs/STAGE1_DESIGN.md(기술 스펙,
  §5.8/§11.1/§11.2가 이번 세션 산물) → PAIN_POINT.md(애널리스트 페인 원천).
- **합법 경계 재확인:** KR 뉴스 본문 크롤 금지(P5)→네이버 오픈API(헤드라인+요약). 코인
  RSS도 동일하게 요약까지만. 본문 sentence-level grounding은 공시(OpenDART/EDGAR)뿐.
- **Stage 0에 막힌 칸 하드코딩 금지** — 파이프라인은 설정/플러그인 경계로 받고 빈 채로 둠.
- gstack 슬러그: SJayKim-finance_agent.
