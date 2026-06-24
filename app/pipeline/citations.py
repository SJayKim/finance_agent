"""§7 2-패스 Citations 분석 (STAGE1_DESIGN §7).

왜 2-패스인가: Anthropic Citations API와 Structured Outputs는 한 콜에서 동시 사용
불가(400). 그래서 분리한다.
- 패스 1 (인용 생성): Citations API로 클러스터 소스(제목+요약)에서 `cited_text`를 강제
  추출하며 영향도 분석 문장을 생성. 근거 없는 주장 금지(zero-fabrication).
- 패스 2 (JSON 추출): Structured Outputs로 패스1 출력을 event_type/direction/confidence로
  재구조화. **무결성 규칙(§7): 패스 2의 입력은 패스 1이 실제 인용한 cited_text 범위로만
  제한** — 새 사실·수치 도입 금지.

영향 종목(티커)은 LLM이 만들지 않는다 — ticker_link(§6.4)가 사전 기반으로 결정한다
(유니버스는 설정 경계, §2). citations는 패스1에서 나온다.

순수 함수(parse_pass1 등, 네트워크·DB 없이 테스트 가능)와 I/O(anthropic_analyzer)를
분리한다 — rss.py와 같은 경계. 클라이언트는 truststore로 OS 인증서를 신뢰시킨다(사내 TLS).
"""

from __future__ import annotations

import json
import ssl
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

import anthropic
import truststore
from anthropic import DefaultHttpxClient
from anthropic.types import MessageParam


@dataclass(frozen=True)
class SourceDoc:
    """패스 1에 먹이는 클러스터 소스 문서. body는 P5(법적 경계)로 None일 수 있어 제목+요약만."""

    raw_document_id: int
    title: str | None
    summary: str | None
    published_at: datetime | None


@dataclass(frozen=True)
class CitedSpan:
    """패스 1이 실제 인용한 원문 범위 — citations 테이블 1행으로 적재."""

    raw_document_id: int
    cited_text: str
    char_start: int | None
    char_end: int | None
    source_published_at: datetime | None


@dataclass(frozen=True)
class ImpactResult:
    """2-패스 결과. citations가 비면 근거 없음(§10 null-evidence) — 호출자가 status로 처리."""

    analysis_text: str
    citations: list[CitedSpan]
    event_type: str | None
    direction: str | None
    confidence: str | None
    # 임팩트 크기 0~100(부호 없음 — 방향은 direction). 근거 기반 분석 산출물. 근거 없으면 None.
    impact_score: int | None = None


# analyze_impact(파이프라인)가 주입받는 I/O 경계. 키 없으면 None(=비활성) 주입 가능.
ImpactAnalyzer = Callable[[Sequence[SourceDoc]], ImpactResult | None]


_PASS1_SYSTEM = (
    "너는 증권 애널리스트의 영향도 분석 보조다. 제공된 뉴스 문서만 근거로, 이 이벤트가 "
    "현재 시황에서 어떤 종목·섹터에 영향을 줄지 간결히 분석한다. 모든 주장은 문서 인용으로 "
    "뒷받침하라. 인용으로 뒷받침할 수 없는 주장·수치는 쓰지 마라. 이것은 투자 권유가 아니라 "
    "뉴스 기준 영향도 해석이다."
)
_PASS1_TASK = "이 뉴스 클러스터의 영향도를 분석하라."

_PASS2_SYSTEM = (
    "너는 1차 영향도 분석을 구조화한다. 아래 분석 텍스트와 인용된 근거만 사용하고, 새 사실·"
    "수치·종목을 도입하지 마라. 재구조화만 한다. impact_score는 이 이벤트가 영향 종목에 주는 "
    "임팩트의 크기(부호 없음)를 0~100으로 매긴다 — 인용된 근거가 시사하는 강도만 반영하고, "
    "방향(상승/하락)은 direction이 따로 표현하므로 점수에 부호를 넣지 마라. 근거가 약하거나 "
    "중립이면 낮게, 다수 강한 근거가 한 방향을 가리키면 높게. 근거로 뒷받침 안 되는 값은 쓰지 마라."
)

_PASS2_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "event_type": {"type": "string"},  # taxonomy STAGE0-BLOCKED → 자유 문자열
        "direction": {"type": "string", "enum": ["긍정", "부정", "중립"]},
        "confidence": {"type": "string", "enum": ["HIGH", "MED", "LOW"]},
        "impact_score": {"type": "integer", "minimum": 0, "maximum": 100},
    },
    "required": ["event_type", "direction", "confidence", "impact_score"],
    "additionalProperties": False,
}


def _document_text(doc: SourceDoc) -> str:
    """제목+요약을 인용 가능한 본문으로. 둘 다 없으면 빈 문자열(인용 대상 없음)."""
    return "\n\n".join(part for part in (doc.title, doc.summary) if part)


