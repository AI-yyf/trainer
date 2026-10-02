from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.models import ProviderConfig
from app.core.settings import AppSettings
from app.llm.provider_service import ProviderService
from app.main import create_app


def client_for(tmp_path: Path) -> TestClient:
    app = create_app(AppSettings(
        app_name="Trainer Skill Draft", host="127.0.0.1", port=8765,
        data_dir=tmp_path, database_name="skills.db", default_session_stage="intake",
        summary_message_limit=6, enable_network_fetch=False,
    ))
    app.state.runtime.provider_config = ProviderConfig(
        name="skill-test", base_url="http://127.0.0.1:9/v1", model="test-model",
        api_key_ref="test-only",
    )
    app.state.runtime.provider_api_key = "test-skill-key"
    app.state.runtime.provider_service = ProviderService(
        config=app.state.runtime.provider_config, api_key="test-skill-key",
    )
    return TestClient(app)


def test_skill_draft_uses_model_without_saving_skill_or_mutating_conversation(tmp_path: Path) -> None:
    draft = {"trigger": "$python-check", "title": "检查 Python", "detail": "一个问题和一次验证",
             "prompt": "检查当前提交。只指出一个关键问题、一条验证命令和下一步。"}
    with client_for(tmp_path) as client, patch.object(
        ProviderService, "chat_completion", new=AsyncMock(return_value=json.dumps(draft)),
    ) as completion:
        response = client.post("/provider/skill-draft", json={
            "description": "检查我的 Python 代码", "response_language": "zh-CN",
        })
        assert response.status_code == 200, response.text
        assert response.json() == {**draft, "source": "model"}
        completion.assert_awaited_once()
        messages = completion.await_args.kwargs["messages"]
        assert "检查我的 Python 代码" in messages[-1]["content"]
        assert "zh-CN" in messages[-1]["content"]
        assert client.app.state.runtime.repository.get_latest_plan("default") is None
        assert client.app.state.runtime.sessions == {}


@pytest.mark.parametrize("description", [None, "", "a", "x" * 2001, 123])
def test_skill_draft_rejects_invalid_description_before_model_call(tmp_path: Path, description) -> None:
    with client_for(tmp_path) as client, patch.object(ProviderService, "chat_completion", new=AsyncMock()) as completion:
        response = client.post("/provider/skill-draft", json={"description": description})
        assert response.status_code == 422
        completion.assert_not_awaited()


@pytest.mark.parametrize("raw", ["not json", "[]", '{"trigger":"$bad trigger"}',
    json.dumps({"trigger": "$check", "title": "check", "detail": "check", "prompt": "x" * 4001})])
def test_invalid_model_draft_is_visible_failure_without_fake_template_success(tmp_path: Path, raw: str) -> None:
    with client_for(tmp_path) as client, patch.object(ProviderService, "chat_completion", new=AsyncMock(return_value=raw)):
        response = client.post("/provider/skill-draft", json={"description": "Check Python"})
        assert response.status_code == 502
        assert response.json()["detail"] == "Skill generation failed. Try again."


def test_skill_draft_errors_do_not_return_upstream_secret_text(tmp_path: Path) -> None:
    with client_for(tmp_path) as client, patch.object(ProviderService, "chat_completion", new=AsyncMock(side_effect=RuntimeError("secret-fixture-123"))):
        response = client.post("/provider/skill-draft", json={"description": "Check Python"})
        assert response.status_code == 502
        assert "secret-fixture-123" not in response.text


def test_saved_skills_survive_summary_and_session_restore_without_formal_plan(tmp_path: Path) -> None:
    with client_for(tmp_path) as client:
        start = client.post("/session/start", json={
            "workspace_id": "workspace-skills", "workspace_name": "Skills",
        })
        assert start.status_code == 200, start.text
        session_id = start.json()["session_id"]
        skill = {"id": "custom-py-check", "trigger": "$py-check", "title": "Python check",
                 "detail": "Check one issue", "prompt": "Check the submitted code", "keywords": []}
        saved = client.post("/memory/settings", json={
            "workspace_id": "workspace-skills", "session_id": session_id,
            "coach_defaults": {"workingSetMode": "focused", "customSkills": [skill]},
        })
        assert saved.status_code == 200, saved.text
        for response in (
            saved,
            client.get("/memory/summary", params={"workspace_id": "workspace-skills"}),
            client.post("/session/start", json={"workspace_id": "workspace-skills", "workspace_name": "Skills"}),
        ):
            assert response.status_code == 200, response.text
            defaults = response.json()["memory"]["workspace"]["coach_defaults"]
            assert defaults["custom_skills"][0]["trigger"] == "$py-check"
            assert defaults["working_set_mode"] == "focused"
