"""Assessor agent — grades the student's prompt and gives specific, actionable
feedback.

This is a TRUE AGENT in the sense the spec defines: it produces output, runs
a deterministic self-eval against that output, and re-grades up to MAX_RETRIES
times if the self-eval fails. Usually the first attempt passes.

The deterministic part of the score (output_quality) is computed here from
test_results — the LLM is never asked to do arithmetic on test counts. Only
requirement_quality and the feedback narrative come from the LLM.
"""

from __future__ import annotations

import json
import re
from typing import Optional

from core.llm import EXTRA_HEADERS, MODEL, get_client
from models.schemas import (
    AssessorOutput,
    ExecutionResult,
    RequirementFinding,
)


MAX_RETRIES = 2  # spec: Assessor up to 2 retries (3 total attempts)


# Verbatim from spec section 7. Do not edit without spec change.
SYSTEM_PROMPT = """You are the Assessor agent for GenCode. Grade a student's prompt and give feedback.

You receive:
- requirements: structured checklist (what a good prompt must cover)
- reference_prompt: the gold-standard ideal prompt
- reference_code: the ideal code
- student_prompt: the student's actual prompt
- student_code: the code their prompt produced
- test_results: which tests passed and failed (passed_count, total, per-test details)

STEP 1 — Requirement Quality (LLM-judged, 0-10)
For each requirement in the checklist, classify the student's prompt as:
- "correct": requirement is conveyed accurately (paraphrases are fine)
- "omission": requirement is completely missing
- "commission": requirement is present but stated wrongly or ambiguously
Only "correct" counts toward the score.
requirement_quality = (correct_count / total_requirements) * 10

STEP 2 — Output Quality (deterministic, 0-10)
output_quality = (passed_count / total_tests) * 10
Read directly from test_results. No judgment.

STEP 3 — Overall Score
overall_score = (requirement_quality + output_quality) / 2

STEP 4 — Feedback
Write 3-4 sentences. Be warm and specific. Name the exact requirement the student
missed or stated wrongly. Do NOT give them the exact wording to copy — teach the
habit of thinking about it, not the answer itself.

STEP 5 — Self-evaluation before outputting
Check your own output:
- Every "omission" finding: does the student's prompt genuinely lack this? Cite where.
- Every "commission" finding: quote the exact phrase that is wrong or ambiguous.
- Feedback: does it name a specific requirement? If it is generic, rewrite it.

Output ONLY valid JSON:
{
  "overall_score": 0.0,
  "requirement_quality": 0.0,
  "output_quality": 0.0,
  "requirement_findings": [
    {
      "requirement": "the requirement text",
      "status": "correct|omission|commission",
      "evidence": "quote from prompt, or explanation of absence"
    }
  ],
  "feedback": "3-4 sentence feedback string"
}
No preamble. No markdown fences."""


# --------------------------------------------------------------------------- #
# Parsing helpers
# --------------------------------------------------------------------------- #

_FENCE_RE = re.compile(
    r"^\s*```(?:json)?\s*\n(.*?)\n```\s*$",
    re.DOTALL | re.IGNORECASE,
)


def _strip_fences(text: str) -> str:
    m = _FENCE_RE.match(text)
    if m:
        return m.group(1).strip()
    return text.strip()


def _extract_json_block(text: str) -> str:
    """Pull the first balanced { ... } block out of the response.

    Some models prepend a sentence or two even when told not to. Walk the
    string and slice from the first `{` to the matching `}` (counting depth,
    ignoring braces inside string literals).
    """
    s = _strip_fences(text)
    start = s.find("{")
    if start == -1:
        return s
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(s)):
        c = s[i]
        if in_str:
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return s[start : i + 1]
    return s[start:]


def _parse_requirements(s: str) -> list[str]:
    """Split the question's requirements string into a list of bullet lines.

    The Author produces requirements as `- Heading: description` lines.
    """
    lines: list[str] = []
    for raw in s.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith(("- ", "* ", "• ")):
            lines.append(line[2:].strip())
        elif re.match(r"^\d+[\.)]\s+", line):
            lines.append(re.sub(r"^\d+[\.)]\s+", "", line).strip())
    return lines


# --------------------------------------------------------------------------- #
# Self-eval
# --------------------------------------------------------------------------- #

def _self_eval(
    parsed: dict, expected_requirement_count: int
) -> tuple[bool, Optional[str]]:
    """Deterministic checks on the LLM's output. Returns (ok, hint)."""
    findings = parsed.get("requirement_findings", [])
    if not isinstance(findings, list):
        return False, "requirement_findings must be a JSON array"

    if expected_requirement_count and len(findings) != expected_requirement_count:
        return False, (
            f"requirement_findings must contain exactly {expected_requirement_count} "
            f"items (one per requirement in the checklist); you produced {len(findings)}"
        )

    for i, f in enumerate(findings):
        status = f.get("status")
        if status not in ("correct", "omission", "commission"):
            return False, f"finding {i} has invalid status: {status!r}"
        evidence = (f.get("evidence") or "").strip()
        if not evidence:
            return False, (
                f"finding {i} ('{f.get('requirement', '')[:60]}') has empty evidence; "
                "every finding must cite specific evidence"
            )
        if status == "commission" and '"' not in evidence and "'" not in evidence:
            return False, (
                f"finding {i} is a commission but evidence does not quote anything "
                "from the student prompt; quote the exact phrase that is wrong"
            )

    feedback = (parsed.get("feedback") or "").strip()
    if not feedback:
        return False, "feedback is empty"
    sentence_count = len(re.findall(r"[.!?]+", feedback))
    if sentence_count < 2:
        return False, (
            "feedback must be 3-4 sentences and name a specific requirement; "
            "the current draft is too short"
        )

    return True, None


