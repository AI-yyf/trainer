from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.event_ledger import EventLedgerService
from app.core.models import ResourceRecord
from app.llm.tools import ToolContext, build_default_tool_registry
from app.sandbox.service import SandboxService
from app.workspace.authority import PermissionLevel, WorkspaceAuthority


def _context(
    runtime: object,
    *,
    host_confirmed: bool = False,
    workspace_id: str = "workspace-resource-organize",
) -> ToolContext:
    extra: dict[str, object] = {
        "active_view": "resources",
        "resource_composer_intent": {"mode": "organize"},
    }
    if host_confirmed:
        extra["resource_organization_confirmed"] = True
    return ToolContext(
        runtime=runtime,
        workspace_id=workspace_id,
        session_id="session-resource-organize",
        extra=extra,
    )


def _authority_wired_sandbox(
    tmp_path: Path,
    *,
    workspace_id: str,
    workspace_trusted: bool,
    remote_name: str = "",
) -> tuple[SandboxService, WorkspaceAuthority, Path, Path, EventLedgerService]:
    """Sandbox + project authority under the post-landing destructive gate."""
    project_root = tmp_path / f"project-{workspace_id}"
    project_root.mkdir()
    # Sentinel: organize must never mutate the opened project root.
    project_sentinel = project_root / "user-project.txt"
    project_sentinel.write_text("project-owned", encoding="utf-8")
    project_authority = WorkspaceAuthority(
        root_path=str(project_root),
        initial_permission=PermissionLevel.INSPECT,
        remote_name=remote_name or None,
    )
    project_authority.set_workspace_context(workspace_trusted=workspace_trusted)
    ledger = EventLedgerService()
    sandbox = SandboxService(
        data_root=tmp_path / f"data-{workspace_id}",
        event_ledger=ledger,
        workspace_path_resolver=lambda _workspace_id: str(project_root),
        workspace_authority_resolver=lambda _workspace_id: project_authority,
    )
    return sandbox, project_authority, project_root, project_sentinel, ledger


