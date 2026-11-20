"""Browser chat lane: the paired extension can start a real session."""

from __future__ import annotations

from pathlib import Path
from typing import Any, AsyncIterator

import pytest
from fastapi.testclient import TestClient
from provider_fixtures import seed_verified_capabilities

from app.core.models import ProviderConfig, TrainingCardCandidateSnapshot
from app.core.settings import AppSettings
from app.llm.provider_service import ProviderService
from app.main import create_app
from tests.training_card_fixtures import open_generated_training_card


def build_client(tmp_path: Path) -> TestClient:
    settings = AppSettings(
        app_name="Trainer browser chat",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path,
        database_name="trainer-browser-chat.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )
    return TestClient(create_app(settings))


def _pair_browser(client: TestClient, workspace_id: str, code: str = "135790") -> str:
    started = client.post(
        "/session/start",
        json={"workspace_id": workspace_id, "workspace_name": "Browser chat"},
    )
    assert started.status_code == 200, started.text
    session_id = started.json()["session_id"]
    registered = client.post(
        "/browser/pair-code",
        json={
            "code": code,
            "expires_in": 600,
            "session_id": session_id,
            "workspace_id": workspace_id,
        },
    )
    assert registered.status_code == 200, registered.text
    paired = client.post("/browser/pair", json={"code": code})
    assert paired.status_code == 200, paired.text
    return str(paired.json()["credential"])


def _script_provider(monkeypatch: pytest.MonkeyPatch, reply: str) -> None:
    """Make every provider call in this test return one scripted reply."""

    async def _chat(self: ProviderService, *_: Any, **__: Any) -> str:
        return reply

    async def _stream(self: ProviderService, *_: Any, **__: Any) -> AsyncIterator[str]:
        yield reply

    monkeypatch.setattr(ProviderService, "chat_completion", _chat)
    monkeypatch.setattr(ProviderService, "chat_completion_stream", _stream)
    monkeypatch.setattr(ProviderService, "coaching_reply", _chat)
    monkeypatch.setattr(ProviderService, "coaching_reply_stream", _stream)


def test_browser_chat_bootstrap_requires_a_bearer_credential(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        response = client.get("/browser/chat/bootstrap")
        assert response.status_code == 401


def test_browser_chat_bootstrap_starts_the_paired_workspace_session(tmp_path: Path) -> None:
    workspace_id = "workspace-browser-chat"
    with build_client(tmp_path) as client:
        credential = _pair_browser(client, workspace_id)
        headers = {"Authorization": f"Bearer {credential}"}
        response = client.get("/browser/chat/bootstrap", headers=headers)
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload.get("session_id")
        assert isinstance(payload.get("messages"), list)
        assert payload.get("contextId") == workspace_id
        assert payload.get("active_panel") == "chat"

        sessions = client.get("/browser/chat/sessions", headers=headers)
        assert sessions.status_code == 200, sessions.text


def test_browser_chat_streams_a_reply_into_the_paired_conversation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Chrome side panel is a conversation client: a paired credential can
    send a turn and read the streamed reply back."""

    workspace_id = "workspace-browser-chat-stream"
    reply = "先做最小的一步，然后告诉我结果。"

    with build_client(tmp_path) as client:
        _script_provider(monkeypatch, reply)

        runtime = client.app.state.runtime
        provider = ProviderConfig(
            name="browser-chat-test",
            base_url="http://127.0.0.1:9/v1",
            api_key_ref="trainer.browser-chat",
            model="gpt-4o-mini",
            capabilities={
                "chat": True,
                "responses": True,
                "vision": False,
                "embeddings": True,
                "tools": False,
                "json_schema": False,
                "streaming": True,
            },
        )
        runtime.provider_config = provider
        runtime.provider_api_key = "sk-test"
        runtime.provider_service = ProviderService(config=provider, api_key="sk-test")
        runtime.provider_service_cache.clear()
        seed_verified_capabilities(runtime, provider, "sk-test", tools=False)

        credential = _pair_browser(client, workspace_id)
        headers = {"Authorization": f"Bearer {credential}"}

        bootstrap = client.get("/browser/chat/bootstrap", headers=headers)
        assert bootstrap.status_code == 200, bootstrap.text
        session_id = str(bootstrap.json()["session_id"])

        with client.stream(
            "POST",
            "/browser/chat/message/stream",
            headers=headers,
            json={"session_id": session_id, "message": "给我一个最小练习。"},
        ) as response:
            assert response.status_code == 200, response.read().decode("utf-8", errors="replace")[:400]
            raw = b"".join(response.iter_bytes()).decode("utf-8", errors="replace")

        assert "data:" in raw, raw[:400]
        assert reply in raw, raw[:400]

        history = client.get(
            "/browser/chat/history",
            headers=headers,
            params={"session_id": session_id},
        )
        assert history.status_code == 200, history.text
        messages = history.json()
        # The history lane answers with session summaries: the paired client
        # reads the latest turn of the conversation it just had.
        assert isinstance(messages, list)
        session_entries = [
            entry for entry in messages if str(entry.get("session_id") or "") == session_id
        ]
        assert session_entries, messages
        entry = session_entries[0]
        assert entry.get("latest_user_message") == "给我一个最小练习。"
        assert entry.get("latest_assistant_message") == reply
        assert int(entry.get("message_count") or 0) >= 2


def test_browser_chat_message_strips_provider_credentials(tmp_path: Path) -> None:
    """The browser lane never carries provider overrides: the paired
    credential already names the workspace and the provider."""

    workspace_id = "workspace-browser-chat-scope"
    with build_client(tmp_path) as client:
        credential = _pair_browser(client, workspace_id)
        headers = {"Authorization": f"Bearer {credential}"}

        bootstrap = client.get("/browser/chat/bootstrap", headers=headers)
        assert bootstrap.status_code == 200, bootstrap.text
        session_id = str(bootstrap.json()["session_id"])

        response = client.post(
            "/browser/chat/message",
            headers=headers,
            json={
                "session_id": session_id,
                "message": "梳理一下当前的证据。",
                "provider_config": {"api_key": "sk-should-be-stripped"},
            },
        )
        # The turn is rejected by the provider gate (no provider configured),
        # never by a leaked browser-supplied key.
        assert response.status_code in {200, 400, 502, 503}, response.text
        assert "sk-should-be-stripped" not in response.text


def test_browser_chat_records_a_practice_answer_as_a_real_attempt(tmp_path: Path) -> None:
    """A practice answered in the browser panel is a real training attempt.

    The panel owns the learner's answer, so the answer travels the server's
    training chain: the attempt starts, the draft is recorded, the evidence is
    bound to what the learner wrote, and the practice return closes it. The
    server owns the trust level and the workspace.
    """
    workspace_id = "workspace-browser-practice"
    with build_client(tmp_path) as client:
        credential = _pair_browser(client, workspace_id)
        headers = {"Authorization": f"Bearer {credential}"}
        runtime = client.app.state.runtime
        runtime.memory_service.upsert_card(
            workspace_id,
            TrainingCardCandidateSnapshot(
                card_id="browser-practice-1",
                card_type="practice",
                title="Practice in the browser panel",
                status="active",
                focus_area="Browser practice",
                target_skill="practice verification",
            ),
        )
        open_generated_training_card(client, workspace_id, "browser-practice-1")

        started = client.post(
            "/browser/chat/training/attempt/start",
            headers=headers,
            json={"card_id": "browser-practice-1"},
        )
        assert started.status_code == 200, started.text
        attempt_id = str(started.json()["attempt"]["attempt_id"])

        updated = client.post(
            "/browser/chat/training/attempt/update",
            headers=headers,
            json={"attempt_id": attempt_id, "answer_draft": "边界检查已覆盖"},
        )
        assert updated.status_code == 200, updated.text

        evidence = client.post(
            "/browser/chat/training/attempt/evidence",
            headers=headers,
            json={
                "attempt_id": attempt_id,
                "artifact_hash": "browser-answer-hash",
                "result": "passed",
            },
        )
        assert evidence.status_code == 200, evidence.text
        recorded = evidence.json()["evidence"]
        # The server decides the trust level: a learner return is never
        # host-verified, so it cannot attest executable capability.
        assert recorded["trust_level"] == "self_reported"
        assert recorded["artifact_hash"] == "browser-answer-hash"

        returned = client.post(
            "/browser/chat/training/practice-return",
            headers=headers,
            json={
                "card_id": "browser-practice-1",
                "passed": True,
                "summary": "边界检查已覆盖",
                "evidence_source": "learner_return",
            },
        )
        assert returned.status_code == 200, returned.text
        payload = returned.json()
        assert payload.get("ok") is True
        # The credential names the workspace: a client cannot record the
        # result somewhere else.
        workspace = payload.get("workspace") or {}
        assert workspace.get("workspace_id") == workspace_id

        # The attempt survived the whole chain, with the learner's own words.
        stored = runtime.attempt_store.get_attempt(attempt_id, workspace_id=workspace_id)
        assert stored is not None
        assert stored.get("answer_draft") == "边界检查已覆盖"


def test_browser_chat_practice_return_requires_a_bearer_credential(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        response = client.post(
            "/browser/chat/training/practice-return",
            json={"card_id": "browser-practice-1", "passed": True},
        )
        assert response.status_code == 401
