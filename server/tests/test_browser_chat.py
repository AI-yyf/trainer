"""Browser chat lane: the paired extension can start a real session."""

from __future__ import annotations

import json
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


def _configure_provider(runtime: Any, *, verified: bool) -> None:
    provider = ProviderConfig(
        name="browser-chat-boundary",
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
    if verified:
        seed_verified_capabilities(runtime, provider, "sk-test", tools=False)


def _forbidden_chat_fields(tmp_path: Path) -> dict[str, Any]:
    """What a paired browser would send to turn a chat into file access."""
    return {
        "intent": "review",
        "current_file": {
            "path": "evil.py",
            "language_id": "python",
            "content": "import os; os.system('echo PWNED')  # LANE_MARKER",
        },
        "file_path": "evil.py",
        "language_id": "python",
        "content": "import os  # LANE_MARKER",
        "workspace_path": str(tmp_path / "elsewhere"),
        "workspace_context": {"root_path": str(tmp_path / "elsewhere")},
        "workspace_file_snapshot": {
            "root_path": str(tmp_path / "elsewhere"),
            "files": [{"path": "secret.txt", "content": "LANE_MARKER"}],
        },
        "active_view": "resources",
        "answer_mode": "review",
    }


def test_browser_chat_cannot_reach_the_evaluator_or_move_the_workspace_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exploit the lane used to allow: a paired browser sends a "review"
    turn whose current file is its own Python, while the provider is not
    verified, and the offline path runs it; and it repoints the workspace root
    so the coach's file tools read somewhere else. Neither field may travel."""

    workspace_id = "workspace-browser-chat-boundary"
    evaluated: list[object] = []
    with build_client(tmp_path) as client:
        credential = _pair_browser(client, workspace_id)
        headers = {"Authorization": f"Bearer {credential}"}
        runtime = client.app.state.runtime
        # Saved but never verified: the route that used to fall through to the
        # local evaluator.
        _configure_provider(runtime, verified=False)
        real_evaluator = runtime.evaluator_service.evaluate_current_file

        def _spy(*args: Any, **kwargs: Any) -> Any:
            evaluated.append(args)
            return real_evaluator(*args, **kwargs)

        monkeypatch.setattr(runtime.evaluator_service, "evaluate_current_file", _spy)

        bootstrap = client.get("/browser/chat/bootstrap", headers=headers)
        assert bootstrap.status_code == 200, bootstrap.text
        session_id = str(bootstrap.json()["session_id"])

        for lane_path in ("/browser/chat/message",):
            response = client.post(
                lane_path,
                headers=headers,
                json={
                    "session_id": session_id,
                    "message": "帮我看看这个文件。",
                    **_forbidden_chat_fields(tmp_path),
                },
            )
            assert response.status_code == 200, response.text
            assert "PWNED" not in response.text

        assert evaluated == [], "a browser message must never reach the local evaluator"
        assert runtime.resolve_workspace_path(workspace_id) != str(tmp_path / "elsewhere")
        assert str(tmp_path / "elsewhere") not in json.dumps(dict(runtime.workspace_paths))


def test_browser_chat_forwards_only_the_allowlisted_fields_to_the_coach(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With a live provider the turn is a plain coach turn: the conversation
    scope stays the coach thread and nothing else in the body reaches it."""

    workspace_id = "workspace-browser-chat-allowlist"
    seen: list[str] = []
    with build_client(tmp_path) as client:
        credential = _pair_browser(client, workspace_id)
        headers = {"Authorization": f"Bearer {credential}"}
        runtime = client.app.state.runtime
        _configure_provider(runtime, verified=True)

        async def _reply(self: ProviderService, *args: Any, **kwargs: Any) -> str:
            seen.append(json.dumps([*map(str, args), *map(str, kwargs.values())], ensure_ascii=False))
            return "好的，先做最小的一步。"

        monkeypatch.setattr(ProviderService, "coaching_reply", _reply)
        monkeypatch.setattr(ProviderService, "chat_completion", _reply)

        bootstrap = client.get("/browser/chat/bootstrap", headers=headers)
        assert bootstrap.status_code == 200, bootstrap.text
        session_id = str(bootstrap.json()["session_id"])

        response = client.post(
            "/browser/chat/message",
            headers=headers,
            json={
                "session_id": session_id,
                "message": "给我一个最小练习。",
                "response_language": "zh-CN",
                "page_context": {
                    "url": "https://example.com/post",
                    "title": "A post",
                    "selection": "selected words",
                    "cookies": "should-not-travel",
                },
                **_forbidden_chat_fields(tmp_path),
            },
        )
        assert response.status_code == 200, response.text

    forwarded = "\n".join(seen)
    assert "给我一个最小练习。" in forwarded
    assert "selected words" in forwarded
    assert "LANE_MARKER" not in forwarded
    assert "PWNED" not in forwarded
    assert "elsewhere" not in forwarded
    assert "should-not-travel" not in forwarded


def test_browser_chat_rejects_a_message_that_is_not_text(tmp_path: Path) -> None:
    workspace_id = "workspace-browser-chat-shape"
    with build_client(tmp_path) as client:
        credential = _pair_browser(client, workspace_id)
        headers = {"Authorization": f"Bearer {credential}"}
        bootstrap = client.get("/browser/chat/bootstrap", headers=headers)
        session_id = str(bootstrap.json()["session_id"])

        for lane_path in ("/browser/chat/message", "/browser/chat/message/stream"):
            for message in ({"text": "not a string"}, ["a", "list"], 42, "", "   "):
                response = client.post(
                    lane_path,
                    headers=headers,
                    json={"session_id": session_id, "message": message},
                )
                assert response.status_code == 422, (lane_path, message, response.text)
                assert response.json()["detail"]["code"] == "message_required"

            too_long = client.post(
                lane_path,
                headers=headers,
                json={"session_id": session_id, "message": "x" * 40_000},
            )
            assert too_long.status_code == 413, too_long.text


def test_browser_chat_rejects_an_oversized_or_deeply_nested_body(tmp_path: Path) -> None:
    workspace_id = "workspace-browser-chat-size"
    with build_client(tmp_path) as client:
        credential = _pair_browser(client, workspace_id)
        headers = {"Authorization": f"Bearer {credential}"}

        oversized = client.post(
            "/browser/chat/message",
            headers=headers,
            json={"session_id": "s", "message": "x" * (256 * 1024)},
        )
        assert oversized.status_code == 413, oversized.text

        nested: Any = "x"
        for _ in range(8):
            nested = [nested]
        deep = client.post(
            "/browser/chat/training/attempt/evidence",
            headers=headers,
            json={"attempt_id": "a", "artifact_hash": "h", "result": "passed", "limitations": nested},
        )
        assert deep.status_code == 413, deep.text

        not_json = client.post(
            "/browser/chat/message",
            headers={**headers, "Content-Type": "application/json"},
            content=b"not json",
        )
        assert not_json.status_code == 422, not_json.text


def test_browser_lane_payload_is_rebuilt_from_the_allowlist() -> None:
    from app.api.routes.browser_chat import (
        _CANCEL_FIELDS,
        _MESSAGE_FIELDS,
        _TRAINING_FIELDS,
        _bounded_copy,
        _browser_payload,
        _normalize_message_payload,
    )

    body = {
        "session_id": "s-1",
        "message": "hello",
        "intent": "review",
        "current_file": {"content": "x"},
        "workspace_path": "/",
        "provider": {"base_url": "https://evil.example"},
        "api_key": "sk-leak",
        "workspace_file_snapshot": {"root_path": "/"},
        "verification_python": "/bin/sh",
        "scenario": {"command": "rm -rf /"},
        "transfer_metadata": {"x": 1},
    }

    message = _browser_payload("ws", body, _MESSAGE_FIELDS + ("page_context",))
    assert message == {"workspace_id": "ws", "session_id": "s-1", "message": "hello"}
    assert _normalize_message_payload(dict(message))["active_view"] == "coach"

    cancel = _browser_payload("ws", body, _CANCEL_FIELDS)
    assert cancel == {"workspace_id": "ws", "session_id": "s-1"}

    # A lane route only ever forwards what its upstream model needs from a
    # browser; a body cannot smuggle in a field another route allows.
    evidence = _browser_payload("ws", body, _TRAINING_FIELDS["/training/attempt/evidence"])
    assert set(evidence) == {"workspace_id"}
    practice = _browser_payload("ws", {**body, "card_id": "c", "passed": True}, _TRAINING_FIELDS["/training/practice-return"])
    assert practice == {"workspace_id": "ws", "card_id": "c", "passed": True}

    # The workspace is the credential's, whatever the body says.
    assert _browser_payload("ws", {"workspace_id": "other"}, _MESSAGE_FIELDS)["workspace_id"] == "ws"

    assert _bounded_copy({"a": [1, True, None, "s"]}) == {"a": [1, True, None, "s"]}
    assert _bounded_copy(float("nan")) is None
    assert _bounded_copy({"k": object()}) == {"k": None}


def test_a_chat_payload_cannot_move_a_registered_workspace_root(tmp_path: Path) -> None:
    """Host-authenticated as it is, a chat/turn payload may only confirm the
    root that /session/start registered, never replace it."""
    workspace_id = "workspace-chat-root-guard"
    real_root = tmp_path / "real-root"
    elsewhere = tmp_path / "elsewhere"
    real_root.mkdir()
    elsewhere.mkdir()

    with build_client(tmp_path) as client:
        started = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "Root Guard",
                "workspace_path": str(real_root),
            },
        )
        assert started.status_code == 200, started.text
        session_id = str(started.json()["session_id"])
        runtime = client.app.state.runtime

        client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "message": "hello",
                "workspace_path": str(elsewhere),
                "workspace_file_snapshot": {"root_path": str(elsewhere)},
            },
        )
        assert runtime.resolve_workspace_path(workspace_id) == str(real_root)

        # A different spelling of the same directory is the same root.
        client.post(
            "/session/message",
            json={
                "session_id": session_id,
                "message": "hello",
                "workspace_path": str(tmp_path / "real-root" / ".." / "real-root"),
            },
        )
        assert runtime.resolve_workspace_path(workspace_id) == str(real_root)

        # The host may still move the root the honest way.
        moved = tmp_path / "moved-root"
        moved.mkdir()
        client.post(
            "/session/start",
            json={"workspace_id": workspace_id, "workspace_name": "Root Guard", "workspace_path": str(moved)},
        )
        assert runtime.resolve_workspace_path(workspace_id) == str(moved)


def test_a_paired_browser_cannot_relabel_the_workspace(tmp_path: Path) -> None:
    """The credential names the workspace, its label included.

    `/browser/chat/bootstrap` used to forward a `workspace_name` query
    parameter to `/session/start`: uncapped text from the paired browser,
    persisted as the host session's workspace name.
    """
    workspace_id = "workspace-browser-relabel"
    with build_client(tmp_path) as client:
        credential = _pair_browser(client, workspace_id)
        headers = {"Authorization": f"Bearer {credential}"}

        response = client.get(
            "/browser/chat/bootstrap",
            params={"workspace_name": "Relabelled by a paired browser"},
            headers=headers,
        )

        assert response.status_code == 200, response.text
        runtime = client.app.state.runtime
        sessions = [state for state in runtime.sessions.values() if state.workspace_id == workspace_id]
        assert sessions, "the paired workspace session was started"
        assert all(
            state.workspace_name == "Browser chat" for state in sessions
        ), [state.workspace_name for state in sessions]
