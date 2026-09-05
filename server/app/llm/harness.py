"""Pi-inspired coach harness primitives.

Trainer reuses Pi's harness mechanics, not its coding-agent product:

* token-threshold compaction with a structured summary and a valid cut point
* within-turn prune that never splits an assistant tool_call from its tool result
* per-tool output limits
* overflow compact-and-retry in the same run
* steering / follow-up injection between LLM calls
* truncated (length) tool calls fail instead of executing
* read-only tools may run in parallel
* sandbox write/index/organize commits are idempotent for the live process

The inner agent loop still owns iteration. This module is the prepare-next-turn
and tool-safety layer that Pi keeps around that loop.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("trainer.llm.harness")

# Pi coding-agent defaults: compact when contextTokens > window - reserve,
# keep the most recent ~20k tokens verbatim.
DEFAULT_CONTEXT_WINDOW_TOKENS = 128_000
RESERVE_TOKENS = 16_384
KEEP_RECENT_TOKENS = 20_000
OVERFLOW_KEEP_RECENT_TOKENS = 8_000
COMPACTION_TOOL_SERIALIZE_CHARS = 2_000

# Character caps aligned with Pi toolOutputLimits (bash 30k / read 100k / default 30k).
TOOL_OUTPUT_LIMITS: dict[str, int] = {
    "read_sandbox_file": 100_000,
    "read_workspace_file": 100_000,
    "inspect_current_file": 50_000,
    "search_resources": 30_000,
    "list_sandbox": 30_000,
    "list_workspace_files": 30_000,
    "run_diagnostics": 30_000,
    "recall_memory": 20_000,
    "inspect_plan": 20_000,
    "verify_practice_current_file": 20_000,
    "write_sandbox_file": 12_000,
    "index_sandbox_file": 12_000,
    "organize_resources": 20_000,
    "import_resource_url": 16_000,
    "save_formal_plan": 16_000,
    "coach_finalize": 8_000,
}
DEFAULT_TOOL_OUTPUT_LIMIT = 30_000
RECENT_TOOL_KEEP = 3
MAX_KEPT_TOOL_RESULT_CHARS = 2_400
PRUNED_TOOL_RESULT_MARK = "…[earlier tool result pruned]"

READ_ONLY_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "search_resources",
        "list_sandbox",
        "read_sandbox_file",
        "list_workspace_files",
        "read_workspace_file",
        "inspect_current_file",
        "inspect_plan",
        "recall_memory",
        "run_diagnostics",
        "verify_practice_current_file",
    }
)
IDEMPOTENT_SANDBOX_TOOLS: frozenset[str] = frozenset(
    {
        "write_sandbox_file",
        "index_sandbox_file",
    }
)

_PROMPT_TOO_LONG_MARKERS = (
    "contextlength",
    "context_length",
    "maximumcontext",
    "promptistoolong",
    "prompt too long",
    "too many tokens",
    "token limit",
    "context window",
    "context_window",
    "please reduce the length",
    "max_tokens",
    "maxcontext",
)
_TRUNCATED_STOP_MARKERS = frozenset(
    {
        "length",
        "max_tokens",
        "maxtokens",
        "truncated",
        "token_limit",
        "max_output_tokens",
    }
)


@dataclass
class CompactionRecord:
    """One in-loop compaction, analogous to Pi's CompactionEntry."""

    summary: str
    first_kept_index: int
    tokens_before: int
    tokens_after: int
    reason: str


