"""Course manifest format (P1 #10, §4 of the general-coach pivot design).

A course is a *forkable starting file*: ``course.json`` carries a manifest plus
``LearningPlan`` stages, resource references and a card pack. Import is
inspect-only — nothing is written until a later step adopts it (#11) — so the
import lane can never mint a plan, a card or evidence by itself.

Trust rules (§4.2, reused not reinvented):

* manifest type/version are fail-closed (``ValueError`` on anything else);
* ``subject_family`` resolves through the verifier registry — an unknown
  family falls back to ``"code"`` exactly like ``verifier_pack_for``, and the
  resolution is *reported*, never silently applied;
* rubric entries obey the §2.2 anchor rule: only ``{"statement", "anchor"}``
  objects count as anchored; plain strings are kept but downgraded to
  ``self_reported`` and can therefore never become verified evidence.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..evaluator.verifiers import DEFAULT_SUBJECT_FAMILY, verifier_pack_for

COURSE_MANIFEST_TYPE = "trainer.course"
COURSE_MANIFEST_VERSION = 1

# Resource kinds a manifest may reference; mirrors ResourceRecord.kind minus
# capture-only kinds so a hand-written course.json stays honest.
COURSE_RESOURCE_KINDS = frozenset({"pdf", "epub", "image", "text", "markdown", "code", "url", "video"})


class CourseStageSpec(BaseModel):
    """One learning stage as shared; mirrors the ``PlanStage`` wire shape."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    id: str = ""
    title: str
    goal: str = ""
    outcomes: list[str] = Field(default_factory=list)
    resources: list[str] = Field(default_factory=list)


class CourseResourceRef(BaseModel):
    """A resource the course expects; ``source`` is a relative path or a URL."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    name: str
    kind: str = "text"
    source: str = ""
    summary: str = ""
    tags: list[str] = Field(default_factory=list)
    content_hash: str | None = Field(default=None, alias="contentHash")


class CourseCardSpec(BaseModel):
    """A practice/quiz card as shared; ``rubric`` entries carry their trust."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    card_type: str = "practice"
    title: str = ""
    focus_area: str = ""
    target_skill: str = ""
    learning_family: str = "theory"
    learning_subtype: str = "concept"
    problem_statement: str = ""
    question: str = ""
    acceptance_criteria: list[str] = Field(default_factory=list)
    expected_symbols: list[str] = Field(default_factory=list)
    rubric: list[Any] = Field(default_factory=list)


