"""Fail-closed workspace recovery for plan, provider last-test, and streams.

These records live on structured workspace memory — the same DB path as
training reliability, coach orientation, and transfer state. Incomplete
records are never treated as success. API keys are never stored.
"""

from __future__ import annotations

from typing import Any

from .plan_persist_chrome import (
    PLAN_RUNTIME_KEY,
    STREAMING_PHASES,
    TRAINING_CHROME_KEY,
    _recovered_overlay_empty_step,
    _revision,
    _text,
    formal_plan_is_live_runtime_identity,
    leftover_formal_plan_is_live_for_fill,
    live_plan_overlay_fields,
    normalize_plan_runtime_recovery,
    strip_secrets,
    utc_now_iso,
)
from .snapshot_and_overlay import (
    live_runtime_stage_id,
)


def coach_focus_runtime_from_snapshot(snapshot: Any | None) -> dict[str, Any]:
    """Read recovered plan runtime from a workbench snapshot when present."""

    if snapshot is None:
        return {}
    memory = getattr(snapshot, "memory", None)
    workspace = getattr(memory, "workspace", None) if memory is not None else None
    workspace = workspace if isinstance(workspace, dict) else {}
    workspace_id = _text(
        getattr(snapshot, "workspace_id", "")
        or workspace.get("workspace_id")
        or workspace.get("workspaceId")
    )
    recovered = select_plan_runtime_for_scope(
        workspace.get(PLAN_RUNTIME_KEY) or workspace.get("latestPlanRuntime"),
        workspace_id,
    )
    if recovered:
        return recovered
    status = getattr(snapshot, "plan_runtime_status", None)
    if not isinstance(status, dict):
        status = workspace.get("plan_runtime_status") if isinstance(workspace.get("plan_runtime_status"), dict) else None
    if isinstance(status, dict):
        step = _text(status.get("current_step") or status.get("currentStep"))
        if step or status.get("recovered") is True:
            return {
                "current_step": step,
                "plan_id": _text(status.get("plan_id") or status.get("planId")),
                "why_now": _text(status.get("why_now") or status.get("whyNow")),
                "blocked_reason": _text(status.get("blocked_reason") or status.get("blockedReason")),
            }
    return {}


def apply_live_training_mint_to_card(
    card: Any,
    *,
    anchors: dict[str, str],
    leftover_labels: set[str],
    recovered_step: str = "",
) -> Any:
    """Keep minted card why/skill/title off leftover formal labels."""

    leftover = {label for label in leftover_labels if _text(label)}
    if card is None or not leftover:
        return card
    updates: dict[str, str] = {}
    why = _text(getattr(card, "why_now", ""))
    if why in leftover:
        updates["why_now"] = _text(anchors.get("why_now"))
    skill = _text(getattr(card, "target_skill", ""))
    if skill in leftover:
        updates["target_skill"] = _text(anchors.get("target_skill"))
    focus = _text(getattr(card, "focus_area", ""))
    if focus in leftover:
        updates["focus_area"] = _text(anchors.get("focus_area"))
    title = _text(getattr(card, "title", ""))
    leftover_titles = tuple(leftover)
    titled_from_leftover = title in leftover or any(
        title
        in {
            f"Practice: {label}",
            f"Flash: {label}",
            f"练习：{label}",
            f"闪记：{label}",
        }
        for label in leftover_titles
    )
    if titled_from_leftover:
        replacement = _text(recovered_step) or _text(anchors.get("focus_area"))
        updates["title"] = "" if replacement in leftover else replacement
    if not updates:
        return card
    copier = getattr(card, "model_copy", None)
    if callable(copier):
        return copier(update=updates)
    for key, value in updates.items():
        setattr(card, key, value)
    return card


def _without_leftover_formal_identity(record: dict[str, Any], plan: Any | None) -> dict[str, Any]:
    cleaned = dict(record)
    formal_id = _text(getattr(plan, "id", "") or getattr(plan, "plan_id", "") if plan is not None else "")
    if formal_id and _text(cleaned.get("plan_id") or cleaned.get("planId")) == formal_id:
        cleaned["plan_id"] = ""
        cleaned.pop("planId", None)
    if plan is None:
        return cleaned
    for field in ("next_why_now", "next_blocked_reason"):
        formal = _text(getattr(plan, field, ""))
        if formal and _text(cleaned.get(field)) == formal:
            cleaned[field] = ""
    formal_verify = _structured_string_list(getattr(plan, "next_verify_method", []) or [])
    carried_verify = _structured_string_list(cleaned.get("next_verify_method") or [])
    if formal_verify and carried_verify == formal_verify:
        cleaned["next_verify_method"] = []
    return cleaned


