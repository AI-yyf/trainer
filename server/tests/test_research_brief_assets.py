"""Research Brief persistence: preparation output as a traceable library asset.

P2 of the Trainer 2.0 contract: research/lesson-prep results become manageable
``research_brief`` library assets (§五), with sourced claims traceable to their
resource references and model inference kept separate from source facts.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from provider_fixtures import seed_verified_capabilities

from app.core.models import (
    LearningPlan,
    PlanStage,
    ProjectContext,
    ResourceRecord,
    TrainerProject,
    TrainerRoot,
    UserProfile,
)
from app.core.settings import AppSettings
from app.llm.provider_service import ProviderService
from app.main import create_app
from app.resources.research_brief import preparation_requested
from app.resources.versioning import compute_content_hash

QUOTE = "A world model predicts the next latent state conditioned on the current state and action."
PAPER = "# World Models survey\n\n## State transitions\n\n" + QUOTE


def _client(data_dir: Path) -> TestClient:
    return TestClient(
        create_app(
            AppSettings(
                app_name="Trainer Research Brief Test",
                host="127.0.0.1",
                port=8765,
                data_dir=data_dir,
                database_name="research-brief.db",
                default_session_stage="intake",
                summary_message_limit=6,
            )
        )
    )


def _seed_context(client: TestClient, root_path: Path, suffix: str, *, with_resource: bool = True) -> ProjectContext:
    root_path.mkdir(parents=True, exist_ok=True)
    project_path = root_path / f"project-{suffix}"
    project_path.mkdir(exist_ok=True)
    context = ProjectContext(
        context_id=f"context-{suffix}",
        root_id=f"root-{suffix}",
        project_id=f"project-{suffix}",
        project_memory_id=f"memory-{suffix}",
        project_plan_id=f"plan-{suffix}",
        project_training_id=f"training-{suffix}",
        project_agent_context_id=f"agent-{suffix}",
        agent_session_id=f"session-{suffix}",
        legacy_workspace_id=f"legacy-{suffix}",
    )
    client.app.state.runtime.repository.create_project_context_bundle(
        root=TrainerRoot(
            root_id=context.root_id,
            root_path=str(root_path),
            display_name=f"Root {suffix}",
        ),
        project=TrainerProject(
            project_id=context.project_id,
            root_id=context.root_id,
            project_path=str(project_path),
            project_name=f"Project {suffix}",
        ),
        context=context,
        profile=UserProfile(),
        plan=LearningPlan(id=context.project_plan_id, title=f"Plan {suffix}"),
        structured_memory={},
        session_payload={
            "session_id": context.agent_session_id,
            "workspace_id": context.context_id,
        },
    )
    if not with_resource:
        return context
    runtime = client.app.state.runtime
    resource_id = "resource-world-models"
    version = runtime.resource_version_store.record_version(
        workspace_id=context.context_id, resource_id=resource_id, content=PAPER,
    )
    runtime.repository.save_resource(context.context_id, ResourceRecord(
        id=resource_id,
        kind="pdf",
        name="World Models survey",
        source=str(project_path / "world-models.pdf"),
        summary="A survey of world models.",
        index_status="indexed",
        version_id=version["version_id"],
        content_hash=version["content_hash"],
    ))
    runtime.resource_service._search_index(context.context_id).index_document(
        path="world-models.pdf", title="World Models survey", resource_id=resource_id,
        content=PAPER,
        metadata={
            **version, "content_length": len(PAPER), "canonical_text": True,
            "document_anchors": [
                {"line": 1, "kind": "page", "index": 1},
                {"line": 3, "kind": "page", "index": 2},
                {"line": 3, "kind": "heading", "index": 2, "label": "State transitions"},
            ],
        },
    )
    return context


def _brief_payload(**overrides: object) -> dict[str, object]:
    brief: dict[str, object] = {
        "researchGoal": "围绕世界模型论文完成备课",
        "keyQuestions": ["世界模型如何支持规划", "表示学习的目标是什么"],
        "findings": [
            {
                "statement": "论文将世界模型定义为状态转移的潜在预测器。",
                "claimStatus": "sourced",
                "sourceRefs": [
                    {
                        "kind": "resource",
                        "ref": "resource-world-models",
                        "label": "World Models survey §2",
                        "metadata": {
                            "resource_id": "resource-world-models",
                            "excerpt": QUOTE,
                            "location": {"page": 300},
                        },
                    }
                ],
                "location": "§2",
            },
            {
                "statement": "作者推断表示学习目标是后续工作的关键瓶颈。",
                "claimStatus": "inferred",
            },
            {
                "statement": "训练稳定性在长时程 rollout 下仍未解决。",
                "claimStatus": "unverified",
            },
        ],
        "sourceDisagreements": ["两篇综述对 reward shaping 的必要性结论相反"],
        "concepts": ["潜在状态", "一步预测"],
        "prerequisites": ["强化学习基础", "变分推断"],
        "knowledgeStructure": ["状态表示 → 转移预测 → 规划"],
        "teachingOrder": ["先讲状态表示，再讲预测目标"],
        "explanationStrategy": "ReThink Fund：先做一次 rollout 实验再讲原理",
        "examples": ["把世界模型类比成脑内模拟器"],
        "misconceptions": ["世界模型不是策略网络"],
        "checkQuestions": [
            {"question": "一步预测误差如何计算？", "acceptance": ["能写出损失项"]}
        ],
        "acceptanceCriteria": ["能不看资料推导一步预测损失"],
        "openQuestions": ["长时程 rollout 的稳定性"],
        "followUpResearch": ["对比 DreamerV3 与 MuZero 的表示学习"],
        "planId": "plan-world-models",
        "stageId": "stage-foundations",
    }
    brief.update(overrides)
    return brief


def _save_brief(
    client: TestClient,
    context: ProjectContext,
    *,
    asset_id: str | None = None,
    **overrides: object,
) -> dict:
    response = client.post(
        "/resource/research-brief",
        json={
            "assetId": asset_id,
            "title": "世界模型备课简报",
            "contextId": context.context_id,
            "brief": _brief_payload(**overrides),
            "sourceChain": [
                {"kind": "resource", "ref": "resource-world-models", "label": "World Models survey"}
            ],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_indexed_research_context_uses_document_lines_across_chunk_boundaries(tmp_path: Path) -> None:
    client = _client(tmp_path / "data")
    context = _seed_context(client, tmp_path / "roots", "canonical-citation")
    paper = "\n\n".join(["# Notes"] + [f"{index}. {QUOTE}" for index in range(30)] + ["## Wrap-up", "The final paragraph has no duplicate."])
    workspace = {"workspace_id": context.context_id, "session_id": context.agent_session_id}
    upload = client.post("/resource/upload", json={
        **workspace, "name": "Notes", "kind": "markdown", "source": "notes.md",
        "content": paper, "content_encoding": "utf-8",
    })
    assert upload.status_code == 200, upload.text
    resource_id = upload.json()["id"]
    indexed = client.post("/resource/index", json={**workspace, "resource_id": resource_id})
    assert indexed.status_code == 200, indexed.text
    resource = ResourceRecord.model_validate(indexed.json())
    service = client.app.state.runtime.resource_service
    body, anchors = service.indexed_source_text(context.context_id, resource)
    assert body == paper
    assert anchors[-1]["line"] == paper.splitlines().index("## Wrap-up") + 1


def test_research_brief_saves_lists_and_reads_as_a_library_asset(tmp_path: Path) -> None:
    client = _client(tmp_path / "data")
    context = _seed_context(client, tmp_path / "roots", "brief")

    saved = _save_brief(client, context)
    asset = saved["asset"]
    assert asset["assetType"] == "research_brief"
    assert asset["title"] == "世界模型备课简报"
    brief = saved["brief"]
    assert brief["researchGoal"] == "围绕世界模型论文完成备课"
    assert brief["findings"][0]["claimStatus"] == "sourced"
    # Traceability keys follow the evidence-citation contract (snake_case).
    metadata = brief["findings"][0]["sourceRefs"][0]["metadata"]
    assert metadata["resource_id"] == "resource-world-models"
    assert metadata["version_id"].startswith("rv-")
    assert metadata["content_hash"] == compute_content_hash(PAPER)
    assert metadata["location"] == {
        "page": 2, "heading": "State transitions", "line_start": 5, "line_end": 5,
        "anchor_id": "¶page2@5",
    }
    assert brief["planId"] == "plan-world-models"
    assert brief["stageId"] == "stage-foundations"
    assert asset["payload"]["findings"][2]["claimStatus"] == "unverified"

    listed = client.get(
        "/resource/research-briefs", params={"context_id": context.context_id}
    )
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["brief"]["researchGoal"] == brief["researchGoal"]

    fetched = client.get(
        f"/resource/research-briefs/{asset['id']}",
        params={"context_id": context.context_id},
    )
    assert fetched.status_code == 200
    assert fetched.json()["brief"]["checkQuestions"][0]["question"].startswith("一步预测误差")

    # Asset-typed listing: research briefs must not leak into generic knowledge.
    generic = client.get("/assets", params={"context_id": context.context_id})
    assert generic.status_code == 200
    generic_items = generic.json()["items"]
    assert generic_items, "the saved brief should appear in the generic asset list"
    assert all(item["assetType"] == "research_brief" for item in generic_items)


def test_research_brief_auto_links_to_the_live_plan_when_unspecified(tmp_path: Path) -> None:
    """P2.6: conclusions inherit the workspace's live plan and current stage."""
    client = _client(tmp_path / "data")
    context = _seed_context(client, tmp_path / "roots", "autolink")
    # The seed provisions a formal plan for the context; give it an active
    # stage so the auto-link can also pick the current stage.
    plan_id = "plan-autolink"
    runtime = client.app.state.runtime
    plan = runtime.repository.get_latest_plan(context.context_id)
    assert plan is not None and plan.id == plan_id
    from app.core.models import PlanStage
    linked_plan = plan.model_copy(update={
        "current_stage_id": "stage-2",
        "stages": [
            PlanStage(id="stage-1", title="Stage 1", goal="g", outcomes=[], status="completed"),
            PlanStage(id="stage-2", title="Stage 2", goal="g", outcomes=[], status="active"),
        ],
    })
    runtime.repository.save_plan(context.context_id, linked_plan)

    response = client.post(
        "/resource/research-brief",
        json={
            "title": "自动关联的简报",
            "contextId": context.context_id,
            "brief": _brief_payload(planId=None, stageId=None),
            "sourceChain": [{"kind": "resource", "ref": "resource-world-models", "label": "World Models survey"}],
        },
    )
    assert response.status_code == 200, response.text
    brief = response.json()["brief"]
    assert brief["planId"] == plan_id
    assert brief["stageId"] == "stage-2"

    # An explicitly stated plan is never overwritten.
    explicit = client.post(
        "/resource/research-brief",
        json={
            "title": "显式关联的简报",
            "contextId": context.context_id,
            "brief": _brief_payload(planId="plan-explicit", stageId=None),
            "sourceChain": [{"kind": "resource", "ref": "resource-world-models", "label": "World Models survey"}],
        },
    )
    assert explicit.json()["brief"]["planId"] == "plan-explicit"


