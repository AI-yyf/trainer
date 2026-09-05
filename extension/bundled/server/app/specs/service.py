from __future__ import annotations

import re
from collections.abc import Iterator

from ..core.models import TaskSpec as ApiTaskSpec
from ..core.models import TaskSpecifyRequest
from .models import (
    RequirementItem,
    TaskSpec,
    TaskSpecificationRequest,
    TaskSpecificationResult,
    ValidationHook,
)

_CHINESE_TEXT_RE = re.compile(r"[\u3400-\u9fff]")
_CHINESE_CLAUSE_BOUNDARY_RE = re.compile(r"(?<=[。！？；，])")

_INPUT_SIGNALS = ("input", "read", "accept", "输入", "入参", "参数", "接收", "读取")
_OUTPUT_SIGNALS = ("output", "return", "print", "输出", "返回", "打印")
_CONSTRAINT_SIGNALS = (
    "must",
    "should",
    "require",
    "constraint",
    "without",
    "必须",
    "应当",
    "需要",
    "不得",
    "不能",
    "禁止",
    "约束",
    "不允许",
    "只能",
    "验收",
    "通过条件",
)
_EDGE_CASE_SIGNALS = (
    "edge",
    "empty",
    "none",
    "null",
    "invalid",
    "边界",
    "空值",
    "空字符串",
    "为空",
    "空输入",
    "空列表",
    "空参数",
    "无效",
    "缺失",
)
_FAILURE_SIGNALS = (
    "fail",
    "error",
    "raise",
    "exception",
    "错误",
    "报错",
    "异常",
    "失败",
    "抛出",
    "拒绝",
)


class TaskSpecGenerator:
    def generate(self, request: TaskSpecificationRequest) -> TaskSpecificationResult:
        spec = TaskSpec.create(title=self._derive_title(request.prompt), objective=request.prompt.strip())
        requirements = self._extract_requirements(request.prompt)
        spec.requirements = requirements
        spec.inputs = [item.text for item in requirements if item.category == "input"]
        spec.outputs = [item.text for item in requirements if item.category == "output"]
        spec.constraints = [item.text for item in requirements if item.category == "constraint"]
        spec.edge_cases = [item.text for item in requirements if item.category == "edge_case"]
        spec.failure_conditions = [item.text for item in requirements if item.category == "failure_condition"]
        spec.validations = self._default_validations(request.language)
        spec.metadata = {
            "plan_context": request.plan_context,
            "weakness_context": list(request.weakness_context),
            "resource_context": list(request.resource_context),
        }
        warnings = []
        if not spec.inputs:
            warnings.append("No explicit inputs found in prompt; defaulting to implementation-defined input handling.")
        if not spec.outputs:
            warnings.append("No explicit outputs found in prompt; validation will lean on tests and semantic review.")
        return TaskSpecificationResult(spec=spec, warnings=warnings)

    def _derive_title(self, prompt: str) -> str:
        sentence = re.split(r"[.!?。！？\n]", prompt.strip())[0]
        return sentence[:80] or "Trainer task"

    def _extract_requirements(self, prompt: str) -> list[RequirementItem]:
        items: list[RequirementItem] = []
        for line in self._iter_requirement_clauses(prompt):
            lowered = line.lower()
            if any(word in lowered for word in _INPUT_SIGNALS):
                items.append(RequirementItem(category="input", text=line))
            if any(word in lowered for word in _OUTPUT_SIGNALS):
                items.append(RequirementItem(category="output", text=line))
            if any(word in lowered for word in _CONSTRAINT_SIGNALS):
                items.append(RequirementItem(category="constraint", text=line))
            if any(word in lowered for word in _EDGE_CASE_SIGNALS):
                items.append(RequirementItem(category="edge_case", text=line))
            if any(word in lowered for word in _FAILURE_SIGNALS):
                items.append(RequirementItem(category="failure_condition", text=line))
        if not items:
            items.append(RequirementItem(category="constraint", text=prompt.strip()))
        return items

    def _iter_requirement_clauses(self, prompt: str) -> Iterator[str]:
        for raw_line in prompt.splitlines():
            line = raw_line.strip(" -*\t")
            if not line:
                continue
            if not _CHINESE_TEXT_RE.search(line):
                yield line
                continue
            for clause in _CHINESE_CLAUSE_BOUNDARY_RE.split(line):
                normalized = clause.strip(" -*\t")
                if normalized:
                    yield normalized

    def _default_validations(self, language: str) -> list[ValidationHook]:
        if language.lower() != "python":
            return [ValidationHook(tool="semantic-review", description="Check the implementation against the natural-language task.")]
        return [
            ValidationHook(tool="ruff", description="Lint and style conformance."),
            ValidationHook(tool="pyright", description="Static type correctness."),
            ValidationHook(tool="pytest", description="Example and regression checks."),
            ValidationHook(tool="hypothesis", description="Property-based checks when a hook is configured.", required=False),
            ValidationHook(tool="semantic-review", description="Explain remaining requirement gaps.", required=True),
        ]


class SpecService:
    def __init__(self, generator: TaskSpecGenerator | None = None) -> None:
        self._generator = generator or TaskSpecGenerator()

    def specify(self, request: TaskSpecifyRequest) -> ApiTaskSpec:
        result = self._generator.generate(TaskSpecificationRequest(prompt=request.natural_language_goal))
        spec = result.spec
        return ApiTaskSpec(
            id=spec.id,
            title=spec.title,
            natural_language_goal=spec.objective,
            inputs=spec.inputs,
            outputs=spec.outputs,
            constraints=spec.constraints,
            edge_cases=spec.edge_cases,
            failure_conditions=spec.failure_conditions,
            verification_strategy=[hook.tool for hook in spec.validations],
        )