def estimate_tokens(messages: list[dict[str, Any]] | None) -> int:
    """Cheap request-size estimate (CJK = 1 token, other chars ≈ 4 per token)."""

    if not messages:
        return 0
    estimated = 32
    for message in messages:
        try:
            serialized = json.dumps(message, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            serialized = str(message)
        cjk = sum(1 for character in serialized if "\u3400" <= character <= "\u9fff")
        rest = max(0, len(serialized) - cjk)
        estimated += cjk + ((rest + 3) // 4) + 16
    return estimated


def tool_output_limit(name: str | None) -> int:
    key = str(name or "").strip()
    return int(TOOL_OUTPUT_LIMITS.get(key, DEFAULT_TOOL_OUTPUT_LIMIT))


def truncate_tool_payload(content_text: str, *, limit: int) -> str:
    text = str(content_text or "")
    if len(text) <= limit:
        return text
    return text[: max(0, limit)] + "\n…[truncated]"


def message_role(message: dict[str, Any] | None) -> str:
    if not isinstance(message, dict):
        return ""
    return str(message.get("role") or "").strip().lower()


def is_truncated_stop(stop_reason: object | None) -> bool:
    if not isinstance(stop_reason, str):
        return False
    normalized = re.sub(r"[^a-z0-9]", "", stop_reason.lower())
    if not normalized:
        return False
    if normalized in {re.sub(r"[^a-z0-9]", "", item) for item in _TRUNCATED_STOP_MARKERS}:
        return True
    return "maxtoken" in normalized or "tokenlimit" in normalized or normalized == "length"


def is_prompt_too_long_error(exc: BaseException | None) -> bool:
    if exc is None:
        return False
    name = exc.__class__.__name__.lower()
    if "contextbudget" in name:
        return True
    blob = re.sub(r"[^a-z0-9]", "", f"{name} {exc}".lower())
    return any(re.sub(r"[^a-z0-9]", "", marker) in blob for marker in _PROMPT_TOO_LONG_MARKERS)


def truncated_tool_failure(name: str) -> dict[str, Any]:
    tool_name = str(name or "tool").strip() or "tool"
    return {
        "ok": False,
        "error": "truncated_tool_call",
        "detail": (
            f'Tool call "{tool_name}" was not executed: the response hit the output '
            "token limit, so its arguments may be truncated. Re-issue the tool call "
            "with complete arguments."
        ),
    }


def tools_are_read_only(tool_calls: list[dict[str, Any]]) -> bool:
    if not tool_calls:
        return False
    names = [str(call.get("name") or "").strip() for call in tool_calls]
    return bool(names) and all(name in READ_ONLY_TOOL_NAMES for name in names)


def resolved_context_window(extra: dict[str, Any] | None) -> int:
    raw = extra.get("context_window_tokens") if isinstance(extra, dict) else None
    try:
        value = int(raw) if raw is not None else DEFAULT_CONTEXT_WINDOW_TOKENS
    except (TypeError, ValueError):
        value = DEFAULT_CONTEXT_WINDOW_TOKENS
    return max(2_048, value)


def resolved_reserve_tokens(extra: dict[str, Any] | None) -> int:
    raw = extra.get("reserve_tokens") if isinstance(extra, dict) else None
    try:
        value = int(raw) if raw is not None else RESERVE_TOKENS
    except (TypeError, ValueError):
        value = RESERVE_TOKENS
    return max(512, value)


def should_compact(
    messages: list[dict[str, Any]],
    *,
    extra: dict[str, Any] | None = None,
    keep_recent_tokens: int = KEEP_RECENT_TOKENS,
) -> bool:
    window = resolved_context_window(extra)
    reserve = resolved_reserve_tokens(extra)
    tokens = estimate_tokens(messages)
    threshold = max(keep_recent_tokens, window - reserve)
    return tokens > threshold


def find_cut_point(
    messages: list[dict[str, Any]],
    *,
    keep_recent_tokens: int = KEEP_RECENT_TOKENS,
) -> int:
    """First index to keep. Never a tool message (Pi: do not cut at tool results)."""

    if not messages:
        return 0
    leading = 0
    while leading < len(messages) and message_role(messages[leading]) in {"system", "developer"}:
        leading += 1
    accumulated = 0
    cut = leading
    for index in range(len(messages) - 1, leading - 1, -1):
        tokens = estimate_tokens([messages[index]])
        if accumulated + tokens > keep_recent_tokens and message_role(messages[index]) != "tool":
            cut = index
            break
        accumulated += tokens
    else:
        return leading

    while cut > leading and message_role(messages[cut]) == "tool":
        cut -= 1
    if message_role(messages[cut]) == "tool":
        return leading
    if cut <= leading:
        return leading
    return cut


def _serialize_span(messages: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for message in messages:
        role = message_role(message)
        content = str(message.get("content") or "").strip()
        if role == "user":
            lines.append(f"[User]: {content[:1200]}")
            continue
        if role == "assistant":
            if content:
                lines.append(f"[Assistant]: {content[:1200]}")
            tool_calls = message.get("tool_calls") or []
            if isinstance(tool_calls, list) and tool_calls:
                rendered: list[str] = []
                for call in tool_calls:
                    if not isinstance(call, dict):
                        continue
                    function = call.get("function") if isinstance(call.get("function"), dict) else {}
                    name = str(call.get("name") or function.get("name") or "").strip()
                    arguments = call.get("arguments")
                    if arguments is None:
                        arguments = function.get("arguments")
                    if not isinstance(arguments, str):
                        try:
                            arguments = json.dumps(arguments, ensure_ascii=False, default=str)
                        except (TypeError, ValueError):
                            arguments = str(arguments or "")
                    rendered.append(f"{name}({str(arguments)[:240]})")
                if rendered:
                    lines.append("[Assistant tool calls]: " + "; ".join(rendered))
            continue
        if role == "tool":
            name = str(message.get("name") or "tool").strip()
            snippet = content[:COMPACTION_TOOL_SERIALIZE_CHARS]
            if len(content) > COMPACTION_TOOL_SERIALIZE_CHARS:
                snippet += "\n…[truncated]"
            lines.append(f"[Tool result {name}]: {snippet}")
    return "\n".join(lines)


def structured_compaction_summary(
    messages: list[dict[str, Any]],
    *,
    extra: dict[str, Any] | None = None,
) -> str:
    """Extractive Goal/Progress/Next summary. No extra LLM call."""

    extra = extra if isinstance(extra, dict) else {}
    goal = str(
        extra.get("thread_summary")
        or extra.get("current_focus")
        or extra.get("summary")
        or extra.get("learner_message")
        or ""
    ).strip()
    next_step = str(
        extra.get("thread_next_step") or extra.get("next_step_hint") or extra.get("resume_hint") or ""
    ).strip()
    blocker = str(extra.get("blocker") or "").strip()

    done: list[str] = []
    sandbox_paths: list[str] = []
    for message in messages:
        if message_role(message) != "tool":
            continue
        name = str(message.get("name") or "tool").strip()
        content = str(message.get("content") or "")
        done.append(name)
        for match in re.findall(r'(?:path|sandbox_path)"?\s*:\s*"([^"]+)"', content):
            if match and match not in sandbox_paths:
                sandbox_paths.append(match)
        if len(done) >= 12:
            break

    unique_done = list(dict.fromkeys(done))
    last_user = ""
    for message in reversed(messages):
        if message_role(message) == "user":
            last_user = str(message.get("content") or "").strip()[:400]
            break

    lines = ["## Goal", goal or last_user or "Continue the live coaching thread.", ""]
    lines.extend(["## Progress", "### Done"])
    if unique_done:
        for name in unique_done[:8]:
            lines.append(f"- [x] {name}")
    else:
        lines.append("- [x] Earlier turns compacted")
    lines.append("")
    lines.append("### In Progress")
    lines.append(f"- [ ] {last_user or 'Current learner request'}")
    if blocker:
        lines.extend(["", "### Blocked", f"- {blocker}"])
    lines.extend(["", "## Next Steps"])
    lines.append(f"1. {next_step or 'Continue from the latest tool evidence.'}")
    lines.extend(["", "## Critical Context"])
    if sandbox_paths:
        for path in sandbox_paths[:8]:
            lines.append(f"- sandbox: {path}")
    serialized = _serialize_span(messages[-6:])
    if serialized:
        lines.append(serialized[:1800])
    return "\n".join(lines).strip()


def prune_older_tool_results(
    history: list[dict[str, Any]],
    *,
    recent_keep: int = RECENT_TOOL_KEEP,
    kept_chars: int = MAX_KEPT_TOOL_RESULT_CHARS,
    history_char_budget: int | None = None,
) -> None:
    """OpenCode/Pi within-turn prune: shrink then stub older tool bodies."""

    tool_indexes = [
        index for index, message in enumerate(history) if message_role(message) == "tool"
    ]
    if not tool_indexes:
        return
    keep_count = max(1, int(recent_keep))
    keep = set(tool_indexes[-keep_count:])
    for index in tool_indexes:
        if index in keep:
            continue
        message = history[index]
        content = str(message.get("content") or "")
        if len(content) > kept_chars:
            message["content"] = truncate_tool_payload(content, limit=kept_chars)

    if history_char_budget is None:
        return
    def _chars() -> int:
        return sum(len(str(item.get("content") or "")) for item in history)

    if _chars() <= history_char_budget:
        return
    for index in tool_indexes:
        if index in keep:
            continue
        if _chars() <= history_char_budget:
            return
        message = history[index]
        stub = f"{str(message.get('name') or 'tool')}: {PRUNED_TOOL_RESULT_MARK}"
        if len(str(message.get("content") or "")) > len(stub):
            message["content"] = stub


def compact_history(
    history: list[dict[str, Any]],
    *,
    extra: dict[str, Any] | None = None,
    keep_recent_tokens: int = KEEP_RECENT_TOKENS,
    reason: str = "threshold",
    force: bool = False,
) -> CompactionRecord | None:
    """Replace older turns with a structured summary. Mutates ``history`` in place."""

    if len(history) < 6 and not force:
        return None
    tokens_before = estimate_tokens(history)
    if not force and not should_compact(
        history, extra=extra, keep_recent_tokens=keep_recent_tokens
    ):
        return None
    cut = find_cut_point(history, keep_recent_tokens=keep_recent_tokens)
    leading = 0
    while leading < len(history) and message_role(history[leading]) in {"system", "developer"}:
        leading += 1
    if cut <= leading + 1:
        if force and len(history) > leading + 3:
            cut = max(leading + 1, len(history) - 2)
            while cut > leading and message_role(history[cut]) == "tool":
                cut -= 1
        else:
            prune_older_tool_results(history, history_char_budget=80_000)
            return None
    to_summarize = [dict(item) for item in history[leading:cut] if isinstance(item, dict)]
    if not to_summarize:
        return None
    summary = structured_compaction_summary(to_summarize, extra=extra)
    prefix = [dict(item) for item in history[:leading] if isinstance(item, dict)]
    kept = [dict(item) for item in history[cut:] if isinstance(item, dict)]
    compaction_message = {
        "role": "system",
        "name": "compaction",
        "content": (
            "Earlier turns were compacted to free the context window. "
            "Use this summary as prior context; do not ask the learner to repeat it.\n\n"
            f"{summary}"
        ),
    }
    history[:] = prefix + [compaction_message] + kept
    record = CompactionRecord(
        summary=summary,
        first_kept_index=len(prefix) + 1,
        tokens_before=tokens_before,
        tokens_after=estimate_tokens(history),
        reason=reason,
    )
    logger.info(
        "agent_history_compacted",
        extra={
            "reason": reason,
            "tokens_before": record.tokens_before,
            "tokens_after": record.tokens_after,
        },
    )
    return record


def prepare_next_turn(
    history: list[dict[str, Any]],
    *,
    extra: dict[str, Any] | None = None,
    keep_recent_tokens: int = KEEP_RECENT_TOKENS,
    history_char_budget: int = 80_000,
) -> CompactionRecord | None:
    """Pi prepareNextTurn: prune, then compact if the next LLM call would overflow."""

    prune_older_tool_results(history, history_char_budget=history_char_budget)
    return compact_history(
        history,
        extra=extra,
        keep_recent_tokens=keep_recent_tokens,
        reason="threshold",
    )


def drain_steering_messages(context: Any) -> list[str]:
    """Pull queued human follow-ups for this session (Pi getSteeringMessages)."""

    texts: list[str] = []
    extra = getattr(context, "extra", None)
    if isinstance(extra, dict):
        raw = extra.get("steering_messages")
        if isinstance(raw, list):
            texts.extend(str(item).strip() for item in raw if str(item).strip())
            extra["steering_messages"] = []
    runtime = getattr(context, "runtime", None)
    session_id = str(getattr(context, "session_id", "") or "").strip()
    drain = getattr(runtime, "drain_steer_messages", None) if runtime is not None else None
    if callable(drain) and session_id:
        try:
            queued = drain(session_id)
        except Exception:
            logger.exception("steer_drain_failed")
            queued = []
        if isinstance(queued, list):
            texts.extend(str(item).strip() for item in queued if str(item).strip())
    return [item for item in texts if item]


def append_steering_messages(history: list[dict[str, Any]], texts: list[str]) -> int:
    count = 0
    for text in texts:
        cleaned = str(text or "").strip()
        if not cleaned:
            continue
        history.append({"role": "user", "content": cleaned})
        count += 1
    return count


def sandbox_operation_key(
    workspace_id: str,
    name: str,
    arguments: dict[str, Any] | None,
) -> str | None:
    if name not in IDEMPOTENT_SANDBOX_TOOLS:
        return None
    payload = arguments if isinstance(arguments, dict) else {}
    try:
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):
        encoded = str(payload)
    digest = hashlib.sha256(encoded.encode("utf-8", errors="replace")).hexdigest()
    return f"{workspace_id}:{name}:{digest}"


def lookup_sandbox_operation(runtime: Any, key: str | None) -> dict[str, Any] | None:
    if not key or runtime is None:
        return None
    log = getattr(runtime, "sandbox_operation_log", None)
    if not isinstance(log, dict):
        return None
    cached = log.get(key)
    return dict(cached) if isinstance(cached, dict) else None


def store_sandbox_operation(runtime: Any, key: str | None, result: dict[str, Any]) -> None:
    if not key or runtime is None or not isinstance(result, dict):
        return
    if result.get("ok") is not True:
        return
    # Never cache dry proposals. A later confirmed commit uses the same
    # operations payload and must actually run.
    if result.get("requires_confirmation") is True or result.get("committed") is False:
        return
    log = getattr(runtime, "sandbox_operation_log", None)
    if not isinstance(log, dict):
        return
    stored = dict(result)
    stored["idempotent_key"] = key
    log[key] = stored
    ledger = getattr(runtime, "event_ledger", None)
    record = getattr(ledger, "record_event", None) if ledger is not None else None
    if not callable(record):
        return
    try:
        record(
            "sandbox_command_executed",
            actor="coach_agent",
            scope=str(result.get("path") or key),
            payload_ref={"key": key, "path": result.get("path"), "replayable": True},
            reversibility="append_only",
        )
    except Exception:
        logger.exception("sandbox_operation_ledger_failed")