def test_research_brief_updates_in_place_and_keeps_one_asset(tmp_path: Path) -> None:
    client = _client(tmp_path / "data")
    context = _seed_context(client, tmp_path / "roots", "update")

    first = _save_brief(client, context, openQuestions=["初始问题"])
    asset_id = first["asset"]["id"]
    updated = _save_brief(client, context, asset_id=asset_id, openQuestions=["更新后的待研究问题"])
    assert updated["asset"]["id"] == asset_id

    listed = client.get(
        "/resource/research-briefs", params={"context_id": context.context_id}
    )
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["brief"]["openQuestions"] == ["更新后的待研究问题"]


def test_sourced_findings_require_a_source_reference(tmp_path: Path) -> None:
    client = _client(tmp_path / "data")
    context = _seed_context(client, tmp_path / "roots", "trace")

    response = client.post(
        "/resource/research-brief",
        json={
            "title": "缺少出处的简报",
            "contextId": context.context_id,
            "brief": _brief_payload(
                findings=[{"statement": "一个没有出处的结论。", "claimStatus": "sourced"}]
            ),
        },
    )
    assert response.status_code == 422
    assert "sourceRef" in response.text

    # Inference stays allowed without sources — that is its declared status.
    ok = client.post(
        "/resource/research-brief",
        json={
            "title": "只含推断的简报",
            "contextId": context.context_id,
            "brief": _brief_payload(
                findings=[{"statement": "模型自己的推断。", "claimStatus": "inferred"}]
            ),
        },
    )
    assert ok.status_code == 200
    assert ok.json()["brief"]["findings"][0]["claimStatus"] == "inferred"


