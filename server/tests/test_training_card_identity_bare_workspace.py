"""Bare-workspace card file identity: a card's own target must stay verifiable.

Measured failure (full-journey run, 2026-11-12): a model-authored card named
``ppo_loss.py`` as its only files_to_touch target, the workspace had no
project root, and the identity check 409'd the card's own target because
``canonical()`` returns "" without a project and the leaf-name rescue was
gated on ``project``. Verifying a card's declared target must not require a
registered project root; a non-target file must still be rejected.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.models import ActiveCardSelectionResult, TrainingCardCandidateSnapshot
from app.core.settings import AppSettings
from app.main import create_app


def _settings(data_dir: Path) -> AppSettings:
    return AppSettings(
        app_name="Trainer bare workspace card identity",
        host="127.0.0.1",
        port=8765,
        data_dir=data_dir,
        database_name="trainer-card-identity-bare.db",
        default_session_stage="intake",
        summary_message_limit=6,
        enable_network_fetch=False,
    )


@pytest.fixture()
def bare_workspace(tmp_path: Path):
    app = create_app(_settings(tmp_path / "data"))
    client = TestClient(app)
    runtime = app.state.runtime
    workspace_id = "bare-card-ws"
    runtime.repository.save_session(
        "session-bare",
        workspace_id,
        {
            "session_id": "session-bare",
            "workspace_id": workspace_id,
            "stage": "intake",
            "messages": [],
        },
    )
    card = TrainingCardCandidateSnapshot(
        card_id="card-bare-target",
        card_type="practice",
        title="从概率比到 PPO 裁剪目标",
        status="active",
        focus_area="PPO 裁剪目标",
        target_skill="解释 clip 分支",
        why_now="知识缺口",
        scenario="工作区中的 `ppo_loss.py` 已完成概率比计算。",
        files_to_touch=["ppo_loss.py"],
    )
    runtime.memory_service.upsert_card(workspace_id, card)
    runtime.memory_service.persist_active_card_selection(
        workspace_id,
        ActiveCardSelectionResult(
            selected_card=card,
            selected_card_id=card.card_id,
            why_this_card="Live selected card.",
            next_after_completion="Verify.",
            fallback_action="Return to coach.",
            candidate_count=1,
            eligible_count=1,
        ),
    )
    return client, runtime, workspace_id


def test_card_target_file_passes_identity_without_project_root(bare_workspace) -> None:
    client, runtime, workspace_id = bare_workspace
    from app.api.training_card_identity import prepare_training_file_evaluation
    from app.core.models import EvaluateCurrentFileRequest

    request = EvaluateCurrentFileRequest(
        file_path="ppo_loss.py",
        language_id="python",
        content="print(1)",
        evaluation_source="training",
        training_card_id="card-bare-target",
    )
    prepared = prepare_training_file_evaluation(runtime, workspace_id, request)
    assert prepared.file_path == "ppo_loss.py"


def test_non_target_file_still_rejected_without_project_root(bare_workspace) -> None:
    client, runtime, workspace_id = bare_workspace
    from app.api.training_card_identity import prepare_training_file_evaluation
    from app.core.models import EvaluateCurrentFileRequest

    request = EvaluateCurrentFileRequest(
        file_path="unrelated.py",
        language_id="python",
        content="print(1)",
        evaluation_source="training",
        training_card_id="card-bare-target",
    )
    with pytest.raises(Exception) as excinfo:
        prepare_training_file_evaluation(runtime, workspace_id, request)
    assert "not a target" in str(getattr(excinfo.value, "detail", excinfo.value))


def test_nested_card_target_exact_match_on_bare_workspace(bare_workspace) -> None:
    """A bare-workspace card naming a nested relative path must match exactly,
    not only via the leading-slash suffix form."""
    from app.api.training_card_identity import prepare_training_file_evaluation
    from app.core.models import EvaluateCurrentFileRequest

    card = runtime_card(bare_workspace)
    card = card.model_copy(update={"files_to_touch": ["trainer/ppo_loss.py"]})
    runtime, workspace_id = bare_workspace[1], bare_workspace[2]
    runtime.memory_service.upsert_card(workspace_id, card)

    request = EvaluateCurrentFileRequest(
        file_path="trainer/ppo_loss.py",
        language_id="python",
        content="print(1)",
        evaluation_source="training",
        training_card_id="card-bare-target",
    )
    prepared = prepare_training_file_evaluation(runtime, workspace_id, request)
    assert prepared.file_path == "trainer/ppo_loss.py"


def runtime_card(bare_workspace):
    runtime, workspace_id = bare_workspace[1], bare_workspace[2]
    return runtime.memory_service.get_card(workspace_id, "card-bare-target")


def test_verify_current_file_http_accepts_card_target_on_bare_workspace(bare_workspace) -> None:
    client, _runtime, workspace_id = bare_workspace
    response = client.post(
        "/evaluate/current-file",
        json={
            "session_id": "session-bare",
            "workspace_id": workspace_id,
            "file_path": "ppo_loss.py",
            "language_id": "python",
            "content": "def add(a, b):\n    return a + b\n",
            "evaluation_source": "training",
            "training_phase": "verify",
            "training_card_id": "card-bare-target",
        },
    )
    assert response.status_code == 200, response.text
