# CLAUDE.md

## Behavioral Guidelines (Karpathy)

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

### 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

### 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

### 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

## Commands
<!-- 스택: Python 3.12 + FastAPI (uv). 근거: docs/STAGE1_DESIGN.md §4. watch 모드 금지 -->
- Install: `uv sync`
- Run: `uv run uvicorn app.main:app`   (--reload 등 watch 모드 금지)
- Test: `uv run pytest`
- Lint: `uv run ruff check .`   (포맷: `uv run ruff format .`)
- Typecheck: `uv run mypy .`

## Project-Specific Gotchas
<!-- 자동 reflection으로 누적됨. 초기에는 비워두기 -->

## Measurable Conventions
<!-- 측정 가능한 것만. "잘 짜라" 같은 추상 표현 금지 -->

## Self-Reflection on Errors
When an error, exception, test failure, or unexpected behavior occurs
during this session, perform reflection AUTONOMOUSLY — do not wait for
the user to point it out:

1. STOP. Do not patch the symptom or suppress the error.
2. Analyze the root cause:
   - What was the actual failure mode (not just the error message)?
   - Why did this happen? Trace back to the originating decision or
     assumption that led here.
   - Was this caused by a silent assumption, missing context, or
     ignored convention?
   - Is this an instance of a pattern that could recur?
3. Fix the root cause, not the symptom.
4. After fixing, ask: "Would a rule in this CLAUDE.md have prevented
   this error?"
   - If YES → propose adding the rule (one line, specific, measurable)
     to the relevant section (Gotchas / Conventions). Show the proposed
     change and wait for user confirmation before writing.
   - If NO → log the lesson to Auto Memory instead, since it's a
     transient environmental issue rather than a project rule.

The goal is preventing the same CLASS of error from recurring. Every
error is a free lesson — capture it before it escapes.

## Project Context
<!-- 도메인·비즈니스 맥락만. 한국어 가능. 코드로 알 수 있는 정보 금지 -->
경제·주식·코인 관련 뉴스를 크롤링해 와서 에이전트로 분석하고, 현재
시황에서 가장 영향이 클 만한 종목을 추천하는 프로젝트.

핵심 파이프라인: 뉴스 수집(크롤링) → 에이전트 분석(시황·이벤트 해석)
→ 영향도 높은 종목 추천.

도메인 주의:
- 종목 추천은 투자 권유가 아니라 "현재 뉴스 기준 영향도 분석" 결과로
  취급. 추천 근거(어떤 뉴스·이벤트에서 도출됐는지)를 항상 함께 남길 것.
- 크롤링 소스의 신뢰도·시점(발행 시각)을 분석에 반영. 오래된 뉴스로
  현재 시황을 판단하지 말 것.
