"""Coach turn helpers moved out of build_router (§五十二 extraction).

The helpers share one dependency bundle (``CoachSupportDeps``) assembled by
``build_router``. Keeping the bundle explicit makes the closure graph visible
instead of hiding 45 names inside a 25k-line function.
"""

from __future__ import annotations

from typing import get_args

from ...core.models import (
    CoachingState,
    CoachScenario,
    LearningPlan,
    TaskSpec,
    WorkbenchSnapshot,
)
from ...llm.prompts import infer_learner_signal as infer_message_learner_signal
from ...llm.training_review_context import active_training_review
from ...memory.workspace_recovery import (
    coach_focus_runtime_from_snapshot,
    live_coaching_next_step,
    live_leftover_focus_candidate,
    live_plan_update_persist_chrome,
    live_task_focus_area,
    live_task_suggested_title,
    live_task_thin_slice_copy,
)
from .._helpers import (
    localized_text,
    prefers_chinese,
)
from ..router_support import (
    _request_is_plan_agent_turn as _request_is_plan_agent_turn,
)
from ..router_support import (
    reset_provider_scheme_cache as reset_provider_scheme_cache,
)
from .types_and_deps import CoachSupportDeps


def build_coaching_artifacts(deps: CoachSupportDeps,
    *,
    scenario: str,
    response_language: str | None,
    coaching_state: CoachingState | None,
    memory,
    message: str | None = None,
    task: TaskSpec | None = None,
    plan: LearningPlan | None = None,
    evaluation=None,
    snapshot: WorkbenchSnapshot | None = None,
    grounding_context: dict[str, object] | None = None,
    completed_return: bool = False,
    active_view: str | None = None,
) -> dict[str, object]:
    artifacts: dict[str, object] = {}
    recall = active_training_review(memory, deps.normalize_active_view_name(active_view))
    if recall is not None:
        recall_rule = recall.guardrail or recall.next_self_implementation_rule
        return {"review": deps.artifact_payload(
            kind="review", title=recall.title, summary=recall.summary,
            content="\n\n".join(part for part in [recall.summary, recall_rule] if part),
            bullets=[recall_rule], focus_area=recall.focus_area,
            metadata={"review_artifact_id": recall.id, "evidence_scope": "self_reported_recall",
                      "status": recall.status},
        )}

    def stored_exercise_prompt() -> dict[str, object] | None:
        if snapshot is None:
            return None
        workspace = snapshot.memory.workspace
        if not isinstance(workspace, dict):
            return None
        return deps.normalized_object_mapping(workspace.get("exercise_prompt"))

    evaluation_checks = (
        [*evaluation.static_checks, *evaluation.dynamic_checks, *evaluation.semantic_checks]
        if evaluation
        else []
    )
    failing_checks = [check.label for check in evaluation_checks if check.status in {"failed", "warning"}]
    active_stage = None
    if plan:
        active_stage = next(
            (stage for stage in plan.stages if stage.id == plan.current_stage_id or stage.status == "active"),
            plan.stages[0] if plan.stages else None,
        )
    leftover_runtime = coach_focus_runtime_from_snapshot(snapshot)
    leftover_focus = live_leftover_focus_candidate(
        plan=plan,
        runtime=leftover_runtime,
        existing=leftover_runtime,
        stage_title=active_stage.title if active_stage else "",
        task_title=task.title if task else "",
    )

    if task and scenario in {"task", "next_task"}:
        artifacts["task"] = task.model_dump()
    if plan and scenario == "plan":
        artifacts["plan"] = plan.model_dump()
    if evaluation and scenario == "review":
        artifacts["evaluation"] = evaluation.model_dump()

    title = deps.coach_artifact_title(
        scenario,
        response_language,
        task=task,
        plan=plan,
        evaluation_summary=evaluation.summary if evaluation else None,
        snapshot=snapshot,
        runtime=leftover_runtime,
    )
    summary = coaching_state.summary if coaching_state else memory.current_focus
    focus_bundle = deps.coach_focus_bundle(
        memory=memory,
        response_language=response_language,
        scenario=scenario,
        coaching_state=coaching_state,
        message=message,
        task=task,
        plan=plan,
        grounding_context=grounding_context,
        snapshot=snapshot,
    )
    persist_workspace_id = ""
    if snapshot is not None:
        persist_workspace = snapshot.memory.workspace if isinstance(snapshot.memory.workspace, dict) else {}
        persist_workspace_id = str(
            persist_workspace.get("workspace_id")
            or persist_workspace.get("workspaceId")
            or getattr(snapshot, "context_id", "")
            or ""
        ).strip()
    if persist_workspace_id:
        deps.runtime.memory_service.persist_turn_context_pressure(
            persist_workspace_id,
            coach_focus=focus_bundle,
        )

    if scenario == "idea_implementation":
        guide = snapshot.implementation_guide if snapshot and snapshot.implementation_guide else None
        exercise_prompt = stored_exercise_prompt()
        entry_point = (
            guide.codebase_entry_points[0]
            if guide and guide.codebase_entry_points
            else ""
        )
        bullets = [
            localized_text(
                "Current focus: keep the first patch inside one thin, visible slice.",
                "当前聚焦点：把第一版 patch 限制在一个很小、可见的范围里。",
                response_language,
            ),
            localized_text(
                f"Start in: {entry_point}",
                f"建议起点：{entry_point}",
                response_language,
            )
            if entry_point
            else "",
            guide.current_step if guide and guide.current_step else coaching_state.next_step if coaching_state else "",
            guide.success_signal if guide and guide.success_signal else "",
            localized_text(
                "Review rhythm: verify it immediately before widening the change.",
                "\u590d\u76d8\u8282\u594f\uff1a\u505a\u5b8c\u7acb\u523b\u9a8c\u8bc1\uff0c\u518d\u6269\u5927\u6539\u52a8\u8303\u56f4\u3002",
                response_language,
            ),
        ]
        if memory.teaching_observations:
            bullets.append(
                localized_text(
                    f"Teaching note: {memory.teaching_observations[0]}",
                    f"教学提醒：{memory.teaching_observations[0]}",
                    response_language,
                )
            )
        artifacts["idea_implementation"] = deps.artifact_payload(
            kind="idea_implementation",
            title=title,
            summary=summary,
            bullets=bullets[:4],
            teaser=guide.current_step if guide and guide.current_step else coaching_state.next_step if coaching_state else "",
            recommended_action="task",
            rationale=localized_text(
                "The coach is turning your idea into a persistent implementation lane with one thin next move, not just describing it.",
                "这里会把你的想法整理成一条能持续推进的实现主线，并明确下一小步，而不只是描述它。",
                response_language,
            ),
            focus_area=live_task_focus_area(
                plan=plan,
                task=task,
                runtime=leftover_runtime,
                existing=leftover_runtime,
                task_title=task.title if task else "",
                fallback="implementation" if not task else "",
            ),
            verification=(
                guide.validation_strategy[:2]
                if guide and guide.validation_strategy
                else [
                    localized_text(
                        "Verify the first working path before widening scope.",
                        "\u5148\u9a8c\u8bc1\u7b2c\u4e00\u6761\u5de5\u4f5c\u8def\u5f84\uff0c\u518d\u6269\u5927\u8303\u56f4\u3002",
                        response_language,
                    )
                ]
            ),
            content=deps.render_artifact_content(
                title=title,
                summary=summary,
                bullets=bullets,
                verification=(
                    guide.validation_strategy[:2]
                    if guide and guide.validation_strategy
                    else [
                        localized_text(
                            "Verify the first working path before widening scope.",
                            "\u5148\u9a8c\u8bc1\u7b2c\u4e00\u6761\u5de5\u4f5c\u8def\u5f84\uff0c\u518d\u6269\u5927\u8303\u56f4\u3002",
                            response_language,
                        )
                    ]
                ),
                rationale=localized_text(
                    "The coach is turning your idea into a persistent implementation lane with one thin next move, not just describing it.",
                    "这里会把你的想法整理成一条能持续推进的实现主线，并明确下一小步，而不只是描述它。",
                    response_language,
                ),
                metadata={"background_mode": "embedded", "coach_focus": focus_bundle},
                extras=[
                    *((
                        [
                            localized_text(
                                f"### MVP boundary\n\n{guide.mvp_definition}",
                                f"### 最小可行版本的范围\n\n{guide.mvp_definition}",
                                response_language,
                            )
                        ]
                    ) if guide and guide.mvp_definition else []),
                    *deps.exercise_lines(exercise_prompt if isinstance(exercise_prompt, dict) else None, response_language),
                ],
                response_language=response_language,
            ),
            metadata={"background_mode": "embedded", "coach_focus": focus_bundle},
        )
    elif scenario == "project_idea":
        project_ideas = snapshot.project_ideas if snapshot and snapshot.project_ideas else []
        top_idea = project_ideas[0] if project_ideas else None
        exercise_prompt = stored_exercise_prompt()
        idea_lines = [
            localized_text(
                f"- [{idea.difficulty}] {idea.title}: {idea.why_now}",
                f"- [{idea.difficulty}] {idea.title}：{idea.why_now}",
                response_language,
            )
            for idea in project_ideas[:3]
            if idea.title
        ]
        bullets = [
            localized_text(
                "Pick one idea that trains a single engineering move.",
                "\u5148\u6311\u4e00\u4e2a\u53ea\u8bad\u7ec3\u4e00\u4e2a\u5de5\u7a0b\u52a8\u4f5c\u7684\u70b9\u3002",
                response_language,
            ),
            top_idea.first_step if top_idea and top_idea.first_step else coaching_state.next_step if coaching_state else "",
            top_idea.why_now if top_idea and top_idea.why_now else "",
            top_idea.acceptance_signals[0] if top_idea and top_idea.acceptance_signals else "",
            localized_text(
                "Keep the scope tight enough to finish in one short loop.",
                "\u8303\u56f4\u8981\u5c0f\u5230\u80fd\u5728\u4e00\u8f6e\u77ed\u5faa\u73af\u91cc\u5b8c\u6210\u3002",
                response_language,
            ),
        ]
        if memory.recent_wins:
            bullets.append(
                localized_text(
                    f"Build on a recent win: {memory.recent_wins[0]}",
                    f"尽量接住最近的进步：{memory.recent_wins[0]}",
                    response_language,
                )
            )
        artifacts["project_idea"] = deps.artifact_payload(
            kind="project_idea",
            title=title,
            summary=(
                top_idea.title
                if top_idea and top_idea.title
                else summary
            ),
            bullets=bullets[:4],
            teaser=top_idea.first_step if top_idea and top_idea.first_step else coaching_state.next_step if coaching_state else "",
            recommended_action="task",
            rationale=localized_text(
                "This extracts a project-shaped training idea from existing code instead of inventing a fake toy task.",
                "\u8fd9\u91cc\u662f\u5728\u73b0\u6709 project \u91cc\u63d0\u70bc\u8bad\u7ec3\u673a\u4f1a\uff0c\u800c\u4e0d\u662f\u865a\u6784\u4e00\u9053\u73a9\u5177\u9898\u3002",
                response_language,
            ),
            focus_area=live_leftover_focus_candidate(
                plan=plan,
                runtime=leftover_runtime,
                existing=leftover_runtime,
                stage_title=active_stage.title if active_stage else "",
                task_title=task.title if task else "",
                candidate=top_idea.source_area if top_idea and top_idea.source_area else "",
                fallback="project-idea",
            ),
            verification=(
                top_idea.acceptance_signals[:2]
                if top_idea and top_idea.acceptance_signals
                else [
                    localized_text(
                        "Keep it small enough to finish in one short coaching loop.",
                        "\u8303\u56f4\u5fc5\u987b\u5c0f\u5230\u80fd\u5728\u4e00\u8f6e\u77ed\u6559\u7ec3\u5faa\u73af\u91cc\u5b8c\u6210\u3002",
                        response_language,
                    )
                ]
            ),
            content=deps.render_artifact_content(
                title=title,
                summary=summary,
                bullets=bullets,
                verification=(
                    top_idea.acceptance_signals[:2]
                    if top_idea and top_idea.acceptance_signals
                    else [
                        localized_text(
                            "Keep it small enough to finish in one short coaching loop.",
                            "\u8303\u56f4\u5fc5\u987b\u5c0f\u5230\u80fd\u5728\u4e00\u8f6e\u77ed\u6559\u7ec3\u5faa\u73af\u91cc\u5b8c\u6210\u3002",
                            response_language,
                        )
                    ]
                ),
                rationale=localized_text(
                    "This extracts a project-shaped training idea from existing code instead of inventing a fake toy task.",
                    "\u8fd9\u91cc\u662f\u5728\u73b0\u6709 project \u91cc\u63d0\u70bc\u8bad\u7ec3\u673a\u4f1a\uff0c\u800c\u4e0d\u662f\u865a\u6784\u4e00\u9053\u73a9\u5177\u9898\u3002",
                    response_language,
                ),
                metadata={"background_mode": "embedded", "coach_focus": focus_bundle},
                extras=[
                    *(
                        [
                            localized_text(
                                "### Candidate drills\n\n" + "\n".join(idea_lines),
                                "### 候选训练题\n\n" + "\n".join(idea_lines),
                                response_language,
                            )
                        ]
                        if idea_lines
                        else []
                    ),
                    *deps.exercise_lines(exercise_prompt if isinstance(exercise_prompt, dict) else None, response_language),
                ],
                response_language=response_language,
            ),
            metadata={"background_mode": "embedded", "coach_focus": focus_bundle},
        )
    elif scenario == "project_adaptation":
        adaptation_guide = (
            snapshot.project_adaptation_guide if snapshot and snapshot.project_adaptation_guide else None
        )
        exercise_prompt = stored_exercise_prompt()
        bullets = [
            localized_text(
                "Current focus: name the boundary that moves first and keep the rest stable.",
                "",
                response_language,
            ),
            adaptation_guide.target_outcome
            if adaptation_guide and adaptation_guide.target_outcome
            else "",
            adaptation_guide.first_migration_step
            if adaptation_guide and adaptation_guide.first_migration_step
            else coaching_state.next_step if coaching_state else "",
            localized_text(
                "Review rhythm: validate one boundary before touching the next one.",
                "",
                response_language,
            ),
        ]
        artifacts["project_adaptation"] = deps.artifact_payload(
            kind="project_adaptation",
            title=title,
            summary=summary,
            bullets=bullets,
            teaser=adaptation_guide.first_migration_step if adaptation_guide and adaptation_guide.first_migration_step else coaching_state.next_step if coaching_state else "",
            recommended_action="plan",
            rationale=localized_text(
                "Adaptation work fails when boundaries blur, so the coach is naming the first safe boundary and the review rhythm before more change.",
                "",
                response_language,
            ),
            focus_area=leftover_focus or "adaptation",
            verification=(
                adaptation_guide.validation_checkpoints[:2]
                if adaptation_guide and adaptation_guide.validation_checkpoints
                else [
                    localized_text(
                        "Validate one boundary before touching the next layer.",
                        "\u6bcf\u6539\u4e00\u5c42\uff0c\u5148\u9a8c\u8bc1\u4e0a\u4e00\u5c42\u7684\u8fb9\u754c\u3002",
                        response_language,
                    )
                ]
            ),
            content=deps.render_artifact_content(
                title=title,
                summary=summary,
                bullets=bullets,
                verification=(
                    adaptation_guide.validation_checkpoints[:2]
                    if adaptation_guide and adaptation_guide.validation_checkpoints
                    else [
                        localized_text(
                            "Validate one boundary before touching the next layer.",
                            "\u6bcf\u6539\u4e00\u5c42\uff0c\u5148\u9a8c\u8bc1\u4e0a\u4e00\u5c42\u7684\u8fb9\u754c\u3002",
                            response_language,
                        )
                    ]
                ),
                rationale=localized_text(
                    "Adaptation work fails when boundaries blur, so the coach is naming the first safe boundary and the review rhythm before more change.",
                    "",
                    response_language,
                ),
                metadata={"background_mode": "embedded", "coach_focus": focus_bundle},
                extras=[
                    *(
                        [
                            localized_text(
                                "### Preserve first\n\n"
                                + "\n".join(
                                    f"- {item}"
                                    for item in adaptation_guide.preserve_areas[:3]
                                    if item
                                ),
                                "### \u5148\u4fdd\u7559\u8fd9\u4e9b\n\n"
                                + "\n".join(
                                    f"- {item}"
                                    for item in adaptation_guide.preserve_areas[:3]
                                    if item
                                ),
                                response_language,
                            )
                        ]
                        if adaptation_guide and adaptation_guide.preserve_areas
                        else []
                    ),
                    localized_text(
                        "### Boundary checklist\n\n| Layer | Change now? | Reason |\n| --- | --- | --- |\n| Stable module | No | Keep the blast radius small |\n| First boundary | Yes | Proves the adaptation path |\n| Downstream layers | Later | Wait until the previous boundary is verified |",
                        "",
                        response_language,
                    ),
                    *deps.exercise_lines(exercise_prompt if isinstance(exercise_prompt, dict) else None, response_language),
                    *(
                        [
                            localized_text(
                                "### Rollback note\n\n"
                                + "\n".join(
                                    f"- {item}"
                                    for item in adaptation_guide.rollback_notes[:2]
                                    if item
                                ),
                                "### \u56de\u9000\u63d0\u793a\n\n"
                                + "\n".join(
                                    f"- {item}"
                                    for item in adaptation_guide.rollback_notes[:2]
                                    if item
                                ),
                                response_language,
                            )
                        ]
                        if adaptation_guide and adaptation_guide.rollback_notes
                        else []
                    ),
                ],
                response_language=response_language,
            ),
            metadata={"background_mode": "embedded", "coach_focus": focus_bundle},
        )
    elif scenario == "project_sourcing":
        project_sources = snapshot.project_sources if snapshot and snapshot.project_sources else []
        top_source = project_sources[0] if project_sources else None
        exercise_prompt = stored_exercise_prompt()
        bullets = [
            localized_text(
                "Current focus: pick an outside project that reinforces one real engineering move.",
                "\u5f53\u524d\u805a\u7126\uff1a\u6311\u4e00\u4e2a\u80fd\u5f3a\u5316\u4e00\u4e2a\u771f\u5b9e\u5de5\u7a0b\u52a8\u4f5c\u7684\u5916\u90e8\u9879\u76ee\u3002",
                response_language,
            ),
            top_source.first_filter if top_source and top_source.first_filter else coaching_state.next_step if coaching_state else "",
            top_source.first_task if top_source and top_source.first_task else "",
            localized_text(
                "Keep the source small enough that setup cost does not swallow the training value.",
                "\u9879\u76ee\u6765\u6e90\u8981\u8db3\u591f\u5c0f\uff0c\u4e0d\u80fd\u8ba9\u73af\u5883\u548c\u642d\u5efa\u6210\u672c\u541e\u6389\u8bad\u7ec3\u4ef7\u503c\u3002",
                response_language,
            ),
        ]
        source_details: list[str] = []
        if top_source and top_source.title:
            source_details.append(
                localized_text(
                    f"### Recommended source\n\n- {top_source.title}",
                    f"### \u63a8\u8350\u6765\u6e90\n\n- {top_source.title}",
                    response_language,
                )
            )
        if top_source and top_source.source_url:
            source_details.append(
                localized_text(
                    f"### Source\n\n- URL: {top_source.source_url}",
                    f"### \u6765\u6e90\n\n- URL: {top_source.source_url}",
                    response_language,
                )
            )
        if top_source and top_source.retrieved_at:
            source_details.append(
                localized_text(
                    f"- Retrieved at: {top_source.retrieved_at}",
                    f"- \u83b7\u53d6\u65f6\u95f4\uff1a{top_source.retrieved_at}",
                    response_language,
                )
            )
        if top_source and top_source.trust_score:
            source_details.append(
                localized_text(
                    f"- Trust score: {top_source.trust_score:.2f}",
                    f"- \u53ef\u4fe1\u5ea6\uff1a{top_source.trust_score:.2f}",
                    response_language,
                )
            )
        artifacts["project_source"] = deps.artifact_payload(
            kind="project_source",
            title=title,
            summary=summary,
            bullets=bullets[:4],
            teaser=top_source.repo_hint if top_source and top_source.repo_hint else coaching_state.next_step if coaching_state else "",
            recommended_action="task",
            rationale=localized_text(
                "When the current repo is not the best training surface, the coach should still keep momentum by recommending a realistic outside project source.",
                "\u5f53\u5f53\u524d\u4ed3\u5e93\u4e0d\u9002\u5408\u4f5c\u4e3a\u8bad\u7ec3\u9762\u65f6\uff0c\u6559\u7ec3\u4e5f\u5e94\u8be5\u7ee7\u7eed\u7ef4\u6301\u63a8\u8fdb\uff0c\u7ed9\u51fa\u4e00\u4e2a\u73b0\u5b9e\u53ef\u7528\u7684\u5916\u90e8\u9879\u76ee\u6765\u6e90\u3002",
                response_language,
            ),
            focus_area=top_source.title if top_source and top_source.title else "project-source",
            verification=[
                top_source.first_filter
                if top_source and top_source.first_filter
                else localized_text(
                    "The source should be small, recent, and easy to verify locally.",
                    "\u8fd9\u4e2a\u6765\u6e90\u5e94\u5f53\u4f53\u91cf\u5c0f\u3001\u7ef4\u62a4\u65b0\uff0c\u5e76\u4e14\u672c\u5730\u5bb9\u6613\u9a8c\u8bc1\u3002",
                    response_language,
                )
            ],
            content=deps.render_artifact_content(
                title=title,
                summary=summary,
                bullets=bullets,
                verification=[
                    top_source.first_filter
                    if top_source and top_source.first_filter
                    else localized_text(
                        "The source should be small, recent, and easy to verify locally.",
                        "\u8fd9\u4e2a\u6765\u6e90\u5e94\u5f53\u4f53\u91cf\u5c0f\u3001\u7ef4\u62a4\u65b0\uff0c\u5e76\u4e14\u672c\u5730\u5bb9\u6613\u9a8c\u8bc1\u3002",
                        response_language,
                    )
                ],
                rationale=localized_text(
                    "This keeps sourcing inside the same coaching lane instead of turning it into a separate research product.",
                    "\u8fd9\u91cc\u628a\u627e\u9879\u76ee\u6765\u6e90\u4ecd\u7136\u538b\u5728\u540c\u4e00\u6761\u6559\u7ec3\u4e3b\u7ebf\u91cc\uff0c\u800c\u4e0d\u662f\u628a\u5b83\u505a\u6210\u72ec\u7acb\u7814\u7a76\u4ea7\u54c1\u3002",
                    response_language,
                ),
                metadata={"background_mode": "embedded", "coach_focus": focus_bundle},
                extras=[
                    *source_details,
                    *deps.exercise_lines(exercise_prompt if isinstance(exercise_prompt, dict) else None, response_language),
                    localized_text(
                        "### What to look for\n\n| Filter | Why |\n| --- | --- |\n| Small codebase | Lowers setup cost |\n| Tests or reproductions | Makes training verifiable |\n| Recent maintenance | Keeps patterns relevant |",
                        "### \u600e\u4e48\u7b5b\n\n| \u7b5b\u9009\u9879 | \u539f\u56e0 |\n| --- | --- |\n| \u4ee3\u7801\u5e93\u8db3\u591f\u5c0f | \u964d\u4f4e\u4e0a\u624b\u6210\u672c |\n| \u6709\u6d4b\u8bd5\u6216\u590d\u73b0\u8def\u5f84 | \u8bad\u7ec3\u66f4\u53ef\u9a8c\u8bc1 |\n| \u6700\u8fd1\u4ecd\u5728\u7ef4\u62a4 | \u6a21\u5f0f\u66f4\u63a5\u8fd1\u5f53\u524d\u5b9e\u8df5 |",
                        response_language,
                    )
                ],
                response_language=response_language,
            ),
            metadata={
                "background_mode": "embedded",
                "coach_focus": focus_bundle,
                "source_url": top_source.source_url if top_source else "",
                "retrieved_at": top_source.retrieved_at if top_source else "",
                "trust_score": top_source.trust_score if top_source else 0.0,
            },
        )
    elif scenario == "principle":
        principle_notes = snapshot.principle_notes if snapshot and snapshot.principle_notes else None
        exercise_prompt = stored_exercise_prompt()
        bullets = [
            localized_text(
                "Current focus: state the rule in plain words before adding detail.",
                "\u5f53\u524d\u805a\u7126\u70b9\uff1a\u5148\u7528\u6700\u76f4\u767d\u7684\u8bdd\u8bf4\u6e05\u89c4\u5219\uff0c\u518d\u8865\u7ec6\u8282\u3002",
                response_language,
            ),
            principle_notes.apply_now if principle_notes and principle_notes.apply_now else coaching_state.next_step if coaching_state else "",
            principle_notes.current_principle if principle_notes and principle_notes.current_principle else "",
            principle_notes.concrete_anchor if principle_notes and principle_notes.concrete_anchor else "",
            localized_text(
                "Review rhythm: tie the rule back to one concrete line or boundary in the code.",
                "",
                response_language,
            ),
        ]
        if memory.weaknesses:
            bullets.append(
                localized_text(
                    f"Watch the old gap: {memory.weaknesses[0]}",
                    f"\u6ce8\u610f\u8fd9\u4e2a\u65e7\u95ee\u9898\uff1a{memory.weaknesses[0]}",
                    response_language,
                )
            )
        artifacts["principle"] = deps.artifact_payload(
            kind="principle",
            title=title,
            summary=summary,
            bullets=bullets[:4],
            teaser=principle_notes.apply_now if principle_notes and principle_notes.apply_now else coaching_state.next_step if coaching_state else "",
            recommended_action="hint",
            rationale=localized_text(
                "This keeps the explanation attached to the current code boundary and the next reviewable move instead of drifting into theory.",
                "",
                response_language,
            ),
            focus_area="principle",
            verification=(
                principle_notes.related_checks[:3]
                if principle_notes and principle_notes.related_checks
                else principle_notes.transfer_targets[:2]
                if principle_notes and principle_notes.transfer_targets
                else [
                    localized_text(
                        "Point at one concrete line, branch, or boundary where the principle matters.",
                        "",
                        response_language,
                    )
                ]
            ),
            content=deps.render_artifact_content(
                title=title,
                summary=summary,
                bullets=bullets,
                verification=(
                    principle_notes.related_checks[:3]
                    if principle_notes and principle_notes.related_checks
                    else principle_notes.transfer_targets[:2]
                    if principle_notes and principle_notes.transfer_targets
                    else [
                        localized_text(
                            "Point at one concrete line, branch, or boundary where the principle matters.",
                            "",
                            response_language,
                        )
                    ]
                ),
                rationale=localized_text(
                    "This keeps the explanation attached to the current code boundary and the next reviewable move instead of drifting into theory.",
                    "",
                    response_language,
                ),
                metadata={"background_mode": "embedded", "coach_focus": focus_bundle},
                extras=[
                    *(
                        [
                            localized_text(
                                f"### Concrete anchor\n\n{principle_notes.concrete_anchor}",
                                f"### \u5177\u4f53\u951a\u70b9\n\n{principle_notes.concrete_anchor}",
                                response_language,
                            )
                        ]
                        if principle_notes and principle_notes.concrete_anchor
                        else []
                    ),
                    *(
                        [
                            localized_text(
                                f"### Common wrong intuition\n\n{principle_notes.common_mistake}",
                                f"### 常见错误直觉\n\n{principle_notes.common_mistake}",
                                response_language,
                            )
                        ]
                        if principle_notes and principle_notes.common_mistake
                        else []
                    ),
                    *(
                        [
                            localized_text(
                                f"### Transfer lesson\n\n{principle_notes.transferable_lesson}",
                                "",
                                response_language,
                            )
                        ]
                        if principle_notes and principle_notes.transferable_lesson
                        else []
                    ),
                    *(
                        [
                            localized_text(
                                f"### Source asset\n\n- {principle_notes.source_asset_title}",
                                f"### 来源教学资产\n\n- {principle_notes.source_asset_title}",
                                response_language,
                            )
                        ]
                        if principle_notes and principle_notes.source_asset_title
                        else []
                    ),
                    *deps.exercise_lines(exercise_prompt if isinstance(exercise_prompt, dict) else None, response_language),
                ],
                response_language=response_language,
            ),
            metadata={"background_mode": "embedded", "coach_focus": focus_bundle},
        )
    elif scenario == "review" and evaluation:
        bullets = [
            localized_text(
                "Current focus: fix the first issue that restores correctness or the feedback loop.",
                "",
                response_language,
            ),
            evaluation.next_step,
            localized_text(
                "Review rhythm: patch, verify, then ask for the next prioritized issue.",
                "",
                response_language,
            ),
        ]
        if memory.review_rhythm:
            bullets.append(
                localized_text(
                    f"Keep the review rhythm alive: {memory.review_rhythm}",
                    f"别断复盘节奏：{memory.review_rhythm}",
                    response_language,
                )
            )
        artifacts["review"] = deps.artifact_payload(
            kind="review",
            title=title,
            summary=evaluation.summary,
            bullets=(bullets + failing_checks[:2])[:4],
            teaser=evaluation.next_step,
            recommended_action="plan" if completed_return else "retry_review" if failing_checks else "review",
            rationale=localized_text(
                "The review loop should keep the learner on the first high-leverage fix, not dump every issue with equal weight.",
                "",
                response_language,
            ),
            focus_area=deps.stateful_focus_area(task, plan, evaluation, snapshot=snapshot),
            verification=[evaluation.next_step],
            content=deps.render_artifact_content(
                title=title,
                summary=evaluation.summary,
                bullets=bullets + failing_checks[:2],
                verification=[evaluation.next_step],
                rationale=localized_text(
                    "The review loop should keep the learner on the first high-leverage fix, not dump every issue with equal weight.",
                    "",
                    response_language,
                ),
                metadata={
                    "failing_checks": failing_checks,
                    "passed": evaluation.passed,
                    "background_mode": "embedded",
                    "coach_focus": focus_bundle,
                },
                extras=[
                    localized_text(
                        "### Review order\n\n```mermaid\nflowchart TD\n    A[Patch first issue] --> B[Run verification]\n    B --> C{Still failing?}\n    C -->|Yes| D[Ask for next issue]\n    C -->|No| E[Widen scope carefully]\n```",
                        "### 评审顺序\n\n```mermaid\nflowchart TD\n    A[先修第一问题] --> B[执行验证]\n    B --> C{还有失败吗}\n    C -->|有| D[继续要下一条问题]\n    C -->|没有| E[再谨慎扩大范围]\n```",
                        response_language,
                    )
                ],
                response_language=response_language,
            ),
            metadata={
                "failing_checks": failing_checks,
                "passed": evaluation.passed,
                "background_mode": "embedded",
                "coach_focus": focus_bundle,
            },
        )
    elif scenario == "plan" and plan:
        bullets = [
            localized_text(
                "Current focus: keep today's work anchored on the active stage.",
                "\u5f53\u524d\u805a\u7126\u70b9\uff1a\u628a\u4eca\u5929\u7684\u52a8\u4f5c\u7a33\u7a33\u951a\u5b9a\u5728\u6d3b\u8dc3\u9636\u6bb5\u4e0a\u3002",
                response_language,
            ),
            deps.live_stage_object_label(plan, snapshot=snapshot, stage=active_stage),
            coaching_state.next_step if coaching_state else "",
            localized_text(
                "Review rhythm: keep the current stage small enough to complete visibly.",
                "",
                response_language,
            ),
        ]
        if memory.teaching_observations:
            bullets.append(
                localized_text(
                    f"Teaching observation to preserve: {memory.teaching_observations[0]}",
                    f"\u8981\u7ee7\u7eed\u4fdd\u6301\u7684\u6559\u5b66\u89c2\u5bdf\uff1a{memory.teaching_observations[0]}",
                    response_language,
                )
            )
        artifacts["plan_update"] = deps.artifact_payload(
            kind="plan_update",
            title=title,
            summary=summary,
            bullets=bullets[:4],
            teaser=coaching_state.next_step
            if coaching_state
            else deps.live_stage_object_label(plan, snapshot=snapshot, stage=active_stage),
            recommended_action="plan",
            rationale=localized_text(
                "This plan update is meant to tighten today's sequence around the active stage and review rhythm, not create a broad dashboard.",
                "",
                response_language,
            ),
            focus_area=deps.stateful_focus_area(task, plan, evaluation, snapshot=snapshot),
            verification=[
                localized_text(
                    "You should be able to name today's first visible move after reading this.",
                    "",
                    response_language,
                )
            ],
            content=deps.render_artifact_content(
                title=title,
                summary=summary,
                bullets=bullets,
                verification=[
                    localized_text(
                        "You should be able to name today's first visible move after reading this.",
                        "",
                        response_language,
                    )
                ],
                rationale=localized_text(
                    "This plan update is meant to tighten today's sequence around the active stage and review rhythm, not create a broad dashboard.",
                    "",
                    response_language,
                ),
                metadata={
                    "active_stage_id": active_stage.id if active_stage else None,
                    "frozen": plan.frozen,
                    "background_mode": "embedded",
                    "coach_focus": focus_bundle,
                },
                extras=[
                    localized_text(
                        "### Stage framing\n\n| Track | Current stage |\n| --- | --- |\n| Coaching lane | " + (deps.live_stage_object_label(plan, snapshot=snapshot, stage=active_stage) or "Current stage") + " |\n| Next visible move | " + ((coaching_state.next_step if coaching_state else "") or "Define the first visible move") + " |",
                        "### \u9636\u6bb5\u6846\u67b6\n\n| \u8f68\u9053 | \u5f53\u524d\u5185\u5bb9 |\n| --- | --- |\n| \u6559\u7ec3\u4e3b\u7ebf | "
                        + (deps.live_stage_object_label(plan, snapshot=snapshot, stage=active_stage) or "\u5f53\u524d\u9636\u6bb5")
                        + " |\n| \u4e0b\u4e00\u4e2a\u53ef\u89c1\u52a8\u4f5c | "
                        + ((coaching_state.next_step if coaching_state else "") or "\u5148\u5b9a\u4e49\u7b2c\u4e00\u4e2a\u53ef\u89c1\u52a8\u4f5c")
                        + " |",
                        response_language,
                    )
                ],
                response_language=response_language,
            ),
            metadata={
                "active_stage_id": active_stage.id if active_stage else None,
                "frozen": plan.frozen,
                "background_mode": "embedded",
                "coach_focus": focus_bundle,
            },
        )
    elif scenario in {"task", "next_task"} and task:
        live_goal = live_task_suggested_title(
            plan=plan,
            task=task,
            runtime=leftover_runtime,
            existing=leftover_runtime,
            title=task.natural_language_goal,
            goal=task.natural_language_goal,
            task_title=task.title,
        )
        bullets = [
            localized_text(
                "Current focus: finish only the first visible slice of this task.",
                "",
                response_language,
            ),
            live_goal,
            *(task.verification_strategy[:1] or []),
            *(task.constraints[:1] or []),
        ]
        if memory.review_rhythm:
            bullets.append(
                localized_text(
                    f"Review rhythm to keep: {memory.review_rhythm}",
                    f"\u9700\u8981\u4fdd\u6301\u7684\u590d\u4e60\u8282\u594f\uff1a{memory.review_rhythm}",
                    response_language,
                )
            )
        artifacts["next_step"] = deps.artifact_payload(
            kind="next_step",
            title=localized_text("Do this now", "\u73b0\u5728\u5148\u505a", response_language),
            summary=summary,
            bullets=bullets[:4],
            teaser=live_goal,
            recommended_action="review",
            rationale=localized_text(
                "The task is only valuable if the learner can attempt it immediately, verify one result, and return for review.",
                "",
                response_language,
            ),
            focus_area=live_task_focus_area(
                plan=plan,
                task=task,
                runtime=leftover_runtime,
                existing=leftover_runtime,
                task_title=task.title,
            ),
            verification=task.verification_strategy[:2],
            content=deps.render_artifact_content(
                title=localized_text("Do this now", "\u73b0\u5728\u5148\u505a", response_language),
                summary=summary,
                bullets=bullets[:3],
                verification=task.verification_strategy[:2],
                rationale=localized_text(
                    "The task is only valuable if the learner can attempt it immediately, verify one result, and return for review.",
                    "",
                    response_language,
                ),
                metadata={"background_mode": "embedded", "coach_focus": focus_bundle},
                extras=[
                    localized_text(
                        "### Start condition\n\nAttempt the task only when the acceptance signal is visible in the current code context.",
                        "",
                        response_language,
                    )
                ],
                response_language=response_language,
            ),
            metadata={"background_mode": "embedded", "coach_focus": focus_bundle},
        )
    elif memory.due_reviews:
        due_review = memory.due_reviews[0]
        artifacts["review"] = deps.artifact_payload(
            kind="review",
            title=localized_text("Review to revisit", "\u5f85\u56de\u770b\u7684\u590d\u4e60\u70b9", response_language),
            summary=due_review.reason,
            bullets=[
                due_review.concept,
                localized_text(
                    "Use a tiny implementation pass to revisit it.",
                    "\u7528\u4e00\u6b21\u5f88\u5c0f\u7684\u5b9e\u73b0\u52a8\u4f5c\u91cd\u65b0\u8fc7\u4e00\u904d\u3002",
                    response_language,
                ),
            ],
            teaser=due_review.concept,
            recommended_action="next_task",
            rationale=localized_text(
                "Background review should surface through the current turn, not as a separate research mode.",
                "",
                response_language,
            ),
            focus_area=due_review.concept,
            verification=[due_review.reason],
            content=deps.render_artifact_content(
                title=localized_text("Review to revisit", "\u5f85\u56de\u770b\u7684\u590d\u4e60\u70b9", response_language),
                summary=due_review.reason,
                bullets=[
                    due_review.concept,
                    localized_text(
                        "Use a tiny implementation pass to revisit it.",
                        "\u7528\u4e00\u6b21\u5f88\u5c0f\u7684\u5b9e\u73b0\u52a8\u4f5c\u91cd\u65b0\u8fc7\u4e00\u904d\u3002",
                        response_language,
                    ),
                ],
                verification=[due_review.reason],
                rationale=localized_text(
                    "Background review should surface through the current turn, not as a separate research mode.",
                    "",
                    response_language,
                ),
                metadata={
                    "due_at": due_review.due_at,
                    "background_mode": "embedded",
                    "coach_focus": focus_bundle,
                },
                extras=[
                    localized_text(
                        "### Review note\n\nA review item should re-enter the loop as a tiny patch, not a giant recap.",
                        "",
                        response_language,
                    )
                ],
                response_language=response_language,
            ),
            metadata={
                "due_at": due_review.due_at,
                "background_mode": "embedded",
                "coach_focus": focus_bundle,
            },
        )

    return artifacts


