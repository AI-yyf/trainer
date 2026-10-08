from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from ...core.models import TeachingKnowledgeAsset
from ...pedagogy.stage_material_state import stage_material_payload, stage_material_state
from ...workspace.remote_identity import validate_remote_verification_artifact
from ..runtime import TrainerRuntime
from ._deps import RouterDeps


def build_learning_router(runtime: TrainerRuntime, deps: RouterDeps) -> APIRouter:
    router = APIRouter(tags=["learning"])

    current_workspace_id = deps.current_workspace_id
    current_snapshot = deps.current_snapshot
    provider_config_from_payload = deps.provider_config_from_payload
    provider_api_key_from_payload = deps.provider_api_key_from_payload

    def _stage_material_payload(asset: TeachingKnowledgeAsset) -> dict[str, object]:
        return stage_material_payload(asset).model_dump(by_alias=True)

    def _resolve_stage(workspace: str, plan_id: str, stage_id: str):
        plan = runtime.repository.get_latest_plan(workspace)
        if plan is None or plan_id not in {plan.id, plan.plan_id}:
            raise HTTPException(status_code=404, detail="Plan not found for this workspace.")
        stage = next((item for item in plan.stages if item.id == stage_id), None)
        if stage is None:
            raise HTTPException(status_code=404, detail="Plan stage not found.")
        return plan, stage

    @router.get("/plan/{plan_id}/stages/{stage_id}/materials")
    def list_stage_materials(
        plan_id: str,
        stage_id: str,
        session_id: str | None = None,
        workspace_id: str | None = None,
    ) -> dict[str, object]:
        resolved_workspace_id = current_workspace_id(session_id=session_id, workspace_id=workspace_id)
        plan, _ = _resolve_stage(resolved_workspace_id, plan_id, stage_id)
        materials = stage_material_state(plan, runtime.memory_service.list_teaching_assets(
            resolved_workspace_id, scope=None, limit=10000,
        )).get(stage_id, [])
        return {
            "plan_id": plan_id,
            "stage_id": stage_id,
            "materials": [item.model_dump(by_alias=True) for item in materials],
        }

    @router.post("/plan/{plan_id}/stages/{stage_id}/material/generate")
    async def generate_stage_materials(
        plan_id: str,
        stage_id: str,
        payload: dict | None = None,
    ) -> dict[str, object]:
        payload = payload or {}
        resolved_workspace_id = current_workspace_id(session_id=payload.get("session_id"), workspace_id=payload.get("workspace_id"))
        plan, stage = _resolve_stage(resolved_workspace_id, plan_id, stage_id)
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
        from ...pedagogy.stage_material_composer import StageMaterialComposer

        composer = StageMaterialComposer(provider_service=provider_service)
        response_language = str(
            payload.get("response_language") or payload.get("responseLanguage") or "zh-CN"
        )
        try:
            materials = await asyncio.wait_for(composer.compose_stage_materials(
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
            ), timeout=90)
        except TimeoutError as exc:
            raise HTTPException(status_code=504, detail="Stage material generation timed out. Retry.") from exc
        # A plan can change while the model is running. Never persist against its replacement.
        _resolve_stage(resolved_workspace_id, plan_id, stage_id)
        batch = f"stage-batch:{datetime.now(UTC).isoformat()}:{uuid4().hex}"
        persisted: list[TeachingKnowledgeAsset] = []
        for asset in materials:
            asset = asset.model_copy(update={"tags": [*asset.tags, f"plan:{plan_id}", batch]})
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
        from ...pedagogy.stage_material_composer import compose_principle_explainer_asset

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
        # A stable per-run key lets an authorized resend replay through the
        # training-reliability ledger instead of double-recording.
        idempotency_key = str(payload.get("idempotency_key") or payload.get("idempotencyKey") or "").strip()
        resolved_workspace_id = current_workspace_id(session_id=payload.get("session_id"), workspace_id=payload.get("workspace_id"))
        verification_artifact = payload.get("verification_artifact")
        provisioning = runtime.get_project_provisioning(resolved_workspace_id)
        project_path = provisioning.project_path if provisioning is not None else runtime.resolve_workspace_path(resolved_workspace_id) or ""
        workspace = runtime.memory_service.snapshot(resolved_workspace_id).workspace
        remote = project_path.startswith("vscode-remote://") or bool(workspace.get("remote_name"))
        if remote or verification_artifact is not None:
            try:
                if provisioning is None:
                    raise ValueError("Remote evidence requires a provisioned project context.")
                verification_artifact = validate_remote_verification_artifact(verification_artifact, provisioning.project_path)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
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
            idempotency_key=idempotency_key,
            verification_artifact=verification_artifact,
        )
        return {"ok": True, "workspace": updated}
    return router
