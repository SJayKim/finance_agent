"""§7 2-패스 Citations 영향도 분석.

패스1(Citations API): 클러스터의 1차 소스에서 cited_text를 강제 추출하며 영향도
분석 문장을 생성한다(zero-fabrication: 인용 없는 주장 금지). 패스2(Structured
Outputs): 패스1 출력만으로 event_type/direction/confidence를 재구조화한다 —
새 사실·수치 도입 금지(무결성 규칙 §7). Citations와 Structured Outputs는 동시
사용 불가(400)라 두 패스로 분리한다.

런타임 httpx는 truststore로 OS 인증서를 신뢰한다(사내 TLS 가로채기, CLAUDE.md gotcha).
"""

from __future__ import annotations

import json
import ssl
from dataclasses import dataclass
from datetime import date
from typing import Any

import truststore
from anthropic import Anthropic, DefaultHttpxClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BriefItem, Citation, ClusterMember, RawDocument

_MODEL = "claude-opus-4-8"
_PASS1_MAX_TOKENS = 16000
_PASS2_MAX_TOKENS = 1024

_PASS1_PROMPT = (
    "다음 1차 소스 문서들을 근거로 현재 시황에서의 영향도를 간결히 분석하라. "
    "모든 문장은 반드시 문서 원문을 인용(cited_text)해 뒷받침하라. "
    "인용으로 뒷받침할 수 없는 주장은 쓰지 마라."
)

