from types import SimpleNamespace

from app.pipeline.impact import (
    ParsedCitation,
    build_document_blocks,
    build_pass2_prompt,
    parse_pass1,
    verify_citation,
)


def _text_block(text, citations=None):
    return SimpleNamespace(type="text", text=text, citations=citations)


def _char_cite(cited_text, document_index, start, end):
    return SimpleNamespace(
        type="char_location",
        cited_text=cited_text,
        document_index=document_index,
        start_char_index=start,
        end_char_index=end,
    )


def test_document_blocks_index_is_document_index() -> None:
    blocks = build_document_blocks(["첫 문서", "둘째 문서"])
    assert [b["source"]["data"] for b in blocks] == ["첫 문서", "둘째 문서"]
    assert all(b["citations"] == {"enabled": True} for b in blocks)
    assert all(b["source"]["media_type"] == "text/plain" for b in blocks)


def test_parse_pass1_assembles_text_and_char_citations() -> None:
    content = [
        _text_block("결론: "),
        _text_block("주가 상승 가능", citations=[_char_cite("실적 호조", 0, 5, 10)]),
    ]
    analysis, cites = parse_pass1(content)
    assert analysis == "결론: 주가 상승 가능"
    assert cites == [
        ParsedCitation(document_index=0, cited_text="실적 호조", start_char=5, end_char=10)
    ]


def test_parse_pass1_ignores_non_char_location_and_non_text() -> None:
    # page_location(다른 인용 타입)과 thinking 블록은 무시한다.
    page_cite = SimpleNamespace(type="page_location", cited_text="x", document_index=0)
    content = [
        SimpleNamespace(type="thinking", thinking="..."),
        _text_block("문장", citations=[page_cite]),
    ]
    analysis, cites = parse_pass1(content)
    assert analysis == "문장"
    assert cites == []


def test_verify_citation_swap_test() -> None:
    source = "0123456789실적 호조 발표"
    ok = ParsedCitation(document_index=0, cited_text="실적 호조", start_char=10, end_char=15)
    bad = ParsedCitation(document_index=0, cited_text="실적 호조", start_char=0, end_char=5)
    assert verify_citation(ok, source) is True
    assert verify_citation(bad, source) is False


def test_pass2_prompt_excludes_original_documents() -> None:
    # 무결성 규칙(§7): 패스2 입력은 패스1 분석문+인용문만. 원문 고유 텍스트가 새면 안 된다.
    analysis = "결론: 영향 긍정."
    cited = ["실적이 시장 예상을 상회"]
    secret_only_in_source = "내부 기밀 수치 12345"
    prompt = build_pass2_prompt(analysis, cited)
    assert analysis in prompt
    assert cited[0] in prompt
    assert secret_only_in_source not in prompt
