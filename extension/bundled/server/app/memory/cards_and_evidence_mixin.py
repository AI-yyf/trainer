from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any, Literal
from uuid import uuid4

from fastapi import HTTPException

from ..core.event_ledger import (
    EVENT_ACTIVE_CARD_SELECTED,
    EVENT_CARD_MARKED_IMPORTANT,
    EVENT_CARD_MERGED,
    EVENT_CARD_PRIORITY_ADJUSTED,
    EVENT_CARD_STATUS_TRANSITIONED,
    EVENT_EVIDENCE_ADOPTED,
    EVENT_EVIDENCE_ENQUEUED,
    EVENT_EVIDENCE_REJECTED,
    EVENT_PRACTICE_SUBMISSION_RECORDED,
    EVENT_WORKSPACE_RESET,
)
from ..core.models import (
    ActiveCardSelectionResult,
    CardStatusTransitionResponse,
    DependencySkillMapHistoryEntry,
    EvidenceAdoptResponse,
    EvidenceItem,
    EvidenceQueueSnapshot,
    FlashcardAttempt,
    FlashDeckSnapshot,
    ReviewArtifactHistoryEntry,
    ReviewArtifactSnapshot,
    ScenarioLab,
    ScenarioLabHistoryEntry,
    TheoryDrillQuestion,
    TheoryDrillSnapshot,
    TrainingCardCandidateSnapshot,
)
from .coaching_adaptation_mixin import (
    _localized_memory_text,
    _workspace_language,
)
from .models import (
    utc_now,
)
from .semantic_helpers import (
    _CJK_TEXT_CORRECT_THRESHOLD,
    _cjk_answer_similarity,
    _contains_cjk_answer_text,
)
from .structured_memory_service import (
    StructuredMemoryService,
)
from .transfer_skills import (
    resolve_skill_scene_key,
)
from .workspace_recovery import (
    PLAN_RUNTIME_KEY,
    TRAINING_CHROME_KEY,
    attest_waiting_verify_on_adopt,
    bound_plan_leftover_training_live_identity_updates,
    formal_plan_is_live_runtime_identity,
    is_current_for_workspace,
    leftover_formal_training_labels,
    live_coach_stage_label,
    live_memory_snapshot_overlay,
    normalize_plan_runtime_recovery,
    select_plan_runtime_for_scope,
    stamp_workspace_scope,
)

logger = logging.getLogger(__name__)


