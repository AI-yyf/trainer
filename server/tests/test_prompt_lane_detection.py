from app.llm.prompts import infer_coaching_scenario, infer_learner_signal


def test_infer_coaching_scenario_prefers_debug_loop_over_bug_substring() -> None:
    assert (
        infer_coaching_scenario(
            "Now teach me the smallest VS Code debug loop.",
            default="general",
        )
        == "debug_loop"
    )


def test_infer_coaching_scenario_recognizes_function_signature_navigation_language() -> None:
    assert (
        infer_coaching_scenario(
            "Now teach me how to inspect a function signature and jump to definition.",
            default="general",
        )
        == "function_guidance"
    )


def test_infer_coaching_scenario_recognizes_unfamiliar_function_before_editing() -> None:
    assert (
        infer_coaching_scenario(
            "This is an unfamiliar TypeScript function. Help me understand its contract before I edit it.",
            default="general",
        )
        == "function_guidance"
    )


def test_infer_coaching_scenario_recognizes_remote_workspace_chinese() -> None:
    assert (
        infer_coaching_scenario(
            "\u5148\u6559\u6211\u600e\u4e48\u5224\u65ad VS Code \u8fdc\u7a0b\u5de5\u4f5c\u533a\u8fb9\u754c\uff0c"
            "\u518d\u7ed9\u6211\u4e00\u4e2a\u5f88\u5c0f\u7684\u9a8c\u8bc1\u52a8\u4f5c\u3002",
            default="general",
        )
        == "remote_workspace"
    )


def test_infer_coaching_scenario_recognizes_vs_code_remote_workflows_phrase() -> None:
    assert (
        infer_coaching_scenario(
            "I want to learn VS Code remote workflows first, then verify my understanding with one tiny real step.",
            default="general",
        )
        == "remote_workspace"
    )


def test_infer_coaching_scenario_recognizes_review_in_chinese() -> None:
    assert infer_coaching_scenario("请帮我复盘这个报错", default="general") == "review"


def test_infer_coaching_scenario_recognizes_project_adaptation_in_chinese() -> None:
    assert infer_coaching_scenario("把这个现有项目改造一下", default="general") == "project_adaptation"
    assert infer_coaching_scenario("把一个现有项目改成我真正想要的样子", default="general") == "project_adaptation"


def test_infer_coaching_scenario_routes_direct_resource_doc_question_to_principle() -> None:
    assert (
        infer_coaching_scenario(
            "我刚导入了一份设计文档。请直接告诉我 Resources 视图的 first viewport promise，以及它绝不能变成什么。",
            default="general",
        )
        == "principle"
    )


def test_infer_coaching_scenario_recognizes_idea_implementation_in_chinese() -> None:
    assert (
        infer_coaching_scenario(
            "我有一个 AI idea，想把它落地成一个最小可验证的原型。",
            default="general",
        )
        == "idea_implementation"
    )


def test_infer_coaching_scenario_keeps_concrete_chinese_idea_out_of_plan() -> None:
    assert (
        infer_coaching_scenario(
            "\u6211\u6709\u4e00\u4e2a AI idea\uff0c\u60f3\u628a\u5b83\u843d\u5730\u6210\u4e00\u4e2a\u6700\u5c0f\u53ef\u9a8c\u8bc1\u7684\u539f\u578b\u3002"
            "\u5148\u522b\u5c55\u5f00\u6210\u603b\u8ba1\u5212\uff0c\u5148\u966a\u6211\u538b\u51fa\u7b2c\u4e00\u6761\u6700\u5c0f\u5207\u7247\u3002",
            default="general",
        )
        == "idea_implementation"
    )


def test_infer_coaching_scenario_keeps_chinese_writing_help_out_of_plan() -> None:
    assert (
        infer_coaching_scenario(
            "\u5e2e\u6211\u6da6\u8272\u4e00\u6bb5\u4e2d\u6587\u9879\u76ee\u8fdb\u5c55\u66f4\u65b0\u3002"
            "\u5148\u53ea\u6539\u8fd9\u4e00\u4e2a\u6bb5\u843d\uff0c\u4e0d\u8981\u628a\u5b83\u53d8\u6210\u5b8c\u6574\u5b66\u4e60\u8ba1\u5212\u3002",
            default="general",
        )
        == "general"
    )


def test_infer_learner_signal_recognizes_blocked_in_chinese() -> None:
    assert infer_learner_signal("我卡住了，搞不定") == "blocked"


def test_infer_learner_signal_recognizes_curious_in_chinese() -> None:
    assert infer_learner_signal("我想试试这个原理") == "curious"