def derive_coaching_state(deps: CoachSupportDeps,
    *,
    snapshot: WorkbenchSnapshot,
    response_language: str | None,
    answer_mode: str | None,
    scenario: str | None = None,
    learner_signal: str | None = None,
    message: str | None = None,
    current_file=None,
    grounding_context: dict[str, object] | None = None,
    active_view: str | None = None,
) -> CoachingState:
    memory = snapshot.memory
    plan = snapshot.plan
    task = snapshot.current_task
    evaluation = snapshot.evaluation
    active_stage = None
    if plan:
        active_stage = next(
            (stage for stage in plan.stages if stage.id == plan.current_stage_id or stage.status == "active"),
            plan.stages[0] if plan.stages else None,
        )

    raw_seed_scenario = scenario or (
        snapshot.memory.active_thread.scenario
        if snapshot.memory.active_thread is not None
        else "general"
    )
    # Active threads may persist pedagogy modes such as "review_reflection"
    # (a TeachingMode, not a CoachScenario); normalize before validation so a
    # restored thread can never crash CoachingState construction.
    if raw_seed_scenario == "review_reflection":
        raw_seed_scenario = "review"
    if raw_seed_scenario not in get_args(CoachScenario):
        raw_seed_scenario = "general"

    coaching_state_seed = CoachingState.model_validate(
        {
            "scenario": raw_seed_scenario,
            "answer_mode": deps.normalize_answer_mode(
                answer_mode or snapshot.profile.answer_policy if snapshot.profile else None
            ),
            "learner_signal": (
                "blocked"
                if learner_signal != "blocked"
                and infer_message_learner_signal(message or "", current_file) == "blocked"
                else learner_signal or "steady"
            ),
        }
    )
    resolved_scenario = coaching_state_seed.scenario
    resolved_mode = coaching_state_seed.answer_mode
    resolved_signal = coaching_state_seed.learner_signal
    active_thread = snapshot.memory.active_thread
    preserve_active_thread = deps.should_preserve_active_thread_for_turn(
        resolved_scenario,
        active_thread,
        message=message,
        grounding_context=grounding_context,
        active_view=active_view,
    )
    view_owned_lane = deps.active_view_owns_turn_lane(active_view)
    resource_grounded_turn = deps.resource_grounding_turn_prefers_fresh_lane(
        message,
        grounding_context,
    )
    active_thread_focus = active_thread.focus_area.strip() if active_thread else ""
    active_thread_summary = active_thread.summary.strip() if active_thread else ""
    active_thread_next_step = active_thread.next_step.strip() if active_thread else ""
    active_thread_blocker = active_thread.blocker.strip() if active_thread else ""
    active_thread_verified = active_thread.verified_result.strip() if active_thread else ""
    workspace = memory.workspace if isinstance(memory.workspace, dict) else {}
    current_file_name = deps.function_guidance_current_file_name(
        current_file,
        scenario=resolved_scenario,
    )
    persist_chrome = live_plan_update_persist_chrome(
        plan=plan,
        runtime=coach_focus_runtime_from_snapshot(snapshot),
        existing=coach_focus_runtime_from_snapshot(snapshot),
        stage_title=active_stage.title if active_stage else "",
        task_title=task.title if task else "",
        stage_goal=active_stage.goal if active_stage else "",
    )
    turn_focus_hint = deps.resolve_turn_focus_hint(
        user_message=message,
        current_file_name=current_file_name or None,
        task_focus=persist_chrome["task_focus"] or None,
        stage_focus=persist_chrome["stage_focus"] or None,
    )

    def _workspace_text(*keys: str) -> str:
        for key in keys:
            value = str(workspace.get(key) or "").strip()
            if value:
                return value
        return ""

    def _workspace_evidence(*keys: str) -> list[str]:
        for key in keys:
            raw = workspace.get(key)
            if isinstance(raw, list):
                evidence = [str(item).strip() for item in raw if str(item).strip()]
                if evidence:
                    return evidence[:4]
            elif isinstance(raw, str):
                normalized = raw.strip()
                if normalized:
                    return [normalized]
        return []

    active_thread_decision = active_thread.decision.strip() if active_thread and preserve_active_thread else ""
    active_thread_teaching_note = (
        active_thread.teaching_note.strip() if active_thread and preserve_active_thread else ""
    )
    active_thread_confidence = active_thread.confidence.strip() if active_thread and preserve_active_thread else ""
    active_thread_evidence = (
        [str(item).strip() for item in active_thread.evidence if str(item).strip()]
        if active_thread and preserve_active_thread
        else []
    )
    if not preserve_active_thread:
        active_thread_focus = ""
        active_thread_summary = ""
        active_thread_next_step = ""
        active_thread_blocker = ""
        active_thread_verified = ""
    if preserve_active_thread and not active_thread_decision:
        active_thread_decision = _workspace_text("latest_coach_decision", "latest_turn_decision")
    if preserve_active_thread and not active_thread_blocker:
        active_thread_blocker = _workspace_text("latest_turn_blocker", "latest_coach_review_note")
    if preserve_active_thread and not active_thread_teaching_note:
        active_thread_teaching_note = _workspace_text("latest_coach_teaching_note", "latest_turn_teaching_note")
    if preserve_active_thread and not active_thread_confidence:
        active_thread_confidence = _workspace_text("latest_coach_confidence", "latest_turn_confidence")
    if preserve_active_thread and not active_thread_evidence:
        active_thread_evidence = _workspace_evidence("latest_coach_evidence", "latest_turn_evidence")

    if resolved_scenario == "review" and evaluation:
        summary = localized_text(
            f"Top fix first: {evaluation.next_step}",
            f"\u5148\u4fee\u6700\u5173\u952e\u7684\u4e00\u6b65\uff1a{evaluation.next_step}",
            response_language,
        )
        next_step = evaluation.next_step
    elif resolved_scenario == "review":
        summary = localized_text(
            "Current focus: name the failing path from current evidence before generating a plan or task.",
            "当前聚焦点：先从当前证据里点出失败路径，不要生成计划或任务。",
            response_language,
        )
        next_step = localized_text(
            "Point at the failing check, error, or code boundary you can see right now.",
            "先指出你现在能看到的失败检查、报错或代码边界。",
            response_language,
        )
    elif resolved_scenario == "onboarding":
        summary = localized_text(
            "First build the coaching relationship: understand the goal, current level, project context, and the best lane to start with.",
            "\u5148\u5efa\u7acb\u6559\u7ec3\u5173\u7cfb\uff1a\u7406\u89e3\u4f60\u7684\u76ee\u6807\u3001\u5f53\u524d\u6c34\u5e73\u3001project \u8bed\u5883\uff0c\u4ee5\u53ca\u6700\u9002\u5408\u5f00\u59cb\u7684\u90a3\u6761\u4e3b\u7ebf\u3002",
            response_language,
        )
        next_step = localized_text(
            "Clarify the first coaching lane, the current blocker, and the rhythm that will make the next few turns easy to follow.",
            "\u5148\u660e\u786e\u7b2c\u4e00\u6761\u6559\u7ec3\u4e3b\u7ebf\u3001\u5f53\u524d\u5361\u70b9\uff0c\u4ee5\u53ca\u80fd\u8ba9\u63a5\u4e0b\u6765\u51e0\u8f6e\u66f4\u597d\u8ddf\u4e0a\u7684\u8bad\u7ec3\u8282\u594f\u3002",
            response_language,
        )
    elif resolved_scenario == "plan" and active_stage:
        live_stage_label = (
            persist_chrome["stage_focus"]
            or active_stage.title
            or active_stage.goal
        )
        summary = localized_text(
            f"Stay inside the current stage: {live_stage_label}",
            f"\u5148\u7a33\u4f4f\u5f53\u524d\u9636\u6bb5\uff1a{live_stage_label}",
            response_language,
        )
        next_step = (
            live_task_suggested_title(
                plan=plan,
                task=task,
                runtime=coach_focus_runtime_from_snapshot(snapshot),
                existing=coach_focus_runtime_from_snapshot(snapshot),
                title=task.natural_language_goal,
                goal=task.natural_language_goal,
                task_title=task.title,
            )
            if task
            else persist_chrome["next_step"]
        )
    elif resolved_scenario in {"task", "next_task"} and task:
        leftover_runtime = coach_focus_runtime_from_snapshot(snapshot)
        thin_slice = live_task_thin_slice_copy(
            plan=plan,
            task=task,
            runtime=leftover_runtime,
            existing=leftover_runtime,
            task_title=task.title,
        )
        summary = localized_text(thin_slice["en"], thin_slice["zh"], response_language)
        next_step = live_task_suggested_title(
            plan=plan,
            task=task,
            runtime=leftover_runtime,
            existing=leftover_runtime,
            title=task.natural_language_goal,
            goal=task.natural_language_goal,
            task_title=task.title,
        )
    elif resolved_scenario == "idea_implementation":
        summary = localized_text(
            (
                f"Current focus: keep the work inside {current_file_name} and land one tiny, verifiable code move."
                if current_file_name
                else "Current focus: keep the work inside the current file and land one tiny, verifiable code move."
            ),
            (
                f"\u5f53\u524d\u7126\u70b9\uff1a\u5148\u628a\u5de5\u4f5c\u6536\u5728 {current_file_name} \u91cc\uff0c\u843d\u4e0b\u4e00\u6761\u5f88\u8584\u3001\u53ef\u9a8c\u8bc1\u7684 code \u52a8\u4f5c\u3002"
                if current_file_name
                else "\u5f53\u524d\u7126\u70b9\uff1a\u5148\u628a\u5de5\u4f5c\u6536\u5728\u5f53\u524d\u6587\u4ef6\u91cc\uff0c\u843d\u4e0b\u4e00\u6761\u5f88\u8584\u3001\u53ef\u9a8c\u8bc1\u7684 code \u52a8\u4f5c\u3002"
            ),
            response_language,
        )
        next_step = localized_text(
            (
                f"Change one tiny spot in {current_file_name}, run one quick check, and use the result to decide the next move."
                if current_file_name
                else "Change one tiny spot in the current file, run one quick check, and use the result to decide the next move."
            ),
            (
                f"\u5148\u5728 {current_file_name} \u91cc\u6539\u4e00\u4e2a\u5c0f\u70b9\uff0c\u8dd1\u4e00\u6b21\u5f88\u5feb\u7684\u9a8c\u8bc1\uff0c\u518d\u7528\u7ed3\u679c\u51b3\u5b9a\u4e0b\u4e00\u6b65\u3002"
                if current_file_name
                else "\u5148\u5728\u5f53\u524d\u6587\u4ef6\u91cc\u6539\u4e00\u4e2a\u5c0f\u70b9\uff0c\u8dd1\u4e00\u6b21\u5f88\u5feb\u7684\u9a8c\u8bc1\uff0c\u518d\u7528\u7ed3\u679c\u51b3\u5b9a\u4e0b\u4e00\u6b65\u3002"
            ),
            response_language,
        )
        if prefers_chinese(response_language):
            summary = (
                f"\u5f53\u524d\u7126\u70b9\uff1a\u5148\u628a\u5de5\u4f5c\u6536\u5728 {current_file_name} \u91cc\uff0c\u843d\u4e0b\u4e00\u6761\u5f88\u8584\u3001\u53ef\u9a8c\u8bc1\u7684 code \u52a8\u4f5c\u3002"
                if current_file_name
                else "\u5f53\u524d\u7126\u70b9\uff1a\u5148\u628a\u5de5\u4f5c\u6536\u5728\u5f53\u524d\u6587\u4ef6\u91cc\uff0c\u843d\u4e0b\u4e00\u6761\u5f88\u8584\u3001\u53ef\u9a8c\u8bc1\u7684 code \u52a8\u4f5c\u3002"
            )
            next_step = (
                f"\u5148\u5728 {current_file_name} \u91cc\u6539\u4e00\u4e2a\u5c0f\u70b9\uff0c\u8dd1\u4e00\u6b21\u5f88\u5feb\u7684\u9a8c\u8bc1\uff0c\u518d\u7528\u7ed3\u679c\u51b3\u5b9a\u4e0b\u4e00\u6b65\u3002"
                if current_file_name
                else "\u5148\u5728\u5f53\u524d\u6587\u4ef6\u91cc\u6539\u4e00\u4e2a\u5c0f\u70b9\uff0c\u8dd1\u4e00\u6b21\u5f88\u5feb\u7684\u9a8c\u8bc1\uff0c\u518d\u7528\u7ed3\u679c\u51b3\u5b9a\u4e0b\u4e00\u6b65\u3002"
            )
    elif resolved_scenario == "principle":
        if resource_grounded_turn:
            summary = localized_text(
                "Current focus: answer the grounded library question directly before widening into adjacent coaching.",
                "\u5f53\u524d\u805a\u7126\u70b9\uff1a\u5148\u76f4\u63a5\u56de\u7b54\u8fd9\u4e2a\u5df2\u7ecf grounded \u7684\u8d44\u6599\u95ee\u9898\uff0c\u518d\u51b3\u5b9a\u8981\u4e0d\u8981\u5f80\u76f8\u90bb\u6559\u5b66\u6269\u5c55\u3002",
                response_language,
            )
            next_step = localized_text(
                "State the requested rule in plain language, name the source boundary it comes from, then turn it into one visible verification check.",
                "\u5148\u7528\u76f4\u767d\u7684\u8bdd\u8bf4\u51fa\u7528\u6237\u95ee\u7684\u89c4\u5219\uff0c\u518d\u8bf4\u6e05\u5b83\u6765\u81ea\u54ea\u6761\u8d44\u6599\u8fb9\u754c\uff0c\u6700\u540e\u628a\u5b83\u538b\u6210\u4e00\u6761\u53ef\u89c1\u7684\u9a8c\u8bc1\u68c0\u67e5\u3002",
                response_language,
            )
        else:
            summary = localized_text(
                "Current focus: explain the mechanism behind the current code before widening the patch.",
                "\u5f53\u524d\u805a\u7126\u70b9\uff1a\u5148\u8bb2\u6e05\u5f53\u524d code \u80cc\u540e\u7684\u673a\u5236\uff0c\u518d\u6269\u5927 patch \u8303\u56f4\u3002",
                response_language,
            )
            next_step = localized_text(
                "Name the rule, then point at the exact line where it matters, then verify it in code review.",
                "\u5148\u8bf4\u6e05\u89c4\u5219\uff0c\u518d\u6307\u51fa\u5b83\u5728\u54ea\u4e00\u884c\u771f\u6b63\u751f\u6548\uff0c\u7136\u540e\u5728 code review \u91cc\u9a8c\u8bc1\u5b83\u3002",
                response_language,
            )
    elif resolved_scenario == "remote_workspace":
        summary = localized_text(
            "Current focus: establish the VS Code remote workspace boundary before widening the lesson.",
            "\u5f53\u524d\u7126\u70b9\uff1a\u5148\u5efa\u7acb VS Code remote workspace \u7684\u8fb9\u754c\uff0c\u518d\u6269\u5927\u8fd9\u8f6e\u6559\u5b66\u8303\u56f4\u3002",
            response_language,
        )
        next_step = localized_text(
            "Return one real boundary signal from the current VS Code window, such as an Explorer path, `pwd`, or the remote host label.",
            "\u5728\u4f60\u5f53\u524d\u7684 VS Code \u7a97\u53e3\u91cc\uff0c\u5e26\u56de\u4e00\u4e2a\u80fd\u8bc1\u660e\u5de5\u4f5c\u533a\u843d\u70b9\u7684\u771f\u5b9e\u4fe1\u53f7\uff0c\u6bd4\u5982 Explorer \u91cc\u7684\u8def\u5f84\u3001\u7ec8\u7aef\u91cc\u7684 `pwd`\uff0c\u6216\u8005\u5de6\u4e0b\u89d2\u7684 remote host \u6807\u7b7e\u3002",
            response_language,
        )
    elif resolved_scenario == "debug_loop":
        summary = localized_text(
            "Current focus: build one trustworthy VS Code debug loop before widening the investigation.",
            "\u5f53\u524d\u7126\u70b9\uff1a\u5148\u5efa\u7acb\u4e00\u6761\u53ef\u4fe1\u7684 VS Code \u8c03\u8bd5\u95ed\u73af\uff0c\u518d\u6269\u5927\u6392\u67e5\u8303\u56f4\u3002",
            response_language,
        )
        next_step = localized_text(
            "Choose one breakpoint or launch.json move, then tell me where you will pause and what single value or branch you expect to inspect there.",
            "\u5148\u9009\u4e00\u4e2a breakpoint \u6216 launch.json \u52a8\u4f5c\uff0c\u518d\u544a\u8bc9\u6211\u4f60\u51c6\u5907\u505c\u5728\u54ea\u513f\uff0c\u4ee5\u53ca\u4f60\u8981\u6838\u5bf9\u7684\u90a3\u4e2a\u503c\u6216\u5206\u652f\u662f\u4ec0\u4e48\u3002",
            response_language,
        )
    elif resolved_scenario == "function_guidance":
        summary = localized_text(
            "Current focus: anchor function guidance to one live call site before widening the explanation.",
            "\u5f53\u524d\u7126\u70b9\uff1a\u5148\u628a function guidance \u951a\u5b9a\u5230\u4e00\u4e2a\u771f\u5b9e call site\uff0c\u518d\u6269\u5c55\u8bf4\u660e\u3002",
            response_language,
        )
        if current_file_name:
            next_step = localized_text(
                f"Go back to {current_file_name}, name the selected function's parameter contract and return contract, then verify that reading against the nearest call site you can see.",
                f"\u56de\u5230 {current_file_name}\uff0c\u5148\u8bf4\u6e05\u5f53\u524d\u9009\u4e2d\u51fd\u6570\u7684\u53c2\u6570 contract \u548c return contract\uff1b\u5982\u679c\u65c1\u8fb9\u5c31\u6709\u6700\u8fd1\u7684 call site\uff0c\u518d\u7528\u5b83\u9a8c\u8bc1\u4f60\u521a\u624d\u7684\u5224\u65ad\u3002",
                response_language,
            )
        else:
            next_step = localized_text(
                "Return the function name, what it expects, and which call site proves that reading.",
                "\u5e26\u56de\u51fd\u6570\u540d\u3001\u5b83\u671f\u671b\u4ec0\u4e48\uff0c\u4ee5\u53ca\u54ea\u4e2a call site \u8bc1\u660e\u4e86\u8fd9\u4e2a contract\u3002",
                response_language,
            )
    elif resolved_scenario == "project_adaptation":
        summary = localized_text(
            "Current focus: keep stable modules stable and move one boundary at a time.",
            "\u5f53\u524d\u805a\u7126\u70b9\uff1a\u7a33\u4f4f\u4e0d\u8be5\u52a8\u7684\u6a21\u5757\uff0c\u4e00\u6b21\u53ea\u6539\u4e00\u5c42\u8fb9\u754c\u3002",
            response_language,
        )
        next_step = localized_text(
            "Choose the first affected layer, land the smallest safe patch, and verify it before touching the next one.",
            "\u5148\u6311\u7b2c\u4e00\u5c42\u53d7\u5f71\u54cd\u7684\u8fb9\u754c\uff0c\u843d\u4e0b\u6700\u5c0f\u5b89\u5168 patch\uff0c\u9a8c\u8bc1\u5b8c\u518d\u52a8\u4e0b\u4e00\u5c42\u3002",
            response_language,
        )
    elif resolved_scenario == "project_sourcing":
        summary = localized_text(
            "Current focus: recommend one outside project source that keeps training realistic and easy to start.",
            "\u5f53\u524d\u805a\u7126\u70b9\uff1a\u63a8\u8350\u4e00\u4e2a\u65e2\u771f\u5b9e\u53c8\u5bb9\u6613\u4e0a\u624b\u7684\u5916\u90e8 project \u6765\u6e90\u3002",
            response_language,
        )
        next_step = localized_text(
            "Choose one small maintained source, reject setup-heavy options, then turn it into the first training task.",
            "\u5148\u9009\u4e00\u4e2a\u5c0f\u800c\u6301\u7eed\u7ef4\u62a4\u7684\u6765\u6e90\uff0c\u6392\u9664\u642d\u5efa\u6210\u672c\u8fc7\u9ad8\u7684\u9009\u9879\uff0c\u518d\u628a\u5b83\u538b\u6210\u7b2c\u4e00\u9053\u8bad\u7ec3\u9898\u3002",
            response_language,
        )
    elif resolved_scenario == "project_idea":
        summary = localized_text(
            "Pull one training opportunity from the current project and keep the scope tight.",
            "\u4ece\u5f53\u524d project \u91cc\u63d0\u70bc\u4e00\u4e2a\u8bad\u7ec3\u673a\u4f1a\uff0c\u5e76\u628a\u8303\u56f4\u538b\u7d27\u3002",
            response_language,
        )
        next_step = localized_text(
            "Pick the smallest idea that teaches one real engineering move.",
            "\u5148\u9009\u4e00\u4e2a\u53ea\u8bad\u7ec3\u4e00\u4e2a\u5173\u952e\u5de5\u7a0b\u52a8\u4f5c\u7684\u5c0f\u60f3\u6cd5\u3002",
            response_language,
        )
    else:
        summary = (
            localized_text(
                f"Current focus: {turn_focus_hint}",
                f"\u5f53\u524d\u805a\u7126\u70b9\uff1a{turn_focus_hint}",
                response_language,
            )
            if turn_focus_hint and not preserve_active_thread
            else memory.current_focus or localized_text(
                "Keep the next step concrete and verifiable.",
                "\u628a\u4e0b\u4e00\u6b65\u538b\u6210\u5177\u4f53\u4e14\u53ef\u9a8c\u8bc1\u7684\u52a8\u4f5c\u3002",
                response_language,
            )
        )
        leftover_runtime = coach_focus_runtime_from_snapshot(snapshot)
        live_goal = live_coaching_next_step(
            plan=plan,
            task=task,
            runtime=leftover_runtime,
            existing=leftover_runtime,
            next_step=task.natural_language_goal if task else "",
            goal=task.natural_language_goal if task else "",
            task_title=task.title if task else "",
        )
        next_step = (
            localized_text(
                f"On '{turn_focus_hint}': one small step, then report back.",
                f"围绕「{turn_focus_hint}」先做一个小动作，把结果带回来。",
                response_language,
            )
            if turn_focus_hint and not preserve_active_thread
            else live_goal
            or (evaluation.next_step if evaluation else memory.review_rhythm or localized_text(
                "Implement the smallest slice you can check quickly.",
                "\u5148\u5b9e\u73b0\u4f60\u80fd\u5feb\u901f\u9a8c\u8bc1\u7684\u6700\u5c0f\u5207\u7247\u3002",
                response_language,
            ))
        )

    if view_owned_lane:
        lane_override = deps.active_view_coaching_lane_override(
            active_view=active_view,
            snapshot=snapshot,
            response_language=response_language,
        )
        if lane_override is not None:
            summary, next_step = lane_override

    if active_thread_focus and resolved_scenario == "general":
        summary = localized_text(
            f"Stay on the live thread '{active_thread_focus}' before opening a new lane.",
            f"\u5148\u6cbf\u7740\u5f53\u524d\u4e3b\u7ebf\u300c{active_thread_focus}\u300d\u7ee7\u7eed\uff0c\u4e0d\u8981\u65b0\u5f00\u5206\u652f\u3002",
            response_language,
        )
    elif active_thread_summary and resolved_scenario == "general":
        summary = active_thread_summary

    if active_thread_next_step:
        next_step = active_thread_next_step

    encouragement = {
        "blocked": localized_text(
            "Reduce scope and land one tiny win before expanding again.",
            "先缩小范围，拿下一个很小的确定性进展再继续。",
            response_language,
        ),
        "uncertain": localized_text(
            "Use the next step to turn ambiguity into one observable result.",
            "用下一步把模糊感压成一个可观察的结果。",
            response_language,
        ),
        "curious": localized_text(
            "Keep the exploration grounded in one concrete code path.",
            "让探索落在一条具体代码路径上，不要散开。",
            response_language,
        ),
        "steady": localized_text(
            "Keep the loop tight: implement, verify, reflect.",
            "把循环保持紧凑：实现、验证、复盘。",
            response_language,
        ),
    }[resolved_signal]
    intervention_strategy = localized_text(
        "First compress the problem into one visible, verifiable move before expanding explanation or scope.",
        "先把问题压成一个可见、可验证的小动作，再决定是否扩大解释和范围。",
        response_language,
    )
    teaching_goal = localized_text(
        "Train implementation judgment inside the current project instead of only giving an answer.",
        "在当前项目里训练实现判断，而不是只给结果。",
        response_language,
    )
    if resolved_scenario == "onboarding":
        teaching_goal = localized_text(
            "Establish trust, understand the learner's real situation, and choose the right coaching lane before pushing execution.",
            "先建立信任、理解学习者的真实处境，再决定对的教练主线，而不是急着推进执行。",
            response_language,
        )
    if active_thread_focus or active_thread_next_step:
        resume_parts = [
            localized_text(
                f"Resume the live thread '{active_thread_focus}'.",
                f"\u4e0b\u4e00\u8f6e\u7ee7\u7eed\u6cbf\u7740\u5f53\u524d\u4e3b\u7ebf\u300c{active_thread_focus}\u300d\u63a5\u4e0a\u3002",
                response_language,
            )
            if active_thread_focus
            else "",
            localized_text(
                f"Do this next before widening scope: {active_thread_next_step}",
                f"\u5148\u5b8c\u6210\u8fd9\u4e00\u6b65\uff0c\u518d\u51b3\u5b9a\u662f\u5426\u6269\u5c55\uff1a{active_thread_next_step}",
                response_language,
            )
            if active_thread_next_step
            else "",
            localized_text(
                f"Current blocker to respect: {active_thread_blocker}",
                f"\u5f53\u524d\u8981\u907f\u5f00\u7684\u5361\u70b9\uff1a{active_thread_blocker}",
                response_language,
            )
            if active_thread_blocker
            else "",
            localized_text(
                f"Last verified result to build on: {active_thread_verified}",
                f"\u4e0a\u4e00\u6b21\u5df2\u9a8c\u8bc1\u7684\u7ed3\u679c\uff0c\u53ef\u4ee5\u63a5\u7740\u5f80\u4e0a\u505a\uff1a{active_thread_verified}",
                response_language,
            )
            if active_thread_verified
            else "",
        ]
        resume_thread = " ".join(part for part in resume_parts if part).strip()
    else:
        resume_thread = localized_text(
            "Resume from the current coaching lane, verify this slice, then decide whether to widen.",
            "下一轮继续沿着当前训练主线接上，先验证这一小步，再决定是否扩展。",
            response_language,
        )
    support_strategy = localized_text(
        "If the learner feels blocked, reduce scope and keep the next move extremely concrete.",
        "如果用户开始卡住，就继续缩小范围，把下一步压得更具体。",
        response_language,
    )

    if resolved_scenario == "principle":
        teaching_goal = localized_text(
            "Reconnect the current code decision back to a transferable principle.",
            "把当前代码判断重新连回一个可迁移的原理。",
            response_language,
        )
    elif resolved_scenario == "project_idea":
        teaching_goal = localized_text(
            "Mine one worthwhile practice opportunity from the current project and keep it thin.",
            "从当前项目里提炼一个值得练的方向，并把范围收薄。",
            response_language,
        )
    elif resolved_scenario == "project_adaptation":
        teaching_goal = localized_text(
            "Reshape the existing project toward the new intention without losing boundary control.",
            "",
            response_language,
        )
    elif resolved_scenario == "project_sourcing":
        teaching_goal = localized_text(
            "Recommend an outside project source without breaking the same coach-first training lane.",
            "",
            response_language,
        )
    elif resolved_scenario == "review":
        teaching_goal = localized_text(
            "Use review to sharpen prioritization and boundary judgment, not just to list issues.",
            "",
            response_language,
        )

    return CoachingState(
        scenario=resolved_scenario,
        answer_mode=resolved_mode,
        learner_signal=resolved_signal,
        summary=summary,
        next_step=next_step,
        encouragement=encouragement,
        intervention_strategy=intervention_strategy,
        teaching_goal=teaching_goal,
        resume_thread=resume_thread,
        decision=active_thread_decision,
        blocker=active_thread_blocker,
        teaching_note=active_thread_teaching_note,
        confidence=active_thread_confidence,
        evidence=active_thread_evidence,
        support_strategy=support_strategy,
    )


