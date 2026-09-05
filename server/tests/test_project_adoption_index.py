from __future__ import annotations

from pathlib import Path

import app.workspace.adoption_index as adoption_index
from app.workspace.adoption_index import ProjectAdoptionIndexService


class _HeldThread:
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        pass

    def start(self) -> None:
        return None


def test_queued_job_is_not_mistaken_for_a_restart_before_its_worker_starts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "trainer-workspace"
    project = root / "Projects" / "sample"
    project.mkdir(parents=True)
    monkeypatch.setattr(adoption_index, "Thread", _HeldThread)
    service = ProjectAdoptionIndexService()

    started = service.start(
        workspace_id="workspace-1",
        discovery_id="discovery-1",
        project_path=str(project),
        project_name="sample",
        root_id="root-1",
        root_path=str(root),
        context_id="context-1",
    )

    observed = service.get(root_path=str(root), job_id=started.job_id)

    assert observed is not None
    assert observed.status == "queued"
    assert observed.retry_reason is None


def test_missing_project_path_interrupts_inventory_without_finalizing(tmp_path: Path) -> None:
    service = ProjectAdoptionIndexService()

    inventory = service._scan_project(str(tmp_path / "missing-project"))

    assert inventory["status"] == "interrupted"
    assert inventory["truncated"] is True
    assert inventory["files"] == []
    assert inventory["message"] == "Project path is no longer available."
