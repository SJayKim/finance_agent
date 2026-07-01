# 05 · 대시보드 소스 에러 제거 + 오늘 데이터 완전 수집

## Context (왜 이 작업을 하는가)

대시보드에서 날짜를 클릭할 때마다 소스 헬스에 `naver / edgar_docs / marketaux / finnhub — ... 미설정 error`가 계속 표시됨. "여러 번 고쳤는데 그대로"인 진짜 이유:

- **저 에러는 "지금 키 상태"가 아니라 과거 실행 기록**이다. 대시보드(`app/web/queries.py:327` `load_source_health`)는 `audit_log`의 해당 날짜 `daily_run` payload를 그대로 읽어 보여줄 뿐, 키를 재확인하지 않는다. 06-23 14:11 실행 당시 4개 소스가 "미설정"이었고 그 기록이 박제됨. **키를 .env에 넣고 화면만 새로고침해도 안 바뀐다 — 수집을 새로 실행해야 기록이 갱신된다.**
- **과거 뉴스는 소급 수집 불가**(RSS/네이버/Marketaux/Finnhub는 현재 뉴스만 제공). 빈 과거 날짜를 진짜 데이터로 채우는 건 불가능 + zero-fabrication 위반.
- 키 7개는 `.env`에 다 있고 변수명 매핑도 정상. 단 **실제 유효성은 라이브 호출로 검증해야** 함(키 틀리면 "미설정"이 아니라 401/403).

**승인된 목표(옵션 1):** ① 키 유효성 라이브 검증(안 되는 키는 콕 집어 교체 안내) → ② 오늘 전체 수집 실행으로 모든 소스 ok·실데이터·LLM분석·digest 확보(기본 화면이 이 깨끗한 날짜로 뜸) → ③ 06-22 기존 8건을 신규 수집 없이 분석·점수 채움 → ④ 빈 과거 날짜는 "데이터 없음" 정직 표시. 과거 06-23 에러 기록은 사실이라 그대로 둠.

## 실행 환경 (모든 명령 공통)

dev DB(컨테이너 `finance_agent_db`, 55432) 가동 필요. 모든 runner/스크립트는 인라인 env + `.env`(API 키 자동 로드) 조합:

```
DATABASE_URL="postgresql+psycopg://postgres:fa_local@localhost:55432/finance_agent" \
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
uv run python -m app.runner [--date YYYY-MM-DD]
```

- `.env`(프로젝트 루트)는 pydantic이 자동 로드(`app/config.py:8` `env_file=".env"`) → API 키 적용.
- 커넥터들은 per-client `truststore.SSLContext` 사용(사내 TLS 가로채기 대응, 확인됨). Anthropic 호출은 이 환경에서 이미 동작(06-23에 153건 scored).

## Steps

### Step 1 — 키 유효성 라이브 검증
1. settings가 키를 실제로 로드하는지 확인:
   `... uv run python -c "from app.config import settings; print({k: bool(getattr(settings,k)) for k in ['naver_client_id','naver_client_secret','sec_edgar_user_agent','marketaux_api_key','finnhub_api_key','opendart_api_key','anthropic_api_key']})"`
2. 각 커넥터를 `app/runner.py:73-87 build_default_connectors()`로 만들어 `fetch()` 1회씩 **라이브 호출**, 예외 분류:
   - `"미설정"` → 키 미로드(설정 문제)
   - `401/403` → **키 무효 → 그 키 교체 필요(사용자에게 콕 집어 보고)**
   - `429` → 쿼터 / `Connect|Timeout` → 네트워크·TLS / 정상 → ok
3. 산출: `[소스 / 판정 / 조치]` 표. **무효 키가 있으면 그 키 교체를 요청하고 그 소스는 보류**(나머지는 계속 진행).

