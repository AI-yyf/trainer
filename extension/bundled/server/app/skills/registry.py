"""Skill registry: Tutor / Knowledge / Action skills + Learner Competency.

Three skill kinds (§八 Skill 生态):
- ``tutor``     — how to teach: explanations, exercises, knowledge transfer
- ``knowledge`` — what the project/domain knows: architecture, patterns
- ``action``    — how to do: analysis flows, external tools, automation

Plus ``learner_competency`` — what the user has actually mastered, tracked
separately from skill installation (§八: Skill 使用成功 ≠ 掌握).

SKILL.md progressive loading: front matter is parsed at registration,
the body is only loaded when the skill is activated.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_SKILL_FRONT_MATTER = re.compile(
    r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL
)
_SAFE_NAME = re.compile(r"[^a-z0-9_-]+")


@dataclass(slots=True)
class SkillRecord:
    skill_id: str
    kind: str  # tutor | knowledge | action
    name: str
    description: str
    permissions: list[str]  # e.g. ["read:workspace", "search:resources"]
    source_path: str | None  # SKILL.md path (external) or None (inline)
    active: bool = False
    reviewed: bool = False  # has the user approved this skill?
    body: str = ""  # only populated when activated
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_payload(self, *, include_body: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "skill_id": self.skill_id,
            "kind": self.kind,
            "name": self.name,
            "description": self.description,
            "permissions": list(self.permissions),
            "active": self.active,
            "reviewed": self.reviewed,
            "source_path": self.source_path,
            "metadata": dict(self.metadata),
        }
        if include_body:
            payload["body"] = self.body
        return payload


def parse_skill_md(path: Path) -> tuple[dict[str, str], str]:
    """Parse SKILL.md front matter + body (progressive loading).

    Returns ``(front_matter_dict, body)``. Front matter keys are lowercased.
    """

    text = path.read_text(encoding="utf-8", errors="replace")
    match = _SKILL_FRONT_MATTER.match(text)
    if not match:
        return {}, text.strip()
    raw = match.group(1)
    body = match.group(2).strip()
    front: dict[str, str] = {}
    for line in raw.splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            front[key.strip().lower()] = value.strip()
    return front, body


# Supply-chain security review (P3 深化): external SKILL.md content is
# scanned for destructive / exfiltration / credential-access patterns before
# registration. Flagged skills are clamped to reviewed=False — the review
# gate then blocks activation of action skills until a human approves.
_DANGEROUS_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("shell_destructive", re.compile(r"\brm\s+-rf\b|\bdel\s+/[sq]\b", re.IGNORECASE)),
    ("remote_execution", re.compile(r"\b(curl|wget)\b[^;\n|]*\|\s*(?:ba|z|da)?sh\b", re.IGNORECASE)),
    ("eval_execution", re.compile(r"\beval\s*\(|\bexec\s*\(|new\s+Function\s*\(", re.IGNORECASE)),
    ("credential_access", re.compile(r"\.ssh/|\.aws/|id_rsa\b|\.netrc\b|secret[_-]?key\b|api[_-]?key\b", re.IGNORECASE)),
    ("reverse_shell", re.compile(r"\bnc\s+-e\b|/dev/tcp/|\bncat\s+-e\b", re.IGNORECASE)),
    ("env_harvest", re.compile(r"\bprintenv\b|\benv\b[^|\n]*\|\s*(?:curl|wget)\b", re.IGNORECASE)),
)


def scan_skill_security(*texts: str) -> list[str]:
    """Deterministic supply-chain scan; returns sorted unique flag names."""

    flags: set[str] = set()
    for text in texts:
        for flag, pattern in _DANGEROUS_PATTERNS:
            if pattern.search(text or ""):
                flags.add(flag)
    return sorted(flags)


class SkillRegistry:
    """In-memory skill registry with file-backed SKILL.md progressive loading.

    Skills are registered but only activated after explicit user action.
    Unreviewed external skills default to read-only and cannot execute.
    """

    def __init__(self, storage_dir: Path) -> None:
        self._storage_dir = Path(storage_dir)
        self._skills: dict[str, SkillRecord] = {}
        self._load_persisted()

    def _persist(self) -> None:
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            sid: record.to_payload()
            for sid, record in self._skills.items()
        }
        (self._storage_dir / "skill-registry.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
        )

    def _load_persisted(self) -> None:
        path = self._storage_dir / "skill-registry.json"
        if not path.is_file():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        for sid, data in payload.items():
            if isinstance(data, dict):
                self._skills[sid] = SkillRecord(
                    skill_id=sid,
                    kind=str(data.get("kind") or "knowledge"),
                    name=str(data.get("name") or sid),
                    description=str(data.get("description") or ""),
                    permissions=list(data.get("permissions") or []),
                    source_path=data.get("source_path"),
                    active=bool(data.get("active")),
                    reviewed=bool(data.get("reviewed")),
                    metadata=dict(data.get("metadata") or {}),
                )

    @staticmethod
    def _make_id(name: str) -> str:
        return _SAFE_NAME.sub("-", name.lower()).strip("-")[:60] or "skill"

    def register(
        self,
        *,
        skill_id: str,
        kind: str,
        name: str,
        description: str = "",
        permissions: list[str] | None = None,
        source_path: str | None = None,
        reviewed: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> SkillRecord:
        if kind not in {"tutor", "knowledge", "action"}:
            raise ValueError(f"Invalid skill kind: {kind!r}. Must be tutor, knowledge, or action.")
        record = SkillRecord(
            skill_id=skill_id,
            kind=kind,
            name=name,
            description=description,
            permissions=list(permissions or []),
            source_path=source_path,
            active=False,
            reviewed=reviewed,
            metadata=dict(metadata or {}),
        )
        self._skills[skill_id] = record
        self._persist()
        return record

    def register_from_skill_md(
        self,
        path: Path,
        *,
        kind: str = "knowledge",
        reviewed: bool = False,
    ) -> SkillRecord:
        """Register a skill from a SKILL.md file (progressive loading).

        External supply chain: the front matter + body pass through the
        deterministic security scan first; any flag clamps ``reviewed`` to
        False so the human review gate cannot be skipped by the importer.
        """

        front, body = parse_skill_md(path)
        security_flags = scan_skill_security(json.dumps(front, ensure_ascii=False), body)
        skill_id = self._make_id(front.get("name") or path.stem)
        permissions = [
            p.strip()
            for p in front.get("permissions", "").split(",")
            if p.strip()
        ]
        return self.register(
            skill_id=skill_id,
            kind=kind,
            name=front.get("name") or path.stem,
            description=front.get("description") or "",
            permissions=permissions,
            source_path=str(path),
            reviewed=reviewed and not security_flags,
            metadata={
                "front_matter": front,
                "skill_md_path": str(path),
                "security_flags": security_flags,
            },
        )

    def mark_reviewed(self, skill_id: str, *, reviewed: bool = True) -> SkillRecord:
        """Human review decision (审核) — the only path to review a skill."""

        record = self._require(skill_id)
        record.reviewed = reviewed
        self._persist()
        return record

    def record_usage(
        self,
        skill_id: str,
        *,
        applied: bool,
        workspace_id: str = "",
        session_id: str = "",
    ) -> SkillRecord:
        """Persist one usage fact (执行结果回流). Skill 使用成功 ≠ 掌握."""

        record = self._require(skill_id)
        metadata = record.metadata
        metadata["usage_count"] = int(metadata.get("usage_count") or 0) + 1
        if applied:
            metadata["applied_count"] = int(metadata.get("applied_count") or 0) + 1
        metadata["last_used_at"] = datetime.now(UTC).isoformat()
        if workspace_id:
            metadata["last_used_workspace"] = workspace_id
        if session_id:
            metadata["last_used_session"] = session_id
        metadata["last_applied"] = bool(applied)
        self._persist()
        return record

    def activate(self, skill_id: str) -> SkillRecord:
        record = self._require(skill_id)
        if not record.reviewed and record.kind == "action":
            raise ValueError(
                f"Action skill {skill_id!r} has not been reviewed by the user. "
                "Review it first before activation."
            )
        record.active = True
        record.body = self._load_body(record)
        self._persist()
        return record

    def deactivate(self, skill_id: str) -> SkillRecord:
        record = self._require(skill_id)
        record.active = False
        record.body = ""
        self._persist()
        return record

    def _load_body(self, record: SkillRecord) -> str:
        if record.source_path and Path(record.source_path).is_file():
            _front, body = parse_skill_md(Path(record.source_path))
            return body
        return record.description

    def _require(self, skill_id: str) -> SkillRecord:
        record = self._skills.get(skill_id)
        if record is None:
            raise KeyError(f"Skill not found: {skill_id!r}")
        return record

    def list_skills(self, *, kind: str | None = None, active_only: bool = False) -> list[SkillRecord]:
        return [
            record
            for record in self._skills.values()
            if (kind is None or record.kind == kind)
            and (not active_only or record.active)
        ]

    def has_permission(self, skill_id: str, permission: str) -> bool:
        record = self._require(skill_id)
        if not record.active:
            return False
        return permission in record.permissions or "*" in record.permissions

    def to_payload(self, *, include_body: bool = False) -> list[dict[str, Any]]:
        return [
            record.to_payload(include_body=include_body)
            for record in self._skills.values()
        ]
