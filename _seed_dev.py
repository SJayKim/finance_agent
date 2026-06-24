"""개발용 시드 — 브라우저 테스트용 샘플 브리프. 멱등(전체 비우고 재삽입). 커밋 대상 아님.

재실행: uv run python _seed_dev.py [YYYY-MM-DD]   (기본 오늘 KST)
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone

from app.db import SessionLocal, engine
from app.models import BriefItem, BriefItemTicker, Citation, RawDocument, Source
from sqlalchemy import text

KST = timezone(timedelta(hours=9))
brief_date = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else datetime.now(KST).date()
pub = datetime.now(KST).replace(hour=7, minute=0, second=0, microsecond=0)

# 멱등: 화면이 읽는 테이블만 비운다(개발 DB 전용).
with engine.begin() as conn:
    conn.execute(
        text(
            "TRUNCATE brief_item_tickers, citations, brief_items, raw_documents, sources "
            "RESTART IDENTITY CASCADE"
        )
    )

with SessionLocal() as s:
    src = Source(name="연합뉴스", kind="news", legal_basis="RSS 헤드라인+링크")
    s.add(src)
    s.flush()

    # (raw_document, [brief_item dict]) 묶음. 인용은 doc 본문의 실제 문장.
    docs = [
        dict(
            external_id="yna-bok-2026-0622",
            title="한국은행, 기준금리 3.50% 동결",
            url="https://example.com/news/bok-hold",
            cited="한국은행 금융통화위원회는 22일 기준금리를 연 3.50%로 동결했다.",
        ),
        dict(
            external_id="yna-sec-2026-0622",
            title="삼성전자 2분기 반도체 수요 둔화 경고",
            url="https://example.com/news/samsung-q2",
            cited="삼성전자는 2분기 메모리 반도체 수요 둔화로 영업이익이 전분기 대비 감소할 것이라고 밝혔다.",
        ),
        dict(
            external_id="yna-btc-2026-0622",
            title="비트코인, 美 ETF 순유입에 강세",
            url="https://example.com/news/btc-etf",
            cited="비트코인은 미국 현물 ETF로의 자금 순유입이 이어지며 7만 달러를 회복했다.",
        ),
    ]
    raws = []
    for d in docs:
        r = RawDocument(
            source_id=src.id,
            external_id=d["external_id"],
            published_at=pub,
            lang="ko",
            title=d["title"],
            url=d["url"],
            body=d["cited"],
        )
        s.add(r)
        raws.append(r)
    s.flush()

    items = [
        dict(
            event_type="통화정책",
            direction="중립",
            confidence="HIGH",
            analysis="기준금리 동결로 시장 예상에 부합. 은행·금리 민감 섹터 변동성 제한적.",
            tickers=[("105560", "KR", False), ("055550", "KR", False)],
            raw=raws[0],
        ),
        dict(
            event_type="실적경고",
            direction="부정",
            confidence="MED",
            analysis="반도체 수요 둔화 경고는 단기 투자심리에 부정적. 메모리 밸류체인 영향.",
            tickers=[("005930", "KR", False), ("000660", "KR", True)],
            raw=raws[1],
        ),
        dict(
            event_type="자금흐름",
            direction="긍정",
            confidence="MED",
            analysis="현물 ETF 순유입은 가격 지지 요인. 다만 거시 변동성에 민감.",
            tickers=[("BTC", "CRYPTO", False)],
            raw=raws[2],
        ),
    ]
    for it in items:
        bi = BriefItem(
            brief_date=brief_date,
            event_type=it["event_type"],
            direction=it["direction"],
            confidence=it["confidence"],
            analysis_text=it["analysis"],
            status="ok",
            generated_at=pub,
        )
        s.add(bi)
        s.flush()
        for tk, mkt, cand in it["tickers"]:
            s.add(
                BriefItemTicker(
                    brief_item_id=bi.id, ticker=tk, market=mkt, link_precision=0.9, is_candidate=cand
                )
            )
        s.add(
            Citation(
                brief_item_id=bi.id,
                raw_document_id=it["raw"].id,
                cited_text=it["raw"].body,
                source_published_at=pub,
            )
        )
    s.commit()

print(f"seeded brief_date={brief_date} — 3 brief_items, 3 docs, 5 tickers, 3 citations")
