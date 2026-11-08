"""Goal session routes: server-owned truth behind GoalBar."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ...core.models import GoalControlRequest
from ..runtime import TrainerRuntime
from ._deps import RouterDeps


def build_goal_router(runtime: TrainerRuntime, deps: RouterDeps) -> APIRouter:
    router = APIRouter(tags=["goal"])

    @router.get("/goal/current")
    def current_goal(
        session_id: str | None = None,
        workspace_id: str | None = None,
    ) -> dict[str, object]:
        resolved_workspace_id = deps.current_workspace_id(
            session_id=session_id,
            workspace_id=workspace_id,
        )
        goal = runtime.goals().current(resolved_workspace_id)
        return {"goal": goal.model_dump(by_alias=True) if goal is not None else None}

    @router.get("/goal/list")
    def list_goals(
        session_id: str | None = None,
        workspace_id: str | None = None,
    ) -> dict[str, object]:
        resolved_workspace_id = deps.current_workspace_id(
            session_id=session_id,
            workspace_id=workspace_id,
        )
        goals = runtime.goals().list(resolved_workspace_id)
        return {"goals": [goal.model_dump(by_alias=True) for goal in goals]}

    @router.post("/goal/action")
    def goal_action(request: GoalControlRequest) -> dict[str, object]:
        resolved_workspace_id = deps.trusted_write_workspace_id(
            session_id=request.session_id,
            workspace_id=request.workspace_id,
        )
        state = runtime.ensure_session(
            request.session_id,
            workspace_id=resolved_workspace_id,
        )
        service = runtime.goals()
        goal = None
        if request.action == "start":
            try:
                goal = service.start(
                    workspace_id=resolved_workspace_id,
                    title=str(request.title or ""),
                    session_id=state.session_id,
                    source="user_explicit",
                    plan=state.snapshot.plan,
                )
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        elif request.action == "pause":
            goal = service.pause(resolved_workspace_id, request.goal_id)
        elif request.action == "resume":
            goal = service.resume(resolved_workspace_id, request.goal_id)
        else:
            goal = service.complete(resolved_workspace_id, request.goal_id)
        if goal is None and request.action == "start":
            raise HTTPException(status_code=404, detail="No goal is available for this action.")
        runtime.publish_goal(resolved_workspace_id)
        return {
            "ok": True,
            "goal": goal.model_dump(by_alias=True) if goal is not None else None,
        }

    return router
