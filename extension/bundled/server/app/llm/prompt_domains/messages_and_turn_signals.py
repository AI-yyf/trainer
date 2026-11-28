from __future__ import annotations

from typing import Any

from ...core.models import UserProfile
from ...workspace.classifier import is_code_like_current_file
from ..library_practice import library_practice_requested
from .templates_and_system import (
    COACHING_SYSTEM_TEMPLATE,
    LEARNER_PROFILE_BLOCK,
    MINIMAL_COACHING_SYSTEM_TEMPLATE,
    MINIMAL_LEARNER_PROFILE_BLOCK,
    _agent_loop_core_instructions,
    _answer_policy_instruction,
    _answer_policy_label,
    _append_depth_clauses,
    _build_resource_composer_boundary,
    _compact_list,
    _compact_text,
    _first_external_reference_summary,
    _first_learning_outcome_summary,
    _first_project_idea_summary,
    _first_project_source_summary,
    _guided_mode_requirements,
    _join_clauses,
    _prompt_visible_teaching_mode,
    _teaching_style_instruction,
    _teaching_style_label,
    active_view_label,
    first_look_recommended_next_from_context,
)


def _build_learner_context_block(context: dict[str, Any]) -> str:
    scenario = str(context.get("scenario", "idea_implementation"))
    signal = str(context.get("learner_signal", "steady"))
    lines: list[str] = [f"- Treat this as `{scenario}` with a `{signal}` learner."]
    active_view = _compact_text(context.get("active_view"), 24)
    if active_view:
        lines.append(f"- The learner is speaking from {active_view_label(active_view)}.")

    relationship_stage = _compact_text(context.get("relationship_stage"), 48)
    first_turn_priority = _compact_text(context.get("first_turn_priority"), 120)
    current_focus = _compact_text(context.get("current_focus"), 110)
    continuity_summary = _compact_text(context.get("continuity_summary"), 120)
    thread_clauses: list[str] = []
    if relationship_stage:
        thread_clauses.append(f"Relationship stage: {relationship_stage}.")
    if first_turn_priority:
        thread_clauses.append(f"First-turn priority: {first_turn_priority}.")
    if current_focus:
        thread_clauses.append(f"Current focus: {current_focus}.")
    if continuity_summary:
        thread_clauses.append(f"Continuity thread: {continuity_summary}.")
    thread_line = _join_clauses(*thread_clauses)
    if thread_line:
        lines.append(f"- {thread_line}")

    learner_profile_clauses: list[str] = []
    learner_name = _compact_text(context.get("learner_name"), 40)
    target_project = _compact_text(context.get("target_project"), 96)
    preferred_stack = _compact_text(context.get("preferred_stack"), 96)
    preferred_rhythm = _compact_text(context.get("preferred_rhythm"), 56)
    preferred_learning_mode = _compact_text(context.get("preferred_learning_mode"), 56)
    onboarding_request = _compact_text(context.get("onboarding_request"), 110)
    if learner_name:
        learner_profile_clauses.append(f"Learner name: {learner_name}.")
    if target_project:
        learner_profile_clauses.append(f"Target project: {target_project}.")
    if preferred_stack:
        learner_profile_clauses.append(f"Preferred stack or direction: {preferred_stack}.")
    if preferred_rhythm:
        learner_profile_clauses.append(f"Preferred rhythm: {preferred_rhythm}.")
    if preferred_learning_mode:
        learner_profile_clauses.append(f"Preferred coaching mode: {preferred_learning_mode}.")
    if onboarding_request:
        learner_profile_clauses.append(f"This round mainly wants to move: {onboarding_request}.")
    learner_profile_line = _join_clauses(*learner_profile_clauses)
    if learner_profile_line:
        lines.append(f"- {learner_profile_line}")

    coaching_adaptation = context.get("coaching_adaptation")
    tone_decision = context.get("tone_decision")
    teaching_decision = context.get("teaching_decision")
    bias_clauses: list[str] = []
    if isinstance(teaching_decision, dict):
        mode = _prompt_visible_teaching_mode(context)
        primary_goal = _compact_text(teaching_decision.get("primary_goal"), 110)
        if mode:
            bias_clauses.append(f"Teaching mode: {mode}.")
        if primary_goal:
            bias_clauses.append(f"Teaching goal: {primary_goal}.")
        _append_depth_clauses(teaching_decision, bias_clauses)
    if isinstance(coaching_adaptation, dict):
        adaptation_summary = _compact_text(coaching_adaptation.get("summary"), 140)
        if adaptation_summary:
            bias_clauses.append(f"Adaptive bias: {adaptation_summary}.")
    if isinstance(tone_decision, dict):
        tone = _compact_text(tone_decision.get("tone"), 32)
        verbosity = _compact_text(tone_decision.get("verbosity_bias"), 32)
        if tone or verbosity:
            bias_clauses.append(f"Tone / verbosity: {tone or 'steady'} / {verbosity or 'medium'}.")
    bias_line = _join_clauses(*bias_clauses)
    if bias_line:
        lines.append(f"- {bias_line}")

    memory_clauses: list[str] = []
    recent_wins = _compact_list(context.get("recent_wins"), 1)
    weak_spots = _compact_list(context.get("weak_spots"), 2)
    review_rhythm = _compact_text(context.get("review_rhythm"), 120)
    teaching_observations = _compact_list(context.get("teaching_observations"), 1)
    recalled_memory_summary = _compact_text(context.get("recalled_memory_summary"), 120)
    teaching_asset_summary = _compact_text(context.get("teaching_asset_summary"), 120)
    strategy_preference_summary = _compact_text(context.get("strategy_preference_summary"), 110)
    if recent_wins:
        memory_clauses.append(f"Preserve this recent win: {recent_wins[0]}.")
    if weak_spots:
        memory_clauses.append(f"Do not repeat: {'; '.join(weak_spots)}.")
    if review_rhythm:
        memory_clauses.append(f"Review rhythm to keep alive: {review_rhythm}.")
    if teaching_observations:
        memory_clauses.append(f"Teaching observation: {teaching_observations[0]}.")
    if recalled_memory_summary:
        memory_clauses.append(f"Relevant recalled memory: {recalled_memory_summary}.")
    if teaching_asset_summary:
        memory_clauses.append(f"Preferred teaching asset: {teaching_asset_summary}.")
    if strategy_preference_summary:
        memory_clauses.append(f"Strategy preference: {strategy_preference_summary}.")
    memory_line = _join_clauses(*memory_clauses)
    if memory_line:
        lines.append(f"- {memory_line}")

    grounding_clauses: list[str] = []
    failing_checks = _compact_list(context.get("failing_checks"), 3)
    if failing_checks:
        grounding_clauses.append(f"Reduce these checks first: {'; '.join(failing_checks)}.")
    requested_resource_summary = _compact_text(context.get("requested_resource_summary"), 120)
    if requested_resource_summary:
        grounding_clauses.append(f"Requested grounding: {requested_resource_summary}.")
    background_reference_summary = _compact_text(context.get("background_reference_summary"), 120)
    if background_reference_summary:
        grounding_clauses.append(f"Background summary: {background_reference_summary}.")
    reference_summary = _first_external_reference_summary(context)
    if reference_summary:
        grounding_clauses.append(f"One useful reference: {reference_summary}.")
    project_idea_summary = _first_project_idea_summary(context)
    if project_idea_summary:
        grounding_clauses.append(f"Project idea anchor: {project_idea_summary}.")
    project_source_summary = _first_project_source_summary(context)
    if project_source_summary:
        grounding_clauses.append(f"Source angle: {project_source_summary}.")
    principle_notes = context.get("principle_notes") or context.get("principle_note")
    if isinstance(principle_notes, dict):
        apply_now = _compact_text(principle_notes.get("apply_now"), 110)
        if apply_now:
            grounding_clauses.append(f"Principle apply-now move: {apply_now}.")
    exercise_prompt = context.get("exercise_prompt")
    if isinstance(exercise_prompt, dict):
        prompt = _compact_text(exercise_prompt.get("prompt"), 110)
        fallback_step = _compact_text(exercise_prompt.get("fallback_step"), 110)
        if prompt:
            grounding_clauses.append(f"Exercise prompt: {prompt}.")
        if fallback_step:
            grounding_clauses.append(f"Fallback if needed: {fallback_step}.")
    project_entry_points = _compact_list(context.get("project_entry_points"), 2)
    if project_entry_points:
        grounding_clauses.append(f"Code entry points: {'; '.join(project_entry_points)}.")
    learning_outcome_summary = _first_learning_outcome_summary(context)
    if learning_outcome_summary:
        grounding_clauses.append(learning_outcome_summary)
    grounding_line = _join_clauses(*grounding_clauses)
    if grounding_line:
        lines.append(f"- {grounding_line}")

    return "\n".join(lines)


