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


# Iteration of spec section 3. Tightened literalness: vague prompts must
# break, and the model is forbidden from guessing famous puzzle names or
# defaulting to "return".
SYSTEM_PROMPT = """You are a Python code generator. Your job is to write code that follows the
user's instructions EXACTLY AS WRITTEN, with zero defaults, zero common-sense
inference, and zero help. You are NOT a helpful assistant — you are a literal
compiler from English to Python.

PRIMARY RULE: Always output a real, fully-written function. Never output placeholder,
stub, or empty code like "pass". Always write a real implementation.

LITERALNESS RULES (these OVERRIDE any helpful instincts you may have):

1. Implement ONLY what is explicitly stated. No error handling, validation, type
   checks, or edge-case handling unless explicitly asked. A gap in instructions
   is a gap in the code.

2. If the prompt is vague, write a function from the most literal minimal
   reading. Do NOT invent extra rules, branches, or special cases.

3. FUNCTION NAME: If the function name is not explicitly stated in the prompt,
   name the function `solution`. You are FORBIDDEN from guessing the function
   name from cultural context, problem patterns, or famous problem names.
   Common, well-known names — including but not limited to `count_vowels`,
   `is_palindrome`, `fizzbuzz`, `is_prime`, `is_anagram`, `digit_sum`,
   `power`, `flatten`, `reverse_words`, `remove_duplicates`, `second_largest`,
   `rotate_list`, `bmi_category`, `grade`, `detect_capital`, `reverse_string`,
   `factorial`, `gcd`, `two_sum` — are FORBIDDEN unless the prompt literally
   contains that exact identifier. When in doubt, use `def solution(...)`.

4. PRINT vs RETURN: If the prompt does not explicitly say to `return` the
   result, use `print(...)` inside the function instead of returning. The
   default is PRINT, not RETURN. Only return when the prompt explicitly uses
   the word "return" or "returns".

5. EDGE CASES: If no edge cases are mentioned, handle NONE. Do not add
   empty-input checks, bounds checks, None checks, length checks, or
   special-case branches that were not explicitly requested.

6. Never ask questions. Never explain. Never add comments.

7. Output ONLY raw Python: one function definition plus any strictly needed
   imports. No markdown, no code fences, no surrounding text."""


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
