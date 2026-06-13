"""Pydantic data contracts for GenCode.

Two views of a Question exist:
  * Question         — full server-side record loaded from JSON in questions/.
  * StudentQuestion  — sanitized payload returned to the browser. Strips
                       reference_prompt, reference_code, reference_solution,
                       and hidden_tests so the student never sees them.
"""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #

class TestCase(BaseModel):
    """A single input/expected pair. `input` is a Python literal source string
    (e.g. "'HELLO'" or "5") so the executor can pass it through ast.literal_eval.
    """
    input: str
    expected: str
    edge_label: Optional[str] = None


class TestResult(BaseModel):
    input: str
    expected: str
    actual: str
    passed: bool
    edge_label: Optional[str] = None
    error: Optional[str] = None


class ExecutionResult(BaseModel):
    """Aggregate output of the Code Executor."""
    results: List[TestResult]
    passed_count: int
    total: int
    all_passed: bool


# --------------------------------------------------------------------------- #
# Questions
# --------------------------------------------------------------------------- #

class Question(BaseModel):
    """Full enriched question. Lives on disk in questions/<id>.json. Never
    sent to the client in full — use Question.for_student() instead.
    """
    id: str
    problem_description: str
    requirements: str
    sample_tests: List[TestCase]
    hidden_tests: List[TestCase] = Field(default_factory=list)
    reference_solution: str
    reference_prompt: str
    reference_code: str

    def for_student(self) -> "StudentQuestion":
        return StudentQuestion(
            id=self.id,
            problem_description=self.problem_description,
            requirements=self.requirements,
            sample_tests=self.sample_tests,
        )


class StudentQuestion(BaseModel):
    """Sanitized view safe to ship to the browser."""
    id: str
    problem_description: str
    requirements: str
    sample_tests: List[TestCase]


class QuestionSummary(BaseModel):
    """Listing item for GET /api/questions."""
    id: str
    title: str


# --------------------------------------------------------------------------- #
# Assessor
# --------------------------------------------------------------------------- #

FindingStatus = Literal["correct", "omission", "commission"]


class RequirementFinding(BaseModel):
    requirement: str
    status: FindingStatus
    evidence: str


class AssessorOutput(BaseModel):
    overall_score: float
    requirement_quality: float
    output_quality: float
    requirement_findings: List[RequirementFinding]
    feedback: str


# --------------------------------------------------------------------------- #
# Author
# --------------------------------------------------------------------------- #

class AuthorOutput(BaseModel):
    """Raw payload returned by the Author LLM before it is merged with the
    raw question (id, sample_tests, hidden_tests, reference_solution)."""
    problem_description: str
    requirements: str
    reference_prompt: str
    reference_code: str


# --------------------------------------------------------------------------- #
# Run endpoint contracts
# --------------------------------------------------------------------------- #

class RunRequest(BaseModel):
    question_id: str
    student_prompt: str
    attempt_number: int = 1


class RunResponse(BaseModel):
    overall_score: float
    requirement_quality: float
    output_quality: float
    requirement_findings: List[RequirementFinding]
    feedback: str
    test_results: List[TestResult]
    passed_count: int
    total: int
    all_passed: bool