def _build_documents(docs: Sequence[SourceDoc]) -> list[dict[str, Any]]:
    """패스 1 user content의 document 블록들(citations 활성). 순서가 document_index가 된다."""
    return [
        {
            "type": "document",
            "source": {"type": "text", "media_type": "text/plain", "data": _document_text(doc)},
            "title": doc.title or f"document {doc.raw_document_id}",
            "citations": {"enabled": True},
        }
        for doc in docs
    ]


def parse_pass1(
    content: Iterable[Any], sent_docs: Sequence[SourceDoc]
) -> tuple[str, list[CitedSpan]]:
    """패스 1 응답(content 블록들) → (분석 텍스트, 인용 범위들) (순수).

    cited 블록의 citations 배열에서 document_index로 sent_docs를 역참조해 raw_document_id·
    발행시각을 붙인다. sent_docs는 _build_documents에 넘긴 것과 같은 순서여야 한다(index 매핑).
    SDK 타입에 묶이지 않게 getattr로 방어적 접근 — 테스트는 더미 객체로 검증.
    """
    texts: list[str] = []
    citations: list[CitedSpan] = []
    for block in content:
        if getattr(block, "type", None) != "text":
            continue
        texts.append(getattr(block, "text", "") or "")
        for cite in getattr(block, "citations", None) or []:
            idx = getattr(cite, "document_index", None)
            if idx is None or idx < 0 or idx >= len(sent_docs):
                continue
            src = sent_docs[idx]
            citations.append(
                CitedSpan(
                    raw_document_id=src.raw_document_id,
                    cited_text=getattr(cite, "cited_text", "") or "",
                    char_start=getattr(cite, "start_char_index", None),
                    char_end=getattr(cite, "end_char_index", None),
                    source_published_at=src.published_at,
                )
            )
    return "".join(texts).strip(), citations


def _pass2_input(analysis_text: str, citations: Sequence[CitedSpan]) -> str:
    """패스 2 입력(무결성 규칙): 패스1 분석 텍스트 + 실제 인용 범위만. 원문 문서는 주지 않는다."""
    spans = "\n".join(f"- {c.cited_text}" for c in citations)
    return f"[분석]\n{analysis_text}\n\n[인용된 근거]\n{spans}"


def _first_text(content: Iterable[Any]) -> str:
    """content 블록들에서 첫 text 블록의 텍스트(없으면 빈 문자열)."""
    for block in content:
        if getattr(block, "type", None) == "text":
            return getattr(block, "text", "") or ""
    return ""


def build_client(api_key: str) -> anthropic.Anthropic:
    """OS 인증서 저장소를 신뢰하는 Anthropic 클라이언트(사내 TLS 가로채기 대응; rss.py와 동일 경계)."""
    ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    return anthropic.Anthropic(api_key=api_key, http_client=DefaultHttpxClient(verify=ctx))


def anthropic_analyzer(client: anthropic.Anthropic, model: str) -> ImpactAnalyzer:
    """실 Anthropic 2-패스 분석기. API 장애·쿼터 시 None 반환(호출자 → status=degraded)."""

    def analyze(docs: Sequence[SourceDoc]) -> ImpactResult | None:
        sent = [doc for doc in docs if _document_text(doc)]
        if not sent:
            return None  # 인용할 본문이 없음
        try:
            pass1 = client.messages.create(
                model=model,
                max_tokens=4096,
                thinking={"type": "adaptive"},
                system=_PASS1_SYSTEM,
                messages=cast(
                    "list[MessageParam]",
                    [
                        {
                            "role": "user",
                            "content": [
                                *_build_documents(sent),
                                {"type": "text", "text": _PASS1_TASK},
                            ],
                        }
                    ],
                ),
            )
            analysis_text, citations = parse_pass1(pass1.content, sent)
            if not citations:
                # 근거 없음 — 환각으로 채우지 않는다(§10). analysis는 버린다.
                return ImpactResult("", [], None, None, None)
            pass2 = client.messages.create(
                model=model,
                max_tokens=1024,
                system=_PASS2_SYSTEM,
                output_config={"format": {"type": "json_schema", "schema": _PASS2_SCHEMA}},
                messages=[{"role": "user", "content": _pass2_input(analysis_text, citations)}],
            )
            data = json.loads(_first_text(pass2.content) or "{}")
            return ImpactResult(
                analysis_text=analysis_text,
                citations=citations,
                event_type=data.get("event_type"),
                direction=data.get("direction"),
                confidence=data.get("confidence"),
                impact_score=data.get("impact_score"),
            )
        except anthropic.APIError:
            return None  # 쿼터 소진·소스 다운·장애 → degraded

    return analyze
