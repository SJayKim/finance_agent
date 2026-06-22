"""FastAPI 골격: health + 온디맨드 트리거 + 대시보드 root (STAGE1_DESIGN §3, §4)."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.pipeline.pipeline import PipelineAlreadyRunning, run_pipeline

BASE_DIR = Path(__file__).resolve().parent
_KST = timezone(timedelta(hours=9))  # 07:00 KST 크론과 같은 기준일(§3) — KST는 DST 없음

app = FastAPI(title="finance-agent — 증거 브리프")
templates = Jinja2Templates(directory=str(BASE_DIR / "web" / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "web" / "static")), name="static")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/trigger")
def trigger() -> dict[str, str]:
    """온디맨드 파이프라인 트리거 (§3·§4): 오늘(KST) brief_date로 run_pipeline 1회 동기 실행.

    07:00 크론과 같은 기준일로 돈다. 동시성 가드(pg_try_advisory_lock)에 걸리면 —
    크론이나 다른 트리거가 이미 실행 중 — 409로 거절한다(중복 실행 방지).
    """
    brief_date = datetime.now(_KST).date()
    try:
        run_pipeline(brief_date)
    except PipelineAlreadyRunning as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"status": "ok", "brief_date": brief_date.isoformat()}


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html")
