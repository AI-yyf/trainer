"""Subject-scoped verifier registry (§2.2 of the general-coach pivot design).

Evidence semantics are unchanged and non-negotiable: ``verified`` only ever
comes from a trusted verifier run against real files, human claims never
promote a card, and the trust-source whitelist (``api/routes/learning.py``)
stays the single authority. A pack is *data about which deterministic checks
belong to a subject family* — registering a pack never creates a new trust
source and never loosens the fail-closed routing below.

P1 #7 scope: the existing Python toolchain chain (ruff + pyright + pytest +
optional script run) moves verbatim into the ``"code"`` pack.
P1 #8 scope: the ``"literature"`` pack registers with the deterministic hook
library (``hooks.py``), the anchor-forced rubric lane and the fail-closed
combine rule — an LLM rubric review can never verify on its own. The
trust-source whitelist (``api/routes/learning.py``) is untouched; rubric
sources join it only in P2 (#23).
"""

from __future__ import annotations

import ast
import shutil
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .hooks import Hook, hooks_from_card_config, run_hooks
from .models import CheckCommand, CheckResult, CheckStatus, EvaluationRequest

DEFAULT_SUBJECT_FAMILY = "code"

# Evidence sources a pack may declare for its verdicts. ``ide_current_file`` is
# the historical, whitelisted source (``api/routes/learning.py``); the rubric
# source is declared here but stays *unused for evidence minting* until P2 #23
# widens the whitelist.
IDE_CURRENT_FILE_EVIDENCE_SOURCE = "ide_current_file"
RUBRIC_DUAL_REVIEW_EVIDENCE_SOURCE = "rubric_dual_review"


class CheckCommandPlanner(Protocol):
    """Turns an evaluation request into the deterministic commands to run."""

    def plan(self, request: EvaluationRequest) -> tuple[CheckCommand, ...]: ...


@dataclass(frozen=True)
class RubricItem:
    """One rubric entry: an assertion backed by a verbatim source anchor.

    The anchor is mandatory (fail-fast at construction) so template authors
    cannot ship anchor-free criteria; the reviewer additionally treats an
    anchor *absent from the submission* as Missing — an LLM must never grade
    against text it cannot point to.
    """

    statement: str
    anchor: str
    criteria: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not str(self.statement).strip():
            raise ValueError("rubric item requires a non-empty statement")
        if not str(self.anchor).strip():
            raise ValueError("rubric item requires a non-empty source anchor")
        if len(self.criteria) > 3:
            raise ValueError("rubric item allows at most 3 observable criteria")


@dataclass(frozen=True)
class RubricSpec:
    """Rubric for semantic review, built from a card's acceptance criteria."""

    items: tuple[RubricItem, ...]
    anchor_text: str = ""


@dataclass(slots=True)
class RubricReview:
    """Structured rubric review outcome. ``source`` names the reviewer lane."""

    status: CheckStatus
    summary: str
    matched: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    source: str = "local_rubric"


class RubricReviewer(Protocol):
    """Semantic review lane. LLM judges implement this with a cheap model
    distinct from the coach model (dual-model rule); the default lane is
    deterministic and local."""

    def review(self, spec: RubricSpec, submission: str) -> RubricReview: ...