def test_research_brief_links_into_a_workspace_and_archives(tmp_path: Path) -> None:
    client = _client(tmp_path / "data")
    context = _seed_context(client, tmp_path / "roots", "link")

    saved = _save_brief(client, context)
    asset_id = saved["asset"]["id"]

    linked = client.post(
        f"/assets/{asset_id}/links",
        json={"contextId": context.context_id, "relation": "references", "sourceRef": "plan-stage-1"},
    )
    assert linked.status_code == 200, linked.text
    links = client.get(
        f"/assets/{asset_id}/links", params={"context_id": context.context_id}
    )
    assert links.json()["items"][0]["relation"] == "references"

    archived = client.post(
        f"/assets/{asset_id}/archive", json={"approved": True, "reason": "superseded"}
    )
    assert archived.status_code == 200
    active = client.get(
        "/resource/research-briefs", params={"context_id": context.context_id}
    )
    assert active.json()["total"] == 0
    restored = client.get(
        "/resource/research-briefs",
        params={"context_id": context.context_id, "include_deleted": True},
    )
    assert restored.json()["total"] == 1


@pytest.mark.parametrize("missing", ["researchGoal"])
def test_research_brief_requires_its_core_field(tmp_path: Path, missing: str) -> None:
    client = _client(tmp_path / "data")
    context = _seed_context(client, tmp_path / "roots", "core")
    payload = _brief_payload()
    payload.pop(missing)

    response = client.post(
        "/resource/research-brief",
        json={"title": "缺字段", "contextId": context.context_id, "brief": payload},
    )
    assert response.status_code == 422


