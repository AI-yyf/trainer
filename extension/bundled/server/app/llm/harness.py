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

# Modern 1M-context defaults: compact when contextTokens > window - reserve,
# scaling reserve and keep_recent thresholds proportionally with window size.
DEFAULT_CONTEXT_WINDOW_TOKENS = 1_000_000
RESERVE_TOKENS = 16_384
KEEP_RECENT_TOKENS = 20_000
OVERFLOW_KEEP_RECENT_TOKENS = 8_000


@dataclass(frozen=True, slots=True)
class ProviderUsage:
    """§二十一: provider-reported token usage for a single LLM call.

    Prefers real reported usage over estimation. All fields optional —
    providers may report only input+output without reasoning/cache detail.
    """

    input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    total_tokens: int | None = None
    input_cost: float | None = None
    output_cost: float | None = None
    total_cost: float | None = None

    @property
    def estimated_input_tokens(self) -> int | None:
        """Best input token count: prefer explicit, derive from total if needed."""
        if self.input_tokens is not None:
            return self.input_tokens
        if self.total_tokens is not None and self.output_tokens is not None:
            return self.total_tokens - self.output_tokens
        return None


def extract_provider_usage(response: object | None) -> ProviderUsage | None:
    """Read provider-reported usage from an OpenAI-compatible response body.

    Looks for ``response.usage`` (or a dict ``usage`` key) and reads the
    standard OpenAI token-count fields. Returns None if no usage data found.
    """
    if response is None:
        return None
    usage_obj = getattr(response, "usage", None)
    if usage_obj is None and isinstance(response, dict):
        usage_obj = response.get("usage")
    if usage_obj is None:
        return None

    def _float(key: str) -> float | None:
        raw = getattr(usage_obj, key, None)
        if raw is None and isinstance(usage_obj, dict):
            raw = usage_obj.get(key)
        if raw is None:
            return None
        try:
            value = float(raw)
            return value if value >= 0 else None
        except (TypeError, ValueError):
            return None

    def _int(key: str) -> int | None:
        raw = getattr(usage_obj, key, None)
        if raw is None and isinstance(usage_obj, dict):
            raw = usage_obj.get(key)
        if raw is None:
            return None
        try:
            value = int(raw)
            return value if value >= 0 else None
        except (TypeError, ValueError):
            return None

    input_tokens = _int("prompt_tokens") or _int("input_tokens")
    output_tokens = _int("completion_tokens") or _int("output_tokens")
    total = _int("total_tokens")
    if input_tokens is None and output_tokens is None and total is None:
        return None
    return ProviderUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        reasoning_tokens=_int("reasoning_tokens"),
        cache_read_tokens=_int("cache_read_input_tokens") or _int("cache_read_tokens"),
        cache_write_tokens=_int("cache_creation_input_tokens") or _int("cache_write_tokens"),
        total_tokens=total,
    input_cost=_float("input_cost") or _float("prompt_cost"),
    output_cost=_float("output_cost") or _float("completion_cost"),
    total_cost=_float("total_cost"),
    )
COMPACTION_TOOL_SERIALIZE_CHARS = 2_000
COMPACTION_RESEARCH_SOURCE_LIMIT = 48
COMPACTION_RESEARCH_ASSESSMENT_LIMIT = 8
COMPACTION_RECORD_LIMIT = 12