def _language_instruction(response_language: str) -> str:
    """Reply language plus the one next-step label a reply in that language must use.

    The label is stated here, once and in the reply's own language, because the stored next step is
    read from that line. A real model asked for "the label in the reply's language" from an English
    rule wrote `` `Next step:` `` inside Chinese replies (2026-11-28), which the reader cannot parse.
    """
    lowered = response_language.lower()
    if lowered.startswith("zh"):
        return (
            "Respond in natural, stable Simplified Chinese. Do not mix in English except for code, API names, file paths, "
            "or literal identifiers that should remain unchanged. "
            "当回复以“下一步”收尾时，这一行必须以“下一步：”开头，写成纯文本："
            "不要用英文标签，不要给标签加反引号、引号或加粗。"
        )
    if lowered.startswith("en"):
        return (
            "Respond in English unless the learner explicitly asks to switch. "
            "When a reply ends with the next-step line, that line must start with the plain text label "
            "Next step: — no backticks, quotes, or bold around it."
        )
    return (
        f"Respond in {response_language} unless the learner explicitly asks to switch. "
        "When a reply ends with the next-step line, that line must start with the equivalent of the label "
        "Next step: in this language, written as plain text with no backticks, quotes, or bold around it."
    )


def build_static_coaching_prefix(
    profile: UserProfile,
    response_language: str | None = None,
    answer_mode: str | None = None,
    *,
    minimal_context: bool = False,
    use_minimal_template: bool = False,
    agent_loop_enabled: bool = False,
) -> str:
    """Build the system prompt shared by a session's turns, ordered for a provider prefix cache.

    What never changes within a session comes first — the coaching rules, the request priority, the
    tool instructions and the reply language — so a provider can reuse it on every call. The learner
    profile and the per-turn biases follow: the pedagogy service adapts the goal, the teaching style
    and the answer policy between turns, so material that depends on them must not sit at byte 0.
    """
    raw_answer_policy = answer_mode or profile.answer_policy
    answer_policy = _answer_policy_label(raw_answer_policy)
    teaching_style = _teaching_style_label(profile.teaching_style)
    profile_fields = {
        "goal": profile.long_term_goal or "Not specified",
        "background": profile.background or "Not specified",
        "weekly_hours": profile.weekly_hours,
        "teaching_style": teaching_style,
        "answer_policy": answer_policy,
        "target_project": profile.target_project or "Not specified",
        "libraries": ", ".join(profile.preferred_libraries) if profile.preferred_libraries else "None specified",
    }
    template = (
        MINIMAL_COACHING_SYSTEM_TEMPLATE if use_minimal_template else COACHING_SYSTEM_TEMPLATE
    )
    prefix = template.format(**profile_fields)
    if use_minimal_template and str(response_language or "").strip().lower().startswith("zh"):
        prefix += (
            "\n- 中文回答严禁使用空洞垫词与套话（“大家都知道”“众所周知”“显然”“其实很简单”"
            "“换句话说”“接下来我们来看一下”“非常巧妙”“代入即得”“希望对你有帮助”）。\n"
        )
    # Session-invariant part.
    prefix += (
        "\n\n## Request Priority\n"
        "- The learner's explicit question, requested format, requested length, and requested directness override generic coaching habits.\n"
        "- For a factual or conceptual question, answer the question before offering a plan, lane choice, training card, or follow-up.\n"
        "- Do not add a generic next action when the requested answer is already complete."
    )
    if agent_loop_enabled:
        prefix += _agent_loop_core_instructions()
    if response_language:
        prefix += f"\n\n## Language\n{_language_instruction(response_language)}"
    # Session- and turn-scoped part.
    profile_block = MINIMAL_LEARNER_PROFILE_BLOCK if use_minimal_template else LEARNER_PROFILE_BLOCK
    prefix += "\n\n" + profile_block.format(**profile_fields)
    prefix += (
        "\n\n## Teaching Style Bias\n"
        f"- Active style: {teaching_style}\n"
        f"- {_teaching_style_instruction(profile.teaching_style)}"
    )
    prefix += (
        "\n\n## Answer Policy Bias\n"
        f"- Active policy: {answer_policy}\n"
        f"- {_answer_policy_instruction(raw_answer_policy)}"
    )
    if answer_policy == "guided":
        prefix += f"\n{_guided_mode_requirements(response_language)}"
    if not minimal_context:
        prefix += (
            "\n\n## Teaching Method\n"
            "- Teach in this order when understanding matters: current state -> gap -> object or boundary -> constraint -> code or API move -> verification -> new state.\n"
            "- Make concepts feel necessary before naming them.\n"
            "- Do not start with a definition when the learner first needs the failure mode, pressure, or boundary.\n"
            "- Every important variable, function, API, or branch should answer: why is it needed now, what does it connect to, and what breaks without it?\n"
            "- Treat each code block as the implementation of the concepts just built: say which gap it closes and what state it maintains before walking the syntax, and refer each part back to the concept it realizes.\n"
            "- Every 2-3 new ideas, briefly recycle the state so the learner knows what is already known, what is still missing, and what proof comes next."
        )
    return prefix