def _scrub_bogus_smalltalk_steps(snapshot: WorkbenchSnapshot) -> None:
    """Clear legacy pre-1.5 smalltalk rescue steps that wrapped casual greetings."""
    from ...pedagogy.smalltalk import is_bogus_smalltalk_step

    if snapshot.coaching_state is not None and is_bogus_smalltalk_step(snapshot.coaching_state.next_step):
        snapshot.coaching_state = snapshot.coaching_state.model_copy(update={"next_step": ""})
    if snapshot.evaluation is not None and is_bogus_smalltalk_step(snapshot.evaluation.next_step):
        snapshot.evaluation = snapshot.evaluation.model_copy(update={"next_step": ""})
    if snapshot.implementation_guide is not None and is_bogus_smalltalk_step(
        snapshot.implementation_guide.current_step
    ):
        snapshot.implementation_guide = snapshot.implementation_guide.model_copy(
            update={"current_step": ""}
        )
    if snapshot.plan is not None and is_bogus_smalltalk_step(snapshot.plan.current_step):
        snapshot.plan = snapshot.plan.model_copy(update={"current_step": None})
    if snapshot.current_task is not None:
        task_updates: dict[str, object] = {}
        if is_bogus_smalltalk_step(snapshot.current_task.title):
            task_updates["title"] = ""
        if is_bogus_smalltalk_step(snapshot.current_task.natural_language_goal):
            task_updates["natural_language_goal"] = ""
        if task_updates:
            snapshot.current_task = snapshot.current_task.model_copy(update=task_updates)
    if snapshot.memory is not None and snapshot.memory.active_thread is not None:
        active_thread = snapshot.memory.active_thread
        if is_bogus_smalltalk_step(active_thread.next_step):
            snapshot.memory = snapshot.memory.model_copy(
                update={"active_thread": active_thread.model_copy(update={"next_step": ""})}
            )
    if isinstance(snapshot.plan_runtime_status, dict):
        cleaned_status = dict(snapshot.plan_runtime_status)
        for key in ("current_step", "currentStep", "next_training_action", "nextTrainingAction"):
            if key in cleaned_status and is_bogus_smalltalk_step(str(cleaned_status.get(key) or "")):
                cleaned_status[key] = ""
        snapshot.plan_runtime_status = cleaned_status
    if snapshot.memory is not None and isinstance(snapshot.memory.workspace, dict):
        workspace_copy = dict(snapshot.memory.workspace)
        for container_key in (
            "latest_plan_runtime",
            "latestPlanRuntime",
            "latest_coach_turn",
            "latestCoachTurn",
            "latest_training_next_hop",
            "latestTrainingNextHop",
            "latest_next_step_hint",
            "latestNextStepHint",
            "current_thread",
            "currentThread",
        ):
            sub = workspace_copy.get(container_key)
            if isinstance(sub, dict):
                sub_copy = dict(sub)
                changed = False
                for field_key in (
                    "current_step",
                    "currentStep",
                    "next_step",
                    "nextStep",
                    "title",
                    "card_title",
                    "cardTitle",
                ):
                    if field_key in sub_copy and is_bogus_smalltalk_step(str(sub_copy.get(field_key) or "")):
                        sub_copy[field_key] = ""
                        changed = True
                if changed:
                    workspace_copy[container_key] = sub_copy
        snapshot.memory = snapshot.memory.model_copy(update={"workspace": workspace_copy})