# Character caps aligned with Pi toolOutputLimits (bash 30k / read 100k / default 30k).
TOOL_OUTPUT_LIMITS: dict[str, int] = {
    "project_read": 100_000,
    "project_verify": 30_000,
    "library_read": 100_000,
    "library_write": 20_000,
    "library_exec": 30_000,
    "web_fetch": 30_000,
    "learning_inspect": 24_000,
    "learning_action": 24_000,
    "read_sandbox_file": 100_000,
    "read_workspace_file": 100_000,
    "inspect_current_file": 50_000,
    "search_resources": 30_000,
    "list_sandbox": 30_000,
    "list_workspace_files": 30_000,
    "web_search": 24_000,
    "search_academic_papers": 28_000,
    "fetch_web_page": 30_000,
    "run_diagnostics": 30_000,
    "recall_memory": 20_000,
    "inspect_plan": 20_000,
    "verify_practice_current_file": 20_000,
    "write_sandbox_file": 12_000,
    "index_sandbox_file": 12_000,
    "organize_resources": 20_000,
    "list_library_folders": 20_000,
    "curate_library_resources": 20_000,
    "list_skills": 16_000,
    "invoke_skill": 24_000,
    "generate_image": 8_000,
    "import_resource_url": 16_000,
    "save_formal_plan": 16_000,
    "inspect_learning_truth": 24_000,
    "save_lecture_note": 8_000,
    "coach_finalize": 8_000,
}
DEFAULT_TOOL_OUTPUT_LIMIT = 30_000
RECENT_TOOL_KEEP = 3
MAX_KEPT_TOOL_RESULT_CHARS = 2_400
PRUNED_TOOL_RESULT_MARK = "…[earlier tool result pruned]"

READ_ONLY_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "project_read",
        "project_verify",
        "library_read",
        "learning_inspect",
        "search_resources",
        "list_sandbox",
        "read_sandbox_file",
        "list_workspace_files",
        "read_workspace_file",
        "web_search",
        "search_academic_papers",
        "fetch_web_page",
        "list_library_folders",
        "list_skills",
        "invoke_skill",
        "inspect_current_file",
        "inspect_plan",
        "inspect_learning_truth",
        "recall_memory",
        "run_diagnostics",
        "verify_practice_current_file",
    }
)
IDEMPOTENT_SANDBOX_TOOLS: frozenset[str] = frozenset(
    {
        "library_write",
        "write_sandbox_file",
    }
)
SANDBOX_OPERATION_LOG_LIMIT = 128

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


def _call_action(call: dict[str, Any]) -> str:
    raw_args = call.get("arguments")
    if isinstance(raw_args, dict):
        return str(raw_args.get("action") or "").strip().lower()
    if isinstance(raw_args, str) and raw_args.strip():
        try:
            parsed = json.loads(raw_args)
            if isinstance(parsed, dict):
                return str(parsed.get("action") or "").strip().lower()
        except (TypeError, ValueError):
            return ""
    return ""


def _is_read_only_tool_call(call: dict[str, Any]) -> bool:
    name = str(call.get("name") or "").strip()
    if not name:
        return False
    if name in READ_ONLY_TOOL_NAMES:
        return True
    action = _call_action(call)
    if name == "web_fetch":
        return action in {"", "search", "fetch", "papers"}
    if name == "learning_action":
        return action == "invoke_skill"
    return False


def tools_are_read_only(tool_calls: list[dict[str, Any]]) -> bool:
    if not tool_calls:
        return False
    return all(_is_read_only_tool_call(call) for call in tool_calls)


def resolved_context_window(extra: dict[str, Any] | None) -> int:
    raw = extra.get("context_window_tokens") if isinstance(extra, dict) else None
    try:
        value = int(raw) if raw is not None else DEFAULT_CONTEXT_WINDOW_TOKENS
    except (TypeError, ValueError):
        value = DEFAULT_CONTEXT_WINDOW_TOKENS
    return max(2_048, value)


