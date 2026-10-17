"""P1 #7 — VerifierPack registry (§2.2 of the general-coach pivot design).

Guards the migration contract: the "code" pack carries the historical
ruff/pyright/pytest chain verbatim, routing is fail-closed (unknown families
fall back to "code", never to an unregistered pack), packs cannot mutate
evidence semantics, and the pipeline delegates to the pack planner.
"""

from __future__ import annotations

import dataclasses
import sys

import pytest

from app.evaluator.models import CheckCommand, EvaluationRequest
from app.evaluator.service import EvaluationPipeline
from app.evaluator.verifiers import (
    DEFAULT_SUBJECT_FAMILY,
    VERIFIER_REGISTRY,
    PythonToolchainPlanner,
    VerifierPack,
    verifier_pack_for,
)
from app.specs.models import TaskSpec


def _minimal_spec() -> TaskSpec:
    return TaskSpec.create(title="t", objective="o")


def _request(**overrides: object) -> EvaluationRequest:
    values: dict[str, object] = {
        "spec": _minimal_spec(),
        "target_path": "/tmp/lesson/exercise.py",
        "code": "x = 1\n",
        "workspace": "/tmp/sandbox",
    }
    values.update(overrides)
    return EvaluationRequest(**values)  # type: ignore[arg-type]


class _StubPlanner:
    def __init__(self, commands: tuple[CheckCommand, ...]) -> None:
        self._commands = commands

    def plan(self, request: EvaluationRequest) -> tuple[CheckCommand, ...]:
        del request
        return self._commands


def test_registry_ships_code_pack_with_python_toolchain_planner() -> None:
    pack = VERIFIER_REGISTRY.get(DEFAULT_SUBJECT_FAMILY)
    assert pack is not None
    assert pack.subject_family == "code"
    assert isinstance(pack.command_planner, PythonToolchainPlanner)
    # P1 #7 migration: the code pack ships without hooks/rubric — those belong
    # to the literature pack (#8) and profile registry (#17).
    assert pack.deterministic_hooks == ()
    assert pack.semantic_rubric is None


def test_routing_is_fail_closed_to_code_pack() -> None:
    for unknown in (None, "", "  ", "LATIN-PROSE", "unknown-family"):
        pack = verifier_pack_for(unknown)
        assert pack is VERIFIER_REGISTRY[DEFAULT_SUBJECT_FAMILY]
    # Normalization: lookup strips whitespace and lowercases before matching.
    assert verifier_pack_for(" code ") is VERIFIER_REGISTRY["code"]
    # P1 #8: literature is now a registered family with its own pack.
    assert verifier_pack_for("literature") is VERIFIER_REGISTRY["literature"]
    assert verifier_pack_for("Literature") is VERIFIER_REGISTRY["literature"]


def test_code_pack_plans_historical_toolchain() -> None:
    commands = PythonToolchainPlanner().plan(_request())
    assert [command.name for command in commands] == ["ruff", "pyright", "pytest"]
    for command in commands:
        assert command.cwd == "/tmp/sandbox"
        assert command.argv, "argv must never be empty"
    # Frozen/venv-less interpreter: bare console scripts, absolute target.
    # (Path.resolve() may expand platform symlink prefixes like /tmp -> /private/tmp.)
    ruff_argv = commands[0].argv
    assert ruff_argv[:2] == ["ruff", "check"]
    assert ruff_argv[-1].endswith("/exercise.py")
    pytest_argv = commands[2].argv
    assert pytest_argv[-2:] == ["-p", "no:cacheprovider"]


def test_code_pack_plans_module_form_for_frozen_sidecar(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    commands = PythonToolchainPlanner().plan(_request(verification_python="/opt/venv/py"))
    assert commands[0].argv[:3] == ["/opt/venv/py", "-m", "ruff"]
    assert commands[1].argv[:3] == ["/opt/venv/py", "-m", "pyright"]
    assert commands[2].argv[:3] == ["/opt/venv/py", "-m", "pytest"]


def test_python_script_check_only_for_real_entrypoint() -> None:
    entrypoint = "x = 1\n\nif __name__ == '__main__':\n    print(x)\n"
    library = "def main() -> int:\n    return 0\n"
    names_entry = [c.name for c in PythonToolchainPlanner().plan(_request(code=entrypoint))]
    names_lib = [c.name for c in PythonToolchainPlanner().plan(_request(code=library))]
    assert "python-script" in names_entry
    assert "python-script" not in names_lib


def test_planner_refuses_missing_sandbox_cwd() -> None:
    with pytest.raises(ValueError, match="sandbox cwd"):
        PythonToolchainPlanner().plan(_request(workspace=None))


def test_verifier_pack_is_frozen_data() -> None:
    pack = verifier_pack_for(None)
    with pytest.raises(dataclasses.FrozenInstanceError):
        pack.subject_family = "literature"  # type: ignore[misc]


def test_pipeline_delegates_plan_commands_to_pack() -> None:
    stub_command = CheckCommand(name="stub-check", argv=["true"], cwd="/tmp/sandbox")
    pack = VerifierPack(
        subject_family="code",
        command_planner=_StubPlanner((stub_command,)),
    )
    pipeline = EvaluationPipeline(verifier_pack=pack)
    planned = pipeline.plan_commands(_request())
    assert [command.name for command in planned] == ["stub-check"]


def test_pipeline_defaults_to_code_pack() -> None:
    pipeline = EvaluationPipeline()
    planned = pipeline.plan_commands(_request())
    assert [command.name for command in planned] == ["ruff", "pyright", "pytest"]
