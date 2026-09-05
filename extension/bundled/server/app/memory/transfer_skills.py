"""Fail-closed transferable-skill promotion after multi-scene evidence.

A scene is a distinct project/workspace. Frontend and backend must use the
same gate. One project success is never global mastery. A second card, leftover
object, or extra scene key in the same workspace does not promote. Bare transfer
IDs without evidence do not promote.
"""

from __future__ import annotations

from typing import Any

DEFAULT_TRANSFER_SCENE_KEY = "default"
TRANSFER_STATES = frozenset({"project_only", "awaiting_second_scene", "transferable"})


def _text(value: Any) -> str:
    return str(value or "").strip()


def _casefold(value: Any) -> str:
    return _text(value).casefold()


def normalize_transfer_skill_state(value: Any) -> str | None:
    normalized = _casefold(value).replace("-", "_")
    return normalized if normalized in TRANSFER_STATES else None


def resolve_skill_scene_key(
    *,
    transfer_source_workspace_id: str = "",
    transfer_target_workspace_id: str = "",
    transfer_source_context: str = "",
    transfer_target_context: str = "",
    transfer_evidence_summary: str = "",
    scenario: str = "",
) -> str:
    source_workspace = _text(transfer_source_workspace_id)
    target_workspace = _text(transfer_target_workspace_id)
    source_context = _text(transfer_source_context)
    target_context = _text(transfer_target_context)
    evidence = _text(transfer_evidence_summary)
    if source_context and target_context and source_context.casefold() != target_context.casefold() and evidence:
        return f"transfer:{target_context.casefold()}"
    if evidence and source_workspace and target_workspace and source_workspace != target_workspace:
        return f"workspace:{target_workspace.casefold()}"
    return DEFAULT_TRANSFER_SCENE_KEY


def unique_transfer_scenes(scenes: list[dict[str, str]] | None) -> list[dict[str, str]]:
    """Collapse to one scene per workspace. Same leftover object cannot mint a second scene."""

    seen: set[str] = set()
    unique: list[dict[str, str]] = []
    for scene in scenes or []:
        workspace_id = _text(scene.get("workspace_id") or scene.get("workspaceId"))
        scene_key = _text(scene.get("scene_key") or scene.get("sceneKey")) or DEFAULT_TRANSFER_SCENE_KEY
        if not workspace_id:
            continue
        key = workspace_id.casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append({"workspace_id": workspace_id, "scene_key": scene_key})
    return unique


def unique_transfer_workspace_ids(scenes: list[dict[str, str]] | None) -> list[str]:
    return [item["workspace_id"] for item in unique_transfer_scenes(scenes)]


def resolve_transfer_skill_state(scene_count: int) -> str:
    if scene_count >= 2:
        return "transferable"
    if scene_count == 1:
        return "awaiting_second_scene"
    return "project_only"


def should_promote_transferable_skill(
    *,
    concept: str = "",
    workspace_id: str = "",
    current_scene_key: str = "",
    existing_scenes: list[dict[str, str]] | None = None,
    outcome_success: bool = False,
    transfer_source_workspace_id: str = "",
    transfer_target_workspace_id: str = "",
    transfer_source_context: str = "",
    transfer_target_context: str = "",
    transfer_evidence_summary: str = "",
    scenario: str = "",
) -> bool:
    if not outcome_success:
        return False
    cleaned_concept = _text(concept)
    cleaned_workspace = _text(workspace_id)
    if not cleaned_concept or not cleaned_workspace:
        return False
    current = {
        "workspace_id": cleaned_workspace,
        "scene_key": _text(current_scene_key)
        or resolve_skill_scene_key(
            transfer_source_workspace_id=transfer_source_workspace_id,
            transfer_target_workspace_id=transfer_target_workspace_id,
            transfer_source_context=transfer_source_context,
            transfer_target_context=transfer_target_context,
            transfer_evidence_summary=transfer_evidence_summary,
            scenario=scenario,
        ),
    }
    return len(unique_transfer_workspace_ids([*(existing_scenes or []), current])) >= 2