class LocalRubricReviewer:
    """Anchor-grounded deterministic rubric review.

    A criterion is Matched only when its verbatim anchor appears in the
    submission (or in ``spec.anchor_text`` for excerpt-based anchors); anything
    else is Missing. This lane never hallucinates a pass: no anchor hit, no
    match. The LLM judge lane (#9/#15) must obey the same anchor rule and run
    on a model distinct from the coach.
    """

    source = "local_rubric"

    def review(self, spec: RubricSpec, submission: str) -> RubricReview:
        if not spec.items:
            return RubricReview(
                status=CheckStatus.SKIPPED,
                summary="No rubric items were supplied.",
                source=self.source,
            )
        corpus = f"{spec.anchor_text}\n{submission}"
        matched: list[str] = []
        missing: list[str] = []
        for item in spec.items:
            if item.anchor in corpus:
                matched.append(item.statement)
            else:
                missing.append(item.statement)
        if missing:
            return RubricReview(
                status=CheckStatus.FAILED,
                summary=f"{len(matched)}/{len(spec.items)} rubric items matched; "
                + f"missing anchors for {len(missing)}.",
                matched=matched,
                missing=missing,
                source=self.source,
            )
        return RubricReview(
            status=CheckStatus.PASSED,
            summary=f"All {len(spec.items)} rubric items matched their anchors.",
            matched=matched,
            source=self.source,
        )


@dataclass(slots=True)
class VerifierVerdict:
    """Combined verdict over deterministic hooks + rubric review.

    ``PASSED`` means "verified candidate" — downstream evidence generation
    still routes through the trusted-source whitelist, unchanged.
    """

    status: CheckStatus
    summary: str
    hook_results: tuple[CheckResult, ...] = ()
    rubric_review: RubricReview | None = None


def combine_verdict(
    hook_results: tuple[CheckResult, ...],
    rubric_review: RubricReview | None,
    *,
    human_adopted: bool = False,
) -> VerifierVerdict:
    """Fail-closed combination rule (§2.2 dual-track rule).

    1. Any deterministic hook FAILED/ERROR → FAILED.
    2. Rubric review FAILED/ERROR → FAILED.
    3. A PASSING rubric review **never verifies on its own**: without at least
       one PASSED deterministic hook or an explicit human adoption, the
       verdict stays PENDING ("LLM review alone is not evidence").
    4. Otherwise (all hooks passed + rubric passed or absent) → PASSED.
    """
    failed_hooks = [
        result for result in hook_results if result.status in {CheckStatus.FAILED, CheckStatus.ERROR}
    ]
    if failed_hooks:
        return VerifierVerdict(
            status=CheckStatus.FAILED,
            summary=f"Deterministic hook failed: {failed_hooks[0].name} — {failed_hooks[0].summary}",
            hook_results=hook_results,
            rubric_review=rubric_review,
        )
    if rubric_review is not None and rubric_review.status in {CheckStatus.FAILED, CheckStatus.ERROR}:
        return VerifierVerdict(
            status=CheckStatus.FAILED,
            summary=f"Rubric review failed: {rubric_review.summary}",
            hook_results=hook_results,
            rubric_review=rubric_review,
        )
    deterministic_pass = any(result.status == CheckStatus.PASSED for result in hook_results)
    if not deterministic_pass and not human_adopted:
        return VerifierVerdict(
            status=CheckStatus.PENDING,
            summary=(
                "Semantic review passed, but no deterministic check or human "
                "adoption backs it; LLM review alone is not evidence."
            ),
            hook_results=hook_results,
            rubric_review=rubric_review,
        )
    return VerifierVerdict(
        status=CheckStatus.PASSED,
        summary="Deterministic checks and rubric review both satisfied.",
        hook_results=hook_results,
        rubric_review=rubric_review,
    )


@dataclass(frozen=True)
class LiteratureSubmissionVerifier:
    """Bundle of card-driven hooks + reviewer for one literature submission."""

    hooks: tuple[Hook, ...] = ()
    reviewer: RubricReviewer = field(default_factory=LocalRubricReviewer)
    rubric: RubricSpec | None = None
    human_adopted: bool = False
    locale: str | None = None

    def verify(self, submission: str, *, locale: str | None = None) -> VerifierVerdict:
        effective_locale = locale or self.locale
        hook_results = run_hooks(self.hooks, submission, locale=effective_locale)
        rubric_review = self.reviewer.review(self.rubric, submission) if self.rubric is not None else None
        return combine_verdict(hook_results, rubric_review, human_adopted=self.human_adopted)


