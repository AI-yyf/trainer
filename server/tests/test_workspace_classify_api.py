"""API tests for POST /workspace/classify endpoint — §1.21 / §1.21.1."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient

from app.api.runtime import TrainerRuntime
from app.core.models import ProviderConfig, ProviderTestResponse, TrainerRoot
from app.core.settings import AppSettings
from app.llm.provider_service import ProviderService
from app.main import create_app


def build_client(tmp_path: Path, *, configure_provider: bool = True) -> TestClient:
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
    app = create_app(settings)
    if configure_provider:
        provider = ProviderConfig(
            name="test-openai-compatible",
            base_url="http://127.0.0.1:9/v1",
            api_key_ref="trainer.default",
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
        runtime = app.state.runtime
        runtime.provider_config = provider
        runtime.provider_api_key = "sk-test"
        runtime.provider_service = ProviderService(config=provider, api_key="sk-test")
        runtime.provider_service_cache.clear()
    return TestClient(app)


def _wait_for_adoption_completion(
    client: TestClient,
    *,
    workspace_id: str,
    root_path: Path,
    job_id: str,
    timeout_s: float = 5.0,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout_s
    root_path_str = str(root_path)
    while time.monotonic() < deadline:
        status = client.get(
            "/workspace/adoption-job",
            params={
                "workspace_id": workspace_id,
                "root_path": root_path_str,
                "job_id": job_id,
            },
        )
        assert status.status_code == 200, status.text
        payload = status.json()
        job = payload["project_adoption_job"]
        if job["status"] == "completed":
            return payload
        if job["status"] in {"interrupted", "retry_required"}:
            raise AssertionError(f"adoption job did not complete: {job}")
        time.sleep(0.05)
    raise AssertionError("timed out waiting for project adoption to complete")


def test_classify_registers_selected_root_identity(tmp_path: Path) -> None:
    root = tmp_path / "trainer-root"
    project = tmp_path / "project"
    root.mkdir()
    project.mkdir()
    with build_client(tmp_path, configure_provider=False) as client:
        response = client.post(
            "/workspace/classify",
            json={"workspace_id": "windows-shaped", "folder_path": str(project), "root_path": str(root)},
        )
        assert response.status_code == 200, response.text
        identity = response.json()["root_identity"]
        assert identity["rootId"].startswith("root-")
        assert Path(identity["rootPath"]) == root.resolve()
        stored = client.app.state.runtime.repository.get_trainer_root(identity["rootId"])
        assert stored is not None
        assert Path(stored.root_path) == root.resolve()


def test_classify_empty_directory(tmp_path: Path) -> None:
    """POST /workspace/classify on empty directory returns empty_new_project."""
    with build_client(tmp_path) as client:
        empty_dir = tmp_path / "empty_ws"
        empty_dir.mkdir()
        response = client.post(
            "/workspace/classify",
            json={"folder_path": str(empty_dir)},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["folder_role"] == "empty_new_project"
    assert payload["confidence"] >= 0.7
    assert payload["project_type_guess"] == "unknown"
    assert payload["classification_method"] == "heuristic"
    # All §1.21.1 fields present
    for field_name in [
        "folder_role",
        "project_type_guess",
        "confidence",
        "why_this_guess",
        "entry_points",
        "directory_anchors",
        "core_modules_or_materials",
        "risk_zones",
        "training_opportunities",
        "unknowns",
        "recommended_next_step",
        "classified_at",
        "classification_method",
    ]:
        assert field_name in payload, f"Missing field: {field_name}"


def test_classify_python_project(tmp_path: Path) -> None:
    """POST /workspace/classify on a Python project detects engineering + API."""
    with build_client(tmp_path) as client:
        project_dir = tmp_path / "python_api"
        project_dir.mkdir()
        (project_dir / "requirements.txt").write_text("fastapi\nuvicorn\n")
        (project_dir / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n")
        (project_dir / "app").mkdir()
        (project_dir / "app" / "__init__.py").write_text("")
        (project_dir / "app" / "routes.py").write_text("# routes")

        response = client.post(
            "/workspace/classify",
            json={"folder_path": str(project_dir)},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["folder_role"] == "existing_engineering"
    assert payload["project_type_guess"] == "api_service"
    assert payload["confidence"] >= 0.5
    assert len(payload["entry_points"]) > 0
    assert len(payload["training_opportunities"]) > 0


def test_classify_uses_llm_after_provider_connection_is_verified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A successful provider probe permits LLM refinement for the same override."""
    provider_calls: list[ProviderService] = []

    def fake_provider_test(
        _service: ProviderService,
        _provider: ProviderConfig,
        _api_key: str | None,
        *,
        probe_message: str | None = None,
        response_language: str | None = None,
    ) -> ProviderTestResponse:
        del probe_message, response_language
        return ProviderTestResponse(ok=True, detail="mocked provider connection")

    async def fake_chat_completion(
        service: ProviderService,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> str:
        del messages, model, temperature, max_tokens
        provider_calls.append(service)
        return json.dumps(
            {
                "folder_role": "existing_engineering",
                "project_type_guess": "api_service",
                "confidence": 0.91,
                "why_this_guess": "Mock provider refined the API classification.",
                "risk_zones": ["Missing integration tests."],
                "training_opportunities": ["Add an API smoke test."],
                "unknowns": [],
                "recommended_next_step": "Add one endpoint test.",
            }
        )

    monkeypatch.setattr(ProviderService, "test", fake_provider_test)
    monkeypatch.setattr(ProviderService, "chat_completion", fake_chat_completion)

    with build_client(tmp_path) as client:
        runtime = cast(TrainerRuntime, cast(Any, client.app).state.runtime)
        provider = runtime.provider_config
        assert provider is not None
        provider_payload = provider.model_dump(mode="json", by_alias=True)
        request_payload = {
            "folder_path": str(tmp_path),
            "provider": provider_payload,
            "api_key": "workspace-classify-test-key",
        }

        provider_test = client.post("/provider/test", json=request_payload)
        cache_size_after_probe = len(runtime.provider_service_cache)
        response = client.post("/workspace/classify", json=request_payload)

    assert provider_test.status_code == 200
    assert provider_test.json()["ok"] is True
    assert response.status_code == 200
    assert response.json()["classification_method"] == "llm_enhanced"
    assert response.json()["why_this_guess"] == "Mock provider refined the API classification."
    assert len(provider_calls) == 1
    assert provider_calls[0]._config is not None  # noqa: SLF001 - assert selected override
    assert provider_calls[0]._config.model == provider.model  # noqa: SLF001
    assert provider_calls[0]._api_key == "workspace-classify-test-key"  # noqa: SLF001
    assert len(runtime.provider_service_cache) == cache_size_after_probe
    assert "workspace-classify-test-key" not in response.text


def test_classify_never_calls_unverified_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Configured credentials alone are insufficient to invoke a model."""
    calls = 0

    async def fail_if_called(
        _service: ProviderService,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> str:
        nonlocal calls
        del messages, model, temperature, max_tokens
        calls += 1
        raise AssertionError("unverified provider must not be called")

    monkeypatch.setattr(ProviderService, "chat_completion", fail_if_called)

    with build_client(tmp_path) as client:
        response = client.post("/workspace/classify", json={"folder_path": str(tmp_path)})

    assert response.status_code == 200
    assert response.json()["classification_method"] == "heuristic"
    assert calls == 0


def test_classify_falls_back_when_verified_provider_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An LLM exception never upgrades a heuristic response."""
    calls = 0

    async def fail_chat_completion(
        _service: ProviderService,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> str:
        nonlocal calls
        del messages, model, temperature, max_tokens
        calls += 1
        raise RuntimeError("mock model failure")

    monkeypatch.setattr(ProviderService, "chat_completion", fail_chat_completion)

    with build_client(tmp_path) as client:
        runtime = cast(TrainerRuntime, cast(Any, client.app).state.runtime)
        provider = runtime.provider_config
        assert provider is not None
        runtime.remember_provider_capability_test(
            provider,
            "sk-test",
            ProviderTestResponse(ok=True, detail="mocked provider connection"),
        )
        response = client.post("/workspace/classify", json={"folder_path": str(tmp_path)})

    assert response.status_code == 200
    assert response.json()["classification_method"] == "heuristic"
    assert calls == 1


@pytest.mark.parametrize(
    ("language_field", "response_language"),
    [
        ("response_language", "ja-JP"),
        ("responseLanguage", "pt-BR"),
    ],
)
def test_classify_accepts_response_language_aliases_and_persists_localized_summary_after_adopt(
    tmp_path: Path,
    language_field: str,
    response_language: str,
) -> None:
    workspace_root = tmp_path / "trainer-workspace"
    project_dir = workspace_root / "Projects" / "localized-project"
    project_dir.mkdir(parents=True)
    (project_dir / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    (project_dir / "main.py").write_text("from fastapi import FastAPI\n", encoding="utf-8")
    workspace_id = f"workspace-localized-{response_language}"

    with build_client(tmp_path) as client:
        runtime = client.app.state.runtime
        default_response = client.post(
            "/workspace/classify",
            json={
                "workspace_id": workspace_id,
                "folder_path": str(project_dir),
                "root_path": str(workspace_root),
            },
        )
        localized_response = client.post(
            "/workspace/classify",
            json={
                "workspace_id": workspace_id,
                "folder_path": str(project_dir),
                "root_path": str(workspace_root),
                language_field: response_language,
            },
        )
        pre_adopt_snapshot = runtime.memory_service.snapshot(workspace_id).workspace_understanding
        classified_payload = localized_response.json()
        discovery_id = classified_payload["project_discovery"]["discovery_id"]
        adopt_response = client.post(
            "/workspace/discovery/decision",
            json={
                "workspace_id": workspace_id,
                "discovery_id": discovery_id,
                "decision": "adopt",
                "root_path": str(workspace_root),
            },
        )
        adopt_payload = adopt_response.json()
        adoption_payload = adopt_payload
        if adopt_payload["project_adoption_job"]["status"] != "completed":
            adoption_payload = _wait_for_adoption_completion(
                client,
                workspace_id=workspace_id,
                root_path=workspace_root,
                job_id=adopt_payload["project_adoption_job"]["job_id"],
            )
        provisioning = adoption_payload["project_provisioning"]
        adopted_snapshot = runtime.memory_service.snapshot(provisioning["workspace_id"]).workspace_understanding

    assert default_response.status_code == 200
    assert localized_response.status_code == 200
    assert adopt_response.status_code == 200
    default_payload = default_response.json()
    localized_payload = classified_payload
    assert localized_payload["why_this_guess"] != default_payload["why_this_guess"]
    assert localized_payload["recommended_next_step"] != default_payload["recommended_next_step"]
    assert pre_adopt_snapshot is None
    assert adopted_snapshot is not None
    assert adopted_snapshot.first_look_summary is not None
    assert adopted_snapshot.first_look_summary.why_this_guess == localized_payload["why_this_guess"]
    assert adopted_snapshot.first_look_summary.recommended_next_step == localized_payload["recommended_next_step"]


def test_classify_root_conflicts_return_safe_error_contract(tmp_path: Path) -> None:
    workspace_root = tmp_path / "trainer-workspace"
    workspace_root.mkdir()
    with build_client(tmp_path) as client:
        missing = client.post(
            "/workspace/classify",
            json={"folder_path": str(tmp_path / "project"), "root_path": str(tmp_path / "missing-root")},
        )
        assert missing.status_code == 409
        assert missing.json()["detail"] == {
            "code": "root_path_unavailable",
            "category": "workspace_root",
            "path_state": "unavailable",
            "message": "The selected Trainer workspace root is unavailable.",
        }

        runtime = client.app.state.runtime
        root = runtime.repository.register_trainer_root(
            TrainerRoot(root_id="root-test", root_path=str(workspace_root), display_name="Test root")
        )
        other_root = tmp_path / "other-root"
        other_root.mkdir()
        mismatch = client.post(
            "/workspace/classify",
            json={
                "folder_path": str(tmp_path / "project"),
                "root_id": root.root_id,
                "root_path": str(other_root),
            },
        )
        assert mismatch.status_code == 409
        detail = mismatch.json()["detail"]
        assert detail["code"] == "root_id_mismatch"
        assert detail["category"] == "workspace_root"
        assert detail["path_state"] == "unknown"
        assert "other-root" not in str(detail)


def test_classify_nonexistent_path_returns_gracefully(tmp_path: Path) -> None:
    """POST /workspace/classify on a nonexistent path returns a valid response, not 500."""
    with build_client(tmp_path) as client:
        response = client.post(
            "/workspace/classify",
            json={"folder_path": str(tmp_path / "does_not_exist")},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["folder_role"] == "empty_new_project"
    assert "does not exist" in payload["why_this_guess"]
    assert payload["classification_method"] == "heuristic"


def test_classify_remote_snapshot_does_not_look_empty(tmp_path: Path) -> None:
    with build_client(tmp_path, configure_provider=False) as client:
        response = client.post(
            "/workspace/classify",
            json={
                "folder_path": "/mnt/vdb1/yunfei.yan/RAP",
                "remote_name": "ssh-remote",
                "workspace_file_snapshot": {
                    "is_remote": True,
                    "files": [
                        {"path": "README.md"},
                        {"path": "setup.py"},
                        {"path": "requirements.txt"},
                        {"path": "navsim/agents/abstract_agent.py"},
                    ],
                },
            },
        )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["folder_role"] != "empty_new_project"
    discovery = payload["project_discovery"]
    assert discovery["status"] == "awaiting_decision"
    assert discovery["is_browse_only"] is True
    assert "adopt" not in discovery["available_decisions"]
    assert discovery["project_path"] == "/mnt/vdb1/yunfei.yan/RAP"


def test_remote_discovery_browse_does_not_require_a_local_directory(tmp_path: Path) -> None:
    with build_client(tmp_path, configure_provider=False) as client:
        classified = client.post(
            "/workspace/classify",
            json={
                "workspace_id": "workspace-remote-browse",
                "folder_path": "/mnt/vdb1/yunfei.yan/RAP",
                "remote_name": "ssh-remote",
                "workspace_file_snapshot": {
                    "is_remote": True,
                    "files": [{"path": "README.md"}, {"path": "setup.py"}],
                },
            },
        )
        assert classified.status_code == 200, classified.text
        discovery_id = classified.json()["project_discovery"]["discovery_id"]
        adopted = client.post(
            "/workspace/discovery/decision",
            json={
                "workspace_id": "workspace-remote-browse",
                "discovery_id": discovery_id,
                "decision": "adopt",
            },
        )
        browsed = client.post(
            "/workspace/discovery/decision",
            json={
                "workspace_id": "workspace-remote-browse",
                "discovery_id": discovery_id,
                "decision": "browse",
            },
        )
    assert browsed.status_code == 200, browsed.text
    discovery = browsed.json()["project_discovery"]
    assert discovery["status"] == "browse_only"
    assert discovery["selected_decision"] == "browse"
    assert discovery["is_managed"] is False
    assert Path("/mnt/vdb1/yunfei.yan/RAP").exists() is False
    assert adopted.status_code == 409
    assert "cannot be adopted" in adopted.text
    assert Path("/mnt/vdb1/yunfei.yan/RAP").exists() is False


def test_classify_returns_non_owning_discovery_without_replacing_workspace_root(
    tmp_path: Path,
) -> None:
    """Classification observes a candidate and never silently adopts its root."""
    with build_client(tmp_path) as client:
        workspace_root = tmp_path / "trainer-workspace"
        candidate = tmp_path / "external-project"
        workspace_root.mkdir()
        candidate.mkdir()
        (candidate / "README.md").write_text("# Candidate\n", encoding="utf-8")
        runtime = client.app.state.runtime
        runtime.register_workspace_path("workspace-discovery", str(workspace_root))

        response = client.post(
            "/workspace/classify",
            json={
                "workspace_id": "workspace-discovery",
                "folder_path": str(candidate),
            },
        )

    assert response.status_code == 200
    payload = response.json()
    discovery = payload["project_discovery"]
    assert discovery["status"] == "awaiting_decision"
    assert discovery["available_decisions"] == ["adopt", "browse", "ignore"]
    assert discovery["is_managed"] is False
    assert discovery["persistent_memory_created"] is False
    assert discovery["trusted_boundary"] is False
    assert runtime.resolve_workspace_path("workspace-discovery") == str(workspace_root)


def test_discovery_browse_is_read_only_inside_configured_workspace_root(tmp_path: Path) -> None:
    """Browse can only open an in-root candidate and creates no project state."""
    with build_client(tmp_path) as client:
        workspace_root = tmp_path / "trainer-workspace"
        project = workspace_root / "Projects" / "browse-only"
        project.mkdir(parents=True)
        (project / "main.py").write_text("print('browse')\n", encoding="utf-8")
        runtime = client.app.state.runtime
        runtime.register_workspace_path("workspace-browse", str(workspace_root))

        classified = client.post(
            "/workspace/classify",
            json={"workspace_id": "workspace-browse", "folder_path": str(project)},
        )
        discovery_id = classified.json()["project_discovery"]["discovery_id"]
        response = client.post(
            "/workspace/discovery/decision",
            json={
                "workspace_id": "workspace-browse",
                "discovery_id": discovery_id,
                "decision": "browse",
            },
        )

    assert classified.status_code == 200
    assert response.status_code == 200
    discovery = response.json()["project_discovery"]
    assert discovery["status"] == "browse_only"
    assert discovery["selected_decision"] == "browse"
    assert discovery["trusted_boundary"] is True
    assert discovery["is_browse_only"] is True
    assert discovery["is_managed"] is False
    assert discovery["persistent_memory_created"] is False
    assert runtime.get_project_provisioning("workspace-browse") is None
    assert runtime.memory_service.snapshot("workspace-browse").workspace_understanding is None
    assert not (project / ".trainer").exists()
    assert runtime.resolve_workspace_path("workspace-browse") == str(workspace_root)


def test_discovery_adopt_provisions_server_created_project_lane(tmp_path: Path) -> None:
    """Adoption creates durable server-owned evidence and ignores client IDs."""
    with build_client(tmp_path) as client:
        workspace_root = tmp_path / "trainer-workspace"
        project = workspace_root / "Projects" / "adopt-me"
        project.mkdir(parents=True)
        (project / "pyproject.toml").write_text("[project]\nname = 'adopt-me'\n", encoding="utf-8")
        runtime = client.app.state.runtime
        runtime.register_workspace_path("workspace-adopt", str(workspace_root))

        classified = client.post(
            "/workspace/classify",
            json={"workspace_id": "workspace-adopt", "folder_path": str(project)},
        )
        discovery_id = classified.json()["project_discovery"]["discovery_id"]
        response = client.post(
            "/workspace/discovery/decision",
            json={
                "workspace_id": "workspace-adopt",
                "discovery_id": discovery_id,
                "decision": "adopt",
                "provisioning": {
                    "project_id": "client-claimed-project",
                    "project_memory_id": "client-claimed-memory",
                },
            },
        )

    assert classified.status_code == 200
    assert response.status_code == 200
    adopt_payload = response.json()
    payload = adopt_payload
    if adopt_payload["project_adoption_job"]["status"] != "completed":
        payload = _wait_for_adoption_completion(
            client,
            workspace_id="workspace-adopt",
            root_path=workspace_root,
            job_id=adopt_payload["project_adoption_job"]["job_id"],
        )
    discovery = payload["project_discovery"]
    provisioning = payload["project_provisioning"]
    assert discovery["status"] == "adopted"
    assert discovery["selected_decision"] == "adopt"
    assert discovery["provisioning_required"] is False
    assert discovery["is_managed"] is True
    assert discovery["persistent_memory_created"] is True
    assert provisioning["project_id"] != "client-claimed-project"
    assert provisioning["project_memory_id"] != "client-claimed-memory"
    assert discovery["adoption_artifacts"] == {
        "project_id": provisioning["project_id"],
        "project_memory_id": provisioning["project_memory_id"],
        "project_plan_id": provisioning["project_plan_id"],
        "project_training_id": provisioning["project_training_id"],
        "project_agent_context_id": provisioning["project_agent_context_id"],
    }
    assert runtime.repository.load_session(provisioning["agent_session_id"]) is not None
    # Adoption creates a plan-lane identity without minting a LearningPlan.
    assert runtime.repository.get_plan_by_id(provisioning["project_plan_id"]) is None
    assert runtime.repository.get_latest_plan(provisioning["context_id"]) is None


def test_discovery_browse_keeps_a_distinct_project_separate_from_trainer_root(tmp_path: Path) -> None:
    """A selected code project may live outside Trainer's data-root container."""
    with build_client(tmp_path) as client:
        workspace_root = tmp_path / "trainer-workspace"
        candidate = tmp_path / "separate-code-project"
        workspace_root.mkdir()
        candidate.mkdir()

        classified = client.post(
            "/workspace/classify",
            json={
                "workspace_id": "workspace-boundary",
                "folder_path": str(candidate),
                "root_path": str(workspace_root),
            },
        )
        discovery_id = classified.json()["project_discovery"]["discovery_id"]
        response = client.post(
            "/workspace/discovery/decision",
            json={
                "workspace_id": "workspace-boundary",
                "discovery_id": discovery_id,
                "decision": "browse",
                "root_path": str(workspace_root),
            },
        )

    assert classified.status_code == 200
    assert response.status_code == 200
    discovery = response.json()["project_discovery"]
    assert discovery["status"] == "browse_only"
    assert discovery["trusted_boundary"] is True


def test_discovery_browse_requires_a_preconfigured_workspace_root(tmp_path: Path) -> None:
    """A discovered folder cannot become browseable just because it was classified."""
    with build_client(tmp_path) as client:
        candidate = tmp_path / "unconfigured-project"
        candidate.mkdir()

        classified = client.post(
            "/workspace/classify",
            json={"workspace_id": "workspace-unconfigured", "folder_path": str(candidate)},
        )
        discovery_id = classified.json()["project_discovery"]["discovery_id"]
        response = client.post(
            "/workspace/discovery/decision",
            json={
                "workspace_id": "workspace-unconfigured",
                "discovery_id": discovery_id,
                "decision": "browse",
            },
        )

    assert classified.status_code == 200
    assert response.status_code == 403
    assert str(candidate) not in response.json()["detail"]


def test_discovery_id_is_scoped_to_its_workspace(tmp_path: Path) -> None:
    """One workspace cannot use another workspace's discovery record."""
    with build_client(tmp_path) as client:
        candidate = tmp_path / "private-project"
        candidate.mkdir()

        classified = client.post(
            "/workspace/classify",
            json={"workspace_id": "workspace-owner", "folder_path": str(candidate)},
        )
        discovery_id = classified.json()["project_discovery"]["discovery_id"]
        response = client.post(
            "/workspace/discovery/decision",
            json={
                "workspace_id": "workspace-other",
                "discovery_id": discovery_id,
                "decision": "ignore",
            },
        )

    assert classified.status_code == 200
    assert response.status_code == 404
    assert str(candidate) not in response.json()["detail"]


def test_discovery_ignore_does_not_require_workspace_authority(tmp_path: Path) -> None:
    """Ignore remains available for an unconfigured workspace and creates no state."""
    with build_client(tmp_path) as client:
        candidate = tmp_path / "ignored-project"
        candidate.mkdir()

        classified = client.post("/workspace/classify", json={"folder_path": str(candidate)})
        discovery_id = classified.json()["project_discovery"]["discovery_id"]
        response = client.post(
            "/workspace/discovery/decision",
            json={"discovery_id": discovery_id, "decision": "ignore"},
        )

    assert classified.status_code == 200
    assert response.status_code == 200
    discovery = response.json()["project_discovery"]
    assert discovery["status"] == "ignored"
    assert discovery["is_managed"] is False
    assert discovery["persistent_memory_created"] is False
    assert client.app.state.runtime.get_project_provisioning("workspace-ignored") is None
    assert client.app.state.runtime.memory_service.snapshot("workspace-ignored").workspace_understanding is None
    assert not (candidate / ".trainer").exists()


def test_discovery_adopt_returns_promptly_before_slow_inventory_finishes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with build_client(tmp_path) as client:
        workspace_root = tmp_path / "trainer-workspace"
        project = workspace_root / "Projects" / "slow-adopt"
        project.mkdir(parents=True)
        (project / "package.json").write_text('{"name":"slow-adopt"}', encoding="utf-8")
        runtime = client.app.state.runtime
        runtime.register_workspace_path("workspace-slow-adopt", str(workspace_root))

        import threading

        ready = threading.Event()
        original_scan = runtime.project_adoption_index_service._scan_project

        def slow_scan(project_path: str) -> dict[str, object]:
            ready.wait(timeout=2.0)
            return original_scan(project_path)

        monkeypatch.setattr(runtime.project_adoption_index_service, "_scan_project", slow_scan)

        classified = client.post(
            "/workspace/classify",
            json={"workspace_id": "workspace-slow-adopt", "folder_path": str(project)},
        )
        discovery_id = classified.json()["project_discovery"]["discovery_id"]
        started_at = time.monotonic()
        response = client.post(
            "/workspace/discovery/decision",
            json={
                "workspace_id": "workspace-slow-adopt",
                "discovery_id": discovery_id,
                "decision": "adopt",
                "root_path": str(workspace_root),
            },
        )
        elapsed = time.monotonic() - started_at
        job_id = response.json()["project_adoption_job"]["job_id"]
        status = client.get(
            "/workspace/adoption-job",
            params={
                "workspace_id": "workspace-slow-adopt",
                "root_path": str(workspace_root),
                "job_id": job_id,
            },
        )
        ready.set()
        completed = _wait_for_adoption_completion(
            client,
            workspace_id="workspace-slow-adopt",
            root_path=workspace_root,
            job_id=job_id,
        )

    assert classified.status_code == 200
    assert response.status_code == 200
    assert elapsed < 1.0
    assert response.json()["project_adoption_job"]["status"] in {"queued", "running"}
    assert status.status_code == 200
    assert status.json()["project_adoption_job"]["status"] in {"queued", "running"}
    assert completed["project_adoption_job"]["status"] == "completed"
    assert completed["project_provisioning"]["project_path"] == str(project.resolve())


@pytest.mark.parametrize("decision", ["browse", "ignore"])
def test_discovery_browse_and_ignore_do_not_enqueue_adoption_job(
    tmp_path: Path,
    decision: str,
) -> None:
    with build_client(tmp_path) as client:
        workspace_root = tmp_path / "trainer-workspace"
        project = workspace_root / "Projects" / f"{decision}-only"
        project.mkdir(parents=True)
        (project / "package.json").write_text(f'{{"name":"{decision}-only"}}', encoding="utf-8")
        runtime = client.app.state.runtime
        runtime.register_workspace_path(f"workspace-{decision}", str(workspace_root))

        classified = client.post(
            "/workspace/classify",
            json={"workspace_id": f"workspace-{decision}", "folder_path": str(project)},
        )
        discovery_id = classified.json()["project_discovery"]["discovery_id"]
        response = client.post(
            "/workspace/discovery/decision",
            json={
                "workspace_id": f"workspace-{decision}",
                "discovery_id": discovery_id,
                "decision": decision,
                "root_path": str(workspace_root),
            },
        )

    assert classified.status_code == 200
    assert response.status_code == 200
    payload = response.json()
    assert "project_adoption_job" not in payload
    assert payload["project_discovery"]["status"] in {"browse_only", "ignored"}
    assert not (workspace_root / ".trainer" / "indexes").exists()


def test_add_project_contract_completes_and_rehydrates_provisioning(tmp_path: Path) -> None:
    """The Extension Host add-project sequence completes across all workspace routes."""
    workspace_root = tmp_path / "trainer-workspace"
    workspace_root.mkdir()
    project = tmp_path / "external-project"
    project.mkdir()
    (project / "pyproject.toml").write_text("[project]\nname = 'external-project'\n", encoding="utf-8")

    with build_client(tmp_path, configure_provider=False) as client:
        workspace_id = "workspace-add-project-contract"
        client.app.state.runtime.register_workspace_path(workspace_id, str(workspace_root))
        classified = client.post(
            "/workspace/classify",
            json={
                "workspace_id": workspace_id,
                "folder_path": str(project),
                "root_path": str(workspace_root),
            },
        )
        assert classified.status_code == 200
        discovery = classified.json()["project_discovery"]
        assert discovery["status"] == "awaiting_decision"
        assert discovery["is_managed"] is False

        decision = client.post(
            "/workspace/discovery/decision",
            json={
                "workspace_id": workspace_id,
                "discovery_id": discovery["discovery_id"],
                "decision": "adopt",
                "root_path": str(workspace_root),
            },
        )
        assert decision.status_code == 200
        payload = decision.json()
        job = payload["project_adoption_job"]
        if job["status"] != "completed":
            payload = _wait_for_adoption_completion(
                client,
                workspace_id=workspace_id,
                root_path=workspace_root,
                job_id=job["job_id"],
            )

        provisioning = payload["project_provisioning"]
        identity = payload["project_identity"]
        lookup = client.get(
            "/workspace/project-provisioning",
            params={"workspace_id": workspace_id},
        )

    assert payload["project_adoption_job"]["status"] == "completed"
    assert payload["project_discovery"]["status"] == "adopted"
    assert provisioning["project_path"] == str(project.resolve())
    assert provisioning["root_path"] == str(workspace_root.resolve())
    assert identity["canonicalProjectPath"] == str(project.resolve())
    assert identity["canonicalRootPath"] == str(workspace_root.resolve())
    assert identity["projectId"] == provisioning["project_id"]
    assert identity["contextId"] == provisioning["context_id"]
    assert lookup.status_code == 200
    assert lookup.json()["project_provisioning"] == provisioning
    assert "api_key" not in decision.text.lower()


def test_discovery_adopt_inventory_skips_git_and_node_modules(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        workspace_root = tmp_path / "trainer-workspace"
        project = workspace_root / "Projects" / "inventory-project"
        project.mkdir(parents=True)
        (project / "package.json").write_text('{"name":"inventory-project"}', encoding="utf-8")
        (project / "src").mkdir()
        (project / "src" / "app.py").write_text("print('ok')\n", encoding="utf-8")
        (project / ".git").mkdir()
        (project / ".git" / "config").write_text("[core]\nrepositoryformatversion = 0\n", encoding="utf-8")
        (project / "node_modules").mkdir()
        (project / "node_modules" / "ignored.js").write_text("console.log('ignore')\n", encoding="utf-8")
        runtime = client.app.state.runtime
        runtime.register_workspace_path("workspace-inventory", str(workspace_root))

        classified = client.post(
            "/workspace/classify",
            json={"workspace_id": "workspace-inventory", "folder_path": str(project)},
        )
        discovery_id = classified.json()["project_discovery"]["discovery_id"]
        adopted = client.post(
            "/workspace/discovery/decision",
            json={
                "workspace_id": "workspace-inventory",
                "discovery_id": discovery_id,
                "decision": "adopt",
                "root_path": str(workspace_root),
            },
        )
        payload = adopted.json()
        if payload["project_adoption_job"]["status"] != "completed":
            payload = _wait_for_adoption_completion(
                client,
                workspace_id="workspace-inventory",
                root_path=workspace_root,
                job_id=payload["project_adoption_job"]["job_id"],
            )

    files = payload["project_adoption_job"]["inventory"]["files"]
    assert "src/app.py" in files
    assert "package.json" in files
    assert not any(path.startswith(".git/") or "/.git/" in path for path in files)
    assert not any(path.startswith("node_modules/") or "/node_modules/" in path for path in files)
