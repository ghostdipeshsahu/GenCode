"""Code Generator — constrained LLM call that turns a student's English prompt
into Python source.

This is the pedagogical core of GenCode. The system prompt forces the model
to be literal: vague prompts produce incomplete code, precise prompts produce
correct code.

Provider config (base URL, model, key env var) lives in `backend/core/llm.py`.
"""

from __future__ import annotations

import re

from core.llm import EXTRA_HEADERS, MODEL, get_client


# Verbatim from spec section 3. Do not edit without spec change.
SYSTEM_PROMPT = """You are a Python code generator. Your job is to write a complete, working Python
function that implements the user's instructions exactly as written.

PRIMARY RULE: Always output a real, fully-written function. Never output placeholder,
stub, or empty code like "pass". Always write a real implementation.

Rules:
- Implement ONLY what is explicitly stated. No error handling, validation, type
  checks, or edge-case handling unless explicitly asked.
- If instructions are vague, write a real function using the most literal minimal
  reading. Do not invent extra rules. A gap in instructions = a gap in the code.
- Never ask questions. Never explain. Never add comments.
- Use the exact function signature given. Return the result (do not print) unless
  told otherwise.
- Output ONLY raw Python: one function definition plus any strictly needed imports.
  No markdown, no code fences, no surrounding text."""


_FENCE_RE = re.compile(
    r"^\s*```(?:python|py)?\s*\n(.*?)\n```\s*$",
    re.DOTALL | re.IGNORECASE,
)


def _strip_fences(text: str) -> str:
    """Strip ```python ... ``` if the model wraps its output despite the
    system prompt forbidding it.
    """
    m = _FENCE_RE.match(text)
    if m:
        return m.group(1).strip()
    return text.strip()


def generate(student_prompt: str, *, max_tokens: int = 2048) -> str:
    """Turn the student's English prompt into Python source code.

    The returned string is fed straight into the Code Executor. Syntax errors
    and missing functions are caught downstream, not here.
    """
    response = get_client().chat.completions.create(
        model=MODEL,
        max_tokens=max_tokens,
        temperature=0,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": student_prompt},
        ],
        extra_headers=EXTRA_HEADERS,
    )
    raw = response.choices[0].message.content or ""
    return _strip_fences(raw)
