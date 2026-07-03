# 07 - Dashboard Production Deploy

이 문서가 canonical handoff 문서다. 다음 세션/agent는 이 파일 하나만 읽고 이어가면 된다.

## TL;DR

- **Production 데이터 파이프라인은 이미 가동 중**이다.
  - GitHub Actions `daily.yml`가 `main`에서 실행된다.
  - `DATABASE_URL` secret을 통해 Supabase PostgreSQL/pgvector에 적재한다.
  - 최신 확인 run은 성공했다.
  - 모든 optional source API key 활성화 후 30분 제한이 부족해 `timeout-minutes`를 `90`으로 올렸다.
- **Production 웹 대시보드도 이제 가동 중**이다.
  - Fly 앱 `finance-agent-dashboard`가 배포됐다.
  - Public health: `https://finance-agent-dashboard.fly.dev/health` returns `{"status":"ok"}`.
  - Dashboard URL: `https://finance-agent-dashboard.fly.dev/`
  - `/`는 Basic Auth 없이는 `401`, 인증 성공 시 `200`으로 dashboard HTML을 렌더링한다.
  - `/chat`, `/trigger`, `/run-daily`도 인증 없이는 `401`이다.
- **FastAPI 대시보드 인증 보호는 로컬 구현/검증 완료** 상태다.
  - Basic Auth가 `/`, `/chat`, `/trigger`, `/run-daily`에 적용됐다.
  - `/health`는 public으로 유지된다.
  - local quality gates는 통과했다: `pytest`, `ruff`, `mypy`.
- **Auto deploy path도 준비됐다.**
  - `.github/workflows/deploy-dashboard.yml`를 추가했다.
  - GitHub secret `FLY_API_TOKEN`을 등록했다.
  - GitHub Actions runtime에서는 flyctl 호환성을 위해 같은 secret을 `FLY_API_TOKEN`과 `FLY_ACCESS_TOKEN` 둘 다로 전달한다.
  - deploy token 검증이 로컬에서 성공한 `flyctl` `0.4.64`로 Actions 버전을 pin했다.
- daily scheduler는 그대로 GitHub Actions에 둔다. Fly는 dashboard runtime만 담당한다.

## Current State

### What Is Already Production

현재 production으로 간주할 수 있는 것은 **Supabase-backed daily data pipeline**이다.

- GitHub repository: `SJayKim/finance_agent`
- Default branch: `main`
- Scheduler: `.github/workflows/daily.yml`
- Cron: `40 21 * * *` UTC, 즉 `06:40 KST`
- Timeout: `90` minutes
- 실제 GitHub scheduled run은 지연될 수 있다.
- Database: managed Supabase PostgreSQL with pgvector, injected via GitHub secret `DATABASE_URL`
- AI analysis: `ANTHROPIC_API_KEY` secret이 있을 때 Anthropic analysis/citation path가 동작한다.

최근 확인된 daily run:

- Run id: `28550916792`
- Event: `schedule`
- Branch: `main`
- Status: `completed`
- Conclusion: `success`
- Created: `2026-07-01T22:07:33Z` (`2026-07-02 07:07:33 KST`)
- Updated: `2026-07-01T22:28:32Z` (`2026-07-02 07:28:32 KST`)

### What Is Production

FastAPI/Jinja dashboard is now deployed on Fly.io.

- Production URL: `https://finance-agent-dashboard.fly.dev`
- DNS check: `Resolve-DnsName finance-agent-dashboard.fly.dev` returns A and AAAA records.
- Tooling: `flyctl` was installed with `winget` on 2026-07-03 KST.
- Auth state: `flyctl auth whoami` succeeds as `cyon13022@gmail.com`.
- App state: `finance-agent-dashboard` is deployed in `nrt` with two app machines.
- Latest verified image tag: `deployment-01KWJNP7FF2WHH4HEXRR0SDHAD`
- Fly secrets deployed:
  - `DATABASE_URL`
  - `ANTHROPIC_API_KEY`
  - `DASHBOARD_USERNAME`
  - `DASHBOARD_PASSWORD`
- Health verification:
  - `GET /health` -> `200 {"status":"ok"}`
  - unauthenticated `GET /` -> `401`
  - authenticated `GET /` -> `200`, dashboard title present
  - unauthenticated `POST /chat` -> `401`
  - unauthenticated `POST /trigger` -> `401`
  - unauthenticated `POST /run-daily` -> `401`