def _library_analysis_system_prompt(
    profile: UserProfile, context: dict[str, Any], response_language: str | None,
    message: str | None,
) -> str:
    lines = [
        "You are Trainer. Compare only the facts stated in the indexed excerpts below. "
        "Do not infer architecture details, supervision, data labels, metrics, or loss functions from a paper's title or topic.",
        _build_resource_composer_boundary(context),
    ]
    if message and library_practice_requested(message, context):
        lines.append(
            "Answer in Markdown. First give each paper's concrete method and what its training "
            "predicts or learns, with the source number beside each. For the study proposal, give "
            "two small work products the learner can check. Phrase current knowledge as unassessed "
            "when the learner has provided no evidence. Leave out the practice question."
        )
    if response_language:
        lines.append(_language_instruction(response_language))
    if profile.long_term_goal:
        lines.append(f"Learner goal: {_compact_text(profile.long_term_goal, 240)}")
    if profile.background:
        lines.append(f"Learner background: {_compact_text(profile.background, 240)}")
    excerpts = context.get("resource_fragments")
    if isinstance(excerpts, list) and excerpts:
        lines.append("Indexed excerpts. Cite these exact numbers in your answer.")
        for number, item in enumerate(excerpts[:4], start=1):
            if isinstance(item, dict):
                title = _compact_text(item.get("title"), 140)
                passage = _compact_text(item.get("excerpt") or item.get("snippet"), 900)
                lines.append(f"[{number}] {title}\n<excerpt>{passage}</excerpt>")
    else:
        lines.append("No verified indexed excerpts were found. Say which evidence is missing before proposing a comparison.")
    return "\n\n".join(lines)


def _nested_get(obj: dict[str, object] | None, *path: str) -> object | None:
    current: object | None = obj
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _first_value(*values: object | None) -> object | None:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, list) and not value:
            continue
        return value
    return None


