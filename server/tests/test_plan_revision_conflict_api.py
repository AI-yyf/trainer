"""Design §9 / TR multi-window: POST /plan/update under optimistic locking.

Two windows load the same plan at the same revision. The first save wins;
the second must get 409 plan_revision_conflict carrying the current head
revision — nothing silently overwritten. A window that omits
expected_revision is refused with 428 unless it explicitly labels a
legacy/migration save.
"""

from pathlib import Path

from fastapi.testclient import TestClient
from provider_fixtures import seed_verified_capabilities

from app.core.models import ProviderConfig
from app.core.settings import AppSettings
from app.llm.provider_service import ProviderService
from app.main import create_app


def build_client(tmp_path: Path) -> TestClient:
    settings = AppSettings(
        app_name="Trainer Plan Revision Conflict API Tests",
        host="127.0.0.1",
        port=8765,
        data_dir=tmp_path,
        database_name="trainer-plan-revision-conflict.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )
    app = create_app(settings)
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
    seed_verified_capabilities(runtime, provider, "sk-test", tools=False)
    return TestClient(app)


def generate_plan(client: TestClient, workspace_id: str) -> tuple[str, dict]:
    started = client.post(
        "/session/start",
        json={
            "user_profile": {
                "long_term_goals": ["Build a document Q&A trainer"],
                "weekly_hours": 6,
            },
            "workspace_context": {
                "workspace_id": workspace_id,
                "name": "trainer",
                "root_path": str(Path("/tmp") / workspace_id),
                "language": "python",
            },
        },
    )
    assert started.status_code == 200, started.text
    generated = client.post(
        "/plan/generate",
        json={
            "session_id": started.json()["session_id"],
            "objectives": ["Ship the first vertical slice of the trainer"],
        },
    )
    assert generated.status_code == 200, generated.text
    payload = generated.json()
    return payload["plan"]["plan_id"], payload


def test_two_windows_same_base_revision_second_save_conflicts(tmp_path: Path) -> None:
    workspace_id = "workspace-plan-conflict-api"
    with build_client(tmp_path) as client:
        plan_id, _ = generate_plan(client, workspace_id)
        runtime = client.app.state.runtime

        # Both windows read the plan at the same revision.
        base_revision = runtime.repository.get_plan_revision(workspace_id, plan_id)
        assert base_revision >= 1

        # Window A saves first and wins.
        window_a = client.post(
            "/plan/update",
            json={
                "plan_id": plan_id,
                "workspace_id": workspace_id,
                "title": "Window A title",
                "expected_revision": base_revision,
            },
        )
        assert window_a.status_code == 200, window_a.text
        assert window_a.json()["plan"]["title"] == "Window A title"
        assert window_a.json()["plan_revision"] == base_revision + 1

        # Window B still holds the base revision: rejected, nothing overwritten.
        window_b = client.post(
            "/plan/update",
            json={
                "plan_id": plan_id,
                "workspace_id": workspace_id,
                "title": "Window B title",
                "expected_revision": base_revision,
            },
        )
        assert window_b.status_code == 409, window_b.text
        detail = window_b.json()["detail"]
        assert detail["code"] == "plan_revision_conflict"
        assert detail["plan_id"] == plan_id
        assert detail["expected_revision"] == base_revision
        assert detail["current_revision"] == base_revision + 1
        stored_title = runtime.repository.get_plan_by_id(plan_id)[1].title
        assert stored_title == "Window A title"


def test_conflicted_window_reapplies_on_current_revision(tmp_path: Path) -> None:
    workspace_id = "workspace-plan-conflict-reapply"
    with build_client(tmp_path) as client:
        plan_id, _ = generate_plan(client, workspace_id)

        first = client.post(
            "/plan/update",
            json={
                "plan_id": plan_id,
                "workspace_id": workspace_id,
                "title": "Window A title",
                "expected_revision": 1,
            },
        )
        assert first.status_code == 200, first.text
        head = first.json()["plan_revision"]

        # Window B loses once, re-reads the head, then its change applies.
        stale = client.post(
            "/plan/update",
            json={
                "plan_id": plan_id,
                "workspace_id": workspace_id,
                "title": "Window B title",
                "expected_revision": 1,
            },
        )
        assert stale.status_code == 409
        reapplied = client.post(
            "/plan/update",
            json={
                "plan_id": plan_id,
                "workspace_id": workspace_id,
                "title": "Window B title",
                "expected_revision": stale.json()["detail"]["current_revision"],
            },
        )
        assert reapplied.status_code == 200, reapplied.text
        assert reapplied.json()["plan"]["title"] == "Window B title"
        assert reapplied.json()["plan_revision"] == head + 1


def test_update_without_expected_revision_is_refused_once_versioned(tmp_path: Path) -> None:
    workspace_id = "workspace-plan-conflict-legacy"
    with build_client(tmp_path) as client:
        plan_id, _ = generate_plan(client, workspace_id)
        runtime = client.app.state.runtime

        refused = client.post(
            "/plan/update",
            json={
                "plan_id": plan_id,
                "workspace_id": workspace_id,
                "title": "Blind overwrite",
            },
        )
        assert refused.status_code == 428, refused.text
        detail = refused.json()["detail"]
        assert detail["code"] == "plan_revision_required"
        assert detail["plan_id"] == plan_id
        assert detail["current_revision"] >= 1
        stored = runtime.repository.get_plan_by_id(plan_id)[1]
        assert stored.title != "Blind overwrite"

        # A caller that explicitly labels the compatibility path may still
        # save, and the revision advances so other windows notice the change.
        legacy = client.post(
            "/plan/update",
            json={
                "plan_id": plan_id,
                "workspace_id": workspace_id,
                "title": "Legacy save",
                "legacy": True,
            },
        )
        assert legacy.status_code == 200, legacy.text
        assert legacy.json()["plan"]["title"] == "Legacy save"
        assert runtime.repository.get_plan_revision(workspace_id, plan_id) >= 2


def test_concurrent_saves_on_one_base_admit_exactly_one(tmp_path: Path) -> None:
    """The revision check and the write are one SQLite transaction, so racing
    writers that all read the same base cannot both land."""
    from concurrent.futures import ThreadPoolExecutor

    from app.core.models import LearningPlan
    from app.db.repository import TrainerRepository

    repository = TrainerRepository(tmp_path / "plan-race.db")
    workspace_id = "workspace-plan-race"
    repository.save_plan(
        workspace_id,
        LearningPlan(id="plan-race", title="Base", stages=[]),
    )
    base_revision = repository.get_plan_revision(workspace_id, "plan-race")
    assert base_revision == 1

    def attempt(index: int):
        candidate = LearningPlan(id="plan-race", title=f"Writer {index}", stages=[])
        return repository.save_plan_with_revision(
            workspace_id, candidate, expected_revision=base_revision
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(attempt, range(8)))

    assert sum(1 for outcome in outcomes if outcome is not None) == 1
    assert repository.get_plan_revision(workspace_id, "plan-race") == base_revision + 1