Conclusion: **Supabase production data와 Fly production dashboard가 모두 동작한다.**

### Local Implementation Progress

Completed on 2026-07-03 KST:

- Added dashboard Basic Auth settings in `app/config.py`:
  - `dashboard_username`
  - `dashboard_password`
- Added FastAPI Basic Auth protection in `app/main.py`.
- Protected routes:
  - `GET /`
  - `POST /chat`
  - `POST /trigger`
  - `POST /run-daily`
- Public route:
  - `GET /health`
- Missing credentials and invalid credentials both return `401` with `WWW-Authenticate: Basic`.
- Tests were updated to use test-only dashboard credentials.
- Added route auth tests, including fail-closed behavior when auth config is missing.
- Fly app `finance-agent-dashboard` was created.
- `ANTHROPIC_API_KEY` was read from local `.env` and deployed as a Fly secret without printing the value.
- `DASHBOARD_USERNAME` and `DASHBOARD_PASSWORD` were generated/stored in local `.env` and deployed as Fly secrets without printing the password.
- Supabase `DATABASE_URL` was URL-encoded correctly and deployed as a Fly secret.
- Manual Fly deploy succeeded.
- Auto deploy workflow was added after manual deploy success.
- GitHub secret `FLY_API_TOKEN` was created from a Fly app-scoped deploy token and passed to flyctl as both `FLY_API_TOKEN` and `FLY_ACCESS_TOKEN`.
- The deploy workflow pins `flyctl` to `0.4.64`, matching the local version that successfully validated the deploy token.
- `daily.yml` timeout was raised from 30 to 90 minutes after the first all-sources run reached the old 30-minute GitHub Actions timeout.

Deployment implementation note:

- The Fly web image intentionally does **not** install the `embeddings` extra, matching the existing `daily.yml` production pipeline.
- This avoids shipping torch/HuggingFace model downloads in the dashboard image.
- Cumulative RAG/embedder paths gracefully degrade when `sentence-transformers` is absent.
- Local Docker builds on this machine needed `UV_SYNC_FLAGS="--allow-insecure-host pypi.org --allow-insecure-host files.pythonhosted.org"` because the local container network rejects PyPI TLS certificates. The committed Dockerfile defaults to secure `uv sync`; the insecure flags are only a build arg override.

Local quality gates completed:

```text
uv run pytest        -> 173 passed, 2 warnings
uv run ruff check .  -> All checks passed
uv run mypy .        -> Success: no issues found in 69 source files
```

Current working tree after this progress contains local, uncommitted changes:

```text
M app/config.py
M app/main.py
M Dockerfile
A .github/workflows/deploy-dashboard.yml
M docs/plans/07-dashboard-production-deploy.md
M tests/conftest.py
M tests/test_digest_view.py
M tests/test_health.py
M tests/test_rag_chat.py
M tests/test_web.py
```

Current working tree also contains unrelated pre-existing deletions not made as part of this deploy work:

```text
D docs/learnings/00-system-overview.md
D docs/learnings/01-data-collection.md
D docs/learnings/02-daily-run-and-trigger.md
D docs/learnings/03-impact-pipeline.md
D docs/learnings/04-citations-and-ai-analysis.md
D docs/learnings/05-digest-and-rag.md
D docs/learnings/06-dashboard-and-chat-ui.md
D docs/learnings/07-data-model.md
D docs/learnings/08-tests-and-quality-gates.md
```

## Evidence And Commands Already Run

These read-only checks were run from repo root `C:\Users\cyon1\OneDrive\Desktop\finance_agent`.

```powershell
git status --short --branch
```

Observed before writing this plan:

```text
## main...origin/main
```

```powershell
gh run list --workflow daily.yml --limit 5 --json databaseId,status,conclusion,createdAt,updatedAt,headBranch,event
```

Important result:

```text
28550916792 schedule main completed success created 2026-07-01T22:07:33Z updated 2026-07-01T22:28:32Z
```

```powershell
Resolve-DnsName finance-agent-dashboard.fly.dev -ErrorAction SilentlyContinue
```

Observed: no DNS result.

```powershell
Get-Command flyctl -ErrorAction SilentlyContinue
```

Original planning observation: no installed `flyctl`.

Current update, 2026-07-03 KST:

