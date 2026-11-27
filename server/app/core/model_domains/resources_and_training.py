from __future__ import annotations

import logging
import re
from hashlib import sha1
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from .foundations_and_provider import (
    AssetSourceReference,
    DependencyMasteryStage,
    LibraryAssetScope,
    ResponseLanguage,
    TeachingAssetKind,
    TeachingAssetOrigin,
    TeachingAssetScope,
    TrainingCardCreatedFrom,
    TrainingCardStatus,
    TrainingCardTrustState,
    TrainingCardType,
    TrainingLearningFamily,
    TrainingLearningPhase,
    utc_now_iso,
)


class LibraryAssetLifecycleRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    approved: bool = False
    reason: str = ""


ResearchBriefClaimStatus = Literal["sourced", "inferred", "unverified"]


class ResearchBriefFinding(BaseModel):
    """One research conclusion with explicit provenance.

    ``sourced`` claims must carry at least one source reference so every key
    conclusion stays traceable to its resource, version and location. Model
    inference and still-unverified assumptions are separate statuses and must
    never be presented as sourced facts.
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    statement: str
    claim_status: ResearchBriefClaimStatus = Field(default="inferred", alias="claimStatus")
    source_refs: list[AssetSourceReference] = Field(default_factory=list, alias="sourceRefs")
    location: str = ""

    @field_validator("statement", "location")
    @classmethod
    def _strip_text(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def _require_sources_for_sourced_claims(self) -> "ResearchBriefFinding":
        self.location = self.location.strip()
        if self.claim_status == "sourced" and not self.source_refs:
            raise ValueError("sourced research findings require at least one sourceRef")
        return self


class ResearchBriefCheckQuestion(BaseModel):
    """One learning check with its acceptance bar (备课验收)."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    question: str
    acceptance: list[str] = Field(default_factory=list)

    @field_validator("question")
    @classmethod
    def _strip_question(cls, value: str) -> str:
        return value.strip()


