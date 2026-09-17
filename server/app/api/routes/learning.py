from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ...core.models import TeachingKnowledgeAsset
from ..runtime import TrainerRuntime
from ._deps import RouterDeps


def build_learning_router(runtime: TrainerRuntime, deps: RouterDeps) -> APIRouter:
    router = APIRouter(tags=["learning"])

    current_workspace_id = deps.current_workspace_id
    current_snapshot = deps.current_snapshot
    provider_config_from_payload = deps.provider_config_from_payload
    provider_api_key_from_payload = deps.provider_api_key_from_payload

    def _stage_material_payload(asset: TeachingKnowledgeAsset) -> dict[str, object]:
        content = asset.concept_card or asset.example or asset.exercise_seed or asset.summary
        return {
            "id": asset.id,
            "planStageId": asset.plan_stage_id,
            "kind": asset.kind,
            "title": asset.title,
            "summary": asset.summary,
            "content": content,
            "focusArea": asset.focus_area,
            "createdAt": asset.created_at or "",
        }

    def _stage_materials_for_stage(workspace: str, stage: str) -> list[TeachingKnowledgeAsset]:
        assets = runtime.memory_service.list_teaching_assets(workspace, scope=None, limit=200)
        return [asset for asset in assets if asset.plan_stage_id == stage]

    @router.get("/plan/{plan_id}/stages/{stage_id}/materials")
    def list_stage_materials(
        plan_id: str,
        stage_id: str,
        session_id: str | None = None,
        workspace_id: str | None = None,
    ) -> dict[str, object]:
        resolved_workspace_id = current_workspace_id(session_id=session_id, workspace_id=workspace_id)
        materials = _stage_materials_for_stage(resolved_workspace_id, stage_id)
        return {
            "plan_id": plan_id,
            "stage_id": stage_id,
            "materials": [_stage_material_payload(asset) for asset in materials],
        }

    @router.post("/plan/{plan_id}/stages/{stage_id}/material/generate")
    async def generate_stage_materials(
        plan_id: str,
        stage_id: str,
        payload: dict | None = None,
    ) -> dict[str, object]:
        payload = payload or {}
        resolved_workspace_id = current_workspace_id(session_id=payload.get("session_id"), workspace_id=payload.get("workspace_id"))
        plan = runtime.repository.get_latest_plan(resolved_workspace_id)
        if plan is None:
            raise HTTPException(status_code=404, detail="No learning plan is available for this workspace.")
        if plan_id not in {getattr(plan, "id", ""), getattr(plan, "plan_id", "")}:
            raise HTTPException(status_code=404, detail="Plan not found for this workspace.")
        stage = next((item for item in (plan.stages or []) if item.id == stage_id), None)
        if stage is None:
            raise HTTPException(status_code=404, detail="Plan stage not found.")
        stage_exercises = list(getattr(stage, "exercises", None) or [])
        if not stage_exercises:
            stage_exercises = [
                exercise
                for phase in (plan.phases or [])
                for exercise in (phase.exercises or [])
            ][:6]
        provider_config = provider_config_from_payload(payload)
        api_key = provider_api_key_from_payload(payload)
        provider_service = runtime.provider_service_for(provider_config, api_key)
        profile = runtime.repository.get_profile(resolved_workspace_id)
        profile_summary = "; ".join(
            item
            for item in (
                getattr(profile, "long_term_goal", "") if profile else "",
                getattr(profile, "background", "") if profile else "",
            )
            if str(item or "").strip()
        )
        hints = [
            asset.title
            for asset in runtime.memory_service.list_teaching_assets(
                resolved_workspace_id, scope=None, limit=12
            )
            if asset.title
        ]
        from ..pedagogy.stage_material_composer import StageMaterialComposer

        composer = StageMaterialComposer(provider_service=provider_service)
        response_language = str(
            payload.get("response_language") or payload.get("responseLanguage") or "zh-CN"
        )
        materials = await composer.compose_stage_materials(
            workspace_id=resolved_workspace_id,
            plan_title=plan.title,
            stage_id=stage_id,
            stage_title=stage.title,
            stage_goal=stage.goal,
            stage_outcomes=list(stage.outcomes or []),
            stage_exercises=stage_exercises,
            focus_area=str(payload.get("focus_area") or payload.get("focusArea") or ""),
            profile_summary=profile_summary,
            teaching_asset_hints=hints,
            response_language=response_language,
        )
        persisted: list[TeachingKnowledgeAsset] = []
        for asset in materials:
            persisted.append(
                runtime.memory_service.record_teaching_asset(resolved_workspace_id, asset)
            )
        return {
            "plan_id": plan_id,
            "stage_id": stage_id,
            "materials": [_stage_material_payload(asset) for asset in persisted],
            "snapshot": current_snapshot(session_id=payload.get("session_id"), workspace_id=resolved_workspace_id),
        }

    @router.post("/pedagogy/explain")
    def explain_principle(payload: dict) -> dict[str, object]:
        principle = str(payload.get("principle") or "").strip()
        if not principle:
            raise HTTPException(status_code=422, detail="principle is required.")
        resolved_workspace_id = current_workspace_id(session_id=payload.get("session_id"), workspace_id=payload.get("workspace_id"))
        from ..pedagogy.stage_material_composer import compose_principle_explainer_asset

        asset = compose_principle_explainer_asset(
            workspace_id=resolved_workspace_id,
            principle=principle,
            context=str(payload.get("context") or ""),
            focus_area=str(payload.get("focus_area") or payload.get("focusArea") or ""),
            response_language=str(payload.get("response_language") or payload.get("responseLanguage") or "zh-CN"),
        )
        saved = runtime.memory_service.record_teaching_asset(resolved_workspace_id, asset)
        return {"ok": True, "asset": _stage_material_payload(saved)}

    @router.post("/training/handoff/rebind")
    def rebind_training_handoff(payload: dict) -> dict[str, object]:
        card_id = str(payload.get("card_id") or payload.get("cardId") or "").strip()
        if not card_id:
            raise HTTPException(status_code=422, detail="card_id is required.")
        resolved_workspace_id = current_workspace_id(session_id=payload.get("session_id"), workspace_id=payload.get("workspace_id"))
        try:
            result = runtime.memory_service.rebind_training_handoff(resolved_workspace_id, card_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"ok": True, **result}

    _HOST_TRUSTED_VERIFICATION_SOURCES = frozenset(
        {"automated_test", "evaluator", "ide_current_file", "server_evaluator", "test_runner", "verification_service"}
    )

    @router.post("/training/verification/attest")
    def attest_training_verification(payload: dict) -> dict[str, object]:
        """Host test-controller attestation of a real dynamic verification run.

        The local host (VS Code test runner / task pipeline) is the designated
        verifier: it executes the learner's tests in the real workspace and
        posts the outcome here. Learner-supplied success flags stay untrusted —
        only this host channel may attest with a trusted evidence source.
        """
        card_id = str(payload.get("card_id") or payload.get("cardId") or "").strip()
        if not card_id:
            raise HTTPException(status_code=422, detail="card_id is required.")
        evidence_source = str(payload.get("evidence_source") or payload.get("evidenceSource") or "").strip()
        if evidence_source not in _HOST_TRUSTED_VERIFICATION_SOURCES:
            raise HTTPException(
                status_code=422,
                detail=f"evidence_source must be one of: {', '.join(sorted(_HOST_TRUSTED_VERIFICATION_SOURCES))}.",
            )
        tests_output = str(payload.get("tests_output") or payload.get("testsOutput") or "").strip()
        passed = bool(payload.get("passed"))
        resolved_workspace_id = current_workspace_id(session_id=payload.get("session_id"), workspace_id=payload.get("workspace_id"))
        updated = runtime.memory_service.record_training_practice_evaluation_result(
            workspace_id=resolved_workspace_id,
            card_id=card_id,
            card_title=str(payload.get("card_title") or payload.get("cardTitle") or ""),
            passed=passed,
            summary=str(payload.get("summary") or tests_output or "Host test runner attestation."),
            next_step=str(payload.get("next_step") or payload.get("nextStep") or "Record a reflection, then return the card."),
            focus_area=str(payload.get("focus_area") or payload.get("focusArea") or ""),
            evidence_source=evidence_source,
            verified_by_evaluator=passed,
        )
        return {"ok": True, "workspace": updated}
    return router
