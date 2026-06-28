# CLAUDE.md

## Behavioral Guidelines (Karpathy)

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

### 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

### 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

### 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

## Commands
<!-- 스택: Python 3.13+ + FastAPI (uv). 근거: docs/STAGE1_DESIGN.md §4. watch 모드 금지 -->
- Install: `uv sync`
- Run: `uv run uvicorn app.main:app`   (--reload 등 watch 모드 금지)
- Test: `uv run pytest`
- Lint: `uv run ruff check .`   (포맷: `uv run ruff format .`)
- Typecheck: `uv run mypy .`

## Project-Specific Gotchas
<!-- 자동 reflection으로 누적됨. 초기에는 비워두기 -->
- configparser가 읽는 설정 파일(`alembic.ini`, `*.ini`, `*.cfg`)에는 비-ASCII(한글 주석 등) 금지. Windows 로케일 코덱(cp949)으로 읽혀 `UnicodeDecodeError`로 alembic이 로드 실패한다. 비-ASCII 주석은 UTF-8로 읽히는 `.py`에만 둘 것. (2026-06-19, alembic.ini)
- 런타임 Python HTTP 클라이언트(httpx/requests)로 외부 HTTPS 요청 시 `truststore`로 OS 인증서 저장소를 신뢰시킬 것(사내 TLS 가로채기 → `CERTIFICATE_VERIFY_FAILED`). 스코프 좁게: `ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)` → `httpx.Client(verify=ctx)`. (2026-06-19, app/collector/rss.py fetch)
- SQLAlchemy `INSERT ... ON CONFLICT DO NOTHING`의 `result.rowcount`는 dialect가 multi-rowcount를 지원해도 **-1(신뢰 불가)**을 반환한다(실측: 3971건 적재에도 -1). 신규 적재 수가 필요하면 `.returning(<PK 컬럼>)` 붙이고 `len(session.execute(stmt).fetchall())`로 셀 것. (2026-06-22, app/pipeline/opendart.py sync)
- API 키를 쿼리스트링으로 받는 외부 API(OpenDART `crtfc_key` 등)는 httpx INFO 로깅이 URL을 통째로 찍어 키를 노출한다. 러너에서 `logging.getLogger("httpx").setLevel(logging.WARNING)`로 억제할 것. (2026-06-22, app/pipeline/opendart.py main)
- `pg_try_advisory_lock`은 연결(세션) 단위 락이라, 작업 세션에서 잡고 `session.commit()` 뒤 `finally`에서 풀면 커밋이 그 연결을 풀에 반납해 언락이 **다른 풀 연결**에서 돌아 락이 안 풀린 채 남는다(누수 → 후속 실행이 `PipelineAlreadyRunning`/`DailyRunAlreadyRunning`). 락은 **전용 연결**(`with engine.connect() as lock_conn:`)에 고정해 같은 연결에서 잡고/풀고, 작업은 별도 세션에서 한다. (2026-06-22, app/pipeline/pipeline.py run_pipeline · app/runner.py run_daily)
- Windows CLI 진입점에서 비-ASCII(한글·em dash 등)를 `print`하면 cp949 stdout이 `UnicodeEncodeError`로 죽는다(실측: 소스 에러 메시지의 `—` → run_daily 데이터는 다 커밋됐는데 CLI가 exit 1). `main()` 진입부에서 `sys.stdout.reconfigure(encoding="utf-8")` 호출할 것. (2026-06-23, app/runner.py main)
- `brief_date`는 KST 기준일(run_daily가 `datetime.now(_KST).date()`로 산출)이다. 날짜 경계·신선도 컷오프를 UTC 자정으로 잡으면 KST 오전에 돌린 수집분(전날 저녁~당일 새벽 UTC 발행)이 컷오프 위로 밀려 통째로 잘려 클러스터·브리프가 0이 된다(빈 다이제스트, 실측: 132건 수집에도 후보 0건). 종일 경계는 KST로 앵커할 것(`tzinfo=_KST`). (2026-06-23, app/pipeline/pipeline.py _freshness_cutoff)
- sentence-transformers(`SentenceTransformer(...)`, app/embed/__init__.py)는 모델이 로컬 캐시에 있어도 로드 시 HF 허브로 메타데이터 HEAD 요청을 보낸다. 서버 프로세스에 truststore가 주입돼 있지 않으면 사내 TLS 가로채기로 `CERTIFICATE_VERIFY_FAILED` → cumulative `/chat` 첫 요청이 500. 서버는 네트워크가 불필요(캐시만 쓰면 됨)하므로 `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1`로 띄울 것. 모델 최초 다운로드(임베딩 백필)만 `truststore.inject_into_ssl()` 필요. (2026-06-23, app/embed/__init__.py / app/main.py)
- alembic `migrations/env.py`에서 DB 접속 문자열을 `config.set_main_option("sqlalchemy.url", …)`/`get_section`(configparser)으로 왕복시키면, URL-인코딩된 비밀번호의 `%`(`%40` 등)를 configparser BasicInterpolation이 보간 문법으로 오인해 `ValueError: invalid interpolation syntax`로 env.py import 단계에서 죽는다(특수문자 비밀번호의 매니지드 DB에서 무조건 재현). URL은 configparser에 넣지 말고 `create_engine(settings.database_url, …)`로 직접 넘길 것. (2026-06-28, migrations/env.py run_migrations_online)