class CourseManifest(BaseModel):
    """The ``course.json`` document (§4.1)."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    manifest_type: str = Field(default=COURSE_MANIFEST_TYPE, alias="_type")
    version: int = COURSE_MANIFEST_VERSION
    title: str
    subject_family: str = DEFAULT_SUBJECT_FAMILY
    summary: str = ""
    stages: list[CourseStageSpec] = Field(default_factory=list)
    resources: list[CourseResourceRef] = Field(default_factory=list)
    card_pack: list[CourseCardSpec] = Field(default_factory=list)
    rubric_packs: dict[str, Any] = Field(default_factory=dict)


@dataclass(slots=True)
class CourseTrustReport:
    """What import vouches for — and what it explicitly refuses to vouch for."""

    stages: int = 0
    resources: int = 0
    cards: int = 0
    anchored_rubric_entries: int = 0
    self_reported_rubric_entries: int = 0
    downgraded_cards: list[str] = field(default_factory=list)
    declared_subject_family: str = ""
    resolved_subject_family: str = DEFAULT_SUBJECT_FAMILY
    subject_family_matched: bool = True
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CourseInspection:
    manifest: CourseManifest
    trust: CourseTrustReport


def _classify_rubric_entry(entry: Any) -> tuple[bool, str]:
    """Mirrors ``evaluator.verifiers.RubricItem``: an anchor or it is not one."""
    if isinstance(entry, Mapping):
        statement = str(entry.get("statement") or "").strip()
        anchor = str(entry.get("anchor") or "").strip()
        if statement and anchor:
            return True, statement
        return False, statement
    return False, str(entry).strip()


def inspect_course_manifest(payload: Mapping[str, Any]) -> CourseInspection:
    """Validate and trust-report a course manifest. Writes nothing.

    Raises ``ValueError`` with a stable message for every fail-closed case so
    the HTTP layer can map them to 422 without re-interpreting them.
    """
    if not isinstance(payload, Mapping):
        raise ValueError("course manifest must be a JSON object")
    manifest_type = str(payload.get("_type") or "").strip()
    if manifest_type != COURSE_MANIFEST_TYPE:
        raise ValueError(
            f"unsupported course manifest _type: expected '{COURSE_MANIFEST_TYPE}', "
            f"got '{manifest_type or '(missing)'}'"
        )
    version = payload.get("version")
    if version != COURSE_MANIFEST_VERSION:
        raise ValueError(
            f"unsupported course manifest version: expected {COURSE_MANIFEST_VERSION}, got {version!r}"
        )
    try:
        manifest = CourseManifest.model_validate(dict(payload))
    except Exception as exc:
        raise ValueError(f"invalid course manifest: {exc}") from exc
    if not manifest.title.strip():
        raise ValueError("course manifest requires a non-empty title")
    if not manifest.stages:
        raise ValueError("course manifest requires at least one stage")
    for stage in manifest.stages:
        if not stage.title.strip():
            raise ValueError("every course stage requires a non-empty title")
    for resource in manifest.resources:
        if resource.kind not in COURSE_RESOURCE_KINDS:
            raise ValueError(
                f"course resource '{resource.name}' has unsupported kind '{resource.kind}'"
            )

    declared = manifest.subject_family.strip().lower()
    resolved = verifier_pack_for(declared).subject_family
    trust = CourseTrustReport(
        stages=len(manifest.stages),
        resources=len(manifest.resources),
        cards=len(manifest.card_pack),
        declared_subject_family=declared,
        resolved_subject_family=resolved,
        subject_family_matched=(declared == resolved),
    )
    if declared and not trust.subject_family_matched:
        trust.notes.append(
            f"declared subject_family '{declared}' is not registered; "
            f"verification falls back to '{resolved}'"
        )
    for card in manifest.card_pack:
        card_self_reported = 0
        for entry in card.rubric:
            anchored, statement = _classify_rubric_entry(entry)
            if anchored:
                trust.anchored_rubric_entries += 1
            else:
                trust.self_reported_rubric_entries += 1
                card_self_reported += 1
        if card.rubric and card_self_reported == len(card.rubric):
            trust.downgraded_cards.append(card.title or card.focus_area or "untitled card")
        elif card_self_reported:
            trust.downgraded_cards.append(card.title or card.focus_area or "untitled card")
    if trust.self_reported_rubric_entries:
        trust.notes.append(
            f"{trust.self_reported_rubric_entries} rubric entr"
            f"{'y has' if trust.self_reported_rubric_entries == 1 else 'ies have'} no anchor "
            "and count as self_reported only — they can never become verified evidence"
        )
    return CourseInspection(manifest=manifest, trust=trust)


def build_course_manifest(
    *,
    title: str,
    subject_family: str,
    summary: str = "",
    stages: Iterable[Any] = (),
    resources: Iterable[Any] = (),
    card_pack: Iterable[Any] = (),
    rubric_packs: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a shareable ``course.json`` dict from local workspace data.

    Accepts live ``PlanStage`` / ``ResourceRecord`` objects or plain mappings;
    the output is stable, ordered and passes ``inspect_course_manifest``.
    """
    stage_specs: list[dict[str, Any]] = []
    for stage in stages:
        if isinstance(stage, Mapping):
            stage_specs.append(
                {
                    "id": str(stage.get("id") or ""),
                    "title": str(stage.get("title") or ""),
                    "goal": str(stage.get("goal") or ""),
                    "outcomes": [str(item) for item in (stage.get("outcomes") or [])],
                    "resources": [str(item) for item in (stage.get("resources") or [])],
                }
            )
        else:
            stage_specs.append(
                {
                    "id": str(getattr(stage, "id", "") or ""),
                    "title": str(getattr(stage, "title", "") or ""),
                    "goal": str(getattr(stage, "goal", "") or ""),
                    "outcomes": [str(item) for item in (getattr(stage, "outcomes", None) or [])],
                    "resources": [str(item) for item in (getattr(stage, "resources", None) or [])],
                }
            )

    resource_specs: list[dict[str, Any]] = []
    for resource in resources:
        if isinstance(resource, Mapping):
            resource_specs.append(
                {
                    "name": str(resource.get("name") or resource.get("id") or ""),
                    "kind": str(resource.get("kind") or "text"),
                    "source": str(resource.get("source") or resource.get("canonical_source") or ""),
                    "summary": str(resource.get("summary") or ""),
                    "tags": [str(tag) for tag in (resource.get("tags") or [])],
                    "contentHash": resource.get("content_hash") or resource.get("contentHash"),
                }
            )
        else:
            resource_specs.append(
                {
                    "name": str(getattr(resource, "name", "") or getattr(resource, "id", "") or ""),
                    "kind": str(getattr(resource, "kind", "") or "text"),
                    "source": str(
                        getattr(resource, "source", "") or getattr(resource, "canonical_source", "") or ""
                    ),
                    "summary": str(getattr(resource, "summary", "") or ""),
                    "tags": [str(tag) for tag in (getattr(resource, "tags", None) or [])],
                    "contentHash": getattr(resource, "content_hash", None),
                }
            )

    card_specs: list[dict[str, Any]] = []
    for card in card_pack:
        if isinstance(card, Mapping):
            card_specs.append(dict(card))
        else:
            card_specs.append(card.model_dump(by_alias=True) if hasattr(card, "model_dump") else dict(card))

    manifest = {
        "_type": COURSE_MANIFEST_TYPE,
        "version": COURSE_MANIFEST_VERSION,
        "title": str(title).strip(),
        "subject_family": str(subject_family or DEFAULT_SUBJECT_FAMILY).strip().lower(),
        "summary": str(summary or ""),
        "stages": stage_specs,
        "resources": resource_specs,
        "card_pack": card_specs,
        "rubric_packs": dict(rubric_packs or {}),
    }
    # Export must not ship a manifest import would reject: same rules, same place.
    inspect_course_manifest(manifest)
    return manifest
