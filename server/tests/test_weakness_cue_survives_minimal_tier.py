"""The weakness recall cue survives the minimal context tier.

Contract §7: when an editor diagnostic touches a previously recorded weakness, the coach
mentions it once, calmly, and invites the learner to locate the cause. The cue is a few
hundred characters of prompt. The minimal context tier ("pure Q&A: skip retrieval and the
learner archive") was introduced to keep a short question from paying for the full archive
prompt; its own rule, written before and after that change, is that the tier is "only ever
a prompt/IO reduction, never a behavior gate". Tying the cue to the tier broke that rule:
a learner with a live error in the editor who types a short message got no cue at all,
because the tier resolver reads only the message text. The cue is therefore computed for
every tier; direct-answer mode still suppresses it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.models import (
    CapabilityFlags,
    ProviderCapabilityEvidence,
    ProviderConfig,
    ProviderTestResponse,
    UserProfile,
)
from app.llm.provider_service import ProviderService
from app.main import create_app
from app.memory.proactive_budget import match_diagnostic_to_weakness


def _client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(Settings(data_dir=tmp_path / "trainer_data")))


def _runtime(client: TestClient) -> Any:
    """Starlette types ``TestClient.app`` as the ASGI callable union; narrow it at runtime."""
    application = client.app
    assert isinstance(application, FastAPI), "test client must wrap the Trainer FastAPI app"
    return application.state.runtime


def _prepare(client: TestClient, workspace_id: str, *, typing_now: bool) -> tuple[Any, str]:
    runtime = _runtime(client)
    started = client.post(
        "/session/start", json={"workspace_id": workspace_id, "workspace_name": "Proactive Repo"}
    )
    assert started.status_code == 200, started.text
    session_id = started.json()["session_id"]
    structured = runtime.memory_service.structured_for_workspace(workspace_id)
    structured.record_weakness(
        "idempotency",
        "forgot idempotent replay status check on conflict",
        severity=2,
        review_after_days=1,
    )
    runtime.memory_service._persist_structured(workspace_id)
    assert runtime.memory_service.weaknesses(workspace_id)
    # The proactive nudge endpoint has its own budget; exercise its typing gate once.
    evaluate = client.post(
        "/proactive/evaluate",
        json={
            "session_id": session_id,
            "workspace_id": workspace_id,
            "diagnostics": ["AssertionError: idempotency key replay returned 500"],
            "learner_actively_typing": typing_now,
            "record": True,
            "now": "2026-11-20T10:00:00Z",
        },
    )
    assert evaluate.status_code == 200, evaluate.text
    provider = ProviderConfig(
        name="proactive-coach",
        baseUrl="https://example.com/v1",
        apiKeyRef="trainer.proactive",
        model="MiniMax-M3",
        capabilities=CapabilityFlags(tools=True, streaming=True),
    )
    runtime.provider_config = provider
    runtime.provider_api_key = "sk-test-fake"
    runtime.provider_service = ProviderService(config=provider, api_key="sk-test-fake")
    runtime.provider_service_cache.clear()
    runtime.remember_provider_capability_test(
        provider,
        "sk-test-fake",
        ProviderTestResponse(
            ok=True,
            detail="mocked provider capability test",
            capabilityEvidence=[
                ProviderCapabilityEvidence(name="streaming", declared=True, observed=True, state="verified"),
                ProviderCapabilityEvidence(name="tools", declared=True, observed=True, state="verified"),
            ],
            toolsReady=True,
            toolProbeStatus="verified",
        ),
    )
    return runtime, session_id


def _capture_context(client: TestClient, session_id: str, workspace_id: str, payload: dict) -> dict:
    captured: list[dict] = []

    async def fake_stream(
        _self: ProviderService,
        _profile: UserProfile | None,
        _message: str,
        current_file: dict | None = None,
        response_language: str | None = None,
        answer_mode: str | None = None,
        coach_context: dict | None = None,
        **_kwargs: object,
    ):
        captured.append(dict(coach_context or {}))
        yield "先检查这一行幂等键的冲突状态码。"

    body = {"session_id": session_id, "workspace_id": workspace_id, **payload}
    with patch.object(ProviderService, "coaching_reply_stream", fake_stream):
        response = client.post("/turn/stream", json=body)
    assert response.status_code == 200, response.text
    assert captured, "the coach stream was not invoked"
    return captured[-1]


DIAGNOSTIC = "AssertionError: idempotency replay status mismatch"
CURRENT_FILE = {
    "path": "src/orders/retry.py",
    "content": "def retry(conflict):\n    return conflict.status_code\n",
    "language_id": "python",
    "diagnostics": [DIAGNOSTIC],
}


def test_a_short_message_with_a_matching_diagnostic_keeps_the_weakness_cue(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        runtime, session_id = _prepare(client, "ws-cue-short", typing_now=True)
        assert match_diagnostic_to_weakness([DIAGNOSTIC], runtime.memory_service.weakness_records("ws-cue-short"))
        # A short, anchor-free message next to a file with a live error is exactly the
        # turn the minimal tier was made for — and exactly the §7 situation.
        context = _capture_context(
            client,
            session_id,
            "ws-cue-short",
            {"message": "然后呢？", "current_file": CURRENT_FILE, "answer_mode": "auto"},
        )

        assert context.get("context_tier") == "minimal", context.get("context_tier")
        assert context["diagnostic_weakness_hint"]["concept"] == "idempotency"
        assert DIAGNOSTIC in context["diagnostic_weakness_hint"]["diagnostic"]


def test_the_cue_is_computed_in_the_full_tier_as_before(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        _runtime, session_id = _prepare(client, "ws-cue-full", typing_now=True)
        context = _capture_context(
            client,
            session_id,
            "ws-cue-full",
            {"message": "这个文件的报错是怎么回事？", "current_file": CURRENT_FILE, "answer_mode": "auto"},
        )

        assert context.get("context_tier") != "minimal"
        assert context["diagnostic_weakness_hint"]["concept"] == "idempotency"


def test_the_cue_stays_absent_without_a_matching_diagnostic(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        _runtime, session_id = _prepare(client, "ws-cue-none", typing_now=True)
        unrelated = dict(CURRENT_FILE, diagnostics=["SyntaxError: invalid syntax"])
        context = _capture_context(
            client,
            session_id,
            "ws-cue-none",
            {"message": "然后呢？", "current_file": unrelated, "answer_mode": "auto"},
        )

        assert "diagnostic_weakness_hint" not in context


def test_the_prompt_carries_the_cue_in_the_minimal_tier_and_direct_mode_drops_it(tmp_path: Path) -> None:
    from app.llm.prompt_domains.scenario_and_context_blocks import build_coaching_system_prompt

    hint = {"diagnostic_weakness_hint": {"concept": "idempotency", "diagnostic": DIAGNOSTIC}}
    for tier in ("minimal", "full"):
        prompt = build_coaching_system_prompt(
            UserProfile(),
            "zh-CN",
            message="然后呢？",
            coach_context=dict(hint, context_tier=tier),
        )
        assert "## Weakness Recall Cue" in prompt, tier
        assert "idempotency" in prompt, tier

    direct = build_coaching_system_prompt(
        UserProfile(),
        "zh-CN",
        answer_mode="direct",
        message="然后呢？",
        coach_context=dict(hint, context_tier="minimal"),
    )
    assert "## Weakness Recall Cue" not in direct