## Measurable Conventions
<!-- 측정 가능한 것만. "잘 짜라" 같은 추상 표현 금지 -->
- 마이그레이션 변경은 실DB(Docker `ankane/pgvector`)에서 `upgrade head → alembic check(클린) → downgrade base` 라운드트립으로 검증한다. pytest/ruff/mypy는 alembic을 실행하지 않으므로 마이그레이션 결함(인코딩·nullable 드리프트 등)을 통과시킨다.
- 같은 세션·트랜잭션에서 한 파이프라인 단계가 직전 단계가 `add`한 행을 SELECT로 다시 읽으면(예: `cluster._candidate_docs`가 `dedup`의 `ClusterMember`를 제외), 쓴 단계 끝에서 `session.flush()`를 명시 호출한다(`SessionLocal` `autoflush=False`라 안 하면 후속 SELECT가 미반영 행을 못 봐 중복 처리 — dedup→cluster 중복 클러스터 (4,4) 회귀). 커밋은 호출자가 일괄 처리. (2026-06-20, app/pipeline/pipeline.py dedup)

## Self-Reflection on Errors
When an error, exception, test failure, or unexpected behavior occurs
during this session, perform reflection AUTONOMOUSLY — do not wait for
the user to point it out:

1. STOP. Do not patch the symptom or suppress the error.
2. Analyze the root cause:
   - What was the actual failure mode (not just the error message)?
   - Why did this happen? Trace back to the originating decision or
     assumption that led here.
   - Was this caused by a silent assumption, missing context, or
     ignored convention?
   - Is this an instance of a pattern that could recur?
3. Fix the root cause, not the symptom.
4. After fixing, ask: "Would a rule in this CLAUDE.md have prevented
   this error?"
   - If YES → propose adding the rule (one line, specific, measurable)
     to the relevant section (Gotchas / Conventions). Show the proposed
     change and wait for user confirmation before writing.
   - If NO → log the lesson to Auto Memory instead, since it's a
     transient environmental issue rather than a project rule.

The goal is preventing the same CLASS of error from recurring. Every
error is a free lesson — capture it before it escapes.

## Project Context
<!-- 도메인·비즈니스 맥락만. 한국어 가능. 코드로 알 수 있는 정보 금지 -->
경제·주식·코인 관련 뉴스를 크롤링해 와서 에이전트로 분석하고, 현재
시황에서 가장 영향이 클 만한 종목을 추천하는 프로젝트.

핵심 파이프라인: 뉴스 수집(크롤링) → 에이전트 분석(시황·이벤트 해석)
→ 영향도 높은 종목 추천.

도메인 주의:
- 종목 추천은 투자 권유가 아니라 "현재 뉴스 기준 영향도 분석" 결과로
  취급. 추천 근거(어떤 뉴스·이벤트에서 도출됐는지)를 항상 함께 남길 것.
- 크롤링 소스의 신뢰도·시점(발행 시각)을 분석에 반영. 오래된 뉴스로
  현재 시황을 판단하지 말 것.
