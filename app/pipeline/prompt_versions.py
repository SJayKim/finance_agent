"""프롬프트 버전 레지스트리 — 비교 실험 전용(scripts/compare_providers.py, 플랜 10).

운영 경로는 이 모듈을 import하지 않는다: citations.py/openai_citations.py의 모듈 상수가
기본값이고, 여기의 "v0"은 그 상수를 그대로 참조한다(항등 — 테스트가 `is`로 증명).
버전 설계 근거는 docs/plans/10 Research notes 절(문헌·공식 가이드 조사) 참조.

모든 버전 공통 불변식(테스트 강제): "0~100" 범위 명시(Anthropic structured output이
integer min/max 미지원이라 범위는 프롬프트가 유일한 강제 수단), direction 무부호 규칙,
OpenAI 버전은 인용(citations) 범위 제약 + 인용문 원문 복사 메커니즘(verify_quotes 전제).

버전 요약(적용 모델은 docs/plans/10 매트릭스):
- v1  앵커 밴드 루브릭 — 루브릭 구체성이 점수 레벨을 직접 이동(arXiv:2503.23989)
- v2  v1 + 분해 판정(범위/신규성/정량성) + 등급 연동 상한 — judge 불변성(Prosa 2605.01630)
- v3  v1 + few-shot 캘리브레이션(Opus 덤프 기반) — Run 0 이후 추가
- v4  구조화 근거 등급화 후 점수(밴드 없음 — 효과 분리)
- v5  confidence 체크 조건 + 스텁 상한(밴드 없음 — 효과 분리)
- v6  GPT 특화: XML 블록 계약(instruction_priority/citation_rules/verification_loop)
- v7  GPT 특화: v1 + 반(反)관대함 셀프 비평 + HIGH 페널티 프레이밍
- v8  Claude 특화: XML 구조화 PASS1+PASS2(루브릭+confidence 태그)
- v9  Sonnet 콤보: v2+v5 — V0-sonnet 드리프트 시에만 실행
"""

from __future__ import annotations

from dataclasses import dataclass

from app.pipeline.citations import _PASS1_SYSTEM, _PASS2_SYSTEM
from app.pipeline.openai_citations import _SYSTEM


@dataclass(frozen=True)
class AnthropicPrompts:
    """2-패스(citations.py) 프롬프트 세트."""

    pass1_system: str
    pass2_system: str


@dataclass(frozen=True)
class OpenAIPrompts:
    """단일 콜(openai_citations.py) 프롬프트 세트."""

    system: str


# --- 공용 조각(한국어 텍스트는 두 프로바이더 동일 — 기법 효과만 분리 측정) ---

_BANDS = (
    " 점수 밴드: 0~20 루틴/거래 신호 없음(정량 정보 없는 헤드라인, 본문 없는 링크 모음, 예정된"
    " 일정의 재확인) · 21~40 단일 종목 소폭 영향(일상적 계약, 인라인 실적, 소규모 제품 뉴스)"
    " · 41~60 단일 종목 대형 영향 또는 섹터 파급(어닝 서프라이즈, 대형 수주, 구체적 규제 결정)"
    " · 61~80 섹터/지수 수준 재평가(하루 피드에 드묾 — 예상 밖 정책 결정, 초대형 M&A)"
    " · 81~100 시장 전체 체제 이벤트(연중 몇 건 — 시스템 리스크급 충격)."
    " 두 밴드 사이에서 망설여지면 낮은 밴드를 선택하라."
)

_DECOMP = (
    " 점수 확정 전 세 판정을 내려라: (a) 범위 — 단일 종목/섹터/시장 전체 중 어디에 영향인가,"
    " (b) 신규성 — 이미 알려진 정보의 재확인인가 새 정보인가, (c) 정량성 — 규모를 말하는 수치가"
    " 인용문에 있는가. 상한 규칙: 정량 수치 인용이 없으면 40 이하, 재확인 성격이면 30 이하,"
    " 범위가 단일 종목이면 60 이하, 섹터 수준이면 80 이하. 점수는 세 판정과 모순되면 안 된다."
)

_CONF_RULES = (
    " confidence 판정 규칙: HIGH는 서로 다른 문서 2개 이상이 정량 수치를 교차 확인하고 영향"
    " 대상이 직접 명시된 경우에만. MED는 단일 문서의 구체적·정량적 정보. 그 외 — 헤드라인 수준"
    " 정보, 정량 수치 부재, 문서 간 불일치, 본문 없는 링크 모음 — 는 LOW."
)

_STUB_RULE = " 스텁 규칙: 문서들이 제목뿐이거나 정량 정보가 전혀 없으면 impact_score 30 이하, confidence LOW."