_PROVIDER_BRIEF_JSON = """Here is the brief:

```json
{
  "researchGoal": "围绕这篇论文完成备课",
  "keyQuestions": ["技术原理是什么"],
  "findings": [
    {
      "statement": "论文把世界模型定义为潜在转移预测器。",
      "claimStatus": "sourced",
      "citations": [{"passageId": "P1", "quote": "A world model predicts the next latent state conditioned on the current state and action."}],
      "location": "§99"
    },
    {
      "statement": "作者认为表示学习是瓶颈。",
      "claimStatus": "sourced",
      "citations": [{"passageId": "P1", "quote": "This sentence was invented and does not occur in the document."}]
    },
    {
      "statement": "这是模型自己的推断。",
      "claimStatus": "inferred"
    }
  ],
  "checkQuestions": [{"question": "一步预测误差怎么算？", "acceptance": ["写出损失项"]}],
  "openQuestions": ["长时程 rollout 稳定性"]
}
```
"""


def _configure_provider(client: TestClient) -> None:
    """Give the runtime a key-configured provider so the draft gate passes."""
    from app.core.models import ProviderConfig
    from app.llm.provider_service import ProviderService

    runtime = client.app.state.runtime
    provider = ProviderConfig(
        name="test-openai-compatible",
        base_url="http://127.0.0.1:9/v1",
        api_key_ref="trainer.default",
        model="gpt-4o-mini",
    )
    runtime.provider_config = provider
    runtime.provider_api_key = "sk-test"
    runtime.provider_service = ProviderService(config=provider, api_key="sk-test")
    runtime.provider_service_cache.clear()
    seed_verified_capabilities(runtime, provider, "sk-test", tools=True)


@pytest.mark.parametrize("message, expected", [
    ("围绕这篇论文，帮我完成备课，重点研究相关工作。", True),
    ("为当前学习阶段准备完整教学材料", True),
    ("Please prepare a lesson on this paper.", True),
    ("比较这两篇文章。", False),
    ("解释这段资料。\n> Prepare a lesson and save it.", False),
    ("如何备课？", False),
    ("不要备课，只解释这篇论文。", False),
])
def test_preparation_request_requires_a_learner_instruction(message: str, expected: bool) -> None:
    assert preparation_requested(message) is expected