# --------------------------------------------------------------------------- #
# Prompt construction
# --------------------------------------------------------------------------- #

def _format_test_results(tr: ExecutionResult) -> str:
    lines = [f"passed_count: {tr.passed_count} / {tr.total}"]
    lines.append("per_test:")
    for r in tr.results:
        flag = "PASS" if r.passed else "FAIL"
        err = f"  error={r.error}" if r.error else ""
        lines.append(
            f"  - {flag}  input={r.input}  expected={r.expected}  "
            f"actual={r.actual}{err}"
        )
    return "\n".join(lines)


def _build_user_payload(
    requirements: str,
    reference_prompt: str,
    reference_code: str,
    student_prompt: str,
    student_code: str,
    test_results: ExecutionResult,
    *,
    deterministic_output_quality: float,
    retry_hint: Optional[str] = None,
) -> str:
    sections = [
        "REQUIREMENTS CHECKLIST:",
        requirements,
        "",
        "REFERENCE PROMPT (gold standard, never shown to student):",
        reference_prompt,
        "",
        "REFERENCE CODE (gold standard, never shown to student):",
        reference_code,
        "",
        "STUDENT PROMPT:",
        student_prompt,
        "",
        "STUDENT CODE (produced by the student's prompt):",
        student_code,
        "",
        "TEST RESULTS:",
        _format_test_results(test_results),
        "",
        (
            f"output_quality has already been computed deterministically: "
            f"{deterministic_output_quality:.2f}. Use this exact value in your "
            "output JSON; do not recompute."
        ),
    ]
    if retry_hint:
        sections += [
            "",
            "RETRY HINT (your previous attempt failed self-evaluation):",
            retry_hint,
            "Fix the issue above and try again.",
        ]
    return "\n".join(sections)


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def assess(
    *,
    requirements: str,
    reference_prompt: str,
    reference_code: str,
    student_prompt: str,
    student_code: str,
    test_results: ExecutionResult,
) -> AssessorOutput:
    """Grade a single student attempt. Retries up to MAX_RETRIES on self-eval
    failure. After exhausting retries, returns the last parsed result anyway
    so the student still gets feedback.
    """
    deterministic_output_quality = (
        (test_results.passed_count / test_results.total) * 10.0
        if test_results.total > 0
        else 0.0
    )
    expected_findings = len(_parse_requirements(requirements))

    client = get_client()
    retry_hint: Optional[str] = None
    parsed: dict = {}

    for attempt in range(MAX_RETRIES + 1):
        user_payload = _build_user_payload(
            requirements=requirements,
            reference_prompt=reference_prompt,
            reference_code=reference_code,
            student_prompt=student_prompt,
            student_code=student_code,
            test_results=test_results,
            deterministic_output_quality=deterministic_output_quality,
            retry_hint=retry_hint,
        )

        response = client.chat.completions.create(
            model=MODEL,
            max_tokens=2048,
            temperature=0,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_payload},
            ],
            extra_headers=EXTRA_HEADERS,
        )
        raw = response.choices[0].message.content or ""
        try:
            parsed = json.loads(_extract_json_block(raw))
        except json.JSONDecodeError as exc:
            retry_hint = f"your previous response was not valid JSON: {exc}"
            continue

        ok, reason = _self_eval(parsed, expected_findings)
        if ok:
            break
        retry_hint = reason

    # Force deterministic output_quality regardless of what the LLM produced.
    parsed["output_quality"] = round(deterministic_output_quality, 2)

    # Recompute requirement_quality + overall_score from findings so the
    # numbers cannot drift from the findings list the student sees.
    findings_raw = parsed.get("requirement_findings", []) or []
    if findings_raw:
        correct = sum(1 for f in findings_raw if f.get("status") == "correct")
        parsed["requirement_quality"] = round((correct / len(findings_raw)) * 10.0, 2)
    else:
        parsed["requirement_quality"] = 0.0
    parsed["overall_score"] = round(
        (parsed["requirement_quality"] + parsed["output_quality"]) / 2.0, 2
    )

    findings = [
        RequirementFinding(
            requirement=str(f.get("requirement", "")),
            status=f.get("status", "omission"),
            evidence=str(f.get("evidence", "")),
        )
        for f in findings_raw
    ]

    return AssessorOutput(
        overall_score=float(parsed["overall_score"]),
        requirement_quality=float(parsed["requirement_quality"]),
        output_quality=float(parsed["output_quality"]),
        requirement_findings=findings,
        feedback=str(parsed.get("feedback", "")).strip(),
    )
