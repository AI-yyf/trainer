"""Task scaffolding helpers (§五十二: extracted from provider_service.py).

Builds the concrete scaffolding around a practice step: surface context,
anchor phrasing, diagnosis, teaching notes, and the argument shapes used
to verify practice attempts.
"""

from __future__ import annotations

from typing import Any

from .coaching_recovery import _trim_sentence
from .prompts import _format_due_review_item


def _practice_verification_arguments(
    *,
    current_file: dict[str, object],
    coach_context: dict[str, Any] | None,
) -> dict[str, Any]:
    criteria: list[str] = []
    expected_symbols: list[str] = []

    def add_text(value: Any) -> None:
        text = str(value or "").strip()
        if text and text not in criteria:
            criteria.append(text)

    def add_list(value: Any) -> None:
        if not isinstance(value, list):
            return
        for item in value:
            add_text(item)

    def add_symbol(value: Any) -> None:
        text = str(value or "").strip()
        if text and text not in expected_symbols:
            expected_symbols.append(text)

    def add_symbol_list(value: Any) -> None:
        if not isinstance(value, list):
            return
        for item in value:
            add_symbol(item)

    def collect_from_record(record: Any) -> None:
        if not isinstance(record, dict):
            return
        add_list(record.get("acceptance_criteria") or record.get("acceptanceCriteria"))
        add_list(record.get("learner_deliverables") or record.get("learnerDeliverables"))
        add_list(record.get("verification_steps") or record.get("verificationSteps"))
        add_list(record.get("self_check") or record.get("selfCheck"))
        add_list(record.get("constraints"))
        for key in (
            "success_signal",
            "successSignal",
            "deliverable",
            "problem_statement",
            "problemStatement",
            "suggested_workspace_action",
            "suggestedWorkspaceAction",
        ):
            add_text(record.get(key))
        add_symbol_list(record.get("expected_symbols") or record.get("expectedSymbols"))
        add_symbol_list(record.get("api_hints") or record.get("apiHints"))

    collect_from_record(current_file)
    if isinstance(coach_context, dict):
        collect_from_record(coach_context.get("exercise_prompt"))
        collect_from_record(coach_context)
        routing = coach_context.get("active_training_card_routing") or coach_context.get("activeTrainingCardRouting")
        if isinstance(routing, dict):
            collect_from_record(routing.get("selected_card") or routing.get("selectedCard"))
        memory = coach_context.get("memory")
        if isinstance(memory, dict):
            routing = memory.get("active_training_card_routing") or memory.get("activeTrainingCardRouting")
            if isinstance(routing, dict):
                collect_from_record(routing.get("selected_card") or routing.get("selectedCard"))
            ledger = memory.get("training_event_ledger") or memory.get("trainingEventLedger")
            if isinstance(ledger, list):
                for item in ledger[-4:]:
                    collect_from_record(item)

    return {
        "acceptance_criteria": criteria[:12],
        "expected_symbols": expected_symbols[:12],
        "max_evidence": 8,
    }


def _surface_context_text(text: str, *, chinese: bool) -> str | None:
    cleaned = text.strip()
    if not cleaned:
        return None
    if not chinese:
        return cleaned
    if _looks_english_heavy(cleaned):
        return None
    return cleaned


def _looks_english_heavy(text: str) -> bool:
    alpha_count = sum(1 for char in text if char.isalpha() and char.isascii())
    cjk_count = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    return alpha_count > 8 and cjk_count == 0


def _scaffold_anchor(
    *,
    scenario: str,
    goal: str,
    file_path: str | None,
    current_focus: str,
    chinese: bool,
) -> str:
    visible_focus = _surface_context_text(current_focus, chinese=chinese)
    if visible_focus:
        return (
            f"我们先沿着这条线继续：{visible_focus}。"
            if chinese
            else f"I will keep working along this live thread: {visible_focus}."
        )

    if scenario == "remote_workspace":
        base = "我们先把这一轮留在 VS Code remote 这条线上。" if chinese else (
            "I will keep this turn in the VS Code remote lane."
        )
    elif scenario == "debug_loop":
        base = "我们先把这一轮收束成一个可信的 debug loop。" if chinese else (
            "I will keep this turn inside one trustworthy debug loop."
        )
    elif scenario == "function_guidance":
        base = "我们先把这一轮留在 function guidance 这条线上。" if chinese else (
            "I will keep this turn in the function-guidance lane."
        )
    elif scenario == "project_adaptation":
        base = "我们先沿着现有项目 adaptation 这条线继续。" if chinese else (
            "I will keep this turn in the existing-project adaptation lane."
        )
    elif scenario == "principle":
        base = "我们先把这一轮锚定在当前原理和代码边界上。" if chinese else (
            "I will anchor this turn in the current principle and code boundary first."
        )
    else:
        base = (
            f"我们先回到 `{file_path}` 这一步。"
            if chinese and file_path
            else f"I will re-anchor on `{file_path}` first."
            if file_path
            else "我们先对齐这一步真正要完成的目标。"
            if chinese
            else "I want to re-anchor on the real goal of this step first."
        )

    if goal and scenario not in {"remote_workspace", "debug_loop", "function_guidance", "project_adaptation"}:
        goal_text = _trim_sentence(goal, 42 if chinese else 96)
        if chinese:
            return f"{base} 这一轮先服务这个目标：{goal_text}。"
        return f"{base} The immediate goal for this round is: {goal_text}."
    return base


