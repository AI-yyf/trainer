"""Coaching recovery overrides (§五十二: extracted from provider_service.py).

Recovery overrides rebuild a coach reply/summary/next-step after a provider
failure, timeout, empty reply, wrong-language corruption, or an unexpected
active-view detour. All coach-visible copy is authored here so the shipped
sources stay free of mojibake and mixed-script damage.
"""

from __future__ import annotations

import re
from typing import Any

from ..training.subject_taxonomy import classify_learning_subject
from .provider.redaction import _compact_text
from .provider.text import _looks_like_mojibake_text


def _localized_text(english: str, chinese: str, response_language: str | None) -> str:
    if _prefers_chinese(response_language) and _looks_like_mojibake_text(chinese):
        return (
            "\u5f53\u524d\u65e0\u6cd5\u5b89\u5168\u663e\u793a\u8fd9\u6761\u4e2d\u6587\u63d0\u793a\u3002"
            "\u8bf7\u68c0\u67e5 provider\u3001model \u548c\u8fde\u63a5\u540e\u91cd\u8bd5\u3002"
        )
    return chinese if _prefers_chinese(response_language) else english


def _agentic_resume_thread_text(
    summary: object | None,
    next_step: object | None,
    *,
    response_language: str | None,
) -> str:
    chinese = _prefers_chinese(response_language)
    summary_text = _compact_text(summary, 160) or ""
    next_step_text = _compact_text(next_step, 160) or ""
    if next_step_text:
        if chinese:
            for prefix in ("\u4e0b\u4e00\u6b65\uff1a", "\u4e0b\u4e00\u6b65:"):
                if next_step_text.startswith(prefix):
                    next_step_text = next_step_text[len(prefix) :].strip()
                    break
        else:
            lowered_next_step = next_step_text.casefold()
            for prefix in ("next step:", "next:"):
                if lowered_next_step.startswith(prefix):
                    next_step_text = next_step_text[len(prefix) :].strip()
                    break
    if not summary_text and not next_step_text:
        return ""
    if summary_text and summary_text[-1] not in ".!?。！？":
        summary_text = f"{summary_text}{'。' if chinese else '.'}"
    if summary_text and next_step_text:
        if chinese:
            return f"\u56de\u5230\u540c\u4e00\u6761\u6559\u7ec3\u7ebf\u7a0b\uff1a{summary_text}\n\n\u4e0b\u4e00\u6b65\uff1a{next_step_text}"
        return f"Resume the live thread around {summary_text} Next: {next_step_text}"
    if summary_text:
        if chinese:
            return f"\u56de\u5230\u540c\u4e00\u6761\u6559\u7ec3\u7ebf\u7a0b\uff1a{summary_text}"
        return f"Resume the live thread around {summary_text}"
    if chinese:
        return f"\u6cbf\u7740\u540c\u4e00\u6761\u7ebf\u7a0b\u7ee7\u7eed\u3002\u4e0b\u4e00\u6b65\uff1a{next_step_text}"
    return f"Resume the live thread. Next: {next_step_text}"


_GUIDED_DOMAIN_SCENARIOS = {
    "remote_workspace",
    "debug_loop",
    "function_guidance",
    "project_adaptation",
}


_STRUCTURED_ACTIVE_VIEWS = frozenset({"plan", "resources", "training", "settings"})


def _coaching_active_view_name(coach_context: dict[str, Any] | None) -> str:
    if not isinstance(coach_context, dict):
        return ""
    normalized = str(
        coach_context.get("active_view")
        or coach_context.get("activeView")
        or ""
    ).strip().lower()
    return normalized if normalized in _STRUCTURED_ACTIVE_VIEWS else ""


def _guided_domain_inference_coach_context(coach_context: dict[str, Any] | None) -> list[str]:
    if not isinstance(coach_context, dict):
        return []
    scenario = str(coach_context.get("scenario") or "").strip().lower()
    history_mode = str(coach_context.get("history_mode") or "").strip().lower()
    parts: list[str] = []
    if scenario:
        parts.append(scenario)
    if history_mode == "fresh_lane":
        return parts
    if scenario not in _GUIDED_DOMAIN_SCENARIOS:
        return parts
    for key in ("current_focus", "summary", "thread_summary", "thread_next_step"):
        value = coach_context.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    return parts


def _guided_domain_blob(
    message: str,
    *,
    current_file: dict[str, object] | None,
    coach_context: dict[str, Any] | None,
) -> str:
    parts: list[str] = [message]
    if current_file:
        for key in ("path", "language_id", "content"):
            value = current_file.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())
    parts.extend(_guided_domain_inference_coach_context(coach_context))
    return " ".join(parts).lower()


def _infer_guided_coaching_domain(
    message: str,
    *,
    current_file: dict[str, object] | None,
    coach_context: dict[str, Any] | None,
) -> str | None:
    blob = _guided_domain_blob(
        message,
        current_file=current_file,
        coach_context=coach_context,
    )
    if not blob:
        return None

    for domain in (
        "remote_workspace",
        "debug_loop",
        "function_guidance",
        "project_adaptation",
    ):
        if domain in blob:
            return domain

    remote_tokens = (
        "remote ssh",
        "remote workspace",
        "remote tunnel",
        "remote tunnels",
        "vscode remote",
        "dev container",
        "dev containers",
        "devcontainer",
        "wsl",
        "credential mode",
        "ssh",
        "远程",
        "远程开发",
        "远程工作区",
        "远程连接",
        "隧道",
        "容器",
        "凭据模式",
    )
    if any(token in blob for token in remote_tokens):
        return "remote_workspace"

    debug_tokens = (
        "debug",
        "launch.json",
        "breakpoint",
        "debug console",
        "watch expression",
        "stack trace",
        "step into",
        "step over",
        "exception breakpoint",
        "调试",
        "断点",
        "调用栈",
        "堆栈",
        "单步",
        "启动配置",
    )
    if any(token in blob for token in debug_tokens):
        return "debug_loop"

    function_tokens = (
        "signature help",
        "function hint",
        "parameter hint",
        "hover",
        "call site",
        "function call",
        "peek definition",
        "go to definition",
        "find all references",
        "intellisense",
        "autocomplete",
        "completion",
        "function contract",
        "typescript function",
        "ts function",
        "api call",
        "函数提示",
        "函数签名",
        "参数提示",
        "悬停",
        "查看定义",
        "转到定义",
        "引用",
        "补全",
    )
    if any(token in blob for token in function_tokens):
        return "function_guidance"

    project_tokens = (
        "existing project",
        "project adaptation",
        "adaptation",
        "migration",
        "migrate",
        "改造",
        "适配",
        "迁移",
        "接入现有项目",
    )
    if any(token in blob for token in project_tokens):
        return "project_adaptation"
    return None


