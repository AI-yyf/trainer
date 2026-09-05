from __future__ import annotations

import re
from datetime import datetime
from hashlib import sha1
from typing import TYPE_CHECKING, Any

from ..network_fetch import ControlledFetchError
from .models import (
    AgentRole,
    Artifact,
    ArtifactKind,
    Checkpoint,
    Finding,
    ResearchProject,
    ResearchTheme,
    ResearchThread,
    ScheduleCadence,
    ThemeStatus,
    ThreadDepth,
)
from .scheduler import ResearchScheduler
from .web_search import SearchResultEnricher, WebSearchClient

if TYPE_CHECKING:
    from ..db.research_repository import ResearchRepository


_REFERENCE_STOPWORDS = {
    "a",
    "an",
    "and",
    "be",
    "before",
    "for",
    "from",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "one",
    "the",
    "to",
    "use",
    "with",
}


class ResearchOrchestratorService:
    def __init__(
        self,
        repository: ResearchRepository | None = None,
        web_search: WebSearchClient | None = None,
        *,
        network_enabled: bool = False,
    ) -> None:
        self._projects: dict[str, ResearchProject] = {}
        self._repository = repository
        self._web_search = web_search or WebSearchClient(network_enabled=network_enabled)
        self._search_enricher = SearchResultEnricher(self._web_search)

    def _persist_project(self, project: ResearchProject) -> None:
        """Persist project and all nested entities to repository if available."""
        if not self._repository:
            return
        self._repository.save_project(project)
        self._repository.save_agent_state(project.id, project.agent_state)
        for theme in project.themes:
            self._repository.save_theme(project.id, theme)
            for thread in theme.threads:
                self._repository.save_thread(project.id, theme.id, thread)
                for finding in thread.findings:
                    self._repository.save_finding(project.id, theme.id, thread.id, finding)
            for artifact in theme.artifacts:
                self._repository.save_artifact(project.id, theme.id, artifact)
            if theme.schedule:
                for cp in theme.schedule.checkpoints:
                    self._repository.save_checkpoint(project.id, theme.id, cp)
        for msg in project.gate.messages:
            self._repository.save_gate_message(project.id, msg)
        for approval in project.gate.approvals:
            self._repository.save_approval(project.id, approval)

    def create_project(self, *, title: str, description: str) -> ResearchProject:
        project = ResearchProject.create(title=title, description=description)
        self._projects[project.id] = project
        self._persist_project(project)
        return project

    def get_project(self, project_id: str) -> ResearchProject | None:
        # Try memory first, then repository if available
        if project_id in self._projects:
            return self._projects[project_id]
        if self._repository:
            project = self._repository.get_project(project_id)
            if project:
                self._projects[project.id] = project
                return project
        return None

    def list_projects(self) -> list[ResearchProject]:
        # If repository is available, load from there; otherwise use memory
        if self._repository:
            projects = self._repository.list_projects()
            for p in projects:
                if p.id not in self._projects:
                    self._projects[p.id] = p
            return projects
        return list(self._projects.values())

    def delete_project(self, project_id: str) -> bool:
        if project_id in self._projects:
            del self._projects[project_id]
            if self._repository:
                self._repository.delete_project(project_id)
            return True
        if self._repository:
            return self._repository.delete_project(project_id)
        return False

    def add_theme(
        self,
        project_id: str,
        *,
        title: str,
        description: str,
        duration_weeks: int = 4,
        cadence: ScheduleCadence = ScheduleCadence.WEEKLY,
        start_date: datetime | None = None,
    ) -> ResearchTheme | None:
        project = self.get_project(project_id)
        if not project:
            return None
        theme = project.add_theme(title=title, description=description, duration_weeks=duration_weeks, cadence=cadence, start_date=start_date)
        self._persist_project(project)
        return theme

    def activate_theme(self, project_id: str, theme_id: str) -> ResearchTheme | None:
        project = self.get_project(project_id)
        if not project:
            return None
        theme = project.activate_theme(theme_id)
        if theme:
            self._persist_project(project)
        return theme

    def pause_theme(self, project_id: str, theme_id: str) -> ResearchTheme | None:
        project = self.get_project(project_id)
        if not project:
            return None
        for theme in project.themes:
            if theme.id == theme_id and theme.status == ThemeStatus.ACTIVE:
                theme.pause()
                project.gate.add_notification(f"Theme '{theme.title}' has been paused.")
                self._persist_project(project)
                return theme
        return None

    def add_thread(
        self, project_id: str, theme_id: str, *, angle: str, depth: ThreadDepth = ThreadDepth.MEDIUM
    ) -> ResearchThread | None:
        project = self.get_project(project_id)
        if not project:
            return None
        for theme in project.themes:
            if theme.id == theme_id:
                thread = theme.add_thread(angle=angle, depth=depth)
                project.gate.add_message(
                    "agent",
                    f"Added research thread '{angle}' (depth: {depth}) to theme '{theme.title}'. "
                    f"I'll explore this angle systematically.",
                )
                self._persist_project(project)
                return thread
        return None

    def add_finding(
        self,
        project_id: str,
        theme_id: str,
        thread_id: str,
        *,
        content: str,
        source: str,
        confidence: float = 0.5,
        tags: list[str] | None = None,
    ) -> Finding | None:
        project = self.get_project(project_id)
        if not project:
            return None
        for theme in project.themes:
            if theme.id == theme_id:
                finding = theme.add_finding(thread_id, content, source, confidence, tags)
                if finding:
                    project.agent_state.add_thinking(
                        role=project.agent_state.current_role,
                        question="What does this finding tell us?",
                        reasoning=f"Finding: {content[:200]}",
                        conclusion=f"Confidence: {confidence}. Source: {source}.",
                    )
                    self._persist_project(project)
                return finding
        return None

    def ensure_background_project(
        self,
        *,
        workspace_id: str,
        title: str | None = None,
        description: str | None = None,
    ) -> ResearchProject:
        project_key = f"workspace:{workspace_id.strip() or 'default'}"
        project = self.get_project(project_key)
        if project is not None:
            return project

        project = ResearchProject(
            id=project_key,
            title=title or "Background Coach Research",
            description=description
            or "Background external learning that supports the active coaching thread.",
        )
        project.gate.add_message(
            "system",
            "Background coach research is active. External references will be recorded here when needed.",
        )
        self._projects[project.id] = project
        self._persist_project(project)
        return project

    def ensure_background_theme(
        self,
        *,
        workspace_id: str,
        focus_area: str,
        description: str = "",
    ) -> tuple[ResearchProject, ResearchTheme]:
        project = self.ensure_background_project(workspace_id=workspace_id)
        cleaned_focus = focus_area.strip() or "Current training focus"
        for theme in project.themes:
            if theme.title.strip().lower() == cleaned_focus.lower():
                if theme.status == ThemeStatus.PLANNING:
                    theme.activate()
                    self._persist_project(project)
                return project, theme

        theme = project.add_theme(
            title=cleaned_focus,
            description=description or f"External references for {cleaned_focus}.",
            duration_weeks=1,
            cadence=ScheduleCadence.WEEKLY,
        )
        theme.activate()
        self._persist_project(project)
        return project, theme

    def record_background_reference(
        self,
        *,
        workspace_id: str,
        focus_area: str,
        source: str,
        content: str,
        trust_score: float,
        tags: list[str] | None = None,
        duplicate_key: str | None = None,
        evidence_summary: str | None = None,
        created_at: datetime | None = None,
        source_type: str | None = None,
        freshness: str | None = None,
        fetched_at: str | None = None,
        why_it_matters: str | None = None,
    ) -> Finding:
        project, theme = self.ensure_background_theme(
            workspace_id=workspace_id,
            focus_area=focus_area,
            description="Grounding references collected during coach turns.",
        )

        thread = next((item for item in theme.threads if item.angle == "grounding"), None)
        if thread is None:
            thread = theme.add_thread(angle="grounding", depth=ThreadDepth.SHALLOW)

        normalized_content = " ".join(content.strip().split())
        normalized_source = source.strip().lower()
        normalized_evidence_summary = self._normalize_summary(
            evidence_summary
            or self._evidence_summary(content, source=source, title=focus_area)
        )
        reference_key = self._background_reference_key(
            normalized_source,
            normalized_content,
            duplicate_key=duplicate_key,
        )
        for existing in thread.findings:
            existing_signature = self._finding_reference_key(existing)
            if existing_signature == reference_key:
                if normalized_evidence_summary and not existing.evidence_summary:
                    existing.evidence_summary = normalized_evidence_summary
                    self._persist_project(project)
                return existing

        metadata_tags = [
            str(tag).strip()
            for tag in (tags or ["background", "grounding"])
            if str(tag).strip()
        ]
        metadata_tags.append(f"reference_key:{reference_key}")
        if source_type:
            metadata_tags.append(f"source_type:{source_type}")
        if freshness:
            metadata_tags.append(f"freshness:{freshness}")
        if fetched_at:
            metadata_tags.append(f"fetched_at:{fetched_at}")
        if why_it_matters:
            metadata_tags.append(f"why:{why_it_matters[:120]}")

        finding = theme.add_finding(
            thread.id,
            content=normalized_content,
            source=source,
            confidence=trust_score,
            tags=list(dict.fromkeys(metadata_tags)),
        )
        if finding is None:
            raise ValueError("Failed to record background research finding.")
        finding.evidence_summary = normalized_evidence_summary
        if created_at is not None:
            finding.created_at = created_at

        project.agent_state.add_thinking(
            role=project.agent_state.current_role,
            question="What should the coach remember from this external reference?",
            reasoning=normalized_content[:240],
            conclusion=f"Source={source}; trust={trust_score:.2f}",
        )
        project.gate.add_message(
            "agent",
            f"Logged background reference for '{theme.title}' from {source}.",
        )
        self._persist_project(project)
        return finding

    def recent_background_references(
        self,
        *,
        workspace_id: str,
        focus_area: str | None = None,
        tags: list[str] | None = None,
        min_confidence: float = 0.0,
        limit: int = 6,
    ) -> list[dict[str, Any]]:
        project = self.ensure_background_project(workspace_id=workspace_id)
        normalized_focus = (focus_area or "").strip().lower()
        required_tags = {str(tag).strip().lower() for tag in (tags or []) if str(tag).strip()}
        candidates: list[dict[str, Any]] = []

        for theme in project.themes:
            if normalized_focus and normalized_focus not in theme.title.strip().lower():
                continue
            for thread in theme.threads:
                for finding in thread.findings:
                    if finding.confidence < min_confidence:
                        continue
                    finding_tags = {str(tag).strip().lower() for tag in finding.tags if str(tag).strip()}
                    if required_tags and not required_tags.intersection(finding_tags):
                        continue
                    candidates.append(
                        {
                            "id": finding.id,
                            "focus_area": theme.title,
                            "thread_angle": thread.angle,
                            "snippet": finding.content,
                            "evidence_summary": finding.evidence_summary
                            or self._evidence_summary(finding.content, source=finding.source, title=theme.title),
                            "duplicate_key": self._finding_reference_key(finding),
                            "source": finding.source,
                            "trust_score": round(float(finding.confidence), 2),
                            "tags": list(finding.tags),
                            "created_at": finding.created_at.isoformat(),
                            "source_type": self._tag_value(finding.tags, prefix="source_type:"),
                            "freshness": self._tag_value(finding.tags, prefix="freshness:"),
                            "fetched_at": self._tag_value(finding.tags, prefix="fetched_at:"),
                            "why_it_matters": self._tag_value(finding.tags, prefix="why:")
                            or f"Background reference collected for {theme.title}.",
                        }
                    )

        ranked = sorted(
            candidates,
            key=lambda item: (
                float(item["trust_score"]),
                str(item["created_at"]),
            ),
            reverse=True,
        )

        deduped: list[dict[str, Any]] = []
        seen_signatures: set[str] = set()
        for item in ranked:
            signature = self._normalize_reference_key(
                str(item.get("duplicate_key", "")).strip()
                or f"{str(item.get('source', '')).strip().lower()}::{self._reference_fingerprint(str(item.get('snippet', '') or ''), str(item.get('why_it_matters', '') or ''))}"
            )
            if signature in seen_signatures:
                continue
            seen_signatures.add(signature)
            deduped.append(item)
            if len(deduped) >= limit:
                break
        return deduped

    def _background_reference_key(
        self,
        source: str,
        content: str,
        *,
        duplicate_key: str | None = None,
    ) -> str:
        key = self._normalize_reference_key(duplicate_key or "")
        if key:
            return key
        fingerprint = self._reference_fingerprint(source, content)
        if fingerprint:
            return sha1(f"{source.strip().lower()}::{fingerprint}".encode("utf-8")).hexdigest()[:20]
        return sha1(source.strip().lower().encode("utf-8")).hexdigest()[:20]

    def _finding_reference_key(self, finding: Finding) -> str:
        tagged_key = self._tag_value(finding.tags, prefix="reference_key:")
        if tagged_key:
            return self._normalize_reference_key(tagged_key)
        return self._background_reference_key(finding.source, finding.content)

    def _reference_fingerprint(self, *parts: str) -> str:
        tokens: list[str] = []
        for part in parts:
            if not part:
                continue
            cleaned = re.findall(r"[a-z0-9]+", part.lower())
            tokens.extend(token for token in cleaned if token not in _REFERENCE_STOPWORDS)
        if not tokens:
            return ""
        return " ".join(tokens[:24])

    def _normalize_reference_key(self, value: str) -> str:
        return " ".join(value.strip().lower().split())

    def _evidence_summary(self, content: str, *, source: str = "", title: str = "") -> str:
        raw = content.strip()
        text = " ".join(raw.split())
        if not text:
            return ""
        normalized = re.sub(r"^[\ufeff\s#>*-]+", "", raw).strip()
        title_hint = " ".join(title.lower().split())
        if "\n" in raw:
            lines = [line.strip() for line in normalized.splitlines() if line.strip()]
            if len(lines) > 1:
                lead = lines[0].lower()
                source_hint = self._reference_fingerprint(source)
                if (title_hint and title_hint in lead) or (source_hint and source_hint in self._reference_fingerprint(lead)) or ":" in lines[0] or len(lines[0]) < 80:
                    text = " ".join(lines[1:])
                elif ":" in lines[0] or len(lines[0]) < 80:
                    text = " ".join(lines[1:] or lines[:1])
                else:
                    text = " ".join(lines[:2])
        elif title_hint and " ".join(normalized.lower().split()).startswith(title_hint):
            normalized = normalized[len(title.strip()):].lstrip(" :-—–,.;")
            text = normalized or text
        if ":" in text:
            head, tail = text.split(":", 1)
            if len(head.strip()) < 80 and tail.strip():
                text = tail.strip()
        parts = re.split(r"(?<=[.!?。！？])\s+", text, maxsplit=2)
        text = next((part.strip() for part in parts if part.strip()), text)
        return text[:160]

    def _normalize_summary(self, value: str) -> str:
        return " ".join(str(value or "").strip().split())

    def _tag_value(self, tags: list[str], *, prefix: str) -> str:
        for tag in tags:
            if tag.startswith(prefix):
                return tag[len(prefix):]
        return ""

    def add_artifact(
        self, project_id: str, theme_id: str, *, title: str, kind: ArtifactKind, content: str
    ) -> Artifact | None:
        project = self.get_project(project_id)
        if not project:
            return None
        for theme in project.themes:
            if theme.id == theme_id:
                artifact = theme.add_artifact(title=title, kind=kind, content=content)
                project.gate.add_message(
                    "agent",
                    f"Created artifact '{title}' ({kind}) for theme '{theme.title}'. "
                    f"This is version {artifact.version}.",
                )
                self._persist_project(project)
                return artifact
        return None

    def get_state(self, project_id: str) -> dict[str, Any] | None:
        project = self.get_project(project_id)
        if not project:
            return None
        return {
            "project": project.to_dict(),
            "schedule_status": ResearchScheduler.project_schedule_status(project),
        }

    def advance_research(self, project_id: str, *, theme_id: str | None = None) -> dict[str, Any]:
        project = self.get_project(project_id)
        if not project:
            return {"error": "Project not found"}

        themes_to_advance = []
        if theme_id:
            for t in project.themes:
                if t.id == theme_id:
                    themes_to_advance.append(t)
        else:
            themes_to_advance = ResearchScheduler.themes_needing_advance(project)

        results = []
        for theme in themes_to_advance:
            result = self._advance_theme(project, theme)
            results.append(result)

        if not results:
            return {"message": "No themes need advancement at this time.", "themes_advanced": []}

        return {
            "message": f"Advanced {len(results)} theme(s).",
            "themes_advanced": results,
            "agent_state": project.agent_state.to_dict(),
        }

    def _advance_theme(self, project: ResearchProject, theme: ResearchTheme) -> dict[str, Any]:
        old_role = project.agent_state.current_role
        actions_taken = []

        overdue = ResearchScheduler.overdue_checkpoints(theme)
        if overdue:
            for cp_info in overdue:
                for cp in theme.schedule.checkpoints if theme.schedule else []:
                    if cp.id == cp_info["id"]:
                        ResearchScheduler.mark_checkpoint_complete(theme, cp.id)
                        actions_taken.append(f"Marked overdue checkpoint '{cp.label}' as complete.")
                        break

        if project.agent_state.current_iteration == 0:
            project.agent_state.switch_role(AgentRole.RESEARCHER)
            project.gate.add_message(
                "agent",
                f"Starting research iteration for '{theme.title}'. "
                f"Role: RESEARCHER. Focus: Deep search and information gathering.",
            )
            actions_taken.append("Switched to RESEARCHER role for deep search phase.")

        elif project.agent_state.current_iteration == 1:
            project.agent_state.switch_role(AgentRole.EDITOR)
            project.gate.add_message(
                "agent",
                f"Editing phase for '{theme.title}'. "
                f"Role: EDITOR. Focus: Organize findings into coherent structure.",
            )
            actions_taken.append("Switched to EDITOR role for organization phase.")

        elif project.agent_state.current_iteration == 2:
            project.agent_state.switch_role(AgentRole.CRITIC)
            project.gate.add_message(
                "agent",
                f"Critique phase for '{theme.title}'. "
                f"Role: CRITIC. Focus: Review for gaps, inconsistencies, and weaknesses.",
            )
            actions_taken.append("Switched to CRITIC role for review phase.")

        elif project.agent_state.current_iteration >= 3:
            project.agent_state.switch_role(AgentRole.SYNTHESIZER)
            project.gate.add_message(
                "agent",
                f"Synthesis phase for '{theme.title}'. "
                f"Role: SYNTHESIZER. Focus: Final synthesis and artifact creation.",
            )
            actions_taken.append("Switched to SYNTHESIZER role for final synthesis.")

            approval = project.gate.request_approval(
                title=f"Complete research phase for '{theme.title}'?",
                description=f"Research has completed {project.agent_state.self_review_count} review rounds. "
                f"Found {sum(len(t.findings) for t in theme.threads)} findings across {len(theme.threads)} threads. "
                f"Ready to finalize?",
                agent_context={"theme_id": theme.id, "iteration": project.agent_state.current_iteration},
            )

            actions_taken.append(f"Created approval request: {approval.id}")
            project.agent_state.reset_iteration()

        can_continue = project.agent_state.increment_review()

        # Persist all changes to repository
        self._persist_project(project)

        return {
            "theme_id": theme.id,
            "theme_title": theme.title,
            "role_transition": f"{old_role} → {project.agent_state.current_role}",
            "actions_taken": actions_taken,
            "iteration": project.agent_state.current_iteration,
            "can_continue": can_continue,
            "progress": ResearchScheduler.progress_percentage(theme),
        }

    def human_message(self, project_id: str, message: str) -> dict[str, Any] | None:
        project = self.get_project(project_id)
        if not project:
            return None

        project.gate.add_message("human", message)

        if "/advance" in message.lower():
            result = self.advance_research(project_id)
            self._persist_project(project)
            return result

        if "/status" in message.lower():
            return self.get_state(project_id)

        response = self._generate_agent_response(project, message)
        project.gate.add_message("agent", response)

        # Persist gate messages
        self._persist_project(project)

        return {
            "project_id": project_id,
            "response": response,
            "agent_state": project.agent_state.to_dict(),
        }

    def search_web(
        self,
        query: str,
        *,
        workspace_id: str = "default",
        focus_area: str = "Web Search",
        limit: int = 3,
    ) -> dict[str, Any]:
        """Perform a web search and record findings to the active research project."""
        if not self._web_search.network_enabled:
            return {
                "error": "Trainer network source acquisition is disabled.",
                "reason_code": "network_disabled",
                "query": query,
                "results": [],
            }
        try:
            results = self._search_enricher.enrich(query, limit=limit)
        except ControlledFetchError as exc:
            return {
                "error": exc.detail,
                "reason_code": exc.code,
                "query": query,
                "results": [],
            }
        except Exception as exc:
            return {"error": str(exc), "query": query, "results": []}

        if not results:
            return {"query": query, "results": [], "message": "No results found."}

        fetched_results = [
            result
            for result in results
            if str(result.get("content_snippet", "")).strip()
            and str(result.get("fetched_at", "")).strip()
        ]
        if not fetched_results:
            reason_code = next(
                (
                    str(result.get("reason_code", "")).strip()
                    for result in results
                    if str(result.get("reason_code", "")).strip()
                ),
                "fetch_failed",
            )
            return {
                "error": "No search result page could be fetched and verified.",
                "reason_code": reason_code,
                "query": query,
                "results": [],
            }

        # Record findings to background research
        recorded_findings = []
        for result in fetched_results:
            finding = self.record_background_reference(
                workspace_id=workspace_id,
                focus_area=focus_area,
                source=result["url"],
                content=f"{result['title']}\n{result.get('content_snippet', '')}",
                trust_score=0.7,
                tags=["web_search", f"source:{result['source']}"],
                source_type="web_search",
                freshness=str(result["freshness"]),
                fetched_at=str(result["fetched_at"]),
                why_it_matters=result["title"],
            )
            recorded_findings.append({
                "id": finding.id,
                "title": result["title"],
                "source": result["source"],
                "url": result["url"],
                "snippet": result.get("content_snippet", "")[:200],
            })

        return {
            "query": query,
            "results_count": len(recorded_findings),
            "results": recorded_findings,
        }

    def _generate_agent_response(self, project: ResearchProject, human_message: str) -> str:
        role = project.agent_state.current_role
        active_themes = project.active_themes()

        if not active_themes:
            return (
                "I notice there are no active research themes yet. "
                "Would you like me to help you create and activate a research theme? "
                "Use /status to see current state, or describe what you'd like to research."
            )

        theme_names = ", ".join(t.title for t in active_themes)

        # Check if user wants web search
        if "/search" in human_message.lower() or "/web" in human_message.lower():
            query = human_message.replace("/search", "").replace("/web", "").strip()
            if query:
                search_result = self.search_web(query, workspace_id=project.id, focus_area=theme_names)
                if "error" in search_result:
                    return f"[{role.upper()}] Search error: {search_result['error']}"
                results_summary = "\n".join(
                    f"- {r['title']} ({r['source']})" for r in search_result.get("results", [])
                )
                return (
                    f"[{role.upper()}] Web search completed for: {query}\n"
                    f"Found {search_result.get('results_count', 0)} results:\n"
                    f"{results_summary}\n\n"
                    f"These findings have been recorded to the research project."
                )
            return f"[{role.upper()}] Please provide a search query after /search"

        if role == AgentRole.RESEARCHER:
            return (
                f"[{role.upper()}] Currently researching: {theme_names}\n"
                f"I'm in the information gathering phase. "
                f"Use /search <query> to search the web for information.\n\n"
                f"Your message: '{human_message[:100]}...'\n"
                f"Shall I add this as a finding or explore a specific angle?"
            )

        if role == AgentRole.EDITOR:
            return (
                f"[{role.upper()}] Organizing research for: {theme_names}\n"
                f"I'm structuring the findings into coherent narratives. "
                f"Current iteration: {project.agent_state.current_iteration}.\n\n"
                f"What aspect would you like me to focus on organizing?"
            )

        if role == AgentRole.CRITIC:
            return (
                f"[{role.upper()}] Reviewing research for: {theme_names}\n"
                f"I'm looking for gaps, inconsistencies, and weak arguments. "
                f"Review round: {project.agent_state.self_review_count}/{project.agent_state.max_review_rounds}.\n\n"
                f"Do you have specific concerns you'd like me to address?"
            )

        if role == AgentRole.SYNTHESIZER:
            return (
                f"[{role.upper()}] Final synthesis for: {theme_names}\n"
                f"I'm preparing the final artifacts and conclusions. "
                f"This is the last phase before completion.\n\n"
                f"Is there anything specific you'd like included in the final output?"
            )

        return f"[{role.upper()}] Processing your input for: {theme_names}"

    def resolve_approval(self, project_id: str, approval_id: str, approved: bool) -> dict[str, Any] | None:
        project = self.get_project(project_id)
        if not project:
            return None

        approval = project.gate.resolve_approval(approval_id, approved)
        if not approval:
            return None

        if approved:
            if approval.agent_context.get("theme_id"):
                for theme in project.themes:
                    if theme.id == approval.agent_context["theme_id"]:
                        theme.complete()
                        project.gate.add_message(
                            "agent",
                            f"Research for '{theme.title}' has been completed and approved. "
                            f"Generated {len(theme.artifacts)} artifacts.",
                        )
                        break
        else:
            project.agent_state.self_review_count = 0
            project.gate.add_message(
                "agent",
                "Approval rejected. I'll continue refining the research. "
                "Let me know what changes you'd like to see.",
            )

        # Persist approval resolution
        self._persist_project(project)

        return {
            "approval_id": approval_id,
            "status": approval.status,
            "resolved_at": approval.resolved_at.isoformat() if approval.resolved_at else None,
        }

    def get_pending_approvals(self, project_id: str) -> list[dict[str, Any]]:
        project = self.get_project(project_id)
        if not project:
            return []

        return [
            {
                "id": a.id,
                "title": a.title,
                "description": a.description,
                "created_at": a.created_at.isoformat(),
                "agent_context": a.agent_context,
            }
            for a in project.gate.pending_approvals()
        ]

    def add_checkpoint(
        self, project_id: str, theme_id: str, *, label: str, due_date: datetime
    ) -> Checkpoint | None:
        project = self.get_project(project_id)
        if not project:
            return None

        for theme in project.themes:
            if theme.id == theme_id and theme.schedule:
                cp = Checkpoint.create(label=label, due_date=due_date)
                theme.schedule.checkpoints.append(cp)
                theme.updated_at = datetime.now()
                project.gate.add_message("agent", f"Added checkpoint '{label}' to theme '{theme.title}' for {due_date.strftime('%Y-%m-%d')}.")
                self._persist_project(project)
                return cp
        return None