```powershell
winget install --id Fly-io.flyctl -e --accept-package-agreements --accept-source-agreements
```

Observed: install succeeded.

```powershell
flyctl version
```

Observed via installed executable path:

```text
flyctl.exe v0.4.64 windows/amd64
```

```powershell
flyctl auth whoami
```

Observed:

```text
Error: no access token available. Please login with 'flyctl auth login'
```

Later update, 2026-07-03 KST:

```powershell
flyctl auth login
flyctl auth whoami
```

Observed:

```text
successfully logged in as cyon13022@gmail.com
```

```powershell
flyctl apps create finance-agent-dashboard
flyctl apps list
```

Observed:

```text
finance-agent-dashboard personal pending
```

```powershell
flyctl secrets set ANTHROPIC_API_KEY=<value from local .env> -a finance-agent-dashboard
flyctl secrets set DASHBOARD_USERNAME=<generated> DASHBOARD_PASSWORD=<generated> -a finance-agent-dashboard
flyctl secrets set DATABASE_URL=<Supabase URL with encoded password> -a finance-agent-dashboard
flyctl secrets list -a finance-agent-dashboard
```

Observed after deploy:

```text
ANTHROPIC_API_KEY Deployed
DASHBOARD_USERNAME Deployed
DASHBOARD_PASSWORD Deployed
DATABASE_URL Deployed
```

Manual deployment:

```powershell
flyctl deploy --local-only --build-arg "UV_SYNC_FLAGS=--allow-insecure-host pypi.org --allow-insecure-host files.pythonhosted.org" -a finance-agent-dashboard
```

Observed:

```text
Image: finance-agent-dashboard:deployment-01KWJNP7FF2WHH4HEXRR0SDHAD
Machines: 5683d111eb0778, 918576676a9558
Region: nrt
```

Production verification:

```text
GET /health -> 200 {"status":"ok"}
GET / without auth -> 401
GET / with auth -> 200, dashboard title present
POST /chat without auth -> 401
POST /trigger without auth -> 401
POST /run-daily without auth -> 401
```

Note: the current PowerShell process may not see the newly added `flyctl` PATH entry until a new shell is opened. The installed executable was found at:

```text
C:\Users\cyon1\AppData\Local\Microsoft\WinGet\Packages\Fly-io.flyctl_Microsoft.Winget.Source_8wekyb3d8bbwe\flyctl.exe
```

```powershell
git log --oneline -- Dockerfile fly.toml .github/workflows/daily.yml
```

Relevant commits:

```text
1774dea feat(ops): 대시보드 Fly.io 배포 (Dockerfile + fly.toml)
e7724a5 feat(ops): 일일 클라우드 자동 실행 워크플로 (GitHub Actions cron)
```

Interpretation:

- `1774dea` added deployment configuration, not proof of a live Fly deployment.
- `e7724a5` introduced the cloud daily workflow that is now proven against Supabase.

## Existing App Shape

The dashboard app is a FastAPI application.

- Entrypoint: `app/main.py`
- Settings: `app/config.py`
- Dashboard route: `GET /`
- Chat route: `POST /chat`
- On-demand pipeline route: `POST /trigger`
- On-demand full daily route: `POST /run-daily`
- Health route: `GET /health`
- Templates/static files: `app/web/templates`, `app/web/static`
- Existing health tests: `tests/test_health.py`

Important security fact:

- Dashboard/action routes are now protected by Basic Auth in the local working tree.
- `/health` remains public.
- If `DASHBOARD_USERNAME` or `DASHBOARD_PASSWORD` is missing, protected routes fail closed with `401`.
- First public deploy still requires setting Fly secrets before verification, otherwise the dashboard will be intentionally inaccessible.

## Deployment Decision

Use **Fly.io** for the web dashboard.

Reasons:

- The repo already has `Dockerfile` and `fly.toml`.
- `fly.toml` already names the app `finance-agent-dashboard`.
- `fly.toml` uses region `nrt`, which matches the prior Supabase Tokyo-region decision and keeps latency low from Korea/Japan.
- Docker runtime matches the current FastAPI deployment shape.
- The app can use Fly secrets without committing production values.

Keep **GitHub Actions** for daily collection.

Reasons:

- It is already green against Supabase.
- It already has concurrency protection and migrations in the workflow.
- Moving the scheduler now would add risk without solving the missing dashboard URL.

