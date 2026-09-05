"""Training-to-project handoff governance.

Generates structured handoff content when a training card is passed/completed,
writes evidence to workspace, and integrates with the project plan.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..core.models import TrainingCardCandidateSnapshot
from ..memory.workspace_recovery import live_training_card_title

logger = logging.getLogger(__name__)

FILE_REFERENCE_PATTERN = re.compile(
    r"(?<![\w/\\])"
    r"(?:[A-Za-z]:[\\/])?"
    r"(?:[\w.-]+[\\/])*"
    r"[\w.-]+\.(?:py|js|ts|tsx|jsx|md|yaml|yml|json|html|css)\b"
)


class HandoffStatus(Enum):
    PENDING = "pending"
    GENERATED = "generated"
    WRITTEN = "written"
    COMPLETED = "completed"
    FAILED = "failed"


class TrainingPhase(Enum):
    """The irreversible learning sequence for one handoff."""

    LEARN = "learn"
    TRY = "try"
    VERIFY = "verify"
    REFLECT = "reflect"
    RETURN = "return"


class HandoffTarget(Enum):
    PROJECT_PLAN = "project_plan"
    PROJECT_EVIDENCE = "project_evidence"
    LEARNER_NOTES = "learner_notes"
    PLAN_UPDATE = "plan_update"


@dataclass
class TrainingHandoffContent:
    """Structured, evidence-first content generated from a training card attempt."""
    card_id: str
    card_title: str
    card_type: str
    concept_practiced: str
    key_takeaway: str
    scenario_pack: str
    next_after_completion: str
    next_steps: list[str]
    files_to_touch: list[str]
    verification_checklist: list[str]
    success_signal: str
    project_scope: str
    evidence_location: str
    status: HandoffStatus = HandoffStatus.PENDING
    verification_state: str = "evidence_required"
    completion_claim: str = "No completion claim has been established."
    reflection_prompt: str = ""
    return_with: str = ""
    resume_action: str = ""


@dataclass
class EvidenceRecord:
    """A piece of evidence submitted from training."""
    id: str
    card_id: str
    concept: str
    content: str
    source: str
    created_at: datetime
    project_scope: str | None = None
    verified: bool = False
    verification_source: str = ""
    verified_at: datetime | None = None


@dataclass
class TrainingPhaseEvent:
    """A persisted audit event for one completed learning phase."""

    phase: TrainingPhase
    recorded_at: datetime
    detail: str = ""


@dataclass
class ProjectHandoff:
    """Complete handoff record linking training to project."""
    handoff_id: str
    card_id: str
    card_title: str
    evidence: list[EvidenceRecord]
    handoff_content: TrainingHandoffContent
    status: HandoffStatus
    written_to_workspace: bool = False
    workspace_path: str | None = None
    verification_state: str = "evidence_required"
    return_state: str = "resume_training"
    resume_token: str = ""
    reflected_at: datetime | None = None
    reflection: str = ""
    phase: TrainingPhase = TrainingPhase.LEARN
    phase_history: list[TrainingPhaseEvent] = field(default_factory=list)
    returned_at: datetime | None = None


class TrainingHandoffGenerator:
    """Generates and manages training-to-project handoffs."""

    # Standard handoff sections
    TAKEAWAY_TEMPLATES = {
        "recall": "Key recall from this card: {concept}",
        "practice": "Practice attempt for: {concept}. Verification is still required before crediting completion.",
        "drill": "Drill attempt for: {concept}. Keep the result provisional until the verification checklist is satisfied.",
        "transfer": "Transfer attempt for: {concept}. Return with inspectable evidence before crediting the result.",
    }

    _TRUSTED_VERIFICATION_SOURCES = frozenset(
        {
            "automated_test",
            "evaluator",
            "ide_current_file",
            "server_evaluator",
            "test_runner",
            "verification_service",
        }
    )
    _VERIFICATION_SOURCE_ALIASES = {"current_ide_file": "ide_current_file"}

    def __init__(
        self,
        workspace_root: Path | None = None,
        *,
        leftover_plan: Any | None = None,
        leftover_runtime: dict[str, Any] | None = None,
        leftover_task_title: str = "",
    ) -> None:
        self._workspace_root = workspace_root
        self._handoff_cache: dict[str, ProjectHandoff] = {}
        self._leftover_plan = leftover_plan
        self._leftover_runtime = leftover_runtime if isinstance(leftover_runtime, dict) else {}
        self._leftover_task_title = leftover_task_title

    def _leftover_identity(
        self,
        leftover_plan: Any | None = None,
        leftover_runtime: dict[str, Any] | None = None,
        leftover_task_title: str | None = None,
    ) -> tuple[Any, dict[str, Any], str]:
        plan = leftover_plan if leftover_plan is not None else self._leftover_plan
        runtime = leftover_runtime if leftover_runtime is not None else self._leftover_runtime
        task_title = self._leftover_task_title if leftover_task_title is None else leftover_task_title
        return plan, runtime if isinstance(runtime, dict) else {}, task_title

    def _live_handoff_card_title(
        self,
        card_title: str,
        *,
        leftover_plan: Any | None = None,
        leftover_runtime: dict[str, Any] | None = None,
        leftover_task_title: str | None = None,
    ) -> str:
        plan, runtime, task_title = self._leftover_identity(
            leftover_plan=leftover_plan,
            leftover_runtime=leftover_runtime,
            leftover_task_title=leftover_task_title,
        )
        return live_training_card_title(
            plan=plan,
            runtime=runtime,
            existing=runtime,
            task_title=task_title,
            card_title=card_title,
        )

    def set_workspace_root(self, path: Path) -> None:
        self._workspace_root = path

    @staticmethod
    def _clean_evidence_values(value: object) -> list[str]:
        if value is None:
            return []
        values = value if isinstance(value, (list, tuple, set)) else [value]
        return [str(item).strip() for item in values if str(item).strip()]

    @classmethod
    def _has_recorded_try(cls, learner_result: dict[str, Any]) -> bool:
        if cls._clean_evidence_values(
            learner_result.get("verified_evidence")
            or learner_result.get("verification_output")
            or learner_result.get("evidence")
        ):
            return True
        return any(
            key in learner_result
            for key in ("correct", "answer", "response", "submission", "attempt", "result")
        )

    @staticmethod
    def _phase_sequence() -> tuple[TrainingPhase, ...]:
        return (
            TrainingPhase.LEARN,
            TrainingPhase.TRY,
            TrainingPhase.VERIFY,
            TrainingPhase.REFLECT,
            TrainingPhase.RETURN,
        )

    @classmethod
    def _initial_phase(cls, learner_result: dict[str, Any]) -> TrainingPhase:
        if cls._has_trusted_verification(learner_result):
            return TrainingPhase.VERIFY
        if cls._has_recorded_try(learner_result):
            return TrainingPhase.TRY
        return TrainingPhase.LEARN

    @classmethod
    def _phase_history_for(
        cls,
        phase: TrainingPhase,
        recorded_at: datetime,
    ) -> list[TrainingPhaseEvent]:
        details = {
            TrainingPhase.LEARN: "Card handoff generated.",
            TrainingPhase.TRY: "Learner submitted a practice attempt.",
            TrainingPhase.VERIFY: "Trusted verifier attested submitted evidence.",
            TrainingPhase.REFLECT: "Learner recorded a reflection.",
            TrainingPhase.RETURN: "Training handoff returned to the coach.",
        }
        history: list[TrainingPhaseEvent] = []
        for candidate in cls._phase_sequence():
            history.append(
                TrainingPhaseEvent(
                    phase=candidate,
                    recorded_at=recorded_at,
                    detail=details[candidate],
                )
            )
            if candidate is phase:
                break
        return history

    @classmethod
    def _advance_phase(
        cls,
        handoff: ProjectHandoff,
        next_phase: TrainingPhase,
        *,
        detail: str,
        recorded_at: datetime,
    ) -> None:
        sequence = cls._phase_sequence()
        current_index = sequence.index(handoff.phase)
        expected = sequence[current_index + 1] if current_index + 1 < len(sequence) else None
        if expected is not next_phase:
            expected_name = expected.value if expected is not None else "no further phase"
            raise ValueError(
                f"Cannot advance training handoff from {handoff.phase.value} to {next_phase.value}; "
                f"expected {expected_name}."
            )
        handoff.phase = next_phase
        handoff.phase_history.append(
            TrainingPhaseEvent(phase=next_phase, recorded_at=recorded_at, detail=detail)
        )

    def _sync_handoff_verification_state(self, handoff: ProjectHandoff, state: str) -> None:
        handoff.verification_state = state
        handoff.return_state = self._return_state(state)
        handoff.handoff_content.verification_state = state
        handoff.handoff_content.completion_claim = self._completion_claim(
            handoff.handoff_content.concept_practiced,
            state,
        )
        handoff.handoff_content.success_signal = self._generate_success_signal(
            TrainingCardCandidateSnapshot(
                card_id=handoff.card_id,
                target_skill=handoff.handoff_content.concept_practiced,
            ),
            {},
            0.0,
            verification_state=state,
        )

    def _persist_transition(self, handoff: ProjectHandoff) -> None:
        if self._workspace_root is not None:
            persisted_path = self.write_handoff_to_workspace(handoff)
            if persisted_path is None or handoff.status is HandoffStatus.FAILED:
                raise OSError(f"Unable to persist training handoff {handoff.handoff_id}.")
        self._handoff_cache[handoff.handoff_id] = handoff

    @classmethod
    def _verification_source(cls, learner_result: dict[str, Any]) -> str:
        return cls._canonical_verification_source(
            str(
                learner_result.get("verification_source")
                or learner_result.get("evidence_source")
                or "learner_submission"
            )
        )

    @classmethod
    def _canonical_verification_source(cls, value: object) -> str:
        source = str(value or "learner_submission").strip().lower()
        return cls._VERIFICATION_SOURCE_ALIASES.get(source, source)

    @classmethod
    def _has_trusted_verification(cls, learner_result: dict[str, Any]) -> bool:
        """A client-side success flag cannot establish a completion claim.

        A verifier must identify itself, the result must include a non-empty
        inspectable artifact, and the evaluator must explicitly attest to it.
        This intentionally rejects a learner-provided ``verified=True`` flag.
        """
        source = cls._verification_source(learner_result)
        evidence = cls._clean_evidence_values(
            learner_result.get("verified_evidence")
            or learner_result.get("verification_output")
            or learner_result.get("evidence")
        )
        return bool(
            learner_result.get("verified_by_evaluator")
            and source in cls._TRUSTED_VERIFICATION_SOURCES
            and evidence
        )

    @classmethod
    def _verification_state(cls, learner_result: dict[str, Any]) -> str:
        if cls._has_trusted_verification(learner_result):
            return "verified"
        if cls._clean_evidence_values(
            learner_result.get("evidence")
            or learner_result.get("verification_output")
            or learner_result.get("verified_evidence")
        ):
            return "verification_required"
        if learner_result.get("correct") is False and learner_result:
            return "blocked"
        return "evidence_required"

    @staticmethod
    def _safe_path_segment(value: str, fallback: str) -> str:
        """Return a stable path segment without letting card data escape the workspace."""
        normalized = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value or "").strip())
        normalized = normalized.strip(".-")
        return normalized[:96] or fallback

    @staticmethod
    def _parse_datetime(value: object) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None

    def _completion_claim(self, concept: str, verification_state: str) -> str:
        if verification_state == "verified":
            return (
                f"Verified evidence supports this card result for {concept}. "
                "It is not a claim of durable mastery; schedule later recall or transfer."
            )
        if verification_state == "blocked":
            return f"This card is not complete for {concept}; return with the first blocker and retry evidence."
        if verification_state == "verification_required":
            return (
                f"A learner result for {concept} was received, but it needs server-side verification "
                "before it can count as card completion."
            )
        return f"No verifiable evidence was returned for {concept}; the card remains in progress."

    @staticmethod
    def _return_state(verification_state: str) -> str:
        return {
            "verified": "return_to_coach",
            "blocked": "resume_training",
            "verification_required": "verify_then_return",
            "evidence_required": "resume_training",
        }.get(verification_state, "resume_training")

    def generate_handoff(
        self,
        card: TrainingCardCandidateSnapshot,
        learner_result: dict[str, Any],
        mastery_delta: float = 0.0,
    ) -> TrainingHandoffContent:
        """Generate handoff content from a completed training card.

        Args:
            card: The training card that was completed
            learner_result: The learner's answer/result
            mastery_delta: How much mastery improved

        Returns:
            Structured handoff content ready to write to project
        """
        concept = getattr(card, "concept", "") or getattr(card, "target_skill", "") or "general"
        card_type = getattr(card, "card_type", "flash") or "flash"
        verification_state = self._verification_state(learner_result)

        # Determine key takeaway based on card type
        template_key = card_type if card_type in self.TAKEAWAY_TEMPLATES else "practice"
        takeaway = self.TAKEAWAY_TEMPLATES[template_key].format(
            concept=concept,
            verification=getattr(card, "validation_method", ""),
        )

        # Extract next steps from card
        next_steps = self._extract_next_steps(card)

        # Identify files to touch
        files_to_touch = self._extract_files_to_touch(card)

        # Generate verification checklist
        verification = self._generate_verification_checklist(card, learner_result)

        # Determine success signal
        success_signal = self._generate_success_signal(
            card,
            learner_result,
            mastery_delta,
            verification_state=verification_state,
        )

        # Determine project scope
        project_scope = getattr(card, "project_scope", "current") or "current"
        scenario_pack = getattr(card, "scenario_pack", "") or ""
        card_next_after_completion = getattr(card, "next_after_completion", "") or ""

        # Generate evidence location
        evidence_location = self._generate_evidence_location(card, project_scope)

        live_card_title = self._live_handoff_card_title(
            getattr(card, "title", "") or getattr(card, "question", "") or "Training Card"
        )
        content = TrainingHandoffContent(
            card_id=card.card_id,
            card_title=live_card_title or "Training Card",
            card_type=card_type,
            concept_practiced=concept,
            key_takeaway=takeaway,
            scenario_pack=scenario_pack,
            next_after_completion=card_next_after_completion,
            next_steps=next_steps,
            files_to_touch=files_to_touch,
            verification_checklist=verification,
            success_signal=success_signal,
            project_scope=project_scope,
            evidence_location=evidence_location,
            status=HandoffStatus.GENERATED,
            verification_state=verification_state,
            completion_claim=self._completion_claim(concept, verification_state),
            reflection_prompt=getattr(card, "reflection_prompt", "") or "",
            return_with=getattr(card, "return_with", "") or "",
            resume_action=(
                "Return with the verifier output and one reflection on what changed."
                if verification_state == "verified"
                else "Resume this card from the first unfinished verification step."
            ),
        )

        logger.info(
            f"Generated handoff for card {card.card_id}: "
            f"concept={concept}, scope={project_scope}"
        )
        return content

    def _extract_next_steps(self, card: TrainingCardCandidateSnapshot) -> list[str]:
        """Extract next steps from card metadata."""
        steps = []

        # Priority: explicit next_steps field > deliverable > validation_method
        explicit = getattr(card, "next_steps", None)
        if explicit and isinstance(explicit, list):
            steps.extend([str(s) for s in explicit if s])
        elif explicit and isinstance(explicit, str):
            steps.append(explicit)

        deliverable = getattr(card, "deliverable", None)
        if deliverable and not steps:
            steps.append(f"Deliver: {deliverable}")

        validation = getattr(card, "validation_method", None)
        if validation and not steps:
            steps.append(f"Verify by: {validation}")

        # Fallback steps based on card type
        if not steps:
            card_type = getattr(card, "card_type", "flash") or "flash"
            if card_type == "practice":
                steps.append("Apply concept to current project")
            elif card_type == "drill":
                steps.append("Repeat drill with variation")
            elif card_type == "transfer":
                steps.append("Transfer to project task")

        return steps[:5]  # Limit to 5 steps

    def _extract_files_to_touch(self, card: TrainingCardCandidateSnapshot) -> list[str]:
        """Extract file paths mentioned in card."""
        files = []

        # Look for file references in various fields
        for field_name in ["deliverable", "problem_statement", "hint", "validation_method"]:
            value = getattr(card, field_name, None)
            if value and isinstance(value, str):
                files.extend(match.group(0) for match in FILE_REFERENCE_PATTERN.finditer(value))

        # Also check explicit files field
        explicit_files = getattr(card, "files_to_touch", None)
        if explicit_files and isinstance(explicit_files, list):
            files.extend([str(f) for f in explicit_files if f])

        return list(dict.fromkeys(files))[:10]  # Dedupe and limit

    def _generate_verification_checklist(
        self,
        card: TrainingCardCandidateSnapshot,
        learner_result: dict[str, Any],
    ) -> list[str]:
        """Generate verification checklist for handoff."""
        checklist = []

        validation = getattr(card, "validation_method", "")
        if validation:
            checklist.append(f"Verify: {validation}")

        evidence = self._clean_evidence_values(
            learner_result.get("verified_evidence")
            or learner_result.get("verification_output")
            or learner_result.get("evidence")
        )
        if evidence:
            checklist.append("Inspect the submitted evidence against the declared validation method")
        else:
            checklist.append("Submit one inspectable result before crediting the card")

        if not self._has_trusted_verification(learner_result):
            checklist.append("Obtain server-side or evaluator verification; learner self-report is not sufficient")

        # Add concept-specific checks
        concept = getattr(card, "concept", "") or getattr(card, "target_skill", "")
        if concept:
            checklist.append(f"Can explain: {concept}")
            checklist.append(f"Can apply: {concept}")

        # Default checklist if nothing specific
        if not checklist:
            checklist.extend([
                "Submit one inspectable result",
                "Run the declared validation",
                "Record a reflection before selecting the next card",
            ])

        return checklist[:6]

    def _generate_success_signal(
        self,
        card: TrainingCardCandidateSnapshot,
        learner_result: dict[str, Any],
        mastery_delta: float,
        *,
        verification_state: str,
    ) -> str:
        """Describe evidence state without promoting a self-report into mastery."""
        concept = getattr(card, "concept", "") or getattr(card, "target_skill", "") or "the concept"

        if verification_state == "verified":
            return (
                f"Verified evidence supports one result for {concept}. "
                "Use later recall or transfer to assess durable mastery."
            )
        if verification_state == "verification_required":
            return f"A result for {concept} is awaiting server-side verification."
        if verification_state == "blocked":
            return f"Retry {concept} from the first reported blocker."
        return f"Return one inspectable result for {concept} before this card can be credited."

    def _generate_evidence_location(self, card: TrainingCardCandidateSnapshot, project_scope: str) -> str:
        """Generate the workspace path for evidence storage."""
        base = "notes/training-handoffs"
        if project_scope == "global":
            return f"{base}/global"
        elif project_scope == "sandbox":
            return f"{base}/sandbox"
        else:
            return f"{base}/current"

    def build_handoff_record(
        self,
        card: TrainingCardCandidateSnapshot,
        learner_result: dict[str, Any],
        mastery_delta: float = 0.0,
    ) -> ProjectHandoff:
        """Build a complete handoff record from card completion."""
        content = self.generate_handoff(card, learner_result, mastery_delta)

        evidence: list[EvidenceRecord] = []
        created_at = datetime.now(timezone.utc)
        phase = self._initial_phase(learner_result)
        evidence_values = self._clean_evidence_values(
            learner_result.get("verified_evidence")
            or learner_result.get("verification_output")
            or learner_result.get("evidence")
        )
        verification_source = self._verification_source(learner_result)
        trusted_verification = self._has_trusted_verification(learner_result)
        if evidence_values:
            for ev in evidence_values:
                evidence.append(EvidenceRecord(
                    id=f"ev-{card.card_id}-{uuid4().hex[:10]}",
                    card_id=card.card_id,
                    concept=getattr(card, "concept", "") or "",
                    content=str(ev),
                    source=verification_source,
                    created_at=created_at,
                    project_scope=getattr(card, "project_scope", None),
                    verified=trusted_verification,
                    verification_source=verification_source if trusted_verification else "",
                    verified_at=created_at if trusted_verification else None,
                ))

        handoff = ProjectHandoff(
            handoff_id=f"handoff-{card.card_id}-{uuid4().hex[:12]}",
            card_id=card.card_id,
            card_title=self._live_handoff_card_title(getattr(card, "title", "") or ""),
            evidence=evidence,
            handoff_content=content,
            status=HandoffStatus.GENERATED,
            verification_state=content.verification_state,
            return_state=self._return_state(content.verification_state),
            resume_token=f"resume-{uuid4().hex}",
            phase=phase,
            phase_history=self._phase_history_for(phase, created_at),
        )

        self._handoff_cache[handoff.handoff_id] = handoff
        return handoff

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)

    @staticmethod
    def _handoff_payload(handoff: ProjectHandoff) -> dict[str, Any]:
        content = handoff.handoff_content
        return {
            "version": 2,
            "handoff_id": handoff.handoff_id,
            "card_id": handoff.card_id,
            "card_title": handoff.card_title,
            "status": handoff.status.value,
            "written_to_workspace": handoff.written_to_workspace,
            "workspace_path": handoff.workspace_path,
            "verification_state": handoff.verification_state,
            "return_state": handoff.return_state,
            "resume_token": handoff.resume_token,
            "reflected_at": handoff.reflected_at.isoformat() if handoff.reflected_at else None,
            "reflection": handoff.reflection,
            "learning_phase": handoff.phase.value,
            "phase_history": [
                {
                    "phase": event.phase.value,
                    "recorded_at": event.recorded_at.isoformat(),
                    "detail": event.detail,
                }
                for event in handoff.phase_history
            ],
            "returned_at": handoff.returned_at.isoformat() if handoff.returned_at else None,
            "handoff_content": {
                "card_id": content.card_id,
                "card_title": content.card_title,
                "card_type": content.card_type,
                "concept_practiced": content.concept_practiced,
                "key_takeaway": content.key_takeaway,
                "scenario_pack": content.scenario_pack,
                "next_after_completion": content.next_after_completion,
                "next_steps": content.next_steps,
                "files_to_touch": content.files_to_touch,
                "verification_checklist": content.verification_checklist,
                "success_signal": content.success_signal,
                "project_scope": content.project_scope,
                "evidence_location": content.evidence_location,
                "status": content.status.value,
                "verification_state": content.verification_state,
                "completion_claim": content.completion_claim,
                "reflection_prompt": content.reflection_prompt,
                "return_with": content.return_with,
                "resume_action": content.resume_action,
            },
            "evidence": [
                {
                    "id": record.id,
                    "card_id": record.card_id,
                    "concept": record.concept,
                    "content": record.content,
                    "source": record.source,
                    "created_at": record.created_at.isoformat(),
                    "project_scope": record.project_scope,
                    "verified": record.verified,
                    "verification_source": record.verification_source,
                    "verified_at": record.verified_at.isoformat() if record.verified_at else None,
                }
                for record in handoff.evidence
            ],
        }

    @staticmethod
    def _parse_phase(value: object) -> TrainingPhase | None:
        try:
            return TrainingPhase(str(value))
        except ValueError:
            return None

    @classmethod
    def _restored_phase(
        cls,
        payload: dict[str, Any],
        *,
        verification_state: str,
        reflection: str,
        status: HandoffStatus,
    ) -> TrainingPhase:
        requested = cls._parse_phase(payload.get("learning_phase"))
        verified = verification_state == "verified"
        reflected = bool(reflection.strip())
        returned = status is HandoffStatus.COMPLETED or bool(payload.get("returned_at"))

        if requested is TrainingPhase.RETURN and verified and reflected and returned:
            return requested
        if requested is TrainingPhase.REFLECT and verified and reflected:
            return requested
        if requested is TrainingPhase.VERIFY and verified:
            return requested
        if requested is TrainingPhase.TRY:
            return requested
        if requested is TrainingPhase.LEARN:
            return requested

        if verified:
            return TrainingPhase.REFLECT if reflected else TrainingPhase.VERIFY
        evidence = payload.get("evidence")
        return TrainingPhase.TRY if isinstance(evidence, list) and evidence else TrainingPhase.LEARN

    @classmethod
    def _restored_phase_history(
        cls,
        value: object,
        *,
        phase: TrainingPhase,
        fallback_at: datetime,
    ) -> list[TrainingPhaseEvent]:
        if isinstance(value, list):
            events: list[TrainingPhaseEvent] = []
            for item in value:
                if not isinstance(item, dict):
                    events = []
                    break
                event_phase = cls._parse_phase(item.get("phase"))
                recorded_at = cls._parse_datetime(item.get("recorded_at"))
                if event_phase is None or recorded_at is None:
                    events = []
                    break
                events.append(
                    TrainingPhaseEvent(
                        phase=event_phase,
                        recorded_at=recorded_at,
                        detail=str(item.get("detail") or ""),
                    )
                )
            expected = list(cls._phase_sequence()[: len(events)])
            if events and [event.phase for event in events] == expected and events[-1].phase is phase:
                return events

        return [
            TrainingPhaseEvent(
                phase=phase,
                recorded_at=fallback_at,
                detail="Recovered handoff state; earlier phase history is unavailable.",
            )
        ]

    @classmethod
    def _handoff_from_payload(cls, payload: dict[str, Any]) -> ProjectHandoff | None:
        raw_content = payload.get("handoff_content")
        if not isinstance(raw_content, dict):
            return None
        try:
            content = TrainingHandoffContent(
                card_id=str(raw_content.get("card_id") or payload.get("card_id") or ""),
                card_title=str(raw_content.get("card_title") or payload.get("card_title") or "Training Card"),
                card_type=str(raw_content.get("card_type") or "practice"),
                concept_practiced=str(raw_content.get("concept_practiced") or "general"),
                key_takeaway=str(raw_content.get("key_takeaway") or ""),
                scenario_pack=str(raw_content.get("scenario_pack") or ""),
                next_after_completion=str(raw_content.get("next_after_completion") or ""),
                next_steps=[str(item) for item in raw_content.get("next_steps", []) if str(item).strip()],
                files_to_touch=[str(item) for item in raw_content.get("files_to_touch", []) if str(item).strip()],
                verification_checklist=[
                    str(item) for item in raw_content.get("verification_checklist", []) if str(item).strip()
                ],
                success_signal=str(raw_content.get("success_signal") or ""),
                project_scope=str(raw_content.get("project_scope") or "current"),
                evidence_location=str(raw_content.get("evidence_location") or "notes/training-handoffs/current"),
                status=HandoffStatus(str(raw_content.get("status") or HandoffStatus.GENERATED.value)),
                verification_state=str(raw_content.get("verification_state") or "evidence_required"),
                completion_claim=str(raw_content.get("completion_claim") or "No completion claim has been established."),
                reflection_prompt=str(raw_content.get("reflection_prompt") or ""),
                return_with=str(raw_content.get("return_with") or ""),
                resume_action=str(raw_content.get("resume_action") or ""),
            )
            evidence = [
                EvidenceRecord(
                    id=str(item.get("id") or ""),
                    card_id=str(item.get("card_id") or content.card_id),
                    concept=str(item.get("concept") or ""),
                    content=str(item.get("content") or ""),
                    source=str(item.get("source") or "learner_submission"),
                    created_at=cls._parse_datetime(item.get("created_at")) or datetime.now(timezone.utc),
                    project_scope=str(item.get("project_scope")) if item.get("project_scope") else None,
                    verified=bool(item.get("verified")),
                    verification_source=str(item.get("verification_source") or ""),
                    verified_at=cls._parse_datetime(item.get("verified_at")),
                )
                for item in payload.get("evidence", [])
                if isinstance(item, dict)
            ]
            status = HandoffStatus(str(payload.get("status") or HandoffStatus.GENERATED.value))
            verification_state = str(payload.get("verification_state") or content.verification_state)
            reflection = str(payload.get("reflection") or "")
            reflected_at = cls._parse_datetime(payload.get("reflected_at"))
            phase = cls._restored_phase(
                payload,
                verification_state=verification_state,
                reflection=reflection,
                status=status,
            )
            phase_history = cls._restored_phase_history(
                payload.get("phase_history"),
                phase=phase,
                fallback_at=reflected_at or datetime.now(timezone.utc),
            )
            return ProjectHandoff(
                handoff_id=str(payload.get("handoff_id") or ""),
                card_id=str(payload.get("card_id") or content.card_id),
                card_title=str(payload.get("card_title") or content.card_title),
                evidence=evidence,
                handoff_content=content,
                status=status,
                written_to_workspace=bool(payload.get("written_to_workspace")),
                workspace_path=str(payload.get("workspace_path")) if payload.get("workspace_path") else None,
                verification_state=verification_state,
                return_state=str(payload.get("return_state") or cls._return_state(verification_state)),
                resume_token=str(payload.get("resume_token") or f"resume-{uuid4().hex}"),
                reflected_at=reflected_at,
                reflection=reflection,
                phase=phase,
                phase_history=phase_history,
                returned_at=cls._parse_datetime(payload.get("returned_at")),
            )
        except (TypeError, ValueError):
            logger.warning("Unable to restore persisted training handoff", exc_info=True)
            return None

    def resume_handoff(
        self,
        handoff_id: str,
        workspace_root: Path | None = None,
    ) -> ProjectHandoff | None:
        """Restore a handoff after an interruption without upgrading its evidence state."""
        if handoff_id in self._handoff_cache:
            return self._handoff_cache[handoff_id]
        root = workspace_root or self._workspace_root
        if not root:
            return None
        handoff_root = root / "notes" / "training-handoffs"
        if not handoff_root.is_dir():
            return None
        for record_path in handoff_root.rglob("*.json"):
            try:
                payload = json.loads(record_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict) or payload.get("handoff_id") != handoff_id:
                continue
            handoff = self._handoff_from_payload(payload)
            if handoff is not None:
                self._handoff_cache[handoff.handoff_id] = handoff
                return handoff
        return None

    def hydrate_handoff(self, payload: dict[str, Any]) -> ProjectHandoff | None:
        """Restore a persisted handoff into this generator's transition cache."""
        handoff = self._handoff_from_payload(payload)
        if handoff is not None and handoff.handoff_id:
            self._handoff_cache[handoff.handoff_id] = handoff
        return handoff

    def record_try(
        self,
        handoff_id: str,
        attempt: str | list[str],
        *,
        source: str = "learner_submission",
    ) -> ProjectHandoff | None:
        """Record an inspectable attempt before any verification can advance."""
        handoff = self.resume_handoff(handoff_id)
        if handoff is None:
            return None
        if handoff.phase is not TrainingPhase.LEARN:
            raise ValueError("A training attempt can only be recorded after Learn and before Verify.")

        values = self._clean_evidence_values(attempt)
        if not values:
            raise ValueError("A training attempt needs an inspectable result.")
        now = datetime.now(timezone.utc)
        normalized_source = str(source or "learner_submission").strip().lower()
        for value in values:
            handoff.evidence.append(
                EvidenceRecord(
                    id=f"ev-{handoff.card_id}-{uuid4().hex[:10]}",
                    card_id=handoff.card_id,
                    concept=handoff.handoff_content.concept_practiced,
                    content=value,
                    source=normalized_source,
                    created_at=now,
                    project_scope=handoff.handoff_content.project_scope,
                )
            )
        self._advance_phase(
            handoff,
            TrainingPhase.TRY,
            detail="Learner submitted an inspectable practice attempt.",
            recorded_at=now,
        )
        self._sync_handoff_verification_state(handoff, "verification_required")
        self._persist_transition(handoff)
        return handoff

    def record_verification(
        self,
        handoff_id: str,
        evidence: str | list[str],
        *,
        evidence_source: str,
        verified_by_evaluator: bool,
        reflection: str = "",
    ) -> ProjectHandoff | None:
        """Attach verifier evidence without permitting a Learn-to-Verify jump.

        Calling this with a learner-controlled source or without evaluator
        attestation leaves the handoff in ``verification_required``.
        """
        handoff = self.resume_handoff(handoff_id)
        if handoff is None:
            return None
        if handoff.phase is TrainingPhase.LEARN:
            logger.warning("Rejected verification before a training attempt for %s", handoff_id)
            return handoff
        if handoff.phase is TrainingPhase.RETURN:
            logger.warning("Rejected verification after a completed training return for %s", handoff_id)
            return handoff
        values = self._clean_evidence_values(evidence)
        source = self._canonical_verification_source(evidence_source)
        trusted = bool(values and verified_by_evaluator and source in self._TRUSTED_VERIFICATION_SOURCES)
        now = datetime.now(timezone.utc)
        for value in values:
            handoff.evidence.append(
                EvidenceRecord(
                    id=f"ev-{handoff.card_id}-{uuid4().hex[:10]}",
                    card_id=handoff.card_id,
                    concept=handoff.handoff_content.concept_practiced,
                    content=value,
                    source=source,
                    created_at=now,
                    project_scope=handoff.handoff_content.project_scope,
                    verified=trusted,
                    verification_source=source if trusted else "",
                    verified_at=now if trusted else None,
                )
            )
        if trusted and handoff.phase is TrainingPhase.TRY:
            self._advance_phase(
                handoff,
                TrainingPhase.VERIFY,
                detail=f"Trusted verification recorded from {source}.",
                recorded_at=now,
            )
        state = "verified" if trusted else handoff.verification_state
        if values and not trusted and state != "verified":
            state = "verification_required"
        self._sync_handoff_verification_state(handoff, state)

        reflection_text = reflection.strip()
        if reflection_text and handoff.phase is TrainingPhase.VERIFY and state == "verified":
            handoff.reflection = reflection_text
            handoff.reflected_at = now
            self._advance_phase(
                handoff,
                TrainingPhase.REFLECT,
                detail="Learner recorded a reflection after trusted verification.",
                recorded_at=now,
            )
        elif reflection_text:
            logger.warning("Reflection was not recorded before trusted verification for %s", handoff_id)
        self._persist_transition(handoff)
        return handoff

    def record_reflection(self, handoff_id: str, reflection: str) -> ProjectHandoff | None:
        """Record reflection only after trusted verification has completed."""
        handoff = self.resume_handoff(handoff_id)
        if handoff is None:
            return None
        if handoff.phase is not TrainingPhase.VERIFY or handoff.verification_state != "verified":
            raise ValueError("Reflection requires trusted verification after a recorded training attempt.")
        reflection_text = reflection.strip()
        if not reflection_text:
            raise ValueError("A reflection is required before returning this training handoff.")
        now = datetime.now(timezone.utc)
        handoff.reflection = reflection_text
        handoff.reflected_at = now
        self._advance_phase(
            handoff,
            TrainingPhase.REFLECT,
            detail="Learner recorded a reflection after trusted verification.",
            recorded_at=now,
        )
        self._persist_transition(handoff)
        return handoff

    def return_handoff(self, handoff_id: str) -> ProjectHandoff | None:
        """Complete Return only after the reflection phase is durable."""
        handoff = self.resume_handoff(handoff_id)
        if handoff is None:
            return None
        if handoff.phase is not TrainingPhase.REFLECT:
            raise ValueError("Return requires Learn, Try, trusted Verify, and Reflect in that order.")
        now = datetime.now(timezone.utc)
        self._advance_phase(
            handoff,
            TrainingPhase.RETURN,
            detail="Training handoff returned after reflection.",
            recorded_at=now,
        )
        handoff.returned_at = now
        handoff.status = HandoffStatus.COMPLETED
        self._persist_transition(handoff)
        return handoff

    def complete_return(self, handoff_id: str) -> ProjectHandoff | None:
        """Compatibility alias for the explicit Return transition."""
        return self.return_handoff(handoff_id)

    def write_handoff_to_workspace(
        self,
        handoff: ProjectHandoff,
        workspace_root: Path | None = None,
        *,
        leftover_plan: Any | None = None,
        leftover_runtime: dict[str, Any] | None = None,
        leftover_task_title: str | None = None,
    ) -> Path | None:
        """Write handoff evidence to workspace.

        Returns the path where evidence was written, or None if failed.
        """
        root = workspace_root or self._workspace_root
        if not root:
            logger.warning("No workspace root set, cannot write handoff")
            return None

        try:
            safe_scope = self._safe_path_segment(handoff.handoff_content.project_scope, "current")
            safe_card_id = self._safe_path_segment(handoff.card_id, "training-card")
            evidence_dir = root / "notes" / "training-handoffs" / safe_scope
            evidence_dir.mkdir(parents=True, exist_ok=True)

            if handoff.status is not HandoffStatus.COMPLETED:
                handoff.status = HandoffStatus.WRITTEN
            handoff.written_to_workspace = True
            handoff_file = evidence_dir / f"{safe_card_id}.md"
            handoff_content = self._render_handoff_markdown(
                handoff,
                leftover_plan=leftover_plan,
                leftover_runtime=leftover_runtime,
                leftover_task_title=leftover_task_title,
            )
            self._atomic_write(handoff_file, handoff_content)

            for ev in handoff.evidence:
                ev_file = evidence_dir / f"{self._safe_path_segment(ev.id, 'evidence')}.txt"
                self._atomic_write(ev_file, ev.content)

            handoff.workspace_path = str(handoff_file)
            payload_file = evidence_dir / f"{safe_card_id}.json"
            self._atomic_write(
                payload_file,
                json.dumps(self._handoff_payload(handoff), ensure_ascii=False, indent=2, sort_keys=True),
            )
            self._handoff_cache[handoff.handoff_id] = handoff

            logger.info(f"Wrote handoff to {handoff_file}")
            return handoff_file

        except Exception as e:
            logger.error(f"Failed to write handoff to workspace: {e}")
            handoff.status = HandoffStatus.FAILED
            handoff.written_to_workspace = False
            return None

    def _render_handoff_markdown(
        self,
        handoff: ProjectHandoff,
        *,
        leftover_plan: Any | None = None,
        leftover_runtime: dict[str, Any] | None = None,
        leftover_task_title: str | None = None,
    ) -> str:
        """Render handoff as markdown for workspace storage."""
        content = handoff.handoff_content
        live_title = self._live_handoff_card_title(
            content.card_title,
            leftover_plan=leftover_plan,
            leftover_runtime=leftover_runtime,
            leftover_task_title=leftover_task_title,
        )
        heading = f"# Training Handoff: {live_title}" if live_title else "# Training Handoff"
        lines = [
            heading,
            "",
            f"**Card ID:** {content.card_id}",
            f"**Type:** {content.card_type}",
            f"**Concept:** {content.concept_practiced}",
            f"**Status:** {handoff.status.value}",
            f"**Learning Phase:** {handoff.phase.value}",
            f"**Verification State:** {handoff.verification_state}",
            f"**Return State:** {handoff.return_state}",
            f"**Generated:** {datetime.now(timezone.utc).isoformat()}",
            "",
            "## Context",
        ]
        if content.scenario_pack:
            lines.append(f"**Scenario Pack:** {content.scenario_pack}")
        lines.extend([
            f"**Project Scope:** {content.project_scope}",
            f"**Evidence Location:** `{content.evidence_location}`",
        ])
        if content.next_after_completion:
            lines.append(f"**Next After Completion:** {content.next_after_completion}")

        lines.extend([
            "",
            "## Key Takeaway",
            content.key_takeaway,
            "",
            "## Evidence Claim",
            content.completion_claim,
            "",
            "## Next Steps",
        ])
        for i, step in enumerate(content.next_steps, 1):
            lines.append(f"{i}. {step}")

        lines.extend([
            "",
            "## Verification Checklist",
        ])
        for item in content.verification_checklist:
            lines.append(f"- [ ] {item}")

        if content.reflection_prompt:
            lines.extend([
                "",
                "## Reflect",
                content.reflection_prompt,
            ])
        if handoff.reflection:
            lines.extend([
                "",
                "## Reflection Result",
                handoff.reflection,
            ])
        if content.return_with or content.resume_action:
            lines.extend([
                "",
                "## Return / Resume",
                f"**Return with:** {content.return_with or 'One inspectable verification result.'}",
                f"**Resume action:** {content.resume_action or 'Resume the first unfinished step.'}",
            ])

        if content.files_to_touch:
            lines.extend([
                "",
                "## Files to Touch",
            ])
            for f in content.files_to_touch:
                lines.append(f"- `{f}`")

        lines.extend([
            "",
            "## Success Signal",
            content.success_signal,
            "",
            "## Evidence",
        ])

        if handoff.evidence:
            for ev in handoff.evidence:
                state = "verified" if ev.verified else "unverified"
                lines.append(f"- [{state}] [{ev.id}] {ev.content[:100]}...")
        else:
            lines.append("*No evidence recorded yet*")

        lines.extend([
            "",
            "---",
            "*Auto-generated by Trainer handoff system*",
        ])

        return "\n".join(lines)

    def get_pending_handoffs(self) -> list[ProjectHandoff]:
        """Get all handoffs that haven't been written to workspace."""
        return [
            h for h in self._handoff_cache.values()
            if h.status == HandoffStatus.GENERATED
        ]

    def get_handoff(self, handoff_id: str) -> ProjectHandoff | None:
        """Get a specific handoff by ID."""
        return self._handoff_cache.get(handoff_id)