def _first_str(*values: object | None) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _coaching_history_mode(
    current_file: dict[str, object] | None,
    coach_context: dict[str, Any] | None,
) -> str:
    return (
        _first_str(
            _nested_get(coach_context, "history_mode") if coach_context else None,
            _nested_get(coach_context, "coach_context", "history_mode") if coach_context else None,
            _nested_get(current_file, "history_mode"),
            _nested_get(current_file, "coach_context", "history_mode"),
        )
        or ""
    ).strip().lower()


def infer_coaching_scenario(
    message: str,
    current_file: dict[str, object] | None = None,
    coach_context: dict[str, Any] | None = None,
    *,
    default: str = "idea_implementation",
) -> str:
    lowered = message.lower()
    diagnostics = current_file.get("diagnostics") if current_file else None
    has_diagnostics = isinstance(diagnostics, list) and bool(diagnostics)

    explicit_scenario = _first_str(
        _nested_get(coach_context, "scenario") if coach_context else None,
        _nested_get(coach_context, "coaching_state", "scenario") if coach_context else None,
        _nested_get(coach_context, "coach_context", "scenario") if coach_context else None,
        _nested_get(current_file, "scenario"),
        _nested_get(current_file, "coaching_state", "scenario"),
        _nested_get(current_file, "coach_context", "scenario"),
    )
    if explicit_scenario and _coaching_history_mode(current_file, coach_context) != "fresh_lane":
        return explicit_scenario

    def _has_any(*tokens: str) -> bool:
        return any(token in lowered for token in tokens)

    rejects_broad_plan = _has_any(
        "not a whole study plan",
        "not a full study plan",
        "without turning this into a full study plan",
        "don't turn this into a full study plan",
        "don't turn this into a study plan",
        "don't make this a plan",
        "先别展开成总计划",
        "不要把它变成完整学习计划",
        "不要把它变成学习计划",
        "别把它变成学习计划",
        "先别变成计划",
        "不要变成计划",
    )
    language_learning_request = _has_any(
        "revise",
        "rewrite",
        "edit this paragraph",
        "project update paragraph",
        "improve this writing",
        "improve this sentence",
        "teach me the word",
        "vocabulary",
        "word meaning",
        "润色",
        "改写",
        "措辞",
        "段落",
        "句子",
        "单词",
        "词汇",
        "中文写作",
        "英文写作",
    )
    idea_request = _has_any(
        "implement",
        "build",
        "ship",
        "prototype",
        "mvp",
        "i want to build",
        "i want to make",
        "i have an idea",
        "turn this idea into",
        "make it real",
        "落地",
        "原型",
        "最小原型",
        "最小可验证",
        "做出来",
        "做成原型",
        "想实现",
        "想做",
        "我有个 idea",
        "我有一个 idea",
        "我有个 ai idea",
        "我有一个 ai idea",
    )
    resource_contract_request = _has_any(
        "design doc",
        "design document",
        "resource contract",
        "view contract",
        "first viewport promise",
        "must not become",
        "resources view",
        "resource view",
        "设计文档",
        "文档",
        "资料",
        "资源",
        "首屏承诺",
        "绝不能变成什么",
        "不能变成什么",
        "不要变成什么",
        "视图",
        "\u8bbe\u8ba1\u6587\u6863",
        "\u6587\u6863",
        "\u8d44\u6599",
        "\u8d44\u6e90",
        "\u9996\u5c4f\u627f\u8bfa",
        "\u7edd\u4e0d\u80fd\u53d8\u6210\u4ec0\u4e48",
        "\u4e0d\u80fd\u53d8\u6210\u4ec0\u4e48",
        "\u4e0d\u8981\u53d8\u6210\u4ec0\u4e48",
        "\u89c6\u56fe",
    )
    direct_explanation_request = _has_any(
        "tell me",
        "please tell me",
        "directly tell me",
        "what is",
        "what are",
        "what must not",
        "explain",
        "请告诉我",
        "直接告诉我",
        "请直接告诉我",
        "是什么",
        "讲解",
        "说明",
        "\u8bf7\u544a\u8bc9\u6211",
        "\u76f4\u63a5\u544a\u8bc9\u6211",
        "\u8bf7\u76f4\u63a5\u544a\u8bc9\u6211",
        "\u662f\u4ec0\u4e48",
        "\u8bb2\u89e3",
        "\u8bf4\u660e",
    )
    resource_contract_definition_request = (
        _has_any(
            "first viewport promise",
            "must not become",
            "resources view",
            "resource view",
            "\u9996\u5c4f\u627f\u8bfa",
            "\u7edd\u4e0d\u80fd\u53d8\u6210\u4ec0\u4e48",
            "\u8d44\u6599\u89c6\u56fe",
            "\u8d44\u6e90\u89c6\u56fe",
        )
        and _has_any(
            "first viewport promise",
            "must not become",
            "\u9996\u5c4f\u627f\u8bfa",
            "\u7edd\u4e0d\u80fd\u53d8\u6210\u4ec0\u4e48",
            "\u4e0d\u80fd\u53d8\u6210\u4ec0\u4e48",
            "\u4e0d\u8981\u53d8\u6210\u4ec0\u4e48",
        )
    )
    if (
        resource_contract_request
        and not has_diagnostics
        and (direct_explanation_request or resource_contract_definition_request)
    ):
        return "principle"

    if _has_any(
        "remote ssh",
        "remote workspace",
        "remote workflow",
        "remote workflows",
        "remote tunnel",
        "remote tunnels",
        "vscode remote",
        "vs code remote",
        "dev container",
        "dev containers",
        "devcontainer",
        "wsl",
        "ssh",
        "远程",
        "远程 ssh",
        "远程开发",
        "远程工作区",
        "开发容器",
        "docker 容器",
        "docker容器",
        "容器工作区",
        "容器开发环境",
        "隧道",
        "主机",
        "host label",
        "凭据模式",
        "工作区边界",
        "credential mode",
    ):
        return "remote_workspace"

    if _has_any(
        "signature help",
        "function signature",
        "function hint",
        "function guidance",
        "parameter hint",
        "hover",
        "peek definition",
        "jump to definition",
        "go to definition",
        "find all references",
        "intellisense",
        "autocomplete",
        "call site",
        "function call",
        "read a function",
        "what this function does",
        "function tips",
        "函数提示",
        "参数提示",
        "函数签名",
        "签名提示",
        "悬停",
        "查看定义",
        "跳转定义",
        "调用点",
        "看懂函数",
        "函数作用",
    ):
        return "function_guidance"

    function_subject = _has_any(
        "function",
        "method",
        "call site",
        "function contract",
        "typescript function",
        "ts function",
        "api call",
        "函数",
        "调用点",
        "函数契约",
        "陌生函数",
    )
    function_guidance_clue = _has_any(
        "before i edit",
        "before editing",
        "before i change",
        "before i touch",
        "unfamiliar",
        "understand this function",
        "read this function",
        "what this function expects",
        "contract",
        "改之前",
        "编辑之前",
        "修改之前",
        "先看懂",
        "看懂",
        "契约",
    )
    if function_subject and function_guidance_clue:
        return "function_guidance"

    if _has_any(
        "launch.json",
        "breakpoint",
        "debug loop",
        "debug console",
        "debug session",
        "debugging in vs code",
        "debug in vs code",
        "debugging in vscode",
        "debug in vscode",
        "watch expression",
        "step into",
        "step over",
        "exception breakpoint",
        "run and debug",
        "debug python",
        "vscode debug",
        "vs code debug",
        "调试",
        "断点",
        "调试器",
        "调试控制台",
        "调用栈",
        "变量",
        "单步",
        "单步进入",
        "单步跳过",
        "监视",
        "异常断点",
        "运行和调试",
        "launch 配置",
        "在 vscode 里调试",
    ):
        return "debug_loop"

    if has_diagnostics or _has_any(
        "review",
        "fix",
        "failing",
        "fails",
        "error",
        "bug",
        "diagnose",
        "diagnosis",
        "what's wrong",
        "whats wrong",
        "what is wrong",
        "stack trace",
        "traceback",
        "复盘",
        "报错",
        "错误",
        "修复",
        "排错",
        "诊断",
        "排查",
        "为什么会挂",
        "为什么失败",
    ):
        return "review"

    if _has_any(
        "principle",
        "why",
        "explain",
        "mechanism",
        "为什么",
        "讲解",
        "原理",
        "机制",
    ):
        return "principle"

    if language_learning_request:
        return "general"

    if idea_request and rejects_broad_plan:
        return "idea_implementation"

    if _has_any(
        "refactor",
        "reshape",
        "adapt",
        "migrate",
        "existing project adaptation",
        "现有项目改造",
        "改造现有项目",
        "把一个现有项目改成",
        "把现有项目改成",
        "现有项目改成",
        "已有项目改成",
        "把这个现有项目改造",
        "基于现有项目",
        "在现有项目上改",
        "已有项目迁移",
        "项目迁移",
        "二次开发",
        "适配现有项目",
        "必须保持不变",
        "必须改变",
        "改造",
        "重构",
        "迁移",
        "适配",
    ):
        return "project_adaptation"

    if _has_any(
        "extract",
        "mine",
        "what should i build",
        "what can i practice",
        "练什么",
        "训练题",
        "训练任务",
        "从当前项目里提炼",
        "提炼",
        "当前项目",
    ):
        return "project_idea"

    if _has_any("plan", "roadmap", "milestone", "review cadence", "复习", "计划", "路线图"):
        return "plan"

    if _has_any("task", "/task", "任务", "练习题"):
        return "task"
    if _has_any("/next", "next task", "下一题", "下一个任务"):
        return "next_task"
    if idea_request:
        return "idea_implementation"

    return default