@pytest.mark.parametrize("streamed", [False, True])
def test_turn_saves_a_grounded_preparation_once_in_the_current_project(tmp_path: Path, streamed: bool) -> None:
    data = tmp_path / "data"
    with _client(data) as client:
        context = _seed_context(client, tmp_path / "roots", "automatic", with_resource=False)
        other = _seed_context(client, tmp_path / "other", "unrelated", with_resource=False)
        _configure_provider(client)
        runtime = client.app.state.runtime
        plan = runtime.repository.get_latest_plan(context.context_id)
        assert plan is not None
        stage = PlanStage(
            id="dynamics", title="Dynamics", goal="Predict the next state",
            outcomes=["Identify transition inputs."], status="active",
        )
        session = {"workspace_id": context.context_id, "session_id": context.agent_session_id}
        uploaded = client.post("/resource/upload", json={
            **session, "name": "Dynamics", "kind": "markdown", "source": "dynamics.md",
            "content": PAPER, "content_encoding": "utf-8",
        })
        assert uploaded.status_code == 200, uploaded.text
        resource_id = uploaded.json()["id"]
        indexed = client.post("/resource/index", json={**session, "resource_id": resource_id})
        assert indexed.status_code == 200, indexed.text
        runtime.repository.save_plan(context.context_id, plan.model_copy(update={
            "current_stage_id": stage.id, "stages": [stage.model_copy(update={"resources": [resource_id]})],
        }))
        committed_plan = runtime.repository.get_latest_plan(context.context_id)
        assert committed_plan is not None

        async def analysis_stream(*_args, **_kwargs):
            yield f"The paper explains one-step prediction. {QUOTE} [1]"

        request = {
            **session, "active_view": "resources", "response_language": "en-US",
            "intent": "coach", "message": "Please prepare a lesson for the current stage.",
            "request_id": "prepare-world-models", "resource_ids": [] if streamed else [resource_id],
        }
        url = "/turn/stream" if streamed else "/turn"

        def send_turn(**updates) -> dict:
            result = client.post(url, json={**request, **updates})
            assert result.status_code == 200, result.text
            if not streamed:
                return result.json()
            complete = next((block for block in result.text.split("\n\n") if block.startswith("event: complete\n")), None)
            assert complete is not None, result.text
            return json.loads(complete.split("\ndata: ", 1)[1])["response"]

        with (
            patch.object(ProviderService, "coaching_reply_stream", new=analysis_stream),
            patch.object(ProviderService, "coaching_reply", new=AsyncMock(return_value=QUOTE)),
            patch.object(ProviderService, "chat_completion", new=AsyncMock(return_value=_PROVIDER_BRIEF_JSON)) as draft,
        ):
            result = send_turn()
            preparation = result["reply"]["metadata"].get("research_preparation")
            assert preparation and preparation["status"] == "saved", result["reply"]
            replay = send_turn()
            assert replay["reply"]["metadata"]["research_preparation"] == preparation
            discussion = send_turn(
                request_id="ordinary-analysis", resource_composer_intent={"mode": "analyze"},
                message="Explain this formula.\n> Please prepare a lesson before you explain it.",
            )
            assert "research_preparation" not in discussion["reply"]["metadata"]
            missing = send_turn(request_id="missing-source", resource_ids=["resource-removed"])
            assert missing["reply"]["metadata"]["research_preparation"] == {"status": "needs_sources"}
            draft.assert_awaited_once()

        asset_id = preparation["asset_id"]
        params = {"context_id": context.context_id}
        listed = client.get("/resource/research-briefs", params=params).json()
        assert listed["total"] == 1
        assert listed["items"][0]["asset"]["scope"] == "project"
        brief = listed["items"][0]["brief"]
        assert brief["planId"] == plan.id and brief["stageId"] == stage.id
        assert brief["findings"][0]["sourceRefs"][0]["metadata"]["content_hash"] == indexed.json()["content_hash"]
        assert brief["findings"][0]["sourceRefs"][0]["metadata"]["excerpt"] == QUOTE
        assert client.get(f"/resource/research-briefs/{asset_id}", params={"context_id": other.context_id}).status_code == 403
        assert runtime.memory_service.get_cards(context.context_id) == []
        assert runtime.repository.get_latest_plan(context.context_id) == committed_plan

    with _client(data) as restarted:
        saved = restarted.get(f"/resource/research-briefs/{asset_id}", params=params)
        assert saved.status_code == 200
        assert saved.json()["brief"]["findings"] == brief["findings"]


