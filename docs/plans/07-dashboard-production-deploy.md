# 07 - Dashboard Production Deploy

이 문서가 canonical handoff 문서다. 다음 세션/agent는 이 파일 하나만 읽고 이어가면 된다.

## TL;DR

- **Production 데이터 파이프라인은 이미 가동 중**이다.
  - GitHub Actions `daily.yml`가 `main`에서 실행된다.
  - `DATABASE_URL` secret을 통해 Supabase PostgreSQL/pgvector에 적재한다.
  - 최신 확인 run은 성공했다.
- **Production 웹 대시보드는 아직 없다.**
  - `finance-agent-dashboard.fly.dev` DNS가 잡혀 있지 않았다.
  - 이 머신에 `flyctl`도 설치되어 있지 않았다.
  - `Dockerfile`과 `fly.toml`은 배포 준비물이지 배포 완료 증거가 아니다.
- 다음 작업의 핵심은 **FastAPI 대시보드를 인증 보호한 뒤 Fly.io에 첫 배포**하는 것이다.
- daily scheduler는 그대로 GitHub Actions에 둔다. Fly는 dashboard runtime만 담당한다.

## Current State

### What Is Already Production

현재 production으로 간주할 수 있는 것은 **Supabase-backed daily data pipeline**이다.

- GitHub repository: `SJayKim/finance_agent`
- Default branch: `main`
- Scheduler: `.github/workflows/daily.yml`
- Cron: `40 21 * * *` UTC, 즉 `06:40 KST`
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

### What Is Not Yet Production

FastAPI/Jinja dashboard는 아직 public production URL로 배포되지 않았다.

- Expected Fly URL: `https://finance-agent-dashboard.fly.dev`
- DNS check: `Resolve-DnsName finance-agent-dashboard.fly.dev` returned no result during planning.
- Tooling check: `Get-Command flyctl` returned no installed `flyctl` during planning.
- There is no known successful `flyctl deploy` checkpoint.

Conclusion: **Supabase에는 production data가 있고, 그 데이터를 보여주는 production dashboard URL은 아직 없다.**

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

Observed: no installed `flyctl`.

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

- Currently, the dashboard/action routes are unauthenticated.
- If deployed as-is, anyone with the URL could view the dashboard and potentially call `/trigger` or `/run-daily`.
- Therefore authentication must be added before first public deploy.

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

### 8. Add Auto Deploy After Manual Success

Only after the first manual Fly deployment succeeds, add a GitHub Actions deployment workflow.

Recommended behavior:

- Trigger on `main` pushes.
- Run after normal CI quality gates.
- Use GitHub secret `FLY_API_TOKEN`.
- Deploy using the existing `fly.toml`.

Do not add auto deploy before proving the first manual deployment works, because failures at this stage are likely account/app/secrets/tooling issues rather than code issues.

## Acceptance Criteria

The deployment work is complete when all are true:

- Tests pass locally.
- Protected routes reject unauthenticated requests.
- `/health` remains public.
- Fly app exists as `finance-agent-dashboard`.
- `https://finance-agent-dashboard.fly.dev/health` returns `{"status":"ok"}`.
- Authenticated `https://finance-agent-dashboard.fly.dev/` renders latest Supabase data.
- Secrets are stored only in Fly/GitHub/local `.env`, not in tracked files.
- A later `main` deploy path is either documented or automated after manual deploy success.

## Risks And Gotchas

- **Authentication is required before public deploy.** Current app has unauthenticated action endpoints.
- **Fly URL absence means no deployed app.** `Dockerfile`/`fly.toml` alone do not imply production.
- **GitHub schedule time is best effort.** Cron is `06:40 KST`, but observed start was `07:07 KST`.
- **Source coverage may be incomplete.** Missing collector secrets affect data breadth, not dashboard deploy mechanics.
- **bge-m3 memory pressure.** Keep existing 4 GB Fly VM setting unless embedding behavior is changed.
- **Do not log secrets.** Especially avoid echoing `DATABASE_URL`.

## Resume Checklist For Next Agent

1. Read only this document first.
2. Confirm current git status.
3. Implement Basic Auth in `app/config.py` and `app/main.py`.
4. Add route auth tests.
5. Run pytest, ruff, mypy.
6. Optionally smoke test local dashboard against Supabase on port `8001`.
7. Install/login `flyctl`.
8. Create/confirm `finance-agent-dashboard`.
9. Set Fly secrets.
10. Run `flyctl deploy`.
11. Verify health and authenticated dashboard.
12. Add auto deploy workflow only after manual deploy succeeds.