def describe_transfer_skill_state(
    state: str,
    concept: str = "",
    language: str | None = None,
) -> dict[str, str]:
    zh = (language or "").strip() == "zh-CN"
    named = _text(concept)
    if state == "transferable":
        return {
            "label": "可迁移" if zh else "Transferable",
            "why": (
                f"「{named}」已在多个场景得到验证。"
                if named and zh
                else f'"{named}" has evidence in more than one scene.'
                if named
                else "这项能力已在多个场景得到验证。"
                if zh
                else "This skill has evidence in more than one scene."
            ),
            "next": (
                "安排复习，或在新挑战里再应用一次。"
                if zh
                else "Schedule a review, or apply it in a new challenge."
            ),
        }
    if state == "awaiting_second_scene":
        return {
            "label": "仍属当前项目" if zh else "Project-scoped",
            "why": (
                f"「{named}」目前只在这个项目里验证过。"
                if named and zh
                else f'"{named}" is verified in this project only.'
                if named
                else "这次成功只停在当前项目。"
                if zh
                else "This success stays in the current project."
            ),
            "next": (
                "再到另一个工作区验证，才能记为可迁移能力。"
                if zh
                else "Confirm it in another workspace before treating it as transferable."
            ),
        }
    return {
        "label": "项目内证据" if zh else "Project evidence",
        "why": "这条证据留在当前项目。" if zh else "This evidence stays in the current project.",
        "next": (
            "继续在这里做；全局迁移需要第二个场景。"
            if zh
            else "Keep working here; global transfer needs a second scene."
        ),
    }


def build_transfer_skill_state_record(
    *,
    concept: str,
    scenes: list[dict[str, str]],
    language: str | None = None,
) -> dict[str, Any]:
    unique = unique_transfer_scenes(scenes)
    state = resolve_transfer_skill_state(len(unique_transfer_workspace_ids(unique)))
    copy = describe_transfer_skill_state(state, concept, language)
    return {
        "concept": _text(concept),
        "state": state,
        "scene_count": len(unique),
        "workspace_ids": list(dict.fromkeys(item["workspace_id"] for item in unique)),
        "scene_keys": list(dict.fromkeys(item["scene_key"] for item in unique)),
        "why": copy["why"],
        "next": copy["next"],
    }


def normalize_transfer_skill_state_record(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    state = normalize_transfer_skill_state(value.get("state"))
    concept = _text(value.get("concept"))
    if not state or not concept:
        return None
    scene_count = value.get("scene_count", value.get("sceneCount"))
    workspace_ids = value.get("workspace_ids", value.get("workspaceIds"))
    scene_keys = value.get("scene_keys", value.get("sceneKeys"))
    return {
        "concept": concept,
        "state": state,
        "scene_count": int(scene_count) if isinstance(scene_count, int) and scene_count >= 0 else 0,
        "workspace_ids": [item for item in workspace_ids if str(item).strip()]
        if isinstance(workspace_ids, list)
        else [],
        "scene_keys": [item for item in scene_keys if str(item).strip()] if isinstance(scene_keys, list) else [],
        "why": _text(value.get("why")),
        "next": _text(value.get("next")),
    }


def apply_transfer_skill_to_coach_orientation(
    orientation: dict[str, Any],
    transfer: dict[str, Any] | None,
) -> dict[str, Any]:
    if not transfer or _text(orientation.get("state")) != "ready":
        return orientation
    why = _text(transfer.get("why"))
    nxt = _text(transfer.get("next"))
    state = _text(transfer.get("state"))
    object_kind = _text(orientation.get("object_kind") or orientation.get("objectKind"))
    advanced_key = "advanced_where" if "advanced_where" in orientation else "advancedWhere"
    next_key = "next_step" if "next_step" in orientation else "nextStep"
    existing_advanced = _text(orientation.get(advanced_key))
    advanced = " · ".join(part for part in (existing_advanced, why) if part)
    updated = dict(orientation)
    if state == "transferable" and object_kind in {"conversation", "plan"}:
        updated[next_key] = nxt or updated.get(next_key)
        updated[advanced_key] = advanced
        return updated
    if state in {"awaiting_second_scene", "transferable"}:
        updated[advanced_key] = advanced
    return updated
