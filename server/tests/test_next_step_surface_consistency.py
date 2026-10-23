"""Turn-end next-step consistency across the coach reply and the learning
surfaces (teaching gate: 本次回答的下一步与学习页下一步一致).

Real-provider evidence (.trainer-convergence/evidence/t0029-1/2/4.json,
captured 2026-10-23 10:22) shipped ONE /turn response where the reply metadata,
coach_turn and memory.active_thread all carried the turn-anchored step while
``snapshot.coaching_state.next_step`` still held the unrelated mint
「围绕「我在学 Python 的 asyncio」先做一个小动作，把结果带回来。」. The
Learning lane teasers read ``coaching_state.next_step``, so the coach bubble
and the learning page disagreed inside the same response. These tests pin the
contract at the API boundary so the two surfaces can never diverge again.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from provider_fixtures import seed_verified_capabilities

from app.core.models import ProviderConfig
from app.core.settings import AppSettings
from app.llm.provider_service import ProviderService
from app.main import create_app

FILLER_MINT = "先做一个小动作"
FILLER_TAIL = "把结果带回来"
ANCHORED_RESCUE = "先把 Python 的 asyncio 压成一个很小的补丁目标，再继续写。"
REPAIRED_ACTION = "跑通一个并发计时实验，确认总耗时小于顺序执行。"

SCRIPTED_PROVIDER_PAYLOAD = {
    "name": "scripted-next-step-consistency",
    "base_url": "https://provider.invalid/v1",
    "api_key_ref": "test-only",
    "model": "scripted-model",
    "protocol": "openai_chat_completions",
    "capabilities": {"tools": True, "streaming": False},
}


def build_client(tmp_path: Path) -> TestClient:
    settings = AppSettings(
        app_name="Trainer Test Server",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path,
        database_name="trainer-test.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=True,
    )
    return TestClient(create_app(settings))


class _FinalizeScriptedProvider:
    """One coach_finalize call with a configurable next_step and summary."""

    protocol = "openai_chat_completions"

    def __init__(self, *, summary: str, next_step: str) -> None:
        self.summary = summary
        self.next_step = next_step
        self.attachments_will_be_sent = lambda: False  # noqa: E731

    async def call(
        self,
        _messages: list[dict[str, object]],
        _tools: list[dict[str, object]] | None,
    ) -> dict[str, object]:
        return {
            "content": "",
            "tool_calls": [
                {
                    "id": "finalize-consistency",
                    "name": "coach_finalize",
                    "arguments": {"summary": self.summary, "next_step": self.next_step},
                }
            ],
        }

    async def call_stream(
        self,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]] | None,
    ):  # type: ignore[no-untyped-def]
        response = await self.call(messages, tools)
        yield {
            "type": "final",
            "content": response["content"],
            "tool_calls": response["tool_calls"],
            "stop_reason": "tool_calls" if response["tool_calls"] else "stop",
        }


def _run_finalize_turn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    workspace_id: str,
    *,
    summary: str,
    next_step: str,
) -> dict[str, Any]:
    scripted = _FinalizeScriptedProvider(summary=summary, next_step=next_step)

    def build_agent_provider(_self: ProviderService, **_kwargs: object):
        return scripted, scripted

    monkeypatch.setattr(ProviderService, "build_agent_provider", build_agent_provider)

    with build_client(tmp_path / "sidecar") as client:
        runtime = client.app.state.runtime
        seed_verified_capabilities(
            runtime,
            ProviderConfig.model_validate(SCRIPTED_PROVIDER_PAYLOAD),
            "test-only-key",
        )
        started = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "Next-step consistency",
                "workspace_path": str(tmp_path / "learner-project"),
            },
        )
        assert started.status_code == 200, started.text
        session_id = str(started.json()["session_id"])
        response = client.post(
            "/turn",
            json={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "intent": "coach",
                "message": "我在学 Python 的 asyncio，能帮我从第一步开始吗？",
                "response_language": "zh-CN",
                "answer_mode": "guided",
                "use_agent_loop": True,
                "provider": SCRIPTED_PROVIDER_PAYLOAD,
                "api_key": "test-only-key",
            },
        )
        assert response.status_code == 200, response.text
        return response.json()


def _surface_next_steps(body: dict[str, Any]) -> dict[str, str]:
    """Collect every learner-facing next-step surface from one /turn response."""
    reply_metadata = (body.get("reply") or {}).get("metadata") or {}
    visible_status = reply_metadata.get("coach_visible_status") or {}
    snapshot = body.get("snapshot") or {}
    memory = snapshot.get("memory") or {}
    workspace_memory = memory.get("workspace") if isinstance(memory.get("workspace"), dict) else {}
    coaching = snapshot.get("coaching_state") or {}
    active_thread = memory.get("active_thread") or {}
    coach_turn = body.get("coach_turn") or {}
    agent_meta = body.get("agent_meta") or {}
    return {
        "reply_visible_status": str(visible_status.get("nextStep") or ""),
        "coach_turn": str(coach_turn.get("next_step") or ""),
        "agent_meta": str(agent_meta.get("next_step") or ""),
        "coaching_state": str(coaching.get("next_step") or ""),
        "coaching_state_resume_thread": str(coaching.get("resume_thread") or ""),
        "active_thread": str(active_thread.get("next_step") or ""),
        "workspace_active_thread": str(
            (workspace_memory or {}).get("active_thread", {}).get("next_step", "")
        )
        if isinstance(workspace_memory, dict)
        and isinstance(workspace_memory.get("active_thread"), dict)
        else "",
        "workspace_coaching_focus": str(
            (workspace_memory or {}).get("latest_coaching_focus", {}).get("next_step", "")
        )
        if isinstance(workspace_memory, dict)
        and isinstance(workspace_memory.get("latest_coaching_focus"), dict)
        else "",
    }


def test_repaired_finalize_step_drives_every_surface(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the T-0027 repair replaces a generic finalize next_step with the
    reply's labelled action, the repaired step — not the filler — must reach
    every learner-facing surface of the SAME response."""
    summary = f"asyncio 的并发发生在事件循环里，而不是线程里。**下一步**：{REPAIRED_ACTION}"
    body = _run_finalize_turn(
        tmp_path,
        monkeypatch,
        "workspace-next-step-consistency-repair",
        summary=summary,
        next_step=f"围绕「我在学 Python 的 asyncio」{FILLER_MINT}，{FILLER_TAIL}。",
    )

    surfaces = _surface_next_steps(body)
    assert surfaces["agent_meta"] == REPAIRED_ACTION
    # A pure-finalize turn (no other tools) ships no coach_visible_status
    # strip by design; when one is present it must carry the repaired step.
    assert surfaces["reply_visible_status"] in ("", REPAIRED_ACTION)
    assert surfaces["coach_turn"] == REPAIRED_ACTION
    assert surfaces["coaching_state"] == REPAIRED_ACTION, surfaces
    assert surfaces["active_thread"] == REPAIRED_ACTION, surfaces
    assert surfaces["workspace_active_thread"] == REPAIRED_ACTION, surfaces
    assert surfaces["workspace_coaching_focus"] == REPAIRED_ACTION, surfaces
    # The pre-repair filler must not survive anywhere in the continuation path.
    assert FILLER_MINT not in surfaces["coaching_state_resume_thread"], surfaces


def test_anchored_rescue_step_stays_consistent_without_a_labelled_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T-0029 lane: the finalize step is the turn-anchored rescue template and
    the reply carries no labelled action, so the repair cannot fire. The
    coaching state must then ship the SAME anchored step as the reply and the
    memory thread — never the unrelated「围绕…」mint (the t0029-1 artifact)."""
    body = _run_finalize_turn(
        tmp_path,
        monkeypatch,
        "workspace-next-step-consistency-rescue",
        summary="asyncio 的并发发生在事件循环里，而不是线程里。先从一个最小的协程示例开始观察。",
        next_step=ANCHORED_RESCUE,
    )

    surfaces = _surface_next_steps(body)
    assert surfaces["agent_meta"] == ANCHORED_RESCUE
    assert surfaces["coach_turn"] == ANCHORED_RESCUE
    assert surfaces["coaching_state"] == ANCHORED_RESCUE, surfaces
    assert surfaces["active_thread"] == ANCHORED_RESCUE, surfaces
    assert FILLER_MINT not in surfaces["coaching_state"], surfaces
    assert FILLER_TAIL not in surfaces["coaching_state"], surfaces
