"""CI validation script.

Walks every enriched question JSON in questions/ (skipping raw_*) and checks:
  1. The file parses as a Question via the Pydantic schema.
  2. reference_code passes EVERY test (sample + hidden) via the Code Executor.

Exits non-zero on the first failure so CI fails loudly. Safe to run without
an API key — does not call the LLM.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "backend"))

# UTF-8 stdout — model-generated text often contains non-ASCII chars and the
# Windows console default (cp1252) would crash on them in CI logs.
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

from core.code_executor import execute  # noqa: E402
from models.schemas import Question  # noqa: E402


QUESTIONS_DIR = _REPO_ROOT / "questions"


def main() -> int:
    paths = sorted(p for p in QUESTIONS_DIR.glob("*.json") if not p.name.startswith("raw_"))
    if not paths:
        print(f"FAIL: no enriched questions found under {QUESTIONS_DIR}")
        return 1

    any_failure = False
    for path in paths:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)

        try:
            q = Question(**raw)
        except Exception as exc:
            print(f"FAIL [{path.name}] schema: {exc}")
            any_failure = True
            continue

        tests = list(q.sample_tests) + list(q.hidden_tests)
        result = execute(q.reference_code, tests)
        if result.all_passed:
            print(f"OK   [{path.name}] {q.id}  {result.passed_count}/{result.total}")
        else:
            print(f"FAIL [{path.name}] {q.id}  {result.passed_count}/{result.total}")
            for t in result.results:
                if not t.passed:
                    err = f"  error={t.error}" if t.error else ""
                    print(
                        f"     input={t.input}  expected={t.expected}  "
                        f"actual={t.actual}{err}"
                    )
            any_failure = True

    if any_failure:
        print("\nVALIDATION: FAILED")
        return 1
    print(f"\nVALIDATION: PASSED ({len(paths)} questions)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
