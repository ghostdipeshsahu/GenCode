"""Author agent — offline enrichment of a raw coding question.

Runs ONCE per question, at setup time. Never runs during a student session.

Input  (raw question JSON):
    id, statement, function_signature, sample_tests, hidden_tests,
    reference_solution, primary_kp_label

Output (enriched question JSON, ready for the runtime):
    id, problem_description, requirements, sample_tests, hidden_tests,
    reference_solution, reference_prompt, reference_code

Eval loop (spec section 2)
--------------------------
After the LLM produces its four fields, we run two checks. If either fails,
we re-call the LLM with a hint pointing at the specific failure. Max 3
retries (4 total attempts).

  Eval 1 (deterministic): execute `reference_code` against all hidden_tests
  via the Code Executor. Every test must pass.

  Eval 2 (LLM-based, adversarial framing): ask the LLM to list any
  requirements that `reference_prompt` does NOT address. Non-empty list
  fails the check.

Usage:
    python scripts/author.py questions/raw_p002.json -o questions/p002.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional


# Allow `from core.* import ...` and `from models.* import ...` regardless of
# where this script is invoked from.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "backend"))

# Windows default console codec is cp1252 and chokes on the unicode chars that
# crop up in LLM output (non-breaking hyphens, smart quotes, em-dashes, ...).
# Force stdout/stderr to UTF-8 for the lifetime of this script.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

from core.code_executor import execute  # noqa: E402
from core.llm import EXTRA_HEADERS, MODEL, get_client  # noqa: E402
from models.schemas import AuthorOutput, Question, TestCase  # noqa: E402


MAX_RETRIES = 3  # spec: Author up to 3 retries (4 total attempts)


# Verbatim from spec section 6. Do not edit without spec change.
SYSTEM_PROMPT = """You are the Author agent for GenCode, a platform that teaches students to write
precise English prompts that instruct an AI to write correct code.

Given a coding question, produce four things:

1. "problem_description"
   2-3 sentences, plain English, suitable for a beginner student. Describe what
   the function should do without revealing the implementation details.

