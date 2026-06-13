"""Code Executor.

Runs an untrusted-ish Python source string against a list of TestCase objects.
No LLM. No network. Just exec() in a fresh namespace, plus per-test try/except.

Input convention
----------------
TestCase.input  : Python literal source for the call arguments.
                  Single-arg example:   "'HELLO'"      -> fn('HELLO')
                  Multi-arg example:    "5, 10"        -> fn(5, 10)
                  Single tuple arg:     "(1, 2)"       -> fn((1, 2))
                  We wrap with a trailing comma so ast.literal_eval always
                  yields a tuple of positional args.
TestCase.expected: Python literal source for the expected return value.

Failure modes
-------------
- Code does not parse / module-level exec raises -> every test fails with the
  same exec error recorded.
- No function definition found -> every test fails with a "no function" error.
- Function call raises -> that test fails, error captured, others continue.
- Returned value != ast.literal_eval(expected) -> that test fails, no error.
"""

from __future__ import annotations

import ast
import re
from typing import Iterable, List, Optional

from models.schemas import ExecutionResult, TestCase, TestResult


_DEF_RE = re.compile(r"^\s*def\s+([a-zA-Z_][a-zA-Z_0-9]*)\s*\(", re.MULTILINE)


def detect_function_name(code: str) -> Optional[str]:
    """Return the name of the first top-level function defined in `code`.

    Walks the AST so nested defs and methods inside classes are ignored.
    Falls back to a regex scan if AST parsing fails (the caller will catch
    the real syntax error elsewhere).
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        m = _DEF_RE.search(code)
        return m.group(1) if m else None

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return node.name
    return None


def _parse_args(input_src: str) -> tuple:
    """Parse a TestCase.input string into a positional-args tuple."""
    wrapped = f"({input_src},)"
    value = ast.literal_eval(wrapped)
    if not isinstance(value, tuple):
        # Defensive: with the trailing comma, ast always gives a tuple,
        # but guard against weird inputs.
        value = (value,)
    return value


def _parse_expected(expected_src: str):
    return ast.literal_eval(expected_src)


def _fail_all(tests: Iterable[TestCase], error: str) -> List[TestResult]:
    return [
        TestResult(
            input=t.input,
            expected=t.expected,
            actual="",
            passed=False,
            edge_label=t.edge_label,
            error=error,
        )
        for t in tests
    ]


def execute(code: str, tests: List[TestCase]) -> ExecutionResult:
    """Run `code` and call its top-level function against each test case."""
    total = len(tests)

    fn_name = detect_function_name(code)
    if fn_name is None:
        results = _fail_all(tests, "no top-level function definition found in generated code")
        return ExecutionResult(results=results, passed_count=0, total=total, all_passed=False)

    namespace: dict = {}
    try:
        exec(code, namespace)
    except Exception as exc:
        results = _fail_all(tests, f"code failed to load: {type(exc).__name__}: {exc}")
        return ExecutionResult(results=results, passed_count=0, total=total, all_passed=False)

    fn = namespace.get(fn_name)
    if not callable(fn):
        results = _fail_all(tests, f"function '{fn_name}' was not defined after exec")
        return ExecutionResult(results=results, passed_count=0, total=total, all_passed=False)

    results: List[TestResult] = []
    passed_count = 0
    for t in tests:
        try:
            args = _parse_args(t.input)
        except Exception as exc:
            results.append(TestResult(
                input=t.input, expected=t.expected, actual="",
                passed=False, edge_label=t.edge_label,
                error=f"could not parse test input: {type(exc).__name__}: {exc}",
            ))
            continue

        try:
            expected_value = _parse_expected(t.expected)
        except Exception as exc:
            results.append(TestResult(
                input=t.input, expected=t.expected, actual="",
                passed=False, edge_label=t.edge_label,
                error=f"could not parse expected value: {type(exc).__name__}: {exc}",
            ))
            continue

        try:
            got = fn(*args)
        except Exception as exc:
            results.append(TestResult(
                input=t.input, expected=t.expected, actual="",
                passed=False, edge_label=t.edge_label,
                error=f"{type(exc).__name__}: {exc}",
            ))
            continue

        passed = got == expected_value
        if passed:
            passed_count += 1
        results.append(TestResult(
            input=t.input,
            expected=t.expected,
            actual=repr(got),
            passed=passed,
            edge_label=t.edge_label,
            error=None,
        ))

    return ExecutionResult(
        results=results,
        passed_count=passed_count,
        total=total,
        all_passed=(passed_count == total and total > 0),
    )