def _runtime(**kwargs: object) -> SimpleNamespace:
    base = {
        "event_ledger": None,
        "resource_organization_history": {},
        "resource_organization_pending": {},
        "resolve_workspace_path": lambda _workspace_id: None,
        "refresh_workspace_sessions": lambda _workspace_id: 0,
        "repository": SimpleNamespace(
            list_resources=lambda _workspace_id: [], save_resource=lambda *_args: None
        ),
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_organize_resources_is_proposal_first_and_supports_undo(tmp_path: Path) -> None:
    ledger = EventLedgerService()
    sandbox = SandboxService(data_root=tmp_path, event_ledger=ledger)
    workspace_id = "workspace-resource-organize"
    root = sandbox.ensure_workspace_root(workspace_id)
    source = root / "notes.md"
    source.write_text("notes", encoding="utf-8")

    runtime = _runtime(
        sandbox_service=sandbox,
        event_ledger=ledger,
    )
    registry = build_default_tool_registry()
    operations = [{"op": "move", "source": "notes.md", "target": "archive/notes.md"}]

    proposal = await registry.invoke(
        _context(runtime), "organize_resources", {"operations": operations}
    )
    assert proposal["ok"] is True
    assert proposal["committed"] is False
    assert proposal["requires_confirmation"] is True
    assert workspace_id in runtime.resource_organization_pending
    assert source.exists()
    assert not (root / "archive" / "notes.md").exists()

    unsafe = await registry.invoke(
        _context(runtime),
        "organize_resources",
        {"operations": [{"op": "move", "source": "../notes.md", "target": "escape.md"}]},
    )
    assert unsafe["ok"] is False
    assert unsafe["error"] == "invalid_path"

    self_attested = await registry.invoke(
        _context(runtime),
        "organize_resources",
        {"operations": operations, "confirmed": True},
    )
    assert self_attested["ok"] is False
    assert self_attested["error"] == "host_confirmation_required"
    assert self_attested["committed"] is False
    assert source.exists()
    assert not (root / "archive" / "notes.md").exists()

    committed = await registry.invoke(
        _context(runtime, host_confirmed=True),
        "organize_resources",
        {"operations": operations},
    )
    assert committed["ok"] is True
    assert committed["committed"] is True
    assert committed["undo_available"] is True
    assert workspace_id not in runtime.resource_organization_pending
    assert (root / "archive" / "notes.md").exists()
    assert not source.exists()
    assert ledger.query(event_type="sandbox_files_reorganized", project_id=workspace_id)

    undone = await registry.invoke(
        _context(runtime, host_confirmed=True),
        "organize_resources",
        {"undo_id": committed["history_id"]},
    )
    assert undone["ok"] is True
    assert undone["undone"] is True
    assert source.exists()
    assert not (root / "archive" / "notes.md").exists()


@pytest.mark.asyncio
async def test_organize_path_only_move_updates_matching_sandbox_record(tmp_path: Path) -> None:
    sandbox = SandboxService(data_root=tmp_path)
    workspace_id = "workspace-resource-organize-path-only"
    root = sandbox.ensure_workspace_root(workspace_id)
    source = root / "notes.md"
    source.write_text("notes about login error handling", encoding="utf-8")
    stored: list[ResourceRecord] = [
        ResourceRecord(
            id="resource-notes-path-only",
            kind="markdown",
            name="notes.md",
            source=str(source),
            summary="notes about login error handling",
            parse_status="parsed",
            index_status="indexed",
            sandbox_path=str(source.resolve()),
        )
    ]

    def save_resource(_workspace_id: str, resource: ResourceRecord) -> None:
        stored[0] = resource

    runtime = _runtime(
        sandbox_service=sandbox,
        repository=SimpleNamespace(
            list_resources=lambda _workspace_id: list(stored),
            save_resource=save_resource,
        ),
    )
    registry = build_default_tool_registry()
    operations = [{"op": "move", "source": "notes.md", "target": "archive/notes.md"}]
    proposal = await registry.invoke(
        _context(runtime, workspace_id=workspace_id),
        "organize_resources",
        {"operations": operations},
    )
    assert proposal["committed"] is False
    assert proposal["operations"][0]["resource_id"] == "resource-notes-path-only"

    committed = await registry.invoke(
        _context(runtime, host_confirmed=True, workspace_id=workspace_id),
        "organize_resources",
        {"operations": operations},
    )
    assert committed["ok"] is True
    assert committed["committed"] is True
    assert (root / "archive" / "notes.md").exists()
    assert not source.exists()
    assert stored[0].sandbox_path is not None
    assert Path(stored[0].sandbox_path).resolve() == (root / "archive" / "notes.md").resolve()
    assert stored[0].sandbox_dirty is False

    sandbox.sync_resource(workspace_id, stored[0])
    assert not source.exists()
    assert (root / "archive" / "notes.md").exists()


@pytest.mark.asyncio
async def test_organize_resources_autonomous_library_turn_commits_without_host_stamp(
    tmp_path: Path,
) -> None:
    sandbox = SandboxService(data_root=tmp_path)
    workspace_id = "workspace-resource-organize-autonomous"
    root = sandbox.ensure_workspace_root(workspace_id)
    source = root / "notes.md"
    source.write_text("notes", encoding="utf-8")
    runtime = _runtime(sandbox_service=sandbox)
    extra = {
        "active_view": "resources",
        "library_sandbox_work": True,
        "resource_composer_intent": {"mode": "organize"},
    }
    context = ToolContext(
        runtime=runtime,
        workspace_id=workspace_id,
        session_id="session-autonomous-organize",
        extra=extra,
    )
    result = await build_default_tool_registry().invoke(
        context,
        "organize_resources",
        {"operations": [{"op": "move", "source": "notes.md", "target": "archive/notes.md"}]},
    )
    assert result["ok"] is True
    assert result["committed"] is True
    assert (root / "archive" / "notes.md").exists()
    assert not source.exists()


@pytest.mark.asyncio
async def test_organize_resources_commit_uses_reviewed_pending_operations(tmp_path: Path) -> None:
    sandbox = SandboxService(data_root=tmp_path)
    workspace_id = "workspace-resource-organize"
    root = sandbox.ensure_workspace_root(workspace_id)
    source = root / "notes.md"
    source.write_text("notes", encoding="utf-8")
    runtime = _runtime(sandbox_service=sandbox)
    registry = build_default_tool_registry()
    reviewed = [{"op": "move", "source": "notes.md", "target": "archive/notes.md"}]
    proposal = await registry.invoke(
        _context(runtime), "organize_resources", {"operations": reviewed}
    )
    assert proposal["requires_confirmation"] is True

    committed = await registry.invoke(
        _context(runtime, host_confirmed=True),
        "organize_resources",
        {"operations": [{"op": "move", "source": "notes.md", "target": "elsewhere/notes.md"}]},
    )
    assert committed["ok"] is True
    assert committed["committed"] is True
    assert committed["operations"][0]["target"] == "archive/notes.md"
    assert (root / "archive" / "notes.md").exists()
    assert not source.exists()
    assert not (root / "elsewhere" / "notes.md").exists()


def test_batch_rename_works_when_sandbox_root_is_relative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.models import SandboxBatchRenameRequest, SandboxRenameRequest

    monkeypatch.chdir(tmp_path)
    sandbox = SandboxService(data_root=Path(".trainer-data"))
    workspace_id = "ws-relative-root"
    root = sandbox.ensure_workspace_root(workspace_id)
    assert root.is_absolute()
    source = root / "notes.md"
    source.write_text("notes", encoding="utf-8")
    result = sandbox.batch_rename(
        workspace_id,
        SandboxBatchRenameRequest(
            workspace_id=workspace_id,
            items=[SandboxRenameRequest(path="notes.md", new_path="archive/notes.md")],
            explicit_destructive_policy=True,
        ),
    )
    assert result.get("changes")
    assert (root / "archive" / "notes.md").exists()
    assert not source.exists()


@pytest.mark.asyncio
async def test_organize_resources_rejects_model_self_attested_confirmed(tmp_path: Path) -> None:
    sandbox = SandboxService(data_root=tmp_path)
    workspace_id = "workspace-resource-organize"
    root = sandbox.ensure_workspace_root(workspace_id)
    source = root / "notes.md"
    source.write_text("notes", encoding="utf-8")
    runtime = _runtime(sandbox_service=sandbox)
    result = await build_default_tool_registry().invoke(
        _context(runtime),
        "organize_resources",
        {"confirmed": True, "operations": [{"op": "delete", "path": "notes.md"}]},
    )
    assert result["ok"] is False
    assert result["error"] == "host_confirmation_required"
    assert result["committed"] is False
    assert source.exists()


@pytest.mark.asyncio
async def test_organize_resources_rejects_host_stamp_without_pending_proposal(
    tmp_path: Path,
) -> None:
    """Direct API resourceOrganizationConfirmed without a prior proposal must not commit."""
    sandbox = SandboxService(data_root=tmp_path)
    workspace_id = "workspace-resource-organize"
    root = sandbox.ensure_workspace_root(workspace_id)
    source = root / "notes.md"
    source.write_text("notes", encoding="utf-8")
    runtime = _runtime(sandbox_service=sandbox)
    result = await build_default_tool_registry().invoke(
        _context(runtime, host_confirmed=True),
        "organize_resources",
        {"operations": [{"op": "move", "source": "notes.md", "target": "archive/notes.md"}]},
    )
    assert result["ok"] is False
    assert result["error"] == "host_confirmation_required"
    assert result["committed"] is False
    assert result["requires_confirmation"] is True
    # Fail-closed: stamped call must not arm pending (would enable a second stamped commit).
    assert workspace_id not in runtime.resource_organization_pending
    assert source.exists()
    assert not (root / "archive" / "notes.md").exists()

    retry = await build_default_tool_registry().invoke(
        _context(runtime, host_confirmed=True),
        "organize_resources",
        {"operations": [{"op": "move", "source": "notes.md", "target": "archive/notes.md"}]},
    )
    assert retry["ok"] is False
    assert retry["error"] == "host_confirmation_required"
    assert source.exists()
    assert workspace_id not in runtime.resource_organization_pending


@pytest.mark.asyncio
async def test_organize_resources_cancel_clears_pending_and_stamp_fails_closed(
    tmp_path: Path,
) -> None:
    """Host cancel must clear server pending so a later stamp cannot commit."""
    sandbox = SandboxService(data_root=tmp_path)
    workspace_id = "workspace-resource-organize"
    root = sandbox.ensure_workspace_root(workspace_id)
    source = root / "notes.md"
    source.write_text("notes", encoding="utf-8")
    runtime = _runtime(sandbox_service=sandbox)
    registry = build_default_tool_registry()
    operations = [{"op": "move", "source": "notes.md", "target": "archive/notes.md"}]

    proposal = await registry.invoke(
        _context(runtime), "organize_resources", {"operations": operations}
    )
    assert proposal["requires_confirmation"] is True
    assert workspace_id in runtime.resource_organization_pending

    from app.llm.tools import _clear_resource_organization_pending

    _clear_resource_organization_pending(runtime, workspace_id)
    assert workspace_id not in runtime.resource_organization_pending

    stamped = await registry.invoke(
        _context(runtime, host_confirmed=True),
        "organize_resources",
        {"operations": operations},
    )
    assert stamped["ok"] is False
    assert stamped["error"] == "host_confirmation_required"
    assert stamped["committed"] is False
    assert workspace_id not in runtime.resource_organization_pending
    assert source.exists()
    assert not (root / "archive" / "notes.md").exists()


@pytest.mark.asyncio
async def test_organize_resources_cancel_while_confirm_in_flight_consume_fails_closed(
    tmp_path: Path,
) -> None:
    """Cancel that pops pending before commit must beat an in-flight stamped organize.

    Models the race: host stamp already on ToolContext, cancel clears pending,
    organize must consume-or-abort and must not mutate the sandbox.
    """
    sandbox = SandboxService(data_root=tmp_path)
    workspace_id = "workspace-resource-organize"
    root = sandbox.ensure_workspace_root(workspace_id)
    source = root / "notes.md"
    source.write_text("notes", encoding="utf-8")
    runtime = _runtime(sandbox_service=sandbox)
    registry = build_default_tool_registry()
    operations = [{"op": "move", "source": "notes.md", "target": "archive/notes.md"}]

    proposal = await registry.invoke(
        _context(runtime), "organize_resources", {"operations": operations}
    )
    assert proposal["requires_confirmation"] is True
    assert workspace_id in runtime.resource_organization_pending

    from app.llm.tools import _consume_resource_organization_pending

    # Cancel wins: pending is gone before the stamped organize starts FS work.
    stolen = _consume_resource_organization_pending(runtime, workspace_id)
    assert stolen is not None
    assert workspace_id not in runtime.resource_organization_pending

    stamped = await registry.invoke(
        _context(runtime, host_confirmed=True),
        "organize_resources",
        {"operations": operations},
    )
    assert stamped["ok"] is False
    assert stamped["error"] == "host_confirmation_required"
    assert stamped.get("committed") is False
    assert source.exists()
    assert not (root / "archive" / "notes.md").exists()
    assert workspace_id not in runtime.resource_organization_pending

    # Successful confirm path still consumes pending then commits once.
    reproposal = await registry.invoke(
        _context(runtime), "organize_resources", {"operations": operations}
    )
    assert reproposal["requires_confirmation"] is True
    committed = await registry.invoke(
        _context(runtime, host_confirmed=True),
        "organize_resources",
        {"operations": operations},
    )
    assert committed["ok"] is True
    assert committed["committed"] is True
    assert not source.exists()
    assert (root / "archive" / "notes.md").exists()
    assert workspace_id not in runtime.resource_organization_pending


@pytest.mark.asyncio
async def test_resource_organization_cancel_route_clears_server_pending(
    tmp_path: Path,
) -> None:
    from fastapi.testclient import TestClient

    from app.core.settings import AppSettings
    from app.main import create_app

    settings = AppSettings(
        app_name="Trainer Organize Cancel Tests",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path,
        database_name="trainer-organize-cancel.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )
    app = create_app(settings)
    client = TestClient(app)
    runtime = app.state.runtime
    workspace_id = "workspace-organize-cancel-route"
    runtime.resource_organization_pending[workspace_id] = {
        "operations": [{"op": "move", "source": "a.md", "target": "b/a.md"}]
    }

    response = client.post(
        "/resource/organization/cancel",
        json={"workspace_id": workspace_id},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["cleared"] is True
    assert body.get("cancelled") is True
    assert body.get("already_committed") is False
    assert workspace_id not in runtime.resource_organization_pending

    again = client.post(
        "/resource/organization/cancel",
        json={"workspace_id": workspace_id},
    )
    assert again.status_code == 200
    assert again.json()["cleared"] is False
    assert again.json().get("already_committed") is not True


@pytest.mark.asyncio
async def test_organize_resources_can_resolve_resource_sandbox_path_and_update_record(
    tmp_path: Path,
) -> None:
    ledger = EventLedgerService()
    sandbox = SandboxService(data_root=tmp_path, event_ledger=ledger)
    workspace_id = "workspace-resource-organize"
    root = sandbox.ensure_workspace_root(workspace_id)
    source = root / "inbox" / "guide.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("guide", encoding="utf-8")
    resource = ResourceRecord(
        id="resource-guide",
        kind="markdown",
        name="Guide",
        source=str(source),
        sandbox_path=str(source),
    )
    saved: list[ResourceRecord] = []
    runtime = _runtime(
        sandbox_service=sandbox,
        repository=SimpleNamespace(
            list_resources=lambda _workspace_id: [resource],
            save_resource=lambda _workspace_id, item: saved.append(item),
        ),
        event_ledger=ledger,
    )
    registry = build_default_tool_registry()
    operations = [
        {"op": "move", "resource_id": "resource-guide", "target": "knowledge/guide.md"}
    ]
    proposal = await registry.invoke(
        _context(runtime), "organize_resources", {"operations": operations}
    )
    assert proposal["requires_confirmation"] is True

    result = await registry.invoke(
        _context(runtime, host_confirmed=True),
        "organize_resources",
        {"operations": operations},
    )

    assert result["ok"] is True
    assert (root / "knowledge" / "guide.md").exists()
    assert saved and saved[-1].sandbox_path == str(root / "knowledge" / "guide.md")


@pytest.mark.asyncio
async def test_organize_resources_delete_is_confirmed_and_trash_restorable(tmp_path: Path) -> None:
    sandbox = SandboxService(data_root=tmp_path)
    workspace_id = "workspace-resource-organize"
    root = sandbox.ensure_workspace_root(workspace_id)
    target = root / "obsolete.md"
    target.write_text("obsolete", encoding="utf-8")
    runtime = _runtime(sandbox_service=sandbox)
    registry = build_default_tool_registry()
    operations = [{"op": "delete", "path": "obsolete.md"}]
    proposal = await registry.invoke(
        _context(runtime), "organize_resources", {"operations": operations}
    )
    assert proposal["requires_confirmation"] is True

    result = await registry.invoke(
        _context(runtime, host_confirmed=True),
        "organize_resources",
        {"operations": operations},
    )
    assert result["ok"] is True
    assert not target.exists()

    undone = await registry.invoke(
        _context(runtime, host_confirmed=True),
        "organize_resources",
        {"undo_id": result["history_id"]},
    )
    assert undone["ok"] is True
    assert target.exists()


@pytest.mark.asyncio
async def test_import_resource_url_uses_runtime_post_index_closure() -> None:
    from unittest.mock import Mock

    from app.core.models import ResourceRecord

    uploaded = ResourceRecord(
        id="resource-url-closure",
        kind="url",
        name="Imported source",
        source="https://example.com/source",
    )
    indexed = uploaded.model_copy(
        update={
            "index_status": "indexed",
            "parse_status": "parsed",
            "canonical_source": "https://example.com/source",
        }
    )
    service = SimpleNamespace(
        registry=SimpleNamespace(get=Mock(return_value=SimpleNamespace(metadata={}))),
        upload=Mock(return_value=uploaded),
        index=Mock(return_value=indexed),
    )
    closure = Mock(
        return_value=(
            indexed,
            {
                "sandbox_synced": True,
                "teaching_assets_created": 2,
                "workspace_understanding_refreshed": True,
                "research_references_recorded": 1,
                "sessions_refreshed": 1,
            },
        )
    )
    runtime = SimpleNamespace(resource_service=service, postprocess_indexed_resource=closure)
    import_context = ToolContext(
        runtime=runtime,
        workspace_id="workspace-resource-organize",
        session_id="session-resource-organize",
        extra={
            "active_view": "resources",
            "resource_composer_intent": {"mode": "download"},
        },
    )
    result = await build_default_tool_registry().invoke(
        import_context,
        "import_resource_url",
        {"url": "https://example.com/source"},
    )
    assert result["ok"] is True
    closure.assert_called_once()


@pytest.mark.asyncio
async def test_organize_host_stamp_commits_on_trusted_local_managed_sandbox(
    tmp_path: Path,
) -> None:
    """Host-confirmed organize on trusted local: sandbox commit ok; project untouched."""
    workspace_id = "workspace-organize-trusted-local"
    sandbox, project_authority, project_root, project_sentinel, ledger = _authority_wired_sandbox(
        tmp_path,
        workspace_id=workspace_id,
        workspace_trusted=True,
    )
    root = sandbox.ensure_workspace_root(workspace_id)
    source = root / "notes.md"
    source.write_text("notes", encoding="utf-8")
    runtime = _runtime(
        sandbox_service=sandbox,
        event_ledger=ledger,
        resolve_workspace_path=lambda _workspace_id: str(project_root),
    )
    registry = build_default_tool_registry()
    operations = [{"op": "move", "source": "notes.md", "target": "archive/notes.md"}]

    proposal = await registry.invoke(
        _context(runtime, workspace_id=workspace_id),
        "organize_resources",
        {"operations": operations},
    )
    assert proposal["ok"] is True
    assert proposal["requires_confirmation"] is True
    assert workspace_id in runtime.resource_organization_pending

    committed = await registry.invoke(
        _context(runtime, host_confirmed=True, workspace_id=workspace_id),
        "organize_resources",
        {"operations": operations},
    )
    assert committed["ok"] is True
    assert committed["committed"] is True
    assert (root / "archive" / "notes.md").exists()
    assert not source.exists()
    assert project_sentinel.read_text(encoding="utf-8") == "project-owned"
    assert project_authority.permission_level is PermissionLevel.INSPECT
    assert project_authority.explicit_destructive_policy is False


@pytest.mark.asyncio
async def test_organize_host_stamp_writes_local_library_when_project_is_untrusted(
    tmp_path: Path,
) -> None:
    workspace_id = "workspace-organize-untrusted-stamp"
    sandbox, project_authority, project_root, project_sentinel, ledger = _authority_wired_sandbox(
        tmp_path,
        workspace_id=workspace_id,
        workspace_trusted=False,
    )
    root = sandbox.ensure_workspace_root(workspace_id)
    source = root / "notes.md"
    source.write_text("notes", encoding="utf-8")
    runtime = _runtime(
        sandbox_service=sandbox,
        event_ledger=ledger,
        resolve_workspace_path=lambda _workspace_id: str(project_root),
    )
    registry = build_default_tool_registry()
    operations = [{"op": "move", "source": "notes.md", "target": "archive/notes.md"}]

    await registry.invoke(
        _context(runtime, workspace_id=workspace_id),
        "organize_resources",
        {"operations": operations},
    )
    committed = await registry.invoke(
        _context(runtime, host_confirmed=True, workspace_id=workspace_id),
        "organize_resources",
        {"operations": operations},
    )
    assert committed["ok"] is True
    assert committed.get("committed") is True
    assert not source.exists()
    assert (root / "archive" / "notes.md").exists()
    assert project_sentinel.read_text(encoding="utf-8") == "project-owned"
    assert project_authority.is_workspace_trusted is False
    assert project_authority.check_permission("write", "user-project.txt") is False


@pytest.mark.asyncio
async def test_organize_host_stamp_writes_local_library_when_project_is_remote(tmp_path: Path) -> None:
    workspace_id = "workspace-organize-remote-stamp"
    sandbox, project_authority, project_root, project_sentinel, ledger = _authority_wired_sandbox(
        tmp_path,
        workspace_id=workspace_id,
        workspace_trusted=True,
        remote_name="ssh-remote",
    )
    root = sandbox.ensure_workspace_root(workspace_id)
    source = root / "notes.md"
    source.write_text("notes", encoding="utf-8")
    runtime = _runtime(
        sandbox_service=sandbox,
        event_ledger=ledger,
        resolve_workspace_path=lambda _workspace_id: str(project_root),
    )
    registry = build_default_tool_registry()
    operations = [{"op": "move", "source": "notes.md", "target": "archive/notes.md"}]

    await registry.invoke(
        _context(runtime, workspace_id=workspace_id),
        "organize_resources",
        {"operations": operations},
    )
    committed = await registry.invoke(
        _context(runtime, host_confirmed=True, workspace_id=workspace_id),
        "organize_resources",
        {"operations": operations},
    )
    assert committed["ok"] is True
    assert committed.get("committed") is True
    assert not source.exists()
    assert (root / "archive" / "notes.md").exists()
    assert project_sentinel.read_text(encoding="utf-8") == "project-owned"
    assert project_authority.is_remote_workspace is True
    assert project_authority.check_permission("write", "user-project.txt") is False


@pytest.mark.asyncio
async def test_class_human_api_organize_stamp_respects_host_trust_gate(
    tmp_path: Path,
) -> None:
    """TestClient (no live LLM): host stamp + pending under trusted/untrusted/remote."""
    from fastapi.testclient import TestClient

    from app.core.settings import AppSettings
    from app.main import create_app

    settings = AppSettings(
        app_name="Trainer Organize Trust Gate Tests",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path / "sidecar-data",
        database_name="trainer-organize-trust-gate.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )
    app = create_app(settings)
    registry = build_default_tool_registry()
    operations = [{"op": "move", "source": "notes.md", "target": "archive/notes.md"}]

    cases = (
        ("trusted-local", True, ""),
        ("untrusted", False, ""),
        ("remote", True, "ssh-remote"),
    )

    with TestClient(app) as client:
        runtime = app.state.runtime
        for label, trusted, remote in cases:
            workspace_id = f"workspace-org-gate-{label}"
            project_root = tmp_path / f"opened-{label}"
            project_root.mkdir()
            project_sentinel = project_root / "user-project.txt"
            project_sentinel.write_text("project-owned", encoding="utf-8")

            started = client.post(
                "/session/start",
                json={
                    "workspace_id": workspace_id,
                    "workspace_name": f"Organize Gate {label}",
                    "workspace_path": str(project_root),
                    "workspace_trusted": trusted,
                    "remote_name": remote,
                },
            )
            assert started.status_code == 200, started.text

            authority = runtime.workspace_authority(workspace_id)
            assert authority is not None
            assert authority.is_workspace_trusted is trusted
            assert authority.is_remote_workspace is bool(remote)

            sandbox = runtime.sandbox_service
            assert sandbox is not None
            root = sandbox.ensure_workspace_root(workspace_id)
            source = root / "notes.md"
            source.write_text("notes", encoding="utf-8")

            proposal = await registry.invoke(
                _context(runtime, workspace_id=workspace_id),
                "organize_resources",
                {"operations": operations},
            )
            assert proposal["requires_confirmation"] is True
            assert workspace_id in runtime.resource_organization_pending

            # Host stamp only when pending exists (routers.py gate mirrors this).
            pending = runtime.resource_organization_pending
            assert isinstance(pending, dict) and workspace_id in pending

            result = await registry.invoke(
                _context(runtime, host_confirmed=True, workspace_id=workspace_id),
                "organize_resources",
                {"operations": operations},
            )
            assert result["ok"] is True
            assert result["committed"] is True
            assert (root / "archive" / "notes.md").exists()
            assert not source.exists()

            assert project_sentinel.read_text(encoding="utf-8") == "project-owned"
            assert authority.permission_level is PermissionLevel.INSPECT


@pytest.mark.asyncio
async def test_agent_tools_cannot_write_outside_sandbox_into_project_sentinel(
    tmp_path: Path,
) -> None:
    """Learning OS fail-closed: no project write tool; organize stays sandbox-only."""
    workspace_id = "workspace-agent-no-project-write"
    sandbox, _authority, project_root, project_sentinel, ledger = _authority_wired_sandbox(
        tmp_path,
        workspace_id=workspace_id,
        workspace_trusted=True,
    )
    root = sandbox.ensure_workspace_root(workspace_id)
    (root / "notes.md").write_text("sandbox-notes", encoding="utf-8")
    runtime = _runtime(
        sandbox_service=sandbox,
        event_ledger=ledger,
        resolve_workspace_path=lambda _workspace_id: str(project_root),
    )
    registry = build_default_tool_registry()
    names = set(registry.names())
    assert "write_file" not in names
    assert "apply_patch" not in names
    assert "edit_file" not in names

    # Absolute / traversal paths must not touch the opened project sentinel.
    for operations in (
        [{"op": "mkdir", "path": str(project_root / "agent-wrote")}],
        [{"op": "mkdir", "path": "../user-project.txt"}],
        [
            {
                "op": "move",
                "source": "notes.md",
                "target": str(project_root / "stolen-notes.md"),
            }
        ],
        [{"op": "delete", "path": str(project_sentinel)}],
    ):
        proposal = await registry.invoke(
            _context(runtime, workspace_id=workspace_id),
            "organize_resources",
            {"operations": operations},
        )
        if proposal.get("ok") and proposal.get("requires_confirmation"):
            committed = await registry.invoke(
                _context(runtime, host_confirmed=True, workspace_id=workspace_id),
                "organize_resources",
                {"operations": operations},
            )
            assert committed.get("committed") is not True or not (
                project_root / "agent-wrote"
            ).exists()
        assert project_sentinel.read_text(encoding="utf-8") == "project-owned"
        assert not (project_root / "agent-wrote").exists()
        assert not (project_root / "stolen-notes.md").exists()
        assert (root / "notes.md").exists() or (root / "archive" / "notes.md").exists()


@pytest.mark.asyncio
async def test_organize_consume_then_fs_abort_restores_pending_fail_closed(
    tmp_path: Path,
) -> None:
    """After pending consume, FS abort must not touch project; proposal recoverable.

    Cancel + empty-pending second confirm stay fail-closed (TestClient cancel route).
    """
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    from app.core.settings import AppSettings
    from app.main import create_app

    settings = AppSettings(
        app_name="Trainer Organize Abort Tests",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path / "sidecar-data",
        database_name="trainer-organize-abort.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )
    app = create_app(settings)
    workspace_id = "workspace-organize-abort-after-consume"
    project_root = tmp_path / "opened-abort"
    project_root.mkdir()
    project_sentinel = project_root / "user-project.txt"
    project_sentinel.write_text("project-owned", encoding="utf-8")
    operations = [{"op": "move", "source": "notes.md", "target": "archive/notes.md"}]
    registry = build_default_tool_registry()

    with TestClient(app) as client:
        runtime = app.state.runtime
        started = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "Organize Abort",
                "workspace_path": str(project_root),
                "workspace_trusted": True,
            },
        )
        assert started.status_code == 200, started.text

        sandbox = runtime.sandbox_service
        assert sandbox is not None
        root = sandbox.ensure_workspace_root(workspace_id)
        source = root / "notes.md"
        source.write_text("notes", encoding="utf-8")

        proposal = await registry.invoke(
            _context(runtime, workspace_id=workspace_id),
            "organize_resources",
            {"operations": operations},
        )
        assert proposal["requires_confirmation"] is True
        assert workspace_id in runtime.resource_organization_pending

        with patch.object(
            sandbox,
            "batch_rename",
            side_effect=RuntimeError("simulated mid-mutate abort"),
        ):
            aborted = await registry.invoke(
                _context(runtime, host_confirmed=True, workspace_id=workspace_id),
                "organize_resources",
                {"operations": operations},
            )
        assert aborted["ok"] is False
        assert aborted["error"] == "resource_organization_failed"
        assert aborted.get("committed") is False
        assert aborted.get("proposal_restored") is True
        assert aborted.get("requires_confirmation") is True
        assert workspace_id in runtime.resource_organization_pending
        assert source.exists()
        assert not (root / "archive" / "notes.md").exists()
        assert project_sentinel.read_text(encoding="utf-8") == "project-owned"

        cancel = client.post(
            "/resource/organization/cancel",
            json={"workspace_id": workspace_id},
        )
        assert cancel.status_code == 200
        assert cancel.json()["cleared"] is True
        assert workspace_id not in runtime.resource_organization_pending

        # Empty pending: host stamp must fail-closed (no silent project write).
        second = await registry.invoke(
            _context(runtime, host_confirmed=True, workspace_id=workspace_id),
            "organize_resources",
            {"operations": operations},
        )
        assert second["ok"] is False
        assert second["error"] == "host_confirmation_required"
        assert second.get("committed") is False
        assert source.exists()
        assert project_sentinel.read_text(encoding="utf-8") == "project-owned"


@pytest.mark.asyncio
async def test_organize_cancel_during_fs_after_consume_fail_closed(
    tmp_path: Path,
) -> None:
    """Cancel mid-FS after pending consume must not resurrect pending for a second confirm."""
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    from app.core.settings import AppSettings
    from app.main import create_app

    settings = AppSettings(
        app_name="Trainer Organize Cancel Race Tests",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path / "sidecar-data",
        database_name="trainer-organize-cancel-race.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )
    app = create_app(settings)
    workspace_id = "workspace-organize-cancel-mid-fs"
    project_root = tmp_path / "opened-cancel-race"
    project_root.mkdir()
    project_sentinel = project_root / "user-project.txt"
    project_sentinel.write_text("project-owned", encoding="utf-8")
    operations = [{"op": "move", "source": "notes.md", "target": "archive/notes.md"}]
    registry = build_default_tool_registry()

    with TestClient(app) as client:
        runtime = app.state.runtime
        started = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "Organize Cancel Race",
                "workspace_path": str(project_root),
                "workspace_trusted": True,
            },
        )
        assert started.status_code == 200, started.text

        sandbox = runtime.sandbox_service
        assert sandbox is not None
        root = sandbox.ensure_workspace_root(workspace_id)
        source = root / "notes.md"
        source.write_text("notes", encoding="utf-8")

        proposal = await registry.invoke(
            _context(runtime, workspace_id=workspace_id),
            "organize_resources",
            {"operations": operations},
        )
        assert proposal["requires_confirmation"] is True
        assert workspace_id in runtime.resource_organization_pending

        def racing_rename(*_args: object, **_kwargs: object):
            cancel = client.post(
                "/resource/organization/cancel",
                json={"workspace_id": workspace_id},
            )
            assert cancel.status_code == 200
            # Pending already consumed — cleared may be false; latch must still win.
            assert cancel.json().get("ok") is True
            raise RuntimeError("simulated mid-mutate abort after cancel")

        with patch.object(sandbox, "batch_rename", side_effect=racing_rename):
            aborted = await registry.invoke(
                _context(runtime, host_confirmed=True, workspace_id=workspace_id),
                "organize_resources",
                {"operations": operations},
            )
        assert aborted["ok"] is False
        assert aborted["error"] == "resource_organization_cancelled"
        assert aborted.get("committed") is False
        assert aborted.get("proposal_restored") is False
        assert workspace_id not in runtime.resource_organization_pending
        assert source.exists()
        assert not (root / "archive" / "notes.md").exists()
        assert project_sentinel.read_text(encoding="utf-8") == "project-owned"

        second = await registry.invoke(
            _context(runtime, host_confirmed=True, workspace_id=workspace_id),
            "organize_resources",
            {"operations": operations},
        )
        assert second["ok"] is False
        assert second["error"] == "host_confirmation_required"
        assert second.get("committed") is False
        assert source.exists()
        assert not (root / "archive" / "notes.md").exists()
        assert project_sentinel.read_text(encoding="utf-8") == "project-owned"


@pytest.mark.asyncio
async def test_organize_cancel_mid_fs_when_write_succeeds_completed_write_wins(
    tmp_path: Path,
) -> None:
    """Cancel mid-FS after consume: if write commits, pending stays dead; cancel fails honestly."""
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    from app.core.settings import AppSettings
    from app.main import create_app

    settings = AppSettings(
        app_name="Trainer Organize Cancel After Success Tests",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path / "sidecar-data",
        database_name="trainer-organize-cancel-after-success.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )
    app = create_app(settings)
    workspace_id = "workspace-organize-cancel-after-success"
    project_root = tmp_path / "opened-cancel-after-success"
    project_root.mkdir()
    project_sentinel = project_root / "user-project.txt"
    project_sentinel.write_text("project-owned", encoding="utf-8")
    operations = [{"op": "move", "source": "notes.md", "target": "archive/notes.md"}]
    registry = build_default_tool_registry()
    cancel_body: dict[str, object] = {}

    with TestClient(app) as client:
        runtime = app.state.runtime
        started = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "Organize Cancel After Success",
                "workspace_path": str(project_root),
                "workspace_trusted": True,
            },
        )
        assert started.status_code == 200, started.text

        sandbox = runtime.sandbox_service
        assert sandbox is not None
        root = sandbox.ensure_workspace_root(workspace_id)
        source = root / "notes.md"
        source.write_text("notes", encoding="utf-8")

        proposal = await registry.invoke(
            _context(runtime, workspace_id=workspace_id),
            "organize_resources",
            {"operations": operations},
        )
        assert proposal["requires_confirmation"] is True
        assert workspace_id in runtime.resource_organization_pending

        real_batch_rename = sandbox.batch_rename

        def cancel_then_commit(*args: object, **kwargs: object):
            cancel = client.post(
                "/resource/organization/cancel",
                json={"workspace_id": workspace_id},
            )
            assert cancel.status_code == 200
            cancel_body.update(cancel.json())
            # Pending already consumed — latch must set; write still proceeds.
            assert cancel_body.get("ok") is True
            assert cancel_body.get("cleared") is False
            assert cancel_body.get("cancel_latched") is True
            return real_batch_rename(*args, **kwargs)

        with patch.object(sandbox, "batch_rename", side_effect=cancel_then_commit):
            committed = await registry.invoke(
                _context(runtime, host_confirmed=True, workspace_id=workspace_id),
                "organize_resources",
                {"operations": operations},
            )
        assert committed["ok"] is True
        assert committed.get("committed") is True
        assert committed.get("proposal_restored") is False
        assert committed.get("cancel_failed_already_committed") is True
        assert workspace_id not in runtime.resource_organization_pending
        assert not source.exists()
        assert (root / "archive" / "notes.md").exists()
        assert project_sentinel.read_text(encoding="utf-8") == "project-owned"

        late = client.post(
            "/resource/organization/cancel",
            json={"workspace_id": workspace_id},
        )
        assert late.status_code == 200
        late_body = late.json()
        assert late_body.get("ok") is False
        assert late_body.get("cancelled") is False
        assert late_body.get("already_committed") is True
        assert late_body.get("error") == "resource_organization_already_committed"
        assert workspace_id not in runtime.resource_organization_pending

        second = await registry.invoke(
            _context(runtime, host_confirmed=True, workspace_id=workspace_id),
            "organize_resources",
            {"operations": operations},
        )
        assert second["ok"] is False
        assert second["error"] == "host_confirmation_required"
        assert second.get("committed") is False
        assert (root / "archive" / "notes.md").exists()
        assert project_sentinel.read_text(encoding="utf-8") == "project-owned"