@dataclass(frozen=True)
class EmptyCommandPlanner:
    """Subject families verified without shell commands (literature, ...)."""

    def plan(self, request: EvaluationRequest) -> tuple[CheckCommand, ...]:
        del request
        return ()


@dataclass(frozen=True)
class VerifierPack:
    """Per-subject verification bundle.

    ``deterministic_hooks`` holds hook *constructors/configurations* the tool
    route (#9) instantiates per card; ``semantic_rubric`` is reserved for the
    literature flow where each card builds its ``RubricSpec`` from acceptance
    criteria. The code pack ships without them so the migration stays
    behavior-identical.

    ``evidence_source`` names the trust source a verdict of this pack may be
    minted under, and ``persists_practice_evidence`` is the fail-closed
    switch: a pack whose source is not yet whitelisted must NOT write
    training evidence through the tool route. Flipping that flag is P2 #23's
    job, together with the whitelist change — never a local decision.
    """

    subject_family: str
    command_planner: CheckCommandPlanner
    deterministic_hooks: tuple[Any, ...] = field(default=())
    semantic_rubric: Any | None = None
    evidence_source: str = IDE_CURRENT_FILE_EVIDENCE_SOURCE
    persists_practice_evidence: bool = True


class PythonToolchainPlanner:
    """The historical ``EvaluationPipeline.plan_commands`` body, verbatim.

    Kept as its own object so packs stay data while the pipeline stays a thin
    executor. Sandbox discipline is part of the contract: without an explicit
    ``EvaluationRequest.workspace`` the planner refuses to run (never falls
    back to the project or ``os.getcwd()``, so tool caches cannot leak into
    the learner project).
    """

    def plan(self, request: EvaluationRequest) -> tuple[CheckCommand, ...]:
        # Absolute target so tools can check a project file while cwd stays sandboxed.
        target = (
            str(Path(request.target_path).resolve())
            if request.target_path
            else "."
        )
        # Fail-closed: never fall back to project parent / os.getcwd() (ruff/pytest
        # caches like .pytest_cache must not land in the learner project).
        cwd = request.workspace
        if not cwd:
            raise ValueError(
                "EvaluationRequest.workspace sandbox cwd is required; "
                "refusing project/os.getcwd() to avoid tool cache side effects."
            )
        pytest_args = list(request.pytest_args) if request.pytest_args else [target]
        if "-p" not in pytest_args:
            pytest_args = [*pytest_args, "-p", "no:cacheprovider"]
        # PyInstaller's sys.executable is the sidecar launcher, not a Python CLI.
        python = request.verification_python or (
            (shutil.which("python3") or shutil.which("python") or "python3")
            if getattr(sys, "frozen", False) else sys.executable
        )
        modules = bool(request.verification_python or getattr(sys, "frozen", False))
        commands = [
            CheckCommand(name="ruff", argv=[python, "-m", "ruff", "check", target] if modules else ["ruff", "check", target], cwd=cwd),
            CheckCommand(name="pyright", argv=[python, "-m", "pyright", target] if modules else ["pyright", target], cwd=cwd),
            CheckCommand(
                name="pytest",
                argv=[python, "-m", "pytest", *pytest_args],
                cwd=cwd,
            ),
        ]
        if _has_python_script_entrypoint(request.code or ""):
            commands.append(CheckCommand(name="python-script", argv=[python, "-B", target], cwd=cwd))
        return tuple(commands)


def _has_python_script_entrypoint(code: str) -> bool:
    """Run explicit executable entry points, never credit an empty library module."""
    try:
        module = ast.parse(code)
    except SyntaxError:
        return False
    for statement in module.body:
        if not isinstance(statement, ast.If) or not isinstance(statement.test, ast.Compare):
            continue
        test = statement.test
        if len(test.ops) != 1 or not isinstance(test.ops[0], ast.Eq):
            continue
        operands = [test.left, *test.comparators]
        if not (any(isinstance(node, ast.Name) and node.id == "__name__" for node in operands)
                and any(isinstance(node, ast.Constant) and node.value == "__main__"
                        for node in operands)):
            continue
        if any(isinstance(node, (ast.Assert, ast.Call))
               for item in statement.body for node in ast.walk(item)
               if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))):
            return True
    return False


