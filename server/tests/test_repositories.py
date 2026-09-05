import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.models import (
    ChatMessage,
    GlobalPlan,
    GlobalPlanProjectLink,
    LearningPlan,
    MemoryShareGrant,
    PlanPhase,
    PlanUpdateRequest,
    ResourceRecord,
    SubPlan,
    TeachingKnowledgeAsset,
    UserProfile,
    WorkspaceContext,
)
from app.db.database import Database
from app.db.repositories import PlanRepository, SessionRepository
from app.db.repository import TrainerRepository


def test_session_message_request_contract_accepts_request_id() -> None:
    from app.core.models import SessionMessageRequest

    request = SessionMessageRequest.model_validate({"message": "hello", "requestId": "req-1"})
    assert request.request_id == "req-1"


def test_session_repository_persists_messages(tmp_path: Path) -> None:
    database = Database(tmp_path / "repo.db")
    database.initialize()
    sessions = SessionRepository(database)

    session = sessions.create_session(
        user_profile=UserProfile(long_term_goals=["Learn FastAPI"]),
        workspace_context=WorkspaceContext(name="trainer"),
        stage="intake",
        summary="Initial summary",
    )
    sessions.add_message(session.session_id, ChatMessage(role="user", content="Hello"))
    sessions.add_message(session.session_id, ChatMessage(role="assistant", content="Hi"))

    restored = sessions.get_session(session.session_id)
    messages = sessions.list_messages(session.session_id)

    assert restored is not None
    assert restored.summary == "Initial summary"
    assert [message.role for message in messages] == ["user", "assistant"]


def test_plan_repository_updates_existing_plan(tmp_path: Path) -> None:
    database = Database(tmp_path / "repo.db")
    database.initialize()
    sessions = SessionRepository(database)
    plans = PlanRepository(database)

    session = sessions.create_session(
        user_profile=UserProfile(long_term_goals=["Learn FastAPI"]),
        workspace_context=WorkspaceContext(name="trainer"),
        stage="intake",
        summary="Initial summary",
    )

    plan = LearningPlan(
        plan_id="plan-1",
        session_id=session.session_id,
        title="Starter",
        objective="Learn the workflow",
        phases=[
            PlanPhase(
                title="Phase 1",
                objective="Start",
                exercises=["Exercise 1"],
                completion_signal="Done",
            )
        ],
        weekly_cadence="4 hours per week",
    )
    plans.create_plan(plan)

    updated = plans.update_plan(
        PlanUpdateRequest(
            plan_id="plan-1",
            title="Updated Starter",
            frozen=True,
        )
    )

    assert updated is not None
    assert updated.title == "Updated Starter"
    assert updated.frozen is True


def test_trainer_repository_round_trips_resource_curation_metadata(tmp_path: Path) -> None:
    repository = TrainerRepository(tmp_path / "trainer-resource.db")
    resource = ResourceRecord(
        id="resource-1",
        kind="markdown",
        name="External Note",
        source="/tmp/external-note.md",
        summary="A grounded trainer note.",
        parse_status="parsed",
        index_status="indexed",
        source_type="local:markdown",
        canonical_source="/tmp/external-note.md",
        fetched_at="2026-05-03T00:00:00+00:00",
        trust_score=0.82,
        freshness="fresh",
        duplicate_key="markdown:/tmp/external-note.md:abc123",
        quality_flags=["grounded"],
        warnings=[],
        knowledge_fragments=[
            {
                "id": "frag-1",
                "resource_id": "resource-1",
                "title": "External Note",
                "snippet": "A grounded trainer note.",
                "summary": "A grounded trainer note.",
                "source": "/tmp/external-note.md",
                "source_type": "local:markdown",
                "kind": "markdown",
                "trust_score": 0.82,
                "freshness": "fresh",
                "fetched_at": "2026-05-03T00:00:00+00:00",
                "duplicate_key": "markdown:/tmp/external-note.md:abc123",
                "quality_flags": ["grounded"],
                "focus_area": "External Note",
                "line_start": None,
                "line_end": None,
                "why_it_matters": "Useful for H1.",
            }
        ],
    )
    repository.save_resource("workspace-1", resource)
    restored = repository.list_resources("workspace-1")
    assert len(restored) == 1
    assert restored[0].duplicate_key == resource.duplicate_key
    assert restored[0].trust_score == resource.trust_score
    assert restored[0].knowledge_fragments == resource.knowledge_fragments


