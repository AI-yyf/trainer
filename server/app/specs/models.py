from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4


@dataclass(slots=True)
class RequirementItem:
    category: str
    text: str
    source: str = "prompt"


@dataclass(slots=True)
class ValidationHook:
    tool: str
    description: str
    required: bool = True


@dataclass(slots=True)
class TaskSpec:
    id: str
    title: str
    objective: str
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    edge_cases: list[str] = field(default_factory=list)
    failure_conditions: list[str] = field(default_factory=list)
    validations: list[ValidationHook] = field(default_factory=list)
    requirements: list[RequirementItem] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(cls, *, title: str, objective: str) -> "TaskSpec":
        return cls(id=f"spec_{uuid4().hex}", title=title, objective=objective)


@dataclass(slots=True)
class TaskSpecificationRequest:
    prompt: str
    language: str = "python"
    plan_context: str | None = None
    weakness_context: list[str] = field(default_factory=list)
    resource_context: list[str] = field(default_factory=list)


@dataclass(slots=True)
class TaskSpecificationResult:
    spec: TaskSpec
    warnings: list[str] = field(default_factory=list)