_PASS2_SCHEMA = {
    "type": "object",
    "properties": {
        "event_type": {"type": "string"},
        "direction": {"type": "string", "enum": ["긍정", "부정", "중립"]},
        "confidence": {"type": "string", "enum": ["HIGH", "MED", "LOW"]},
    },
    "required": ["event_type", "direction", "confidence"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class ParsedCitation:
    document_index: int
    cited_text: str
    start_char: int
    end_char: int


def default_client() -> Anthropic:
    """truststore TLS를 신뢰하는 Anthropic 클라이언트 (ANTHROPIC_API_KEY env)."""
    ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    return Anthropic(http_client=DefaultHttpxClient(verify=ctx))


def _doc_text(title: str | None, summary: str | None, body: str | None) -> str | None:
    """인용 대상 본문: body → summary → title 순으로 비지 않은 첫 텍스트."""
    for text in (body, summary, title):
        if text and text.strip():
            return text
    return None


def build_document_blocks(texts: list[str]) -> list[dict[str, Any]]:
    """plain-text document 블록 목록 (citations 활성). 리스트 인덱스 = document_index."""
    return [
        {
            "type": "document",
            "source": {"type": "text", "media_type": "text/plain", "data": text},
            "citations": {"enabled": True},
        }
        for text in texts
    ]


def parse_pass1(content: list[Any]) -> tuple[str, list[ParsedCitation]]:
    """패스1 응답 content → (analysis_text, char_location 인용 목록).

    text 블록을 이어 analysis_text를 만들고, 각 블록의 citations 중 char_location만
    추출한다(plain-text 문서 → 문자 인덱스). 다른 인용 타입·비-text 블록은 무시.
    """
    parts: list[str] = []
    cites: list[ParsedCitation] = []
    for block in content:
        if getattr(block, "type", None) != "text":
            continue
        parts.append(block.text)
        for c in getattr(block, "citations", None) or []:
            if getattr(c, "type", None) == "char_location":
                cites.append(
                    ParsedCitation(
                        document_index=c.document_index,
                        cited_text=c.cited_text,
                        start_char=c.start_char_index,
                        end_char=c.end_char_index,
                    )
                )
    return "".join(parts), cites


def verify_citation(cite: ParsedCitation, source_text: str) -> bool:
    """swap test: 원문의 char 범위가 cited_text와 일치하는가(§7 검증)."""
    return source_text[cite.start_char : cite.end_char] == cite.cited_text


def build_pass2_prompt(analysis_text: str, cited_texts: list[str]) -> str:
    """패스2 입력: 패스1 분석문 + 인용문만(무결성 규칙 — 원문 미포함)."""
    quotes = "\n".join(f"- {t}" for t in cited_texts)
    return (
        "다음은 1차 인용 분석 결과다. 이 분석문과 인용문만 근거로 "
        "event_type·direction·confidence를 추출하라. 새로운 사실이나 수치를 끌어오지 마라.\n\n"
        f"[분석문]\n{analysis_text}\n\n[인용문]\n{quotes}"
    )


def _empty_items_with_cluster(session: Session, brief_date: date) -> list[BriefItem]:
    """이 brief_date의 status=empty 이고 클러스터가 있는 brief_item (멱등 재실행 대비)."""
    rows = session.execute(
        select(BriefItem).where(
            BriefItem.brief_date == brief_date,
            BriefItem.status == "empty",
            BriefItem.cluster_id.is_not(None),
        )
    ).scalars()
    return list(rows)


def _cluster_docs(session: Session, cluster_id: int) -> list[RawDocument]:
    rows = session.execute(
        select(RawDocument)
        .join(ClusterMember, ClusterMember.raw_document_id == RawDocument.id)
        .where(ClusterMember.cluster_id == cluster_id)
        .order_by(RawDocument.id)
    ).scalars()
    return list(rows)


def analyze_impact(session: Session, brief_date: date, client: Anthropic | None = None) -> None:
    """§7 2-패스 분석: status=empty brief_item을 채운다. 클러스터당 1회 분석.

    근거(인용)가 하나도 안 나오면 status=empty를 유지한다(§10 null-evidence:
    근거 없으면 환각으로 채우지 않는다). swap test에서 탈락한 인용이 있으면 degraded.
    client 미주입 시 처리할 항목이 있을 때만 default_client()를 만든다(키 없는 빈
    파이프라인 실행이 클라이언트 생성에서 깨지지 않게).
    """
    items = _empty_items_with_cluster(session, brief_date)
    if not items:
        return
    if client is None:
        client = default_client()

    for item in items:
        assert item.cluster_id is not None  # _empty_items_with_cluster 보장
        sources = [
            doc
            for doc in _cluster_docs(session, item.cluster_id)
            if _doc_text(doc.title, doc.summary, doc.body) is not None
        ]
        texts = [_doc_text(d.title, d.summary, d.body) or "" for d in sources]
        if not texts:
            continue  # 근거 텍스트 없음 → status=empty 유지(§10)

        # document 블록(dict)은 SDK MessageParam TypedDict와 정적으로 안 맞아 Any로 둔다.
        pass1_content: Any = [
            *build_document_blocks(texts),
            {"type": "text", "text": _PASS1_PROMPT},
        ]
        pass1 = client.messages.create(
            model=_MODEL,
            max_tokens=_PASS1_MAX_TOKENS,
            thinking={"type": "adaptive"},
            messages=[{"role": "user", "content": pass1_content}],
        )
        analysis_text, cites = parse_pass1(pass1.content)

        verified: list[ParsedCitation] = []
        dropped = False
        for c in cites:
            if 0 <= c.document_index < len(texts) and verify_citation(c, texts[c.document_index]):
                verified.append(c)
            else:
                dropped = True
        if not verified:
            continue  # 인용 없음/전부 탈락 → 환각 금지, status=empty 유지(§10)

        for c in verified:
            src = sources[c.document_index]
            session.add(
                Citation(
                    brief_item_id=item.id,
                    raw_document_id=src.id,
                    cited_text=c.cited_text,
                    char_start=c.start_char,
                    char_end=c.end_char,
                    source_published_at=src.published_at,
                )
            )

        pass2 = client.messages.create(
            model=_MODEL,
            max_tokens=_PASS2_MAX_TOKENS,
            messages=[
                {
                    "role": "user",
                    "content": build_pass2_prompt(analysis_text, [c.cited_text for c in verified]),
                }
            ],
            output_config={"format": {"type": "json_schema", "schema": _PASS2_SCHEMA}},
        )
        fields = json.loads(next(b.text for b in pass2.content if b.type == "text"))
        item.event_type = fields["event_type"]
        item.direction = fields["direction"]
        item.confidence = fields["confidence"]
        item.analysis_text = analysis_text
        item.status = "degraded" if dropped else "ok"

    session.flush()