def python_toolchain_pack() -> VerifierPack:
    """The ``"code"`` pack: the pre-registry Python chain, unchanged."""
    return VerifierPack(subject_family=DEFAULT_SUBJECT_FAMILY, command_planner=PythonToolchainPlanner())


def literature_pack() -> VerifierPack:
    """The ``"literature"`` pack (P1 #8).

    No shell commands: verification runs through card-driven deterministic
    hooks and the anchor-forced rubric lane. Hooks are carried as the
    ``hooks_from_card_config`` builder so each card's declarations (word
    window, banned phrases, structure) instantiate per submission; the rubric
    reviewer default is the local anchor-grounded lane, and an LLM judge may
    only take its place by implementing the same ``RubricReviewer`` protocol
    under the dual-model rule.

    ``persists_practice_evidence=False`` is deliberate: the rubric source is
    not in the host-trusted whitelist yet, so this pack's verdicts may be
    reported to the coach but never minted as training evidence (#23).
    """
    return VerifierPack(
        subject_family="literature",
        command_planner=EmptyCommandPlanner(),
        deterministic_hooks=(hooks_from_card_config,),
        evidence_source=RUBRIC_DUAL_REVIEW_EVIDENCE_SOURCE,
        persists_practice_evidence=False,
    )


VERIFIER_REGISTRY: dict[str, VerifierPack] = {
    DEFAULT_SUBJECT_FAMILY: python_toolchain_pack(),
    "literature": literature_pack(),
}


def verifier_pack_for(subject_family: str | None) -> VerifierPack:
    """Fail-closed subject routing.

    Unknown, empty or unregistered families fall back to the ``"code"`` pack —
    the exact behavior before the registry existed. A pack only starts
    applying once it is registered here by name; nothing else in the codebase
    can widen what runs.
    """
    normalized = str(subject_family or "").strip().lower()
    return VERIFIER_REGISTRY.get(normalized, VERIFIER_REGISTRY[DEFAULT_SUBJECT_FAMILY])


def verify_submission_with_pack(
    pack: VerifierPack,
    *,
    submission: str,
    card_config: Mapping[str, Any] | None = None,
    rubric: RubricSpec | None = None,
    reviewer: RubricReviewer | None = None,
    human_adopted: bool = False,
    locale: str | None = None,
    extra_deterministic: tuple[CheckResult, ...] = (),
) -> VerifierVerdict:
    """Run a pack's non-command lane over one submission (P1 #9).

    Command packs are executed by ``EvaluationPipeline``; this entry is for
    packs whose evidence is *in-process* (hooks + rubric). ``extra_deterministic``
    carries caller-side deterministic results (the tool route's acceptance
    signal match) so they count toward the combine rule instead of being
    invisible to it. A malformed card declaration yields no hooks rather than
    an exception — silence must never read as a pass, and
    ``combine_verdict`` then refuses to verify on rubric alone.
    """
    hooks: list[Hook] = []
    config = dict(card_config or {})
    if locale and "locale" not in config:
        config["locale"] = locale
    for builder in pack.deterministic_hooks:
        try:
            hooks.extend(builder(config))
        except Exception:  # noqa: BLE001 - a bad card declaration yields no hooks, never a pass
            continue
    hook_results = (*extra_deterministic, *run_hooks(tuple(hooks), submission, locale=locale))
    resolved_reviewer: RubricReviewer = reviewer if reviewer is not None else LocalRubricReviewer()
    rubric_review = resolved_reviewer.review(rubric, submission) if rubric is not None else None
    return combine_verdict(hook_results, rubric_review, human_adopted=human_adopted)
