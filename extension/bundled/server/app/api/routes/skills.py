"""P3 深化 — Skill ecosystem runtime API.

Cross-workspace skill lifecycle over HTTP: register (inline) / import
(SKILL.md, supply-chain scanned) → review (human gate) → activate →
deactivate, with progressive body loading only at activation. The registry
persists under ``data_root/skills`` so skills survive sidecar restarts and
are shared across every workspace of this sidecar.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from ...skills.registry import SkillRegistry
from ..runtime import TrainerRuntime


def build_skills_router(runtime: TrainerRuntime) -> APIRouter:
    router = APIRouter(tags=["skills"])

    def _registry() -> SkillRegistry:
        if runtime.skill_registry is None:
            data_root = getattr(runtime.resource_service, "data_root", None)
            if data_root is None:
                raise HTTPException(
                    status_code=503,
                    detail="Sidecar data root is unavailable; skills cannot be persisted.",
                )
            runtime.skill_registry = SkillRegistry(Path(str(data_root)) / "skills")
        return runtime.skill_registry

    @router.get("/skill/list")
    def skill_list(
        kind: str | None = None,
        active_only: bool = False,
        include_body: bool = False,
    ) -> dict[str, Any]:
        skills = [
            skill
            for skill in _registry().to_payload(include_body=include_body)
            if (kind is None or skill.get("kind") == kind)
            and (not active_only or skill.get("active"))
        ]
        return {
            "ok": True,
            "total": len(skills),
            "skills": skills,
        }

    @router.post("/skill/register")
    def skill_register(payload: dict) -> dict[str, Any]:
        name = str(payload.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="name is required.")
        kind = str(payload.get("kind") or "knowledge").strip()
        skill_id = str(payload.get("skill_id") or "").strip() or name
        try:
            record = _registry().register(
                skill_id=skill_id,
                kind=kind,
                name=name,
                description=str(payload.get("description") or "").strip(),
                permissions=[str(p).strip() for p in payload.get("permissions") or [] if str(p).strip()],
                reviewed=bool(payload.get("reviewed", False)),
                metadata={"origin": "inline"},
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"ok": True, "skill": record.to_payload()}

    @router.post("/skill/import")
    def skill_import(payload: dict) -> dict[str, Any]:
        """External SKILL.md import — supply-chain scanned, review-gated."""

        path_text = str(payload.get("path") or "").strip()
        if not path_text:
            raise HTTPException(status_code=400, detail="path to SKILL.md is required.")
        skill_md = Path(path_text).expanduser()
        if not skill_md.is_file():
            raise HTTPException(status_code=422, detail=f"SKILL.md not found: {skill_md}")
        kind = str(payload.get("kind") or "knowledge").strip()
        try:
            record = _registry().register_from_skill_md(
                skill_md,
                kind=kind,
                reviewed=bool(payload.get("reviewed", False)),
            )
        except OSError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "ok": True,
            "skill": record.to_payload(),
            "security_flags": list(record.metadata.get("security_flags") or []),
            "review_required": not record.reviewed,
        }

    @router.post("/skill/activate")
    def skill_activate(payload: dict) -> dict[str, Any]:
        skill_id = str(payload.get("skill_id") or "").strip()
        if not skill_id:
            raise HTTPException(status_code=400, detail="skill_id is required.")
        try:
            record = _registry().activate(skill_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            # Review gate: action skills need explicit human approval first.
            raise HTTPException(
                status_code=403,
                detail={"code": "skill_not_reviewed", "message": str(exc)},
            ) from exc
        return {"ok": True, "skill": record.to_payload(include_body=True)}

    @router.post("/skill/deactivate")
    def skill_deactivate(payload: dict) -> dict[str, Any]:
        skill_id = str(payload.get("skill_id") or "").strip()
        if not skill_id:
            raise HTTPException(status_code=400, detail="skill_id is required.")
        try:
            record = _registry().deactivate(skill_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"ok": True, "skill": record.to_payload()}

    @router.post("/skill/review")
    def skill_review(payload: dict) -> dict[str, Any]:
        """审核 flow: record the human decision for one skill."""

        skill_id = str(payload.get("skill_id") or "").strip()
        if not skill_id:
            raise HTTPException(status_code=400, detail="skill_id is required.")
        reviewed = bool(payload.get("approved", payload.get("reviewed", True)))
        note = str(payload.get("note") or "").strip()
        try:
            record = _registry().mark_reviewed(skill_id, reviewed=reviewed)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if note:
            record.metadata["review_note"] = note
        return {"ok": True, "skill": record.to_payload()}

    @router.get("/skill/status")
    def skill_status() -> dict[str, Any]:
        registry = _registry()
        skills = registry.to_payload()
        return {
            "ok": True,
            "total": len(skills),
            "active": sum(1 for s in skills if s.get("active")),
            "unreviewed": sum(1 for s in skills if not s.get("reviewed")),
            "by_kind": {
                kind: sum(1 for s in skills if s.get("kind") == kind)
                for kind in ("tutor", "knowledge", "action")
            },
        }

    return router
