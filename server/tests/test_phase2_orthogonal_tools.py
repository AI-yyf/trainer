"""Phase 2 regressions: 8 dual-domain orthogonal primitives, <LibraryRoot> autonomy & auto-FTS5."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.core.config import Settings
from app.llm.agent_tool_context import _build_agent_tool_context_extra
from app.llm.tool_primitives import (
    ORTHOGONAL_PRIMITIVE_NAMES,
    _validate_library_exec_command,
    select_orthogonal_tools_for_turn,
)
from app.llm.tools import ToolContext, build_default_tool_registry
from app.main import create_app


def _setup_ctx(tmp_path: Path) -> tuple[Any, ToolContext, Path, Path]:
    project_root = tmp_path / "learner_project"
    project_root.mkdir(parents=True, exist_ok=True)
    (project_root / "app.py").write_text("def greet(name: str) -> str:\n    return f'hi {name}'\n", encoding="utf-8")
    app = create_app(Settings(data_dir=tmp_path / "trainer_data"))
    runtime = app.state.runtime
    workspace_id = "ws-phase2"
    runtime.register_workspace_path(workspace_id, str(project_root))
    library_root = Path(runtime.sandbox_service.ensure_operation_root(workspace_id)).resolve()
    ctx = ToolContext(
        runtime=runtime,
        workspace_id=workspace_id,
        session_id="sess-phase2",
        response_language="zh-CN",
        extra={},
    )
    return runtime, ctx, project_root, library_root


def test_eight_orthogonal_primitives_across_protocols() -> None:
    registry = build_default_tool_registry()
    for protocol in (
        "openai_chat_completions",
        "openai_responses",
        "anthropic_messages",
        "gemini_generate_content",
    ):
        schemas = registry.as_protocol_schemas(protocol, orthogonal_only=True)
        names = [
            item["function"]["name"] if "function" in item else item["name"]
            for item in schemas
        ]
        assert names == list(ORTHOGONAL_PRIMITIVE_NAMES)
        assert len(names) == 8


def test_dynamic_per_turn_mounting_mounts_minimal_orthogonal_subset() -> None:
    library_extra = _build_agent_tool_context_extra(
        coach_context={"active_view": "resources", "library_sandbox_work": True},
        attachment_delivery={},
        answer_mode="auto",
        current_file=None,
        learner_message="帮我整理资料库里的笔记",
    )
    assert set(library_extra["allowed_tool_names"]) == {
        "library_read",
        "library_write",
        "library_exec",
        "web_fetch",
        "learning_inspect",
    }

    web_extra = _build_agent_tool_context_extra(
        coach_context={"active_view": "coach"},
        attachment_delivery={},
        answer_mode="auto",
        current_file=None,
        learner_message="帮我联网搜索最新的 FlashAttention 论文",
    )
    assert set(web_extra["allowed_tool_names"]) == {
        "web_fetch",
        "library_read",
        "library_write",
        "learning_inspect",
    }

    project_extra = _build_agent_tool_context_extra(
        coach_context={"active_view": "coach"},
        attachment_delivery={},
        answer_mode="auto",
        current_file={"path": "app.py", "content": "print(1)"},
        learner_message="解释一下 app.py 的逻辑",
    )
    assert set(project_extra["allowed_tool_names"]) == {
        "project_read",
        "project_verify",
        "library_read",
        "learning_inspect",
    }

    assert len(select_orthogonal_tools_for_turn({}, "请帮我梳理一下")) == 8


@pytest.mark.asyncio
async def test_project_read_only_and_library_autonomy_with_auto_fts5(tmp_path: Path) -> None:
    _runtime, ctx, project_root, library_root = _setup_ctx(tmp_path)
    registry = build_default_tool_registry()

    listed = await registry.invoke(ctx, "project_read", {"action": "list"})
    assert listed["ok"] is True
    assert listed["domain"] == "project_readonly"

    read_res = await registry.invoke(ctx, "project_read", {"action": "read", "path": "app.py"})
    assert read_res["ok"] is True
    assert "def greet" in str(read_res.get("content") or "")

    assert _validate_library_exec_command(
        f"ls {project_root}",
        library_root=library_root,
        project_root=project_root,
    ) is not None

    mk = await registry.invoke(ctx, "library_write", {"action": "mkdir", "path": "notes"})
    assert mk["ok"] is True
    assert (library_root / "notes").is_dir()

    written = await registry.invoke(
        ctx,
        "library_write",
        {
            "action": "write",
            "path": "notes/transformer_attention.md",
            "content": "# Transformer Attention\n\nScaled dot-product attention uses QK^T / sqrt(d_k).\n",
        },
    )
    assert written["ok"] is True
    assert written["auto_indexed"] is True

    searched = await registry.invoke(
        ctx,
        "library_read",
        {"action": "search", "query": "Scaled dot-product attention"},
    )
    assert searched["ok"] is True
    assert searched.get("hits"), f"expected auto-indexed FTS5 hit, got {searched!r}"

    edited = await registry.invoke(
        ctx,
        "library_write",
        {
            "action": "edit",
            "path": "notes/transformer_attention.md",
            "old_text": "sqrt(d_k)",
            "new_text": "sqrt(d_k) with softmax normalization",
        },
    )
    assert edited["ok"] is True
    assert edited["replacements"] == 1
    assert edited["auto_indexed"] is True

    grepped = await registry.invoke(
        ctx,
        "library_read",
        {"action": "grep", "query": "softmax normalization"},
    )
    assert grepped["ok"] is True
    assert any(m["path"] == "notes/transformer_attention.md" for m in grepped["matches"])

    deleted = await registry.invoke(
        ctx,
        "library_write",
        {"action": "soft_delete", "path": "notes/transformer_attention.md"},
    )
    assert deleted["ok"] is True
    assert deleted["soft_deleted"] is True
    assert not (library_root / "notes/transformer_attention.md").exists()
    assert deleted["trashed_path"]

    restored = await registry.invoke(
        ctx,
        "library_write",
        {
            "action": "restore",
            "path": deleted["trashed_path"],
            "restore_path": "notes/transformer_attention.md",
        },
    )
    assert restored["ok"] is True
    assert (library_root / "notes/transformer_attention.md").exists()

    exec_ok = await registry.invoke(ctx, "library_exec", {"command": "echo phase2_ok"})
    assert exec_ok["ok"] is True
    assert "phase2_ok" in exec_ok["stdout"]

    denied_plan = await registry.invoke(ctx, "learning_action", {"action": "save_formal_plan"})
    assert denied_plan["ok"] is False
    assert denied_plan["error"] == "formal_plan_mutation_required"
