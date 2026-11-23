"""Regression tests for 1M smart token budgeting, new backend tools, skills, and image generation."""

from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from provider_fixtures import seed_verified_capabilities

from app.core.models import ProviderConfig, ResourceUploadRequest
from app.core.settings import AppSettings
from app.llm.harness import DEFAULT_CONTEXT_WINDOW_TOKENS, READ_ONLY_TOOL_NAMES, TOOL_OUTPUT_LIMITS
from app.llm.image_generation import (
    resolve_generated_images_in_text,
    sanitize_generated_svg,
)
from app.llm.prompts import resolve_smart_history_budget
from app.llm.provider.thinking import clamp_wire_thinking_budget
from app.llm.provider_service import ProviderService
from app.llm.tools import ToolContext, build_default_tool_registry
from app.main import create_app


def _make_app(tmp_path: Path):
    settings = AppSettings(
        app_name="Trainer Smart Test",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path / "data",
        database_name="trainer-smart-test.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=True,
    )
    return create_app(settings)


def test_smart_token_budget_defaults_and_clamping() -> None:
    assert DEFAULT_CONTEXT_WINDOW_TOKENS == 1_000_000
    assert resolve_smart_history_budget(1_000_000) > (12, 1_800)
    assert resolve_smart_history_budget(128_000)[1] >= 8_000

    anthropic_payload = {
        "max_tokens": 8192,
        "thinking": {"type": "enabled", "budget_tokens": 32768},
    }
    clamped_anthropic = clamp_wire_thinking_budget(anthropic_payload)
    assert clamped_anthropic["thinking"]["budget_tokens"] < clamped_anthropic["max_tokens"]

    gemini_payload = {
        "generationConfig": {
            "maxOutputTokens": 4096,
            "thinkingConfig": {"thinkingBudget": 16384},
        }
    }
    clamped_gemini = clamp_wire_thinking_budget(gemini_payload)
    assert (
        clamped_gemini["generationConfig"]["thinkingConfig"]["thinkingBudget"]
        < clamped_gemini["generationConfig"]["maxOutputTokens"]
    )


def test_tool_registry_exposes_all_new_tools_and_safety_classifications() -> None:
    registry = build_default_tool_registry()
    names = set(registry.names())
    expected = {
        "search_academic_papers",
        "list_library_folders",
        "curate_library_resources",
        "list_skills",
        "invoke_skill",
        "generate_image",
    }
    assert expected.issubset(names)
    assert len(names) >= 43
    for tool_name in expected:
        assert tool_name in TOOL_OUTPUT_LIMITS
    for ro_name in ("search_academic_papers", "list_library_folders", "list_skills", "invoke_skill"):
        assert ro_name in READ_ONLY_TOOL_NAMES
    assert "curate_library_resources" not in READ_ONLY_TOOL_NAMES


def test_svg_sanitizer_strips_script_and_foreign_object() -> None:
    unsafe = (
        '<svg viewBox="0 0 200 100" onload="alert(1)">'
        '<script>alert(1)</script>'
        '<foreignObject><div>bad</div></foreignObject>'
        '<a href="javascript:alert(1)"><rect x="10" y="10" width="80" height="40" /></a>'
        '</svg>'
    )
    sanitized = sanitize_generated_svg(unsafe)
    assert "<script" not in sanitized.lower()
    assert "<foreignobject" not in sanitized.lower()
    assert "onload=" not in sanitized.lower()
    assert "javascript:" not in sanitized.lower()
    assert "<rect" in sanitized


