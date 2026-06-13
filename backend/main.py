"""FastAPI entrypoint for GenCode.

Endpoints
---------
GET  /api/health             liveness check
GET  /api/questions          list of {id, title}
GET  /api/question/{id}      student-visible payload (sanitized)
POST /api/run                grade one student attempt end-to-end

Run from this directory:

    cd backend
    uvicorn main:app --reload --port 8000

The questions folder is read once at startup into an in-memory dict.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from agents.assessor import assess
from core.code_executor import execute
from core.code_generator import generate
from models.schemas import (
    Question,
    QuestionSummary,
    RunRequest,
    RunResponse,
    StudentQuestion,
    TestResult,
)


logger = logging.getLogger("gencode")
logging.basicConfig(level=logging.INFO)


_BACKEND_DIR = Path(__file__).resolve().parent
QUESTIONS_DIR = _BACKEND_DIR.parent / "questions"


def _load_questions() -> Dict[str, Question]:
    """Load every enriched question JSON in questions/. Files prefixed with
    `raw_` are pre-enrichment inputs to the Author script and are ignored.
    """
    questions: Dict[str, Question] = {}
    for path in sorted(QUESTIONS_DIR.glob("*.json")):
        if path.name.startswith("raw_"):
            continue
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        q = Question(**raw)
        questions[q.id] = q
        logger.info("loaded question %s from %s", q.id, path.name)
    if not questions:
        logger.warning("no questions found in %s", QUESTIONS_DIR)
    return questions


def _derive_title(q: Question) -> str:
    """First sentence of problem_description, capped to 80 chars."""
    first = q.problem_description.split(".")[0].strip()
    if len(first) > 80:
        first = first[:77] + "..."
    return first


def _mask_hidden(r: TestResult) -> TestResult:
    """Hide hidden-test input/expected/actual from the response.

    Students still see pass/fail and the edge_label (e.g. 'single_upper')
    so they know which kind of case broke, but they cannot read the inputs.
    Per spec rule 3: students never see hidden_tests.
    """
    return TestResult(
        input="(hidden)",
        expected="(hidden)",
        actual="(hidden)",
        passed=r.passed,
        edge_label=r.edge_label,
        error=None,
    )


# --------------------------------------------------------------------------- #
# App
# --------------------------------------------------------------------------- #

app = FastAPI(title="GenCode Backend", version="0.1.0")

# Permissive CORS for the demo. Tighten allow_origins for production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


_questions: Dict[str, Question] = _load_questions()


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "questions": len(_questions)}


@app.get("/api/questions", response_model=List[QuestionSummary])
def list_questions() -> List[QuestionSummary]:
    return [
        QuestionSummary(id=q.id, title=_derive_title(q))
        for q in _questions.values()
    ]


@app.get("/api/question/{question_id}", response_model=StudentQuestion)
def get_question(question_id: str) -> StudentQuestion:
    q = _questions.get(question_id)
    if q is None:
        raise HTTPException(
            status_code=404, detail=f"unknown question_id: {question_id}"
        )
    return q.for_student()


@app.post("/api/run", response_model=RunResponse)
def run_attempt(req: RunRequest) -> RunResponse:
    q = _questions.get(req.question_id)
    if q is None:
        raise HTTPException(
            status_code=404, detail=f"unknown question_id: {req.question_id}"
        )
    if not req.student_prompt.strip():
        raise HTTPException(status_code=400, detail="student_prompt must not be empty")

    # Spec rule 3: tests run sample first, then hidden, so we can split by index
    # when masking hidden test inputs out of the response.
    all_tests = list(q.sample_tests) + list(q.hidden_tests)
    n_sample = len(q.sample_tests)

    try:
        code = generate(req.student_prompt)
    except Exception as exc:
        logger.exception("code generation failed")
        raise HTTPException(status_code=502, detail=f"code generation failed: {exc}")

    exec_result = execute(code, all_tests)

    try:
        grading = assess(
            requirements=q.requirements,
            reference_prompt=q.reference_prompt,
            reference_code=q.reference_code,
            student_prompt=req.student_prompt,
            student_code=code,
            test_results=exec_result,
        )
    except Exception as exc:
        logger.exception("assessor failed")
        raise HTTPException(status_code=502, detail=f"assessor failed: {exc}")

    visible_results: List[TestResult] = list(exec_result.results[:n_sample]) + [
        _mask_hidden(r) for r in exec_result.results[n_sample:]
    ]

    return RunResponse(
        overall_score=grading.overall_score,
        requirement_quality=grading.requirement_quality,
        output_quality=grading.output_quality,
        requirement_findings=grading.requirement_findings,
        feedback=grading.feedback,
        test_results=visible_results,
        passed_count=exec_result.passed_count,
        total=exec_result.total,
        all_passed=exec_result.all_passed,
    )