def _scaffold_diagnosis(
    *,
    scenario: str,
    learner_signal: str,
    diagnostics_count: int,
    weak_spots: list[str],
    teaching_observations: list[str],
    summary: str,
    teaching_decision_reason: str,
    chinese: bool,
) -> str:
    visible_summary = _surface_context_text(summary, chinese=chinese)
    if visible_summary:
        return visible_summary if visible_summary.endswith(("。", ".", "!", "！", "?", "？")) else (
            f"{visible_summary}。"
            if chinese
            else f"{visible_summary}."
        )

    visible_reason = _surface_context_text(teaching_decision_reason, chinese=chinese)
    if visible_reason:
        return (
            f"这一轮先这样收束，是因为{visible_reason}。"
            if chinese
            else f"I am narrowing this turn this way because {visible_reason}."
        )

    if diagnostics_count > 0:
        return (
            f"当前文件里还有 {diagnostics_count} 条 diagnostics，先不要铺开，先恢复一条最小反馈链。"
            if chinese
            else f"There are still {diagnostics_count} diagnostics in the current file, so I want one minimal feedback loop before we widen anything."
        )

    if weak_spots:
        weak_spot = _trim_sentence(weak_spots[0], 28 if chinese else 72)
        return (
            f"这一轮先盯住最容易反复卡住的点：{weak_spot}。"
            if chinese
            else f"The riskiest recurring weak spot on this turn is: {weak_spot}."
        )

    if teaching_observations:
        observation = _surface_context_text(teaching_observations[0], chinese=chinese)
        if observation:
            return observation if observation.endswith(("。", ".", "!", "！", "?", "？")) else (
                f"{observation}。"
                if chinese
                else f"{observation}."
            )

    if learner_signal == "blocked":
        return (
            "你现在更需要的是先把范围压小，而不是再加更多解释。"
            if chinese
            else "Right now you need a smaller scope more than a larger explanation."
        )

    scenario_map = {
        "remote_workspace": (
            "先把工作区边界说稳，再决定 remote 里的下一步。",
            "The next useful move depends on proving the real workspace boundary first.",
        ),
        "debug_loop": (
            "先把 debug 收束到一个 pause point、一个 value 和一个验证动作上。",
            "The next useful move is to keep debugging inside one pause point, one observed value, and one verification move.",
        ),
        "function_guidance": (
            "先把函数 contract 锚定在一个 live call site 上，再扩解释。",
            "The next useful move is to anchor the function contract to one live call site before the explanation widens.",
        ),
        "project_adaptation": (
            "先分清稳定面和变更面，再动第一条 adaptation 边界。",
            "The next useful move is to separate the stable surface from the change surface before the first adaptation.",
        ),
        "principle": (
            "先把原理压回当前代码边界，再做一个最小验证。",
            "The next useful move is to pin the principle back to the live code boundary and test it once.",
        ),
    }
    zh, en = scenario_map.get(
        scenario,
        (
            "这一轮先落一个最小可验证动作，把线程继续接稳。",
            "The next useful move is one small verifiable action that keeps the thread continuous.",
        ),
    )
    return zh if chinese else en