def _runtime_for_formal_plan_persist(
    *,
    plan: Any | None,
    runtime: dict[str, Any],
    existing: dict[str, Any] | None,
) -> tuple[Any | None, dict[str, Any], dict[str, Any] | None]:
    """Do not let leftover formal mutate/freeze rewrite recovered current_step."""

    existing = existing if isinstance(existing, dict) else None
    existing_step = _text((existing or {}).get("current_step"))
    existing_plan_id = _text((existing or {}).get("plan_id"))
    if formal_plan_is_live_runtime_identity(
        plan=plan,
        runtime=existing or runtime,
        existing=existing,
        current_step=existing_step or _text(runtime.get("current_step")),
    ):
        return plan, runtime, existing
    if plan is not None and not existing_step and not existing_plan_id:
        return plan, runtime, existing
    plan_step = _text(getattr(plan, "current_step", "") if plan is not None else "")
    runtime_step = _text(runtime.get("current_step"))
    cleaned_existing = _without_leftover_formal_identity(existing, plan) if existing else existing
    if (
        existing_step
        and plan_step
        and runtime_step == plan_step
        and runtime_step != existing_step
    ):
        return None, _without_leftover_formal_identity(existing or {}, plan), cleaned_existing
    return None, _without_leftover_formal_identity(runtime, plan), cleaned_existing


def build_plan_runtime_recovery(
    *,
    plan: Any | None,
    plan_runtime: dict[str, Any] | None,
    existing: dict[str, Any] | None = None,
    evidence_binding: str = "",
    request_id: str = "",
    workspace_id: str = "",
    replace_evidence_binding: bool = False,
) -> dict[str, Any] | None:
    runtime = plan_runtime if isinstance(plan_runtime, dict) else {}
    plan, runtime, existing = _runtime_for_formal_plan_persist(
        plan=plan,
        runtime=runtime,
        existing=existing,
    )
    leftover_live = leftover_formal_plan_is_live_for_fill(
        plan=plan,
        runtime=runtime,
        existing=existing if isinstance(existing, dict) else {},
    )
    if plan is not None and not leftover_live:
        plan_fields = {
            "current_step": "",
            "why_now": "",
            "verify_method": [],
            "blocked_reason": "",
            "next_after_current": "",
        }
    else:
        plan_fields = {
            "current_step": _text(getattr(plan, "current_step", "")),
            "why_now": _text(getattr(plan, "why_now", "")),
            "verify_method": list(getattr(plan, "verify_method", []) or []),
            "blocked_reason": _text(getattr(plan, "blocked_reason", "")),
            "next_after_current": _text(getattr(plan, "next_after_current", "")),
        }
    overlaid = overlay_plan_runtime_display_facts(
        plan_fields=plan_fields,
        recovered=runtime if _text(runtime.get("current_step")) else None,
    )
    payload = {
        "revision": _revision((existing or {}).get("revision"), 0) + 1,
        "workspace_id": workspace_id or _text((existing or {}).get("workspace_id")),
        "request_id": request_id or _text((existing or {}).get("request_id")),
        "plan_id": live_runtime_plan_id(
            plan=plan,
            runtime=runtime,
            existing=existing,
            current_step=overlaid["current_step"],
        )
        or None,
        "current_stage_id": live_runtime_stage_id(
            plan=plan,
            runtime=runtime,
            existing=existing,
            current_step=overlaid["current_step"],
        )
        or None,
        "current_step": overlaid["current_step"],
        "frozen": live_runtime_frozen(
            plan=plan,
            runtime=runtime,
            existing=existing,
            current_step=overlaid["current_step"],
        ),
        "blocked_reason": overlaid["blocked_reason"],
        "why_now": overlaid["why_now"],
        "verify_method": list(overlaid["verify_method"]),
        "next_after_current": overlaid["next_after_current"],
        "next_why_now": live_runtime_next_text(
            field="next_why_now",
            plan=plan,
            runtime=runtime,
            existing=existing,
            current_step=overlaid["current_step"],
        ),
        "next_blocked_reason": live_runtime_next_text(
            field="next_blocked_reason",
            plan=plan,
            runtime=runtime,
            existing=existing,
            current_step=overlaid["current_step"],
        ),
        "next_verify_method": live_runtime_next_verify_method(
            plan=plan,
            runtime=runtime,
            existing=existing,
            current_step=overlaid["current_step"],
        ),
        "evidence_binding": _text(evidence_binding)
        if replace_evidence_binding
        else (_text(evidence_binding) or _text((existing or {}).get("evidence_binding"))),
        "selected_card_id": _text(
            runtime.get("selected_card_id")
            or runtime.get("selectedCardId")
            or (existing or {}).get("selected_card_id")
            or (existing or {}).get("selectedCardId")
        )
        or None,
        "resume_state": _text(runtime.get("resume_state") or (existing or {}).get("resume_state"))
        or "interrupted",
        "updated_at": utc_now_iso(),
    }
    normalized = normalize_plan_runtime_recovery(payload)
    if normalized is None:
        return None
    previous = normalize_plan_runtime_recovery(existing)
    if previous and _plan_runtime_identity(previous) == _plan_runtime_identity(normalized):
        return previous
    return normalized


