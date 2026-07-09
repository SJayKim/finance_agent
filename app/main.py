"""FastAPI 골격: health + 온디맨드 트리거 + 증거 브리프 대시보드 (STAGE1_DESIGN §3, §4)."""

import importlib.util
import secrets
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.db import SessionLocal
from app.embed import get_embedder
from app.llm.factory import (
    chat_key_configured,
    make_chat_analyzer,
    make_digester,
    make_rag_chat_analyzer,
)
from app.pipeline.pipeline import PipelineAlreadyRunning, run_pipeline
from app.pipeline.seed import seed_universe
from app.runner import DailyRunAlreadyRunning, run_daily
from app.web.chat import ChatAnalyzer, RagChatAnalyzer
from app.web.queries import (
    board_asset_counts,
    dates_with_briefs,
    load_brief,
    load_digest,
    load_source_health,
    rank_board,
)
from app.web.render import analysis_html

BASE_DIR = Path(__file__).resolve().parent
_KST = timezone(timedelta(hours=9))  # 07:00 KST 크론과 같은 기준일(§3) — KST는 DST 없음

app = FastAPI(title="finance-agent — 증거 브리프")
templates = Jinja2Templates(directory=str(BASE_DIR / "web" / "templates"))
templates.env.filters["md"] = analysis_html
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "web" / "static")), name="static")
_basic_auth = HTTPBasic(auto_error=False)


def _auth_401(detail: str = "Not authenticated") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Basic"},
    )


def _require_dashboard_auth(
    credentials: Annotated[HTTPBasicCredentials | None, Depends(_basic_auth)],
) -> str:
    username = settings.dashboard_username
    password = settings.dashboard_password
    if credentials is None or not username or not password:
        raise _auth_401()

    username_ok = secrets.compare_digest(
        credentials.username.encode("utf-8"), username.encode("utf-8")
    )
    password_ok = secrets.compare_digest(
        credentials.password.encode("utf-8"), password.encode("utf-8")
    )
    if not (username_ok and password_ok):
        raise _auth_401("Invalid authentication credentials")
    return credentials.username


def _parse_date(value: str | None) -> date:
    """?date=YYYY-MM-DD → date. 없으면 오늘(KST, /trigger·크론과 같은 기준일). 잘못된 형식 → 400."""
    if not value:
        return datetime.now(_KST).date()
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid date (expected YYYY-MM-DD)") from exc


def _default_date(has_data: set[date], today: date) -> date:
    """대시보드 기본 날짜: 데이터 있는 최신일, 없으면 오늘. 오늘 데이터가 있으면 오늘(=최신)."""
    return max(has_data) if has_data else today


def _chat_analyzer() -> ChatAnalyzer | None:
    """챗 provider 키 있으면 §7 경계 채팅 분석기, 없으면 None(채팅 비활성). 테스트는 monkeypatch."""
    return make_chat_analyzer()


def _no_key_msg() -> str:
    """챗 비활성 사유 — 설정된 챗 provider 키 이름을 노출(기본 anthropic → 현행 문자열 동일)."""
    return f"채팅 비활성 ({settings.chat_provider.upper()}_API_KEY 미설정)"


_NO_EMBEDDER_MSG = "누적 검색 비활성 — 서버에 임베딩 모델 미설치 ('이 날짜' 범위는 사용 가능)"


def _rag_available() -> bool:
    """누적 RAG 가용성의 싼 확인: 키 + sentence-transformers 설치 여부(모델 로드 없이).

    대시보드 렌더에서 get_embedder()(2GB 모델 로드)를 부르면 안 된다(§4 규약) —
    find_spec은 import 없이 설치 여부만 본다. Fly 이미지는 임베더 미설치(의도된 설계)라
    False → 누적 라디오 disabled + 툴팁. 예전엔 키만 봐서 임베더 없는 서버가 원인을
    "키 미설정"으로 오진했다(2026-07-04).
    """
    if not chat_key_configured() or settings.embedding_model is None:
        return False
    return importlib.util.find_spec("sentence_transformers") is not None


def _rag_analyzer() -> RagChatAnalyzer | None:
    """키 + 임베더 둘 다 있으면 누적 RAG 채팅 분석기(§4 트랙 D2), 하나라도 없으면 None(graceful 비활성).

    첫 누적 질의에서 get_embedder()가 bge-m3를 로드한다(이후 lru_cache) — import 시 미리 로드하지
    않는다. 테스트는 monkeypatch.
    """
    if not chat_key_configured():
        return None
    embedder = get_embedder()
    if embedder is None:
        return None
    return make_rag_chat_analyzer(embedder)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/trigger", dependencies=[Depends(_require_dashboard_auth)])
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