### Step 2 — 오늘 전체 수집 실행
- `... uv run python -m app.runner` (기본 오늘 KST)
- `_collect`(6소스) → `run_pipeline`(dedup→cluster→generate→analyze(Anthropic)→ticker_link→embed) → `build_digest` → `daily_run` audit_log 기록.
- 기대: 유효 키 소스 전부 `status=ok`, 오늘 brief_items 생성+scored, digest ok.
- **수집 중 한 소스라도 error면(예: 과거 'rss 403' 재발) 멈추지 말고 근본원인 디버그**(UA 헤더/키 교체/TLS 등). 최소한의 코드·설정 수정 가능.

### Step 3 — 06-22 백필 (기존 데이터만, 신규 수집 X)
- 06-22는 brief 8건이 `impact_score=NULL`, digest 없음. 이미 수집된 데이터를 분석/점수화 → 합법(조작 아님).
- 실행 중 `run_pipeline(date(2026,6,22))`의 analyze/digest 경로가 **기존 8건만 깨끗이 점수화하는지**(신선도 윈도우로 최신 뉴스가 06-22에 섞이지 않는지) 라이브 확인 후 진행. 오염 위험 시 06-22는 정직한 부분상태로 두고 보고.
- 06-22는 `daily_run` 기록이 없어 소스헬스 섹션이 안 뜸(에러 문구 없음) — 옵션 1에서 허용.

### Step 4 — 라이브 대시보드 검증
- 웹 서버 가동(http://localhost:8000).
- `GET /?date=<오늘>`: 소스헬스 전부 ok(렌더 HTML에 `미설정`/`src-error` 0건), 보드 카드·digest·분석 존재. Playwright 스크린샷.
- `GET /` (날짜 미지정): `_default_date` 폴백으로 최신(오늘)에 깨끗하게 안착.
- `GET /?date=2026-06-23`: 과거 에러 기록은 그대로 남음을 확인·명시.

### Step 5 — 보고
키별 판정(동작/교체필요), 오늘 깨끗(스크린샷), 06-22 상태, 정직한 한계(06-23 과거 기록·빈 과거 날짜는 소급 불가).

## 변경 범위
주로 **운영 작업(수집 실행·검증)**, 코드 수정 최소. 단 Step 2/3에서 소스 실패(예: rss 403)나 버그가 드러나면 근본원인 수정 포함.

## 핵심 파일
- `app/runner.py` — `run_daily`/`main`/`build_default_connectors`(실행 진입점)
- `app/config.py:8` — .env 로드
- `app/web/queries.py:327` — `load_source_health`(대시보드가 읽는 것)
- 커넥터 키 체크: `app/collector/{naver,edgar_docs,marketaux,finnhub,opendart_docs,rss}.py`, `app/pipeline/coingecko.py`
- `app/pipeline/pipeline.py` — 파이프라인 단계, 신선도 윈도우(`_freshness_cutoff`)

## 관련 사전조사 (별도 RCA)
같은 세션의 대시보드 미해결 4문제 RCA(P1 주식 0건·P2 빈상태·P3 보드침묵·P4 기본날짜) 중 P4(기본 날짜=빈 보드)는 이미 수정 완료(`_default_date` 폴백, `app/main.py`). 본 문서는 그와 별개인 소스헬스/데이터 수집 과제.

## Verification (완료 기준)
1. 키 검증 표 — 각 소스 ok 또는 (무효 키는 교체 안내).
2. `SELECT payload->>'brief_date', jsonb_array_elements(payload->'sources')->>'name' AS name, jsonb_array_elements(payload->'sources')->>'status' AS status FROM audit_log WHERE action='daily_run' AND payload->>'brief_date'='<오늘>' ORDER BY ts DESC LIMIT 6;` → 모든 소스 `ok`.
3. 렌더된 `/?date=<오늘>` HTML에서 `미설정`/`src-error` 문자열 0건.
4. 오늘 보드 카드 ≥1 + digest 섹션 존재 + Playwright 스크린샷.
