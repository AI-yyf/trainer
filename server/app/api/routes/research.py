from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from ...llm.provider_service import ProviderService, redact_provider_error
from ...research.models import AgentRole, ArtifactKind, ScheduleCadence, ThreadDepth
from ...research.service import ResearchOrchestratorService


def build_research_router(
    service: ResearchOrchestratorService, provider_service: ProviderService | None = None
) -> APIRouter:
    router = APIRouter(prefix="/research", tags=["research"])

    @router.post("/create")
    def create_project(payload: dict[str, Any]) -> dict[str, Any]:
        title = payload.get("title", "Untitled Research Project")
        description = payload.get("description", "")
        project = service.create_project(title=title, description=description)
        return {"project": project.to_dict(), "message": f"Research project '{title}' created successfully."}

    @router.get("/projects")
    def list_projects() -> list[dict[str, Any]]:
        return [p.to_dict() for p in service.list_projects()]

    @router.get("/{project_id}")
    def get_project(project_id: str) -> dict[str, Any]:
        state = service.get_state(project_id)
        if not state:
            raise HTTPException(status_code=404, detail="Project not found")
        return state

    @router.delete("/{project_id}")
    def delete_project(project_id: str) -> dict[str, Any]:
        deleted = service.delete_project(project_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Project not found")
        return {"deleted": True, "project_id": project_id}

    @router.post("/{project_id}/theme")
    def add_theme(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        title = payload.get("title", "Untitled Theme")
        description = payload.get("description", "")
        duration_weeks = payload.get("duration_weeks", 4)
        cadence_str = payload.get("cadence", "weekly").upper()
        try:
            cadence = ScheduleCadence[cadence_str]
        except KeyError:
            cadence = ScheduleCadence.WEEKLY
        start_date_str = payload.get("start_date")
        start_date = datetime.fromisoformat(start_date_str) if start_date_str else None

        theme = service.add_theme(
            project_id,
            title=title,
            description=description,
            duration_weeks=duration_weeks,
            cadence=cadence,
            start_date=start_date,
        )
        if not theme:
            raise HTTPException(status_code=404, detail="Project not found")
        return {"theme": theme.to_dict(), "project_id": project_id}

    @router.post("/{project_id}/theme/{theme_id}/activate")
    def activate_theme(project_id: str, theme_id: str) -> dict[str, Any]:
        theme = service.activate_theme(project_id, theme_id)
        if not theme:
            raise HTTPException(status_code=404, detail="Project or theme not found, or theme already active")
        return {"theme": theme.to_dict(), "message": f"Theme '{theme.title}' is now active."}

    @router.post("/{project_id}/theme/{theme_id}/pause")
    def pause_theme(project_id: str, theme_id: str) -> dict[str, Any]:
        theme = service.pause_theme(project_id, theme_id)
        if not theme:
            raise HTTPException(status_code=404, detail="Project or active theme not found")
        return {"theme": theme.to_dict(), "message": f"Theme '{theme.title}' has been paused."}

    @router.post("/{project_id}/theme/{theme_id}/thread")
    def add_thread(project_id: str, theme_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        angle = payload.get("angle", "General exploration")
        depth_str = payload.get("depth", "medium").upper()
        try:
            depth = ThreadDepth[depth_str]
        except KeyError:
            depth = ThreadDepth.MEDIUM

        thread = service.add_thread(project_id, theme_id, angle=angle, depth=depth)
        if not thread:
            raise HTTPException(status_code=404, detail="Project or theme not found")
        return {
            "thread": {
                "id": thread.id,
                "angle": thread.angle,
                "depth": thread.depth,
                "status": thread.status,
            },
            "theme_id": theme_id,
        }

    @router.post("/{project_id}/theme/{theme_id}/thread/{thread_id}/finding")
    def add_finding(project_id: str, theme_id: str, thread_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        content = payload.get("content", "")
        source = payload.get("source", "unknown")
        confidence = payload.get("confidence", 0.5)
        tags = payload.get("tags", [])

        if not content:
            raise HTTPException(status_code=400, detail="Finding content is required")

        finding = service.add_finding(
            project_id, theme_id, thread_id, content=content, source=source, confidence=confidence, tags=tags
        )
        if not finding:
            raise HTTPException(status_code=404, detail="Project, theme, or thread not found")
        return {
            "finding": {
                "id": finding.id,
                "content": finding.content,
                "source": finding.source,
                "confidence": finding.confidence,
                "tags": finding.tags,
                "created_at": finding.created_at.isoformat(),
            },
            "thread_id": thread_id,
        }

    @router.post("/{project_id}/theme/{theme_id}/artifact")
    def add_artifact(project_id: str, theme_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        title = payload.get("title", "Untitled Artifact")
        kind_str = payload.get("kind", "note").upper()
        content = payload.get("content", "")

        try:
            kind = ArtifactKind[kind_str]
        except KeyError:
            kind = ArtifactKind.NOTE

        artifact = service.add_artifact(project_id, theme_id, title=title, kind=kind, content=content)
        if not artifact:
            raise HTTPException(status_code=404, detail="Project or theme not found")
        return {
            "artifact": {
                "id": artifact.id,
                "title": artifact.title,
                "kind": artifact.kind,
                "version": artifact.version,
            },
            "theme_id": theme_id,
        }

    @router.post("/{project_id}/theme/{theme_id}/checkpoint")
    def add_checkpoint(project_id: str, theme_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        label = payload.get("label", "Checkpoint")
        due_date_str = payload.get("due_date")
        if not due_date_str:
            raise HTTPException(status_code=400, detail="due_date is required")

        due_date = datetime.fromisoformat(due_date_str)
        cp = service.add_checkpoint(project_id, theme_id, label=label, due_date=due_date)
        if not cp:
            raise HTTPException(status_code=404, detail="Project or theme not found")
        return {
            "checkpoint": {
                "id": cp.id,
                "label": cp.label,
                "due_date": cp.due_date.isoformat(),
            },
            "theme_id": theme_id,
        }

    @router.post("/{project_id}/advance")
    def advance_research(project_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        theme_id = payload.get("theme_id") if payload else None
        result = service.advance_research(project_id, theme_id=theme_id)
        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])
        return result

    @router.post("/{project_id}/message")
    def send_message(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        message = payload.get("message", "")
        if not message:
            raise HTTPException(status_code=400, detail="Message is required")
        result = service.human_message(project_id, message)
        if not result:
            raise HTTPException(status_code=404, detail="Project not found")
        return result

    @router.post("/{project_id}/message/stream")
    async def send_message_stream(project_id: str, payload: dict[str, Any]):
        """Streaming research agent response via SSE."""

        async def generate():
            token_count = 0
            try:
                message = payload.get("message", "")
                if not message:
                    yield f"event: error\ndata: {json.dumps({'error': 'Message is required'})}\n\n"
                    return

                project = service.get_project(project_id)
                if not project:
                    yield f"event: error\ndata: {json.dumps({'error': 'Project not found'})}\n\n"
                    return

                # Record human message
                project.gate.add_message("human", message)

                # Handle commands
                if "/advance" in message.lower():
                    result = service.advance_research(project_id)
                    response_text = json.dumps(result, indent=2)
                elif "/status" in message.lower():
                    result = service.get_state(project_id)
                    response_text = json.dumps(result, indent=2)
                elif provider_service and provider_service.has_api_key:
                    # Use LLM for streaming response
                    response_text = await _generate_streaming_agent_response(
                        project, message, provider_service
                    )
                else:
                    # Fallback to non-streaming response
                    response_text = service._generate_agent_response(project, message)

                project.gate.add_message("agent", response_text)

                # Stream bounded chunks so long responses do not create one SSE
                # event and one webview message per character.
                for offset in range(0, len(response_text), 512):
                    chunk = response_text[offset : offset + 512]
                    token_count += len(chunk)
                    yield f"data: {json.dumps({'chunk': chunk})}\n\n"

                yield f"event: complete\ndata: {json.dumps({'tokens': token_count})}\n\n"

            except Exception as exc:
                safe_error = redact_provider_error(exc, fallback="Research provider request failed")
                yield f"event: error\ndata: {json.dumps({'error': safe_error})}\n\n"

        return StreamingResponse(generate(), media_type="text/event-stream")

    @router.get("/{project_id}/approvals")
    def get_pending_approvals(project_id: str) -> list[dict[str, Any]]:
        return service.get_pending_approvals(project_id)

    @router.post("/{project_id}/approve/{approval_id}")
    def resolve_approval(project_id: str, approval_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        approved = payload.get("approved", True)
        result = service.resolve_approval(project_id, approval_id, approved)
        if not result:
            raise HTTPException(status_code=404, detail="Project or approval not found")
        return result

    @router.get("/{project_id}/schedule")
    def get_schedule_status(project_id: str) -> dict[str, Any]:
        state = service.get_state(project_id)
        if not state:
            raise HTTPException(status_code=404, detail="Project not found")
        return state.get("schedule_status", {})

    return router


async def _generate_streaming_agent_response(
    project: Any, human_message: str, provider_service: ProviderService
) -> str:
    """Generate a streaming agent response using the LLM."""
    role = project.agent_state.current_role
    active_themes = project.active_themes()

    if not active_themes:
        return (
            "I notice there are no active research themes yet. "
            "Would you like me to help you create and activate a research theme? "
            "Use /status to see current state, or describe what you'd like to research."
        )

    theme_names = ", ".join(t.title for t in active_themes)
    role_context = _build_role_context(role, project, theme_names, human_message)

    messages = [
        {
            "role": "system",
            "content": f"You are a research agent in the {role.upper()} role. "
            f"Respond concisely and helpfully to the human's message. "
            f"Context: {role_context}",
        },
        {"role": "user", "content": human_message},
    ]

    full_response = ""
    async for chunk in provider_service.chat_completion_stream(messages):
        full_response += chunk

    return f"[{role.upper()}] {full_response}"


def _build_role_context(role: Any, project: Any, theme_names: str, human_message: str) -> str:
    """Build context string for the current agent role."""
    if role == AgentRole.RESEARCHER:
        return (
            f"Currently researching: {theme_names}. "
            f"Information gathering phase. "
            f"{len(project.agent_state.pending_questions)} pending questions, "
            f"{len(project.agent_state.thinking_log)} thinking entries logged."
        )
    if role == AgentRole.EDITOR:
        return (
            f"Organizing research for: {theme_names}. "
            f"Structuring findings into coherent narratives. "
            f"Current iteration: {project.agent_state.current_iteration}."
        )
    if role == AgentRole.CRITIC:
        return (
            f"Reviewing research for: {theme_names}. "
            f"Looking for gaps, inconsistencies, and weak arguments. "
            f"Review round: {project.agent_state.self_review_count}/{project.agent_state.max_review_rounds}."
        )
    if role == AgentRole.SYNTHESIZER:
        return (
            f"Final synthesis for: {theme_names}. "
            f"Preparing final artifacts and conclusions. "
            f"This is the last phase before completion."
        )
    return f"Processing input for: {theme_names}"
