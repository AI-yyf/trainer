"""Journey fixture: provision one adopted project context for a scenario run.

Scenario 2's resource-grounded candidate cards require an adopted workspace
(provisioned Root/Project/Context). The headless journey has no VS Code
admission flow, so it seeds the same canonical bundle the tests and the host
adoption route write — one python invocation, argv:

    python journey_provision.py <data_dir> <db_filename> <workspace_id> <workspace_name>

Side effect only: creates the bundle if it does not exist. Idempotent.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "server"))

from app.core.models import (  # noqa: E402
    LearningPlan,
    PlanStage,
    ProjectContext,
    TrainerProject,
    TrainerRoot,
    UserProfile,
)
from app.db.repository import TrainerRepository  # noqa: E402
from app.memory.service import MemoryService  # noqa: E402
from app.planner.service import PlannerService  # noqa: E402


def main() -> int:
    data_dir = Path(sys.argv[1])
    db_filename = sys.argv[2]
    workspace_id = sys.argv[3]
    workspace_name = sys.argv[4] or "Journey Workspace"

    suffix = workspace_id.replace("-workspace", "") or "journey"
    repository = TrainerRepository(data_dir / db_filename)
    context = ProjectContext(
        context_id=workspace_id,
        root_id=f"root-{suffix}",
        project_id=f"project-{suffix}",
        project_memory_id=f"memory-{suffix}",
        project_plan_id=f"plan-{suffix}",
        project_training_id=f"training-{suffix}",
        project_agent_context_id=f"agent-{suffix}",
        agent_session_id=f"session-{suffix}",
        legacy_workspace_id=workspace_id,
    )
    workspace_root = data_dir / "workspace"
    workspace_root.mkdir(parents=True, exist_ok=True)
    structured_memory = {
        "workspace": {
            "workspace_id": context.context_id,
            "context_id": context.context_id,
            "root_id": context.root_id,
            "root_path": str(data_dir),
            "project_id": context.project_id,
            "project_path": str(workspace_root),
            "canonical_project_path": str(workspace_root),
            "project_name": workspace_name,
            "project_memory": {"id": context.project_memory_id},
            "project_training_state": {"id": context.project_training_id},
            "project_agent_context": {"id": context.project_agent_context_id},
            "project_provisioning": context.model_dump(mode="json", by_alias=True),
        }
    }
    repository.create_project_context_bundle(
        root=TrainerRoot(
            root_id=context.root_id,
            root_path=str(data_dir),
            display_name=f"Root {suffix}",
        ),
        project=TrainerProject(
            project_id=context.project_id,
            root_id=context.root_id,
            project_path=str(workspace_root),
            project_name=workspace_name,
        ),
        context=context,
        profile=UserProfile(),
        plan=LearningPlan(
            id=context.project_plan_id,
            title=workspace_name,
            stages=[
                PlanStage(
                    id="stage-foundations",
                    title="基础",
                    goal="建立核心概念",
                    outcomes=[],
                    status="active",
                ),
            ],
            current_stage_id="stage-foundations",
        ),
        structured_memory=structured_memory,
        session_payload={
            "session_id": context.agent_session_id,
            "workspace_id": context.context_id,
        },
    )
    # Verify through the real service (same gate the resource-card route uses),
    # so a journey that needs provisioned lanes fails here with the exact error.
    from app.workspace.provisioning import ProjectProvisioningService
    memory_service = MemoryService(repository, event_ledger=None)
    planner_service = PlannerService(repository=repository)
    service = ProjectProvisioningService(
        repository=repository,
        memory_service=memory_service,
        planner_service=planner_service,
    )
    verified = service.get(context.context_id)
    if verified is None:
        print("verify failed: provisioning not found", file=sys.stderr)
        return 3
    print(context.context_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
