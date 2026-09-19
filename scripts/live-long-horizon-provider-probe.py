"""Run a disposable, source-grounded Trainer agent stress probe.

The provider key is read from TRAINER_LIVE_PROBE_API_KEY and is never persisted.
The probe uses a temporary Trainer database, exercises the real provider route and
agent loop, then recreates the app to verify durable session and plan recovery.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

from app.core.models import ProviderConfig
from app.core.settings import AppSettings
from app.main import create_app


def progress(stage: str) -> None:
    print(json.dumps({"progress": stage}, ensure_ascii=False), file=sys.stderr, flush=True)


def build_client(data_dir: Path) -> TestClient:
    settings = AppSettings(
        app_name="Trainer Live Long-Horizon Probe",
        host="127.0.0.1",
        port=8765,
        data_dir=data_dir,
        database_name="trainer-live-probe.db",
        default_session_stage="intake",
        summary_message_limit=12,
        enable_network_fetch=True,
    )
    return TestClient(create_app(settings))


def provider_payload(base_url: str, model: str, *, max_tokens: int = 2048) -> dict[str, Any]:
    context_window_tokens = int(
        os.environ.get("TRAINER_LIVE_PROBE_CONTEXT_WINDOW_TOKENS", "1048576")
    )
    return {
        "name": "Disposable long-horizon probe",
        "baseUrl": base_url,
        "apiKeyRef": "trainer.live-probe.ephemeral",
        "model": model,
        "protocol": "openai_chat_completions_compatible",
        "contextWindowTokens": context_window_tokens,
        "requestDefaults": {"max_tokens": max_tokens, "temperature": 0.2},
        "capabilities": {
            "chat": True,
            "responses": False,
            "vision": False,
            "embeddings": False,
            "tools": True,
            "jsonSchema": False,
            "structuredOutput": False,
            "streaming": True,
        },
    }


def safe_json(response: Any) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def tool_event_summary(
    payload: dict[str, Any],
) -> tuple[list[str], list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    agent_meta = payload.get("agent_meta")
    events = agent_meta.get("tool_events") if isinstance(agent_meta, dict) else []
    names: list[str] = []
    verified_sources: list[dict[str, Any]] = []
    research_evaluation: dict[str, Any] = {}
    tool_failures: list[dict[str, Any]] = []
    for event in events if isinstance(events, list) else []:
        if not isinstance(event, dict):
            continue
        name = str(event.get("name") or "").strip()
        if name:
            names.append(name)
        if event.get("type") != "tool_result":
            continue
        result = event.get("result")
        if not isinstance(result, dict):
            continue
        if result.get("ok") is False:
            tool_failures.append(
                {
                    "name": name,
                    "error": result.get("error"),
                    "detail": result.get("detail"),
                }
            )
        if name == "assess_research_evidence" and result.get("research_status"):
            research_evaluation = {
                "status": result.get("research_status"),
                "complete": result.get("research_complete") is True,
                "exhausted": result.get("research_exhausted") is True,
                "coverage": result.get("evidence_coverage") or {},
            }
        if name != "search_learning_materials":
            continue
        for source in result.get("sources", []):
            if not isinstance(source, dict):
                continue
            title = str(source.get("title") or "").strip()
            url = str(source.get("url") or "").strip()
            fetched_at = str(source.get("fetched_at") or "").strip()
            if title and url and fetched_at:
                verified_sources.append(
                    {
                        "id": str(source.get("id") or "").strip(),
                        "title": title,
                        "url": url,
                        "fetched_at": fetched_at,
                        "trust_score": source.get("trust_score"),
                    }
                )
    deduplicated = {source["url"]: source for source in verified_sources}
    return names, list(deduplicated.values()), research_evaluation, tool_failures


def plan_summary(payload: dict[str, Any]) -> dict[str, Any]:
    snapshot = payload.get("snapshot") if isinstance(payload.get("snapshot"), dict) else payload
    plan = snapshot.get("plan") if isinstance(snapshot, dict) else None
    if not isinstance(plan, dict):
        return {"present": False, "stage_count": 0, "stages": []}
    stages = plan.get("stages") if isinstance(plan.get("stages"), list) else []
    return {
        "present": True,
        "id": plan.get("id") or plan.get("plan_id"),
        "title": plan.get("title"),
        "stage_count": len(stages),
        "current_step": plan.get("current_step"),
        "stages": [
            {
                "id": stage.get("id"),
                "title": stage.get("title"),
                "status": stage.get("status"),
                "resource_count": len(stage.get("resources") or []),
                "outcome_count": len(stage.get("outcomes") or []),
            }
            for stage in stages
            if isinstance(stage, dict)
        ],
    }


async def run_agent_stress(
    *,
    service: Any,
    runtime: Any,
    profile: Any,
    workspace_id: str,
    session_id: str,
    message: str,
) -> tuple[list[dict[str, Any]], dict[str, Any], bool]:
    events: list[dict[str, Any]] = []
    final_event: dict[str, Any] = {}
    timed_out = False
    try:
        async with asyncio.timeout(300):
            async for event in service.coaching_reply_agentic_stream(
                profile,
                message,
                response_language="zh-CN",
                answer_mode="balanced",
                coach_context={
                    "__runtime__": runtime,
                    "workspace_id": workspace_id,
                    "session_id": session_id,
                    "active_view": "plan",
                    "formal_plan_mutation": True,
                    "allow_coach_only_tools": True,
                    "relationship_stage": "established",
                    "scenario": "plan_generation",
                },
                max_steps=20,
                history=[],
            ):
                if not isinstance(event, dict):
                    continue
                events.append(event)
                event_type = str(event.get("type") or "unknown")
                event_name = str(event.get("name") or "").strip()
                if event_type in {"tool_call", "tool_result", "step", "error", "final"}:
                    progress(": ".join(part for part in (f"agent_{event_type}", event_name) if part))
                if event_type == "final":
                    final_event = event
    except TimeoutError:
        timed_out = True
        progress("long_horizon_turn_timed_out")
    return events, final_event, timed_out


def main() -> int:
    api_key = os.environ.get("TRAINER_LIVE_PROBE_API_KEY", "").strip()
    if not api_key:
        print(json.dumps({"ok": False, "error": "TRAINER_LIVE_PROBE_API_KEY is required"}))
        return 2

    base_url = os.environ.get("TRAINER_LIVE_PROBE_BASE_URL", "http://minimax.redfast.top/v1").strip()
    model = os.environ.get("TRAINER_LIVE_PROBE_MODEL", "MiniMax-M2.7-highspeed").strip()
    workspace_id = "workspace-live-long-horizon-probe"
    provider = provider_payload(base_url, model)
    probe_provider = provider_payload(base_url, model, max_tokens=512)
    report: dict[str, Any] = {
        "provider": {
            "base_url": base_url,
            "model": model,
            "configured_context_window_tokens": provider["contextWindowTokens"],
        },
        "criteria": {},
    }

    with tempfile.TemporaryDirectory(prefix="trainer-live-probe-") as temporary:
        data_dir = Path(temporary)
        with build_client(data_dir) as client:
            progress("provider_test_started")
            provider_started = time.monotonic()
            provider_response = client.post(
                "/provider/test",
                json={
                    "provider": probe_provider,
                    "apiKey": api_key,
                    "probeMessage": (
                        "请用中文确认你能处理长程学习任务：先说明会检索和核验来源，"
                        "再给出一个可验证的下一步。"
                    ),
                    "responseLanguage": "zh-CN",
                },
            )
            provider_result = safe_json(provider_response)
            report["provider_test"] = {
                "http_status": provider_response.status_code,
                "elapsed_seconds": round(time.monotonic() - provider_started, 2),
                "ok": provider_result.get("ok") is True,
                "status": provider_result.get("status"),
                "error_category": provider_result.get("error_category"),
                "model_supported": provider_result.get("model_supported"),
                "streaming_ready": provider_result.get("streaming_ready"),
                "tool_calling_ready": provider_result.get("tool_calling_ready"),
                "detail": provider_result.get("detail"),
                "warnings": provider_result.get("warnings") or [],
            }
            progress("provider_test_completed")

            progress("session_start_started")
            start_response = client.post(
                "/session/start",
                json={
                    "workspace_id": workspace_id,
                    "workspace_name": "Live long-horizon provider probe",
                    "profile": {
                        "long_term_goal": (
                            "Master FastAPI dependency injection, testing overrides, and "
                            "maintainable service boundaries"
                        ),
                        "weekly_hours": 7,
                        "teaching_style": "guided",
                        "answer_policy": "balanced",
                    },
                },
            )
            started = safe_json(start_response)
            session_id = str(started.get("session_id") or "")
            report["session_start"] = {
                "http_status": start_response.status_code,
                "session_created": bool(session_id),
            }
            progress("session_start_completed")

            progress("long_horizon_turn_started")
            turn_started = time.monotonic()
            stress_message = (
                "现在直接创建并保存一个高强度、可执行的 6 阶段学习计划，不要再问澄清问题。"
                "目标是在真实项目中掌握 FastAPI 依赖注入、子依赖、生命周期、测试替换和架构边界。"
                "你必须先主动检索公开学习资料，优先使用 FastAPI 官方文档。第一次调用检索工具时，"
                "固定 required_facets 为 dependency injection、sub-dependencies、dependency lifecycle、"
                "testing overrides、service boundaries，并将 fastapi.tiangolo.com 放入 preferred_domains。"
                "不能把来源数量直接当作证据充分；只有工具返回 sufficient 才能停止检索，"
                "每次检索后必须由你调用 assess_research_evidence，逐项引用 source_ids 并说明判断理由；"
                "若评估返回 gaps_remain 则只针对 missing_facets 缩小检索。"
                "每个阶段都要有明确产物、验证方法和来源资源，最后一阶段必须是综合项目与回归测试。"
                "完成检索后调用正式计划工具保存计划，再用简洁中文汇报来源、阶段和第一步。"
            )
            runtime = client.app.state.runtime
            provider_config = ProviderConfig.model_validate(provider)
            coaching_service = runtime.provider_service_for(provider_config, api_key)
            profile = runtime.repository.get_profile(workspace_id)
            agent_events, final_event, turn_timed_out = asyncio.run(
                run_agent_stress(
                    service=coaching_service,
                    runtime=runtime,
                    profile=profile,
                    workspace_id=workspace_id,
                    session_id=session_id,
                    message=stress_message,
                )
            )
            persisted_plan = runtime.repository.get_latest_plan(workspace_id)
            turn_payload = {
                "snapshot": {
                    "plan": (
                        persisted_plan.model_dump(mode="json")
                        if persisted_plan is not None
                        else None
                    )
                },
                "agent_meta": {
                    "tool_events": agent_events,
                    "stop_reason": final_event.get("stop_reason"),
                    "fell_back": final_event.get("fell_back"),
                    "formal_plan_commit": (
                        "committed"
                        if any(
                            event.get("type") == "tool_result"
                            and event.get("name") == "save_formal_plan"
                            and isinstance(event.get("result"), dict)
                            and event["result"].get("ok") is True
                            for event in agent_events
                        )
                        else "missing"
                    ),
                },
                "reply": {"content": final_event.get("content") or ""},
            }
            tool_names, sources, research_evaluation, tool_failures = tool_event_summary(turn_payload)
            generated_plan = plan_summary(turn_payload)
            reply = turn_payload.get("reply") if isinstance(turn_payload.get("reply"), dict) else {}
            agent_meta = (
                turn_payload.get("agent_meta")
                if isinstance(turn_payload.get("agent_meta"), dict)
                else {}
            )
            report["long_horizon_turn"] = {
                "http_status": 504 if turn_timed_out else 200,
                "elapsed_seconds": round(time.monotonic() - turn_started, 2),
                "reply_characters": len(str(reply.get("content") or "")),
                "stop_reason": agent_meta.get("stop_reason"),
                "fell_back": agent_meta.get("fell_back"),
                "formal_plan_commit": agent_meta.get("formal_plan_commit"),
                "tool_call_count": len(tool_names),
                "tool_counts": dict(Counter(tool_names)),
                "verified_source_count": len(sources),
                "verified_sources": sources,
                "research_evaluation": research_evaluation,
                "tool_failures": tool_failures,
                "plan": generated_plan,
            }
            progress("long_horizon_turn_completed")

        progress("restart_recovery_started")
        with build_client(data_dir) as restored_client:
            restored_response = restored_client.post(
                "/session/start",
                json={
                    "workspace_id": workspace_id,
                    "workspace_name": "Live long-horizon provider probe",
                },
            )
            restored_payload = safe_json(restored_response)
            restored_plan = plan_summary(restored_payload)
            report["restart_recovery"] = {
                "http_status": restored_response.status_code,
                "same_session": restored_payload.get("session_id") == session_id,
                "same_plan": bool(generated_plan.get("id"))
                and restored_plan.get("id") == generated_plan.get("id"),
                "restored_stage_count": restored_plan.get("stage_count"),
            }
        progress("restart_recovery_completed")

    stages = generated_plan.get("stages") if isinstance(generated_plan.get("stages"), list) else []
    criteria = {
        "provider_usable": report["provider_test"]["ok"] is True,
        "agent_completed_without_fallback": (
            report["long_horizon_turn"]["http_status"] == 200
            and report["long_horizon_turn"]["fell_back"] is not True
        ),
        "public_research_used": "search_learning_materials" in tool_names,
        "verified_sources_found": len(sources) >= 2,
        "evidence_coverage_sufficient": research_evaluation.get("status") == "sufficient",
        "formal_plan_saved": "save_formal_plan" in tool_names and generated_plan.get("present") is True,
        "complex_plan_has_six_stages": generated_plan.get("stage_count") == 6,
        "every_stage_has_evidence_and_outcome": bool(stages)
        and all(
            int(stage.get("resource_count") or 0) > 0
            and int(stage.get("outcome_count") or 0) > 0
            for stage in stages
        ),
        "restart_restores_same_session_and_plan": (
            report["restart_recovery"]["same_session"] is True
            and report["restart_recovery"]["same_plan"] is True
            and report["restart_recovery"]["restored_stage_count"] == 6
        ),
    }
    report["criteria"] = criteria
    report["ok"] = all(criteria.values())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
