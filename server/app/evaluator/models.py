from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.specs.models import TaskSpec


class CheckStatus(StrEnum):
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"


@dataclass(slots=True)
class CheckCommand:
    name: str
    argv: list[str]
    cwd: str | None = None
    required: bool = True


@dataclass(slots=True)
class CheckResult:
    name: str
    status: CheckStatus
    command: list[str] = field(default_factory=list)
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    summary: str = ""


@dataclass(slots=True)
class SemanticReview:
    status: CheckStatus
    summary: str
    missing_requirements: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)


@dataclass(slots=True)
class EvaluationRequest:
    spec: TaskSpec
    target_path: str | None = None
    code: str | None = None
    workspace: str | None = None
    pytest_args: list[str] = field(default_factory=list)
    hypothesis_target: str | None = None


@dataclass(slots=True)
class EvaluationReport:
    target: str
    overall_status: CheckStatus
    checks: list[CheckResult]
    semantic_review: SemanticReview
    missing_requirements: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    reflection: dict[str, Any] = field(default_factory=dict)