def resolved_reserve_tokens(extra: dict[str, Any] | None) -> int:
    raw = extra.get("reserve_tokens") if isinstance(extra, dict) else None
    if raw is not None:
        try:
            return max(512, int(raw))
        except (TypeError, ValueError):
            pass
    window = resolved_context_window(extra)
    if window <= 131_072:
        return max(512, RESERVE_TOKENS)
    return max(512, min(128_000, max(RESERVE_TOKENS, window // 10)))


def resolved_keep_recent_tokens(extra: dict[str, Any] | None) -> int:
    """§二十: keep_recent_tokens scales with context window and stays overridable via extra."""
    raw = extra.get("keep_recent_tokens") if isinstance(extra, dict) else None
    if raw is not None:
        try:
            return max(1_024, int(raw))
        except (TypeError, ValueError):
            pass
    window = resolved_context_window(extra)
    if window <= 131_072:
        return max(1_024, KEEP_RECENT_TOKENS)
    return max(1_024, min(160_000, max(KEEP_RECENT_TOKENS, window // 8)))


def resolve_compaction_profile(
    extra: dict[str, Any] | None,
) -> tuple[int, int, int]:
    """§十九 §二十: resolve (context_window, reserve, keep_recent) as a set.

    A 1M-context model might set context_window_tokens=1_000_000,
    reserve_tokens=160_000, keep_recent_tokens=32_000 in its provider
    extra. Returns values clamped to safe minimums.
    """
    return (
        resolved_context_window(extra),
        resolved_reserve_tokens(extra),
        resolved_keep_recent_tokens(extra),
    )


def should_compact(
    messages: list[dict[str, Any]],
    *,
    extra: dict[str, Any] | None = None,
    keep_recent_tokens: int = KEEP_RECENT_TOKENS,
    last_provider_input_tokens: int | None = None,
) -> bool:
    """§二十一: prefer provider-reported input tokens when available.

    ``last_provider_input_tokens`` comes from the most recent LLM response's
    real usage report. It reflects the actual token count including
    reasoning/cache tokens that chars/4 estimation systematically misses.
    Falls back to estimate_tokens when no provider usage is available.
    """
    window = resolved_context_window(extra)
    reserve = resolved_reserve_tokens(extra)
    if last_provider_input_tokens is not None and last_provider_input_tokens > 0:
        tokens = last_provider_input_tokens
    else:
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

    while cut > leading and message_role(messages[cut]) != "user":
        cut -= 1
    if message_role(messages[cut]) != "user":
        # Fall back to the earliest non-tool boundary only if no user message exists.
        cut = leading
        while cut < len(messages) and message_role(messages[cut]) == "tool":
            cut += 1
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
                    raw_function = call.get("function")
                    function: dict[str, object] = (
                        raw_function if isinstance(raw_function, dict) else {}
                    )
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


def _research_evidence_ledger(extra: dict[str, Any]) -> list[str]:
    """Render the durable research state, not repeated raw page bodies.

    Tool results are deliberately pruned well before a very large context window is full.
    This ledger is the loss-resistant checkpoint that lets the model continue deciding
    whether evidence is sufficient after a full history compaction.
    """

    state_raw = extra.get("_learning_material_research_state")
    if not isinstance(state_raw, dict):
        return []
    state = state_raw
    required_facets = [
        " ".join(str(item or "").split())
        for item in state.get("required_facets", [])
        if str(item or "").strip()
    ][:8]
    covered_facets = [
        " ".join(str(item or "").split())
        for item in state.get("covered_facets", [])
        if str(item or "").strip()
    ][:8]
    covered_keys = {item.casefold() for item in covered_facets}
    missing_facets = [item for item in required_facets if item.casefold() not in covered_keys]
    sources = [
        item for item in state.get("sources", []) if isinstance(item, dict)
    ][:COMPACTION_RESEARCH_SOURCE_LIMIT]
    assessments = [
        item for item in state.get("assessment", []) if isinstance(item, dict)
    ][:COMPACTION_RESEARCH_ASSESSMENT_LIMIT]
    evidence_standard_raw = state.get("evidence_standard")
    evidence_standard = (
        evidence_standard_raw if isinstance(evidence_standard_raw, dict) else {}
    )

    lines = ["## Research Evidence Ledger"]
    lines.append(f"- Status: {str(state.get('status') or 'in_progress').strip()}")
    lines.append(f"- Search rounds completed: {int(state.get('search_count') or 0)}")
    if required_facets:
        lines.append("- Required facets: " + "; ".join(required_facets))
    if covered_facets:
        lines.append("- Covered facets: " + "; ".join(covered_facets))
    if missing_facets:
        lines.append("- Open evidence gaps: " + "; ".join(missing_facets))
    if evidence_standard:
        lines.extend(["", "### Adaptive Evidence Standard"])
        lines.append(
            "- Risk / claims: "
            + str(evidence_standard.get("risk_level") or "unknown")
            + " / "
            + ", ".join(
                str(item) for item in evidence_standard.get("claim_types", []) if str(item)
            )
        )
        lines.append(
            "- Source threshold: "
            + str(evidence_standard.get("minimum_independent_sources") or "unknown")
            + "; authoritative required="
            + str(evidence_standard.get("requires_authoritative_source")).lower()
            + "; freshness="
            + str(evidence_standard.get("freshness_requirement") or "unknown")
        )
        scope = " ".join(str(evidence_standard.get("applicability_scope") or "").split())
        stopping_rule = " ".join(str(evidence_standard.get("stopping_rule") or "").split())
        if scope:
            lines.append(f"- Applicability: {scope[:360]}")
        if stopping_rule:
            lines.append(f"- Stop rule: {stopping_rule[:360]}")
        for check in evidence_standard.get("quality_checks", []):
            if not isinstance(check, dict):
                continue
            dimension = str(check.get("dimension") or "quality").strip()
            status = str(check.get("status") or "unknown").strip()
            rationale = " ".join(str(check.get("rationale") or "").split())[:300]
            lines.append(f"- Quality {dimension}: {status} | {rationale}")
        uncertainties = [
            " ".join(str(item or "").split())
            for item in evidence_standard.get("unresolved_uncertainties", [])
            if str(item or "").strip()
        ]
        if uncertainties:
            lines.append("- Unresolved uncertainties: " + "; ".join(uncertainties[:8]))
    if sources:
        lines.extend(["", "### Verified Source Catalog"])
        for source in sources:
            source_id = str(source.get("id") or source.get("url") or "source").strip()
            title = " ".join(str(source.get("title") or "Untitled source").split())[:180]
            url = str(source.get("url") or "").strip()
            fetched_at = str(source.get("fetched_at") or "").strip()
            suffix = f" (fetched {fetched_at})" if fetched_at else ""
            lines.append(f"- [{source_id}] {title} — {url}{suffix}")
    if assessments:
        lines.extend(["", "### Model Evidence Judgments"])
        for assessment in assessments:
            facet = " ".join(str(assessment.get("facet") or "facet").split())[:120]
            status = str(assessment.get("status") or "unknown").strip()
            source_ids = [
                str(item).strip()
                for item in assessment.get("source_ids", [])
                if str(item).strip()
            ][:8]
            rationale = " ".join(str(assessment.get("rationale") or "").split())[:320]
            line = f"- {facet}: {status}"
            if source_ids:
                line += " | sources=" + ", ".join(source_ids)
            if rationale:
                line += f" | rationale={rationale}"
            lines.append(line)
            quotes = [
                item
                for item in assessment.get("evidence_quotes", [])
                if isinstance(item, dict)
            ][:4]
            for quote_item in quotes:
                quote_source = str(quote_item.get("source_id") or "").strip()
                quote = " ".join(str(quote_item.get("quote") or "").split())[:280]
                if quote:
                    lines.append(f'  - exact evidence [{quote_source}]: "{quote}"')
    return lines


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
    research_ledger = _research_evidence_ledger(extra)
    if research_ledger:
        lines.extend(["", *research_ledger])
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
            while cut > leading and message_role(history[cut]) != "user":
                cut -= 1
            if cut <= leading:
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
    if isinstance(extra, dict):
        metrics_raw = extra.get("_context_compaction_records")
        metrics = list(metrics_raw) if isinstance(metrics_raw, list) else []
        metric = {
            "reason": record.reason,
            "tokens_before": record.tokens_before,
            "tokens_after": record.tokens_after,
            "research_state_preserved": isinstance(
                extra.get("_learning_material_research_state"), dict
            ),
        }
        metrics.append(metric)
        extra["_context_compaction_records"] = metrics[-COMPACTION_RECORD_LIMIT:]
        extra["_last_context_compaction"] = metric
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


def _normalize_sandbox_op_relpath(raw_path: Any) -> str:
    return str(raw_path or "").strip().replace("\\", "/").lstrip("./").rstrip("/")


def sandbox_operation_key(
    workspace_id: str,
    name: str,
    arguments: dict[str, Any] | None,
) -> str | None:
    if name not in IDEMPOTENT_SANDBOX_TOOLS:
        return None
    payload = arguments if isinstance(arguments, dict) else {}
    if name == "library_write":
        action = str(payload.get("action") or "write").strip().lower()
        # Only exact file-content writes are candidates for idempotent replay;
        # refresh_index exists specifically to re-read mutated disk files.
        if action != "write":
            return None
    try:
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):
        encoded = str(payload)
    digest = hashlib.sha256(encoded.encode("utf-8", errors="replace")).hexdigest()
    return f"{workspace_id}:{name}:{digest}"


def invalidate_sandbox_operations(
    runtime: Any,
    workspace_id: str,
    *,
    paths: list[str] | tuple[str, ...] | None = None,
) -> int:
    """Evict cached sandbox write entries for a workspace (all paths or specific paths)."""
    if runtime is None or not workspace_id:
        return 0
    log = getattr(runtime, "sandbox_operation_log", None)
    if not isinstance(log, dict) or not log:
        return 0
    prefix = f"{workspace_id}:"
    normalized_targets = {
        _normalize_sandbox_op_relpath(item).casefold()
        for item in (paths or ())
        if _normalize_sandbox_op_relpath(item)
    }
    to_remove: list[str] = []
    for existing_key, entry in list(log.items()):
        if not str(existing_key).startswith(prefix):
            continue
        if not normalized_targets:
            to_remove.append(existing_key)
            continue
        entry_path = (
            _normalize_sandbox_op_relpath(entry.get("path")).casefold()
            if isinstance(entry, dict)
            else ""
        )
        if not entry_path or entry_path in normalized_targets:
            to_remove.append(existing_key)
    for existing_key in to_remove:
        log.pop(existing_key, None)
    return len(to_remove)


def lookup_sandbox_operation(
    runtime: Any,
    key: str | None,
    *,
    workspace_id: str | None = None,
    expected_path: str | None = None,
    expected_content: str | None = None,
    limit: int = SANDBOX_OPERATION_LOG_LIMIT,
) -> dict[str, Any] | None:
    if not key or runtime is None:
        return None
    log = getattr(runtime, "sandbox_operation_log", None)
    if not isinstance(log, dict):
        return None
    cached = log.get(key)
    if not isinstance(cached, dict):
        return None
    # Verify live disk state whenever sandbox_service is attached so prior edits,
    # renames, soft_deletes, or external changes never trigger a stale replay.
    sandbox_service = getattr(runtime, "sandbox_service", None)
    effective_ws = str(workspace_id or key.split(":", 1)[0] or "").strip()
    rel_path = _normalize_sandbox_op_relpath(expected_path or cached.get("path"))
    if sandbox_service is not None and effective_ws and rel_path:
        try:
            from pathlib import Path

            root = Path(sandbox_service.ensure_operation_root(effective_ws)).resolve()
            target = (root / rel_path).resolve()
            target.relative_to(root)
            if not target.is_file():
                log.pop(key, None)
                return None
            if expected_content is not None:
                disk_text = target.read_text(encoding="utf-8", errors="replace")
                if disk_text != str(expected_content):
                    log.pop(key, None)
                    return None
        except Exception:
            log.pop(key, None)
            return None
    # Touch on hit for true LRU ordering and enforce bound.
    log.pop(key, None)
    log[key] = cached
    while len(log) > max(1, limit):
        log.pop(next(iter(log)), None)
    return dict(cached)


def store_sandbox_operation(
    runtime: Any,
    key: str | None,
    result: dict[str, Any],
    *,
    limit: int = SANDBOX_OPERATION_LOG_LIMIT,
) -> None:
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
    workspace_id = key.split(":", 1)[0]
    rel_path = _normalize_sandbox_op_relpath(result.get("path"))
    if workspace_id and rel_path:
        invalidate_sandbox_operations(runtime, workspace_id, paths=[rel_path])
    stored = dict(result)
    stored["idempotent_key"] = key
    log.pop(key, None)
    log[key] = stored
    while len(log) > max(1, limit):
        log.pop(next(iter(log)), None)
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
