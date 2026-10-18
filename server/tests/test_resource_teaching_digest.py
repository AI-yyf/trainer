"""Just-in-time teaching digestion: a resource the coach actually used gets
digested (总结/预备题目/直观案例/常见误区) with one LLM call, cached by content
hash — never a blanket sweep, never paid for twice."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.settings import AppSettings
from app.main import create_app

WORKSPACE_ID = "ws-teaching-digest"


def _settings(data_dir: Path) -> AppSettings:
    return AppSettings(
        app_name="Trainer teaching digest",
        host="127.0.0.1",
        port=8765,
        data_dir=data_dir,
        database_name="trainer-teaching-digest.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )


class StubProviderService:
    has_api_key = True

    def __init__(self) -> None:
        self.calls = 0

    async def chat_completion(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> str:
        self.calls += 1
        return (
            '{"summary": "旋转护栏在重试队列排空之前执行。", '
            '"practice_questions": ["护栏为何先于队列运行？", "跳过护栏会怎样？", "如何临时禁用它？"], '
            '"intuitive_examples": ["像门禁先于闸机放行。", "像编译前的语法检查。"], '
            '"common_pitfalls": ["误以为护栏在队列之后运行。", "把禁用当成配置错误。"]}'
        )


def _indexed_resource(client: TestClient) -> dict:
    session_id = client.post(
        "/session/start",
        json={"workspace_id": WORKSPACE_ID, "workspace_name": "Digest"},
    ).json()["session_id"]
    upload = client.post(
        "/resource/upload",
        json={
            "session_id": session_id,
            "workspace_id": WORKSPACE_ID,
            "kind": "markdown",
            "name": "Rotation guard notes",
            "source": "notes/rotation-guard.md",
            "content": "# Rotation guard\n\nThe rotation guard runs before the retry queue drains.",
            "source_type": "file",
        },
    )
    assert upload.status_code == 200, upload.text
    record = upload.json()
    indexed = client.post(
        "/resource/index",
        json={
            "session_id": session_id,
            "workspace_id": WORKSPACE_ID,
            "resource_id": record["id"],
            "enable_network": False,
        },
    )
    assert indexed.status_code == 200, indexed.text
    return indexed.json()


def test_digest_generates_four_assets_then_caches_by_content(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path / "data"))
    runtime = app.state.runtime
    runtime.provider_service = StubProviderService()
    record = _indexed_resource(TestClient(app))

    first = asyncio.run(runtime.digest_resource_for_teaching(WORKSPACE_ID, record["id"]))
    assert first is not None and first["cached"] is False
    assets = first["assets"]
    assert len(assets) == 4
    kinds = {asset.kind for asset in assets}
    assert kinds == {"concept_card", "exercise_set", "code_examples", "common_pitfall"}
    # Every digest section must land in the text field its kind maps to (see
    # stage_material_composer._CONTENT_FIELD_BY_KIND): the model ignores unknown
    # fields (extra="ignore"), so a wrong field name silently drops the body.
    by_kind = {asset.kind: asset for asset in assets}
    assert "旋转护栏" in by_kind["concept_card"].concept_card
    assert "护栏为何先于队列运行？" in by_kind["exercise_set"].exercise_seed
    assert "门禁先于闸机放行" in by_kind["code_examples"].example
    assert "误以为护栏在队列之后运行" in by_kind["common_pitfall"].common_pitfall
    assert all(asset.scenario == "resource_digest" for asset in assets)
    assert all("resource-digest::" in asset.source_key for asset in assets)

    # Same content version: the cache answers, the provider is not called again.
    second = asyncio.run(runtime.digest_resource_for_teaching(WORKSPACE_ID, record["id"]))
    assert second is not None and second["cached"] is True
    assert len(second["assets"]) == 4
    assert runtime.provider_service.calls == 1


def test_digest_skips_without_provider_or_unindexed_resource(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path / "data"))
    runtime = app.state.runtime
    record = _indexed_resource(TestClient(app))

    # No provider configured: a quiet skip, never an error surfaced to a turn.
    assert asyncio.run(runtime.digest_resource_for_teaching(WORKSPACE_ID, record["id"])) is None

    runtime.provider_service = StubProviderService()
    # An unknown/unindexed id is skipped as well.
    assert asyncio.run(runtime.digest_resource_for_teaching(WORKSPACE_ID, "resource-nope")) is None