def _scenario_step_text(
    scenario: str,
    *,
    file_path: str | None,
    weak_spots: list[str],
    chinese: bool,
) -> str:
    file_suffix = _file_suffix(file_path, chinese=chinese)
    weak_spot = _trim_sentence(weak_spots[0], 24 if chinese else 56) if weak_spots else ""

    if scenario == "remote_workspace":
        return (
            "判断当前工作区是 SSH、tunnels、dev container、WSL 还是 local，再确认文件实际在哪台机器上"
            if chinese
            else "identify whether the workspace is SSH, tunnels, dev container, WSL, or local, then prove which machine actually owns the files"
        )
    if scenario == "debug_loop":
        return (
            "只复现一次，在第一个有意义的 breakpoint 停下，检查一个 value、branch 或 stack frame"
            if chinese
            else "reproduce once, pause at the first meaningful breakpoint, and inspect one value, branch, or stack frame"
        )
    if scenario == "function_guidance":
        return (
            "先从一个 live call site 读这个函数，再用 hover、signature help、definition 把 contract 读稳"
            if chinese
            else "start from one live call site, then use hover, signature help, and definition until the contract stops moving"
        )
    if scenario == "project_adaptation":
        return (
            "写出必须保持不变的行为、必须改变的目标，以及要先碰的第一条边界"
            if chinese
            else "write down what must stay stable, what must change, and the first boundary you want to adapt"
        )
    if scenario == "principle":
        return (
            f"把当前原理钉在一处 live code boundary 上，再做一个最小验证{file_suffix}"
            if chinese
            else f"pin the current principle to one live code boundary and run one small verification{file_suffix}"
        )
    if scenario in {"review", "task", "next_task"}:
        return (
            f"先恢复一条最小反馈链{file_suffix}"
            if chinese
            else f"restore one minimal feedback loop{file_suffix}"
        )
    if scenario == "plan":
        return (
            "只保留一个最近的里程碑和一个验证点"
            if chinese
            else "keep only the nearest milestone and one verification point"
        )
    if weak_spot:
        return (
            f"先把 {weak_spot} 这一处压稳{file_suffix}"
            if chinese
            else f"stabilize {weak_spot} first{file_suffix}"
        )
    return (
        f"先落一个最小可验证切片{file_suffix}"
        if chinese
        else f"land one smallest verifiable slice{file_suffix}"
    )


def _scaffold_teaching_note(
    *,
    scenario: str,
    mode: str,
    recent_wins: list[str],
    weak_spots: list[str],
    due_reviews: list[dict[str, str]],
    review_rhythm: str,
    coach_defaults: dict[str, object],
    tone_name: str,
    verbosity_bias: str,
    chinese: bool,
) -> str:
    if recent_wins:
        recent_win = _surface_context_text(recent_wins[0], chinese=chinese) or recent_wins[0]
        return (
            f"你前面已经把这条线的一部分走通了：{recent_win}。这一轮继续沿着可验证的节奏走。"
            if chinese
            else f"You already proved part of this lane earlier: {recent_win}. I want to keep the same verifiable rhythm."
        )
    if weak_spots:
        weak_spot = _surface_context_text(weak_spots[0], chinese=chinese) or weak_spots[0]
        return (
            f"我会继续盯住 {weak_spot} 这个易错点，不让它在这一轮重新扩散。"
            if chinese
            else f"I will keep watching the recurring weak spot around {weak_spot} so it does not spread again on this turn."
        )
    if due_reviews:
        reason = _format_due_review_item(due_reviews[0])
        return (
            f"做完这一步后，我们再决定要不要把复习队列里的这条也收回来：{reason}。"
            if chinese
            else f"After this move, we can decide whether to pull this review thread back in: {reason}."
        )
    if review_rhythm and scenario == "plan":
        visible_rhythm = _surface_context_text(review_rhythm, chinese=chinese)
        if visible_rhythm:
            return (
                f"这一步完成后，再按现在的 review rhythm 接着走：{visible_rhythm}。"
                if chinese
                else f"After this move, continue with the current review rhythm: {visible_rhythm}."
            )
    if mode == "direct":
        return (
            "我会把解释压短一点，但会把为什么这一步重要和怎么验证说清楚。"
            if chinese
            else "I will keep the explanation short, but I will still make the reason and verification signal explicit."
        )
    if verbosity_bias == "short":
        return (
            "这一轮先保持短一点，只围绕当前这一条线说清楚。"
            if chinese
            else "I will keep this turn compact and stay on one line of coaching."
        )
    if tone_name:
        return (
            f"这一轮我会保持 {tone_name} 这类语气，但优先保证动作可验证。"
            if chinese
            else f"I will keep the {tone_name} tone, but I still want the move to stay verifiable."
        )
    if coach_defaults:
        return (
            "我会继续沿着你已经设定好的教练偏好来带，不额外打开新的面。"
            if chinese
            else "I will keep following your saved coaching defaults instead of opening a new lane."
        )
    return (
        "这一步的重点不是讲更多，而是把线程继续接稳。"
        if chinese
        else "The point of this turn is not more breadth; it is keeping the thread stable."
    )


def _file_suffix(file_path: str | None, chinese: bool = False) -> str:
    if not file_path:
        return ""
    if chinese:
        return f"，先从 `{file_path}` 开始"
    return f" in `{file_path}`"
