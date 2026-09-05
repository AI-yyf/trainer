from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ScheduleCadence(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"
    BIWEEKLY = "biweekly"
    MONTHLY = "monthly"


class AgentRole(StrEnum):
    RESEARCHER = "researcher"
    EDITOR = "editor"
    CRITIC = "critic"
    SYNTHESIZER = "synthesizer"


class ThemeStatus(StrEnum):
    PLANNING = "planning"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"


class ThreadDepth(StrEnum):
    SHALLOW = "shallow"
    MEDIUM = "medium"
    DEEP = "deep"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ArtifactKind(StrEnum):
    NOTE = "note"
    DRAFT = "draft"
    SUMMARY = "summary"
    REPORT = "report"
    OUTLINE = "outline"
    BIBLIOGRAPHY = "bibliography"


# ---------------------------------------------------------------------------
# Schedule
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Checkpoint:
    id: str
    label: str
    due_date: datetime
    completed: bool = False
    completed_at: datetime | None = None
    notes: str = ""

    @classmethod
    def create(cls, *, label: str, due_date: datetime) -> Checkpoint:
        return cls(id=f"cp_{uuid4().hex[:8]}", label=label, due_date=due_date)

    def to_full_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "due_date": self.due_date.isoformat(),
            "completed": self.completed,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Checkpoint:
        return cls(
            id=data["id"],
            label=data["label"],
            due_date=datetime.fromisoformat(data["due_date"]),
            completed=data.get("completed", False),
            completed_at=datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None,
            notes=data.get("notes", ""),
        )


@dataclass(slots=True)
class ScheduleSpec:
    start_date: datetime
    end_date: datetime
    cadence: ScheduleCadence = ScheduleCadence.WEEKLY
    checkpoints: list[Checkpoint] = field(default_factory=list)

    @property
    def duration(self) -> timedelta:
        return self.end_date - self.start_date

    @classmethod
    def create(
        cls,
        *,
        start_date: datetime | None = None,
        duration_weeks: int = 4,
        cadence: ScheduleCadence = ScheduleCadence.WEEKLY,
    ) -> ScheduleSpec:
        start = start_date or utc_now()
        end = start + timedelta(weeks=duration_weeks)
        checkpoints = []
        if cadence == ScheduleCadence.DAILY:
            step = timedelta(days=1)
        elif cadence == ScheduleCadence.WEEKLY:
            step = timedelta(weeks=1)
        elif cadence == ScheduleCadence.BIWEEKLY:
            step = timedelta(weeks=2)
        else:
            step = timedelta(weeks=4)

        current = start + step
        idx = 1
        while current <= end:
            checkpoints.append(Checkpoint.create(label=f"Checkpoint {idx}", due_date=current))
            current += step
            idx += 1

        return cls(start_date=start, end_date=end, cadence=cadence, checkpoints=checkpoints)

    def to_full_dict(self) -> dict[str, Any]:
        return {
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "cadence": self.cadence,
            "checkpoints": [cp.to_full_dict() for cp in self.checkpoints],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScheduleSpec:
        return cls(
            start_date=datetime.fromisoformat(data["start_date"]),
            end_date=datetime.fromisoformat(data["end_date"]),
            cadence=ScheduleCadence(data["cadence"]),
            checkpoints=[Checkpoint.from_dict(cp) for cp in data.get("checkpoints", [])],
        )


# ---------------------------------------------------------------------------
# Findings & Artifacts
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Finding:
    id: str
    content: str
    source: str
    confidence: float = 0.5
    tags: list[str] = field(default_factory=list)
    evidence_summary: str = ""
    created_at: datetime = field(default_factory=utc_now)

    @classmethod
    def create(cls, *, content: str, source: str, confidence: float = 0.5, tags: list[str] | None = None) -> Finding:
        return cls(id=f"find_{uuid4().hex[:8]}", content=content, source=source, confidence=confidence, tags=list(tags or []))

    def to_full_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "source": self.source,
            "confidence": self.confidence,
            "tags": list(self.tags),
            "evidence_summary": self.evidence_summary,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Finding:
        return cls(
            id=data["id"],
            content=data["content"],
            source=data["source"],
            confidence=data.get("confidence", 0.5),
            tags=list(data.get("tags", [])),
            evidence_summary=data.get("evidence_summary", ""),
            created_at=datetime.fromisoformat(data["created_at"]),
        )


@dataclass(slots=True)
class Artifact:
    id: str
    title: str
    kind: ArtifactKind
    content: str
    version: int = 1
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    @classmethod
    def create(cls, *, title: str, kind: ArtifactKind, content: str) -> Artifact:
        return cls(id=f"art_{uuid4().hex[:8]}", title=title, kind=kind, content=content)

    def to_full_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "kind": self.kind,
            "content": self.content,
            "version": self.version,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Artifact:
        return cls(
            id=data["id"],
            title=data["title"],
            kind=ArtifactKind(data["kind"]),
            content=data["content"],
            version=data.get("version", 1),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
        )


# ---------------------------------------------------------------------------
# Research Thread (an angle within a theme)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ResearchThread:
    id: str
    angle: str
    depth: ThreadDepth = ThreadDepth.MEDIUM
    findings: list[Finding] = field(default_factory=list)
    status: str = "active"
    created_at: datetime = field(default_factory=utc_now)

    @classmethod
    def create(cls, *, angle: str, depth: ThreadDepth = ThreadDepth.MEDIUM) -> ResearchThread:
        return cls(id=f"thread_{uuid4().hex[:8]}", angle=angle, depth=depth)

    def to_full_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "angle": self.angle,
            "depth": self.depth,
            "findings": [f.to_full_dict() for f in self.findings],
            "status": self.status,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ResearchThread:
        return cls(
            id=data["id"],
            angle=data["angle"],
            depth=ThreadDepth(data.get("depth", ThreadDepth.MEDIUM)),
            findings=[Finding.from_dict(f) for f in data.get("findings", [])],
            status=data.get("status", "active"),
            created_at=datetime.fromisoformat(data["created_at"]),
        )


# ---------------------------------------------------------------------------
# Research Theme
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ResearchTheme:
    id: str
    title: str
    description: str
    duration_weeks: int = 4
    status: ThemeStatus = ThemeStatus.PLANNING
    schedule: ScheduleSpec | None = None
    threads: list[ResearchThread] = field(default_factory=list)
    artifacts: list[Artifact] = field(default_factory=list)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    @classmethod
    def create(
        cls,
        *,
        title: str,
        description: str,
        duration_weeks: int = 4,
        cadence: ScheduleCadence = ScheduleCadence.WEEKLY,
        start_date: datetime | None = None,
    ) -> ResearchTheme:
        schedule = ScheduleSpec.create(start_date=start_date, duration_weeks=duration_weeks, cadence=cadence)
        return cls(id=f"theme_{uuid4().hex[:8]}", title=title, description=description, duration_weeks=duration_weeks, schedule=schedule)

    def activate(self) -> None:
        self.status = ThemeStatus.ACTIVE
        self.updated_at = utc_now()

    def pause(self) -> None:
        self.status = ThemeStatus.PAUSED
        self.updated_at = utc_now()

    def complete(self) -> None:
        self.status = ThemeStatus.COMPLETED
        self.updated_at = utc_now()

    def add_thread(self, angle: str, depth: ThreadDepth = ThreadDepth.MEDIUM) -> ResearchThread:
        thread = ResearchThread.create(angle=angle, depth=depth)
        self.threads.append(thread)
        self.updated_at = utc_now()
        return thread

    def add_finding(self, thread_id: str, content: str, source: str, confidence: float = 0.5, tags: list[str] | None = None) -> Finding | None:
        for thread in self.threads:
            if thread.id == thread_id:
                finding = Finding.create(content=content, source=source, confidence=confidence, tags=tags)
                thread.findings.append(finding)
                self.updated_at = utc_now()
                return finding
        return None

    def add_artifact(self, title: str, kind: ArtifactKind, content: str) -> Artifact:
        artifact = Artifact.create(title=title, kind=kind, content=content)
        self.artifacts.append(artifact)
        self.updated_at = utc_now()
        return artifact

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "duration_weeks": self.duration_weeks,
            "status": self.status,
            "schedule": {
                "start_date": self.schedule.start_date.isoformat() if self.schedule else None,
                "end_date": self.schedule.end_date.isoformat() if self.schedule else None,
                "cadence": self.schedule.cadence if self.schedule else None,
                "checkpoints": [
                    {
                        "id": cp.id,
                        "label": cp.label,
                        "due_date": cp.due_date.isoformat(),
                        "completed": cp.completed,
                    }
                    for cp in (self.schedule.checkpoints if self.schedule else [])
                ],
            },
            "threads": [
                {
                    "id": t.id,
                    "angle": t.angle,
                    "depth": t.depth,
                    "status": t.status,
                    "findings_count": len(t.findings),
                }
                for t in self.threads
            ],
            "artifacts_count": len(self.artifacts),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    def to_full_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "duration_weeks": self.duration_weeks,
            "status": self.status,
            "schedule": self.schedule.to_full_dict() if self.schedule else None,
            "threads": [t.to_full_dict() for t in self.threads],
            "artifacts": [a.to_full_dict() for a in self.artifacts],
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ResearchTheme:
        return cls(
            id=data["id"],
            title=data["title"],
            description=data["description"],
            duration_weeks=data.get("duration_weeks", 4),
            status=ThemeStatus(data.get("status", ThemeStatus.PLANNING)),
            schedule=ScheduleSpec.from_dict(data["schedule"]) if data.get("schedule") else None,
            threads=[ResearchThread.from_dict(t) for t in data.get("threads", [])],
            artifacts=[Artifact.from_dict(a) for a in data.get("artifacts", [])],
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
        )


# ---------------------------------------------------------------------------
# Agent State
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ThinkingEntry:
    id: str
    role: AgentRole
    question: str
    reasoning: str
    conclusion: str
    created_at: datetime = field(default_factory=utc_now)

    @classmethod
    def create(cls, *, role: AgentRole, question: str, reasoning: str, conclusion: str) -> ThinkingEntry:
        return cls(id=f"think_{uuid4().hex[:8]}", role=role, question=question, reasoning=reasoning, conclusion=conclusion)

    def to_full_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "role": self.role,
            "question": self.question,
            "reasoning": self.reasoning,
            "conclusion": self.conclusion,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ThinkingEntry:
        return cls(
            id=data["id"],
            role=AgentRole(data["role"]),
            question=data["question"],
            reasoning=data["reasoning"],
            conclusion=data["conclusion"],
            created_at=datetime.fromisoformat(data["created_at"]),
        )


@dataclass(slots=True)
class AgentState:
    current_role: AgentRole = AgentRole.RESEARCHER
    thinking_log: list[ThinkingEntry] = field(default_factory=list)
    pending_questions: list[str] = field(default_factory=list)
    self_review_count: int = 0
    max_review_rounds: int = 3
    current_iteration: int = 0

    def switch_role(self, role: AgentRole) -> None:
        self.current_role = role

    def add_thinking(self, *, role: AgentRole, question: str, reasoning: str, conclusion: str) -> ThinkingEntry:
        entry = ThinkingEntry.create(role=role, question=question, reasoning=reasoning, conclusion=conclusion)
        self.thinking_log.append(entry)
        return entry

    def add_pending_question(self, question: str) -> None:
        self.pending_questions.append(question)

    def resolve_pending_question(self, question: str) -> None:
        if question in self.pending_questions:
            self.pending_questions.remove(question)

    def increment_review(self) -> bool:
        self.self_review_count += 1
        self.current_iteration += 1
        return self.self_review_count < self.max_review_rounds

    def reset_iteration(self) -> None:
        self.current_iteration = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "current_role": self.current_role,
            "thinking_log": [
                {
                    "id": t.id,
                    "role": t.role,
                    "question": t.question,
                    "conclusion": t.conclusion,
                    "created_at": t.created_at.isoformat(),
                }
                for t in self.thinking_log[-10:]
            ],
            "pending_questions": self.pending_questions[-5:],
            "self_review_count": self.self_review_count,
            "current_iteration": self.current_iteration,
            "max_review_rounds": self.max_review_rounds,
        }

    def to_full_dict(self) -> dict[str, Any]:
        return {
            "current_role": self.current_role,
            "thinking_log": [t.to_full_dict() for t in self.thinking_log],
            "pending_questions": list(self.pending_questions),
            "self_review_count": self.self_review_count,
            "max_review_rounds": self.max_review_rounds,
            "current_iteration": self.current_iteration,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentState:
        return cls(
            current_role=AgentRole(data.get("current_role", AgentRole.RESEARCHER)),
            thinking_log=[ThinkingEntry.from_dict(t) for t in data.get("thinking_log", [])],
            pending_questions=list(data.get("pending_questions", [])),
            self_review_count=data.get("self_review_count", 0),
            max_review_rounds=data.get("max_review_rounds", 3),
            current_iteration=data.get("current_iteration", 0),
        )


# ---------------------------------------------------------------------------
# Approval
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Approval:
    id: str
    title: str
    description: str
    status: ApprovalStatus = ApprovalStatus.PENDING
    created_at: datetime = field(default_factory=utc_now)
    resolved_at: datetime | None = None
    agent_context: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(cls, *, title: str, description: str, agent_context: dict[str, Any] | None = None) -> Approval:
        return cls(id=f"appr_{uuid4().hex[:8]}", title=title, description=description, agent_context=dict(agent_context or {}))

    def approve(self) -> None:
        self.status = ApprovalStatus.APPROVED
        self.resolved_at = utc_now()

    def reject(self) -> None:
        self.status = ApprovalStatus.REJECTED
        self.resolved_at = utc_now()

    def to_full_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "agent_context": dict(self.agent_context),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Approval:
        return cls(
            id=data["id"],
            title=data["title"],
            description=data["description"],
            status=ApprovalStatus(data.get("status", ApprovalStatus.PENDING)),
            created_at=datetime.fromisoformat(data["created_at"]),
            resolved_at=datetime.fromisoformat(data["resolved_at"]) if data.get("resolved_at") else None,
            agent_context=dict(data.get("agent_context", {})),
        )


# ---------------------------------------------------------------------------
# Workbench Gate (human-agent communication portal)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class WorkbenchGate:
    messages: list[dict[str, Any]] = field(default_factory=list)
    approvals: list[Approval] = field(default_factory=list)
    notifications: list[str] = field(default_factory=list)

    def add_message(self, role: str, content: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        msg = {
            "id": f"gate_msg_{uuid4().hex[:8]}",
            "role": role,
            "content": content,
            "timestamp": utc_now().isoformat(),
            "metadata": metadata or {},
        }
        self.messages.append(msg)
        return msg

    def request_approval(self, *, title: str, description: str, agent_context: dict[str, Any] | None = None) -> Approval:
        approval = Approval.create(title=title, description=description, agent_context=agent_context)
        self.approvals.append(approval)
        return approval

    def resolve_approval(self, approval_id: str, approved: bool) -> Approval | None:
        for approval in self.approvals:
            if approval.id == approval_id and approval.status == ApprovalStatus.PENDING:
                if approved:
                    approval.approve()
                else:
                    approval.reject()
                return approval
        return None

    def add_notification(self, message: str) -> None:
        self.notifications.append(message)

    def pending_approvals(self) -> list[Approval]:
        return [a for a in self.approvals if a.status == ApprovalStatus.PENDING]

    def to_dict(self) -> dict[str, Any]:
        return {
            "messages": self.messages[-20:],
            "pending_approvals": [a.id for a in self.pending_approvals()],
            "notifications": self.notifications[-5:],
        }

    def to_full_dict(self) -> dict[str, Any]:
        return {
            "messages": list(self.messages),
            "approvals": [a.to_full_dict() for a in self.approvals],
            "notifications": list(self.notifications),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkbenchGate:
        return cls(
            messages=list(data.get("messages", [])),
            approvals=[Approval.from_dict(a) for a in data.get("approvals", [])],
            notifications=list(data.get("notifications", [])),
        )


# ---------------------------------------------------------------------------
# Research Project (top-level container)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ResearchProject:
    id: str
    title: str
    description: str
    themes: list[ResearchTheme] = field(default_factory=list)
    agent_state: AgentState = field(default_factory=AgentState)
    gate: WorkbenchGate = field(default_factory=WorkbenchGate)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    @classmethod
    def create(cls, *, title: str, description: str) -> ResearchProject:
        project = cls(id=f"proj_{uuid4().hex[:8]}", title=title, description=description)
        project.gate.add_message("system", f"Research project '{title}' created. Ready to add themes and start research.")
        return project

    def add_theme(
        self,
        *,
        title: str,
        description: str,
        duration_weeks: int = 4,
        cadence: ScheduleCadence = ScheduleCadence.WEEKLY,
        start_date: datetime | None = None,
    ) -> ResearchTheme:
        theme = ResearchTheme.create(title=title, description=description, duration_weeks=duration_weeks, cadence=cadence, start_date=start_date)
        self.themes.append(theme)
        self.updated_at = utc_now()
        assert theme.schedule is not None  # create() always produces a schedule
        self.gate.add_message(
            "agent",
            f"Theme '{title}' added (duration: {duration_weeks} weeks, cadence: {cadence}). "
            f"Schedule: {theme.schedule.start_date.strftime('%Y-%m-%d')} → {theme.schedule.end_date.strftime('%Y-%m-%d')} "
            f"with {len(theme.schedule.checkpoints)} checkpoints.",
        )
        return theme

    def activate_theme(self, theme_id: str) -> ResearchTheme | None:
        for theme in self.themes:
            if theme.id == theme_id and theme.status == ThemeStatus.PLANNING:
                theme.activate()
                self.gate.add_notification(f"Theme '{theme.title}' is now active.")
                return theme
        return None

    def active_themes(self) -> list[ResearchTheme]:
        return [t for t in self.themes if t.status == ThemeStatus.ACTIVE]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "themes": [t.to_dict() for t in self.themes],
            "agent_state": self.agent_state.to_dict(),
            "gate": self.gate.to_dict(),
            "active_themes_count": len(self.active_themes()),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    def to_full_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "themes": [t.to_full_dict() for t in self.themes],
            "agent_state": self.agent_state.to_full_dict(),
            "gate": self.gate.to_full_dict(),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ResearchProject:
        return cls(
            id=data["id"],
            title=data["title"],
            description=data["description"],
            themes=[ResearchTheme.from_dict(t) for t in data.get("themes", [])],
            agent_state=AgentState.from_dict(data["agent_state"]) if data.get("agent_state") else AgentState(),
            gate=WorkbenchGate.from_dict(data["gate"]) if data.get("gate") else WorkbenchGate(),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
        )