def test_trainer_repository_save_resource_supports_legacy_composite_resource_key_schema(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "trainer-legacy-resource.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE resources (
                resource_id TEXT NOT NULL,
                workspace_id TEXT NOT NULL,
                payload TEXT NOT NULL,
                PRIMARY KEY (workspace_id, resource_id)
            )
            """
        )
        connection.commit()

    repository = TrainerRepository(db_path)
    resource = ResourceRecord(
        id="resource-legacy",
        kind="markdown",
        name="Legacy Resource",
        source="/tmp/legacy-note.md",
        summary="Legacy resource upload should still work.",
    )

    repository.save_resource("workspace-legacy", resource)
    updated = resource.model_copy(update={"summary": "Updated payload still persists."})
    repository.save_resource("workspace-legacy", updated)

    restored = repository.list_resources("workspace-legacy")
    assert len(restored) == 1
    assert restored[0].id == "resource-legacy"
    assert restored[0].summary == "Updated payload still persists."


def test_trainer_repository_round_trips_teaching_assets(tmp_path: Path) -> None:
    repository = TrainerRepository(tmp_path / "trainer-asset.db")
    asset = TeachingKnowledgeAsset(
        kind="concept_card",
        scope="project",
        workspace_id="workspace-asset",
        title="Router boundary",
        summary="Keep orchestration thin.",
        concept_card="Keep orchestration thin.",
        explanation_recipe="Use one boundary at a time.",
        origin="resource",
        source_key="resource::one::concept",
        source_ids=["resource-1"],
        source_fragments=["server/app/api/routers.py"],
        evidence_snippets=["Keep orchestration thin.", "Use one boundary at a time."],
        retrieval_hints=["router", "coach", "boundary"],
        source_summary="A reusable router boundary note.",
        source_quality_flags=["grounded"],
        source_freshness="fresh",
        source_retrieved_at="2026-05-03T00:00:00+00:00",
        tags=["router", "coach"],
        trust_score=0.8,
    )
    repository.save_teaching_asset("workspace-asset", asset)

    restored = repository.list_teaching_assets("workspace-asset")
    assert len(restored) == 1
    assert restored[0].title == asset.title
    assert restored[0].source_key == asset.source_key
    assert restored[0].concept_card == asset.concept_card
    assert restored[0].origin == "resource"
    assert restored[0].evidence_snippets == asset.evidence_snippets
    assert restored[0].retrieval_hints == asset.retrieval_hints
    assert restored[0].source_summary == asset.source_summary
    assert restored[0].source_quality_flags == asset.source_quality_flags
    assert restored[0].source_freshness == asset.source_freshness
    assert restored[0].source_retrieved_at == asset.source_retrieved_at


def test_trainer_repository_lists_general_and_personal_teaching_assets_for_workspace(tmp_path: Path) -> None:
    repository = TrainerRepository(tmp_path / "trainer-asset-scope.db")
    project_asset = TeachingKnowledgeAsset(
        kind="implementation_pattern",
        scope="project",
        workspace_id="workspace-alpha",
        title="Alpha pattern",
        summary="Project-only pattern.",
        implementation_pattern="Project-only pattern.",
        source_key="project::alpha",
        trust_score=0.8,
    )
    personal_asset = TeachingKnowledgeAsset(
        kind="explanation_recipe",
        scope="personal",
        workspace_id="workspace-alpha",
        title="Personal explanation",
        summary="Personal reusable explanation.",
        explanation_recipe="Personal reusable explanation.",
        source_key="personal::alpha",
        trust_score=0.72,
    )
    general_asset = TeachingKnowledgeAsset(
        kind="concept_card",
        scope="general",
        workspace_id="__global__",
        title="General concept",
        summary="General reusable concept.",
        concept_card="General reusable concept.",
        source_key="general::concept",
        trust_score=0.75,
    )
    foreign_project_asset = TeachingKnowledgeAsset(
        kind="common_pitfall",
        scope="project",
        workspace_id="workspace-beta",
        title="Beta pitfall",
        summary="Foreign project pitfall.",
        common_pitfall="Foreign project pitfall.",
        source_key="project::beta",
        trust_score=0.68,
    )
    repository.save_teaching_asset("workspace-alpha", project_asset)
    repository.save_teaching_asset("workspace-alpha", personal_asset)
    repository.save_teaching_asset("workspace-alpha", general_asset)
    repository.save_teaching_asset("workspace-beta", foreign_project_asset)

    restored = repository.list_teaching_assets("workspace-alpha")
    titles = {asset.title for asset in restored}
    assert "Alpha pattern" in titles
    assert "Personal explanation" in titles
    assert "General concept" in titles
    assert "Beta pitfall" not in titles


def test_trainer_repository_persists_memory_share_grants(tmp_path: Path) -> None:
    database_path = tmp_path / "trainer-memory-share-grants.db"
    repository = TrainerRepository(database_path)
    grant = MemoryShareGrant(
        source_workspace_id="workspace-source",
        target_workspace_id="workspace-target",
        categories=["preferences"],
    )

    repository.save_memory_share_grant(grant)

    restored = repository.get_memory_share_grant("workspace-source", "workspace-target")
    assert restored is not None
    assert restored.categories == ["preferences"]

    updated = grant.model_copy(update={"categories": ["mastery"]})
    repository.save_memory_share_grant(updated)
    rebuilt = TrainerRepository(database_path)
    listed = rebuilt.list_memory_share_grants("workspace-target")
    assert len(listed) == 1
    assert listed[0].categories == ["mastery"]
    assert rebuilt.delete_memory_share_grant("workspace-source", "workspace-target") is True
    assert rebuilt.list_memory_share_grants("workspace-target") == []


def test_trainer_repository_persists_subplans(tmp_path: Path) -> None:
    database_path = tmp_path / "trainer-subplans.db"
    repository = TrainerRepository(database_path)
    repository.save_plan("workspace-1", LearningPlan(id="plan-1", title="Parent plan"))
    subplan = SubPlan(
        id="subplan-1",
        parent_plan_id="plan-1",
        title="Persisted sub-plan",
        description="Retains its stages across a sidecar restart.",
    )

    repository.save_subplan("plan-1", subplan)

    restored = repository.get_subplan("plan-1", "subplan-1")
    assert restored is not None
    assert restored.title == "Persisted sub-plan"

    updated = subplan.model_copy(update={"title": "Updated sub-plan"})
    repository.save_subplan("plan-1", updated)
    rebuilt = TrainerRepository(database_path)
    assert [item.title for item in rebuilt.list_subplans("plan-1")] == ["Updated sub-plan"]
    assert rebuilt.delete_subplan("plan-1", "subplan-1") is True
    assert rebuilt.list_subplans("plan-1") == []


def test_trainer_repository_persists_global_plan_and_project_link(tmp_path: Path) -> None:
    database_path = tmp_path / "trainer-global-plan.db"
    repository = TrainerRepository(database_path)
    owner = repository.ensure_default_local_owner()
    project_plan = LearningPlan(id="project-plan-1", title="Current project plan")
    repository.save_plan("workspace-1", project_plan)
    global_plan = GlobalPlan(
        id="global-plan-1",
        owner_id=owner.id,
        title="Long-term mastery",
        goals=["Ship durable work across projects"],
    )

    repository.save_global_plan(global_plan)
    repository.save_global_plan_project_link(
        GlobalPlanProjectLink(
            global_plan_id=global_plan.id,
            workspace_id="workspace-1",
            project_plan_id=project_plan.id,
        )
    )

    rebuilt = TrainerRepository(database_path)
    restored = rebuilt.get_default_global_plan()
    assert restored is not None
    assert restored.title == "Long-term mastery"
    link = rebuilt.get_global_plan_project_link(
        global_plan.id,
        "workspace-1",
        project_plan.id,
    )
    assert link is not None
    assert link.project_plan_id == project_plan.id
    assert rebuilt.delete_global_plan_project_link(global_plan.id, "workspace-1") is True
    assert rebuilt.get_global_plan_project_link(global_plan.id, "workspace-1") is None