def test_academic_search_skills_curation_and_image_generation(tmp_path: Path) -> None:
    app = _make_app(tmp_path)
    runtime = app.state.runtime
    ws_id = "ws-smart-tools"
    code_repo = tmp_path / "code_repo"
    code_repo.mkdir()
    library_root = tmp_path / "library_root"
    library_root.mkdir()
    runtime.register_workspace_path(ws_id, str(code_repo))
    runtime.resource_service.set_library_root_resolver(lambda _ws: library_root)

    uploaded = runtime.resource_service.upload(
        ws_id,
        ResourceUploadRequest(
            workspace_id=ws_id,
            name="world_models.md",
            source="world_models.md",
            kind="markdown",
            content="# World Models\nLatent dynamics and planning.",
        ),
    )

    registry = build_default_tool_registry()
    context = ToolContext(
        runtime=runtime,
        workspace_id=ws_id,
        response_language="zh-CN",
        extra={
            "custom_skills": [
                {
                    "id": "custom-arch",
                    "trigger": "$arch-check",
                    "title": "Architecture Check",
                    "detail": "Inspect module boundaries carefully.",
                    "prompt": "Compare boundaries before editing.",
                }
            ]
        },
    )

    with patch(
        "app.research.web_search.WebSearchClient._search_arxiv",
        return_value=[
            {
                "title": "World Models Survey (2026-10-01)",
                "url": "https://arxiv.org/abs/2610.00001",
                "source": "arxiv.org",
                "snippet": "Latent dynamics overview.",
                "rank": 1,
            }
        ],
    ):
        arxiv_res = asyncio.run(
            registry.get("search_academic_papers").handler(context, {"query": "world models", "limit": 3})
        )
    assert arxiv_res["ok"] is True
    assert arxiv_res["count"] == 1
    assert "arxiv.org" in arxiv_res["results"][0]["url"]

    skills_res = asyncio.run(registry.get("list_skills").handler(context, {}))
    skill_ids = {item["skill_id"] for item in skills_res["skills"]}
    assert {
        "rethinkfun-lecture",
        "visual-image-generator",
        "deep-web-research",
        "library-curator",
        "custom-arch",
    }.issubset(skill_ids)

    invoked_builtin = asyncio.run(
        registry.get("invoke_skill").handler(context, {"skill_id": "画图"})
    )
    assert invoked_builtin["ok"] is True
    assert invoked_builtin["skill_id"] == "visual-image-generator"
    assert "generate_image" in invoked_builtin["instructions"]

    invoked_custom = asyncio.run(
        registry.get("invoke_skill").handler(context, {"skill_id": "$arch-check"})
    )
    assert invoked_custom["ok"] is True
    assert invoked_custom["instructions"] == "Compare boundaries before editing."

    created = asyncio.run(
        registry.get("curate_library_resources").handler(
            context, {"action": "create_folder", "folder_path": "Papers/WorldModels"}
        )
    )
    assert created["ok"] is True

    moved = asyncio.run(
        registry.get("curate_library_resources").handler(
            context,
            {
                "action": "move_to_folder",
                "resource_id": uploaded.id,
                "folder_path": "Papers/WorldModels",
            },
        )
    )
    assert moved["ok"] is True
    assert "WorldModels/" in str(moved["resource"]["collection_path"] or "")

    folders = asyncio.run(registry.get("list_library_folders").handler(context, {}))
    assert folders["ok"] is True
    folder_paths = {node["path"] for node in folders["groups"]}
    assert "Papers/WorldModels" in folder_paths

    # Generate image offline -> deterministic SVG + Trainer Library copy + code repo untouched
    img_res = asyncio.run(
        registry.get("generate_image").handler(
            context,
            {
                "title": "World Model Loop",
                "prompt": "Observation -> Encoder -> Latent State -> Transition Model -> Planner",
                "style": "diagram",
                "aspect_ratio": "16:9",
            },
        )
    )
    assert img_res["ok"] is True
    image_id = img_res["image_id"]
    assert img_res["markdown"] == f"![World Model Loop](trainer-image://{image_id})"
    assert img_res["library_path"] and img_res["library_path"].startswith("Trainer Library/Generated Images/")
    assert list(code_repo.iterdir()) == []

    # Resolve inline trainer-image:// and fallback append when omitted
    resolved_inline = resolve_generated_images_in_text(
        f"Here is the flow:\n\n{img_res['markdown']}",
        runtime,
        context.extra.get("generated_image_ids"),
    )
    assert "trainer-image://" not in resolved_inline
    assert "data:image/svg+xml;base64," in resolved_inline

    resolved_omitted = resolve_generated_images_in_text(
        "Here is the explanation without pasting the markdown link.",
        runtime,
        context.extra.get("generated_image_ids"),
    )
    assert "![World Model Loop](data:image/svg+xml;base64," in resolved_omitted

    with TestClient(app) as client:
        resp = client.get(f"/generated-images/{image_id}")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("image/svg+xml")
        assert b"<svg" in resp.content

        assert client.get("/generated-images/not-valid!").status_code == 422
        assert client.get("/generated-images/img_doesnotexist").status_code == 404


