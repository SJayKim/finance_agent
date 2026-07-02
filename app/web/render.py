"""브리프 분석 본문 렌더 (마크다운 → 안전한 HTML, 대시보드 Jinja 필터)."""

from __future__ import annotations

import markdown
from markupsafe import Markup, escape


def analysis_html(text: str) -> Markup:
    """LLM 분석 마크다운(#·**·리스트)을 이스케이프 후 HTML로 변환 (XSS 안전).

    LLM 출력은 신뢰하지 않는다 — escape()가 원시 HTML을 먼저 엔티티로 바꾸므로 변환
    결과에 LLM발 태그가 살아남지 않는다. 마크다운 문법 문자(#, **, -)는 HTML
    특수문자가 아니라 이스케이프의 영향을 받지 않는다.

    nl2br: LLM은 빈 줄 없이 문단에 붙은 리스트를 자주 쓰는데 python-markdown은 이를
    리스트로 안 본다(문단으로 합쳐 한 줄로 흐름) — 단일 개행을 <br>로 살려 이전
    pre-wrap 표시와 같은 줄 단위 가독성을 유지한다(채팅 UI들의 통상 동작).
    """
    return Markup(markdown.markdown(str(escape(text)), extensions=["nl2br"]))