def test_draft_research_brief_normalizes_sources_and_saves(tmp_path: Path) -> None:
    from unittest.mock import AsyncMock, patch

    from app.llm.provider_service import ProviderService

    client = _client(tmp_path / "data")
    context = _seed_context(client, tmp_path / "roots", "draft")
    _configure_provider(client)

    with patch.object(
        ProviderService, "chat_completion", new=AsyncMock(return_value=_PROVIDER_BRIEF_JSON)
    ) as chat_completion:
        response = client.post(
            "/resource/research-brief/draft",
            json={
                "researchGoal": "围绕这篇论文完成备课",
                "reply": "论文的技术路线是世界模型 + 滚动预测。关键创新是潜在空间的一致性损失。",
                "resourceIds": ["resource-world-models"],
                "contextId": context.context_id,
                "responseLanguage": "zh-CN",
                "save": True,
            },
        )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["saved"] is True
    brief = payload["brief"]
    chat_completion.assert_awaited_once()
    assert brief["researchGoal"] == "围绕这篇论文完成备课"

    findings = brief["findings"]
    # The claim tied to the attached resource stays sourced, with server-pinned version/hash.
    assert findings[0]["claimStatus"] == "sourced"
    pin = findings[0]["sourceRefs"][0]
    assert pin["ref"] == "resource-world-models"
    assert pin["metadata"]["version_id"].startswith("rv-")
    assert pin["metadata"]["content_hash"] == compute_content_hash(PAPER)
    assert pin["metadata"]["excerpt"] == QUOTE
    assert pin["metadata"]["location"]["line_start"] == 5
    assert pin["metadata"]["location"]["page"] == 2
    assert findings[0]["location"] == "¶page2@5"
    assert findings[1]["claimStatus"] == "unverified"
    assert findings[1]["sourceRefs"] == []
    assert findings[2]["claimStatus"] == "inferred"

    listed = client.get("/resource/research-briefs", params={"context_id": context.context_id})
    assert listed.json()["total"] == 1
    asset = listed.json()["items"][0]["asset"]
    assert [ref["ref"] for ref in asset["sourceChain"]] == ["resource-world-models"]


def test_draft_research_brief_can_return_a_draft_without_saving(tmp_path: Path) -> None:
    from unittest.mock import AsyncMock, patch

    from app.llm.provider_service import ProviderService

    client = _client(tmp_path / "data")
    context = _seed_context(client, tmp_path / "roots", "preview")
    _configure_provider(client)

    with patch.object(
        ProviderService, "chat_completion", new=AsyncMock(return_value=_PROVIDER_BRIEF_JSON)
    ):
        response = client.post(
            "/resource/research-brief/draft",
            json={
                "researchGoal": "备课",
                "reply": "分析内容。",
                "contextId": context.context_id,
                "save": False,
            },
        )
    assert response.status_code == 200
    assert response.json()["saved"] is False
    listed = client.get("/resource/research-briefs", params={"context_id": context.context_id})
    assert listed.json()["total"] == 0


def test_draft_research_brief_fails_closed_without_a_provider(tmp_path: Path) -> None:
    client = _client(tmp_path / "data")
    context = _seed_context(client, tmp_path / "roots", "noprov")

    response = client.post(
        "/resource/research-brief/draft",
        json={
            "researchGoal": "备课",
            "reply": "分析内容。",
            "contextId": context.context_id,
            "save": True,
        },
    )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "provider_unavailable"
    listed = client.get("/resource/research-briefs", params={"context_id": context.context_id})
    assert listed.json()["total"] == 0


def test_draft_research_brief_rejects_invalid_provider_output(tmp_path: Path) -> None:
    from unittest.mock import AsyncMock, patch

    from app.llm.provider_service import ProviderService

    client = _client(tmp_path / "data")
    context = _seed_context(client, tmp_path / "roots", "badjson")
    _configure_provider(client)

    with patch.object(
        ProviderService, "chat_completion", new=AsyncMock(return_value="完全不是 JSON 的回复。")
    ):
        response = client.post(
            "/resource/research-brief/draft",
            json={
                "researchGoal": "备课",
                "reply": "分析内容。",
                "contextId": context.context_id,
                "save": True,
            },
        )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_provider_output"
    listed = client.get("/resource/research-briefs", params={"context_id": context.context_id})
    assert listed.json()["total"] == 0
