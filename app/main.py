"""FastAPI 골격: health + 온디맨드 트리거 stub + 대시보드 root (STAGE1_DESIGN §3, §4)."""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="finance-agent — 증거 브리프")
templates = Jinja2Templates(directory=str(BASE_DIR / "web" / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "web" / "static")), name="static")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/trigger")
def trigger() -> dict[str, str]:
    """온디맨드 파이프라인 트리거. 골격 단계 — 아직 미구현."""
    return {"status": "accepted", "detail": "pipeline not yet implemented"}


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html")