def bind_explicit_generated_plan_runtime(
    *,
    plan: Any,
    existing: dict[str, Any] | None = None,
    workspace_id: str = "",
    evidence_binding: str = "",
    request_id: str = "",
) -> dict[str, Any] | None:
    """Explicit generate binds THIS plan as live. Do not text-match leftover into it."""

    if plan is None:
        return None
    existing = existing if isinstance(existing, dict) else {}
    formal = _text(getattr(plan, "id", "") or getattr(plan, "plan_id", ""))
    if not formal:
        return None
    verify_raw = getattr(plan, "verify_method", None) or []
    verify_method = (
        [str(item).strip() for item in verify_raw if str(item).strip()]
        if isinstance(verify_raw, list)
        else []
    )
    next_verify_raw = getattr(plan, "next_verify_method", None) or []
    payload = {
        "revision": _revision(existing.get("revision"), 0) + 1,
        "workspace_id": workspace_id or _text(existing.get("workspace_id")),
        "request_id": request_id or _text(existing.get("request_id")) or formal,
        "plan_id": formal,
        "current_stage_id": _text(getattr(plan, "current_stage_id", "")),
        "current_step": _text(getattr(plan, "current_step", "")),
        "frozen": bool(getattr(plan, "frozen", False)),
        "blocked_reason": _text(getattr(plan, "blocked_reason", "")),
        "why_now": _text(getattr(plan, "why_now", "")),
        "verify_method": verify_method,
        "next_after_current": _text(getattr(plan, "next_after_current", "")),
        "next_why_now": _text(getattr(plan, "next_why_now", "")),
        "next_blocked_reason": _text(getattr(plan, "next_blocked_reason", "")),
        "next_verify_method": _structured_string_list(next_verify_raw),
        "evidence_binding": _text(evidence_binding) or _text(existing.get("evidence_binding")),
        "resume_state": _text(existing.get("resume_state")) or "in_progress",
        "updated_at": utc_now_iso(),
    }
    return normalize_plan_runtime_recovery(payload)


def _plan_runtime_identity(record: dict[str, Any]) -> tuple[Any, ...]:
    return (
        record.get("plan_id"),
        record.get("selected_card_id"),
        record.get("current_stage_id"),
        record.get("current_step"),
        record.get("frozen"),
        record.get("blocked_reason"),
        record.get("why_now"),
        tuple(record.get("verify_method") or []),
        record.get("next_after_current"),
        record.get("next_why_now"),
        record.get("next_blocked_reason"),
        tuple(record.get("next_verify_method") or []),
        record.get("evidence_binding"),
        record.get("resume_state") or "interrupted",
        record.get("request_id"),
    )


