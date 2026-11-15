"""A source-rooted task whose rubric never contains a worked solution."""

from ..core.models import CardGenerationRequest, TrainingCardCandidateSnapshot


def is_independent_resource_practice(request: CardGenerationRequest) -> bool:
    return (
        request.source == "resource_knowledge"
        and request.card_type == "practice"
        and bool(request.resource_content_hash)
    )


def is_independent_resource_card(card: TrainingCardCandidateSnapshot | None) -> bool:
    return bool(
        card and card.resource_anchor and card.card_type == "practice"
        and card.source_chain[:2] == ["card_generation_router", "resource_knowledge"]
    )


def build_independent_resource_practice(request: CardGenerationRequest) -> TrainingCardCandidateSnapshot:
    if request.resource_anchor is None:
        raise ValueError("Resource practice requires a verified source version.")
    zh = request.response_language == "zh-CN"
    title = "基于资料的独立练习" if zh else "Independent practice from this source"
    problem = (
        "从关联资料选一个原理，用自己的实现展示它在正常输入和一个边界情况下的行为。"
        if zh else "Choose one principle from the linked source. Implement it yourself and demonstrate its behavior for a normal input and an edge case."
    )
    checks = [
        "能从资料定位所选原理，并解释它影响的行为。" if zh else "Identify where the source states the principle and explain which behavior it affects.",
        "独立完成实现，在运行前写下正常和边界两种输入的预期结果。" if zh else "Complete the implementation independently and predict both outcomes before running it.",
        "使用项目已有的测试或运行入口，记录实际结果及与预期的差异。" if zh else "Use an existing project test or entry point and record actual outcomes and any differences from your predictions.",
    ]
    deliverable = "已保存的实现文件和两种输入的验证记录。" if zh else "A saved implementation file and the verification record for both inputs."
    verification = "使用项目现有的验证入口检查当前文件。" if zh else "Verify the saved file with the project's existing checks."
    return TrainingCardCandidateSnapshot(
        card_type="practice",
        title=title,
        created_from="resource",
        source_chain=["card_generation_router", "resource_knowledge"],
        resource_id=request.resource_anchor.resource_id,
        resource_anchor=request.resource_anchor,
        learning_family="code",
        learning_subtype="implementation",
        problem_statement=problem,
        deliverable=deliverable,
        learner_deliverables=[deliverable],
        acceptance_criteria=checks,
        verification_steps=[verification],
        validation_method=verification,
        reflection_prompt="哪个验证结果最能说明原理已实现？" if zh else "Which observed result best shows that the principle is working?",
    )
