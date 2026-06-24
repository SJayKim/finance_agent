"""FastAPI 골격: health + 온디맨드 트리거 + 증거 브리프 대시보드 (STAGE1_DESIGN §3, §4)."""

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.db import SessionLocal
from app.embed import get_embedder
from app.pipeline.citations import build_client
from app.pipeline.digest import anthropic_digester
from app.pipeline.pipeline import PipelineAlreadyRunning, run_pipeline
from app.runner import DailyRunAlreadyRunning, run_daily
from app.web.chat import ChatAnalyzer, RagChatAnalyzer, anthropic_chat, anthropic_rag_chat
from app.web.queries import load_brief, load_digest, load_source_health, rank_board

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


def _rag_analyzer() -> RagChatAnalyzer | None:
    """키 + 임베더 둘 다 있으면 누적 RAG 채팅 분석기(§4 트랙 D2), 하나라도 없으면 None(graceful 비활성).

    첫 누적 질의에서 get_embedder()가 bge-m3를 로드한다(이후 lru_cache) — import 시 미리 로드하지
    않는다. 테스트는 monkeypatch.
    """
    if not settings.anthropic_api_key:
        return None
    embedder = get_embedder()
    if embedder is None:
        return None
    return anthropic_rag_chat(
        build_client(settings.anthropic_api_key), settings.impact_model, embedder
    )


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


@app.post("/run-daily")
def run_daily_endpoint() -> dict[str, object]:
    """온디맨드 전체 일일 실행 (§4 트랙 B): 수집(모든 커넥터) → 파이프라인 → 다이제스트.

    /trigger(파이프라인만 도는 빠른 경로)와 달리 수집까지 포함한 일일 1회 실행이다. 첫
    호출은 embeddings extra가 깔려 있으면 bge-m3를 로드한다(get_embedder, 이후 lru_cache).
    다른 일일 실행이 진행 중이면(_DAILY_LOCK_KEY) 409로 거절한다.
    """
    brief_date = datetime.now(_KST).date()
    embedder = get_embedder()
    digester = (
        anthropic_digester(build_client(settings.anthropic_api_key), settings.impact_model)
        if settings.anthropic_api_key
        else None
    )
    try:
        report = run_daily(brief_date, embedder=embedder, digester=digester)
    except DailyRunAlreadyRunning as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "brief_date": report.brief_date.isoformat(),
        "sources": [
            {"name": s.name, "status": s.status, "attempted": s.attempted, "error": s.error}
            for s in report.sources
        ],
        "embedded": report.embedded,
        "digest_status": report.digest_status,
    }


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, date: str | None = None) -> HTMLResponse:
    """추적성 뷰 + 일일 다이제스트 + 소스 헬스 (§4 트랙 E / §8.6).

    rag_enabled는 키 유무만 본다 — 여기서 get_embedder()를 부르지 않는다(2GB bge-m3가
    페이지 렌더에 로드되면 안 됨, §4). 누적 토글은 채팅이 켜지면 노출되고, 임베더가 없으면
    누적 선택 시 첫 질의에서 graceful하게 '채팅 비활성'으로 떨어진다.
    """
    brief_date = _parse_date(date)
    with SessionLocal() as session:
        briefs = load_brief(session, brief_date)
        digest = load_digest(session, brief_date)
        health = load_source_health(session, brief_date)
    last_updated = max((b.last_updated for b in briefs), default=None)
    board = rank_board(briefs)
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "briefs": briefs,
            "board": board,
            "digest": digest,
            "health": health,
            "brief_date": brief_date,
            "prev_date": (brief_date - timedelta(days=1)).isoformat(),
            "next_date": (brief_date + timedelta(days=1)).isoformat(),
            "last_updated": last_updated,
            "chat_enabled": bool(settings.anthropic_api_key),
            "rag_enabled": bool(settings.anthropic_api_key),
        },
    )


@app.post("/chat", response_class=HTMLResponse)
def chat(
    request: Request,
    q: str = Form(""),
    date: str | None = Form(None),
    scope: str = Form("date"),
) -> HTMLResponse:
    """근거기반 채팅 (요구 #2 + §4 트랙 D2): Citations 강제 답변 HTML 프래그먼트.

    scope='cumulative'면 누적 코퍼스 RAG 경로(임베딩 검색 → 인용 span), 그 외엔 기존 '이 날짜'
    경로. 키/임베더 없음 → '채팅 비활성'. 빈 입력/인용 0/장애 → '관련 근거 없음'(graceful, HTTP
    200). 거부 판정은 인용 유무가 유일 기준 — 두 경로 모두 LLM 텍스트로 판정하지 않는다.
    """
    ctx: dict[str, object] = {"answer": None, "disabled": False}
    question = q.strip()
    if scope == "cumulative":
        rag = _rag_analyzer()
        if rag is None:
            ctx["disabled"] = True
            return templates.TemplateResponse(request, "_chat_answer.html", ctx)
        if question:
            with SessionLocal() as session:
                ctx["answer"] = rag(session, question)
        return templates.TemplateResponse(request, "_chat_answer.html", ctx)

    analyzer = _chat_analyzer()
    if analyzer is None:
        ctx["disabled"] = True
        return templates.TemplateResponse(request, "_chat_answer.html", ctx)
    if question:
        brief_date = _parse_date(date)
        with SessionLocal() as session:
            briefs = load_brief(session, brief_date)
        ctx["answer"] = analyzer(question, briefs)
    return templates.TemplateResponse(request, "_chat_answer.html", ctx)