def _function_guidance_prompt_inputs(
    message: str | None,
    current_file: dict[str, object] | None,
    coach_context: dict[str, Any] | None,
) -> tuple[str, dict[str, object] | None]:
    scenario = infer_coaching_scenario(
        message or "",
        current_file,
        coach_context,
        default="idea_implementation",
    )
    if scenario != "function_guidance":
        return scenario, current_file
    if is_code_like_current_file(current_file):
        return scenario, current_file
    return scenario, None


def _has_execution_ready_next_step_request(
    message: str | None,
    current_file: dict[str, object] | None = None,
) -> bool:
    if not message:
        return False

    lowered = " ".join(message.lower().split())
    scenario = infer_coaching_scenario(
        message,
        current_file,
        None,
        default="general",
    )
    next_step_tokens = (
        "next step",
        "next move",
        "first step",
        "smallest next step",
        "tiny next step",
        "give me the next step",
        "only tell me the next step",
        "what should i do next",
        "what do i do next",
        "what should i change first",
        "\u4e0b\u4e00\u6b65",
        "下一招",
        "最小可验证动作",
        "先改哪里",
        "只告诉我",
        "\u4e0b\u4e00\u62db",
        "\u6700\u5c0f\u52a8\u4f5c",
        "\u5148\u505a\u4ec0\u4e48",
        "先改哪里",
        "\u4e0b\u4e00\u6b65\u8be5\u505a\u4ec0\u4e48",
        # Natural phrasings a learner uses when asking for the first concrete
        # slice. Missing these sent execution-ready turns back through the
        # intake reframe, which replaced a live model reply with the canned
        # lane-selection template (verified live against MiniMax-M2.7).
        "第一步",
        "第一小步",
        "第一个练习",
        "最小练习",
        "的练习",
        "练习开始",
        "第一个任务",
        "给我练习",
        "先带我做",
        "\u5e26\u6211\u505a\u4e00\u4e2a",
        "只告诉我",
    )
    scope_tokens = (
        "small",
        "smallest",
        "tiny",
        "minimal",
        "thin",
        "narrow",
        "focused",
        "verifiable",
        "teaching value",
        "very small",
        "很小",
        "小步",
        "一小步",
        "\u6700\u5c0f",
        "小步",
        "一小步",
        "\u53ef\u9a8c\u8bc1",
        "\u6559\u5b66\u4ef7\u503c",
        "\u5c0f\u8865\u4e01",
    )
    learn_first_tokens = (
        "learn -> try -> verify",
        "learn first",
        "teach me first",
        "explain first",
        "walk me through it first",
        "start by teaching",
        "\u5148\u5b66",
        "\u5148\u5b66\u4e60",
        "\u5148\u6559\u6211",
        "\u5148\u89e3\u91ca",
        "\u5148\u8bb2",
        "\u5148\u5e26\u6211",
        "\u5148\u5b66\u518d\u6d4b",
        "\u5148\u5b66\u518d\u8bd5",
        "\u4e0d\u8981\u4e00\u4e0a\u6765\u76f4\u63a5\u8003\u8bd5",
        "\u522b\u4e00\u4e0a\u6765\u5c31\u8003",
    )
    try_or_verify_tokens = (
        "try",
        "small try",
        "tiny try",
        "very small try",
        "verify",
        "verification",
        "small verification",
        "tiny verification",
        "test me",
        "check it",
        "\u8bd5\u4e00\u4e0b",
        "\u5f88\u5c0f\u7684 try",
        "\u5f88\u5c0f\u7684\u9a8c\u8bc1",
        "\u6700\u5c0f\u9a8c\u8bc1",
        "\u6700\u5c0f\u9a8c\u8bc1\u52a8\u4f5c",
        "\u518d\u6d4b",
        "\u518d\u8bd5",
        "\u518d\u9a8c\u8bc1",
        "\u6d4b\u8bd5\u6211",
        "\u9a8c\u8bc1\u52a8\u4f5c",
    )

    wants_next_step = any(token in lowered for token in next_step_tokens)
    wants_small_scope = any(token in lowered for token in scope_tokens)
    wants_learn_first = any(token in lowered for token in learn_first_tokens)
    wants_try_or_verify = any(token in lowered for token in try_or_verify_tokens)
    # An explicit ask for the first concrete slice is execution-ready on its
    # own; requiring an additional smallness qualifier here is what let "第一
    # 步做什么"-style turns fall back into the intake lane template.
    explicit_first_slice_ask = any(
        token in lowered
        for token in (
            "第一步做什么",
            "第一步是",
            "第一步该",
            "第一小步",
            "第一个练习",
            "第一个任务",
            "先带我做",
            "带我做一个",
        )
    )
    has_live_anchor = bool(
        current_file
        and any(
            str(current_file.get(key) or "").strip()
            for key in ("path", "selection_text", "content_excerpt", "content")
        )
    )
    guided_lane = scenario in {"remote_workspace", "debug_loop", "function_guidance"}

    if wants_next_step and wants_small_scope:
        return True
    if explicit_first_slice_ask:
        return True
    if has_live_anchor and wants_learn_first and (wants_try_or_verify or wants_small_scope or wants_next_step):
        return True
    if guided_lane and wants_learn_first and (wants_try_or_verify or wants_small_scope or wants_next_step):
        return True
    return False