def _prefers_chinese(response_language: str | None) -> bool:
    return bool(response_language and response_language.lower().startswith("zh"))


def _trim_sentence(text: str, limit: int) -> str:
    normalized = " ".join(text.split()).strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 3)].rstrip() + "..."


def _selection_function_symbol(selection_text: str) -> str | None:
    normalized = " ".join(str(selection_text or "").split())
    if not normalized:
        return None
    patterns = (
        r"\bfunction\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(",
        r"\b([A-Za-z_][A-Za-z0-9_]*)\s*[:=]\s*(?:async\s*)?\(",
        r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(",
    )
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if match:
            return match.group(1)
    return None


def _function_guidance_starter_reply_parts(
    coach_context: dict[str, Any] | None,
    *,
    chinese: bool,
) -> tuple[str, str]:
    if not isinstance(coach_context, dict):
        return "", ""
    starter = coach_context.get("function_guidance_starter")
    if not isinstance(starter, dict) or str(starter.get("status") or "").strip() != "ready":
        selection_text = str(coach_context.get("selection_text") or "").strip()
        file_path = _compact_text(coach_context.get("file_path"), 120)
        symbol = _selection_function_symbol(selection_text)
        if selection_text and file_path and symbol:
            if chinese:
                return (
                    f"我会先把这一轮锚定在当前文件 `{file_path}` 里的 `{symbol}` 上，再用 hover、signature help 和 definition 读稳它的 contract。",
                    f"下一步：留在 `{file_path}`，先围绕 `{symbol}` 说清 parameter contract 和 return contract，再决定要不要扩大解释。",
                )
            return (
                f"I will keep this anchored to `{symbol}` in the current file `{file_path}`, then use hover, signature help, and definition until the contract stops moving.",
                f"Next step: stay in `{file_path}`, read `{symbol}` from the current selection, and name the parameter contract and return contract before we widen the explanation.",
            )
        return "", ""
    call_site_path = _compact_text(starter.get("call_site_path"), 120) or "the prepared call site"
    definition_path = _compact_text(starter.get("definition_path"), 120) or "the prepared definition"
    symbol = (
        _compact_text(starter.get("definition_symbol"), 48)
        or _compact_text(starter.get("call_site_symbol"), 48)
        or "the prepared function"
    )
    if chinese:
        return (
            f"我会先把这一轮锚定在准备好的 live call site `{call_site_path}`，再用 hover、signature help 和 definition 读稳 `{symbol}` 的 contract。",
            f"下一步：打开 `{call_site_path}`，把光标放到 `{symbol}` 上，先看 hover 和 signature help，再跳到 `{definition_path}` 说清参数 contract 和返回 contract。",
        )
    return (
        f"I will keep this anchored to the prepared live call site in `{call_site_path}`, then use hover, signature help, and definition to read `{symbol}` with a stable contract.",
        f"Next step: open `{call_site_path}`, place the cursor on `{symbol}`, check hover and signature help, then jump to `{definition_path}` and name the parameter and return contract.",
    )


def _clean_guided_domain_empty_reply(
    domain: str | None,
    *,
    response_language: str | None,
    coach_context: dict[str, Any] | None = None,
) -> str:
    if domain == "remote_workspace":
        return _localized_text(
            (
                "Remote work gets easier once the workspace boundary stops moving. "
                "Stay in the VS Code remote lane for one more turn: identify whether this workspace is SSH, "
                "tunnels, dev container, WSL, or local, then verify which machine owns the files and whether "
                "the API key should stay local or remote. Return in 2 short lines: one real workspace label or "
                "path, and one sentence about the safe credential mode."
            ),
            (
                "先把工作区边界说清楚，remote 才会变简单。继续留在 VS Code remote 这条线上："
                "先确认当前是 SSH、tunnels、dev container、WSL 还是 local，再确认文件实际在哪台机器上，"
                "以及 API key 应该留在 local 还是 remote。请用 2 行回复：第一行给一个真实的工作区标签或路径，"
                "第二行给一个安全 credential mode 的判断。"
            ),
            response_language,
        )
    if domain == "debug_loop":
        return _localized_text(
            (
                "Keep this in one trustworthy VS Code debug loop. Reproduce once, pause at the first meaningful "
                "state change, and inspect one value, branch, or stack frame before widening the story. Return in "
                "2 short lines: where you will pause first, and what single thing you expect to inspect there."
            ),
            (
                "先把这一轮收束成一个可信的 VS Code debug loop。先复现一次，在第一个有意义的 state change 停下，"
                "再检查一个 value、branch 或 stack frame，不要先把叙述铺开。请用 2 行回复：第一行写你准备停在哪里，"
                "第二行写你准备先检查哪一个点。"
            ),
            response_language,
        )
    if domain == "function_guidance":
        starter_note, starter_next_step = _function_guidance_starter_reply_parts(
            coach_context,
            chinese=_prefers_chinese(response_language),
        )
        if starter_note or starter_next_step:
            return "\n\n".join(part for part in (starter_note, starter_next_step) if part.strip())
        return _localized_text(
            (
                "Keep this in the function-guidance lane. Start from one live call site, then use hover, "
                "signature help, and definition in that order until the contract stops moving. Return in 2 short "
                "lines: the function name, and the call site or evidence that proves what the function expects."
            ),
            (
                "先把这一轮留在 function guidance 这条线上。先从一个 live call site 开始，再按顺序用 hover、"
                "signature help、definition 把 contract 读稳。请用 3 行回复：第一行写函数名，第二行写你看的 "
                "call site，第三行写能证明它期望什么的 contract 证据。"
            ),
            response_language,
        )
    if domain == "project_adaptation":
        return _localized_text(
            (
                "Keep this in the existing-project adaptation lane. First separate what must stay stable from what "
                "must change, then land one narrow adaptation before widening scope. Return in 3 short lines: one "
                "stable behavior you must keep, one thing that must change, and the first boundary you want to adapt."
            ),
            (
                "先把这一轮留在现有项目 adaptation 这条线上。先分清哪些必须保持不变、哪些必须改变，"
                "再先落一个窄范围 adaptation，不要一开始就铺大。请用 3 行回复：第一行写必须保持不变的行为，"
                "第二行写必须改变的目标，第三行写你想先适配的第一条边界。"
            ),
            response_language,
        )
    return ""


def _clean_guided_domain_empty_reply_override(
    domain: str | None,
    *,
    response_language: str | None,
    coach_context: dict[str, Any] | None = None,
) -> dict[str, str] | None:
    if domain == "remote_workspace":
        return {
            "summary": _localized_text(
                "The provider returned no visible answer, so this turn stays in the VS Code remote lane.",
                "provider 没有返回可见内容，所以我先把这一轮继续留在 VS Code remote 这条线上。",
                response_language,
            ),
            "next_step": _localized_text(
                "Return one real workspace label or path and one sentence about the safe credential mode.",
                "请返回一个真实的工作区标签或路径，再补一句安全 credential mode 的判断。",
                response_language,
            ),
            "teaching_note": _localized_text(
                "Keep the lesson grounded in the real workspace boundary before widening the remote story.",
                "先把真实工作区边界说稳，再展开 remote 细节。",
                response_language,
            ),
        }
    if domain == "debug_loop":
        return {
            "summary": _localized_text(
                "The provider returned no visible answer, so this turn stays in the VS Code debug lane.",
                "provider 没有返回可见内容，所以我先把这一轮收束在 VS Code debug 这条线上。",
                response_language,
            ),
            "next_step": _localized_text(
                "Tell me where you will pause first and which single value, branch, or stack frame you expect to inspect there.",
                "请告诉我你准备先停在哪里，以及你准备先检查哪一个 value、branch 或 stack frame。",
                response_language,
            ),
            "teaching_note": _localized_text(
                "Pause at one meaningful state change before widening the debug story.",
                "先在一个有意义的 state change 停下，再展开 debug 叙述。",
                response_language,
            ),
        }
    if domain == "function_guidance":
        starter_note, starter_next_step = _function_guidance_starter_reply_parts(
            coach_context,
            chinese=_prefers_chinese(response_language),
        )
        if starter_note or starter_next_step:
            return {
                "summary": starter_note or "",
                "next_step": starter_next_step or "",
                "teaching_note": starter_note or "",
            }
        return {
            "summary": _localized_text(
                "The provider returned no visible answer, so this turn stays in the function-guidance lane.",
                "provider 没有返回可见内容，所以我先把这一轮留在 function guidance 这条线上。",
                response_language,
            ),
            "next_step": _localized_text(
                "Return the function name and one call site that proves what the function expects.",
                "请返回函数名、一个 call site，以及能证明它期望什么的 contract 证据。",
                response_language,
            ),
            "teaching_note": _localized_text(
                "Keep the contract anchored to one live call site before widening the explanation.",
                "先把 contract 锚定在一个 live call site 上，再展开解释。",
                response_language,
            ),
        }
    if domain == "project_adaptation":
        return {
            "summary": _localized_text(
                "The provider returned no visible answer, so this turn stays in the existing-project adaptation lane.",
                "provider 没有返回可见内容，所以我先把这一轮留在现有项目 adaptation 这条线上。",
                response_language,
            ),
            "next_step": _localized_text(
                "Tell me what must stay stable, what must change, and the first boundary you want to adapt.",
                "请告诉我什么必须保持不变、什么必须改变，以及你想先适配的第一条边界。",
                response_language,
            ),
            "teaching_note": _localized_text(
                "Separate stable behavior from change scope before widening the adaptation plan.",
                "先分清稳定面和变更面，再扩大 adaptation 计划。",
                response_language,
            ),
        }
    return None


def _timeout_focus_seed(
    message: str,
    *,
    coach_context: dict[str, Any] | None,
    response_language: str | None,
) -> str:
    chinese = response_language == "zh-CN"
    candidates: list[object] = []
    if isinstance(coach_context, dict):
        scenario = str(coach_context.get("scenario") or "").strip().lower()
        history_mode = str(coach_context.get("history_mode") or "").strip().lower()
        prefer_message_first = history_mode == "fresh_lane" or scenario in {"", "general"}
        if prefer_message_first:
            candidates.append(message)
        candidates.extend(
            [
                coach_context.get("current_focus"),
                coach_context.get("currentFocus"),
                coach_context.get("thread_summary"),
                coach_context.get("threadSummary"),
                coach_context.get("summary"),
            ]
        )
        if not prefer_message_first:
            candidates.append(message)
    else:
        candidates.append(message)
    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        cleaned = " ".join(candidate.strip().split())
        if not cleaned:
            continue
        return _trim_sentence(cleaned, 28 if chinese else 96)
    return ""


def _looks_code_or_tooling_focus(text: str) -> bool:
    lowered = text.strip().lower()
    if not lowered:
        return False
    return classify_learning_subject(lowered).family == "code"


def _general_recovery_focus_and_subject(
    message: str,
    *,
    coach_context: dict[str, Any] | None,
    response_language: str | None,
):
    focus = _timeout_focus_seed(
        message,
        coach_context=coach_context,
        response_language=response_language,
    )
    if not focus:
        return None, None
    subject = classify_learning_subject(
        focus,
        message,
    )
    return focus, subject


def _build_active_view_recovery_override(
    *,
    active_view: str | None,
    response_language: str | None,
    reason: str,
) -> dict[str, str] | None:
    normalized = str(active_view or "").strip().lower()
    if normalized not in _STRUCTURED_ACTIVE_VIEWS:
        return None

    if reason == "timeout":
        summary_prefix = (
            "The provider timed out before it could finish",
            "provider 在完成前超时了",
        )
        reply_prefix = (
            "The provider timed out before finishing",
            "provider 还没讲完就超时了",
        )
    elif reason == "language_corruption":
        summary_prefix = (
            "The provider reply was not trustworthy enough to use directly",
            "这次回答显示有问题，不能直接拿来用",
        )
        reply_prefix = summary_prefix
    elif reason == "reanchor":
        summary_prefix = ("", "")
        reply_prefix = ("", "")
    else:
        summary_prefix = (
            "The provider became unstable on this turn",
            "这一轮 provider 链路不稳定",
        )
        reply_prefix = (
            "The provider became unstable before finishing",
            "provider 还没讲完就变得不稳定了",
        )

    view_copy: dict[str, dict[str, str]] = {
        "plan": {
            "lane_en": "the Plan lane",
            "lane_zh": "Plan 视图",
            "unit_en": "plan move",
            "unit_zh": "计划动作",
            "next_en": (
                "Stay inside the formal plan lane and compress the thread into four short items: "
                "current stage, why now, the smallest next step, and the verify method. "
                "Do not silently mutate the formal plan."
            ),
            "next_zh": (
                "先留在正式计划这条主线里，把这一轮压成四项：当前阶段、why now、最小 next step、"
                "verify method。普通聊天不要静默改正式计划。"
            ),
            "note_en": "Keep the plan truthful, compact, and evidence-first while the provider recovers.",
            "note_zh": "先保住计划的真实性、紧凑度和 evidence 导向，再等 provider 恢复。",
        },
        "resources": {
            "lane_en": "the Resources lane",
            "lane_zh": "Resources 视图",
            "unit_en": "resource move",
            "unit_zh": "资料动作",
            "next_en": (
                "Stay inside the resource lane and do one small library pass: locate the most relevant material, "
                "decide which sandbox folder should receive it, then describe how it should be organized into "
                "sources, knowledge, and cards."
            ),
            "next_zh": (
                "先留在资料库这条主线里，做一轮很小的整理：定位最相关资料、决定该放进资料库里的哪个分组目录，"
                "再说明如何整理成 sources、knowledge、cards。"
            ),
            "note_en": "Keep provenance, sandbox boundaries, and the next transformation path visible.",
            "note_zh": "先保住 provenance、沙箱边界和下一步转化路径的清晰度。",
        },
        "training": {
            "lane_en": "the Training lane",
            "lane_zh": "Training 视图",
            "unit_en": "Learn-first training move",
            "unit_zh": "Learn-first 训练动作",
            "next_en": (
                "Stay inside Learn -> Try -> Verify -> Reflect -> Return. "
                "Do not start with an exam. Land one single card that states why now, the problem, "
                "the learner deliverable, the verify method, and what to bring back."
            ),
            "next_zh": (
                "先留在 Learn -> Try -> Verify -> Reflect -> Return 这条训练闭环里，不要一上来考试。"
                "先落一张单卡，至少说清 why now、problem、deliverable、verify、return。"
            ),
            "note_en": "Keep one dominant card and preserve the learn-first loop while the provider recovers.",
            "note_zh": "先保住单卡优先和 learn-first 的训练闭环，再等 provider 恢复。",
        },
        "settings": {
            "lane_en": "the Settings lane",
            "lane_zh": "Settings 视图",
            "unit_en": "settings check",
            "unit_zh": "设置检查",
            "next_en": (
                "Stay inside the configuration lane and verify the current provider, model, protocol, and runtime truth "
                "before resuming the work."
            ),
            "next_zh": "先留在配置这条主线里，核对 provider、model、protocol 和 runtime 真相，再回来续上这一轮。",
            "note_en": "Keep capability truth explicit before resuming teaching work.",
            "note_zh": "先把能力真相说清楚，再恢复教学动作。",
        },
    }
    spec = view_copy.get(normalized)
    if spec is None:
        return None

    next_step = _localized_text(spec["next_en"], spec["next_zh"], response_language)
    teaching_note = _localized_text(spec["note_en"], spec["note_zh"], response_language)
    if reason == "reanchor":
        summary = _localized_text(
            f"I kept this turn inside {spec['lane_en']}.",
            f"这一轮我继续留在 {spec['lane_zh']} 里。",
            response_language,
        )
        reply = _localized_text(
            f"I will keep this turn inside {spec['lane_en']} with one smaller {spec['unit_en']}.\n\nNext step: {next_step}",
            f"这一轮我先在 {spec['lane_zh']} 里用一个更小的{spec['unit_zh']}把它接住。\n\n下一步：{next_step}",
            response_language,
        )
    else:
        summary = _localized_text(
            f"{summary_prefix[0]}, so I kept this turn inside {spec['lane_en']}.",
            f"{summary_prefix[1]}，所以我先把这一轮继续留在 {spec['lane_zh']} 里。",
            response_language,
        )
        reply = _localized_text(
            f"{reply_prefix[0]}, so I will keep the work alive inside {spec['lane_en']} with one smaller {spec['unit_en']}.\n\nNext step: {next_step}",
            f"{reply_prefix[1]}，所以我先在 {spec['lane_zh']} 里用一个更小的{spec['unit_zh']}把这轮工作接住。\n\n下一步：{next_step}",
            response_language,
        )

    return {
        "summary": summary,
        "next_step": next_step,
        "teaching_note": teaching_note,
        "reply": reply,
    }


def _general_theory_recovery_next_step(
    focus: str,
    *,
    subtype: str,
    response_language: str | None,
) -> str:
    if subtype == "derivation":
        return _localized_text(
            f"Write one tiny worked step or mini-derivation about {focus}, name the rule that justifies it, then bring back one check that proves it.",
            f"先围绕 {focus} 写出一个很小的步骤或小推导，说明支撑它的规则，再带回一个证明它成立的检查结果。",
            response_language,
        )
    if subtype == "writing":
        return _localized_text(
            f"Write or revise one sentence about {focus}, name one nearby alternative you rejected, then bring back the tone or meaning difference it proves.",
            f"先围绕 {focus} 写一句或改一句，说明你放弃了哪个相邻表达，再带回它证明了什么语气或含义差别。",
            response_language,
        )
    if subtype == "memorization":
        return _localized_text(
            f"Turn {focus} into one tiny fact cluster, do one closed-book recall, then bring back what you remembered versus missed.",
            f"先把 {focus} 收成一小组事实点，做一次闭卷回忆，再带回你记住了什么、漏了什么。",
            response_language,
        )
    if subtype == "reading":
        return _localized_text(
            f"Make one narrow claim about {focus}, support it with one real excerpt or detail, then bring back the evidence link.",
            f"先围绕 {focus} 提出一个很窄的判断，用一个真实片段或细节支撑它，再带回证据和判断之间的联系。",
            response_language,
        )
    return _localized_text(
        f"Explain {focus} in one short example, boundary, or contrast, then bring back one check that proves the explanation holds.",
        f"先用一个短例子、边界或对比把 {focus} 讲清楚，再带回一个能证明这段解释站得住的检查结果。",
        response_language,
    )


def _build_general_theory_recovery_override(
    message: str,
    *,
    coach_context: dict[str, Any] | None,
    response_language: str | None,
    reason: str,
) -> dict[str, str] | None:
    focus, subject = _general_recovery_focus_and_subject(
        message,
        coach_context=coach_context,
        response_language=response_language,
    )
    if not focus or subject is None or subject.family == "code":
        return None

    next_step = _general_theory_recovery_next_step(
        focus,
        subtype=subject.subtype,
        response_language=response_language,
    )
    if reason == "timeout":
        summary = _localized_text(
            "The provider timed out before it could finish, so I kept the lesson on the same learning thread.",
            "provider 还没讲完就 timeout 了，所以我先把这次学习留在同一条学习主线上。",
            response_language,
        )
        teaching_note = _localized_text(
            "When the provider is slow, keep the lesson alive with one Learn -> Try -> Verify micro-loop.",
            "当 provider 变慢时，先用一个 Learn -> Try -> Verify 的微循环把教学接住。",
            response_language,
        )
        reply = _localized_text(
            (
                "The provider timed out before finishing, so I will keep the lesson alive with one tiny Learn-first move.\n\n"
                f"Next step: {next_step}"
            ),
            (
                "provider 还没讲完就 timeout 了，所以我先用一个很小的 Learn-first 动作把这次学习接住。\n\n"
                f"下一步：{next_step}"
            ),
            response_language,
        )
    elif reason == "language_corruption":
        summary = _localized_text(
            "The provider reply was not trustworthy enough to use directly, so I kept the lesson on the same learning thread.",
            "这次回答显示有问题，不能直接拿来用，所以我先把你的问题留在当前进度里。",
            response_language,
        )
        teaching_note = _localized_text(
            "When the visible reply is corrupted or in the wrong language, keep the lesson alive with one Learn -> Try -> Verify micro-loop in the requested language.",
            "当回答显示异常或语言不对时，先用你选择的语言补上一小步说明和检查。",
            response_language,
        )
        reply = _localized_text(
            (
                "The provider reply was not trustworthy enough to use directly, so I will keep the lesson alive with one tiny Learn-first move.\n\n"
                "Trainer will not pretend this broken input is normal teaching, because the model never really saw the original sentence.\n\n"
                f"Next step: {next_step}"
            ),
            (
                "这次回答显示有问题，不能直接拿来用，所以我先用一个很小的步骤把当前问题接住。\n\n"
                "为了避免误导你，我不会把这段异常内容当成正常回答。\n\n"
                f"下一步：{next_step}"
            ),
            response_language,
        )
    else:
        summary = _localized_text(
            "The provider became unstable before it could finish, so I kept the lesson on the same learning thread.",
            "这次 provider 在讲完前变得不稳定，所以我先把这次学习留在同一条学习主线上。",
            response_language,
        )
        teaching_note = _localized_text(
            "When the provider path is unstable, keep the lesson alive with one Learn -> Try -> Verify micro-loop.",
            "当 provider 链路不稳定时，先用一个 Learn -> Try -> Verify 的微循环把教学接住。",
            response_language,
        )
        reply = _localized_text(
            (
                "The provider broke before finishing, so I will keep the lesson alive with one tiny Learn-first move.\n\n"
                f"Next step: {next_step}"
            ),
            (
                "provider 在讲完前出错了，所以我先用一个很小的 Learn-first 动作把这次学习接住。\n\n"
                f"下一步：{next_step}"
            ),
            response_language,
        )

    return {
        "summary": summary,
        "next_step": next_step,
        "teaching_note": teaching_note,
        "reply": reply,
    }


def _build_general_timeout_teaching_override(
    message: str,
    *,
    coach_context: dict[str, Any] | None,
    response_language: str | None,
) -> dict[str, str] | None:
    return _build_general_theory_recovery_override(
        message,
        coach_context=coach_context,
        response_language=response_language,
        reason="timeout",
    )

    focus = _timeout_focus_seed(
        message,
        coach_context=coach_context,
        response_language=response_language,
    )
    if not focus or _looks_code_or_tooling_focus(focus):
        return None

    next_step = _localized_text(
        f"Write one tiny explanation, worked step, or example about {focus}, then bring back one check that proves it.",
        f"先围绕「{focus}」写出一小步解释、例题或推导，再带回一个最小验证结果。",
        response_language,
    )
    teaching_note = _localized_text(
        "When the provider is slow, keep the lesson alive with one Learn-first move and one tiny verification step.",
        "当 provider 较慢时，先用一个 Learn-first 动作和一个最小验证步骤把教学线程接住。",
        response_language,
    )
    summary = _localized_text(
        "The provider timed out before it could finish, so I kept the lesson on the same learning thread.",
        "provider 还没讲完就 timeout 了，所以我先把这次学习继续留在同一条学习主线上。",
        response_language,
    )
    reply = _localized_text(
        (
            "The provider timed out before finishing, so I will keep the lesson alive with one tiny Learn-first move.\n\n"
            f"Next step: {next_step}"
        ),
        (
            "provider 还没讲完就 timeout 了，所以我先用一个很小的 Learn-first 动作把这次学习接住。\n\n"
            f"下一步：{next_step}"
        ),
        response_language,
    )
    return {
        "summary": summary,
        "next_step": next_step,
        "teaching_note": teaching_note,
        "reply": reply,
    }


def _build_timeout_recovery_override(
    message: str,
    *,
    current_file: dict[str, object] | None,
    coach_context: dict[str, Any] | None,
    response_language: str | None,
) -> dict[str, object]:
    domain = _infer_guided_coaching_domain(
        message,
        current_file=current_file,
        coach_context=coach_context,
    )
    guided_reply = _clean_guided_domain_empty_reply(
        domain,
        response_language=response_language,
        coach_context=coach_context,
    ).strip()
    domain_override = _clean_guided_domain_empty_reply_override(
        domain,
        response_language=response_language,
        coach_context=coach_context,
    )
    active_view = _coaching_active_view_name(coach_context)
    active_view_override = (
        _build_active_view_recovery_override(
            active_view=active_view,
            response_language=response_language,
            reason="timeout",
        )
        if active_view
        else None
    )
    if isinstance(active_view_override, dict):
        summary = str(active_view_override.get("summary") or "").strip()
        next_step = str(active_view_override.get("next_step") or "").strip()
        teaching_note = str(active_view_override.get("teaching_note") or "").strip()
        reply = str(active_view_override.get("reply") or "").strip()
        resume_thread = _agentic_resume_thread_text(
            summary,
            next_step,
            response_language=response_language,
        )
        return {
            "summary": summary,
            "next_step": next_step,
            "blocker": summary,
            "teaching_note": teaching_note,
            "resume_thread": resume_thread,
            "reply": reply,
            "stop_reason": "timeout",
            "fell_back": True,
        }
    summary_map: dict[str | None, tuple[str, str]] = {
        "remote_workspace": (
            "The provider timed out before it could finish, so I kept this turn in the VS Code remote lane.",
            "provider 在完成前超时了，所以我先把这一轮继续留在 VS Code remote 这条主线上。",
        ),
        "debug_loop": (
            "The provider timed out before it could finish, so I kept this turn inside one trustworthy debug loop.",
            "provider 在完成前超时了，所以我先把这一轮继续收束在一个可信的 debug loop 里。",
        ),
        "function_guidance": (
            "The provider timed out before it could finish, so I kept this turn in the function-guidance lane.",
            "provider 在完成前超时了，所以我先把这一轮继续留在 function guidance 这条主线上。",
        ),
        "project_adaptation": (
            "The provider timed out before it could finish, so I kept this turn in the existing-project adaptation lane.",
            "provider 在完成前超时了，所以我先把这一轮继续留在 existing-project adaptation 这条主线上。",
        ),
    }
    default_summary = _localized_text(
        "The provider timed out before it could finish, so I kept this turn anchored to the same coaching lane.",
        "provider 在完成前超时了，所以我先把这一轮继续锚定在同一条教学主线上。",
        response_language,
    )
    summary = _localized_text(
        *(summary_map.get(domain, ("", ""))),
        response_language,
    ).strip() or default_summary
    general_timeout_override = (
        _build_general_timeout_teaching_override(
            message,
            coach_context=coach_context,
            response_language=response_language,
        )
        if domain in {"", "general", None}
        else None
    )
    if isinstance(general_timeout_override, dict):
        summary = str(general_timeout_override.get("summary") or "").strip() or summary
    next_step = (
        str(domain_override.get("next_step") or "").strip()
        if isinstance(domain_override, dict)
        else ""
    )
    if not next_step and isinstance(general_timeout_override, dict):
        next_step = str(general_timeout_override.get("next_step") or "").strip()
    if not next_step:
        next_step = _localized_text(
            "Return with the next local, visible, verifiable move on this same lane.",
            "请直接带回这条主线上下一个本地可见、可验证的小动作。",
            response_language,
        )
    teaching_note = (
        str(domain_override.get("teaching_note") or "").strip()
        if isinstance(domain_override, dict)
        else ""
    )
    if not teaching_note and isinstance(general_timeout_override, dict):
        teaching_note = str(general_timeout_override.get("teaching_note") or "").strip()
    if not teaching_note:
        teaching_note = _localized_text(
            "Keep the lesson grounded in one small local move while the provider path is slow.",
            "当 provider 链路偏慢时，先把教学继续锚定在一个本地的小动作上。",
            response_language,
        )
    resume_thread = _agentic_resume_thread_text(
        summary,
        next_step,
        response_language=response_language,
    )
    reply = guided_reply or (
        str(general_timeout_override.get("reply") or "").strip()
        if isinstance(general_timeout_override, dict)
        else ""
    ) or _localized_text(
        (
            "I kept this turn on the same coaching lane instead of letting the timeout break the lesson.\n\n"
            f"Next step: {next_step}"
        ),
        (
            "我先把这一轮继续留在同一条教学主线上，不让 timeout 把这次学习打断。\n\n"
            f"下一步：{next_step}"
        ),
        response_language,
    )
    return {
        "summary": summary,
        "next_step": next_step,
        "blocker": summary,
        "teaching_note": teaching_note,
        "resume_thread": resume_thread,
        "reply": reply,
        "stop_reason": "timeout",
        "fell_back": True,
    }


def _provider_error_recovery_kind(error_detail: str | None) -> str:
    normalized = str(error_detail or "").strip().lower()
    if not normalized:
        return "unstable"

    overloaded_markers = (
        "high load",
        "rate limit",
        "too many requests",
        "status 429",
        "status 529",
        "overloaded",
    )
    if any(marker in normalized for marker in overloaded_markers):
        return "overloaded"

    auth_markers = (
        "unauthorized",
        "forbidden",
        "permission",
        "access denied",
        "invalid api key",
        "missing api key",
        "status 401",
        "status 403",
    )
    if any(marker in normalized for marker in auth_markers):
        return "auth"

    config_markers = (
        "model not found",
        "unsupported model",
        "protocol",
        "malformed",
        "status 404",
        "status 400",
    )
    if any(marker in normalized for marker in config_markers):
        return "config"

    return "unstable"


def _build_provider_error_recovery_override(
    message: str,
    *,
    current_file: dict[str, object] | None,
    coach_context: dict[str, Any] | None,
    response_language: str | None,
    error_detail: str | None = None,
) -> dict[str, object]:
    domain = _infer_guided_coaching_domain(
        message,
        current_file=current_file,
        coach_context=coach_context,
    )
    guided_reply = _clean_guided_domain_empty_reply(
        domain,
        response_language=response_language,
        coach_context=coach_context,
    ).strip()
    domain_override = _clean_guided_domain_empty_reply_override(
        domain,
        response_language=response_language,
        coach_context=coach_context,
    )
    active_view = _coaching_active_view_name(coach_context)
    active_view_override = (
        _build_active_view_recovery_override(
            active_view=active_view,
            response_language=response_language,
            reason="provider_error",
        )
        if active_view
        else None
    )
    issue_kind = _provider_error_recovery_kind(error_detail)

    if issue_kind == "auth":
        summary = _localized_text(
            "The provider rejected this turn, so Trainer cannot continue on this connection yet.",
            "这一轮 provider 拒绝了请求，所以 Trainer 还不能沿着这条连接继续。",
            response_language,
        )
        next_step = _localized_text(
            "Check the API key, model access, and provider permissions, then resend this same turn.",
            "先检查 API key、model 访问权限和 provider 权限，再重发这一轮。",
            response_language,
        )
        teaching_note = _localized_text(
            "Keep the current coaching lane, but restore the connection truth before continuing.",
            "先保留当前教学主线，但继续之前必须先恢复连接真相。",
            response_language,
        )
        reply = _localized_text(
            "This turn was blocked by the provider connection, so I will not pretend it completed.\n\n"
            "Fix the connection first, then continue the same coaching thread.",
            "这一轮被 provider 连接拦住了，所以我不会假装它已经完成。\n\n"
            "先修好连接，再继续同一条教学主线。",
            response_language,
        )
    elif issue_kind == "config":
        summary = _localized_text(
            "This provider configuration blocked the turn before Trainer could finish it.",
            "这一轮被当前 provider 配置拦住了，Trainer 还没法把它完整带完。",
            response_language,
        )
        next_step = _localized_text(
            "Check the protocol, model name, and endpoint compatibility, then retry this same turn.",
            "先检查 protocol、model 名称和 endpoint 兼容性，再重试这一轮。",
            response_language,
        )
        teaching_note = _localized_text(
            "Keep the live coaching lane, but repair the configuration truth before continuing.",
            "先保留当前教学主线，但继续之前必须先修好配置真相。",
            response_language,
        )
        reply = _localized_text(
            "This turn hit a provider configuration problem, so I will not pretend the lesson completed.\n\n"
            "Repair the configuration first, then continue the same coaching thread.",
            "这一轮碰到了 provider 配置问题，所以我不会假装这次教学已经完成。\n\n"
            "先修好配置，再继续同一条教学主线。",
            response_language,
        )
    else:
        summary_map: dict[str | None, tuple[str, str]] = {
            "remote_workspace": (
                "The provider was slow or overloaded on this turn, so I kept the lesson in the VS Code remote lane.",
                "这一轮 provider 负载偏高或链路不稳，所以我先把教学继续留在 VS Code remote 这条线上。",
            ),
            "debug_loop": (
                "The provider was slow or overloaded on this turn, so I kept the lesson inside one trustworthy debug loop.",
                "这一轮 provider 负载偏高或链路不稳，所以我先把教学继续收束在一个可信的 debug loop 里。",
            ),
            "function_guidance": (
                "The provider was slow or overloaded on this turn, so I kept the lesson in the function-guidance lane.",
                "这一轮 provider 负载偏高或链路不稳，所以我先把教学继续留在 function guidance 这条线上。",
            ),
            "project_adaptation": (
                "The provider was slow or overloaded on this turn, so I kept the lesson in the existing-project adaptation lane.",
                "这一轮 provider 负载偏高或链路不稳，所以我先把教学继续留在现有项目 adaptation 这条线上。",
            ),
        }
        default_summary = _localized_text(
            "The provider became unstable on this turn, so I kept the lesson anchored to the same coaching lane.",
            "这一轮 provider 链路不稳定，所以我先把教学继续锚定在同一条主线上。",
            response_language,
        )
        general_override = _build_general_theory_recovery_override(
            message,
            coach_context=coach_context,
            response_language=response_language,
            reason="provider_error",
        )
        if isinstance(active_view_override, dict):
            summary = str(active_view_override.get("summary") or "").strip() or default_summary
            next_step = str(active_view_override.get("next_step") or "").strip()
            teaching_note = str(active_view_override.get("teaching_note") or "").strip()
            reply = str(active_view_override.get("reply") or "").strip()
        else:
            summary = (
                _localized_text(*(summary_map.get(domain, ("", ""))), response_language).strip()
                or default_summary
            )
            if isinstance(general_override, dict):
                summary = str(general_override.get("summary") or "").strip() or summary
            next_step = (
                str(domain_override.get("next_step") or "").strip()
                if isinstance(domain_override, dict)
                else ""
            )
            if not next_step and isinstance(general_override, dict):
                next_step = str(general_override.get("next_step") or "").strip()
            if not next_step:
                next_step = _localized_text(
                    "Return with the next visible, local, verifiable move on this same lane.",
                    "请直接带回这条主线上下一个本地可见、可验证的小动作。",
                    response_language,
                )
            teaching_note = (
                str(domain_override.get("teaching_note") or "").strip()
                if isinstance(domain_override, dict)
                else ""
            )
            if not teaching_note and isinstance(general_override, dict):
                teaching_note = str(general_override.get("teaching_note") or "").strip()
            if not teaching_note:
                teaching_note = _localized_text(
                    "Keep the lesson narrow and verifiable while the provider path settles.",
                    "在 provider 链路恢复稳定前，先把教学收窄成可验证的小动作。",
                    response_language,
                )
            reply = guided_reply or (
                str(general_override.get("reply") or "").strip()
                if isinstance(general_override, dict)
                else ""
            ) or _localized_text(
                (
                    "I kept this turn on the same coaching lane instead of letting the provider glitch break the lesson.\n\n"
                    f"Next step: {next_step}"
                ),
                (
                    "我先把这一轮继续留在同一条教学主线上，不让 provider 抖动把这次学习打断。\n\n"
                    f"下一步：{next_step}"
                ),
                response_language,
            )

    resume_thread = _agentic_resume_thread_text(
        summary,
        next_step,
        response_language=response_language,
    )
    return {
        "summary": summary,
        "next_step": next_step,
        "blocker": summary,
        "teaching_note": teaching_note,
        "resume_thread": resume_thread,
        "reply": reply,
        "stop_reason": "provider_error",
        "fell_back": True,
    }


def _build_language_corruption_recovery_override(
    message: str,
    *,
    current_file: dict[str, object] | None,
    coach_context: dict[str, Any] | None,
    response_language: str | None,
) -> dict[str, object] | None:
    domain = _infer_guided_coaching_domain(
        message,
        current_file=current_file,
        coach_context=coach_context,
    )
    guided_reply = _clean_guided_domain_empty_reply(
        domain,
        response_language=response_language,
        coach_context=coach_context,
    ).strip()
    domain_override = _clean_guided_domain_empty_reply_override(
        domain,
        response_language=response_language,
        coach_context=coach_context,
    )
    active_view = _coaching_active_view_name(coach_context)
    active_view_override = (
        _build_active_view_recovery_override(
            active_view=active_view,
            response_language=response_language,
            reason="language_corruption",
        )
        if active_view
        else None
    )
    general_override = _build_general_theory_recovery_override(
        message,
        coach_context=coach_context,
        response_language=response_language,
        reason="language_corruption",
    )
    if (
        not guided_reply
        and not isinstance(domain_override, dict)
        and not isinstance(general_override, dict)
    ):
        summary = _localized_text(
            "The reply was not readable, so I did not use it as your answer.",
            "这条回复没有读清，我不会把它当作答案。",
            response_language,
        )
        next_step = _localized_text(
            "Please send the same question again.",
            "请把刚才的问题再发一次。",
            response_language,
        )
        reply = _localized_text(
            "I could not read that reply. Please send the same question again.",
            "这条回复没有读清。请把刚才的问题再发一次。",
            response_language,
        )
        return {
            "summary": summary,
            "next_step": next_step,
            "teaching_note": "",
            "reply": reply,
            "resume_thread": _agentic_resume_thread_text(
                summary,
                next_step,
                response_language=response_language,
            ),
            "stop_reason": "language_corruption_recovered",
            "fell_back": True,
            "scenario": domain or "general",
        }

    if isinstance(active_view_override, dict):
        summary = str(active_view_override.get("summary") or "").strip()
        next_step = str(active_view_override.get("next_step") or "").strip()
        teaching_note = str(active_view_override.get("teaching_note") or "").strip()
        reply = str(active_view_override.get("reply") or "").strip()
    else:
        summary = _localized_text(
            "The provider reply came back degraded, so I kept this lesson moving with a local recovery scaffold.",
            "这次回答显示有问题，我先用一个可靠的小步骤把这轮学习接住。",
            response_language,
        )
        if isinstance(general_override, dict):
            summary = str(general_override.get("summary") or "").strip() or summary
        next_step = (
            str(domain_override.get("next_step") or "").strip()
            if isinstance(domain_override, dict)
            else ""
        )
        if not next_step and isinstance(general_override, dict):
            next_step = str(general_override.get("next_step") or "").strip()
        teaching_note = (
            str(domain_override.get("teaching_note") or "").strip()
            if isinstance(domain_override, dict)
            else ""
        )
        if not teaching_note and isinstance(general_override, dict):
            teaching_note = str(general_override.get("teaching_note") or "").strip()
        if not next_step:
            next_step = _localized_text(
                "Keep going with the next small verifiable move on this same lane.",
                "继续沿着同一条主线做下一个可验证的小动作。",
                response_language,
            )
        if not teaching_note:
            teaching_note = _localized_text(
                "Keep the lesson narrow, visible, and verifiable until the provider path is stable again.",
                "先把这一步收窄成一个可见、可验证的小动作，等回答恢复正常后再继续。",
                response_language,
            )
        if not guided_reply:
            guided_reply = (
                str(general_override.get("reply") or "").strip()
                if isinstance(general_override, dict)
                else ""
            ) or summary
        reply = guided_reply if guided_reply.startswith(summary) else f"{summary}\n\n{guided_reply}"
    resume_thread = _agentic_resume_thread_text(
        summary,
        next_step,
        response_language=response_language,
    )
    resolved_scenario = domain or ("general" if isinstance(general_override, dict) else domain)
    return {
        "summary": summary,
        "next_step": next_step,
        "teaching_note": teaching_note,
        "reply": reply,
        "resume_thread": resume_thread,
        "stop_reason": "language_corruption_recovered",
        "fell_back": True,
        "scenario": resolved_scenario,
    }