2. "requirements"
   A structured checklist of what a good prompt for this problem must specify.
   Use these headings (skip any that genuinely do not apply):
   - Logical Decomposition: the key steps the solution must perform
   - Implementation Specifications: function name, parameters, language, constraints
   - Edge Case Handling: unusual inputs the obvious implementation gets wrong
     (ONLY cases consistent with the problem's stated constraints)
   - Output Formatting: exact return type and value format
   - Avoiding Default Biases: anything the AI would otherwise guess wrong
   Keep each point to ONE crisp line. This is shown to students as a teaching guide.

3. "reference_prompt"
   The gold-standard prompt a perfect student would write. Natural English that
   covers every requirement above such that a literal AI produces fully correct code.
   This is NOT shown to students.

4. "reference_code"
   The Python code that the reference_prompt would produce — a complete, correct
   implementation. This is NOT shown to students.

Output ONLY valid JSON with these four keys. No markdown fences. No preamble."""


COVERAGE_SYSTEM_PROMPT = """You are an adversarial evaluator. You are given:
- a checklist of requirements (bulleted list with headings)
- a prompt that is supposed to address every requirement

Your job is to find any requirement that the prompt does NOT address. Be
strict — if a requirement is only partially mentioned or its key detail is
missing, count it as not addressed.

Output ONLY valid JSON with this shape:
{"missing": ["requirement heading 1", "requirement heading 2", ...]}

If every requirement is addressed, output {"missing": []}. No preamble. No
markdown fences."""


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
    """Same balanced-brace extractor used in the Assessor."""
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


# --------------------------------------------------------------------------- #
# LLM calls
# --------------------------------------------------------------------------- #

def _build_user_payload(raw: dict, retry_hint: Optional[str]) -> str:
    sections = [
        "RAW QUESTION:",
        f"statement: {raw['statement']}",
        f"function_signature: {raw['function_signature']}",
        f"primary_kp_label: {raw.get('primary_kp_label', '')}",
        "",
        "sample_tests:",
        json.dumps(raw["sample_tests"], indent=2),
        "",
        "hidden_tests:",
        json.dumps(raw["hidden_tests"], indent=2),
        "",
        "reference_solution (authoritative behavior — your reference_code MUST "
        "behave identically and must pass every hidden test):",
        raw["reference_solution"],
    ]
    if retry_hint:
        sections += [
            "",
            "RETRY HINT (your previous attempt failed an eval check):",
            retry_hint,
            "Fix the issue above and try again.",
        ]
    return "\n".join(sections)


def _call_author(raw: dict, retry_hint: Optional[str]) -> dict:
    client = get_client()
    response = client.chat.completions.create(
        model=MODEL,
        max_tokens=2048,
        temperature=0,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_payload(raw, retry_hint)},
        ],
        extra_headers=EXTRA_HEADERS,
    )
    raw_text = response.choices[0].message.content or ""
    return json.loads(_extract_json_block(raw_text))


def _call_coverage_check(reference_prompt: str, requirements: str) -> list[str]:
    """Return the list of requirement headings the prompt fails to address."""
    user = (
        "REQUIREMENTS:\n"
        f"{requirements}\n\n"
        "PROMPT:\n"
        f"{reference_prompt}"
    )
    client = get_client()
    response = client.chat.completions.create(
        model=MODEL,
        max_tokens=512,
        temperature=0,
        messages=[
            {"role": "system", "content": COVERAGE_SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
        extra_headers=EXTRA_HEADERS,
    )
    raw_text = response.choices[0].message.content or ""
    try:
        parsed = json.loads(_extract_json_block(raw_text))
    except json.JSONDecodeError:
        # If the evaluator misbehaves, fail open — let the deterministic
        # eval be the strict gate.
        return []
    missing = parsed.get("missing", [])
    if not isinstance(missing, list):
        return []
    return [str(x) for x in missing if str(x).strip()]


# --------------------------------------------------------------------------- #
# Output normalization
# --------------------------------------------------------------------------- #

def _flatten_value(v) -> str:
    """Coerce any JSON value (str, list, dict, scalar) into a single ONE-LINE
    string. Lists are joined with '; '; nested dicts are flattened to
    'key: value; ...'."""
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, list):
        parts = [p for p in (_flatten_value(x) for x in v) if p]
        return "; ".join(parts)
    if isinstance(v, dict):
        return "; ".join(
            f"{k}: {_flatten_value(vv)}" for k, vv in v.items() if _flatten_value(vv)
        )
    return str(v).strip()


def _normalize_requirements(output: dict) -> dict:
    """The spec wants `requirements` as a bulleted string with ONE line per
    requirement (section 6: "Keep each point to ONE crisp line."). Models
    sometimes return it as a dict[heading -> body], a dict[heading -> list
    of sub-points], or a list of objects. Flatten all of those to the
    canonical "- Heading: body\\n- ..." string."""
    req = output.get("requirements")
    if isinstance(req, str):
        return output

    if isinstance(req, dict):
        lines = [
            f"- {k}: {_flatten_value(v)}" for k, v in req.items() if _flatten_value(v)
        ]
        output["requirements"] = "\n".join(lines)
        return output

    if isinstance(req, list):
        lines: list[str] = []
        for item in req:
            if isinstance(item, dict):
                heading = (
                    item.get("heading")
                    or item.get("name")
                    or item.get("title")
                    or ""
                )
                rest = {
                    k: v
                    for k, v in item.items()
                    if k not in ("heading", "name", "title") and _flatten_value(v)
                }
                body = _flatten_value(rest) if rest else ""
                if heading and body:
                    lines.append(f"- {heading}: {body}")
                elif heading or body:
                    lines.append(f"- {heading or body}")
            elif item:
                lines.append(f"- {_flatten_value(item)}")
        output["requirements"] = "\n".join(lines)
    return output


# --------------------------------------------------------------------------- #
# Eval loop
# --------------------------------------------------------------------------- #

def _eval_reference_code(reference_code: str, hidden_tests_raw: list[dict]) -> Optional[str]:
    """Return None if every hidden test passes, else a hint describing the
    first failure."""
    tests = [TestCase(**t) for t in hidden_tests_raw]
    result = execute(reference_code, tests)
    if result.all_passed:
        return None
    failed = [r for r in result.results if not r.passed]
    f = failed[0]
    err = f" (error: {f.error})" if f.error else ""
    return (
        f"reference_code failed {len(failed)} of {result.total} hidden tests. "
        f"First failure: input={f.input}, expected={f.expected}, got={f.actual}{err}. "
        "Fix reference_code so it matches the reference_solution behavior, "
        "and tighten reference_prompt so a literal model would produce code "
        "that also handles that case."
    )


def enrich(raw: dict) -> dict:
    """Run the Author agent end-to-end with the eval loop. Returns the
    enriched-question dict ready to be saved as JSON.
    """
    retry_hint: Optional[str] = None
    last_output: Optional[dict] = None

    for attempt in range(MAX_RETRIES + 1):
        print(f"[author] attempt {attempt + 1}/{MAX_RETRIES + 1}...", flush=True)
        try:
            output = _call_author(raw, retry_hint)
        except json.JSONDecodeError as exc:
            retry_hint = f"your previous response was not valid JSON: {exc}"
            print(f"[author] JSON parse failed: {exc}", flush=True)
            continue

        output = _normalize_requirements(output)
        try:
            validated = AuthorOutput(**output)
        except Exception as exc:
            retry_hint = (
                "your previous response was JSON but did not match the schema. "
                "All four keys must be present and non-empty: "
                f"problem_description, requirements, reference_prompt, reference_code. Error: {exc}"
            )
            print(f"[author] schema validation failed: {exc}", flush=True)
            continue

        last_output = validated.model_dump()

        # Eval 1: deterministic test run on reference_code
        hint = _eval_reference_code(validated.reference_code, raw["hidden_tests"])
        if hint:
            retry_hint = hint
            print(f"[author] eval 1 failed: {hint}", flush=True)
            continue
        print("[author] eval 1 passed (reference_code runs all hidden tests)", flush=True)

        # Eval 2: LLM coverage check on reference_prompt vs requirements
        missing = _call_coverage_check(validated.reference_prompt, validated.requirements)
        if missing:
            retry_hint = (
                "reference_prompt fails to address the following requirements: "
                f"{', '.join(missing)}. Rewrite reference_prompt so a literal AI "
                "reading it would know to handle every requirement on the checklist."
            )
            print(f"[author] eval 2 failed: missing {missing}", flush=True)
            continue
        print("[author] eval 2 passed (reference_prompt covers every requirement)", flush=True)

        # Both evals green — assemble enriched payload
        return _assemble(raw, validated)

    # Out of retries. Return the best we have, marked with a warning.
    print("[author] WARNING: max retries exhausted; saving last output anyway", flush=True)
    if last_output is None:
        raise RuntimeError("Author produced no valid output across all attempts")
    return _assemble(raw, AuthorOutput(**last_output))


def _assemble(raw: dict, validated: AuthorOutput) -> dict:
    """Combine raw inputs (minus author-only fields) with the LLM's outputs
    into the enriched-question schema from spec section 5.
    """
    return {
        "id": raw["id"],
        "problem_description": validated.problem_description,
        "requirements": validated.requirements,
        "sample_tests": raw["sample_tests"],
        "hidden_tests": raw["hidden_tests"],
        "reference_solution": raw["reference_solution"],
        "reference_prompt": validated.reference_prompt,
        "reference_code": validated.reference_code,
    }


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

_QUESTIONS_DIR = _REPO_ROOT / "questions"


def _slug_from_signature(sig: str) -> str:
    """Extract the function name from a signature like 'def is_palindrome(text):'
    or 'is_palindrome(text)' for use in output filenames.
    """
    s = (sig or "").strip()
    if s.startswith("def "):
        s = s[4:]
    paren = s.find("(")
    if paren > 0:
        s = s[:paren]
    return s.strip().lower() or "question"


def _default_output_for_id(raw: dict) -> Path:
    """questions/{id_lower}_{function_name}.json"""
    slug = _slug_from_signature(raw.get("function_signature", ""))
    return _QUESTIONS_DIR / f"{raw['id'].lower()}_{slug}.json"


def _default_single_output_path(raw_path: Path, qid: str) -> Path:
    """Single-file mode: drop the 'raw_' prefix if present, else suffix the id."""
    name = raw_path.name
    if name.startswith("raw_"):
        return raw_path.with_name(name[4:])
    return raw_path.with_name(f"{qid.lower()}_enriched.json")


def _process_one(raw: dict, out_path: Path) -> bool:
    """Enrich one raw question and write it. Returns True on success."""
    try:
        enriched = enrich(raw)
        Question(**enriched)  # final sanity check
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(enriched, f, indent=2)
            f.write("\n")
        print(f"[author] OK   {raw['id']}  ->  {out_path}", flush=True)
        return True
    except Exception as exc:
        print(f"[author] FAIL {raw['id']}: {type(exc).__name__}: {exc}", flush=True)
        return False


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("raw", type=Path, help="path to raw question JSON (object or array with --batch)")
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="path to write enriched JSON (single-file mode only)",
    )
    p.add_argument(
        "--batch",
        action="store_true",
        help="raw file is a JSON array of raw questions; write each to "
        "questions/{id_lower}_{function_name}.json",
    )
    args = p.parse_args()

    with open(args.raw, encoding="utf-8") as f:
        data = json.load(f)

    if args.batch:
        if not isinstance(data, list):
            print("[author] --batch requires a JSON array at the top level", flush=True)
            return 2
        print(f"[author] batch mode: {len(data)} question(s)", flush=True)
        succeeded = 0
        for i, raw in enumerate(data, 1):
            print(f"\n[author] ---- {i}/{len(data)}  id={raw.get('id', '?')} ----", flush=True)
            out_path = _default_output_for_id(raw)
            if _process_one(raw, out_path):
                succeeded += 1
        print(f"\n[author] batch complete: {succeeded}/{len(data)} succeeded", flush=True)
        return 0 if succeeded == len(data) else 1

    # Single-file mode
    if isinstance(data, list):
        print(
            "[author] input is a JSON array; pass --batch to process all entries",
            flush=True,
        )
        return 2
    out_path = args.output or _default_single_output_path(args.raw, data["id"])
    return 0 if _process_one(data, out_path) else 1


if __name__ == "__main__":
    sys.exit(main())
