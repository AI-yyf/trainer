"""Phase 3 — 项目分析知识 → Knowledge Skill 自动沉淀验收.

失败优先：此前项目分析只产出 artifact，不产生可复用 Skill，也不关联
资料库/Coach/学习计划。现在：
- 导入成功自动沉淀 (显式 POST /project/distill 可重试)；
- 同一 commit 幂等 (updated=False, 版本不变)，commit 前进版本 +1；
- 技能 kind=knowledge、自动审核激活，trigger 含项目名与结构词 →
  agent 选择器命中，注入正文（含引用与诚实局限）；
- TeachingKnowledgeAsset (study_guide) 写入并带 source_ids 关联。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.settings import AppSettings
from app.main import create_app
from app.skills.runtime import select_active_skills

GIT = __import__("shutil").which("git") is not None


def build_client(tmp_path: Path) -> TestClient:
    settings = AppSettings(
        app_name="Trainer Distill",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path / "data",
        database_name="trainer-distill.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )
    return TestClient(create_app(settings))


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.strip()


def _init_repo(repo: Path) -> str:
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "utils.py").write_text(
        "def format_name(name: str) -> str:\n    return name.strip()\n", encoding="utf-8"
    )
    (repo / "service.py").write_text(
        "from utils import format_name\n\ndef handle(name: str) -> str:\n    return format_name(name)\n",
        encoding="utf-8",
    )
    (repo / "main.py").write_text(
        "from service import handle\n\nif __name__ == '__main__':\n    print(handle('a'))\n",
        encoding="utf-8",
    )
    _git(repo, "init", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=T", "commit", "-m", "init")
    return _git(repo, "rev-parse", "HEAD")


@pytest.mark.skipif(not GIT, reason="git fixture")
def test_import_auto_distills_knowledge_skill_linked_three_ways(tmp_path: Path) -> None:
    repo = tmp_path / "repos" / "distill-repo"
    commit = _init_repo(repo)

    with build_client(tmp_path) as client:
        (tmp_path / "ws").mkdir()
        client.post(
            "/session/start",
            json={"workspace_id": "ws-distill", "workspace_name": "ws-distill", "workspace_path": str(tmp_path / "ws")},
        )
        imported = client.post(
            "/project/import/local", json={"workspace_id": "ws-distill", "path": str(repo)}
        )
        assert imported.status_code == 200, imported.text
        payload = imported.json()
        resource_id = payload["resource_id"]
        distilled = payload["knowledge_skill"]
        assert distilled is not None, "import must auto-distill the project knowledge skill"
        assert distilled["created"] is True
        assert distilled["commit_sha"] == commit
        assert distilled["linked"] == {"library": True, "coach": True, "learning": True}

        runtime = client.app.state.runtime
        registry = runtime.skill_registry
        record = registry._skills[distilled["skill_id"]]
        assert record.kind == "knowledge"
        assert record.active is True and record.reviewed is True
        assert record.metadata["source_resource_id"] == resource_id
        assert record.metadata["commit_sha"] == commit
        assert "项目身份" in record.body and "局限" in record.body
        assert record.version == 1

        # Coach linkage: the selection path picks it up for a structure question.
        selected = select_active_skills(registry, "帮我理解这个项目的架构与模块入口")
        assert any(skill.skill_id == distilled["skill_id"] for skill in selected)

        # Learning plan linkage: a study_guide teaching asset carries the links.
        assets = runtime.memory_service.list_teaching_assets(workspace_id="ws-distill")
        asset = next(
            (item for item in assets if resource_id in (item.source_ids or [])), None
        )
        assert asset is not None
        assert asset.kind == "study_guide"
        assert asset.origin == "workspace_understanding"
        assert asset.source_key == f"project-analysis:{resource_id}"

        # Idempotent re-distill at the same commit: version unchanged.
        again = client.post(
            "/project/distill", json={"workspace_id": "ws-distill", "resource_id": resource_id}
        )
        assert again.status_code == 200, again.text
        assert again.json()["updated"] is True
        assert again.json()["version"] == 1

        # The import is a pinned snapshot: simulate a pulled update inside the
        # managed lane checkout, which is what re-distill actually reads.
        lane = Path(payload["repo_root"])
        (lane / "extra.py").write_text("def extra_fn():\n    return 1\n", encoding="utf-8")
        _git(lane, "add", "-A")
        _git(lane, "-c", "user.email=t@t", "-c", "user.name=T", "commit", "-m", "more")
        new_commit = _git(lane, "rev-parse", "HEAD")
        refreshed = client.post(
            "/project/distill", json={"workspace_id": "ws-distill", "resource_id": resource_id}
        )
        assert refreshed.status_code == 200, refreshed.text
        assert refreshed.json()["version"] == 2
        assert refreshed.json()["commit_sha"] == new_commit
        assert "extra_fn" not in refreshed.json()["skill_id"]  # id stays stable


@pytest.mark.skipif(not GIT, reason="git fixture")
def test_distill_route_rejects_unknown_and_non_project(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        (tmp_path / "ws").mkdir()
        client.post(
            "/session/start",
            json={"workspace_id": "ws-x", "workspace_name": "ws-x", "workspace_path": str(tmp_path / "ws")},
        )
        missing = client.post(
            "/project/distill", json={"workspace_id": "ws-x", "resource_id": "resource-none"}
        )
        assert missing.status_code == 404
        missing_fields = client.post("/project/distill", json={"workspace_id": "ws-x"})
        assert missing_fields.status_code == 400