_COUNTER_LENIENCY = (
    " 점수 확정 전 반문하라: 이 점수가 한 밴드 낮아야 한다는 주장에 어떤 근거가 있는가. 그"
    " 주장을 인용 근거로 반박할 수 있을 때만 현재 밴드를 유지하고, 아니면 한 밴드 낮춰라."
    " confidence HIGH는 direction과 점수 밴드가 재검토에서 그대로 유지된다고 90% 이상 확신할"
    " 때만 부여하라 — 잘못된 HIGH의 비용은 잘못된 LOW의 9배다."
)

# --- Anthropic 조립 조각: v0 PASS2에서 모호한 강도 문장("약하면 낮게…")을 밴드/규칙으로
# 대체한다(모순 지시 감사 — GPT-5 가이드; Claude 4.6+ 문자적 해석 — 포괄 보수화 지시 금지). ---

_AN_PASS2_CORE = (
    "너는 1차 영향도 분석을 구조화한다. 아래 분석 텍스트와 인용된 근거만 사용하고, 새 사실·"
    "수치·종목을 도입하지 마라. 재구조화만 한다. impact_score는 이 이벤트가 영향 종목에 주는 "
    "임팩트의 크기(부호 없음)를 0~100으로 매긴다 — 인용된 근거가 시사하는 강도만 반영하고, "
    "방향(상승/하락)은 direction이 따로 표현하므로 점수에 부호를 넣지 마라."
)
_AN_TAIL = " 근거로 뒷받침 안 되는 값은 쓰지 마라."

_AN_V4_PASS1 = _PASS1_SYSTEM + (
    " 분석 마지막에 근거 등급 요약을 명시하라: 각 인용의 강도(강/약), 영향 범위(단일 종목/"
    "섹터/시장 전체), 신규성(재확인/새 정보), 정량성(규모 수치 유무)."
)
_AN_V4_PASS2 = (
    _AN_PASS2_CORE
    + " 분석 텍스트의 근거 등급 요약에서 impact_score를 도출하라 — 등급 판정과 모순되는 점수는"
    " 쓰지 마라. 확정 전 점수와 판정을 대조 검증하라." + _AN_TAIL
)

_AN_V8_PASS1 = (
    "<role>증권 애널리스트의 영향도 분석 보조.</role>\n"
    "<instructions>제공된 뉴스 문서만 근거로, 이 이벤트가 현재 시황에서 어떤 종목·섹터에 영향을"
    " 줄지 간결히 분석한다. 모든 주장은 문서 인용으로 뒷받침하라. 인용으로 뒷받침할 수 없는"
    " 주장·수치는 쓰지 마라. 이것은 투자 권유가 아니라 뉴스 기준 영향도 해석이다. 응답은"
    " 한국어로 작성한다.</instructions>"
)
_AN_V8_PASS2 = (
    "<role>1차 영향도 분석의 구조화 담당.</role>\n"
    "<instructions>아래 분석 텍스트와 인용된 근거만 사용하고, 새 사실·수치·종목을 도입하지"
    " 마라. 재구조화만 한다.</instructions>\n"
    "<scoring_rubric>impact_score는 이 이벤트가 영향 종목에 주는 임팩트의 크기(부호 없음)를"
    " 0~100으로 매긴다 — 인용된 근거가 시사하는 강도만 반영하고, 방향(상승/하락)은 direction이"
    " 따로 표현하므로 점수에 부호를 넣지 마라." + _BANDS + "</scoring_rubric>\n"
    "<confidence_rules>" + _CONF_RULES.strip() + _STUB_RULE + "</confidence_rules>\n"
    "<verification>점수 확정 전 인용된 근거와 밴드 정의를 대조 검증하라."
    + _AN_TAIL
    + "</verification>"
)

# --- OpenAI 조립 조각: v0 _SYSTEM에서 모호한 강도 문장을 뺀 베이스(인용 메커니즘·범위 제약은
# 전 버전 유지 — verify_quotes 전제). ---

_OA_CITE_MECHANICS = (
    " 모든 주장의 근거로 citations 배열에 인용문을 담아라. 각 인용문(quote)은 해당 문서"
    " 텍스트에서 그대로 복사한 연속된 문자열이어야 한다 — 의역·요약·여러 구절 조합 금지."
    " 원문에 없는 인용문은 검증에서 탈락한다."
)
_OA_SCORE_DEF = (
    " impact_score는 이 이벤트가 영향 종목에 주는 임팩트의 크기(부호 없음)를 0~100으로"
    " 매긴다 — 인용된 근거가 시사하는 강도만 반영하고, 방향(상승/하락)은 direction이 따로"
    " 표현하므로 점수에 부호를 넣지 마라."
)
_OA_SCOPE = (
    " direction·confidence·impact_score는 citations에 담은 인용문만 근거로 산출하라 —"
    " 인용하지 않은 문서 내용은 이 세 필드에 반영하지 마라. 인용문이 뒷받침하지 못하는 값은"
    " 쓰지 마라."
)
_OA_BASE = _PASS1_SYSTEM + _OA_CITE_MECHANICS + _OA_SCORE_DEF + _OA_SCOPE