def normalize_provider_capability_recovery(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    cleaned = strip_secrets(value)
    provider_name = _text(cleaned.get("provider_name") or cleaned.get("providerName"))
    base_url = _text(cleaned.get("base_url") or cleaned.get("baseUrl"))
    model = _text(cleaned.get("model"))
    checked_at = _text(cleaned.get("checked_at") or cleaned.get("checkedAt"))
    if not provider_name or not base_url or not model or not checked_at:
        return None
    evidence_raw = cleaned.get("capability_evidence") or cleaned.get("capabilityEvidence") or []
    evidence: list[dict[str, Any]] = []
    if isinstance(evidence_raw, list):
        for item in evidence_raw:
            if not isinstance(item, dict):
                continue
            name = _text(item.get("name"))
            state = _text(item.get("state"))
            if not name or not state:
                continue
            evidence.append(
                {
                    "name": name,
                    "declared": item.get("declared") is True,
                    "observed": item.get("observed") if isinstance(item.get("observed"), bool) else None,
                    "state": state,
                }
            )

    def verified_ready(ready_keys: tuple[str, ...], status_keys: tuple[str, ...], evidence_name: str) -> bool:
        if cleaned.get("ok") is not True:
            return False
        ready = any(cleaned.get(key) is True for key in ready_keys)
        status = any(_text(cleaned.get(key)) == "verified" for key in status_keys)
        match = next((item for item in evidence if item["name"].casefold() == evidence_name), None)
        return ready and status and match is not None and match["state"] == "verified" and match["observed"] is True

    return {
        "revision": _revision(cleaned.get("revision")),
        "workspace_id": _text(cleaned.get("workspace_id") or cleaned.get("workspaceId")) or None,
        "provider_profile_id": _text(
            cleaned.get("provider_profile_id")
            or cleaned.get("providerProfileId")
            or cleaned.get("profile_id")
            or cleaned.get("profileId")
        )
        or None,
        "provider_name": provider_name,
        "base_url": base_url,
        "model": model,
        "protocol": _text(cleaned.get("protocol")) or None,
        "ok": cleaned.get("ok") is True,
        "checked_at": checked_at,
        "tools_ready": verified_ready(("tools_ready", "toolsReady"), ("tool_probe_status", "toolProbeStatus"), "tools"),
        "tool_probe_status": _text(cleaned.get("tool_probe_status") or cleaned.get("toolProbeStatus"))
        or "unverified",
        "streaming_ready": verified_ready(
            ("streaming_ready", "streamingReady"),
            ("stream_probe_status", "streamProbeStatus"),
            "streaming",
        ),
        "stream_probe_status": _text(cleaned.get("stream_probe_status") or cleaned.get("streamProbeStatus"))
        or "unverified",
        "vision_ready": verified_ready(
            ("vision_ready", "visionReady"),
            ("vision_probe_status", "visionProbeStatus"),
            "vision",
        ),
        "vision_probe_status": _text(cleaned.get("vision_probe_status") or cleaned.get("visionProbeStatus"))
        or "unverified",
        "thinking_ready": verified_ready(
            ("thinking_ready", "thinkingReady"),
            ("thinking_probe_status", "thinkingProbeStatus"),
            "thinking",
        ),
        "thinking_probe_status": _text(cleaned.get("thinking_probe_status") or cleaned.get("thinkingProbeStatus"))
        or "unverified",
        "capability_evidence": evidence,
    }


def normalize_streaming_checkpoint(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    request_id = _text(value.get("request_id") or value.get("requestId") or value.get("stream_id"))
    phase = _text(value.get("phase")).replace("-", "_").casefold()
    if not request_id or phase not in STREAMING_PHASES:
        return None
    return {
        "revision": _revision(value.get("revision")),
        "workspace_id": _text(value.get("workspace_id") or value.get("workspaceId")) or None,
        "provider_profile_id": _text(
            value.get("provider_profile_id")
            or value.get("providerProfileId")
            or value.get("profile_id")
            or value.get("profileId")
        )
        or None,
        "provider_name": _text(value.get("provider_name") or value.get("providerName")) or None,
        "base_url": _text(value.get("base_url") or value.get("baseUrl")) or None,
        "model": _text(value.get("model")) or None,
        "request_id": request_id,
        "checkpoint_id": _text(value.get("checkpoint_id") or value.get("checkpointId")) or None,
        "session_id": _text(value.get("session_id") or value.get("sessionId")) or None,
        "stream_message_id": _text(value.get("stream_message_id") or value.get("streamMessageId")) or None,
        "phase": phase,
        "stop_reason": _text(value.get("stop_reason") or value.get("stopReason")) or None,
        "error": _text(value.get("error")) or None,
        "updated_at": _text(value.get("updated_at") or value.get("updatedAt")) or None,
    }


def build_streaming_checkpoint(
    *,
    request_id: str,
    phase: str,
    existing: dict[str, Any] | None = None,
    checkpoint_id: str = "",
    session_id: str = "",
    stream_message_id: str = "",
    stop_reason: str = "",
    error: str = "",
    workspace_id: str = "",
    provider_profile_id: str = "",
    provider_name: str = "",
    base_url: str = "",
    model: str = "",
) -> dict[str, Any] | None:
    mapped_phase = phase.replace("-", "_").casefold()
    if mapped_phase == "failed":
        mapped_phase = "interrupted"
    if mapped_phase == "in_progress":
        mapped_phase = "streaming"
    payload = {
        "revision": _revision((existing or {}).get("revision"), 0) + 1,
        "workspace_id": workspace_id or _text((existing or {}).get("workspace_id")),
        "provider_profile_id": provider_profile_id or _text((existing or {}).get("provider_profile_id")),
        "provider_name": provider_name or _text((existing or {}).get("provider_name")),
        "base_url": base_url or _text((existing or {}).get("base_url")),
        "model": model or _text((existing or {}).get("model")),
        "request_id": request_id,
        "checkpoint_id": checkpoint_id or _text((existing or {}).get("checkpoint_id")),
        "session_id": session_id or _text((existing or {}).get("session_id")),
        "stream_message_id": stream_message_id or _text((existing or {}).get("stream_message_id")),
        "phase": mapped_phase,
        "stop_reason": stop_reason or _text((existing or {}).get("stop_reason")),
        "error": error,
        "updated_at": utc_now_iso(),
    }
    return normalize_streaming_checkpoint(payload)


def recover_streaming_checkpoint_after_restart(value: Any) -> dict[str, Any] | None:
    record = normalize_streaming_checkpoint(value)
    if record is None:
        return None
    if record["phase"] != "streaming":
        return record
    record = dict(record)
    record["phase"] = "interrupted"
    record["stop_reason"] = record.get("stop_reason") or "interrupted"
    record["revision"] = int(record.get("revision") or 1) + 1
    record["updated_at"] = utc_now_iso()
    return record


def is_interrupted_streaming_checkpoint(value: Any) -> bool:
    record = normalize_streaming_checkpoint(value) or recover_streaming_checkpoint_after_restart(value)
    return bool(record and record.get("phase") in {"interrupted", "cancelled"})


def _same_identity(left: Any, right: Any) -> bool:
    first = _text(left)
    second = _text(right)
    return bool(first) and first.casefold() == second.casefold()


def stamp_produced_workspace_record(record: Any, workspace_id: str) -> Any:
    """Stamp a produced plan/task with the workspace that created it. Does not invent one."""

    if record is None:
        return None
    scope = _text(workspace_id)
    if not scope:
        return record
    existing = _text(getattr(record, "workspace_id", "") or getattr(record, "workspaceId", ""))
    if existing and existing != scope:
        return record
    if hasattr(record, "workspace_id"):
        record.workspace_id = existing or scope
    return record


def is_current_for_workspace(record: dict[str, Any] | None, workspace_id: str) -> bool:
    record_workspace_id = _text((record or {}).get("workspace_id"))
    scope_workspace_id = _text(workspace_id)
    return bool(record_workspace_id) and bool(scope_workspace_id) and record_workspace_id == scope_workspace_id


def is_current_for_provider(
    record: dict[str, Any] | None,
    *,
    workspace_id: str,
    provider_profile_id: str = "",
    provider_name: str = "",
    base_url: str = "",
    model: str = "",
) -> bool:
    if not is_current_for_workspace(record, workspace_id):
        return False
    record_profile_id = _text((record or {}).get("provider_profile_id"))
    scope_profile_id = _text(provider_profile_id)
    if scope_profile_id:
        return bool(record_profile_id) and record_profile_id == scope_profile_id
    if _text(provider_name) or _text(base_url) or _text(model):
        return (
            not record_profile_id
            and _same_identity((record or {}).get("provider_name"), provider_name)
            and _same_identity((record or {}).get("base_url"), base_url)
            and _same_identity((record or {}).get("model"), model)
        )
    return True


def select_plan_runtime_for_scope(value: Any, workspace_id: str) -> dict[str, Any] | None:
    record = normalize_plan_runtime_recovery(value)
    return record if record and is_current_for_workspace(record, workspace_id) else None


def normalize_training_chrome(value: Any) -> dict[str, Any] | None:
    """Incomplete Training chrome is not success. Unscoped title is not current truth."""

    if not isinstance(value, dict):
        return None
    workspace_id = _text(value.get("workspace_id") or value.get("workspaceId"))
    title = _text(
        value.get("selected_card_title")
        or value.get("selectedCardTitle")
        or value.get("card_title")
        or value.get("cardTitle")
        or value.get("title")
    )
    if not workspace_id and not title:
        return None
    return {
        "workspace_id": workspace_id or None,
        "selected_card_title": title or None,
        "card_title": _text(value.get("card_title") or value.get("cardTitle")) or None,
        "title": _text(value.get("title")) or None,
    }


def select_training_chrome_for_scope(value: Any, workspace_id: str) -> dict[str, Any] | None:
    record = normalize_training_chrome(value)
    return record if record and is_current_for_workspace(record, workspace_id) else None


def select_training_record_for_scope(value: Any, workspace_id: str) -> dict[str, Any] | None:
    """Consume-time fail-closed for stamped Training handoff / next hop."""

    if not isinstance(value, dict):
        return None
    return value if is_current_for_workspace(value, workspace_id) else None


def training_record_matches_workspace(value: Any, workspace_id: str) -> bool:
    """Stamped mismatch is not current. Unscoped payload may still belong to this store."""

    if not isinstance(value, dict):
        return False
    stamped = _text(value.get("workspace_id") or value.get("workspaceId"))
    if not stamped:
        return True
    scope = _text(workspace_id)
    if not scope:
        return True
    return stamped == scope


def apply_training_chrome_scope(workspace: dict[str, Any] | None, workspace_id: str) -> dict[str, Any]:
    """Drop recovered Training chrome that does not belong to this workspace."""

    payload = dict(workspace) if isinstance(workspace, dict) else {}
    handoff = payload.get("latest_training_handoff") or payload.get("latestTrainingHandoff")
    next_hop = payload.get("latest_training_next_hop") or payload.get("latestTrainingNextHop")
    chrome_source = payload.get(TRAINING_CHROME_KEY) or payload.get("latestTrainingChrome")
    handoff_record = handoff if isinstance(handoff, dict) else {}
    hop_record = next_hop if isinstance(next_hop, dict) else {}
    if not isinstance(chrome_source, dict):
        chrome_source = {
            "workspace_id": (
                _text(handoff_record.get("workspace_id") or handoff_record.get("workspaceId"))
                or _text(hop_record.get("workspace_id") or hop_record.get("workspaceId"))
            ),
            "selected_card_title": payload.get("selected_card_title") or payload.get("selectedCardTitle"),
            "card_title": handoff_record.get("card_title") or handoff_record.get("cardTitle"),
            "title": hop_record.get("title"),
        }
    chrome = select_training_chrome_for_scope(chrome_source, workspace_id)
    scoped_handoff = (
        handoff_record
        if handoff_record and training_record_matches_workspace(handoff_record, workspace_id)
        else None
    )
    scoped_hop = (
        hop_record if hop_record and training_record_matches_workspace(hop_record, workspace_id) else None
    )
    title = _text((chrome or {}).get("selected_card_title"))
    if not title and training_record_matches_workspace(chrome_source, workspace_id):
        title = _text(chrome_source.get("selected_card_title") or payload.get("selected_card_title"))
    payload[TRAINING_CHROME_KEY] = chrome
    payload["latest_training_handoff"] = scoped_handoff or None
    payload["latest_training_next_hop"] = scoped_hop or None
    payload["selected_card_title"] = title
    return payload


def evidence_item_workspace_id(item: Any) -> str:
    if item is None:
        return ""
    if isinstance(item, dict):
        return _text(item.get("workspace_id") or item.get("workspaceId"))
    return _text(getattr(item, "workspace_id", "") or getattr(item, "workspaceId", ""))


def scope_evidence_items_to_workspace(items: list[Any], workspace_id: str) -> list[Any]:
    """Pending/history items from another workspace are not live here."""

    return [
        item
        for item in items
        if is_current_for_workspace({"workspace_id": evidence_item_workspace_id(item)}, workspace_id)
    ]


def _plan_identity_fields(plan: Any) -> dict[str, str]:
    if plan is None:
        return {}
    if isinstance(plan, dict):
        return {
            "workspace_id": _text(plan.get("workspace_id") or plan.get("workspaceId")),
            "id": _text(plan.get("id") or plan.get("plan_id") or plan.get("planId")),
            "title": _text(plan.get("title")),
            "summary": _text(plan.get("summary") or plan.get("objective")),
            "current_step": _text(plan.get("current_step") or plan.get("currentStep")),
        }
    return {
        "workspace_id": _text(getattr(plan, "workspace_id", "") or getattr(plan, "workspaceId", "")),
        "id": _text(getattr(plan, "id", "") or getattr(plan, "plan_id", "")),
        "title": _text(getattr(plan, "title", "")),
        "summary": _text(getattr(plan, "summary", "") or getattr(plan, "objective", "")),
        "current_step": _text(getattr(plan, "current_step", "")),
    }


def normalize_formal_plan_identity(value: Any) -> dict[str, str] | None:
    """Incomplete leftover plan identity is not current truth."""

    fields = _plan_identity_fields(value)
    if not fields:
        return None
    if not any(fields[key] for key in ("workspace_id", "id", "title", "summary", "current_step")):
        return None
    return fields


def select_resources_for_scope(value: Any, workspace_id: str) -> list[Any]:
    if not isinstance(value, list):
        return []
    scoped: list[Any] = []
    for item in value:
        record = item if isinstance(item, dict) else {
            "workspace_id": getattr(item, "workspace_id", "") if item is not None else "",
        }
        if training_record_matches_workspace(record, workspace_id):
            scoped.append(item)
    return scoped


def select_plan_runtime_for_pressure(value: Any, workspace_id: str) -> dict[str, Any] | None:
    """Scoped runtime usable as pressure only — never as a generated plan.

    A plan_id-only or otherwise incomplete record is stale: it must not invent
    urgency, a live plan, or a successful generate. Blocked reason or current
    step is required before the record can shrink/hold the next move.
    """

    record = select_plan_runtime_for_scope(value, workspace_id)
    if record is None:
        return None
    if not (_text(record.get("blocked_reason")) or _text(record.get("current_step"))):
        return None
    return record


def overlay_plan_runtime_display_facts(
    *,
    plan_fields: dict[str, Any],
    recovered: dict[str, Any] | None,
    plan: Any | None = None,
) -> dict[str, Any]:
    """Prefer recovered/advanced runtime what/why/next. Never invent a plan."""

    runtime = recovered if isinstance(recovered, dict) else {}
    if plan is not None:
        gated = live_plan_overlay_fields(plan=plan, runtime=runtime, existing=runtime)
        if leftover_formal_plan_is_live_for_fill(plan=plan, runtime=runtime, existing=runtime):
            return {
                "current_step": gated["current_step"] or _text(plan_fields.get("current_step")),
                "why_now": gated["why_now"] or _text(plan_fields.get("why_now")),
                "verify_method": list(gated["verify_method"])
                or [
                    str(item).strip()
                    for item in (plan_fields.get("verify_method") or [])
                    if str(item).strip()
                ],
                "blocked_reason": gated["blocked_reason"] or _text(plan_fields.get("blocked_reason")),
                "next_after_current": gated["next_after_current"]
                or _text(plan_fields.get("next_after_current")),
            }
        return gated
    runtime_step = _text(runtime.get("current_step"))
    if recovered is None or not runtime_step:
        return {
            "current_step": _text(plan_fields.get("current_step")),
            "why_now": _text(plan_fields.get("why_now")),
            "verify_method": [
                item for item in (plan_fields.get("verify_method") or []) if str(item).strip()
            ],
            "blocked_reason": _text(plan_fields.get("blocked_reason")),
            "next_after_current": _text(plan_fields.get("next_after_current")),
        }
    return {
        "current_step": runtime_step,
        "why_now": _text(recovered.get("why_now")),
        "verify_method": [item for item in (recovered.get("verify_method") or []) if str(item).strip()],
        "blocked_reason": _text(recovered.get("blocked_reason")),
        "next_after_current": _text(recovered.get("next_after_current")),
    }


def live_runtime_plan_id(
    *,
    plan: Any | None = None,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    current_step: str = "",
) -> str:
    """Plan id is live when already carried, or on first persist of a matching live plan."""

    runtime = runtime if isinstance(runtime, dict) else {}
    existing = existing if isinstance(existing, dict) else {}
    carried = _text(runtime.get("plan_id") or existing.get("plan_id"))
    formal = _text(
        getattr(plan, "id", "") or getattr(plan, "plan_id", "") if plan is not None else ""
    )
    runtime_step = _text(current_step) or _text(runtime.get("current_step"))
    existing_step = _text(existing.get("current_step"))
    existing_id = _text(existing.get("plan_id"))
    if not formal:
        return carried
    if not runtime_step:
        if runtime or existing:
            return carried if carried and carried != formal else ""
        return carried or formal
    still_on_plan = bool(
        live_runtime_stage_id(
            plan=plan,
            runtime=runtime,
            existing=existing,
            current_step=runtime_step,
        )
        or runtime_step == _text(getattr(plan, "current_step", ""))
    )
    if still_on_plan:
        if carried:
            return carried
        # Recovered overlay already has a step/id: do not invent leftover plan_id from text match.
        if existing_step or existing_id:
            return ""
        return formal
    if carried and carried != formal:
        return carried
    return ""


def _runtime_still_on_formal_plan(
    *,
    plan: Any | None,
    runtime: dict[str, Any],
    existing: dict[str, Any],
    current_step: str,
) -> bool:
    runtime_step = _text(current_step) or _text(runtime.get("current_step"))
    if not runtime_step:
        return not bool(runtime or existing)
    return bool(
        live_runtime_stage_id(
            plan=plan,
            runtime=runtime,
            existing=existing,
            current_step=runtime_step,
        )
        or runtime_step == _text(getattr(plan, "current_step", "") if plan is not None else "")
    )


def live_runtime_next_text(
    *,
    field: str,
    plan: Any | None = None,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    current_step: str = "",
) -> str:
    """Formal next-* text is live only while recovered runtime still names that plan step."""

    runtime = runtime if isinstance(runtime, dict) else {}
    existing = existing if isinstance(existing, dict) else {}
    aliases = {
        "next_why_now": (
            "next_why_now",
            "nextWhyNow",
            "why_after_current",
            "whyAfterCurrent",
        ),
        "next_blocked_reason": (
            "next_blocked_reason",
            "nextBlockedReason",
            "blocked_after_current",
            "blockedAfterCurrent",
        ),
    }.get(field, (field,))
    carried = ""
    found = False
    for source in (runtime, existing):
        for alias in aliases:
            if alias in source:
                carried = _text(source.get(alias))
                found = True
                break
        if found:
            break
    formal = _text(getattr(plan, field, "") if plan is not None else "")
    if _runtime_still_on_formal_plan(
        plan=plan,
        runtime=runtime,
        existing=existing,
        current_step=current_step,
    ):
        return carried or formal
    if carried and carried != formal:
        return carried
    return ""


def live_runtime_next_verify_method(
    *,
    plan: Any | None = None,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    current_step: str = "",
) -> list[str]:
    """Formal next verify list is live only while recovered runtime still names that plan step."""

    runtime = runtime if isinstance(runtime, dict) else {}
    existing = existing if isinstance(existing, dict) else {}
    carried: list[str] = []
    if "next_verify_method" in runtime or "nextVerifyMethod" in runtime:
        carried = _structured_string_list(
            runtime.get("next_verify_method") or runtime.get("nextVerifyMethod")
        )
    elif "next_verify_method" in existing or "nextVerifyMethod" in existing:
        carried = _structured_string_list(
            existing.get("next_verify_method") or existing.get("nextVerifyMethod")
        )
    formal = _structured_string_list(
        getattr(plan, "next_verify_method", []) if plan is not None else []
    )
    if _runtime_still_on_formal_plan(
        plan=plan,
        runtime=runtime,
        existing=existing,
        current_step=current_step,
    ):
        return carried or formal
    if carried and carried != formal:
        return carried
    return []


def live_runtime_frozen(
    *,
    plan: Any | None = None,
    runtime: dict[str, Any] | None = None,
    existing: dict[str, Any] | None = None,
    current_step: str = "",
) -> bool:
    """Formal frozen is live only while recovered runtime still names that plan step."""

    runtime = runtime if isinstance(runtime, dict) else {}
    existing = existing if isinstance(existing, dict) else {}
    formal = bool(getattr(plan, "frozen", False)) if plan is not None else False
    runtime_step = _text(current_step) or _text(runtime.get("current_step"))
    if _recovered_overlay_empty_step(runtime, existing, runtime_step):
        return False
    still_on_plan = bool(
        not runtime_step
        or live_runtime_stage_id(
            plan=plan,
            runtime=runtime,
            existing=existing,
            current_step=runtime_step,
        )
        or runtime_step == _text(getattr(plan, "current_step", "") if plan is not None else "")
    )
    if still_on_plan:
        if "frozen" in runtime:
            return bool(runtime.get("frozen"))
        if "frozen" in existing:
            return bool(existing.get("frozen"))
        return formal
    if "frozen" in runtime:
        return bool(runtime.get("frozen"))
    return False


def overlay_plan_runtime_current_stage(
    *,
    plan_stage: dict[str, Any] | None,
    plan_current_step: str = "",
    recovered: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Keep the plan record. Do not claim its old stage is live after runtime advances."""

    runtime_step = _text((recovered or {}).get("current_step"))
    if recovered is None or not runtime_step:
        return plan_stage
    stage = plan_stage if isinstance(plan_stage, dict) else {}
    stage_title = _text(stage.get("title"))
    stage_goal = _text(stage.get("goal") or stage.get("objective"))
    if runtime_step in {_text(plan_current_step), stage_title, stage_goal}:
        return plan_stage
    return None


def evidence_item_concepts(item: Any) -> list[str]:
    raw = getattr(item, "concepts", None)
    if raw is None and isinstance(item, dict):
        raw = item.get("concepts")
    return [_text(concept) for concept in (raw or []) if _text(concept)]


def evidence_bound_to_runtime_step(item: Any, current_step: str) -> bool:
    step = _text(current_step)
    if not step:
        return False
    bound_step = _text(
        getattr(item, "target_plan_step", None)
        or (item.get("target_plan_step") if isinstance(item, dict) else "")
    )
    if bound_step:
        return bound_step == step
    if step in evidence_item_concepts(item):
        return True
    target = _text(
        getattr(item, "target_plan_stage_id", None)
        or (item.get("target_plan_stage_id") if isinstance(item, dict) else "")
    )
    return bool(target) and target == step


def scope_evidence_queue_to_runtime_step(
    *,
    pending: list[Any],
    deferred: list[Any],
    adopted: list[Any],
    rejected: list[Any],
    history: list[Any] | None = None,
    current_step: str = "",
    recovered: bool = False,
    current_plan_id: str = "",
    current_stage_id: str = "",
) -> dict[str, list[Any]]:
    """Live pending/adopt follow recovered current_step. Older items stay history.

    Non-bound pending items (no step binding at all) surface in the
    ``unscoped`` bucket so they stay actionable; pending items explicitly bound
    to another step stay history, as do non-bound deferred/adopted/rejected.
    """

    def _item_target_stage(item: Any) -> str:
        return _text(
            getattr(item, "target_plan_stage_id", None)
            or (item.get("target_plan_stage_id") if isinstance(item, dict) else "")
        )

    def _partition(
        items: list[Any], *, pending_bucket: bool = False
    ) -> tuple[list[Any], list[Any], list[Any]]:
        live: list[Any] = []
        historic: list[Any] = []
        unscoped: list[Any] = []
        for item in items:
            target_plan = _text(
                getattr(item, "target_plan_id", None)
                or (item.get("target_plan_id") if isinstance(item, dict) else "")
            )
            if target_plan and target_plan != _text(current_plan_id):
                historic.append(item)
                continue
            if target_plan and _item_target_stage(item) != _text(current_stage_id):
                historic.append(item)
                continue
            if not recovered or not _text(current_step):
                live.append(item)
                continue
            if evidence_bound_to_runtime_step(item, current_step):
                live.append(item)
                continue
            target_stage = _item_target_stage(item)
            if pending_bucket and not target_stage:
                # No binding at all: keep it visible as unscoped pending.
                unscoped.append(item)
            else:
                # Explicitly bound elsewhere (or non-pending): history as today.
                historic.append(item)
        return live, historic, unscoped

    live_pending, pending_history, pending_unscoped = _partition(list(pending), pending_bucket=True)
    live_deferred, deferred_history, _deferred_unscoped = _partition(list(deferred))
    live_adopted, adopted_history, _adopted_unscoped = _partition(list(adopted))
    live_rejected, rejected_history, _rejected_unscoped = _partition(list(rejected))
    historic = [
        *list(history or []),
        *pending_history,
        *deferred_history,
        *adopted_history,
        *rejected_history,
    ]
    seen: set[str] = set()
    unique_history: list[Any] = []
    for item in historic:
        item_id = _text(getattr(item, "id", "") or (item.get("id") if isinstance(item, dict) else ""))
        if item_id and item_id in seen:
            continue
        if item_id:
            seen.add(item_id)
        unique_history.append(item)
    return {
        "pending": live_pending,
        "deferred": live_deferred,
        "adopted": live_adopted,
        "rejected": live_rejected,
        "history": unique_history,
        "unscoped": pending_unscoped,
    }


def _structured_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    items = [_text(item) for item in value]
    return [item for item in items if item]