class CardsAndEvidenceMixin:
    if TYPE_CHECKING:
        _canonical_workspace_id: Any
        _card_ledger: Any
        _event_ledger: Any
        _dependency_mastery_snapshots: Any
        _ensure_stage_progress: Any
        _leftover_persist_context: Any
        _normalize_dependency_key: Any
        _persist_structured: Any
        _persist_transfer_skill_state: Any
        _record_global_verified_outcome: Any
        _record_persisted_card_activity: Any
        _record_training_event: Any
        _record_verified_skill_scene: Any
        _refresh_training_next_challenge_after_runtime_advance: Any
        _resolve_workspace_for_write: Any
        _should_promote_verified_outcome_to_global: Any
        _structured_by_workspace: Any
        _structured_for: Any
        _sync_dependency_training_views: Any
        _sync_live_evidence_binding: Any
        _training_handoff_generator: Any
        _verified_scenes_for_concept: Any
        live_selected_training_card_id: Any
        persist_plan_runtime_advance_after_adopt: Any
        persist_plan_runtime_advance_after_verify: Any
        record_learning_outcome: Any
        repository: Any

    def clear_workspace_memory(self, workspace_id: str) -> None:
        self._structured_by_workspace.pop(workspace_id, None)

    def reset_workspace_training_state(self, workspace_id: str) -> dict[str, Any]:
        structured = self._structured_for(workspace_id)
        structured._training_cards = {}
        structured._card_ledger = []
        structured._active_training_card_routing = None
        structured._evidence_items = {}
        structured._dependency_skill_map_history = []
        structured._flash_deck = None
        structured._recent_flash_attempts = []
        structured._theory_drill = None
        structured._theory_drill_history = []
        structured._scenario_lab = None
        structured._scenario_lab_history = []
        structured._review_queue_actions = []
        structured._review_artifact = None
        structured._review_artifact_history = []
        structured._training_event_ledger = []
        structured.update_workspace(
            selected_card_id="",
            selected_card_status="",
            latest_training_submode="",
            latest_training_next_hop={},
            latest_flashcard_recovery_mode="",
        )
        self._persist_structured(workspace_id)
        self._card_ledger = [entry for entry in self._card_ledger if entry.get("workspace_id") != workspace_id]
        if self._event_ledger is not None:
            canonical_ws = self._canonical_workspace_id(workspace_id)
            try:
                self._event_ledger.record_event(
                    EVENT_WORKSPACE_RESET,
                    actor="learner",
                    scope="workspace",
                    project_id=canonical_ws,
                    workspace_id=canonical_ws,
                    payload_ref={"workspace_id": canonical_ws, "retain_resources": True},
                )
            except Exception:
                logger.exception("Could not record workspace reset in the event ledger")
        return {"workspace_id": workspace_id, "ok": True}

    def _build_flash_deck_snapshot(self, structured: StructuredMemoryService) -> FlashDeckSnapshot:
        language = _workspace_language(structured._workspace)

        def t(en: str, zh: str) -> str:
            return _localized_memory_text(en, zh, language)

        cards: list[TrainingCardCandidateSnapshot] = []
        for dependency_key, skill_map in structured._dependency_skill_maps.items():
            dependency_name = skill_map.dependency_name or dependency_key
            for index, item in enumerate(skill_map.items):
                layer_label = {
                    "api": t("API", "API"),
                    "scenario": t("Minimum scenario", "最小场景"),
                    "parameter": t("Parameter semantics", "参数语义"),
                    "return_value": t("Return value semantics", "返回值语义"),
                    "misuse": t("Misuse check", "误用检查"),
                    "concept": t("Dependency selection", "依赖选择"),
                    "verification": t("Verification method", "验证方法"),
                    "transfer": t("Cross-context transfer", "跨场景迁移"),
                }.get(item.layer, t("skill", "技能"))
                question = {
                    "parameter": t(
                        f"What does the parameter passed through {item.related_api or dependency_name} represent?",
                        f"经由 {item.related_api or dependency_name} 传入的这个参数到底表示什么？",
                    ),
                    "return_value": t(
                        f"What value comes back from {item.related_api or dependency_name} into the caller?",
                        f"{item.related_api or dependency_name} 返回给调用方的值是什么？",
                    ),
                    "misuse": t(
                        f"What is the most common misuse to avoid around {item.related_api or dependency_name}?",
                        f"围绕 {item.related_api or dependency_name} 最常见、需要避免的误用是什么？",
                    ),
                    "verification": t(
                        f"What is the smallest verification step for {dependency_name} here?",
                        f"这里要验证 {dependency_name}，最小的一步是什么？",
                    ),
                    "transfer": t(
                        f"How would you transfer this {dependency_name} judgment into a second project slice?",
                        f"如果换到第二个项目切片里，你会怎样迁移这次对 {dependency_name} 的判断？",
                    ),
                    "concept": t(
                        f"Why is {dependency_name} the right dependency choice for this boundary?",
                        f"为什么在这个边界上，{dependency_name} 是合适的依赖选择？",
                    ),
                    "scenario": t(
                        f"What is the minimum scenario that proves {dependency_name} belongs here?",
                        f"什么样的最小场景可以证明 {dependency_name} 应该放在这里？",
                    ),
                    "api": t(
                        f"When does {item.related_api or dependency_name} belong in the current slice?",
                        f"在当前切片里，{item.related_api or dependency_name} 应该在什么情况下出现？",
                    ),
                }.get(
                    item.layer,
                    t(
                        f"What should you verify about {dependency_name} next?",
                        f"下一步你最该验证 {dependency_name} 的哪一点？",
                    ),
                )
                expected_answer = {
                    "parameter": t(
                        "State the parameter meaning, the boundary it crosses, and why that input matters.",
                        "说明这个参数的含义、它穿过的边界，以及为什么这个输入重要。",
                    ),
                    "return_value": t(
                        "State what value returns into the caller and how that value proves the dependency behavior.",
                        "说明返回给调用方的值是什么，以及这个值如何证明依赖行为成立。",
                    ),
                    "misuse": t(
                        "Name the misuse, the boundary it breaks, and the guardrail that keeps the slice minimal.",
                        "指出误用方式、它会破坏哪条边界，以及保持切片最小的保护规则是什么。",
                    ),
                    "verification": t(
                        "Name one concrete verification method tied to the smallest changed boundary.",
                        "说出一个和最小改动边界直接对应的具体验证方法。",
                    ),
                    "transfer": t(
                        "Name the same judgment, the new context, and the proof that it still holds.",
                        "说出同样的判断、迁移后的新语境，以及它依然成立的证据。",
                    ),
                    "concept": t(
                        "Explain the concrete pressure, the dependency choice, and why a simpler boundary is not enough.",
                        "解释具体压力、依赖选择，以及为什么更简单的边界还不够。",
                    ),
                    "scenario": t(
                        "Describe the minimum scenario, the boundary, and the proof you expect back.",
                        "描述最小场景、目标边界，以及你期待看到的验证结果。",
                    ),
                    "api": t(
                        "Explain when the API belongs and what concrete pressure justifies it.",
                        "解释这个 API 何时该出现，以及是什么具体压力让它合理。",
                    ),
                }.get(
                    item.layer,
                    t(
                        "Give the smallest truthful explanation and one concrete proof.",
                        "给出最小但真实的解释，再补一个具体证据。",
                    ),
                )
                card = TrainingCardCandidateSnapshot(
                    card_id=f"skill-{dependency_key}-{item.layer}-{index}",
                    card_type="flash",
                    title=t(
                        f"Flash: {dependency_name} {item.layer or 'skill'}",
                        f"闪记卡：{dependency_name} {layer_label}",
                    ),
                    status="active",
                    created_from="dependency_mastery",
                    why_now=skill_map.priority_summary,
                    focus_area=skill_map.priority_summary,
                    target_skill=dependency_name,
                    knowledge_type=item.knowledge_type,
                    question=question,
                    answer_mode="text",
                    expected_answer=expected_answer,
                    hint_ladder=list(
                        item.hint_ladder
                        or [
                            t("State the boundary first.", "先把边界说清楚。"),
                            t("Then name the proof.", "再把证据说出来。"),
                        ]
                    ),
                    common_mistakes=[t("Widening scope before stating the boundary.", "还没说明边界，就先把范围放大了。")],
                    feedback={
                        "correct": t("Good. The dependency explanation stayed grounded.", "很好，这次对依赖的解释是贴着真实边界的。"),
                        "incorrect": t(
                            "Return to the smallest boundary and explain the meaning before coding.",
                            "先回到最小边界，把含义说清楚，再决定要不要动手写代码。",
                        ),
                    },
                    dependency_key=dependency_key,
                    dependency_layer=item.layer,
                    question_style=item.question_style,
                    verification_method=item.verification_method,
                )
                cards.append(card)
                structured._training_cards[card.card_id] = card
            fallback_card = TrainingCardCandidateSnapshot(
                card_id=f"skill-{dependency_key}-fallback",
                card_type="flash",
                title=t(
                    f"Flash: {dependency_name} scenario judgment",
                    f"闪记卡：{dependency_name} 场景判断",
                ),
                status="active",
                created_from="dependency_mastery",
                why_now=skill_map.priority_summary,
                focus_area=skill_map.priority_summary,
                target_skill=dependency_name,
                knowledge_type="scenario_judgment",
                question=t(
                    f"What is the smallest scenario that proves {dependency_name} belongs here?",
                    f"什么样的最小场景可以证明 {dependency_name} 应该放在这里？",
                ),
                answer_mode="text",
                expected_answer=t(
                    "State the minimum scenario, the dependency boundary, and one proof the behavior is correct.",
                    "先说最小场景、依赖边界，再补一个证明行为正确的证据。",
                ),
                hint_ladder=[
                    t("Name the scenario before the abstraction.", "先讲场景，再讲抽象。"),
                    t("Keep the slice to one boundary and one proof.", "只保留一条边界和一个证据。"),
                ],
                common_mistakes=[t("Naming the dependency without naming the real pressure first.", "先说依赖名字，却没有先说真实压力。")],
                feedback={
                    "correct": t("Good. The scenario stayed concrete.", "很好，这个场景保持得很具体。"),
                    "incorrect": t(
                        "Return to the concrete pressure before naming the dependency again.",
                        "先回到具体压力，再重新判断这项依赖。",
                    ),
                },
                dependency_key=dependency_key,
                dependency_layer="",
                question_style="scenario_answer",
                verification_method=t("Prove the same judgment in one minimum scenario.", "用一个最小场景证明这次判断依然成立。"),
            )
            cards.append(fallback_card)
            structured._training_cards[fallback_card.card_id] = fallback_card
        return FlashDeckSnapshot(
            id=f"flash-{uuid4().hex[:10]}",
            title=t("Dependency mastery flash deck", "dependency mastery 闪记卡组"),
            focus_area=t("dependency mastery", "dependency mastery"),
            cards=cards,
        )

    def _build_theory_drill_snapshot(self, structured: StructuredMemoryService) -> TheoryDrillSnapshot | None:
        language = _workspace_language(structured._workspace)

        def t(en: str, zh: str) -> str:
            return _localized_memory_text(en, zh, language)

        if not structured._dependency_skill_maps:
            return None
        questions: list[TheoryDrillQuestion] = []
        dependency_keys = list(structured._dependency_skill_maps.keys())
        for dependency_key, skill_map in structured._dependency_skill_maps.items():
            for index, item in enumerate(skill_map.items[:6]):
                questions.append(
                    TheoryDrillQuestion(
                        id=f"theory-{dependency_key}-{item.layer}-{index}",
                        prompt=f"{item.label}: {item.verification_method or skill_map.priority_summary}",
                        choices=[],
                        answer=t(
                            "Give the smallest grounded explanation and one concrete proof.",
                            "给出最小、贴着真实边界的解释，再补一个具体证据。",
                        ),
                        explanation=skill_map.priority_summary,
                        dependency_key=dependency_key,
                        dependency_layer=item.layer,
                        knowledge_type=item.knowledge_type,
                        question_style=item.question_style,
                    )
                )
        if not questions:
            return None
        return TheoryDrillSnapshot(
            id=f"theory-{uuid4().hex[:10]}",
            title=t("Theory drill: dependency mastery", "理论演练：dependency mastery"),
            focus_area=t("dependency mastery", "dependency mastery"),
            status="ready",
            summary=t("Rebuild the dependency judgment before widening scope.", "先重新建立对 dependency 的判断，再扩大范围。"),
            success_signal=t("The learner can explain the dependency boundary without bluffing.", "学习者能不靠猜测地讲清 dependency 边界。"),
            return_with=t("Return with the smallest explanation and one concrete proof.", "带着最小解释和一个具体证据回来。"),
            questions=questions,
            dependency_keys=dependency_keys,
        )

    _LEARNING_PHASE_ORDER = {
        "learn": 0,
        "try": 1,
        "verify": 2,
        "reflect": 3,
        "return": 4,
    }

    @staticmethod
    def _normalize_learning_phase(value: object | None) -> str:
        phase = str(value or "").strip().lower()
        return phase if phase in CardsAndEvidenceMixin._LEARNING_PHASE_ORDER else "learn"

    @classmethod
    def _learning_phase_for_card_status(cls, status: str, current_phase: str | None = None) -> str:
        current = cls._normalize_learning_phase(current_phase) if current_phase else "learn"
        if status in {"candidate", "needs_primer"}:
            return "learn"
        if status in {"active", "answered"}:
            return "try"
        if status in {"implemented", "completed"}:
            return "verify"
        if status == "reviewed":
            return "reflect"
        if status in {"fed_back", "archived"}:
            return "return"
        return current

    def _apply_card_learning_phase(
        self,
        workspace_id: str,
        card: TrainingCardCandidateSnapshot,
        phase: str,
    ) -> TrainingCardCandidateSnapshot:
        next_phase = self._normalize_learning_phase(phase)
        if card.learning_phase == next_phase:
            return card
        updated = card.model_copy(
            update={"learning_phase": next_phase, "updated_at": utc_now().isoformat()}
        )
        structured = self._structured_for(workspace_id)
        structured._training_cards[updated.card_id] = updated
        return updated

    def upsert_card(
        self,
        workspace_id: str,
        card: TrainingCardCandidateSnapshot,
        *,
        persist: bool = True,
    ) -> TrainingCardCandidateSnapshot:
        structured = self._structured_for(workspace_id)
        normalized = card.model_copy(
            update={
                "card_id": card.card_id or str(uuid4()),
                "learning_phase": self._normalize_learning_phase(
                    getattr(card, "learning_phase", None) or self._learning_phase_for_card_status(card.status)
                ),
                "updated_at": utc_now().isoformat(),
            }
        )
        structured._training_cards[normalized.card_id] = normalized
        self._record_training_event(
            structured,
            event_type="training_card_upserted",
            payload={
                "card_candidate_id": normalized.card_id,
                "card_candidate_type": normalized.card_type,
                "card_candidate_title": normalized.title,
            },
        )
        if persist:
            self._persist_structured(workspace_id)
        return normalized

    def get_card(
        self,
        workspace_id: str,
        card_id: str,
    ) -> TrainingCardCandidateSnapshot | None:
        structured = self._structured_for(workspace_id)
        card = structured._training_cards.get(card_id)
        if card is not None:
            return card
        if structured._flash_deck is not None:
            return next((item for item in structured._flash_deck.cards if item.card_id == card_id), None)
        return None

    def get_cards(self, workspace_id: str) -> list[TrainingCardCandidateSnapshot]:
        structured = self._structured_for(workspace_id)
        priority = {
            "needs_primer": 0,
            "active": 1,
            "candidate": 2,
            "answered": 3,
            "implemented": 4,
            "reviewed": 5,
            "fed_back": 6,
            "blocked": 7,
            "skipped": 8,
            "archived": 9,
        }
        cards = [
            item
            for item in structured._training_cards.values()
            if item.status != "archived" and item.review_state != "rejected"
        ]
        return sorted(
            cards,
            key=lambda item: (priority.get(item.status, 9), item.updated_at, item.card_id),
        )

    def persist_active_card_selection(
        self,
        workspace_id: str,
        selection: ActiveCardSelectionResult,
    ) -> ActiveCardSelectionResult:
        structured = self._structured_for(workspace_id)
        selected_card = selection.selected_card
        selected_card_scenario_pack = (
            getattr(selected_card, "scenario_pack", "") or ""
        ).strip()
        if selected_card is not None:
            existing = self.get_card(workspace_id, selected_card.card_id)
            if (existing or selected_card).review_state != "saved":
                raise ValueError("Save this card to the library before starting practice.")
            if existing is None:
                existing = self.upsert_card(workspace_id, selected_card)
            target_status = (
                "needs_primer"
                if (selected_card.status == "needs_primer" or existing.status == "needs_primer")
                else "active"
            )
            if existing.status != target_status:
                transition = self.transition_card_status(
                    workspace_id,
                    existing.card_id,
                    target_status,
                    reason="Persist active training card selection.",
                )
                selected_card = transition.card
            else:
                selected_card = existing
            selected_card_id = selected_card.card_id
            for other_card_id, other_card in list(structured._training_cards.items()):
                if other_card_id == selected_card_id or other_card.status != "active":
                    continue
                structured._training_cards[other_card_id] = other_card.model_copy(
                    update={
                        "status": "candidate",
                        "updated_at": utc_now().isoformat(),
                    }
                )
                self._record_training_event(
                    structured,
                    event_type="training_card_deactivated",
                    payload={
                        "card_candidate_id": other_card_id,
                        "previous_status": "active",
                        "new_status": "candidate",
                        "reason": "Single-card-first active routing selected another card.",
                    },
                )
            if selected_card_scenario_pack and not getattr(selected_card, "scenario_pack", "").strip():
                selected_card = selected_card.model_copy(
                    update={"scenario_pack": selected_card_scenario_pack}
                )
                structured._training_cards[selected_card.card_id] = selected_card
            selection = selection.model_copy(update={"selected_card": selected_card, "selected_card_id": selected_card.card_id})
        structured._active_training_card_routing = selection
        existing_next_hop = structured._workspace.get("latest_training_next_hop")
        next_hop = {
            **(existing_next_hop if isinstance(existing_next_hop, dict) else {}),
            "selected_card_id": selection.selected_card_id,
            "scenario_pack": selected_card_scenario_pack,
            "next_after_completion": selection.next_after_completion,
            "fallback_action": selection.fallback_action,
        }
        workspace_patch = {
            "selected_card_id": selection.selected_card_id or "",
            "selected_card_status": selection.selected_card.status if selection.selected_card else "",
            "latest_training_next_hop": next_hop,
            "live_training_selection": {
                "workspace_id": workspace_id,
                "card_id": selection.selected_card_id or "",
                "selected_at": utc_now().isoformat(),
            },
        }
        if selection.selected_card is not None:
            workspace_patch["latest_training_submode"] = selection.selected_card.card_type
        # Explicit bind: stamp card id onto recovered plan runtime (like /plan/generate
        # stamps plan_id) so leftover title/current_step cannot fake live identity.
        existing_runtime = structured._workspace.get(PLAN_RUNTIME_KEY)
        if not isinstance(existing_runtime, dict):
            existing_runtime = structured._workspace.get("latestPlanRuntime")
        if isinstance(existing_runtime, dict):
            runtime_record = dict(existing_runtime)
            runtime_record["selected_card_id"] = selection.selected_card_id or ""
            scoped = stamp_workspace_scope(runtime_record, workspace_id)
            if scoped is not None:
                workspace_patch[PLAN_RUNTIME_KEY] = scoped
        structured.update_workspace(**workspace_patch)
        self._record_training_event(
            structured,
            event_type="active_training_card_persisted",
            payload={
                "selected_card_id": selection.selected_card_id or "",
                "why_this_card": selection.why_this_card,
                "candidate_count": selection.candidate_count,
                "eligible_count": selection.eligible_count,
            },
        )
        self._persist_structured(workspace_id)
        if self._event_ledger is not None:
            canonical_ws = self._canonical_workspace_id(workspace_id)
            try:
                self._event_ledger.record_event(
                    EVENT_ACTIVE_CARD_SELECTED,
                    actor="learner",
                    scope="training",
                    project_id=canonical_ws,
                    workspace_id=canonical_ws,
                    payload_ref={"card_id": selection.selected_card_id or ""},
                )
            except Exception:
                logger.exception("Could not record active card selection in the event ledger")
        return selection

    def transition_card_status(
        self,
        workspace_id: str,
        card_id: str,
        new_status: str,
        reason: str = "",
        *,
        verified_by_evaluator: bool = False,
        archive_from_library: bool = False,
    ) -> CardStatusTransitionResponse:
        structured = self._structured_for(workspace_id)
        card = self.get_card(workspace_id, card_id)
        if card is None:
            raise ValueError(f"Card {card_id!r} not found")
        if card.review_state != "saved":
            raise ValueError("Save this card to the library before changing its practice status.")
        # A selected card is already `active` while it still sits at Learn.
        # The Training surface's "start" action sends active -> active with
        # reason=start_step; that is a phase advance, not a status conflict.
        if (
            new_status == "active"
            and card.status == "active"
            and str(getattr(card, "learning_phase", "") or "").strip().lower() == "learn"
            and reason == "start_step"
        ):
            updated = card.model_copy(
                update={"learning_phase": "try", "updated_at": utc_now().isoformat()}
            )
            structured._training_cards[card_id] = updated
            event = self._record_training_event(
                structured,
                event_type="training_card_started",
                payload={
                    "selected_card_id": card_id,
                    "candidate_status": card.status,
                    "learning_phase": "try",
                },
            )
            self._persist_structured(workspace_id)
            self._record_persisted_card_activity(
                workspace_id, updated, EVENT_CARD_STATUS_TRANSITIONED, event["event_id"], "started",
            )
            return CardStatusTransitionResponse(card=updated)
        allowed = {
            "candidate": {"active", "needs_primer", "skipped", "blocked"},
            "active": {"needs_primer", "answered", "implemented", "completed", "skipped", "blocked"},
            "needs_primer": {"active", "skipped", "blocked"},
            # Return credits a verified answered card as implemented; review is
            # the other allowed follow-up for a settled answer.
            "answered": {"implemented", "completed", "reviewed"},
            "implemented": {"reviewed", "completed"},
            "completed": {"reviewed"},
            "reviewed": {"fed_back", "archived"},
            "fed_back": {"archived"},
            "blocked": {"active"},
            "skipped": {"active"},
            "archived": set(),
        }
        archive = archive_from_library and new_status == "archived" and card.status != "archived"
        if not archive and new_status not in allowed.get(card.status, set()):
            raise ValueError(f"Invalid transition from {card.status} to {new_status}")
        if new_status in {"implemented", "completed"} and not verified_by_evaluator:
            raise ValueError(
                "A training card can only be marked implemented or completed after server-side verification."
            )
        if (card.card_type == "practice" and not archive
                and new_status in {"reviewed", "fed_back", "archived"}):
            has_verified_evidence = any(
                evidence.verified and evidence.source_card_id == card_id
                for evidence in structured._evidence_items.values()
            )
            if not has_verified_evidence:
                raise ValueError(
                    "A practice card needs server-side evidence before it can be reviewed, fed back, or archived."
                )
        updated = card.model_copy(
            update={
                "status": new_status,
                "learning_phase": self._learning_phase_for_card_status(
                    new_status,
                    getattr(card, "learning_phase", None),
                ),
                "updated_at": utc_now().isoformat(),
            }
        )
        structured._training_cards[card_id] = updated
        # The active-routing snapshot is what the training surface renders.
        # Without this sync a returned/implemented card keeps its old
        # active/verify shape and the completed return action stays visible.
        routing = structured._active_training_card_routing
        if routing is not None and routing.selected_card_id == card_id:
            structured._active_training_card_routing = routing.model_copy(
                update={"selected_card": updated, "selected_card_id": updated.card_id}
            )
        ledger_entry = {
            "card_id": card_id,
            "workspace_id": workspace_id,
            "previous_status": card.status,
            "new_status": new_status,
            "reason": reason,
            "transitioned_at": utc_now().isoformat(),
        }
        structured._card_ledger.append(ledger_entry)
        self._card_ledger.append(dict(ledger_entry))
        # A terminal skip/archive must release the live selection: otherwise the
        # workspace keeps pointing at a card that can no longer be trained, and
        # Training renders it as if it were still active while every governed
        # action is rejected. Clear only when the transitioned card is the
        # selected one so unrelated card transitions stay side-effect free.
        if new_status in {"skipped", "archived"}:
            selected_card_id = str(structured._workspace.get("selected_card_id") or "").strip()
            if selected_card_id == card_id:
                live_handoff = structured._workspace.get("latest_training_handoff")
                handoff_belongs_to_card = isinstance(live_handoff, dict) and card_id in {
                    str(live_handoff.get("card_id") or "").strip(),
                    str(live_handoff.get("candidate_id") or "").strip(),
                    str(live_handoff.get("target_id") or "").strip(),
                }
                structured.update_workspace(
                    selected_card_id="",
                    selected_card_status="",
                    latest_training_next_hop={},
                    live_training_selection={},
                    latest_training_handoff={} if handoff_belongs_to_card else None,
                )
                if (
                    structured._active_training_card_routing is not None
                    and structured._active_training_card_routing.selected_card_id == card_id
                ):
                    structured._active_training_card_routing = None
                existing_runtime = structured._workspace.get(PLAN_RUNTIME_KEY)
                if not isinstance(existing_runtime, dict):
                    existing_runtime = structured._workspace.get("latestPlanRuntime")
                if isinstance(existing_runtime, dict):
                    runtime_record = dict(existing_runtime)
                    if str(runtime_record.get("selected_card_id") or "") == card_id:
                        runtime_record["selected_card_id"] = ""
                        scoped = stamp_workspace_scope(runtime_record, workspace_id)
                        if scoped is not None:
                            structured.update_workspace(**{PLAN_RUNTIME_KEY: scoped})
        event = self._record_training_event(
            structured,
            event_type="training_card_status_changed",
            payload={
                "candidate_id": card_id,
                "candidate_status": new_status,
                "candidate_status_reason": reason,
            },
        )
        self._persist_structured(workspace_id)
        if new_status in {"active", "completed", "implemented", "skipped", "archived"}:
            self._record_persisted_card_activity(
                workspace_id,
                updated,
                EVENT_CARD_STATUS_TRANSITIONED,
                event["event_id"],
                "started" if new_status == "active" else new_status,
            )
        return CardStatusTransitionResponse(card=updated, ledger_entry=ledger_entry)

    def review_card_candidate(
        self,
        workspace_id: str,
        card: TrainingCardCandidateSnapshot,
        *,
        state: Literal["saved", "deferred", "rejected"],
        prompt: str | None = None,
        acceptance_criteria: list[str] | None = None,
    ) -> TrainingCardCandidateSnapshot:
        if card.review_state == state:
            return card
        if card.status not in {"candidate", "needs_primer"} or card.review_state not in {"pending", "deferred"}:
            raise ValueError("Only candidates awaiting review can be updated.")
        updates: dict[str, object] = {"review_state": state, "updated_at": utc_now().isoformat()}
        if state == "saved":
            updates["reviewed_at"] = updates["updated_at"]
        if prompt is not None:
            if not prompt.strip() or (card.card_type == "flash" and card.answer_mode != "text"):
                raise ValueError("Only a nonempty text prompt can be saved.")
            updates["question" if card.card_type == "flash" else "problem_statement"] = prompt.strip()
        if acceptance_criteria is not None:
            criteria = [item.strip() for item in acceptance_criteria if item.strip()]
            if not criteria:
                raise ValueError("Keep at least one acceptance criterion.")
            updates["acceptance_criteria"] = criteria
            updates["grading_rubric"] = criteria
            if card.card_type == "flash":
                updates["rubric"] = criteria
        updated = card.model_copy(update=updates)
        structured = self._structured_for(workspace_id)
        structured._training_cards[card.card_id] = updated
        self._record_training_event(
            structured,
            event_type=f"training_candidate_{state}",
            payload={"candidate_id": card.card_id, "card_candidate_title": card.title},
        )
        self._persist_structured(workspace_id)
        return updated

    # --------------------------------------------------------------
    # P1.4 candidate management: merge / mark important / priority.
    # The learner decides which candidates are worth keeping. All three ride
    # the existing card records, the existing structured ledger and the
    # unified event ledger — no second card store, no new status machine.
    # --------------------------------------------------------------

    def set_card_importance(
        self,
        workspace_id: str,
        card_id: str,
        important: bool,
    ) -> CardStatusTransitionResponse:
        structured = self._structured_for(workspace_id)
        card = self.get_card(workspace_id, card_id)
        if card is None:
            raise ValueError(f"Card {card_id!r} not found")
        updated = card.model_copy(
            update={"important": bool(important), "updated_at": utc_now().isoformat()}
        )
        structured._training_cards[card_id] = updated
        event = self._record_training_event(
            structured,
            event_type="training_card_importance_changed",
            payload={
                "candidate_id": card_id,
                "important": bool(important),
            },
        )
        self._persist_structured(workspace_id)
        self._record_persisted_card_activity(
            workspace_id, updated, EVENT_CARD_MARKED_IMPORTANT, event["event_id"],
            "important" if important else "unimportant",
        )
        return CardStatusTransitionResponse(card=updated)

    def set_card_priority(
        self,
        workspace_id: str,
        card_id: str,
        priority: int,
    ) -> CardStatusTransitionResponse:
        structured = self._structured_for(workspace_id)
        card = self.get_card(workspace_id, card_id)
        if card is None:
            raise ValueError(f"Card {card_id!r} not found")
        try:
            normalized = int(priority)
        except (TypeError, ValueError) as exc:
            raise ValueError("card priority must be an integer") from exc
        normalized = max(-5, min(5, normalized))
        updated = card.model_copy(
            update={"card_priority": normalized, "updated_at": utc_now().isoformat()}
        )
        structured._training_cards[card_id] = updated
        event = self._record_training_event(
            structured,
            event_type="training_card_priority_changed",
            payload={
                "candidate_id": card_id,
                "priority": normalized,
            },
        )
        self._persist_structured(workspace_id)
        self._record_persisted_card_activity(
            workspace_id, updated, EVENT_CARD_PRIORITY_ADJUSTED, event["event_id"],
            f"priority:{normalized}",
        )
        return CardStatusTransitionResponse(card=updated)

    def merge_training_cards(
        self,
        workspace_id: str,
        keep_card_id: str,
        duplicate_card_ids: list[str],
    ) -> CardStatusTransitionResponse:
        """Merge duplicate candidates into one keeper the learner chose.

        Only still-candidate duplicates merge — a card already in flight keeps
        its history. The keeper absorbs the duplicates' still-missing plan
        links, acceptance criteria, mistakes, hint steps and source chain, and
        each duplicate is archived in place with ``merged_into`` pointing at
        the keeper. Every step rides the existing card records and ledger.
        """
        structured = self._structured_for(workspace_id)
        keeper = self.get_card(workspace_id, keep_card_id)
        if keeper is None:
            raise ValueError(f"Card {keep_card_id!r} not found")
        wanted: list[str] = []
        for duplicate_id in duplicate_card_ids:
            normalized = str(duplicate_id or "").strip()
            if normalized and normalized != keep_card_id and normalized not in wanted:
                wanted.append(normalized)
        if not wanted:
            raise ValueError("Merging requires at least one other duplicate card")
        merged_sources = list(keeper.source_chain)
        merged_criteria = list(keeper.acceptance_criteria)
        merged_mistakes = list(keeper.common_mistakes)
        merged_plan_links = list(keeper.plan_links)
        merged_hint_ladder = list(keeper.hint_ladder)
        duplicates = []
        for duplicate_id in wanted:
            duplicate = self.get_card(workspace_id, duplicate_id)
            if duplicate is None:
                raise ValueError(f"Card {duplicate_id!r} not found")
            if duplicate.status != "candidate":
                raise ValueError(
                    f"Only candidate cards can be merged; {duplicate_id!r} is {duplicate.status!r}"
                )
            duplicates.append(duplicate)
        archived_count = 0
        for duplicate in duplicates:
            merged_sources.extend(
                source for source in duplicate.source_chain if source not in merged_sources
            )
            merged_criteria.extend(
                item for item in duplicate.acceptance_criteria if item not in merged_criteria
            )
            merged_mistakes.extend(
                item for item in duplicate.common_mistakes if item not in merged_mistakes
            )
            merged_plan_links.extend(
                link for link in duplicate.plan_links if link not in merged_plan_links
            )
            merged_hint_ladder.extend(
                hint for hint in duplicate.hint_ladder if hint not in merged_hint_ladder
            )
            structured._training_cards[duplicate.card_id] = duplicate.model_copy(
                update={
                    "status": "archived",
                    "merged_into": keep_card_id,
                    "updated_at": utc_now().isoformat(),
                }
            )
            archived_count += 1
        updated = keeper.model_copy(
            update={
                "source_chain": merged_sources,
                "acceptance_criteria": merged_criteria,
                "common_mistakes": merged_mistakes,
                "plan_links": merged_plan_links,
                "hint_ladder": merged_hint_ladder,
                "updated_at": utc_now().isoformat(),
            }
        )
        structured._training_cards[keep_card_id] = updated
        routing = structured._active_training_card_routing
        if routing is not None and routing.selected_card_id == keep_card_id:
            structured._active_training_card_routing = routing.model_copy(
                update={"selected_card": updated, "selected_card_id": updated.card_id}
            )
        event = self._record_training_event(
            structured,
            event_type="training_cards_merged",
            payload={
                "keep_card_id": keep_card_id,
                "merged_card_ids": wanted,
            },
        )
        self._persist_structured(workspace_id)
        self._record_persisted_card_activity(
            workspace_id, updated, EVENT_CARD_MERGED, event["event_id"],
            f"merged:{archived_count}",
        )
        return CardStatusTransitionResponse(card=updated)

    def enqueue_evidence(
        self,
        workspace_id: str,
        item: EvidenceItem,
        *,
        verified: bool = False,
        verification_source: str = "",
        auto_bind_current_plan: bool = True,
        bound_plan_step: str = "",
    ) -> EvidenceItem:
        structured = self._structured_for(workspace_id)
        normalized = item.model_copy(
            update={
                "id": item.id or f"ev-{uuid4().hex[:10]}",
                "workspace_id": workspace_id,
                "timestamp": item.timestamp or utc_now().isoformat(),
                "verified": verified,
                # Unverified evidence keeps no trust source, except the explicit
                # self-reported provenance: it is honest about where the claim
                # came from while remaining non-trusted (verified stays False).
                "verification_source": (
                    verification_source.strip()
                    if verified or verification_source.strip() == "self_reported"
                    else ""
                ),
                "trust_level": "controlled_check" if verified else "self_reported",
                "target_plan_step": bound_plan_step.strip(),
            }
        )
        recovered = select_plan_runtime_for_scope(structured._workspace.get(PLAN_RUNTIME_KEY), workspace_id)
        if auto_bind_current_plan and recovered and normalized.target_plan_stage_id:
            plan = self.repository.get_latest_plan(workspace_id)
            if (
                plan
                and normalized.target_plan_stage_id == plan.current_stage_id
                and formal_plan_is_live_runtime_identity(plan=plan, runtime=recovered, existing=recovered)
            ):
                normalized = normalized.model_copy(
                    update={"target_plan_step": str(recovered.get("current_step") or "").strip()}
                )
        if auto_bind_current_plan and not str(normalized.target_plan_stage_id or "").strip():
            # Auto-bind unscoped evidence to the recovered runtime's current step
            # so it stays live pending instead of draining into history.
            recovered = normalize_plan_runtime_recovery(structured._workspace.get(PLAN_RUNTIME_KEY))
            if recovered is not None and is_current_for_workspace(recovered, workspace_id):
                current_step = str(recovered.get("current_step") or "").strip()
                if current_step:
                    normalized = normalized.model_copy(update={"target_plan_stage_id": current_step})
        structured._evidence_items[normalized.id] = normalized
        try:
            self._persist_structured(workspace_id)
        except Exception:
            structured._evidence_items.pop(normalized.id, None)
            raise
        if self._event_ledger is not None:
            canonical_ws = self._canonical_workspace_id(workspace_id)
            try:
                self._event_ledger.record_event(
                    EVENT_EVIDENCE_ENQUEUED,
                    actor="system" if verified else "learner",
                    scope="training",
                    project_id=canonical_ws,
                    workspace_id=canonical_ws,
                    payload_ref={"evidence_id": normalized.id, "verified": verified},
                    idempotency_key=f"evidence_enqueued:{normalized.id}",
                )
            except Exception:
                logger.exception("Could not record enqueued evidence in the event ledger")
        return normalized

    def latest_handoff_evidence(
        self,
        workspace_id: str,
    ) -> tuple[str, list[Any]]:
        """The latest persisted handoff's evidence records, workspace-scoped.

        Handoff evidence is serialized inside ``latest_training_handoff``; this
        accessor lets the unified evidence view read it without a second store.
        """
        scope = self._resolve_workspace_for_write(workspace_id)
        structured = self._structured_for(scope)
        payload = structured._workspace.get("latest_training_handoff")
        if not isinstance(payload, dict):
            return "", []
        generator = self._training_handoff_generator(scope)
        handoff = generator.hydrate_handoff(payload)
        if handoff is None:
            return "", []
        return handoff.handoff_id, list(handoff.evidence)

    def evidence_queue(self, workspace_id: str) -> EvidenceQueueSnapshot:
        from .evidence_view import build_evidence_queue_snapshot

        structured = self._structured_for(workspace_id)
        items = list(structured._evidence_items.values())
        recovered = normalize_plan_runtime_recovery(structured._workspace.get(PLAN_RUNTIME_KEY))
        recovered_runtime = bool(recovered) and is_current_for_workspace(recovered, workspace_id)
        return build_evidence_queue_snapshot(
            items=items,
            workspace_id=workspace_id,
            recovered=recovered,
            recovered_runtime=recovered_runtime,
            current_plan_id=str((recovered or {}).get("plan_id") or ""),
            current_stage_id=str((recovered or {}).get("current_stage_id") or ""),
            current_step=str((recovered or {}).get("current_step") or ""),
        )

    def _adopted_return_transfer_concepts(
        self,
        workspace_id: str,
        evidence: EvidenceItem,
    ) -> list[str]:
        leftover_plan, leftover_runtime, leftover_task = self._leftover_persist_context(workspace_id)
        recovered_step = str(
            (leftover_runtime or {}).get("current_step")
            or (leftover_runtime or {}).get("currentStep")
            or ""
        ).strip()
        live_plan = formal_plan_is_live_runtime_identity(
            plan=leftover_plan,
            runtime=leftover_runtime,
            existing=leftover_runtime,
            current_step=recovered_step,
        )
        leftover_labels = leftover_formal_training_labels(
            plan=leftover_plan,
            task_title=leftover_task,
            live_plan=live_plan,
            live_task=False,
        )
        concepts: list[str] = []
        for item in evidence.concepts:
            text = str(item or "").strip()
            if text and text not in leftover_labels and text not in concepts:
                concepts.append(text)
        return concepts

    def _record_adopted_return_transfer(
        self,
        workspace_id: str,
        evidence: EvidenceItem,
    ) -> None:
        """Project-scoped until a second distinct workspace proves the same skill. Never invent a plan."""

        if evidence.source != "training_handoff_return":
            return
        if not evidence.verified or evidence.outcome != "pass":
            return
        if not (evidence.summary or "").strip():
            return
        concepts = self._adopted_return_transfer_concepts(workspace_id, evidence)
        if not concepts:
            return
        concept = concepts[0]
        self._record_verified_skill_scene(
            workspace_id=workspace_id,
            concept=concept,
            scene_key=resolve_skill_scene_key(scenario=evidence.source),
        )
        structured = self._structured_for(workspace_id)
        structured.remember_learning_outcome(
            concept,
            "tests_passed",
            summary=evidence.summary,
            action_type="training_handoff_return",
            verified_by_evaluator=True,
            verified_result=evidence.summary,
        )
        should_promote = self._should_promote_verified_outcome_to_global(
            concepts=[concept],
            workspace_id=workspace_id,
        )
        self._persist_transfer_skill_state(
            workspace_id=workspace_id,
            concept=concept,
            language=str(structured._workspace.get("response_language") or ""),
            schedule_review=should_promote,
        )
        if should_promote and (evidence.summary or "").strip():
            scenes = self._verified_scenes_for_concept(concept)
            self._record_global_verified_outcome(
                [concept],
                "tests_passed",
                workspace_id=workspace_id,
                scene_count=len(scenes),
            )

    def adopt_evidence(self, workspace_id: str, evidence_id: str) -> EvidenceAdoptResponse:
        structured = self._structured_for(workspace_id)
        evidence = structured._evidence_items.get(evidence_id)
        if evidence is None or evidence.adopted or evidence.rejected_at:
            raise HTTPException(status_code=404, detail="Evidence item not found.")
        queue = self.evidence_queue(workspace_id)
        if any(item.id == evidence_id for item in queue.history):
            raise HTTPException(
                status_code=409,
                detail="Historical evidence does not belong to the current step. Verify the current task before adopting evidence.",
            )
        independent_evidence = any(item.id == evidence_id for item in queue.unscoped)
        adopted = evidence.model_copy(
            update={
                "adopted": True,
                "adopted_at": utc_now().isoformat(),
                **attest_waiting_verify_on_adopt(evidence),
            }
        )
        structured._evidence_items[evidence_id] = adopted

        if independent_evidence:
            self._record_adopted_return_transfer(workspace_id, adopted)
            self._persist_structured(workspace_id)
            if self._event_ledger is not None:
                canonical_ws = self._canonical_workspace_id(workspace_id)
                try:
                    self._event_ledger.record_event(
                        EVENT_EVIDENCE_ADOPTED,
                        actor="learner",
                        scope="training",
                        project_id=canonical_ws,
                        workspace_id=canonical_ws,
                        payload_ref={"evidence_id": adopted.id, "independent": True},
                        idempotency_key=f"evidence_adopted:{adopted.id}",
                    )
                except Exception:
                    logger.exception("Could not record adopted evidence in the event ledger")
            return EvidenceAdoptResponse(
                evidence=adopted,
                plan_updated=False,
                plan_change_summary="Independent evidence adopted without plan or training context changes.",
            )

        plan_updated = False
        plan_change_summary = ""
        plan = self.repository.get_latest_plan(workspace_id)
        recovered_runtime = select_plan_runtime_for_scope(
            structured._workspace.get(PLAN_RUNTIME_KEY),
            workspace_id,
        )
        leftover_plan_is_live = formal_plan_is_live_runtime_identity(
            plan=plan,
            runtime=recovered_runtime,
            existing=recovered_runtime,
        )
        if (
            leftover_plan_is_live
            and plan
            and not plan.frozen
            and adopted.outcome == "pass"
            and adopted.verified
        ):
            active_index = next(
                (
                    index
                    for index, stage in enumerate(plan.stages)
                    if stage.id == (adopted.target_plan_stage_id or plan.current_stage_id) or stage.status == "active"
                ),
                0,
            )
            if 0 <= active_index < len(plan.stages):
                active_stage = plan.stages[active_index]
                concept_set = {self._normalize_dependency_key(item) for item in adopted.concepts}
                outcome_set = {self._normalize_dependency_key(item) for item in active_stage.outcomes}
                if adopted.target_plan_stage_id == active_stage.id or concept_set & outcome_set:
                    active_stage.status = "completed"
                    next_stage = plan.stages[active_index + 1] if active_index + 1 < len(plan.stages) else None
                    if next_stage is not None:
                        next_stage.status = "active"
                        plan.current_stage_id = next_stage.id
                        plan.current_step = next_stage.goal or next_stage.title
                        plan.verify_method = list(next_stage.outcomes)
                        following_stage = plan.stages[active_index + 2] if active_index + 2 < len(plan.stages) else None
                        plan.next_after_current = following_stage.goal if following_stage else ""
                        plan_change_summary = f"Advanced from {active_stage.title} to {next_stage.title}."
                    else:
                        plan.current_stage_id = active_stage.id
                        plan_change_summary = f"Completed {active_stage.title}."
                    plan.blocked_reason = ""
                    plan.why_now = adopted.summary
                    plan.updated_at = utc_now().isoformat()
                    from_label = live_coach_stage_label(
                        plan=plan,
                        runtime=recovered_runtime,
                        existing=recovered_runtime,
                        stage_title=active_stage.title,
                    )
                    to_label = (
                        live_coach_stage_label(
                            plan=plan,
                            runtime=recovered_runtime,
                            existing=recovered_runtime,
                            stage_title=next_stage.title,
                        )
                        if next_stage is not None
                        else ""
                    )
                    if from_label and to_label:
                        plan_change_summary = f"Advanced from {from_label} to {to_label}."
                    elif from_label:
                        plan_change_summary = f"Completed {from_label}."
                    else:
                        plan_change_summary = live_memory_snapshot_overlay(
                            plan=plan,
                            runtime=recovered_runtime,
                            existing=recovered_runtime,
                            plan_change_summary=plan_change_summary,
                        )["plan_change_summary"]
                    plan_updated = True
                    from ..training.plan_revision import save_plan_advancing_revision

                    save_plan_advancing_revision(self.repository, workspace_id, plan)
        advanced = (
            self.persist_plan_runtime_advance_after_verify(workspace_id, plan, request_id=adopted.id)
            if plan_updated
            else self.persist_plan_runtime_advance_after_adopt(workspace_id, adopted)
        )
        if advanced and leftover_plan_is_live and plan and not plan.frozen:
            plan_updated = True
        self._refresh_training_next_challenge_after_runtime_advance(
            workspace_id,
            advanced or recovered_runtime,
        )
        if not isinstance(advanced, dict) or not str(advanced.get("current_step") or "").strip():
            leftover_training = bound_plan_leftover_training_live_identity_updates(
                workspace_id=workspace_id,
                generated_step="",
                workspace=structured._workspace if isinstance(structured._workspace, dict) else {},
            )
            if leftover_training:
                structured.update_workspace(**leftover_training)
        self._record_adopted_return_transfer(workspace_id, adopted)
        self._sync_live_evidence_binding(workspace_id)
        refreshed_runtime = advanced or recovered_runtime
        if isinstance(refreshed_runtime, dict) and str(refreshed_runtime.get("current_step") or "").strip():
            structured = self._structured_for(workspace_id)
            current_title = str(refreshed_runtime["current_step"]).strip()
            current_hop = structured._workspace.get("latest_training_next_hop")
            if isinstance(current_hop, dict):
                structured.update_workspace(
                    latest_training_next_hop=stamp_workspace_scope(
                        {**current_hop, "title": current_title, "card_title": current_title},
                        workspace_id,
                    ),
                    selected_card_title=current_title,
                    **{
                        TRAINING_CHROME_KEY: stamp_workspace_scope(
                            {"selected_card_title": current_title},
                            workspace_id,
                        )
                    },
                )
        self._persist_structured(workspace_id)
        if self._event_ledger is not None:
            canonical_ws = self._canonical_workspace_id(workspace_id)
            try:
                self._event_ledger.record_event(
                    EVENT_EVIDENCE_ADOPTED,
                    actor="learner",
                    scope="training",
                    project_id=canonical_ws,
                    workspace_id=canonical_ws,
                    payload_ref={"evidence_id": adopted.id, "plan_updated": plan_updated},
                    idempotency_key=f"evidence_adopted:{adopted.id}",
                )
            except Exception:
                logger.exception("Could not record adopted evidence in the event ledger")
        return EvidenceAdoptResponse(
            evidence=adopted,
            plan_updated=plan_updated,
            plan_change_summary=plan_change_summary or "Evidence adopted without plan stage changes.",
        )

    def reject_evidence(self, workspace_id: str, evidence_id: str, reason: str = "") -> EvidenceItem:
        structured = self._structured_for(workspace_id)
        evidence = structured._evidence_items.get(evidence_id)
        if evidence is None or evidence.adopted or evidence.rejected_at:
            raise HTTPException(status_code=404, detail="Evidence item not found.")
        rejected = evidence.model_copy(
            update={
                "rejected_at": utc_now().isoformat(),
                "rejection_reason": reason,
            }
        )
        structured._evidence_items[evidence_id] = rejected
        self._persist_structured(workspace_id)
        self._sync_live_evidence_binding(workspace_id)
        if self._event_ledger is not None:
            canonical_ws = self._canonical_workspace_id(workspace_id)
            try:
                self._event_ledger.record_event(
                    EVENT_EVIDENCE_REJECTED,
                    actor="learner",
                    scope="training",
                    project_id=canonical_ws,
                    workspace_id=canonical_ws,
                    payload_ref={"evidence_id": rejected.id, "reason": reason},
                    idempotency_key=f"evidence_rejected:{rejected.id}",
                )
            except Exception:
                logger.exception("Could not record rejected evidence in the event ledger")
        return rejected

    def defer_evidence(self, workspace_id: str, evidence_id: str, reason: str = "") -> EvidenceItem:
        structured = self._structured_for(workspace_id)
        evidence = structured._evidence_items.get(evidence_id)
        if evidence is None or evidence.adopted or evidence.rejected_at:
            raise HTTPException(status_code=404, detail="Evidence item not found.")
        deferred = evidence.model_copy(
            update={
                "deferred_at": utc_now().isoformat(),
                "deferral_reason": reason,
            }
        )
        structured._evidence_items[evidence_id] = deferred
        self._persist_structured(workspace_id)
        self._sync_live_evidence_binding(workspace_id)
        return deferred

    def build_flash_deck(self, workspace_id: str) -> FlashDeckSnapshot:
        structured = self._structured_for(workspace_id)
        self._sync_dependency_training_views(structured)
        if structured._flash_deck is None:
            structured._flash_deck = self._build_flash_deck_snapshot(structured)
        self._persist_structured(workspace_id)
        return structured._flash_deck

    def submit_flashcard_answer(
        self,
        workspace_id: str,
        card_id: str,
        learner_answer: str = "",
        selected_option_index: int | None = None,
        selected_option_indices: list[int] | None = None,
        fill_blank_answers: dict[str, str] | None = None,
        sort_order: list[int] | None = None,
    ) -> FlashcardAttempt:
        structured = self._structured_for(workspace_id)
        self._sync_dependency_training_views(structured)
        card = self.get_card(workspace_id, card_id)
        if card is not None and (card.review_state != "saved" or card.status == "archived"):
            raise HTTPException(status_code=409, detail="Select an available card from your library.")
        if card is not None and card.reviewed_at and self.live_selected_training_card_id(workspace_id) != card_id:
            raise HTTPException(status_code=409, detail="Open this card for practice before answering.")
        answer_text = learner_answer.strip()
        selected_indices = sorted(
            {
                int(index)
                for index in (selected_option_indices or [])
                if isinstance(index, int) and index >= 0
            }
        )
        if selected_option_index is not None and selected_option_index >= 0 and selected_option_index not in selected_indices:
            selected_indices.append(selected_option_index)
            selected_indices.sort()
        submitted_blanks = {
            str(key): str(value).strip()
            for key, value in (fill_blank_answers or {}).items()
            if str(value).strip()
        }
        submitted_sort_order = [
            int(index)
            for index in (sort_order or [])
            if isinstance(index, int) and index >= 0
        ]
        dependency_history: list[DependencySkillMapHistoryEntry] = []
        if card is None:
            raise HTTPException(
                status_code=404,
                detail="Flashcard not found. Refresh Training to load the current cards.",
            )

        answer_mode = str(card.answer_mode or "text").strip().lower()
        answer_mode = {
            "choice": "single_choice",
            "single": "single_choice",
            "multiple": "multiple_choice",
            "multi": "multiple_choice",
            "fill": "fill_blank",
            "truefalse": "true_false",
            "boolean": "true_false",
        }.get(answer_mode, answer_mode)
        expected_indices = sorted(
            {
                int(index)
                for index in (card.correct_option_indices or [])
                if isinstance(index, int) and index >= 0
            }
        )
        if not expected_indices and card.correct_option_index is not None:
            expected_indices = [card.correct_option_index]
        expected_blanks = {
            str(key): str(value).strip()
            for key, value in (card.fill_blank_answers or {}).items()
            if str(value).strip()
        }
        expected_sort_order = [
            int(index)
            for index in (card.correct_sort_order or [])
            if isinstance(index, int) and index >= 0
        ]
        score = 0.0
        mismatches: list[str] = []
        correct = False
        if answer_mode in {"single_choice", "true_false"}:
            correct = bool(expected_indices and selected_indices == expected_indices)
            score = 1.0 if correct else 0.0
            if not correct:
                mismatches.append("selected_option")
        elif answer_mode == "multiple_choice":
            expected_set = set(expected_indices)
            selected_set = set(selected_indices)
            if expected_set:
                score = len(expected_set & selected_set) / len(expected_set)
            correct = bool(expected_set and selected_set == expected_set)
            if selected_set - expected_set:
                mismatches.append("extra_options")
            if expected_set - selected_set:
                mismatches.append("missing_options")
        elif answer_mode == "sorting":
            if expected_sort_order:
                matched = sum(
                    expected == actual
                    for expected, actual in zip(expected_sort_order, submitted_sort_order, strict=False)
                )
                score = matched / len(expected_sort_order)
            correct = bool(expected_sort_order and submitted_sort_order == expected_sort_order)
            if not correct:
                mismatches.append("sort_order")
        elif answer_mode == "fill_blank" and expected_blanks:
            expected_values = [
                expected_blanks[key]
                for key in sorted(expected_blanks, key=lambda value: int(value) if value.isdigit() else value)
            ]
            submitted_values = [
                submitted_blanks[key]
                for key in sorted(submitted_blanks, key=lambda value: int(value) if value.isdigit() else value)
            ]
            if len(expected_values) == len(submitted_values):
                matched = sum(
                    re.sub(r"\s+", " ", expected.lower()) == re.sub(r"\s+", " ", actual.lower())
                    for expected, actual in zip(expected_values, submitted_values, strict=False)
                )
                score = matched / len(expected_values) if expected_values else 0.0
            correct = bool(expected_values and score == 1.0)
            if not correct:
                mismatches.append("fill_blank")
        elif card.expected_answer:
            expected = re.sub(r"\s+", " ", card.expected_answer.strip().lower())
            answer = re.sub(r"\s+", " ", answer_text.lower())
            exact = answer and answer == expected
            containment = answer and (answer in expected or expected in answer)
            stop_words = {"a", "an", "and", "are", "for", "in", "is", "of", "on", "or", "the", "to", "use", "with"}
            expected_tokens = {
                token for token in re.split(r"[^a-z0-9]+", expected)
                if len(token) > 2 and token not in stop_words
            }
            answer_tokens = {
                token for token in re.split(r"[^a-z0-9]+", answer)
                if len(token) > 2 and token not in stop_words
            }
            overlap = len(expected_tokens & answer_tokens)
            overlap_threshold = max(3, (len(expected_tokens) + 1) // 2)
            correct = bool(exact or containment or (expected_tokens and overlap >= overlap_threshold))
            if not correct and card.dependency_key:
                normalized_answer = answer.replace(" ", "")
                dependency_hint = card.dependency_key.replace("-", "")
                correct = dependency_hint in normalized_answer
            score = 1.0 if correct else 0.0
            if not correct and (_contains_cjk_answer_text(expected) or _contains_cjk_answer_text(answer)):
                # CJK fallback: latin tokenization yields no tokens for Chinese
                # text, so grade paraphrases by CJK bigram/unigram Dice instead.
                coefficient = _cjk_answer_similarity(expected, answer)
                if coefficient >= _CJK_TEXT_CORRECT_THRESHOLD:
                    correct = True
                    score = coefficient
            if not correct:
                mismatches.append("text_answer")
        else:
            correct = False
            mismatches.append("missing_answer_key")

        if card.status == "active":
            next_status = "answered" if correct else "needs_primer"
            transition_reason = (
                "Flashcard answer submitted."
                if correct
                else "Flashcard answer was incorrect; keep the card for retry and reinforcement."
            )
            self.transition_card_status(
                workspace_id,
                card.card_id,
                next_status,
                reason=transition_reason,
            )
            card = self.get_card(workspace_id, card.card_id) or card

        detail = (
            "Flashcard answer matches the answer key."
            if correct
            else "Flashcard answer needs another pass against the answer key."
        )
        feedback: dict[str, Any] = {
            "kind": "flashcard_answer",
            "answer_mode": answer_mode,
            "correct": correct,
            "score": round(score, 3),
            "detail": detail,
            "retry_required": not correct,
            "mismatches": mismatches,
            "expected_option_indices": expected_indices,
            "selected_option_indices": selected_indices,
            "expected_sort_order": expected_sort_order,
            "submitted_sort_order": submitted_sort_order,
            "expected_fill_blank_answers": expected_blanks,
            "submitted_fill_blank_answers": submitted_blanks,
        }
        updated_card = card.model_copy(
            update={
                "last_feedback": feedback,
                "learner_answer": learner_answer,
                "learner_selected_option_indices": selected_indices,
                "learner_fill_blank_answers": submitted_blanks,
                "learner_sort_order": submitted_sort_order,
                "updated_at": utc_now().isoformat(),
            }
        )
        structured._training_cards[card.card_id] = updated_card
        card = updated_card

        if card.focus_area:
            structured.update_mastery(
                card.focus_area,
                delta=0.08 if correct else -0.02,
                confidence=0.72 if correct else 0.55,
                review_after_days=2 if correct else 1,
            )

        if card.dependency_key:
            dependency_key = self._normalize_dependency_key(card.dependency_key)
            current = structured._dependency_mastery.get(dependency_key) or {}
            current_stage = str(current.get("mastery_stage") or "understood")
            next_stage = "recalled" if correct else current_stage
            if correct:
                structured.upsert_dependency_mastery(
                    dependency_key,
                    dependency_name=str(current.get("dependency_name") or dependency_key),
                    apis=list(current.get("apis") or []),
                    use_cases=list(current.get("use_cases") or []),
                    scenarios=list(current.get("scenarios") or []),
                    weakest_points=list(current.get("weakest_points") or []),
                    evidence=list(current.get("evidence") or []),
                    mastery_stage=next_stage,
                    mastery_stage_progress=self._ensure_stage_progress(
                        list(current.get("mastery_stage_progress") or []),
                        next_stage,
                    ),
                )
            else:
                structured.update_workspace(latest_flashcard_recovery_mode="flashcards")
                self._sync_dependency_training_views(structured)
                current_map = structured._dependency_skill_maps.get(dependency_key)
                focus_item = next(
                    (
                        item
                        for item in (current_map.top_review_items if current_map else [])
                        if item.layer == card.dependency_layer
                    ),
                    None,
                ) or (current_map.top_review_items[0] if current_map and current_map.top_review_items else None)
                if current_map is not None and focus_item is not None:
                    entry = DependencySkillMapHistoryEntry(
                        entry_id=f"hist-{uuid4().hex[:10]}",
                        dependency_key=dependency_key,
                        action="flash_retry",
                        version=current_map.version,
                        focus_item_key=focus_item.key,
                        focus_label=focus_item.label,
                        note="Flashcard answer showed the dependency layer is still unstable.",
                        before_snapshot=current_map.model_dump(mode="json"),
                        after_snapshot=current_map.model_dump(mode="json"),
                        after_summary=current_map.priority_summary,
                    )
                    structured._dependency_skill_map_history.append(entry)
                    dependency_history = [entry]

        attempt = FlashcardAttempt(
            card_id=card.card_id,
            correct=correct,
            score=round(score, 3),
            detail=detail,
            learner_answer=learner_answer,
            selected_option_index=selected_option_index,
            selectedOptionIndices=selected_indices,
            fillBlankAnswers=submitted_blanks,
            sortOrder=submitted_sort_order,
            answer_mode=answer_mode,
            feedback=feedback,
            dependency_key=card.dependency_key,
            dependency_layer=card.dependency_layer,
            question_style=card.question_style,
            knowledge_type=card.knowledge_type,
            dependency_mastery=self._dependency_mastery_snapshots(structured),
            dependency_skill_map_history=dependency_history,
        )
        structured._recent_flash_attempts.insert(0, attempt)
        structured._recent_flash_attempts = structured._recent_flash_attempts[:16]
        self._persist_structured(workspace_id)
        self._record_persisted_card_activity(
            workspace_id, card, EVENT_PRACTICE_SUBMISSION_RECORDED, attempt.recorded_at,
        )
        return attempt

    def build_scenario_lab(self, workspace_id: str) -> ScenarioLab | None:
        structured = self._structured_for(workspace_id)
        self._sync_dependency_training_views(structured)
        dependency_items = self._dependency_mastery_snapshots(structured)
        if not dependency_items:
            return None
        primary = dependency_items[0]
        workspace = structured._workspace
        scenario_lab = ScenarioLab(
            id=f"scenario-{uuid4().hex[:10]}",
            title=f"Scenario lab: {workspace.get('latest_learning_focus_area') or primary.dependency_name or primary.dependency_key}",
            focus_area=str(workspace.get("latest_learning_focus_area") or primary.dependency_name or primary.dependency_key),
            status="ready",
            summary=str(workspace.get("latest_learning_blocker") or "Rebuild the dependency judgment in one minimum scenario."),
            success_signal=str(
                workspace.get("latest_turn_success_signal")
                or "The minimum scenario proves the dependency behavior without widening scope."
            ),
            learner_deliverables=[
                str(workspace.get("latest_turn_expected_artifact") or "One minimum implementation artifact."),
            ],
            verification_steps=list(workspace.get("latest_turn_coach_checks") or ["Verify the boundary before widening scope."]),
            migrate_back_guidance=[
                str(workspace.get("latest_turn_after_try") or "Bring back the proof before migrating into the main project."),
                str(workspace.get("latest_turn_teach_back_prompt") or "Teach back why the dependency belongs."),
            ],
            dependency_keys=[primary.dependency_key],
            related_apis=list(primary.apis[:3]),
            minimum_environment=[
                "One isolated file, route, or function boundary.",
                "Exactly one dependency judgment under test.",
            ],
            last_action="created",
            version=1,
        )
        structured._scenario_lab = scenario_lab
        history = ScenarioLabHistoryEntry(
            entry_id=f"hist-{uuid4().hex[:10]}",
            scenario_lab_id=scenario_lab.id,
            action="created",
            version=1,
            note="Created from current dependency mastery and workspace signals.",
            before_snapshot={},
            after_snapshot=scenario_lab.model_dump(mode="json"),
        )
        structured._scenario_lab_history.append(history)
        structured.update_workspace(latest_training_submode="practice")
        self._persist_structured(workspace_id)
        return scenario_lab

    def apply_scenario_lab_action(
        self,
        workspace_id: str,
        scenario_lab_id: str,
        action: str,
        note: str = "",
        review_outcome: str = "",
        *,
        verified_by_evaluator: bool = False,
        verification_source: str = "",
    ) -> tuple[ScenarioLab | None, list[ScenarioLabHistoryEntry]]:
        structured = self._structured_for(workspace_id)
        if structured._scenario_lab is None or structured._scenario_lab.id != scenario_lab_id:
            return None, []
        scenario_lab = structured._scenario_lab
        if scenario_lab is None:
            return None, []
        if action == "complete":
            if scenario_lab.status != "in_progress":
                raise ValueError("Start the current scenario lab before completing it.")
            if not verified_by_evaluator or not verification_source.strip():
                raise ValueError(
                    "Scenario lab completion needs server-side verification. Run a Trainer evaluation, then refresh this lab."
                )
        status_map = {"start": "in_progress", "complete": "completed", "archive": "archived"}
        history_action = {"start": "started", "complete": "completed", "archive": "archived"}.get(action, action)
        updated = scenario_lab.model_copy(
            update={
                "status": status_map.get(action, scenario_lab.status),
                "last_action": action,
                "review_outcome": review_outcome or scenario_lab.review_outcome,
                "version": scenario_lab.version + 1,
                "updated_at": utc_now().isoformat(),
            }
        )
        structured._scenario_lab = updated
        history_entry = ScenarioLabHistoryEntry(
            entry_id=f"hist-{uuid4().hex[:10]}",
            scenario_lab_id=updated.id,
            action=history_action,
            version=updated.version,
            note=note,
            before_snapshot=scenario_lab.model_dump(mode="json"),
            after_snapshot=updated.model_dump(mode="json"),
        )
        structured._scenario_lab_history.append(history_entry)
        structured.update_workspace(latest_training_submode="practice")
        if action == "complete":
            self.record_learning_outcome(
                workspace_id=workspace_id,
                concepts=updated.dependency_keys or [updated.focus_area],
                outcome="tests_passed",
                summary=note or "Scenario lab completed.",
                focus_area=updated.focus_area,
                scenario="scenario_lab",
                verified_result=review_outcome or updated.success_signal,
                verified_by_evaluator=True,
            )
            artifact = ReviewArtifactSnapshot(
                id=f"review-{uuid4().hex[:10]}",
                title=f"Review artifact: {updated.focus_area}",
                focus_area=updated.focus_area,
                source="scenario_lab",
                status="resolved",
                summary=note or updated.summary,
                root_cause=updated.summary,
                guardrail="Keep the same minimum boundary when migrating back.",
                next_self_implementation_rule="Migrate the same proven slice back into the project without widening scope.",
                recommended_recovery_mode="review",
                recommended_actions=["Move the same proven slice back into the project."],
                verified_result=review_outcome or updated.success_signal,
                last_action="resolved",
                version=1,
                metadata={"verification_source": verification_source.strip()},
            )
            structured._review_artifact = artifact
            structured._review_artifact_history.append(
                ReviewArtifactHistoryEntry(
                    entry_id=f"hist-{uuid4().hex[:10]}",
                    review_artifact_id=artifact.id,
                    action="resolved",
                    version=artifact.version,
                    note="Created from completed scenario lab.",
                    before_snapshot={},
                    after_snapshot=artifact.model_dump(mode="json"),
                )
            )
        self._persist_structured(workspace_id)
        return updated, list(reversed([item for item in structured._scenario_lab_history if item.scenario_lab_id == updated.id]))