_OA_V6 = (
    "<role>증권 애널리스트의 영향도 분석 보조. 제공된 뉴스 문서만 근거로 이 이벤트가 현재"
    " 시황에서 어떤 종목·섹터에 영향을 줄지 간결히 분석한다. 투자 권유가 아니라 뉴스 기준"
    " 영향도 해석이다.</role>\n"
    "<instruction_priority>규칙 충돌 시 우선순위: citation_rules > grounding_rules >"
    " scoring_rubric. 두 밴드 사이에서 망설여지면 낮은 밴드를 선택한다.</instruction_priority>\n"
    "<citation_rules>모든 주장의 근거로 citations 배열에 인용문을 담아라. 각 인용문(quote)은"
    " 해당 문서 텍스트에서 문자 단위로 그대로 복사한 연속된 문자열이어야 한다 — 의역·요약·여러"
    " 구절 조합 금지. 원문에 없는 인용문은 검증에서 탈락한다. 인용문은 그것이 뒷받침하는 주장에"
    " 붙여라. 인용문·URL·ID를 지어내지 마라.</citation_rules>\n"
    "<grounding_rules>direction·confidence·impact_score는 citations에 담은 인용문만 근거로"
    " 산출하라 — 인용하지 않은 문서 내용은 이 세 필드에 반영하지 마라. 인용문이 뒷받침하지"
    " 못하는 값은 쓰지 마라.</grounding_rules>\n"
    "<scoring_rubric>impact_score는 이 이벤트가 영향 종목에 주는 임팩트의 크기(부호 없음)를"
    " 0~100으로 매긴다. 방향(상승/하락)은 direction이 따로 표현하므로 점수에 부호를 넣지"
    " 마라." + _BANDS + "</scoring_rubric>\n"
    "<verification_loop>확정 전 검증: (1) 모든 수치·주장이 인용문으로 뒷받침되는가, (2)"
    " impact_score가 밴드 정의와 일치하는가, (3) 출력이 요구 스키마와 일치하는가. 하나라도"
    " 어긋나면 수정 후 출력하라.</verification_loop>"
)

ANTHROPIC_VERSIONS: dict[str, AnthropicPrompts] = {
    "v0": AnthropicPrompts(pass1_system=_PASS1_SYSTEM, pass2_system=_PASS2_SYSTEM),
    "v1": AnthropicPrompts(_PASS1_SYSTEM, _AN_PASS2_CORE + _BANDS + _AN_TAIL),
    "v2": AnthropicPrompts(_PASS1_SYSTEM, _AN_PASS2_CORE + _BANDS + _DECOMP + _AN_TAIL),
    "v4": AnthropicPrompts(_AN_V4_PASS1, _AN_V4_PASS2),
    "v5": AnthropicPrompts(_PASS1_SYSTEM, _AN_PASS2_CORE + _CONF_RULES + _STUB_RULE + _AN_TAIL),
    "v8": AnthropicPrompts(_AN_V8_PASS1, _AN_V8_PASS2),
    "v9": AnthropicPrompts(
        _PASS1_SYSTEM, _AN_PASS2_CORE + _BANDS + _DECOMP + _CONF_RULES + _STUB_RULE + _AN_TAIL
    ),
}

OPENAI_VERSIONS: dict[str, OpenAIPrompts] = {
    "v0": OpenAIPrompts(system=_SYSTEM),
    "v1": OpenAIPrompts(_OA_BASE + _BANDS),
    "v2": OpenAIPrompts(_OA_BASE + _BANDS + _DECOMP),
    "v4": OpenAIPrompts(
        _OA_BASE
        + " analysis_text 안에서 점수보다 먼저 근거 등급을 명시하라: 각 인용의 강도(강/약),"
        " 영향 범위(단일 종목/섹터/시장 전체), 신규성(재확인/새 정보), 정량성(규모 수치 유무)."
        " impact_score·direction·confidence는 그 등급 판정에서 도출하고, 확정 전 점수가 판정과"
        " 모순되지 않는지 검증하라."
    ),
    "v5": OpenAIPrompts(_OA_BASE + _CONF_RULES + _STUB_RULE),
    "v6": OpenAIPrompts(_OA_V6),
    "v7": OpenAIPrompts(_OA_BASE + _BANDS + _COUNTER_LENIENCY),
}


def anthropic_prompts(version: str) -> AnthropicPrompts:
    try:
        return ANTHROPIC_VERSIONS[version]
    except KeyError:
        raise KeyError(
            f"unknown anthropic prompt version {version!r} — valid: {sorted(ANTHROPIC_VERSIONS)}"
        ) from None


def openai_prompts(version: str) -> OpenAIPrompts:
    try:
        return OPENAI_VERSIONS[version]
    except KeyError:
        raise KeyError(
            f"unknown openai prompt version {version!r} — valid: {sorted(OPENAI_VERSIONS)}"
        ) from None
