"""FastAPI 골격: health + 온디맨드 트리거 + 증거 브리프 대시보드 (STAGE1_DESIGN §3, §4)."""

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.db import SessionLocal
from app.pipeline.citations import build_client
from app.pipeline.pipeline import PipelineAlreadyRunning, run_pipeline
from app.web.chat import ChatAnalyzer, anthropic_chat
from app.web.queries import load_brief

BASE_DIR = Path(__file__).resolve().parent
_KST = timezone(timedelta(hours=9))  # 07:00 KST 크론과 같은 기준일(§3) — KST는 DST 없음

app = FastAPI(title="finance-agent — 증거 브리프")
templates = Jinja2Templates(directory=str(BASE_DIR / "web" / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "web" / "static")), name="static")


def _parse_date(value: str | None) -> date:
    """?date=YYYY-MM-DD → date. 없으면 오늘(KST, /trigger·크론과 같은 기준일). 잘못된 형식 → 400."""
    if not value:
        return datetime.now(_KST).date()
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid date (expected YYYY-MM-DD)") from exc


def _chat_analyzer() -> ChatAnalyzer | None:
    """anthropic_api_key 있으면 §7 경계 채팅 분석기, 없으면 None(채팅 비활성). 테스트는 monkeypatch."""
    if not settings.anthropic_api_key:
        return None
    return anthropic_chat(build_client(settings.anthropic_api_key), settings.impact_model)


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
def dashboard(request: Request, date: str | None = None) -> HTMLResponse:
    """추적성 뷰: 해당 날짜(기본 오늘 KST)의 brief_items + 종목 + 인용 근거를 렌더 (§10)."""
    brief_date = _parse_date(date)
    with SessionLocal() as session:
        briefs = load_brief(session, brief_date)
    last_updated = max((b.last_updated for b in briefs), default=None)
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "briefs": briefs,
            "brief_date": brief_date,
            "last_updated": last_updated,
            "chat_enabled": bool(settings.anthropic_api_key),
        },
    )


@app.post("/chat", response_class=HTMLResponse)
def chat(request: Request, q: str = Form(""), date: str | None = Form(None)) -> HTMLResponse:
    """근거기반 채팅 (요구 #2): 해당 날짜 브리프 근거로 Citations 강제 답변 HTML 프래그먼트.

    키 없음 → '채팅 비활성'. 빈 입력/인용 0/장애 → '관련 근거 없음'(graceful, HTTP 200).
    거부 판정은 인용 유무가 유일 기준 — LLM 텍스트로 판정하지 않는다.
    """
    analyzer = _chat_analyzer()
    ctx: dict[str, object] = {"answer": None, "disabled": False}
    if analyzer is None:
        ctx["disabled"] = True
        return templates.TemplateResponse(request, "_chat_answer.html", ctx)
    question = q.strip()
    if question:
        brief_date = _parse_date(date)
        with SessionLocal() as session:
            briefs = load_brief(session, brief_date)
        ctx["answer"] = analyzer(question, briefs)
    return templates.TemplateResponse(request, "_chat_answer.html", ctx)