class ResearchBrief(BaseModel):
    """Preparation Engine output: one research + lesson-preparation result.

    Stored as a ``research_brief`` library asset payload so研究成果 become
    manageable, traceable library assets instead of a second dashboard.
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    research_goal: str = Field(alias="researchGoal")
    key_questions: list[str] = Field(default_factory=list, alias="keyQuestions")
    findings: list[ResearchBriefFinding] = Field(default_factory=list)
    source_disagreements: list[str] = Field(default_factory=list, alias="sourceDisagreements")
    concepts: list[str] = Field(default_factory=list)
    prerequisites: list[str] = Field(default_factory=list)
    knowledge_structure: list[str] = Field(default_factory=list, alias="knowledgeStructure")
    teaching_order: list[str] = Field(default_factory=list, alias="teachingOrder")
    explanation_strategy: str = Field(default="", alias="explanationStrategy")
    examples: list[str] = Field(default_factory=list)
    misconceptions: list[str] = Field(default_factory=list)
    check_questions: list[ResearchBriefCheckQuestion] = Field(default_factory=list, alias="checkQuestions")
    acceptance_criteria: list[str] = Field(default_factory=list, alias="acceptanceCriteria")
    open_questions: list[str] = Field(default_factory=list, alias="openQuestions")
    follow_up_research: list[str] = Field(default_factory=list, alias="followUpResearch")
    plan_id: str | None = Field(default=None, alias="planId")
    stage_id: str | None = Field(default=None, alias="stageId")

    @field_validator("research_goal", "explanation_strategy")
    @classmethod
    def _strip_brief_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("plan_id", "stage_id")
    @classmethod
    def _strip_optional_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def _normalize_brief_lines(self) -> "ResearchBrief":
        self.research_goal = (self.research_goal or "").strip()
        line_fields = (
            "key_questions", "source_disagreements", "concepts", "prerequisites",
            "knowledge_structure", "teaching_order", "examples", "misconceptions",
            "acceptance_criteria", "open_questions", "follow_up_research",
        )
        for field_name in line_fields:
            values = getattr(self, field_name)
            setattr(self, field_name, [line.strip() for line in values if line.strip()])
        self.explanation_strategy = (self.explanation_strategy or "").strip()
        self.plan_id = self.plan_id or None
        self.stage_id = self.stage_id or None
        if not self.research_goal:
            raise ValueError("research_goal is required")
        return self


class ResearchBriefUpsertRequest(BaseModel):
    """Save (or update) one Research Brief as a traceable library asset."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    asset_id: str | None = Field(default=None, alias="assetId")
    scope: LibraryAssetScope = "library"
    title: str
    brief: ResearchBrief
    source_chain: list[AssetSourceReference] = Field(default_factory=list, alias="sourceChain")
    project_id: str | None = Field(default=None, alias="projectId")
    context_id: str | None = Field(default=None, alias="contextId")
    approved: bool = False

    @field_validator("title")
    @classmethod
    def _require_title(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("research brief title is required")
        return normalized


class ResearchBriefDraftRequest(BaseModel):
    """Draft (and optionally save) a Research Brief from one finished turn.

    The webview sends the learner's stated research goal, the reply text and
    the resource ids the turn was grounded in. The server drafts the brief
    with the provider, downgrades claims whose sources do not resolve, and
    pins every sourced citation to the real resource version and hash.
    """

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    research_goal: str = Field(alias="researchGoal")
    reply: str
    title: str = ""
    resource_ids: list[str] = Field(default_factory=list, alias="resourceIds")
    response_language: str | None = Field(default=None, alias="responseLanguage")
    scope: LibraryAssetScope = "library"
    context_id: str | None = Field(default=None, alias="contextId")
    project_id: str | None = Field(default=None, alias="projectId")
    save: bool = False
    asset_id: str | None = Field(default=None, alias="assetId")
    # Per-request provider override (same contract as /plan/generate): the
    # journey/host passes the provider explicitly instead of a saved profile.
    provider: dict[str, Any] | None = None
    api_key: str | None = None

    @field_validator("research_goal", "reply", "title")
    @classmethod
    def _strip_draft_text(cls, value: str) -> str:
        return value.strip()


class TeachingKnowledgeAsset(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    id: str = ""
    kind: TeachingAssetKind
    scope: TeachingAssetScope = "project"
    workspace_id: str = ""
    title: str
    summary: str = ""
    concept_card: str = ""
    implementation_pattern: str = ""
    common_pitfall: str = ""
    exercise_seed: str = ""
    explanation_recipe: str = ""
    why_it_matters: str = ""
    example: str = ""
    anti_pattern: str = ""
    focus_area: str = ""
    scenario: str = ""
    origin: TeachingAssetOrigin = "manual"
    source_key: str = ""
    source_ids: list[str] = Field(default_factory=list)
    source_fragments: list[str] = Field(default_factory=list)
    evidence_snippets: list[str] = Field(default_factory=list)
    retrieval_hints: list[str] = Field(default_factory=list)
    source_summary: str = ""
    source_quality_flags: list[str] = Field(default_factory=list)
    source_freshness: Literal["fresh", "stale", "unknown"] = "unknown"
    source_retrieved_at: str | None = None
    tags: list[str] = Field(default_factory=list)
    trust_score: float = 0.0
    usage_count: int = 0
    plan_stage_id: str = ""
    success_count: int = 0
    failure_count: int = 0
    last_outcome: str = ""
    last_effective_at: str | None = None
    effectiveness_by_scenario: dict[str, dict[str, int]] = Field(default_factory=dict)
    last_used_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    @model_validator(mode="after")
    def sync_identity(self) -> "TeachingKnowledgeAsset":
        if not self.workspace_id:
            # Empty general assets must not auto-promote into the global catalog.
            self.workspace_id = ""
        if not self.source_key:
            source_bits = [
                self.scope,
                self.kind,
                self.workspace_id or "__global__",
                self.focus_area or self.scenario or self.title,
                ",".join(sorted({item.strip() for item in self.source_ids if item.strip()})),
            ]
            cleaned_source_key = "::".join(
                item.strip().lower().replace(" ", "-")
                for item in source_bits
                if isinstance(item, str) and item.strip()
            )
            self.source_key = cleaned_source_key or f"{self.scope}::{self.kind}::{self.title}"
        if not self.id:
            self.id = f"asset-{sha1(self.source_key.encode('utf-8')).hexdigest()[:12]}"
        if not self.summary:
            for candidate in (
                self.concept_card,
                self.implementation_pattern,
                self.common_pitfall,
                self.exercise_seed,
                self.explanation_recipe,
                self.why_it_matters,
                self.example,
                self.anti_pattern,
            ):
                cleaned = candidate.strip()
                if cleaned:
                    self.summary = cleaned
                    break
        if not self.source_summary:
            for candidate in (
                self.why_it_matters,
                self.example,
                self.explanation_recipe,
                self.summary,
            ):
                cleaned = candidate.strip()
                if cleaned:
                    self.source_summary = cleaned
                    break
        if not self.evidence_snippets:
            derived_evidence = [
                item.strip()
                for item in [
                    self.example,
                    self.anti_pattern,
                    *self.source_fragments[:2],
                ]
                if isinstance(item, str) and item.strip()
            ]
            self.evidence_snippets = derived_evidence[:3]
        if not self.retrieval_hints:
            hints = [
                self.focus_area.strip(),
                self.scenario.strip(),
                *[item.strip() for item in self.tags if item.strip()],
                self.title.strip(),
            ]
            seen_hints: set[str] = set()
            normalized_hints: list[str] = []
            for item in hints:
                lowered = item.lower()
                if not item or lowered in seen_hints:
                    continue
                seen_hints.add(lowered)
                normalized_hints.append(item)
            self.retrieval_hints = normalized_hints[:8]
        if not self.created_at:
            self.created_at = utc_now_iso()
        if not self.updated_at:
            self.updated_at = utc_now_iso()
        return self


class TaskSpec(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    title: str
    natural_language_goal: str
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    edge_cases: list[str] = Field(default_factory=list)
    failure_conditions: list[str] = Field(default_factory=list)
    verification_strategy: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    workspace_id: str = Field(default="", alias="workspaceId")


class EvaluationCheck(BaseModel):
    id: str
    label: str
    status: Literal["passed", "failed", "warning", "skipped"]
    detail: str


class EvaluationReport(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    task_spec_id: str | None = None
    summary: str
    static_checks: list[EvaluationCheck] = Field(default_factory=list)
    dynamic_checks: list[EvaluationCheck] = Field(default_factory=list)
    semantic_checks: list[EvaluationCheck] = Field(default_factory=list)
    next_step: str
    reflection: str | None = None
    passed: bool
    workspace_id: str = Field(default="", alias="workspaceId")


class ReviewQueueItem(BaseModel):
    concept: str
    reason: str
    due_at: str | None = None
    source: Literal["weakness", "mastery", "reflection", "plan"] = "weakness"
    severity: Literal["low", "medium", "high"] = "medium"
    surface_mode: Literal["due", "ahead", "digest"] = "due"
    task_hint: str = ""
    focus_area: str = ""
    linked_context: str = ""
    interval_days: int | None = None
    mastery_score: float | None = None
    evidence_basis: Literal["fsrs_recall", "no_recall_evidence"] = "no_recall_evidence"


class TrainingPlanBinding(BaseModel):
    """Formal identity captured when a practice is minted, never supplied by the model."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    plan_id: str = Field(alias="planId", min_length=1)
    stage_id: str = Field(alias="stageId", min_length=1)
    step: str = Field(min_length=1)
    revision: int | None = Field(default=None, ge=0)


_FILE_NOTE_OPEN_RE = re.compile(r"\s*[(（\[【{<]")


_SENTENCE_PUNCTUATION_RE = re.compile(r"[，。；：！？、（）【】「」“”‘’;!?]")


_TRAILING_FILE_NAME_RE = re.compile(r"(?<![\w/])([A-Za-z0-9_.+-]+\.[A-Za-z0-9]{1,12})$")


def _looks_like_training_file_target(text: str) -> bool:
    """A path, not a sentence.

    A file target has no line break or sentence punctuation and carries a path
    separator, a dotfile name, a file extension, or a bare ASCII file name. A
    path may contain spaces ("My Project/app.py"); a bare name may not.
    """
    if not text or "\n" in text or len(text) > 260 or _SENTENCE_PUNCTUATION_RE.search(text):
        return False
    without_line = re.sub(r":\d+(?:-\d+)?$", "", text)
    if re.search(r'[<>"|?*]', without_line):
        return False
    name = without_line.rsplit("/", 1)[-1]
    if "/" in without_line:
        # A real path may contain spaces, but not a CJK prose annotation
        # after them ("src/app.py 的入口").
        if re.search(r"[\u4e00-\u9fff]", without_line) and any(
            character.isspace() for character in without_line
        ):
            return False
        return True
    if any(character.isspace() for character in without_line):
        return False
    if name.startswith(".") or re.search(r"\.[A-Za-z0-9]{1,12}$", name):
        return True
    return bool(re.fullmatch(r"[A-Za-z0-9_.+-]{1,64}", name))


def _normalize_training_file_path(value: object) -> str:
    """Normalize a card-authored file target without guessing a new file.

    Model-authored cards sometimes wrap the target in prose: an appended note
    (``foo.py（建议新建，具体路径由学习者选择）``), a leading sentence
    (``新建 foo.py``) or plain prose with no file at all. Such an entry is not
    a path: it was shown to learners as the target file, and it made host
    verification refuse every real file because the artifact name never
    matched the "target". Keep the file when there is one, drop the prose.
    A ``<placeholder>`` is kept verbatim; downstream logic already treats it as
    "no concrete file".
    """
    text = str(value).strip()
    text = text.strip("`'\"")
    text = text.replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    text = text.strip()
    if not text or (text.startswith("<") and text.endswith(">")):
        return text
    note = _FILE_NOTE_OPEN_RE.search(text)
    if note and note.start() > 0:
        candidate = text[: note.start()].strip()
        if _looks_like_training_file_target(candidate):
            return candidate
    if _looks_like_training_file_target(text):
        return text
    if any(character.isspace() for character in text):
        head = re.split(r"\s+", text, maxsplit=1)[0]
        if "/" in head and _looks_like_training_file_target(head):
            return head
        if "/" not in text:
            trailing = _TRAILING_FILE_NAME_RE.search(text)
            if trailing and _looks_like_training_file_target(trailing.group(1)):
                return trailing.group(1)
    return ""


_ALTERNATIVE_SYMBOL_PAIR_RE = re.compile(
    r"`([^`\n]+)`([^`\n]{0,60}?(?:或|\bor\b)[^`\n]{0,60}?)`([^`\n]+)`"
)


def _drop_alternative_expected_symbols(symbols: list[str], texts: list[object]) -> list[str]:
    """A card that says "`torch.minimum`（或 `torch.min`）" means either one.

    Model-authored cards list both spellings as expected symbols, and the
    evaluator requires every listed symbol: a correct `torch.minimum`
    implementation then failed on `torch.min`. When the card's own text
    presents two symbols as alternatives, the second stops being required on
    its own. Symbols the card never presents as alternatives are untouched.
    """
    alternatives: set[str] = set()
    for text in texts:
        for _first, _separator, second in _ALTERNATIVE_SYMBOL_PAIR_RE.findall(str(text or "")):
            normalized = str(second).strip().strip("`").strip()
            if normalized:
                alternatives.add(normalized)
    if not alternatives:
        return list(symbols)
    return [symbol for symbol in symbols if str(symbol).strip() not in alternatives]


class TrainingCardCandidateSnapshot(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    card_id: str = ""
    card_type: TrainingCardType = "practice"
    title: str = ""
    status: TrainingCardStatus = "candidate"
    learning_phase: TrainingLearningPhase = "learn"
    created_from: TrainingCardCreatedFrom = "conversation"
    scenario_pack: str = ""
    why_now: str = ""
    focus_area: str = ""
    target_skill: str = ""
    learning_family: TrainingLearningFamily = "theory"
    learning_subtype: str = "concept"
    scenario: str = ""
    problem_statement: str = ""
    suggested_workspace_action: str = ""
    api_hints: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    deliverable: str = ""
    self_check: list[str] = Field(default_factory=list)
    expected_answer_shape: str = ""
    validation_method: str = ""
    grading_rubric: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    trainer_review_input: str = ""
    stuck_recovery: str = ""
    reflection_prompt: str = ""
    knowledge_type: str = ""
    question: str = ""
    context: str = ""
    answer_mode: str = "text"
    options: list[str] = Field(default_factory=list)
    correct_option_index: int | None = None
    correct_option_indices: list[int] = Field(default_factory=list)
    correct_sort_order: list[int] = Field(default_factory=list)
    fill_blank_answers: dict[str, str] = Field(default_factory=dict)
    expected_answer: str = ""
    rubric: list[str] = Field(default_factory=list)
    hint_ladder: list[str] = Field(default_factory=list)
    feedback: dict[str, str] = Field(default_factory=dict)
    last_feedback: dict[str, Any] = Field(default_factory=dict)
    learner_answer: str = ""
    learner_selected_option_indices: list[int] = Field(default_factory=list)
    learner_fill_blank_answers: dict[str, str] = Field(default_factory=dict)
    learner_sort_order: list[int] = Field(default_factory=list)
    common_mistakes: list[str] = Field(default_factory=list)
    review_schedule: dict[str, Any] = Field(default_factory=dict)
    difficulty: str = "medium"
    plan_links: list[str] = Field(default_factory=list)
    plan_binding: TrainingPlanBinding | None = Field(default=None, alias="planBinding")
    source_chain: list[str] = Field(default_factory=list)
    project_id: str = ""
    project_scope: str = ""
    requires_project_context: bool = False
    project_context_ready: bool = True
    trust_state: TrainingCardTrustState = "unknown"
    trust_acknowledged: bool = False
    resource_id: str = ""
    resource_version_id: str = ""
    resource_content_hash: str = ""
    resource_location: dict[str, Any] = Field(default_factory=dict)
    dependency_key: str = ""
    dependency_layer: str = ""
    question_style: str = ""
    verification_method: str = ""
    next_steps: list[str] = Field(default_factory=list)
    files_to_touch: list[str] = Field(default_factory=list)
    learner_deliverables: list[str] = Field(default_factory=list)
    verification_steps: list[str] = Field(default_factory=list)
    expected_symbols: list[str] = Field(default_factory=list)
    success_signal: str = ""
    return_with: str = ""
    next_after_completion: str = ""
    created_at: str = ""
    updated_at: str = ""
    # P1.4 candidate management: the learner decides which candidates are
    # worth keeping. These ride the existing card record and ledger — merging
    # archives the duplicate in place (merged_into) instead of inventing a
    # second card store.
    important: bool = False
    card_priority: int = Field(default=0, alias="cardPriority")
    merged_into: str = Field(default="", alias="mergedInto")
    # Cards from before the review flow retain their existing library status.
    review_state: Literal["pending", "deferred", "saved", "rejected"] = "saved"
    reviewed_at: str = ""

    @model_validator(mode="after")
    def sync_training_defaults(self) -> "TrainingCardCandidateSnapshot":
        if not self.created_at:
            self.created_at = utc_now_iso()
        if not self.updated_at:
            self.updated_at = utc_now_iso()
        if not self.title:
            self.title = self.question or self.problem_statement or self.target_skill or self.focus_area or "Training Card"
        normalized_files: list[str] = []
        seen_files: set[str] = set()
        for path in self.files_to_touch:
            normalized = _normalize_training_file_path(path)
            if normalized and normalized not in seen_files:
                seen_files.add(normalized)
                normalized_files.append(normalized)
        self.files_to_touch = normalized_files
        self.expected_symbols = _drop_alternative_expected_symbols(
            self.expected_symbols,
            [
                *self.acceptance_criteria,
                *self.api_hints,
                *self.learner_deliverables,
                *self.grading_rubric,
                *self.hint_ladder,
                self.problem_statement,
                self.deliverable,
                self.validation_method,
            ],
        )
        if not self.source_chain:
            self.source_chain = ["card_generation_router"]
        try:
            from app.training.subject_taxonomy import classify_learning_subject

            subject = classify_learning_subject(
                self.focus_area,
                self.target_skill,
                self.scenario,
                self.problem_statement,
                self.question,
                self.knowledge_type,
                self.verification_method,
                self.scenario_pack,
                self.suggested_workspace_action,
            )
            default_family = not self.learning_family or self.learning_family == "theory"
            default_subtype = not self.learning_subtype or self.learning_subtype == "concept"
            if default_family and (subject.family != "theory" or subject.subtype != "concept"):
                self.learning_family = subject.family
            if default_subtype and subject.subtype != "concept":
                self.learning_subtype = subject.subtype
        except Exception:
            # Subject classification is a best-effort enrichment. A failure
            # used to disappear entirely, so a broken taxonomy import looked
            # exactly like a card that genuinely had no subject.
            logging.getLogger("trainer.models").debug(
                "learning subject classification failed; keeping theory/concept defaults",
                exc_info=True,
            )
        self.learning_family = self.learning_family or "theory"
        self.learning_subtype = self.learning_subtype or "concept"
        # A hands-on implementation card must point at at least one concrete
        # file. If the generator omitted the file target, the card is actually
        # a reading/orientation task; downgrade it so the UI uses manual
        # verification instead of forcing "verify current file".
        if self.learning_subtype.strip().lower() == "implementation":
            concrete_files = [
                str(path).strip()
                for path in self.files_to_touch
                if str(path).strip()
                and not (str(path).strip().startswith("<") and str(path).strip().endswith(">"))
            ]
            if not concrete_files:
                self.learning_subtype = "reading"
        # Inspection/note tasks that only reference a file must not force a
        # current-file edit verification. Keep a real change verb as hands-on.
        if self.learning_subtype.strip().lower() in {"implementation", "function", "debug"}:
            task_text = " ".join(
                str(value or "")
                for value in (
                    self.title,
                    self.problem_statement,
                    self.suggested_workspace_action,
                    self.deliverable,
                    self.success_signal,
                    self.target_skill,
                    self.focus_area,
                )
            ).lower()
            analysis_markers = (
                "梳理",
                "记录",
                "说明",
                "不要先改",
                "不要修改",
                "阅读",
                "检查",
                "分析",
                "review",
                "inspect",
                "explain",
                "describe",
                "record",
                "note",
                "do not modify",
            )
            change_markers = (
                "实现",
                "新增",
                "增加",
                "添加",
                "补充",
                "编写",
                "创建",
                "修改",
                "修复",
                "重构",
                "优化",
                "更新",
                "完善",
                "implement",
                "add ",
                "modify",
                "fix",
                "refactor",
                "create",
                "update",
                "optimize",
                "improve",
                "write",
                "build",
            )
            if any(marker in task_text for marker in analysis_markers) and not any(
                marker in task_text for marker in change_markers
            ):
                self.learning_subtype = "reading"
        if self.learning_phase not in {"learn", "try", "verify", "reflect", "return"}:
            self.learning_phase = "learn"
        return self


class ResourceKnowledgeEvidence(BaseModel):
    """Server-projected indexed fragment that may ground a resource training card."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    resource_id: str = Field(default="", alias="resourceId")
    fragment_id: str = Field(default="", alias="fragmentId")
    source_type: str = Field(default="", alias="sourceType")
    focus_area: str = Field(default="", alias="focusArea")
    summary: str = ""
    excerpt: str = ""


class DependencyUsageEvidence(BaseModel):
    """Server-projected import, call, or declared dependency usage fact."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    file_path: str = Field(default="", alias="filePath")
    kind: str = ""
    identifier: str = ""
    summary: str = ""


class CardGenerationContext(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    workspace_id: str = ""
    source: str = "conversation_gap"
    card_type: TrainingCardType = "practice"
    context_hint: str = ""
    target_skill: str = ""
    focus_area: str = ""
    plan_stage_id: str = ""
    plan_binding: TrainingPlanBinding | None = Field(default=None, alias="planBinding")
    resource_id: str = ""
    resource_version_id: str = ""
    resource_content_hash: str = ""
    resource_location: dict[str, Any] = Field(default_factory=dict)
    difficulty: str = "medium"
    hint_count: int | None = None
    code_reveal: str = ""
    practice_type: str = ""
    review_frequency: str = ""
    material_recommendation: str = ""
    next_plan_step: str = ""
    should_reveal_code: bool | None = None
    pedagogy_mode: str = ""
    why_now: str = ""
    resource_quality_flags: list[str] = Field(default_factory=list)
    resource_trust_score: float = 0.0
    resource_trust_state: str = ""
    resource_missing: bool = False
    resource_missing_reason: str = ""
    resource_freshness: str = ""
    resource_knowledge_evidence: ResourceKnowledgeEvidence | None = Field(
        default=None,
        alias="resourceKnowledgeEvidence",
    )
    response_language: ResponseLanguage | None = None
    current_file_path: str = Field(default="", alias="currentFilePath")
    current_file_language_id: str = Field(default="", alias="currentFileLanguageId")
    current_file_content: str = Field(default="", alias="currentFileContent")
    current_file_excerpt: str = Field(default="", alias="currentFileExcerpt")
    current_file_selection: str = Field(default="", alias="currentFileSelection")
    current_file_selection_range: str = Field(default="", alias="currentFileSelectionRange")
    current_file_diagnostics: list[str] = Field(
        default_factory=list,
        alias="currentFileDiagnostics",
    )
    project_verification_steps: list[str] = Field(default_factory=list)
    dependency_usage_evidence: list[DependencyUsageEvidence] = Field(
        default_factory=list,
        alias="dependencyUsageEvidence",
    )
    workspace_root_path: str = Field(default="", alias="workspaceRootPath")
    remote_workspace_name: str = Field(default="", alias="remoteWorkspaceName")
    remote_workspace_facts: list[str] = Field(
        default_factory=list,
        alias="remoteWorkspaceFacts",
    )

    @field_validator("source", mode="before")
    @classmethod
    def normalize_legacy_conversation_source(cls, value: object) -> str:
        """Keep older Training clients on the canonical card-generation path."""

        source = str(value or "").strip()
        if not source or source == "conversation":
            return "conversation_gap"
        return source


class ExpectedResourceVersion(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    version_id: str = Field(alias="versionId", min_length=1, max_length=128)
    content_hash: str = Field(alias="contentHash", min_length=1, max_length=128)


class CardGenerationRequest(CardGenerationContext):
    source: str = "conversation_gap"
    card_type: TrainingCardType = "practice"
    submode: str = ""
    current_file: dict[str, Any] | None = Field(default=None, alias="currentFile")
    expected_resource_version: ExpectedResourceVersion | None = Field(
        default=None, alias="expectedResourceVersion",
    )
    # Stream cancel remint identity — same request_id must not double-mint.
    request_id: str = Field(default="", alias="requestId", max_length=128)
    provider: dict[str, Any] | None = None
    api_key: str | None = Field(default=None, alias="apiKey")
    last_test_result: dict[str, Any] | None = Field(default=None, alias="lastTestResult")


class TrainingCardScoreFactors(BaseModel):
    plan_relevance: float = 0.0
    blocking_power: float = 0.0
    evidence_gap: float = 0.0
    recency_need: float = 0.0
    resource_trust: float = 0.0
    difficulty_fit: float = 0.0
    project_fit: float = 0.0
    transfer_value: float = 0.0
    recovery_priority: float = 0.0


class BlockedCandidateDetail(BaseModel):
    card_id: str = ""
    card_type: TrainingCardType = "practice"
    title: str = ""
    reasons: list[str] = Field(default_factory=list)


class ActiveCardSelectionResult(BaseModel):
    selected_card: TrainingCardCandidateSnapshot | None = None
    selected_card_id: str | None = None
    selection_score: float = 0.0
    score_factors: TrainingCardScoreFactors = Field(default_factory=TrainingCardScoreFactors)
    why_this_card: str = ""
    why_not_others: list[str] = Field(default_factory=list)
    blocked_candidates: list[BlockedCandidateDetail] = Field(default_factory=list)
    fallback_action: str = ""
    next_after_completion: str = ""
    candidate_count: int = 0
    eligible_count: int = 0


class CardGenerationResponse(BaseModel):
    card: TrainingCardCandidateSnapshot
    score: float = 0.0
    success: bool = True
    reason: str = ""
    active_routing: ActiveCardSelectionResult | None = None


class TrainingReliabilityRequestFields(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    request_id: str = Field(default="", alias="requestId")
    idempotency_key: str = Field(default="", alias="idempotencyKey")
    revision: int = 0
    timeout_ms: int = Field(default=30_000, alias="timeoutMs")
    cancel: bool = False


class CardStatusTransitionRequest(TrainingReliabilityRequestFields):
    workspace_id: str
    card_id: str
    new_status: TrainingCardStatus
    reason: str = ""


class CardLibraryActionRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    workspace_id: str = Field(min_length=1)
    card_id: str = Field(min_length=1)
    action: Literal["save", "defer", "reject", "start", "archive"]
    prompt: str | None = Field(default=None, max_length=8000)
    acceptance_criteria: list[str] | None = Field(default=None, max_length=20)


class CardImportanceRequest(BaseModel):
    """P1.4 candidate management: mark/unmark a candidate as important."""

    model_config = ConfigDict(populate_by_name=True)

    workspace_id: str
    card_id: str
    important: bool


class CardPriorityRequest(BaseModel):
    """P1.4 candidate management: adjust a candidate's practice priority."""

    model_config = ConfigDict(populate_by_name=True)

    workspace_id: str
    card_id: str
    priority: int


class CardMergeRequest(BaseModel):
    """P1.4 candidate management: merge duplicate candidates into one keeper."""

    model_config = ConfigDict(populate_by_name=True)

    workspace_id: str
    keep_card_id: str = Field(alias="keepCardId")
    duplicate_card_ids: list[str] = Field(default_factory=list, alias="duplicateCardIds")


class EvidenceItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    id: str = ""
    workspace_id: str = ""
    summary: str = ""
    source: str = "card_result"
    source_card_id: str = ""
    concepts: list[str] = Field(default_factory=list)
    outcome: str = "partial"
    confidence: float = 0.0
    verified: bool = False
    verification_source: str = ""
    # The trusted remote attestation boundary validates this observation.
    verification_artifact: dict[str, str] | None = None
    timestamp: str = ""
    target_plan_stage_id: str = ""
    target_plan_id: str = ""
    target_plan_step: str = ""
    adopted: bool = False
    adopted_at: str | None = None
    deferred_at: str | None = None
    deferral_reason: str = ""
    rejected_at: str | None = None
    rejection_reason: str = ""
    # Unified Evidence contract (schema 1): the adoption queue keeps its
    # lifecycle fields, while trust/version facts share one vocabulary with
    # AttemptStore and handoff evidence.
    schema_version: int = 1
    source_store: Literal["memory"] = "memory"
    trust_level: str = "self_reported"
    artifact_hash: str = ""
    resource_id: str = ""
    resource_version_id: str = ""
    resource_content_hash: str = ""
    resource_location: dict[str, Any] = Field(default_factory=dict)
    resource_git_sha: str | None = None
    canonical_evidence_id: str = ""

    @model_validator(mode="after")
    def sync_evidence_defaults(self) -> "EvidenceItem":
        if not self.timestamp:
            self.timestamp = utc_now_iso()
        return self


class EvidenceQueueSnapshot(BaseModel):
    pending: list[EvidenceItem] = Field(default_factory=list)
    deferred: list[EvidenceItem] = Field(default_factory=list)
    adopted: list[EvidenceItem] = Field(default_factory=list)
    rejected: list[EvidenceItem] = Field(default_factory=list)
    history: list[EvidenceItem] = Field(default_factory=list)
    unscoped: list[EvidenceItem] = Field(default_factory=list)
    total_count: int = 0


PlanChangeCandidateStatus = Literal["pending", "acknowledged", "rejected"]


class PlanChangeCandidate(BaseModel):
    id: str = ""
    workspace_id: str
    plan_id: str = ""
    feedback_id: str = ""
    reason: str
    diff: dict[str, Any] = Field(default_factory=dict)
    impact: dict[str, Any] = Field(default_factory=dict)
    status: PlanChangeCandidateStatus = "pending"
    created_at: str = Field(default_factory=utc_now_iso)
    acknowledged_at: str | None = None
    acknowledgement_note: str = ""


class EvidenceAdoptResponse(BaseModel):
    evidence: EvidenceItem
    plan_updated: bool = False
    plan_change_summary: str = ""


class CardStatusTransitionResponse(BaseModel):
    card: TrainingCardCandidateSnapshot
    ledger_entry: dict[str, Any] | None = None
    evidence_item: EvidenceItem | None = None


class DependencyMasterySnapshot(BaseModel):
    dependency_key: str
    dependency_name: str = ""
    apis: list[str] = Field(default_factory=list)
    use_cases: list[str] = Field(default_factory=list)
    scenarios: list[str] = Field(default_factory=list)
    weakest_points: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    mastery_stage: DependencyMasteryStage = "understood"
    mastery_stage_progress: list[str] = Field(default_factory=lambda: ["understood"])
    latest_transfer_blocked_reason: str = ""
    latest_transfer_evidence_id: str = ""
    latest_transfer_evidence_summary: str = ""
    latest_transfer_source_workspace_id: str = ""
    latest_transfer_target_workspace_id: str = ""
    latest_transfer_source_context: str = ""
    latest_transfer_target_context: str = ""
    updated_at: str = Field(default_factory=utc_now_iso)


class DependencySkillItemSnapshot(BaseModel):
    key: str
    label: str
    layer: str
    related_api: str = ""
    scenario: str = ""
    knowledge_type: str = ""
    question_style: str = ""
    verification_method: str = ""
    hint_ladder: list[str] = Field(default_factory=list)
    priority: float = 0.0

    @field_validator("priority", mode="before")
    @classmethod
    def normalize_priority(cls, value: Any) -> float:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized == "high":
                return 0.9
            if normalized == "medium":
                return 0.6
            if normalized == "low":
                return 0.3
            try:
                return float(normalized)
            except ValueError:
                return 0.0
        return 0.0


class DependencySkillMapSnapshot(BaseModel):
    dependency_key: str
    dependency_name: str = ""
    version: int = 1
    covered_layers: list[str] = Field(default_factory=list)
    items: list[DependencySkillItemSnapshot] = Field(default_factory=list)
    top_review_items: list[DependencySkillItemSnapshot] = Field(default_factory=list)
    priority_summary: str = ""
    project_first_cut: str = ""
    suggested_scenario_lab: list[str] = Field(default_factory=list)
    last_action: str = "derived"
    last_action_note: str = ""
    updated_at: str = Field(default_factory=utc_now_iso)

    @field_validator("project_first_cut", mode="before")
    @classmethod
    def normalize_project_first_cut(cls, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, bool):
            return "Build one minimum project slice first." if value else ""
        return str(value)

    @field_validator("suggested_scenario_lab", mode="before")
    @classmethod
    def normalize_suggested_scenario_lab(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item) for item in value if str(item).strip()]
        if isinstance(value, str):
            return [value] if value.strip() else []
        return [str(value)]


class DependencySkillMapHistoryEntry(BaseModel):
    entry_id: str
    dependency_key: str
    action: str
    version: int
    focus_item_key: str = ""
    focus_label: str = ""
    note: str = ""
    before_snapshot: dict[str, Any] = Field(default_factory=dict)
    after_snapshot: dict[str, Any] = Field(default_factory=dict)
    after_summary: str = ""
    created_at: str = Field(default_factory=utc_now_iso)


class FlashDeckSnapshot(BaseModel):
    id: str
    title: str = ""
    focus_area: str = ""
    cards: list[TrainingCardCandidateSnapshot] = Field(default_factory=list)
    generated_at: str = Field(default_factory=utc_now_iso)


class FlashcardAttempt(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    card_id: str
    correct: bool
    score: float = 0.0
    detail: str = ""
    learner_answer: str = ""
    selected_option_index: int | None = None
    selected_option_indices: list[int] = Field(
        default_factory=list,
        alias="selectedOptionIndices",
    )
    fill_blank_answers: dict[str, str] = Field(
        default_factory=dict,
        alias="fillBlankAnswers",
    )
    sort_order: list[int] = Field(default_factory=list, alias="sortOrder")
    answer_mode: str = "text"
    feedback: dict[str, Any] = Field(default_factory=dict)
    recorded_at: str = Field(default_factory=utc_now_iso)
    dependency_key: str = ""
    dependency_layer: str = ""
    question_style: str = ""
    knowledge_type: str = ""
    dependency_mastery: list[DependencyMasterySnapshot] = Field(default_factory=list)
    dependency_skill_map_history: list[DependencySkillMapHistoryEntry] = Field(default_factory=list)


class ReviewQueueAction(BaseModel):
    entry_id: str = ""
    concept: str
    action: str
    outcome: str
    focus_area: str = ""
    task_hint: str = ""
    note: str = ""
    scope: str = "single"
    created_at: str = Field(default_factory=utc_now_iso)
    next_review_at: str = ""

    @model_validator(mode="after")
    def sync_review_action_defaults(self) -> "ReviewQueueAction":
        if not self.entry_id:
            digest = sha1(f"{self.concept}:{self.action}:{self.created_at}".encode("utf-8")).hexdigest()[:10]
            self.entry_id = f"review-{digest}"
        return self
