from app.memory.transfer_skills import (
    apply_transfer_skill_to_coach_orientation,
    build_transfer_skill_state_record,
    resolve_skill_scene_key,
    should_promote_transferable_skill,
)


def test_single_scene_does_not_promote() -> None:
    assert (
        should_promote_transferable_skill(
            concept="tool calling",
            workspace_id="project-a",
            outcome_success=True,
            existing_scenes=[],
        )
        is False
    )


def test_two_cards_same_default_scene_do_not_promote() -> None:
    scene = {"workspace_id": "project-a", "scene_key": "default"}
    assert (
        should_promote_transferable_skill(
            concept="tool calling",
            workspace_id="project-a",
            current_scene_key="default",
            existing_scenes=[scene],
            outcome_success=True,
        )
        is False
    )


def test_second_workspace_promotes() -> None:
    assert should_promote_transferable_skill(
        concept="tool calling",
        workspace_id="project-b",
        current_scene_key="default",
        existing_scenes=[{"workspace_id": "project-a", "scene_key": "default"}],
        outcome_success=True,
    )


def test_transfer_ids_without_evidence_stay_default_scene() -> None:
    assert (
        resolve_skill_scene_key(
            transfer_source_workspace_id="project-a",
            transfer_target_workspace_id="project-b",
            transfer_evidence_summary="",
        )
        == "default"
    )
    assert (
        should_promote_transferable_skill(
            concept="tool calling",
            workspace_id="project-b",
            outcome_success=True,
            transfer_source_workspace_id="project-a",
            transfer_target_workspace_id="project-b",
            existing_scenes=[],
        )
        is False
    )


def test_distinct_evidenced_scenes_in_same_workspace_do_not_promote() -> None:
    first = resolve_skill_scene_key()
    second = resolve_skill_scene_key(
        transfer_source_context="billing route",
        transfer_target_context="docs sandbox",
        transfer_evidence_summary="Applied the same guard in a second task.",
    )
    leftover = resolve_skill_scene_key(
        transfer_source_context="Keep the leftover plan",
        transfer_target_context="docs sandbox",
        transfer_evidence_summary="Applied the same guard against the leftover object.",
    )
    assert first == "default"
    assert second.startswith("transfer:")
    assert leftover.startswith("transfer:")
    assert (
        should_promote_transferable_skill(
            concept="response model",
            workspace_id="project-a",
            current_scene_key=second,
            existing_scenes=[{"workspace_id": "project-a", "scene_key": first}],
            outcome_success=True,
        )
        is False
    )
    assert (
        should_promote_transferable_skill(
            concept="response model",
            workspace_id="project-a",
            current_scene_key=leftover,
            existing_scenes=[{"workspace_id": "project-a", "scene_key": first}],
            outcome_success=True,
        )
        is False
    )


def test_failure_never_promotes() -> None:
    assert (
        should_promote_transferable_skill(
            concept="tool calling",
            workspace_id="project-b",
            existing_scenes=[{"workspace_id": "project-a", "scene_key": "default"}],
            outcome_success=False,
        )
        is False
    )


def test_copy_never_claims_global_mastery_from_one_scene() -> None:
    awaiting = build_transfer_skill_state_record(
        concept="tool calling",
        scenes=[{"workspace_id": "project-a", "scene_key": "default"}],
        language="en-US",
    )
    assert awaiting["state"] == "awaiting_second_scene"
    assert "mastered" not in awaiting["why"].lower()
    assert "global" not in awaiting["why"].lower()

    transferable = build_transfer_skill_state_record(
        concept="tool calling",
        scenes=[
            {"workspace_id": "project-a", "scene_key": "default"},
            {"workspace_id": "project-b", "scene_key": "default"},
        ],
        language="en-US",
    )
    assert transferable["state"] == "transferable"
    assert "mastered" not in transferable["why"].lower()


def test_orientation_overlay_does_not_steal_blockers() -> None:
    blocked = apply_transfer_skill_to_coach_orientation(
        {
            "object_kind": "provider",
            "state": "needs_setup",
            "next_step": "Save and test a provider first.",
            "advanced_where": "Settings · provider",
        },
        {
            "state": "transferable",
            "why": "This skill has evidence in more than one scene.",
            "next": "Schedule a review, or apply it in a new challenge.",
        },
    )
    assert blocked["next_step"] == "Save and test a provider first."

    ready = apply_transfer_skill_to_coach_orientation(
        {
            "object_kind": "plan",
            "state": "ready",
            "next_step": "Continue on this object, or check Plan.",
            "advanced_where": "Plan · current step",
        },
        {
            "state": "transferable",
            "why": "This skill has evidence in more than one scene.",
            "next": "Schedule a review, or apply it in a new challenge.",
        },
    )
    assert ready["next_step"] == "Schedule a review, or apply it in a new challenge."
    assert "more than one scene" in ready["advanced_where"]