@app.post("/run-daily", dependencies=[Depends(_require_dashboard_auth)])
def run_daily_endpoint() -> dict[str, object]:
    """온디맨드 전체 일일 실행 (§4 트랙 B): 수집(모든 커넥터) → 파이프라인 → 다이제스트.

    /trigger(파이프라인만 도는 빠른 경로)와 달리 수집까지 포함한 일일 1회 실행이다. 첫
    호출은 embeddings extra가 깔려 있으면 bge-m3를 로드한다(get_embedder, 이후 lru_cache).
    다른 일일 실행이 진행 중이면(_DAILY_LOCK_KEY) 409로 거절한다.
    """
    brief_date = datetime.now(_KST).date()
    embedder = get_embedder()
    digester = make_digester()
    try:
        report = run_daily(
            brief_date, embedder=embedder, digester=digester, seeder=seed_universe
        )
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


def _render_dashboard(
    request: Request,
    date: str | None,
    *,
    public_mode: bool,
) -> HTMLResponse:
    """추적성 뷰 + 일일 다이제스트 + 소스 헬스 (§4 트랙 E / §8.6).

    rag_enabled는 _rag_available()(키 + 라이브러리 설치 여부의 싼 확인) — 여기서
    get_embedder()를 부르지 않는다(2GB bge-m3가 페이지 렌더에 로드되면 안 됨, §4).
    누적 토글은 채팅이 켜지면 노출되고, 임베더 없는 서버는 disabled + 툴팁으로 렌더된다.
    """
    today = datetime.now(_KST).date()
    with SessionLocal() as session:
        has_data = dates_with_briefs(session)
        brief_date = _parse_date(date) if date else _default_date(has_data, today)
        briefs = load_brief(session, brief_date)
        digest = load_digest(session, brief_date)
        health = load_source_health(session, brief_date)
    last_updated = max((b.last_updated for b in briefs), default=None)
    board = rank_board(briefs)
    date_chips = [
        {
            "iso": d.isoformat(),
            "label": d.strftime("%m-%d"),
            "has_data": d in has_data,
            "is_current": d == brief_date,
        }
        for d in (today - timedelta(days=n) for n in range(13, -1, -1))
    ]
    response = templates.TemplateResponse(
        request,
        "index.html",
        {
            "briefs": briefs,
            "board": board,
            "asset_counts": board_asset_counts(board),
            "digest": digest,
            "health": health,
            "brief_date": brief_date,
            "date_chips": date_chips,
            "prev_date": (brief_date - timedelta(days=1)).isoformat(),
            "next_date": (brief_date + timedelta(days=1)).isoformat(),
            "last_updated": last_updated,
            "chat_enabled": False if public_mode else chat_key_configured(),
            "rag_enabled": False if public_mode else _rag_available(),
            "public_mode": public_mode,
            "dashboard_base_path": "/public" if public_mode else "/",
        },
    )
    if public_mode:
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


@app.get("/", response_class=HTMLResponse, dependencies=[Depends(_require_dashboard_auth)])
def dashboard(request: Request, date: str | None = None) -> HTMLResponse:
    """Protected operator dashboard with read-only views plus authenticated chat."""
    return _render_dashboard(request, date, public_mode=False)


@app.get("/public", response_class=HTMLResponse)
def public_dashboard(request: Request, date: str | None = None) -> HTMLResponse:
    """Public read-only dashboard. Write/LLM actions stay behind dashboard auth."""
    return _render_dashboard(request, date, public_mode=True)


@app.post("/chat", response_class=HTMLResponse, dependencies=[Depends(_require_dashboard_auth)])
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
    ctx: dict[str, object] = {"answer": None, "disabled": False, "disabled_msg": None}
    question = q.strip()
    if scope == "cumulative":
        rag = _rag_analyzer()
        if rag is None:
            # 원인 구분: 키 없음 vs 임베더 없음(Fly 이미지는 의도적으로 임베더 미설치).
            ctx["disabled"] = True
            ctx["disabled_msg"] = (
                _no_key_msg() if not chat_key_configured() else _NO_EMBEDDER_MSG
            )
            return templates.TemplateResponse(request, "_chat_answer.html", ctx)
        if question:
            with SessionLocal() as session:
                ctx["answer"] = rag(session, question)
        return templates.TemplateResponse(request, "_chat_answer.html", ctx)

    analyzer = _chat_analyzer()
    if analyzer is None:
        ctx["disabled"] = True
        ctx["disabled_msg"] = _no_key_msg()
        return templates.TemplateResponse(request, "_chat_answer.html", ctx)
    if question:
        brief_date = _parse_date(date)
        with SessionLocal() as session:
            briefs = load_brief(session, brief_date)
        ctx["answer"] = analyzer(question, briefs)
    return templates.TemplateResponse(request, "_chat_answer.html", ctx)