def test_user_image_attachment_persists_preview_metadata(tmp_path: Path) -> None:
    import struct
    import zlib

    def _chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack("!I", len(data)) + tag + data + struct.pack("!I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack("!IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00\xff\x00\x00")
    png_bytes = b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", idat) + _chunk(b"IEND", b"")
    png_b64 = base64.b64encode(png_bytes).decode("ascii")
    app = _make_app(tmp_path)

    provider = ProviderConfig(
        name="mock-openai",
        base_url="http://127.0.0.1:9/v1",
        api_key_ref="trainer.mock",
        model="gpt-5.4",
        protocol="openai_chat_completions",
        capabilities={
            "chat": True,
            "responses": True,
            "vision": True,
            "embeddings": True,
            "tools": False,
            "json_schema": False,
            "streaming": True,
        },
    )
    runtime = app.state.runtime
    runtime.provider_config = provider
    runtime.provider_api_key = "sk-test-key"
    runtime.provider_service = ProviderService(config=provider, api_key="sk-test-key")
    runtime.provider_service_cache.clear()
    ws_id = "ws-img-preview"
    seed_verified_capabilities(runtime, provider, "sk-test-key", tools=False, vision=True)

    with TestClient(app) as client:
        session_resp = client.post(
            "/session/start",
            json={
                "workspace_context": {"workspace_id": ws_id, "name": "ImgPreview"},
                "user_profile": {"long_term_goals": ["Visual debugging"]},
            },
        )
        assert session_resp.status_code == 200
        session_id = session_resp.json()["session_id"]

        with (
            patch.object(
                ProviderService,
                "coaching_reply",
                return_value="Looked at your image attachment.",
            ),
            patch.object(
                ProviderService,
                "coaching_reply_agentic",
                return_value={
                    "content": "Looked at your image attachment.",
                    "steps": [],
                    "tool_events": [],
                    "stop_reason": "completed",
                },
            ),
        ):
            turn_resp = client.post(
                "/turn",
                json={
                    "session_id": session_id,
                    "workspace_id": ws_id,
                    "message": "请看这张图",
                    "attachments": [
                        {
                            "id": "att-1",
                            "kind": "image",
                            "mime_type": "image/png",
                            "data_base64": png_b64,
                            "name": "diagram.png",
                        }
                    ],
                },
            )
        assert turn_resp.status_code == 200, turn_resp.text
        snap_payload = turn_resp.json().get("snapshot")
        if not isinstance(snap_payload, dict) or not snap_payload.get("messages"):
            snap_resp = client.get(f"/snapshot?session_id={session_id}")
            assert snap_resp.status_code == 200
            snap_data = snap_resp.json()
            snap_payload = snap_data.get("snapshot") if isinstance(snap_data.get("snapshot"), dict) else snap_data
        messages = snap_payload["messages"]
        user_msg = next(msg for msg in reversed(messages) if msg["role"] == "user")
        previews = user_msg["metadata"].get("image_previews")
        assert isinstance(previews, list) and len(previews) == 1
        assert previews[0]["data_url"] == f"data:image/png;base64,{png_b64}"