def infer_learner_signal(
    message: str,
    current_file: dict[str, object] | None = None,
    coach_context: dict[str, Any] | None = None,
) -> str:
    explicit_signal = _first_str(
        _nested_get(coach_context, "learner_signal") if coach_context else None,
        _nested_get(coach_context, "coaching_state", "learner_signal") if coach_context else None,
        _nested_get(coach_context, "coach_context", "learner_signal") if coach_context else None,
        _nested_get(current_file, "learner_signal"),
        _nested_get(current_file, "coaching_state", "learner_signal"),
        _nested_get(current_file, "coach_context", "learner_signal"),
    )
    if explicit_signal and _coaching_history_mode(current_file, coach_context) != "fresh_lane":
        return explicit_signal

    lowered = message.lower()
    if any(
        token in lowered
        for token in (
            "stuck",
            "blocked",
            "can't",
            "cannot",
            "broken",
            "卡住了",
            "搞不定",
            "不会",
            "不行",
            "崩了",
        )
    ):
        return "blocked"
    if any(
        token in lowered
        for token in (
            "confused",
            "not sure",
            "uncertain",
            "maybe",
            "不确定",
            "没把握",
            "大概",
            "有点糊涂",
        )
    ):
        return "uncertain"
    if any(
        token in lowered
        for token in (
            "why",
            "how",
            "curious",
            "understand",
            "原理",
            "想试试",
            "想弄懂",
            "好奇",
        )
    ):
        return "curious"
    return "steady"


