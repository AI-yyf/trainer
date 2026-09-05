"""Live-shaped remote workspace test using 141s RAP files.

The SSH host is optional. Prefer G:\\temp\\rap_141s_snapshot.json when present
(dumped by the 141s probe). Otherwise a built-in RAP fixture is used.
The sidecar under test is always local: remote_name is stamped, the project path
does not exist on this machine, and library writes stay in TRAINER data_dir.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.routers import _attach_requested_workspace_files
from app.core.settings import AppSettings
from app.llm.tools import ToolContext, build_default_tool_registry
from app.main import create_app

REMOTE_ROOT = "/mnt/vdb1/yunfei.yan/RAP"
SNAPSHOT_CACHE = Path(r"G:\temp\rap_141s_snapshot.json")


def _fixture_snapshot() -> dict[str, Any]:
    contents = {
        "README.md": {
            "content": "RAP (Rasterization Augmented Planning) is a scalable data augmentation pipeline.",
            "language_id": "markdown",
        },
        "navsim/agents/abstract_agent.py": {
            "content": "class AbstractAgent:\n    def name(self) -> str:\n        raise NotImplementedError\n",
            "language_id": "python",
        },
        "setup.py": {
            "content": 'setuptools.setup(name="navsim", version="1.1.0")\n',
            "language_id": "python",
        },
        "requirements.txt": {
            "content": "pytorch-lightning==2.2.1\n",
            "language_id": "text",
        },
    }
    files = [
        {"path": key, "size": len(value["content"])} for key, value in contents.items()
    ]
    files.append({"path": "navsim/agents/rap_dino/rap_agent.py"})
    return {
        "is_remote": True,
        "root_uri": f"vscode-remote://ssh-remote+141s{REMOTE_ROOT}",
        "files": files,
        "contents": contents,
        "source": "fixture",
    }


def _pull_rap_snapshot() -> dict[str, Any]:
    if SNAPSHOT_CACHE.is_file():
        payload = json.loads(SNAPSHOT_CACHE.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and payload.get("files"):
            payload["source"] = "ssh-cache"
            return payload
    return _fixture_snapshot()


@pytest.fixture(scope="module")
def rap_snapshot() -> dict[str, Any]:
    return _pull_rap_snapshot()


def _imported_sandbox_path(sandbox_root: Path, relative: str) -> Path:
    return sandbox_root.joinpath("sources", "workspace", *relative.split("/"))


def _first_look_from_session(payload: dict[str, Any]) -> dict[str, Any]:
    memory = payload.get("memory") or {}
    understanding = memory.get("workspaceUnderstanding") or memory.get("workspace_understanding") or {}
    first_look = understanding.get("firstLookSummary") or understanding.get("first_look_summary") or {}
    return first_look if isinstance(first_look, dict) else {}


def _client(tmp_path: Path) -> TestClient:
    settings = AppSettings(
        app_name="Trainer 141s RAP",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path / "sidecar-data",
        database_name="trainer-141s.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )
    return TestClient(create_app(settings))


def test_remote_rap_session_start_without_snapshot_is_not_empty_new_project(tmp_path: Path) -> None:
    if SNAPSHOT_CACHE.is_file():
        assert _pull_rap_snapshot()["source"] == "ssh-cache"
    else:
        assert _pull_rap_snapshot()["source"] == "fixture"
    with _client(tmp_path) as client:
        started = client.post(
            "/session/start",
            json={
                "workspace_id": "workspace-141s-rap-no-snapshot",
                "workspace_name": "RAP remote",
                "workspace_path": REMOTE_ROOT,
                "remote_name": "ssh-remote",
                "workspace_trusted": True,
                "force_new": True,
            },
        )
    assert started.status_code == 200, started.text
    first_look = _first_look_from_session(started.json())
    role = first_look.get("folderRole") or first_look.get("folder_role")
    assert role != "empty_new_project"
    assert role == "mixed_uncertain"
    assert Path(REMOTE_ROOT).exists() is False


@pytest.mark.asyncio
async def test_remote_rap_session_library_import_and_project_isolation(
    tmp_path: Path, rap_snapshot: dict[str, Any]
) -> None:
    if SNAPSHOT_CACHE.is_file():
        assert rap_snapshot["source"] == "ssh-cache"
    else:
        assert rap_snapshot["source"] == "fixture"
    print(
        f"RAP snapshot source={rap_snapshot['source']} "
        f"cache_exists={SNAPSHOT_CACHE.is_file()} files={len(rap_snapshot.get('files') or [])}"
    )
    workspace_id = "workspace-141s-rap"
    with _client(tmp_path) as client:
        classified = client.post(
            "/workspace/classify",
            json={
                "workspace_id": workspace_id,
                "folder_path": REMOTE_ROOT,
                "remote_name": "ssh-remote",
                "workspace_file_snapshot": {
                    "is_remote": True,
                    "root_uri": rap_snapshot["root_uri"],
                    "files": rap_snapshot["files"],
                    "contents": rap_snapshot["contents"],
                },
            },
        )
        assert classified.status_code == 200, classified.text
        classification = classified.json()
        assert classification["folder_role"] != "empty_new_project"
        assert classification["project_discovery"]["is_browse_only"] is True
        assert classification["project_discovery"]["project_path"] == REMOTE_ROOT

        started = client.post(
            "/session/start",
            json={
                "workspace_id": workspace_id,
                "workspace_name": "RAP remote",
                "workspace_path": REMOTE_ROOT,
                "remote_name": "ssh-remote",
                "workspace_trusted": True,
                "force_new": True,
                "workspace_file_snapshot": {
                    "is_remote": True,
                    "root_uri": rap_snapshot["root_uri"],
                    "files": rap_snapshot["files"],
                    "contents": rap_snapshot["contents"],
                },
            },
        )
        assert started.status_code == 200, started.text
        started_payload = started.json()
        session_id = started_payload.get("session_id") or started_payload.get("sessionId")
        first_look = _first_look_from_session(started_payload)
        role = first_look.get("folderRole") or first_look.get("folder_role")
        assert role != "empty_new_project"
        assert role in {"existing_engineering", "algorithm_model"}
        runtime = client.app.state.runtime
        authority = runtime.workspace_authority(workspace_id)
        assert authority is not None
        assert authority.is_remote_workspace is True
        assert authority.active_workspace_root in {None, ""}
        sandbox_root = runtime.sandbox_service.ensure_workspace_root(workspace_id)
        assert Path(REMOTE_ROOT).exists() is False
        assert str(sandbox_root).startswith(str(tmp_path))

        written = client.post(
            "/sandbox/write",
            json={
                "workspace_id": workspace_id,
                "path": "notes/local-only.md",
                "content": "Trainer library stays local.",
                "create": True,
                "remote_name": "ssh-remote",
                "workspace_trusted": True,
            },
        )
        assert written.status_code == 200, written.text
        assert (sandbox_root / "notes" / "local-only.md").read_text(encoding="utf-8") == "Trainer library stays local."
        escaped = client.post(
            "/sandbox/write",
            json={
                "workspace_id": workspace_id,
                "path": f"{REMOTE_ROOT}/setup.py",
                "content": "must-not-write",
                "create": True,
                "remote_name": "ssh-remote",
                "workspace_trusted": True,
            },
        )
        assert escaped.status_code == 422, escaped.text
        assert Path(REMOTE_ROOT).exists() is False

        context = ToolContext(
            runtime=runtime,
            workspace_id=workspace_id,
            session_id=str(session_id or "session-141s"),
            extra={
                "library_sandbox_work": True,
                "workspace_file_snapshot": {
                    "is_remote": True,
                    "root_uri": rap_snapshot["root_uri"],
                    "files": rap_snapshot["files"],
                    "contents": rap_snapshot["contents"],
                },
            },
        )
        registry = build_default_tool_registry()

        listed = await registry.invoke(context, "list_workspace_files", {"pattern": "**/*.py", "limit": 40})
        assert listed["ok"] is True
        assert listed["source"] == "workspace_snapshot"
        paths = {item["path"] for item in listed["items"]}
        assert any(path.endswith("abstract_agent.py") for path in paths)

        read = await registry.invoke(
            context, "read_workspace_file", {"path": "navsim/agents/abstract_agent.py"}
        )
        assert read["ok"] is True
        assert "AbstractAgent" in read["content"]
        assert read["source"] == "workspace_snapshot"

        imported = await registry.invoke(
            context, "import_workspace_file", {"path": "navsim/agents/abstract_agent.py"}
        )
        assert imported["ok"] is True
        dest = _imported_sandbox_path(sandbox_root, "navsim/agents/abstract_agent.py")
        assert dest.is_file()
        assert "AbstractAgent" in dest.read_text(encoding="utf-8")
        assert not Path(REMOTE_ROOT).exists()

        readme = await registry.invoke(context, "read_workspace_file", {"path": "README.md"})
        assert readme["ok"] is True
        assert "RAP" in readme["content"] or "Rasterization" in readme["content"]
        await registry.invoke(context, "import_workspace_file", {"path": "README.md"})

        listed_without_body = next(
            item["path"]
            for item in listed["items"]
            if item["path"] not in rap_snapshot["contents"]
        )
        missing = await registry.invoke(
            context, "read_workspace_file", {"path": listed_without_body}
        )
        assert missing["ok"] is False
        assert missing["error"] == "snapshot_content_unavailable"
        assert listed_without_body in runtime.requested_workspace_file_paths(workspace_id)
        stamped = _attach_requested_workspace_files({}, runtime, workspace_id)
        assert listed_without_body in stamped["requested_workspace_files"]

        blocked = await registry.invoke(
            context, "import_workspace_file", {"path": listed_without_body}
        )
        assert blocked["ok"] is False
        assert blocked["error"] == "snapshot_content_unavailable"

        snapshot = dict(context.extra["workspace_file_snapshot"])
        contents = dict(snapshot["contents"])
        contents[listed_without_body] = {
            "content": "class RapAgent:\n    pass\n",
            "language_id": "python",
        }
        snapshot["contents"] = contents
        context.extra["workspace_file_snapshot"] = snapshot
        imported_later = await registry.invoke(
            context, "import_workspace_file", {"path": listed_without_body}
        )
        assert imported_later["ok"] is True
        later_dest = _imported_sandbox_path(sandbox_root, listed_without_body)
        assert later_dest.is_file()
        assert "class RapAgent" in later_dest.read_text(encoding="utf-8")
        assert listed_without_body not in runtime.requested_workspace_file_paths(workspace_id)
        assert not Path(REMOTE_ROOT).exists()

        denied = await registry.invoke(
            context,
            "write_sandbox_file",
            {"path": f"{REMOTE_ROOT}/hack.py", "content": "nope", "create": True},
        )
        assert denied.get("ok") is False
        assert not Path(REMOTE_ROOT).exists()

        searched = await registry.invoke(
            context, "search_resources", {"query": "AbstractAgent", "limit": 5}
        )
        assert searched["ok"] is True
        assert searched["total"] >= 1

        state = client.get("/sandbox/state", params={"workspace_id": workspace_id})
        assert state.status_code == 200, state.text
        assert state.json()["capability_summary"]["platform"]["workspace_trust_state"] == "remote"
        assert authority.check_permission("write", "setup.py") is False
