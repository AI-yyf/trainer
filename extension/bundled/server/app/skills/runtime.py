"""P1 Skills 深化 — agent runtime skill selection + usage feedback.

The coach agent loop previously never saw the skill registry: activated
skills existed only as HTTP-managed records. This module closes the loop:

- **条件触发 (condition trigger)**: :func:`select_active_skills`
  deterministically matches ACTIVE skills against the learner message via
  SKILL.md front-matter ``trigger``/``triggers``/``keywords`` terms, with a
  description-token-overlap fallback. Skills that match nothing are never
  injected. Bodies load progressively at selection time only.
- **权限约束 (permission constraint)**: the guidance block never expands
  tool authority — the agent keeps exactly the tools the run already
  granted, and workspace write rules apply unchanged.
- **执行结果回流 (usage feedback)**: :func:`record_skill_usage` persists
  per-skill usage stats in the registry and appends a session highlight to
  memory so later turns can see which guidance the coach acted on. Skill
  使用成功 ≠ 掌握: this records usage facts only, never learner competency.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .registry import SkillRegistry, parse_skill_md

_TRIGGER_KEYS = ("triggers", "trigger", "keywords")

_TOKEN_SPLIT = re.compile(r"[\W_]+", re.UNICODE)
_TOKEN_STOPWORDS = {
    "the", "and", "for", "with", "this", "that", "from", "into", "when",
    "your", "you", "are", "how", "what", "use", "using", "about", "help",
    "please", "project", "understand", "explain",
}

MAX_SELECTED_SKILLS = 2
MAX_SKILL_BODY_CHARS = 1200
MAX_HIGHLIGHT_CHARS = 200


@dataclass(slots=True)
class SelectedSkill:
    """One skill chosen for the current turn (body progressively loaded)."""

    skill_id: str
    name: str
    kind: str
    permissions: list[str]
    body: str
    matched_terms: list[str] = field(default_factory=list)


def _front_matter_terms(record: Any) -> list[str]:
    front_matter = record.metadata.get("front_matter")
    if not isinstance(front_matter, dict):
        return []
    terms: list[str] = []
    for key in _TRIGGER_KEYS:
        raw = front_matter.get(key)
        if not raw:
            continue
        for chunk in re.split(r"[,;、\n]+", str(raw)):
            term = chunk.strip().lower()
            if term and term not in terms:
                terms.append(term)
    return terms


def _description_tokens(record: Any) -> list[str]:
    tokens: list[str] = []
    for token in _TOKEN_SPLIT.split(str(record.description or "").lower()):
        if len(token) >= 4 and token not in _TOKEN_STOPWORDS and token not in tokens:
            tokens.append(token)
    return tokens


def _load_body(record: Any) -> str:
    """Progressive loading: read SKILL.md body only when the skill is selected."""

    source_path = record.source_path
    if source_path:
        try:
            _front, body = parse_skill_md(Path(source_path))
            if body.strip():
                return body.strip()
        except OSError:
            pass
    return str(record.body or record.description or "").strip()


def select_active_skills(
    registry: SkillRegistry,
    user_message: str,
    *,
    limit: int = MAX_SELECTED_SKILLS,
) -> list[SelectedSkill]:
    """Deterministic condition-trigger matching over ACTIVE skills only."""

    message = str(user_message or "").strip().lower()
    if not message:
        return []
    message_tokens = {t for t in _TOKEN_SPLIT.split(message) if len(t) >= 4}
    scored: list[tuple[int, int, str, SelectedSkill]] = []
    for record in registry.list_skills(active_only=True):
        matched_terms: list[str] = []
        for term in _front_matter_terms(record):
            if term and term in message:
                matched_terms.append(term)
        if matched_terms:
            score = 100 + len(matched_terms)
        else:
            matched_terms = [token for token in _description_tokens(record) if token in message_tokens]
            if not matched_terms:
                continue
            score = len(matched_terms)
        reviewed_rank = 1 if record.reviewed else 0
        scored.append(
            (
                score,
                reviewed_rank,
                record.skill_id,
                SelectedSkill(
                    skill_id=record.skill_id,
                    name=str(record.name or record.skill_id),
                    kind=str(record.kind),
                    permissions=list(record.permissions),
                    body=_load_body(record),
                    matched_terms=matched_terms[:6],
                ),
            )
        )
    scored.sort(key=lambda item: (-item[0], -item[1], item[2]))
    return [item[3] for item in scored[: max(1, limit)]]


def build_skill_guidance_block(selected: list[SelectedSkill]) -> str:
    """System-prompt block for the selected skills (authority-neutral)."""

    if not selected:
        return ""
    lines = [
        "Active project skills matched this request. Follow their guidance when it "
        "is relevant; skip it when the learner's request conflicts with it.",
    ]
    for skill in selected:
        lines.append("")
        lines.append(f"### Skill: {skill.name} ({skill.kind}, id={skill.skill_id})")
        if skill.matched_terms:
            lines.append(f"Matched by: {', '.join(skill.matched_terms)}")
        body = skill.body[:MAX_SKILL_BODY_CHARS]
        if body:
            lines.append(body)
        if skill.permissions:
            lines.append(f"Declared permissions: {', '.join(skill.permissions)} (informational only).")
    lines.append("")
    lines.append(
        "Skill permissions never expand your tool authority: use only the tools "
        "already available in this run, and workspace write/read rules apply "
        "exactly as before. Cite the skill id when its guidance shapes your answer."
    )
    return "\n".join(lines)


def record_skill_usage(
    runtime: Any,
    workspace_id: str,
    session_id: str,
    selected: list[SelectedSkill],
    *,
    stop_reason: str = "",
    final_content: str = "",
) -> list[dict[str, Any]]:
    """Persist usage facts: registry stats + one memory session highlight.

    Returns per-skill usage payloads for the turn's diagnostics.
    """

    if not selected:
        return []
    registry: SkillRegistry | None = getattr(runtime, "skill_registry", None)
    content_lower = str(final_content or "").lower()
    now = datetime.now(UTC).isoformat()
    usages: list[dict[str, Any]] = []
    highlights: list[str] = []
    for skill in selected:
        applied = bool(skill.name) and skill.name.lower() in content_lower
        usage = {
            "skill_id": skill.skill_id,
            "applied": applied,
            "stop_reason": stop_reason or None,
            "workspace_id": workspace_id,
            "recorded_at": now,
        }
        usages.append(usage)
        if registry is not None:
            try:
                registry.record_usage(
                    skill.skill_id,
                    applied=applied,
                    workspace_id=workspace_id,
                    session_id=session_id,
                )
            except KeyError:
                continue
        marker = "applied" if applied else "provided"
        highlights.append(f"Skill {marker}: {skill.name} ({skill.skill_id})")
    if highlights and session_id:
        memory_service = getattr(runtime, "memory_service", None)
        add_highlight = getattr(memory_service, "add_session_highlight", None)
        if callable(add_highlight):
            try:
                add_highlight(session_id, "; ".join(highlights)[:MAX_HIGHLIGHT_CHARS])
            except (KeyError, ValueError, RuntimeError, OSError):
                pass
    return usages