def _coerce_resource_sequence_guidance(value: object | None) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    sequences: list[dict[str, object]] = []
    for item in value[:3]:
        if not isinstance(item, dict):
            continue
        title = _first_str(item.get("title"), item.get("source"), item.get("resource_id")) or "resource"
        source = _first_str(item.get("source")) or ""
        boundary_sentinel = _first_str(item.get("boundary_sentinel"), item.get("boundary")) or ""
        raw_steps = item.get("steps")
        if not isinstance(raw_steps, list):
            continue
        steps: list[dict[str, str]] = []
        for step in raw_steps[:6]:
            if not isinstance(step, dict):
                continue
            label = _first_str(step.get("label"), step.get("step")) or ""
            text = _first_str(step.get("text"), step.get("body"), step.get("summary")) or ""
            if not label or not text:
                continue
            steps.append({"label": label, "text": text})
        if len(steps) < 2:
            continue
        sequences.append(
            {
                "title": title,
                "source": source,
                "boundary_sentinel": boundary_sentinel,
                "steps": steps,
                "step_count": len(steps),
            }
        )
    return sequences


def _extract_next_step_hint_text(value: object | None) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, dict):
        return _first_str(
            value.get("title"),
            value.get("label"),
            value.get("next_step"),
            value.get("nextStep"),
            value.get("summary"),
        )
    return None


def _build_turn_contract_block(context: dict[str, Any]) -> str:
    scenario = _compact_text(context.get("scenario"), 48)
    current_focus = _compact_text(context.get("current_focus"), 110)
    next_step_hint = _compact_text(_extract_next_step_hint_text(context.get("next_step_hint")), 110)
    thread_summary = _compact_text(context.get("thread_summary"), 140)
    thread_next_step = _compact_text(context.get("thread_next_step"), 110)
    resume_hint = _compact_text(context.get("resume_hint"), 160)
    review_queue_summary = _compact_text(context.get("review_queue_summary"), 120)
    pace_signal = _compact_text(context.get("pace_signal"), 48)
    failing_checks = _compact_list(context.get("failing_checks"), 3)
    exercise_prompt = context.get("exercise_prompt")
    implementation_guide = context.get("implementation_guide")
    decision = _compact_text(context.get("decision"), 96)
    blocker = _compact_text(context.get("blocker"), 96)
    teaching_note = _compact_text(context.get("teaching_note"), 120)
    confidence = _compact_text(context.get("confidence"), 32)
    evidence = _compact_list(context.get("evidence"), 3)
    auto_resource_lookup = bool(context.get("auto_resource_lookup"))
    requested_resources = context.get("requested_resources")
    has_prepared_resource_grounding = auto_resource_lookup or (
        isinstance(requested_resources, list) and bool(requested_resources)
    )
    resource_question_facets = _compact_list(context.get("resource_question_facets"), 4)
    resource_sequence_summary = _compact_text(context.get("resource_sequence_summary"), 180)

    contract_clauses: list[str] = []
    if current_focus:
        contract_clauses.append(f"stay on {current_focus}")
    if next_step_hint:
        contract_clauses.append(f"use this next move: {next_step_hint}")
    if thread_summary:
        contract_clauses.append(f"resume the live thread around {thread_summary}")
    if thread_next_step:
        contract_clauses.append(f"carry forward this next move: {thread_next_step}")
    if resume_hint:
        contract_clauses.append(f"follow this resume hint: {resume_hint}")
    if failing_checks:
        contract_clauses.append(f"verify against {'; '.join(failing_checks)}")
    if review_queue_summary:
        contract_clauses.append(f"keep the review rhythm in view: {review_queue_summary}")
    if pace_signal in {"fragile", "gentle", "overloaded", "stalled", "recovery"}:
        contract_clauses.append("shrink scope before widening")
    if decision:
        contract_clauses.append(f"keep the latest finalized decision in view: {decision}")
    if blocker:
        contract_clauses.append(f"respect this blocker: {blocker}")
    if teaching_note:
        contract_clauses.append(f"follow this teaching note: {teaching_note}")
    if confidence:
        contract_clauses.append(f"coach confidence is {confidence}")
    if evidence:
        contract_clauses.append(f"ground the turn in {'; '.join(evidence)}")
    if has_prepared_resource_grounding:
        contract_clauses.append(
            "start from the prepared library grounding for this turn before widening to memory or general recall"
        )
        if resource_question_facets:
            contract_clauses.append(
                f"cover every explicitly requested resource facet: {'; '.join(resource_question_facets)}"
            )
        if scenario == "principle":
            contract_clauses.append(
                "answer the explicit resource question directly before you widen into generic teaching or another coaching lane"
            )
            if {
                "first viewport promise",
                "must not become",
            }.issubset({item.casefold() for item in resource_question_facets}):
                contract_clauses.append(
                    "state both the positive promise and the negative must-not-become boundary in the visible reply"
                )
    if resource_sequence_summary:
        contract_clauses.append(
            f"preserve this prepared library sequence exactly: {resource_sequence_summary}"
        )

    if isinstance(exercise_prompt, dict):
        success_signal = _compact_text(exercise_prompt.get("success_signal"), 96)
        fallback_step = _compact_text(exercise_prompt.get("fallback_step"), 96)
        if success_signal:
            contract_clauses.append(f"treat success as: {success_signal}")
        if fallback_step:
            contract_clauses.append(f"fallback: {fallback_step}")

    if isinstance(implementation_guide, dict):
        validation = _compact_list(implementation_guide.get("validation_strategy"), 2)
        if validation:
            contract_clauses.append(f"validate with {'; '.join(validation)}")

    first_look_next = _compact_text(
        context.get("first_look_recommended_next") or first_look_recommended_next_from_context(context),
        110,
    )
    if first_look_next and not _compact_text(context.get("active_task"), 48):
        contract_clauses.append(f"stay with this first-look next: {first_look_next}")
        contract_clauses.append("do not invent a plan, card, task, note, or resource")

    if not contract_clauses:
        return ""

    return _join_clauses(*contract_clauses) or ""