## Target Production Shape

- Data pipeline:
  - GitHub Actions `daily.yml`
  - Supabase PostgreSQL/pgvector
  - Existing repo secrets
- Dashboard:
  - Fly.io app `finance-agent-dashboard`
  - URL `https://finance-agent-dashboard.fly.dev`
  - Docker image from existing `Dockerfile`
  - Existing `fly.toml`
  - Basic Auth on user-facing/action routes
  - Public `/health`

## Implementation Plan

### 1. Add Dashboard Authentication

Implement Basic Auth in FastAPI before deployment.

Status: **done locally on 2026-07-03 KST**.

Settings to add in `app/config.py`:

- `dashboard_username: str | None = None`
- `dashboard_password: str | None = None`

Behavior:

- Protect:
  - `GET /`
  - `POST /chat`
  - `POST /trigger`
  - `POST /run-daily`
- Keep public:
  - `GET /health`

Implementation requirements:

- Use FastAPI `HTTPBasic` or equivalent framework-supported Basic Auth.
- Use constant-time comparison, for example `secrets.compare_digest`.
- Return `401` with `WWW-Authenticate: Basic` when credentials are missing or invalid.
- If credentials are not configured, fail closed for protected routes in production-like runtime. Do not silently expose the dashboard because a secret was forgotten.

Recommended minimal rule:

- Protected routes require both username and password to be configured and matched.
- Tests can set these via monkeypatch/env.

### 2. Add Authentication Tests

Extend `tests/test_health.py` or add a focused test file.

Status: **done locally on 2026-07-03 KST**.

Required cases:

- `GET /health` without auth returns `200`.
- `GET /` without auth returns `401`.
- `GET /` with invalid auth returns `401`.
- `GET /` with valid auth returns `200`.
- `POST /chat` without auth returns `401`.
- `POST /trigger` without auth returns `401`.
- `POST /run-daily` without auth returns `401`.

When testing authenticated `/`, keep using the existing test DB fixture behavior. Do not require live Supabase for tests.

### 3. Run Local Quality Gates

Run:

```powershell
uv run pytest
uv run ruff check .
uv run mypy .
```

Fix any failures before deployment.

Status: **done locally on 2026-07-03 KST**.

```text
173 passed
ruff passed
mypy passed
```

### 4. Optional Local Production-Data Smoke Test

This is useful before Fly deploy because it proves the UI can read the existing Supabase production data.

Use the Supabase `DATABASE_URL` from local `.env`; do not print the value.

Example shape:

```powershell
# Use a separate port so it does not collide with normal local dev.
uv run uvicorn app.main:app --host 127.0.0.1 --port 8001
```

Then visit:

```text
http://127.0.0.1:8001
```

Rules:

- Confirm latest daily data renders.
- Confirm digest/source health render.
- Confirm drawer/chat UI still works.
- Do not call `/trigger` or `/run-daily` during read-only visual verification unless explicitly testing authenticated actions.

### 5. Install And Initialize Fly

Install `flyctl`, then authenticate:

Status: **done**.

- `flyctl` is installed via `winget`.
- Fly login is done.
- App creation is done: `finance-agent-dashboard`.
- Required secrets are deployed.
- The dashboard is live.

```powershell
flyctl auth login
```

Confirm app state:

```powershell
flyctl apps list
```

If `finance-agent-dashboard` does not exist:

```powershell
flyctl apps create finance-agent-dashboard
```

Use the existing `fly.toml`.

### 6. Set Fly Secrets

Required:

```powershell
flyctl secrets set DATABASE_URL="..." ANTHROPIC_API_KEY="..." DASHBOARD_USERNAME="..." DASHBOARD_PASSWORD="..."
```

Do not paste real secret values into docs, chat, git commits, or logs.

Status: **done**.

Deployed Fly secrets:

- `DATABASE_URL`
- `ANTHROPIC_API_KEY`
- `DASHBOARD_USERNAME`
- `DASHBOARD_PASSWORD`

Optional dashboard/runtime parity secrets:

- `OPENFIGI_API_KEY`
- `COINGECKO_API_KEY`

Optional collector secrets can also be registered on Fly, but daily collection remains on GitHub Actions:

- `NAVER_CLIENT_ID`
- `NAVER_CLIENT_SECRET`
- `OPENDART_API_KEY`
- `SEC_EDGAR_USER_AGENT`
- `MARKETAUX_API_KEY`
- `FINNHUB_API_KEY`

