"""§7 일일 다이제스트 생성 (STAGE1.5_DESIGN §4 트랙 C + §7).

D1(가장 엄격한 컴플라이언스): 다이제스트는 **합성이 아니라 집계**다. 그날
status=ok brief_items의 인용 근거(cited_text)만 입력으로 보고, 거시 테마·영향 섹터
축으로 요약한다. 자유로운 LLM 거시 전망은 금지(§2 프리미스 1). 모든 문장은
brief_item → citation으로 역추적된다(digest_sources).

citations.py의 2-패스 경계를 그대로 재사용한다:
- 패스 1 (Citations API): 그날 brief_item들의 cited_text를 인용 가능한 document 블록으로
  먹여 "거시 테마 / 영향 섹터 후보" 문장을 인용 강제로 생성. document_index로 어느
  brief_item에서 나왔는지 역추적한다.
- 패스 2 (Structured Outputs): **입력은 패스1 텍스트 + 인용 span만**(무결성 규칙 §7) —
  원문 brief_item 분석 텍스트를 인용 범위 밖으로 더 주지 않는다. section/heading/body로
  재구조화만 한다.

거부 규칙: 인용 0 → 빈 다이제스트(정직, §10 null-evidence). 환각으로 채우지 않는다.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any, cast

import anthropic
from anthropic.types import MessageParam
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import BriefItem, Citation, DailyDigest, DigestSource
from app.pipeline.citations import CitedSpan

_EMPTY_BODY = "오늘은 추적 가능한 근거가 없습니다."
_DEGRADED_BODY = "다이제스트 생성기를 사용할 수 없어 오늘 요약을 만들지 못했습니다."


@dataclass(frozen=True)
class DigestInput:
    """패스 1에 먹이는 그날 ok brief_item 하나. cited_text 모음이 인용 가능한 ground truth."""

    brief_item_id: int
    analysis_text: str | None
    citations: Sequence[CitedSpan]


@dataclass(frozen=True)
class DigestSection:
    """다이제스트 한 섹션. body_text의 모든 주장은 citations·source_brief_item_ids로 역추적."""

    section: str  # 'macro' | 'sector:<섹터명>'
    heading: str | None
    body_text: str
    citations: list[CitedSpan] = field(default_factory=list)
    source_brief_item_ids: list[int] = field(default_factory=list)


# build_digest가 주입받는 I/O 경계. 키 없으면 None(=비활성) 주입 가능 → degraded.
Digester = Callable[[Sequence[DigestInput]], list[DigestSection] | None]


_PASS1_SYSTEM = (
    "너는 증권 리서치 데스크의 일일 다이제스트 편집자다. 오늘 수집·분석된 뉴스 근거만 "
    "사용해, 그날의 증거를 거시 테마와 영향 섹터 후보 축으로 집계·요약한다. 모든 주장은 "
    "제공된 문서 인용으로 뒷받침하라. 인용으로 뒷받침할 수 없는 주장·수치·전망은 절대 쓰지 "
    "마라. 이것은 투자 권유가 아니라 뉴스 기준 영향도 집계다. "
    "금지 표현: '매수', '상승 전망', '목표가', 매도/매수 의견. "
    "허용 표현: '주목 섹터 후보', '긍정 요인으로 분류', '영향 가능성'. "
    "오늘 근거 밖의 거시 전망을 자유 서술하지 마라."
)
_PASS1_TASK = "오늘 수집된 근거를 거시 테마와 영향 섹터 후보로 집계·요약하라."

_PASS2_SYSTEM = (
    "너는 1차 다이제스트 분석을 거시/섹터 섹션으로 구조화한다. 아래 분석 텍스트와 인용된 "
    "근거만 사용하고, 새 사실·수치·종목·전망을 도입하지 마라. 재구조화만 한다. section은 "
    "거시는 'macro', 섹터는 'sector:<섹터명>' 형식으로 쓴다."
)

_PASS2_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "section": {"type": "string"},  # 'macro' | 'sector:<name>'
                    "heading": {"type": "string"},
                    "body_text": {"type": "string"},
                },
                "required": ["section", "heading", "body_text"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["sections"],
    "additionalProperties": False,
}


def _input_text(inp: DigestInput) -> str:
    """패스 1에 인용 가능한 본문으로 쓸 cited_text 모음. 비면 빈 문자열(인용 대상 없음)."""
    return "\n\n".join(c.cited_text for c in inp.citations if c.cited_text)


def _build_documents(inputs: Sequence[DigestInput]) -> list[dict[str, Any]]:
    """패스 1 user content의 document 블록들(citations 활성). 순서가 document_index가 된다.

    여기서 "문서"는 brief_item별 cited_text 모음(이미 zero-fabrication ground truth) —
    citations.py._build_documents와 같은 형태지만 데이터 출처가 다르다. inputs 순서가 곧
    parse_pass1이 document_index로 역참조할 매핑이다.
    """
    return [
        {
            "type": "document",
            "source": {"type": "text", "media_type": "text/plain", "data": _input_text(inp)},
            "title": f"brief_item {inp.brief_item_id}",
            "citations": {"enabled": True},
        }
        for inp in inputs
    ]


def parse_pass1(
    content: Any, sent_inputs: Sequence[DigestInput]
) -> tuple[str, list[CitedSpan], list[int]]:
    """패스 1 응답 → (분석 텍스트, 인용 범위들, 근거 brief_item_id들) (순수).

    cited 블록의 document_index로 sent_inputs를 역참조해 raw_document_id·발행시각을 붙이고,
    어느 brief_item에서 나왔는지(source_brief_item_ids)를 등장 순서대로 중복 없이 모은다.
    sent_inputs는 _build_documents에 넘긴 것과 같은 순서여야 한다(index 매핑).
    SDK 타입에 묶이지 않게 getattr로 방어적 접근 — 테스트는 더미 객체로 검증.
    """
    texts: list[str] = []
    citations: list[CitedSpan] = []
    source_ids: list[int] = []
    for block in content:
        if getattr(block, "type", None) != "text":
            continue
        texts.append(getattr(block, "text", "") or "")
        for cite in getattr(block, "citations", None) or []:
            idx = getattr(cite, "document_index", None)
            if idx is None or idx < 0 or idx >= len(sent_inputs):
                continue
            src = sent_inputs[idx]
            cited_text = getattr(cite, "cited_text", "") or ""
            # cited_text는 패스1이 실제 인용한 span. raw_document_id는 그 span을 담은
            # brief_item의 첫 citation에서 가져온다(span 자체가 ground truth라 충분).
            ref = src.citations[0] if src.citations else None
            citations.append(
                CitedSpan(
                    raw_document_id=ref.raw_document_id if ref else 0,
                    cited_text=cited_text,
                    char_start=getattr(cite, "start_char_index", None),
                    char_end=getattr(cite, "end_char_index", None),
                    source_published_at=ref.source_published_at if ref else None,
                )
            )
            if src.brief_item_id not in source_ids:
                source_ids.append(src.brief_item_id)
    return "".join(texts).strip(), citations, source_ids


def _pass2_input(analysis_text: str, citations: Sequence[CitedSpan]) -> str:
    """패스 2 입력(무결성 규칙): 패스1 분석 텍스트 + 실제 인용 범위만. 원문 문서는 주지 않는다."""
    spans = "\n".join(f"- {c.cited_text}" for c in citations)
    return f"[분석]\n{analysis_text}\n\n[인용된 근거]\n{spans}"


def _first_text(content: Any) -> str:
    """content 블록들에서 첫 text 블록의 텍스트(없으면 빈 문자열)."""
    for block in content:
        if getattr(block, "type", None) == "text":
            return getattr(block, "text", "") or ""
    return ""


def anthropic_digester(client: anthropic.Anthropic, model: str) -> Digester:
    """실 Anthropic 2-패스 다이제스트 생성기. API 장애·쿼터 시 None(호출자 → degraded)."""

    def digest(inputs: Sequence[DigestInput]) -> list[DigestSection] | None:
        sent = [inp for inp in inputs if _input_text(inp)]
        if not sent:
            return []  # 인용할 본문이 없음 → 빈 다이제스트
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
            analysis_text, citations, source_ids = parse_pass1(pass1.content, sent)
            if not citations:
                # 근거 없음 — 환각으로 채우지 않는다(§10). 빈 다이제스트.
                return []
            pass2 = client.messages.create(
                model=model,
                max_tokens=2048,
                system=_PASS2_SYSTEM,
                output_config={"format": {"type": "json_schema", "schema": _PASS2_SCHEMA}},
                messages=[{"role": "user", "content": _pass2_input(analysis_text, citations)}],
            )
            data = json.loads(_first_text(pass2.content) or "{}")
            sections: list[DigestSection] = []
            for raw in data.get("sections") or []:
                section = raw.get("section")
                body_text = raw.get("body_text")
                if not section or not body_text:
                    continue
                # 판단: 패스2는 패스1 텍스트+인용만 보고 섹션을 나누므로 인용을 섹션별로
                # 깔끔히 분배하지 못한다. 충실·안전하게 패스1의 전체 인용 + 전체 근거
                # brief_item을 각 섹션에 붙인다(섹션별 인용 귀속을 지어내지 않음). 모든
                # 섹션은 그날 실제 인용 집합 안에 있으므로 zero-fabrication 경계는 유지된다.
                sections.append(
                    DigestSection(
                        section=section,
                        heading=raw.get("heading"),
                        body_text=body_text,
                        citations=list(citations),
                        source_brief_item_ids=list(source_ids),
                    )
                )
            return sections
        except anthropic.APIError:
            return None  # 쿼터 소진·장애 → degraded

    return digest


def _ok_inputs(session: Session, brief_date: date) -> list[DigestInput]:
    """그날 status=ok brief_items + 그 citations를 패스1 입력(DigestInput)으로.

    이 집합이 다이제스트의 유일한 입력이다(D1: 외부 지식·자유 거시 전망 없음).
    """
    items = (
        session.execute(
            select(BriefItem).where(BriefItem.brief_date == brief_date, BriefItem.status == "ok")
        )
        .scalars()
        .all()
    )
    inputs: list[DigestInput] = []
    for item in items:
        rows = (
            session.execute(select(Citation).where(Citation.brief_item_id == item.id))
            .scalars()
            .all()
        )
        spans = [
            CitedSpan(
                raw_document_id=c.raw_document_id,
                cited_text=c.cited_text,
                char_start=c.char_start,
                char_end=c.char_end,
                source_published_at=c.source_published_at,
            )
            for c in rows
        ]
        inputs.append(
            DigestInput(brief_item_id=item.id, analysis_text=item.analysis_text, citations=spans)
        )
    return inputs


def _clear_existing(session: Session, brief_date: date) -> None:
    """그날 기존 다이제스트(+digest_sources 자식)를 지운다. 재실행 멱등의 선결 단계."""
    ids = (
        session.execute(select(DailyDigest.id).where(DailyDigest.brief_date == brief_date))
        .scalars()
        .all()
    )
    if ids:
        session.execute(delete(DigestSource).where(DigestSource.digest_id.in_(ids)))
        session.execute(delete(DailyDigest).where(DailyDigest.id.in_(ids)))
    # 후속 INSERT가 uq_daily_digests_date_section에서 기존 행과 충돌하지 않도록 flush.
    session.flush()


def build_digest(session: Session, brief_date: date, digester: Digester | None = None) -> None:
    """그날 ok brief_items를 거시·섹터 다이제스트로 집계 (§7 grounding 계약). 커밋은 호출자.

    멱등: 매 실행마다 그날 기존 다이제스트를 지우고 새로 쓴다(재실행이 그날 다이제스트를
    깨끗이 교체). 빈 날·생성기 부재·인용 0은 환각으로 채우지 않는다(정직).
    - ok brief_item 0건 → macro 1행 status=empty(정직한 빈 다이제스트). digest_sources 없음.
    - digester None(키 없음/오프라인) → macro 1행 status=degraded.
    - digester None 반환(API 장애) → macro 1행 status=degraded.
    - 정상: 반환된 섹션마다 DailyDigest(status=ok) + digest_sources(근거 brief_item 역추적).
      인용 0 섹션은 건너뛴다(zero-fabrication).
    """
    _clear_existing(session, brief_date)

    inputs = _ok_inputs(session, brief_date)
    if not inputs:
        session.add(
            DailyDigest(
                brief_date=brief_date,
                section="macro",
                heading=None,
                body_text=_EMPTY_BODY,
                status="empty",
            )
        )
        return

    if digester is None:
        session.add(
            DailyDigest(
                brief_date=brief_date,
                section="macro",
                heading=None,
                body_text=_DEGRADED_BODY,
                status="degraded",
            )
        )
        return

    sections = digester(inputs)
    if sections is None:
        session.add(
            DailyDigest(
                brief_date=brief_date,
                section="macro",
                heading=None,
                body_text=_DEGRADED_BODY,
                status="degraded",
            )
        )
        return

    if not sections:
        # 인용 가능한 근거가 없어 빈 다이제스트(정직, §10).
        session.add(
            DailyDigest(
                brief_date=brief_date,
                section="macro",
                heading=None,
                body_text=_EMPTY_BODY,
                status="empty",
            )
        )
        return

    for sec in sections:
        if not sec.citations:
            continue  # 인용 0 섹션은 쓰지 않는다(zero-fabrication).
        digest_row = DailyDigest(
            brief_date=brief_date,
            section=sec.section,
            heading=sec.heading,
            body_text=sec.body_text,
            status="ok",
        )
        session.add(digest_row)
        session.flush()  # digest_row.id 확보 후 근거 링크 적재
        session.add_all(
            DigestSource(digest_id=digest_row.id, brief_item_id=bid)
            for bid in dict.fromkeys(sec.source_brief_item_ids)
        )
