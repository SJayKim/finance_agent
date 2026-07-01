"""§7 일일 다이제스트 단위·통합 테스트.

순수 테스트(no DB): 가짜 Anthropic content 블록으로 디제스터의 2-패스 무결성 경계를
덮는다(test_citations.py의 가짜 블록 헬퍼 재사용). 실 Anthropic 호출은 없다.
DB 테스트(db 픽스처): build_digest의 빈 날·grounded·멱등·degraded 케이스를 실 Postgres로.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, timezone
from types import SimpleNamespace
from typing import Any, cast

import anthropic
import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.models import BriefItem, Citation, Cluster, DailyDigest, DigestSource, RawDocument, Source
from app.pipeline.citations import CitedSpan
from app.pipeline.digest import (
    DigestInput,
    DigestSection,
    _pass2_input,
    anthropic_digester,
    build_digest,
    parse_pass1,
)

_PUB = datetime(2026, 6, 20, 12, tzinfo=timezone.utc)
_BRIEF_DATE = date(2026, 6, 20)


# ----------------------------------------------------------------------------
# 가짜 블록 헬퍼 (test_citations.py와 동형) — SDK 응답을 SimpleNamespace로 흉내.
# ----------------------------------------------------------------------------
def _span(doc_id: int, cited_text: str) -> CitedSpan:
    return CitedSpan(
        raw_document_id=doc_id,
        cited_text=cited_text,
        char_start=0,
        char_end=len(cited_text),
        source_published_at=_PUB,
    )


def _input(
    brief_item_id: int, cited_texts: list[str], analysis: str = "uncited analysis"
) -> DigestInput:
    return DigestInput(
        brief_item_id=brief_item_id,
        analysis_text=analysis,
        citations=[_span(brief_item_id * 10, t) for t in cited_texts],
    )


def _cite(document_index: int, cited_text: str, start: int = 0, end: int = 5) -> SimpleNamespace:
    return SimpleNamespace(
        type="char_location",
        document_index=document_index,
        cited_text=cited_text,
        start_char_index=start,
        end_char_index=end,
    )


def _text_block(text: str, citations: list[SimpleNamespace] | None = None) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text, citations=citations)


def _fake_client(responses: list[Any]) -> tuple[anthropic.Anthropic, list[dict[str, Any]]]:
    calls: list[dict[str, Any]] = []

    def create(**kwargs: Any) -> Any:
        calls.append(kwargs)
        return responses.pop(0)

    client = SimpleNamespace(messages=SimpleNamespace(create=create))
    return cast(anthropic.Anthropic, client), calls


# ----------------------------------------------------------------------------
# 순수 테스트 (no DB)
# ----------------------------------------------------------------------------
def test_pass2_input_excludes_uncited_text() -> None:
    """무결성 규칙(§7): 패스 2 입력에는 cited_text만, 인용 안 된 brief_item 텍스트는 없어야."""
    sent = [_input(1, ["only this span"], analysis="SECRET UNCITED ANALYSIS")]
    _, citations, _ = parse_pass1([_text_block("a", [_cite(0, "only this span")])], sent)
    payload = _pass2_input("analysis here", citations)
    assert "only this span" in payload
    assert "SECRET UNCITED ANALYSIS" not in payload


def test_digester_rejects_when_zero_citations() -> None:
    """패스1이 인용 0건이면 디제스터는 [](빈 다이제스트) 반환 — 패스2 호출 안 함."""
    pass1 = SimpleNamespace(content=[_text_block("ungrounded macro narration", citations=None)])
    client, calls = _fake_client([pass1])
    result = anthropic_digester(client, "claude-opus-4-8")([_input(1, ["some evidence"])])
    assert result == []
    assert len(calls) == 1  # 패스2 미호출


def test_digester_maps_document_index_to_brief_item() -> None:
    """document_index → brief_item_id 역추적 + 패스2 섹션에 인용·근거 부착(충실 폴백)."""
    pass1 = SimpleNamespace(
        content=[
            _text_block("Theme A. ", [_cite(0, "evidence from item one")]),
            _text_block("Theme B.", [_cite(1, "evidence from item two")]),
        ]
    )
    pass2 = SimpleNamespace(
        content=[
            _text_block(
                '{"sections": [{"section": "macro", "heading": "금리", '
                '"body_text": "긍정 요인으로 분류"}]}'
            )
        ]
    )
    client, calls = _fake_client([pass1, pass2])
    sections = anthropic_digester(client, "m")([_input(11, ["a"]), _input(22, ["b"])])
    assert sections is not None and len(sections) == 1
    sec = sections[0]
    assert sec.section == "macro"
    assert [c.cited_text for c in sec.citations] == [
        "evidence from item one",
        "evidence from item two",
    ]
    assert sec.source_brief_item_ids == [11, 22]
    assert len(calls) == 2


def test_digester_merges_duplicate_section_keys() -> None:
    """같은 section 키(예: 크립토 일색인 날 macro 두 개)는 하나로 합친다 — uq 위반 방지, 첫 heading 유지."""
    pass1 = SimpleNamespace(content=[_text_block("Theme.", [_cite(0, "evidence one")])])
    pass2 = SimpleNamespace(
        content=[
            _text_block(
                '{"sections": ['
                '{"section": "macro", "heading": "금리", "body_text": "첫째 테마"},'
                '{"section": "macro", "heading": "환율", "body_text": "둘째 테마"}'
                "]}"
            )
        ]
    )
    client, _ = _fake_client([pass1, pass2])
    sections = anthropic_digester(client, "m")([_input(1, ["a"])])
    assert sections is not None and len(sections) == 1
    sec = sections[0]
    assert sec.section == "macro"
    assert sec.heading == "금리"  # 첫 heading 유지
    assert "첫째 테마" in sec.body_text and "둘째 테마" in sec.body_text  # body 합쳐짐


def test_digester_returns_none_on_malformed_json() -> None:
    """패스2 JSON이 잘리거나(토큰 한도) 깨지면 None(degraded) — build_digest를 크래시시키지 않는다."""
    pass1 = SimpleNamespace(content=[_text_block("Theme.", [_cite(0, "evidence one")])])
    # max_tokens에서 잘린 JSON: 문자열이 닫히지 않음(실측 Unterminated string 회귀).
    pass2 = SimpleNamespace(content=[_text_block('{"sections": [{"section": "macro", "body_text": "잘린')])
    client, _ = _fake_client([pass1, pass2])
    assert anthropic_digester(client, "m")([_input(1, ["a"])]) is None


def test_digester_returns_none_on_api_error() -> None:
    def create(**kwargs: Any) -> Any:
        raise anthropic.APIConnectionError(request=httpx.Request("POST", "https://api"))

    client = cast(anthropic.Anthropic, SimpleNamespace(messages=SimpleNamespace(create=create)))
    assert anthropic_digester(client, "m")([_input(1, ["x"])]) is None


def test_digester_returns_none_on_truncated_json() -> None:
    """패스2 구조화 JSON이 max_tokens로 잘려 오면 크래시 대신 None(→degraded).

    회귀: 잘린 JSON의 json.JSONDecodeError(APIError 아님)가 안 잡혀 build_digest→daily_run
    전체가 죽던 버그(2026-06-26 오늘 수집 실행 중단).
    """
    pass1 = SimpleNamespace(content=[_text_block("Theme.", [_cite(0, "evidence")])])
    # 닫히지 않은 문자열 — json.loads가 JSONDecodeError를 던진다(잘린 응답 모사).
    pass2 = SimpleNamespace(
        content=[_text_block('{"sections": [{"section": "macro", "heading": "금리 인')]
    )
    client, _ = _fake_client([pass1, pass2])
    assert anthropic_digester(client, "m")([_input(1, ["a"])]) is None


# ----------------------------------------------------------------------------
# DB 테스트 (db 픽스처; 오케스트레이터가 직렬 실행)
# ----------------------------------------------------------------------------
def _seed_ok_items(db: sessionmaker, count: int = 2) -> list[int]:
    """그날 status=ok brief_items + citations 적재. brief_item_id 목록 반환."""
    ids: list[int] = []
    with db() as s:
        src = Source(name="test-src", kind="news")
        s.add(src)
        s.flush()
        for i in range(count):
            doc = RawDocument(
                source_id=src.id,
                external_id=f"d{i}",
                title=f"Headline {i}",
                published_at=_PUB,
            )
            s.add(doc)
            s.flush()
            cl = Cluster(brief_date=_BRIEF_DATE, representative_doc_id=doc.id)
            s.add(cl)
            s.flush()
            item = BriefItem(
                brief_date=_BRIEF_DATE,
                cluster_id=cl.id,
                status="ok",
                analysis_text=f"impact {i}",
                event_type="price_move",
                direction="긍정",
                confidence="MED",
            )
            s.add(item)
            s.flush()
            s.add(
                Citation(
                    brief_item_id=item.id,
                    raw_document_id=doc.id,
                    cited_text=f"cited evidence {i}",
                    char_start=0,
                    char_end=5,
                    source_published_at=_PUB,
                )
            )
            ids.append(item.id)
        s.commit()
    return ids


def _grounded_digester(source_ids: Sequence[int]) -> object:
    """가짜 디제스터: 그날 입력의 인용을 묶어 1개 macro 섹션을 돌려준다(네트워크 없이)."""

    def digest(inputs: Sequence[DigestInput]) -> list[DigestSection] | None:
        cites = [c for inp in inputs for c in inp.citations]
        return [
            DigestSection(
                section="macro",
                heading="금리 인하 기대",
                body_text="긍정 요인으로 분류된 근거 집계",
                citations=list(cites),
                source_brief_item_ids=[inp.brief_item_id for inp in inputs],
            )
        ]

    return digest


def test_build_digest_empty_day_writes_empty(db: sessionmaker) -> None:
    with db() as s:
        build_digest(s, _BRIEF_DATE, digester=lambda inputs: [])  # digester는 안 불릴 것
        s.commit()
    with db() as s:
        rows = s.execute(select(DailyDigest)).scalars().all()
        assert len(rows) == 1
        assert rows[0].section == "macro"
        assert rows[0].status == "empty"
        assert rows[0].heading is None
        assert rows[0].body_text == "오늘은 추적 가능한 근거가 없습니다."
        assert s.execute(select(func.count()).select_from(DigestSource)).scalar_one() == 0


def test_build_digest_grounded_writes_sections_and_sources(db: sessionmaker) -> None:
    ids = _seed_ok_items(db, count=2)
    with db() as s:
        build_digest(s, _BRIEF_DATE, digester=cast(Any, _grounded_digester(ids)))
        s.commit()
    with db() as s:
        rows = s.execute(select(DailyDigest)).scalars().all()
        assert len(rows) == 1
        assert all(r.status == "ok" for r in rows)
        sources = s.execute(select(DigestSource)).scalars().all()
        assert {src.brief_item_id for src in sources} == set(ids)
        # swap-test 정신: 모든 근거 brief_item이 이 brief_date 소속이어야 한다.
        for src in sources:
            owner_date = s.execute(
                select(BriefItem.brief_date).where(BriefItem.id == src.brief_item_id)
            ).scalar_one()
            assert owner_date == _BRIEF_DATE


def test_build_digest_is_idempotent(db: sessionmaker) -> None:
    ids = _seed_ok_items(db, count=2)
    with db() as s:
        build_digest(s, _BRIEF_DATE, digester=cast(Any, _grounded_digester(ids)))
        s.commit()
    with db() as s:
        build_digest(s, _BRIEF_DATE, digester=cast(Any, _grounded_digester(ids)))  # 재실행
        s.commit()
    with db() as s:
        digests = s.execute(select(func.count()).select_from(DailyDigest)).scalar_one()
        sources = s.execute(select(func.count()).select_from(DigestSource)).scalar_one()
    assert digests == 1  # uq_daily_digests_date_section 유지, 중복 없음
    assert sources == 2


def test_build_digest_merges_duplicate_section_keys(db: sessionmaker) -> None:
    """디제스터가 같은 section 키를 여러 번 내도 uq_daily_digests_date_section 위반 없이 1행으로 병합.

    회귀: LLM 패스2가 'macro'를 두 섹션으로 쪼개 반환 → 중복 키 INSERT가 UniqueViolation으로
    daily_run을 죽이던 버그(2026-06-26).
    """
    ids = _seed_ok_items(db, count=2)

    def dup_digester(inputs: Sequence[DigestInput]) -> list[DigestSection]:
        cites = [c for inp in inputs for c in inp.citations]
        sids = [inp.brief_item_id for inp in inputs]
        return [
            DigestSection(
                section="macro",
                heading="A",
                body_text="첫째",
                citations=cites,
                source_brief_item_ids=sids,
            ),
            DigestSection(
                section="macro",
                heading="B",
                body_text="둘째",
                citations=cites,
                source_brief_item_ids=sids,
            ),
        ]

    with db() as s:
        build_digest(s, _BRIEF_DATE, digester=cast(Any, dup_digester))
        s.commit()
    with db() as s:
        rows = s.execute(select(DailyDigest).where(DailyDigest.section == "macro")).scalars().all()
        assert len(rows) == 1  # 두 'macro' 섹션이 1행으로 병합
        assert "첫째" in rows[0].body_text and "둘째" in rows[0].body_text
        sources = s.execute(select(DigestSource)).scalars().all()
        assert {src.brief_item_id for src in sources} == set(ids)  # 근거 중복 없이 합집합


def test_build_digest_degraded_when_no_digester(db: sessionmaker) -> None:
    _seed_ok_items(db, count=1)
    with db() as s:
        build_digest(s, _BRIEF_DATE, digester=None)
        s.commit()
    with db() as s:
        rows = s.execute(select(DailyDigest)).scalars().all()
        assert len(rows) == 1
        assert rows[0].section == "macro"
        assert rows[0].status == "degraded"