def _looks_like_first_turn(context: dict[str, Any]) -> bool:
    if context.get("execution_ready"):
        return False

    current_focus = str(context.get("current_focus") or "").strip()
    summary = str(context.get("summary") or "").strip()
    next_step_hint = _extract_next_step_hint_text(context.get("next_step_hint")) or ""
    thread_summary = str(context.get("thread_summary") or "").strip()
    thread_next_step = str(context.get("thread_next_step") or "").strip()
    resume_hint = str(context.get("resume_hint") or "").strip()
    memory_evidence = context.get("memory_evidence") or []
    active_thread = context.get("active_thread")
    review_queue_summary = str(context.get("review_queue_summary") or "").strip()
    project_summary = str(context.get("project_summary") or "").strip()
    learning_outcomes = context.get("learning_outcomes") or []
    teaching_observations = context.get("teaching_observations") or []
    due_reviews = context.get("due_reviews") or []
    recalled_memory_summary = str(context.get("recalled_memory_summary") or "").strip()
    teaching_asset_summary = str(context.get("teaching_asset_summary") or "").strip()
    workspace_understanding_present = bool(project_summary or context.get("project_entry_points"))

    has_active_thread = False
    if isinstance(active_thread, dict):
        has_active_thread = any(
            str(active_thread.get(key) or "").strip()
            for key in (
                "focus_area",
                "summary",
                "next_step",
                "verified_result",
                "blocker",
                "decision",
                "teaching_note",
                "confidence",
            )
        ) or any(str(item).strip() for item in (active_thread.get("evidence") or []))
    context_evidence = context.get("evidence")
    has_active_thread = has_active_thread or any(
        str(context.get(key) or "").strip()
        for key in ("decision", "blocker", "teaching_note", "confidence")
    ) or (
        isinstance(context_evidence, list)
        and any(str(item).strip() for item in context_evidence)
    )
    has_memory_evidence = isinstance(memory_evidence, list) and any(str(item).strip() for item in memory_evidence)
    has_learning_history = isinstance(learning_outcomes, list) and any(
        isinstance(item, dict)
        and any(str(item.get(key) or "").strip() for key in ("concept", "summary", "outcome"))
        for item in learning_outcomes
    )
    has_due_reviews = isinstance(due_reviews, list) and any(
        isinstance(item, dict) and any(str(item.get(key) or "").strip() for key in ("concept", "reason"))
        for item in due_reviews
    )
    has_teaching_memory = any(
        (
            recalled_memory_summary,
            teaching_asset_summary,
            isinstance(teaching_observations, list)
            and any(str(item).strip() for item in teaching_observations),
        )
    )
    focus_from_live_thread = has_active_thread or bool(
        summary or next_step_hint or review_queue_summary or thread_summary or thread_next_step or resume_hint
    )
    memory_should_open_onboarding = not any(
        (
            has_learning_history,
            has_due_reviews,
            has_teaching_memory,
            has_memory_evidence,
            focus_from_live_thread,
        )
    )

    return memory_should_open_onboarding and not any(
        (
            summary,
            next_step_hint,
            review_queue_summary,
            has_active_thread,
            current_focus if not workspace_understanding_present else "",
        )
    )


def _coerce_str_list(value: object | None) -> list[str]:
    if not isinstance(value, list):
        return []
    results: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            results.append(item.strip())
        elif isinstance(item, dict):
            text = _first_str(
                item.get("summary"),
                item.get("reason"),
                item.get("concept"),
                item.get("title"),
            )
            if text:
                results.append(text)
    return results


def _coerce_due_reviews(value: object | None) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    results: list[dict[str, str]] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            results.append({"concept": item.strip(), "reason": "", "due_at": ""})
        elif isinstance(item, dict):
            concept = _first_str(item.get("concept"), item.get("title"), item.get("summary")) or "review"
            reason = _first_str(item.get("reason")) or ""
            due_at = _first_str(item.get("due_at")) or ""
            results.append({"concept": concept, "reason": reason, "due_at": due_at})
    return results


def _format_due_review_item(item: dict[str, str]) -> str:
    concept = item.get("concept", "review")
    reason = item.get("reason", "")
    due_at = item.get("due_at", "")
    if reason and due_at:
        return f"{concept}: {reason} (due {due_at})"
    if reason:
        return f"{concept}: {reason}"
    if due_at:
        return f"{concept} (due {due_at})"
    return concept
