"""Phase 2 regressions: 8 dual-domain orthogonal primitives, <LibraryRoot> autonomy & auto-FTS5."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.core.config import Settings
from app.core.models import UserProfile
from app.llm.agent_loop import AgentProvider, CoachAgentLoop
from app.llm.agent_tool_context import _build_agent_tool_context_extra
from app.llm.coaching_replies import enforce_truthful_saved_note_path
from app.llm.harness import sandbox_operation_key, tool_output_limit, tools_are_read_only
from app.llm.prompts import build_coaching_system_prompt
from app.llm.resource_message_parts import build_resource_display_parts
from app.llm.tool_primitives import (
    ORTHOGONAL_PRIMITIVE_NAMES,
    _build_library_exec_env,
    _validate_library_exec_command,
    select_orthogonal_tools_for_turn,
)
from app.llm.tools import ToolContext, build_default_tool_registry
from app.main import create_app


def _setup_ctx(tmp_path: Path) -> tuple[Any, ToolContext, Path, Path]:
    project_root = tmp_path / "learner_project"
    project_root.mkdir(parents=True, exist_ok=True)
    (project_root / "app.py").write_text(
        "def greet(name: str) -> str:\n    return f'hi {name}'\n",
        encoding="utf-8",
    )
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

    assert (
        _validate_library_exec_command(
            f"ls {project_root}",
            library_root=library_root,
            project_root=project_root,
        )
        is not None
    )

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


def test_prompts_and_harness_have_zero_legacy_tool_disconnects() -> None:
    profile = UserProfile(
        long_term_goal="Master distributed systems",
        background="Python",
        weekly_hours=8,
        teaching_style="guided",
        answer_policy="guided",
    )
    plan_prompt = build_coaching_system_prompt(
        profile,
        message="请先搜索我的资料库，再制定并保存正式计划",
        coach_context={"active_view": "plan", "formal_plan_mutation": True, "scenario": "plan"},
        agent_loop_enabled=True,
    )
    assert "learning_action(action='save_formal_plan'" in plan_prompt
    assert "web_fetch(action='learning_materials'" in plan_prompt
    assert "web_fetch(action='assess_evidence'" in plan_prompt
    assert "library_read(action='search'" in plan_prompt
    assert "Call `search_resources`" not in plan_prompt
    assert "Call `save_formal_plan`" not in plan_prompt

    training_prompt = build_coaching_system_prompt(
        profile,
        message="请把这份推导整理一份讲稿并保存到资料库",
        coach_context={"active_view": "training", "scenario": "practice"},
        agent_loop_enabled=True,
    )
    assert "project_verify(action='verify_practice'" in training_prompt
    assert "library_write(action='save_lecture_note'" in training_prompt
    assert "verify_practice_current_file" not in training_prompt

    assert tool_output_limit("project_read") == 100_000
    assert tool_output_limit("library_read") == 100_000
    assert tool_output_limit("library_write") == 20_000
    assert tools_are_read_only(
        [
            {"name": "project_read", "arguments": {"action": "read", "path": "app.py"}},
            {"name": "library_read", "arguments": {"action": "search", "query": "attention"}},
            {"name": "web_fetch", "arguments": {"action": "search", "query": "arxiv"}},
        ]
    )
    assert not tools_are_read_only(
        [
            {"name": "web_fetch", "arguments": {"action": "import_url", "url": "https://example.com"}},
        ]
    )
    assert sandbox_operation_key("ws", "library_write", {"action": "write", "path": "a.md"}) is not None
    assert sandbox_operation_key("ws", "library_write", {"action": "organize", "operations": []}) is None


@pytest.mark.asyncio
async def test_formal_plan_research_synthesis_and_loop_repair_via_orthogonal_primitives(
    tmp_path: Path,
) -> None:
    runtime, ctx, _project_root, _library_root = _setup_ctx(tmp_path)
    registry = build_default_tool_registry()

    class _StubResearch:
        def search_web(self, query: str, **_kwargs: Any) -> dict[str, Any]:
            return {
                "query": query,
                "results": [
                    {
                        "id": "src-1",
                        "title": "Raft Consensus Specification",
                        "url": "https://raft.github.io/raft.pdf",
                        "source": "raft.github.io",
                        "snippet": "Leader election uses randomized election timeouts and term numbers.",
                        "evidence_excerpt": (
                            "Leader election uses randomized election timeouts and term numbers."
                        ),
                        "fetched_at": "2026-11-25T00:00:00+00:00",
                        "trust_score": 0.95,
                    }
                ],
            }

    runtime.research_service = _StubResearch()
    ctx.extra = {
        "allow_coach_only_tools": True,
        "formal_plan_mutation": True,
        "allowed_tool_names": [
            "learning_inspect",
            "learning_action",
            "project_read",
            "library_read",
            "web_fetch",
        ],
        "learner_message": "请帮我制定并保存一份 1 个阶段的 Raft 学习计划",
    }

    search_res = await registry.invoke(
        ctx,
        "web_fetch",
        {
            "action": "learning_materials",
            "query": "Raft leader election log replication",
            "required_facets": ["leader election", "term numbers"],
            "preferred_domains": ["raft.github.io"],
        },
    )
    assert search_res["ok"] is True
    assert search_res["action"] == "learning_materials"
    assert ctx.extra["allowed_tool_names"] == ["web_fetch"]

    # Calling another search before assess_evidence must fail-closed.
    premature_search = await registry.invoke(
        ctx,
        "web_fetch",
        {"action": "search", "query": "another search"},
    )
    assert premature_search["ok"] is False
    assert premature_search["error"] == "assessment_required_before_next_search"

    quality_checks = [
        {
            "dimension": dim,
            "status": "satisfied",
            "source_ids": ["src-1"],
            "rationale": f"Verified {dim} directly against the primary Raft specification.",
        }
        for dim in ("coverage", "source_quality", "recency", "contradictions", "applicability")
    ]
    assess_res = await registry.invoke(
        ctx,
        "web_fetch",
        {
            "action": "assess_evidence",
            "verdict": "sufficient",
            "evidence_standard": {
                "risk_level": "normal",
                "minimum_independent_sources": 1,
                "requires_authoritative_source": True,
                "claim_types": ["factual"],
                "freshness_requirement": "stable",
                "applicability_scope": "Core Raft consensus protocol mechanics.",
                "stopping_rule": "Stop once leader election and term numbers are directly quoted.",
                "unresolved_uncertainties": [],
                "quality_checks": quality_checks,
            },
            "facet_assessments": [
                {
                    "facet": "leader election",
                    "status": "covered",
                    "source_ids": ["src-1"],
                    "evidence_quotes": [
                        {
                            "source_id": "src-1",
                            "quote": "Leader election uses randomized election timeouts",
                        }
                    ],
                    "rationale": "Primary paper directly defines leader election timeout mechanics.",
                },
                {
                    "facet": "term numbers",
                    "status": "covered",
                    "source_ids": ["src-1"],
                    "evidence_quotes": [
                        {
                            "source_id": "src-1",
                            "quote": "randomized election timeouts and term numbers",
                        }
                    ],
                    "rationale": "Primary paper links term numbers to election rounds.",
                },
            ],
        },
    )
    assert assess_res["ok"] is True
    assert ctx.extra["allowed_tool_names"] == ["learning_action"]

    # Test CoachAgentLoop repair turn when model forgets to call learning_action(save_formal_plan) first:
    calls = {"n": 0}

    async def _provider_call(
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        calls["n"] += 1
        assert tools and any(
            (t.get("function", {}).get("name") or t.get("name")) == "learning_action"
            for t in tools
        )
        if calls["n"] == 1:
            return {"content": "Drafting your Raft plan without calling the save tool yet.", "tool_calls": []}
        if calls["n"] == 2:
            assert "learning_action(action='save_formal_plan'" in str(messages[-1].get("content"))
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "plan-save-1",
                        "name": "learning_action",
                        "arguments": {
                            "action": "save_formal_plan",
                            "title": "Raft 领导者选举实战计划",
                            "summary": "掌握随机超时与任期号单调性不变量。",
                            "stages": [
                                {
                                    "id": "stage-1",
                                    "title": "任期与选举超时",
                                    "goal": "实现任期递增与随机选举超时状态机。",
                                    "outcomes": ["通过单节点任期推进检查"],
                                    "resources": ["src-1"],
                                    "status": "active",
                                }
                            ],
                            "verify_method": ["检查任期号单调递增"],
                        },
                    }
                ],
            }
        return {"content": "已为你保存《Raft 领导者选举实战计划》。", "tool_calls": []}

    loop = CoachAgentLoop(
        provider=AgentProvider(protocol="openai_chat_completions", call=_provider_call),
        registry=registry,
        context=ctx,
        max_steps=5,
    )
    run_res = await loop.run([{"role": "user", "content": "请帮我制定并保存一份 1 个阶段的 Raft 学习计划"}])
    assert calls["n"] == 3
    assert run_res.stop_reason == "completed"
    saved_plan = runtime.repository.get_latest_plan(ctx.workspace_id)
    assert saved_plan is not None
    assert saved_plan.title == "Raft 领导者选举实战计划"


@pytest.mark.asyncio
async def test_lecture_note_record_note_curate_skill_and_citation_parts(tmp_path: Path) -> None:
    runtime, ctx, _project_root, _library_root = _setup_ctx(tmp_path)
    registry = build_default_tool_registry()
    ctx.extra = {
        "allow_coach_only_tools": True,
        "explicit_lecture_note_save_request": True,
        "explicit_learning_note_request": True,
        "custom_skills": [
            {
                "id": "state-flow",
                "trigger": "$state-flow",
                "title": "State Flow Check",
                "prompt": "Verify every variable by origin and role.",
            }
        ],
    }

    lecture = await registry.invoke(
        ctx,
        "library_write",
        {
            "action": "save_lecture_note",
            "title": "Attention Scaling Note",
            "content": "Dot products grow in variance with d_k, pushing softmax into flat regions.",
        },
    )
    assert lecture["ok"] is True
    assert lecture["action"] == "save_lecture_note"
    saved_path = str(lecture["saved_path"])
    patched_reply = enforce_truthful_saved_note_path(
        "已保存到 `Trainer Library/wrong-folder/guessed.md`。",
        [{"type": "tool_result", "name": "library_write", "ok": True, "result": lecture}],
    )
    assert saved_path in patched_reply
    assert "guessed.md" not in patched_reply

    note_res = await registry.invoke(
        ctx,
        "learning_action",
        {
            "action": "record_note",
            "content": "Learner prefers concrete variance examples before matrix notation.",
        },
    )
    assert note_res["ok"] is True
    assert note_res["action"] == "record_note"

    skill_res = await registry.invoke(
        ctx,
        "learning_action",
        {
            "action": "invoke_skill",
            "skill_name": "state-flow",
            "prompt": "Apply to attention scaling",
        },
    )
    assert skill_res["ok"] is True
    assert skill_res["skill_id"] == "state-flow"

    curated = await registry.invoke(
        ctx,
        "library_write",
        {
            "action": "curate",
            "curate_action": "create_folder",
            "folder_path": "Attention Papers",
        },
    )
    assert curated["ok"] is True
    assert curated["action"] == "curate"
    assert curated["curate_action"] == "create_folder"

    search_res = await registry.invoke(
        ctx,
        "library_read",
        {"action": "search", "query": "variance with d_k"},
    )
    assert search_res["ok"] is True
    parts = build_resource_display_parts(
        [
            {"type": "tool_result", "name": "library_read", "ok": True, "result": search_res},
            {
                "type": "tool_result",
                "name": "web_fetch",
                "ok": True,
                "result": {
                    "ok": True,
                    "action": "learning_materials",
                    "sources": [
                        {
                            "id": "web-1",
                            "title": "Attention Is All You Need",
                            "url": "https://arxiv.org/abs/1706.03762",
                        }
                    ],
                },
            },
        ],
        response_language="zh-CN",
    )
    assert any(p.get("referenceOrigin") == "library" for p in parts)
    assert any(p.get("referenceOrigin") == "web_research" for p in parts)


@pytest.mark.asyncio
async def test_line_slicing_excerpt_forwarding_grounding_and_turn_write_gates(
    tmp_path: Path,
) -> None:
    from app.llm.coaching_reply_drafts import _agentic_has_grounded_resource_evidence

    _runtime, ctx, project_root, _library_root = _setup_ctx(tmp_path)
    registry = build_default_tool_registry()

    ten_lines = "\n".join(f"line-{idx}" for idx in range(1, 11)) + "\n"
    (project_root / "multiline.py").write_text(ten_lines, encoding="utf-8")

    # 1. project_read(read) honors 1-based start_line / end_line before max_chars truncation
    sliced_proj = await registry.invoke(
        ctx,
        "project_read",
        {"action": "read", "path": "multiline.py", "start_line": 4, "end_line": 6},
    )
    assert sliced_proj["ok"] is True
    assert sliced_proj["content"] == "line-4\nline-5\nline-6"
    assert sliced_proj["start_line"] == 4
    assert sliced_proj["end_line"] == 6
    assert sliced_proj["total_lines"] == 10
    assert sliced_proj["line_count"] == 3

    # 2. library_write(write) + library_read(read_file) honors start_line / end_line
    padding = "padding_segment_" * 4
    written_a = await registry.invoke(
        ctx,
        "library_write",
        {
            "action": "write",
            "path": "notes/alpha.md",
            "content": "\n".join(
                f"alpha-{i}: unique_token_alpha {padding}" for i in range(1, 21)
            ),
        },
    )
    written_b = await registry.invoke(
        ctx,
        "library_write",
        {
            "action": "write",
            "path": "notes/beta.md",
            "content": "\n".join(f"beta-{i}: unique_token_alpha" for i in range(1, 6)),
        },
    )
    assert written_a["ok"] is True and written_b["ok"] is True

    sliced_lib = await registry.invoke(
        ctx,
        "library_read",
        {"action": "read_file", "path": "notes/alpha.md", "start_line": 3, "end_line": 5},
    )
    assert sliced_lib["ok"] is True
    assert sliced_lib["content"] == "\n".join(
        f"alpha-{i}: unique_token_alpha {padding}" for i in range(3, 6)
    )
    assert sliced_lib["line_count"] == 3

    # 3. library_read(search) filters by resource_ids and library_read(excerpt) maps max_chars -> chars
    res_a_id = str(written_a["resource_id"])
    filtered_search = await registry.invoke(
        ctx,
        "library_read",
        {
            "action": "search",
            "query": "unique_token_alpha",
            "resource_ids": [res_a_id],
        },
    )
    assert filtered_search["ok"] is True
    assert filtered_search["hits"]
    assert all(
        str(hit.get("resource_id") or hit.get("id")) == res_a_id
        for hit in filtered_search["hits"]
    )

    excerpt_res = await registry.invoke(
        ctx,
        "library_read",
        {"action": "excerpt", "resource_id": res_a_id, "max_chars": 240},
    )
    assert excerpt_res["ok"] is True
    assert excerpt_res["excerpts"]
    assert len(str(excerpt_res["excerpts"][0]["text"])) <= 260

    # 4. _agentic_has_grounded_resource_evidence recognizes orthogonal primitives and ignores failures
    assert (
        _agentic_has_grounded_resource_evidence(
            [{"type": "tool_result", "name": "project_read", "ok": False, "result": {"ok": False}}]
        )
        is False
    )
    for prim_name in ("project_read", "library_read", "web_fetch"):
        assert (
            _agentic_has_grounded_resource_evidence(
                [{"type": "tool_result", "name": prim_name, "ok": True, "result": {"ok": True}}]
            )
            is True
        )

    # 5. Unsolicited library mutations fail-closed on non-library agent-loop Q&A turns
    ctx.extra = _build_agent_tool_context_extra(
        coach_context={"active_view": "coach"},
        attachment_delivery={},
        answer_mode="guided",
        current_file=None,
        learner_message="请解释什么是尾递归优化",
    )
    blocked_write = await registry.invoke(
        ctx,
        "library_write",
        {"action": "write", "path": "notes/unrequested.md", "content": "should not write"},
    )
    assert blocked_write["ok"] is False
    assert blocked_write["error"] == "library_write_not_requested"

    blocked_exec = await registry.invoke(
        ctx,
        "library_exec",
        {"command": "echo unrequested"},
    )
    assert blocked_exec["ok"] is False
    assert blocked_exec["error"] == "library_write_not_requested"

    blocked_import = await registry.invoke(
        ctx,
        "web_fetch",
        {"action": "import_url", "url": "https://example.com"},
    )
    assert blocked_import["ok"] is False
    assert blocked_import["error"] == "library_write_not_requested"


@pytest.mark.asyncio
async def test_sandbox_operation_log_never_replays_stale_after_edit_delete_or_exec(
    tmp_path: Path,
) -> None:
    _runtime, ctx, _project_root, library_root = _setup_ctx(tmp_path)
    ctx.extra = {"library_sandbox_work": True}
    registry = build_default_tool_registry()

    first_write = await registry.invoke(
        ctx,
        "library_write",
        {"action": "write", "path": "notes/versioned.md", "content": "# v1\nalpha\n"},
    )
    assert first_write["ok"] is True
    assert first_write.get("replayed") is not True

    # Identical repeat while disk still matches v1 SHOULD replay idempotently.
    same_write = await registry.invoke(
        ctx,
        "library_write",
        {"action": "write", "path": "notes/versioned.md", "content": "# v1\nalpha\n"},
    )
    assert same_write["ok"] is True
    assert same_write.get("replayed") is True

    # Mutate file via surgical edit -> v2, then write v1 again: MUST NOT stale-replay!
    edited = await registry.invoke(
        ctx,
        "library_write",
        {
            "action": "edit",
            "path": "notes/versioned.md",
            "old_text": "# v1\nalpha",
            "new_text": "# v2\nbeta",
        },
    )
    assert edited["ok"] is True
    assert (library_root / "notes/versioned.md").read_text(encoding="utf-8") == "# v2\nbeta\n"

    rewrite_v1 = await registry.invoke(
        ctx,
        "library_write",
        {"action": "write", "path": "notes/versioned.md", "content": "# v1\nalpha\n"},
    )
    assert rewrite_v1["ok"] is True
    assert rewrite_v1.get("replayed") is not True
    assert (library_root / "notes/versioned.md").read_text(encoding="utf-8") == "# v1\nalpha\n"

    # Soft-delete to .trash/, then write v1 again: MUST recreate file on disk!
    deleted = await registry.invoke(
        ctx,
        "library_write",
        {"action": "soft_delete", "path": "notes/versioned.md"},
    )
    assert deleted["ok"] is True
    assert not (library_root / "notes/versioned.md").exists()

    recreated = await registry.invoke(
        ctx,
        "library_write",
        {"action": "write", "path": "notes/versioned.md", "content": "# v1\nalpha\n"},
    )
    assert recreated["ok"] is True
    assert recreated.get("replayed") is not True
    assert (library_root / "notes/versioned.md").is_file()

    # refresh_index must never be cached across external/exec file mutations.
    assert sandbox_operation_key(ctx.workspace_id, "library_write", {"action": "refresh_index", "path": "notes/versioned.md"}) is None
    assert sandbox_operation_key(ctx.workspace_id, "index_sandbox_file", {"path": "notes/versioned.md"}) is None
    first_refresh = await registry.invoke(
        ctx,
        "library_write",
        {"action": "refresh_index", "path": "notes/versioned.md"},
    )
    assert first_refresh["ok"] is True
    (library_root / "notes/versioned.md").write_text("# v3\ngamma_updated_token\n", encoding="utf-8")
    second_refresh = await registry.invoke(
        ctx,
        "library_write",
        {"action": "refresh_index", "path": "notes/versioned.md"},
    )
    assert second_refresh["ok"] is True
    assert second_refresh.get("replayed") is not True


def test_library_exec_blocks_quoted_tilde_env_and_inline_delete_escapes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _runtime, _ctx, project_root, library_root = _setup_ctx(tmp_path)
    outside_secret = tmp_path / "outside_secret.txt"
    outside_secret.write_text("top-secret", encoding="utf-8")

    forbidden_commands = [
        f'cat "{outside_secret}"',
        f"cat '{outside_secret}'",
        f"grep --file={outside_secret} root",
        f"python3 -c \"print(open('{outside_secret}').read())\"",
        f'cat "{project_root / "app.py"}"',
        "cat ~/Documents/secret.txt",
        'cat "~/Documents/secret.txt"',
        "cat $HOME/.ssh/id_rsa",
        'cat "${HOME}/.ssh/id_rsa"',
        "find . -name '*.md' -delete",
        "find . -type f -exec rm {} +",
        "echo note.md | xargs rm",
        '"rm" -rf notes',
        "python3 -c 'import os; os.remove(\"a.md\")'",
        "python3 -c 'import shutil; shutil.rmtree(\"notes\")'",
        "node -e 'fs.rmSync(\"a.md\")'",
        "ln -s /etc/passwd leak.txt",
        "git clean -fd",
        "cd",
        "cd -",
        'cat "unterminated_quote',
    ]
    for cmd in forbidden_commands:
        reason = _validate_library_exec_command(
            cmd,
            library_root=library_root,
            project_root=project_root,
        )
        assert reason is not None, f"Expected command to be blocked: {cmd!r}"

    # Safe commands inside <LibraryRoot> (including quoted relative filenames and /usr/bin tools) pass.
    safe_commands = [
        'python3 -c "from pathlib import Path; Path(\'summary.md\').write_text(\'ok\')"',
        '/usr/bin/env python3 -c "print(1 + 1)"',
        'grep -rn "alpha" "notes/my file.md" || true',
    ]
    for cmd in safe_commands:
        assert (
            _validate_library_exec_command(
                cmd,
                library_root=library_root,
                project_root=project_root,
            )
            is None
        ), f"Expected safe command to pass: {cmd!r}"

    # Packaged PyInstaller env isolation check.
    monkeypatch.setenv("_MEIPASS", "/var/folders/xx/_MEI12345")
    monkeypatch.setenv("_MEIPASS2", "/var/folders/xx/_MEI12345")
    monkeypatch.setenv("DYLD_LIBRARY_PATH", "/var/folders/xx/_MEI12345")
    monkeypatch.setenv("LD_LIBRARY_PATH", "/var/folders/xx/_MEI12345")
    monkeypatch.setenv("PYTHONPATH", "/var/folders/xx/_MEI12345/pkgs")
    monkeypatch.setenv("PYTHONHOME", "/var/folders/xx/_MEI12345")
    monkeypatch.setenv("PATH", "/var/folders/xx/_MEI12345:/usr/bin:/bin")
    clean_env = _build_library_exec_env(library_root)
    for stripped in (
        "_MEIPASS",
        "_MEIPASS2",
        "DYLD_LIBRARY_PATH",
        "LD_LIBRARY_PATH",
        "PYTHONPATH",
        "PYTHONHOME",
    ):
        assert stripped not in clean_env
    path_parts = clean_env["PATH"].split(":")
    assert all("_MEI" not in part for part in path_parts)
    assert path_parts[:2] == ["/opt/homebrew/bin", "/usr/local/bin"]
    assert clean_env["HOME"] == str(library_root)