Known context: prior checkpoints noted several collector secrets missing from GitHub Actions, so production source coverage may currently be RSS plus Anthropic. That is separate from web deployment.

### 7. Manual First Deploy

Deploy once manually:

```powershell
flyctl deploy
```

Check:

```powershell
flyctl status
flyctl logs
```

Verify public health:

```text
https://finance-agent-dashboard.fly.dev/health
```

Expected:

```json
{"status":"ok"}
```

Verify authenticated dashboard:

```text
https://finance-agent-dashboard.fly.dev/
```

Expected:

- Browser asks for Basic Auth.
- Correct credentials load dashboard.
- Latest Supabase-backed daily data is visible.
- `/chat` works if `ANTHROPIC_API_KEY` is present.
- `/trigger` and `/run-daily` are not accessible without auth.

Status: **done**.

Latest verified image:

```text
finance-agent-dashboard:deployment-01KWJNP7FF2WHH4HEXRR0SDHAD
```

### 8. Add Auto Deploy After Manual Success

Only after the first manual Fly deployment succeeds, add a GitHub Actions deployment workflow.

Recommended behavior:

- Trigger on `main` pushes.
- Run after normal CI quality gates.
- Use GitHub secret `FLY_API_TOKEN`.
- Deploy using the existing `fly.toml`.

Do not add auto deploy before proving the first manual deployment works, because failures at this stage are likely account/app/secrets/tooling issues rather than code issues.

Status: **done**.

- Added `.github/workflows/deploy-dashboard.yml`.
- Created app-scoped Fly deploy token.
- Stored token as GitHub secret `FLY_API_TOKEN`.
- Passed the same secret as both `FLY_API_TOKEN` and `FLY_ACCESS_TOKEN` in the deploy job for flyctl compatibility.
- Pinned GitHub Actions flyctl to `0.4.64` after `0.4.66` returned `Authenticate: token validation error` with the same deploy token.

## Acceptance Criteria

The deployment work is complete when all are true:

- [x] Tests pass locally.
- [x] Protected routes reject unauthenticated requests.
- [x] `/health` remains public.
- [x] Fly app exists as `finance-agent-dashboard`.
- [x] `https://finance-agent-dashboard.fly.dev/health` returns `{"status":"ok"}`.
- [x] Authenticated `https://finance-agent-dashboard.fly.dev/` renders latest Supabase data.
- [x] Secrets are stored only in Fly/GitHub/local `.env`, not in tracked files.
- [x] A later `main` deploy path is automated after manual deploy success.

## Risks And Gotchas

- **Authentication is required before public deploy.** This is now implemented; keep it in place.
- **Fly smoke warning can be early/noisy.** Manual deploy briefly warned that the app was not listening before Uvicorn finished starting, but post-deploy health and logs confirmed `0.0.0.0:8080`.
- **GitHub schedule time is best effort.** Cron is `06:40 KST`, but observed start was `07:07 KST`.
- **Daily run duration increased after enabling all sources.** Timeout is now 90 minutes. If runs still time out, the next fix should reduce analysis volume or split source collection/pipeline steps.
- **Dashboard image does not install embeddings extra.** Cumulative RAG/embedder degrades gracefully. Daily pipeline also currently runs without embeddings extra.
- **bge-m3 memory pressure.** Existing 4 GB Fly VM setting is conservative; if embeddings remain out of the web image, this can be revisited later.
- **Do not log secrets.** Especially avoid echoing `DATABASE_URL`.

## Resume Checklist For Next Agent

1. Read only this document first.
2. Confirm current git status.
3. Review/commit the local changes.
4. Push to `main` when ready; CI should run first, then `Deploy dashboard` should deploy via `FLY_API_TOKEN`/`FLY_ACCESS_TOKEN`.
5. If manually deploying from this Windows machine, use local Docker build with:
   `flyctl deploy --local-only --build-arg "UV_SYNC_FLAGS=--allow-insecure-host pypi.org --allow-insecure-host files.pythonhosted.org" -a finance-agent-dashboard`
6. Verify after any deploy:
   - `GET https://finance-agent-dashboard.fly.dev/health` -> `200`
   - unauthenticated `/` -> `401`
   - authenticated `/` -> dashboard HTML
