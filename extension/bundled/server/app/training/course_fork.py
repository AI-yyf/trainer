"""Course fork adoption (P1 #11, §4.3 + §4.2).

Forking is the *explicit* write step: an inspected ``course.json`` becomes a
local ``LearningPlan``, and the fork immediately tries to hand the learner its
first card **through the card generator's resource source path** — the same
grounded lane the product already trusts, never a synthesized card.

Honest degradation is the contract:

* a stage resource reference only resolves when the library really holds a
  matching record (id, name, or content hash);
* the first card is generated only from a *trusted, indexed* resource with a
  knowledge fragment; otherwise the fork reports ``deferred`` with the exact
  missing precondition instead of improvising one;
* the generated card is returned as a candidate and is **not** bound into the
  training ledger — minting stays on the explicit ``/training/generate-card``
  path (the same discipline the coach tools obey).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..core.models import (
    CardGenerationContext,
    LearningPlan,
    PlanStage,
    ResourceKnowledgeEvidence,
    ResourceRecord,
    TrainingCardCandidateSnapshot,
)
from .card_generator import CardGenerationService
from .course_pack import CourseManifest
from .plan_revision import save_plan_advancing_revision

FIRST_CARD_GENERATED = "generated"
FIRST_CARD_DEFERRED = "deferred"


@dataclass(slots=True)
class CourseForkResult:
    """What a fork actually did, including what it refused to invent."""

    plan: LearningPlan
    revision: int | None = None
    first_card: TrainingCardCandidateSnapshot | None = None
    first_card_status: str = FIRST_CARD_DEFERRED
    first_card_reason: str = ""
    unresolved_resource_refs: list[str] = field(default_factory=list)


def _library_index(records: list[ResourceRecord]) -> dict[str, ResourceRecord]:
    """Index the library by record id, resource name and content hash."""
    index: dict[str, ResourceRecord] = {}
    for record in records:
        for key in (record.id, record.name, record.content_hash):
            text = str(key or "").strip()
            if text:
                index.setdefault(text, record)
    return index


def _manifest_resource_keys(manifest: CourseManifest) -> dict[str, set[str]]:
    """Map each manifest resource ref onto the keys a stage may cite."""
    keys: dict[str, set[str]] = {}
    for resource in manifest.resources:
        aliases = {resource.name, resource.source, resource.content_hash or ""}
        for alias in [alias for alias in aliases if str(alias or "").strip()]:
            keys.setdefault(alias, set()).update(
                alias2 for alias2 in aliases if str(alias2 or "").strip()
            )
    return keys


def _resolve_ref(ref: str, index: dict[str, ResourceRecord], aliases: dict[str, set[str]]) -> ResourceRecord | None:
    text = str(ref or "").strip()
    if not text:
        return None
    if text in index:
        return index[text]
    for alias in aliases.get(text, set()):
        if alias in index:
            return index[alias]
    return None


def plan_from_manifest(
    manifest: CourseManifest,
    *,
    workspace_id: str,
    repository: Any,
) -> tuple[LearningPlan, list[str]]:
    """Build the forked plan, resolving stage resource refs against the library.

    Unresolved refs are kept verbatim (the learner may still upload them — that
    is the ``course.json`` → ``/resource/upload`` → ``/resource/index`` chain)
    and reported back so the host can say what is still missing.
    """
    records = list(repository.list_resources(workspace_id) or [])
    index = _library_index(records)
    aliases = _manifest_resource_keys(manifest)
    unresolved: list[str] = []
    stages: list[PlanStage] = []
    for position, spec in enumerate(manifest.stages, start=1):
        resolved: list[str] = []
        for ref in spec.resources:
            record = _resolve_ref(ref, index, aliases)
            if record is None:
                unresolved.append(str(ref))
                resolved.append(str(ref))
            else:
                resolved.append(record.id)
        stages.append(
            PlanStage(
                id=spec.id or f"stage-{position}",
                title=spec.title,
                goal=spec.goal or spec.title,
                outcomes=[str(item) for item in spec.outcomes],
                resources=resolved,
            )
        )
    plan = LearningPlan(
        id=f"course-{manifest.title.strip()[:48] or 'course'}",
        title=manifest.title,
        summary=manifest.summary,
        stages=stages,
        current_stage_id=stages[0].id if stages else None,
        # Alias form: it is the wire name the plan is stored and rehydrated under.
        workspaceId=workspace_id,
        objective=manifest.summary or manifest.title,
    )
    return plan, unresolved


def _first_card_evidence(
    runtime: Any,
    workspace_id: str,
    record: ResourceRecord,
) -> ResourceKnowledgeEvidence | None:
    """One redacted knowledge fragment, mirroring the production projection.

    Same gates as the card route: the resource must be indexed and trusted, and
    the fragment must carry a focus and a summary — otherwise there is nothing
    to ground a card on and the fork must say so.
    """
    if record.index_status != "indexed" or record.trust_state != "trusted":
        return None
    service = getattr(runtime, "resource_service", None)
    builder = getattr(service, "build_requested_resource_context", None)
    if not callable(builder):
        return None
    context = builder(workspace_id, [record.id], max_items=1, summary_chars=220)
    fragments = context.get("resource_fragments") if isinstance(context, dict) else None
    if not isinstance(fragments, list):
        return None
    for fragment in fragments:
        if not isinstance(fragment, dict):
            continue
        if str(fragment.get("resource_id") or "").strip() != record.id:
            continue
        fragment_id = str(fragment.get("id") or "").strip()
        focus_area = str(fragment.get("focus_area") or "").strip()
        summary = ""
        for key in ("evidence_summary", "summary", "snippet"):
            summary = str(fragment.get(key) or "").strip()
            if summary:
                break
        if fragment_id and focus_area and summary:
            return ResourceKnowledgeEvidence(
                resourceId=record.id,
                fragmentId=fragment_id,
                sourceType=str(fragment.get("source_type") or record.kind).strip().lower(),
                focusArea=focus_area,
                summary=summary,
            )
    return None


def _first_card(
    manifest: CourseManifest,
    plan: LearningPlan,
    *,
    runtime: Any,
    workspace_id: str,
    response_language: str | None,
    card_type: str,
) -> tuple[TrainingCardCandidateSnapshot | None, str, str]:
    records = list(runtime.repository.list_resources(workspace_id) or [])
    by_id = {record.id: record for record in records}
    for stage in plan.stages:
        for resource_id in stage.resources:
            record = by_id.get(resource_id)
            if record is None:
                continue
            evidence = _first_card_evidence(runtime, workspace_id, record)
            if evidence is None:
                continue
            context = CardGenerationContext(
                workspace_id=workspace_id,
                source="resource_knowledge",
                card_type=card_type,  # type: ignore[arg-type]
                focus_area=evidence.focus_area,
                target_skill=evidence.focus_area,
                why_now=f"Forked course '{manifest.title}' starts from resource '{record.name}'.",
                plan_stage_id=stage.id,
                resource_id=record.id,
                resource_trust_state=record.trust_state,
                resource_trust_score=record.trust_score,
                resource_freshness=record.freshness,
                resource_quality_flags=list(record.quality_flags),
                # Alias form: the wire name the card route already uses.
                resourceKnowledgeEvidence=evidence,
                response_language=response_language,  # type: ignore[arg-type]
            )
            card = CardGenerationService().generate_card(
                "resource_knowledge", context, allow_llm=False
            )
            return card, FIRST_CARD_GENERATED, ""
    if not records:
        return None, FIRST_CARD_DEFERRED, "the library has no resources yet"
    indexed = [record for record in records if record.index_status == "indexed"]
    if not indexed:
        return None, FIRST_CARD_DEFERRED, "no referenced resource is indexed yet"
    trusted = [record for record in indexed if record.trust_state == "trusted"]
    if not trusted:
        return None, FIRST_CARD_DEFERRED, "no indexed resource is trusted yet"
    return (
        None,
        FIRST_CARD_DEFERRED,
        "trusted indexed resources carry no usable knowledge fragment yet",
    )


def fork_course_manifest(
    manifest: CourseManifest,
    *,
    runtime: Any,
    workspace_id: str,
    response_language: str | None = None,
    card_type: str = "practice",
) -> CourseForkResult:
    """Adopt a course manifest: write the forked plan, then try its first card."""
    plan, unresolved = plan_from_manifest(
        manifest, workspace_id=workspace_id, repository=runtime.repository
    )
    revision = save_plan_advancing_revision(runtime.repository, workspace_id, plan)
    card, status, reason = _first_card(
        manifest,
        plan,
        runtime=runtime,
        workspace_id=workspace_id,
        response_language=response_language,
        card_type=card_type,
    )
    return CourseForkResult(
        plan=plan,
        revision=revision if isinstance(revision, int) else None,
        first_card=card,
        first_card_status=status,
        first_card_reason=reason,
        unresolved_resource_refs=sorted({ref for ref in unresolved if ref}),
    )
