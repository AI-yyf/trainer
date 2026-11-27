"""Trainer coach tool registry.

This module turns Trainer's existing services (memory, planner, training cards,
resources, evaluator) into first-class **tools** the LLM can call inside an
agent loop. Each tool is described by a JSON Schema (so we can format it for
OpenAI / Anthropic / Gemini protocols) and a handler that executes against the
shared :class:`~app.api.runtime.TrainerRuntime` instance.

Design goals:

* **Coach-first**: tools surface evidence, propose plans, generate cards. They
  do **not** edit user code; that stays the learner's job.
* **Read-mostly with audit-friendly writes**: every write tool returns the
  delta it persisted so the agent loop can describe it back to the learner.
* **Resilient**: handlers convert exceptions into structured error payloads so
  one failing tool never aborts the loop.
* **Schema-driven**: each tool publishes a JSON Schema usable for
  ``response_format`` / ``tools=`` injection.

The registry stays focused: gather evidence, work the managed resource sandbox,
and commit explicit plan/library writes — never the learner's project code.
"""

from __future__ import annotations

import inspect
import logging
import re
from typing import Any

from ...evaluator.models import CheckResult, CheckStatus
from ...evaluator.verifiers import (
    DEFAULT_SUBJECT_FAMILY,
    LocalRubricReviewer,
    RubricItem,
    RubricSpec,
    VerifierPack,
    verifier_pack_for,
    verify_submission_with_pack,
)
from ...resources.search import citation_id_for
from ...training.card_request import DeliverableKind, normalize_deliverable_kind
from .organization_and_sandbox import (
    _slice_text_by_lines,
)
from .registry_core import (
    ToolContext,
    _leftover_training_persist_identity,
    _normalize_workspace_relpath,
    _resolve_workspace_root,
    _safe_path_under,
    _snapshot_file_listed,
    _snapshot_file_record,
)

logger = logging.getLogger("trainer.llm.tools")

_PRACTICE_SIGNAL_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "that",
    "this",
    "into",
    "when",
    "then",
    "should",
    "must",
    "have",
    "has",
    "use",
    "uses",
    "using",
    "add",
    "make",
    "create",
    "return",
    "returns",
    "value",
    "values",
    "file",
    "code",
    "current",
    "实现",
    "使用",
    "需要",
    "应该",
    "当前",
    "文件",
    "代码",
}


def _diagnostic_severity(diagnostic: Any) -> str:
    text = str(diagnostic or "").strip().lower()
    match = re.match(r"^\[(error|warning|info|hint|unknown)\]", text)
    if match:
        return match.group(1)
    if "error" in text or "错误" in text:
        return "error"
    if "warning" in text or "警告" in text:
        return "warning"
    if "hint" in text:
        return "hint"
    return "info" if text else "unknown"


def _practice_signals(text: str) -> list[str]:
    raw_tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_.$-]*|[\u4e00-\u9fff]{2,}", text)
    signals: list[str] = []
    for token in raw_tokens:
        normalized = token.strip("._-$").lower()
        if len(normalized) < 3 or normalized in _PRACTICE_SIGNAL_STOPWORDS:
            continue
        if normalized not in signals:
            signals.append(normalized)
    return signals[:8]


def _criterion_result(criterion: str, content_lower: str) -> dict[str, Any]:
    signals = _practice_signals(criterion)
    if not signals:
        criterion_lower = criterion.strip().lower()
        matched = bool(criterion_lower and criterion_lower in content_lower)
        return {
            "text": criterion,
            "status": "matched" if matched else "not_verifiable",
            "matched_signals": [criterion.strip()] if matched else [],
            "missing_signals": [] if matched else [criterion.strip()],
        }
    matched_signals = [signal for signal in signals if signal in content_lower]
    required_matches = 1 if len(signals) <= 2 else 2
    matched = len(matched_signals) >= required_matches
    return {
        "text": criterion,
        "status": "matched" if matched else "missing",
        "matched_signals": matched_signals,
        "missing_signals": [signal for signal in signals if signal not in matched_signals],
    }


async def _handle_verify_practice_current_file(
    context: ToolContext,
    args: dict[str, Any],
) -> dict[str, Any]:
    extra = context.extra if isinstance(context.extra, dict) else {}
    current_file = extra.get("current_file")
    text_submission = extra.get("text_submission")
    deliverable_kind = _practice_deliverable_kind(context, current_file if isinstance(current_file, dict) else None)

    if deliverable_kind == "text_payload" and not isinstance(current_file, dict):
        if isinstance(text_submission, dict):
            current_file = {
                "path": str(text_submission.get("path") or "card://text_payload"),
                "language_id": str(text_submission.get("language_id") or "markdown"),
                "content": str(text_submission.get("content") or text_submission.get("text") or ""),
                "diagnostics": text_submission.get("diagnostics") or [],
                "subject_family": text_submission.get("subject_family") or extra.get("subject_family") or "literature",
                "deliverable_kind": "text_payload",
                "card_config": text_submission.get("card_config"),
                "rubric_items": text_submission.get("rubric_items"),
                "anchor_text": text_submission.get("anchor_text"),
                "human_adopted": text_submission.get("human_adopted"),
                "locale": text_submission.get("locale"),
            }
        elif isinstance(text_submission, str):
            current_file = {
                "path": "card://text_payload",
                "language_id": "markdown",
                "content": text_submission,
                "diagnostics": [],
                "subject_family": extra.get("subject_family") or "literature",
                "deliverable_kind": "text_payload",
                "card_config": extra.get("card_config"),
                "rubric_items": extra.get("rubric_items"),
                "anchor_text": extra.get("anchor_text"),
                "human_adopted": extra.get("human_adopted"),
                "locale": extra.get("locale"),
            }

    if not isinstance(current_file, dict):
        return {
            "ok": False,
            "error": "no_current_file",
            "status": "blocked",
            "passed": False,
            "detail": "Practice verification requires the active IDE file snapshot.",
            "next_step": "Open the learner's implementation file and run Verify current file again.",
        }

    content = (
        current_file.get("content")
        or current_file.get("content_excerpt")
        or (current_file.get("text_payload") if deliverable_kind == "text_payload" else "")
        or ""
    )
    if not isinstance(content, str):
        content = str(content)
    if not content.strip():
        return {
            "ok": False,
            "error": "empty_current_file",
            "status": "blocked",
            "passed": False,
            "path": str(current_file.get("path") or "unknown"),
            "detail": "The active IDE file has no readable content.",
            "next_step": "Save or focus the implementation file, then verify the current file again.",
        }

    raw_diagnostics = current_file.get("diagnostics")
    diagnostics = [str(item) for item in raw_diagnostics if str(item).strip()] if isinstance(raw_diagnostics, list) else []
    error_diagnostics = [item for item in diagnostics if _diagnostic_severity(item) == "error"]
    warning_diagnostics = [item for item in diagnostics if _diagnostic_severity(item) == "warning"]
    allow_warnings = bool(args.get("allow_warnings") is True)

    # P1 #9 & #15: subject_family and deliverable_kind routing. The pack decides
    # *how* a practice submission is verified; unknown/absent families fall back
    # to the historical code lane unless deliverable_kind == "text_payload",
    # which routes to the rubric/hook pack lane (§7.2).
    family = _practice_subject_family(context, current_file)
    if family == DEFAULT_SUBJECT_FAMILY and deliverable_kind == "text_payload":
        family = "literature"
    pack = verifier_pack_for(family)
    if pack.subject_family != DEFAULT_SUBJECT_FAMILY or deliverable_kind == "text_payload":
        return _verify_practice_with_pack(
            pack,
            content=content,
            args=args,
            current_file=current_file,
            diagnostics=diagnostics,
            error_diagnostics=error_diagnostics,
            warning_diagnostics=warning_diagnostics,
            allow_warnings=allow_warnings,
            deliverable_kind=deliverable_kind,
        )

    criteria = [
        str(item).strip()
        for item in args.get("acceptance_criteria", [])
        if isinstance(item, str) and item.strip()
    ] if isinstance(args.get("acceptance_criteria"), list) else []
    expected_symbols = [
        str(item).strip()
        for item in args.get("expected_symbols", [])
        if isinstance(item, str) and item.strip()
    ] if isinstance(args.get("expected_symbols"), list) else []
    check_items = [*criteria, *expected_symbols]
    content_lower = content.lower()
    criterion_results = [_criterion_result(item, content_lower) for item in check_items]
    missing_results = [item for item in criterion_results if item.get("status") != "matched"]

    path = str(current_file.get("path") or "unknown")
    language_id = str(current_file.get("language_id") or "unknown")
    evidence = [
        f"Read active IDE file {path} ({language_id}).",
        f"Current file content length: {len(content)} characters.",
    ]
    if current_file.get("selection_range"):
        evidence.append(f"Selection attached: {current_file.get('selection_range')}.")
    if diagnostics:
        evidence.append(f"VS Code diagnostics attached: {len(diagnostics)}.")
    for item in criterion_results:
        if item.get("status") == "matched":
            evidence.append(f"Matched: {item.get('text')}")

    if error_diagnostics:
        status = "blocked"
        passed = False
        reason = "error_diagnostics"
        summary = "Current-file practice verification is blocked by VS Code error diagnostics."
        next_step = "Fix the error diagnostics in the active file, then run Verify current file again."
    elif warning_diagnostics and not allow_warnings:
        status = "needs_review"
        passed = False
        reason = "warning_diagnostics"
        summary = "The active file was read, but warning diagnostics need review before marking the practice passed."
        next_step = "Review the warning diagnostics or rerun verification with warnings explicitly allowed."
    elif not check_items:
        status = "needs_review"
        passed = False
        reason = "missing_acceptance_criteria"
        summary = "The active file was read, but no acceptance criteria were supplied."
        next_step = "Provide concrete acceptance criteria or expected symbols for this practice card."
    elif missing_results:
        status = "needs_review"
        passed = False
        reason = "missing_acceptance_signals"
        matched_count = len(criterion_results) - len(missing_results)
        missing_texts = [
            str(item.get("text") or "").strip() for item in missing_results
        ]
        missing_texts = [text for text in missing_texts if text]
        missing_preview = "; ".join(missing_texts[:3])
        summary = (
            f"The active file was read: {matched_count}/{len(criterion_results)} "
            "acceptance signals matched."
        )
        if missing_preview:
            summary = f"{summary} Still missing: {missing_preview}."
        else:
            summary = f"{summary} Some signals still need current-file evidence."
        if missing_texts:
            next_step = (
                f"Implement the missing acceptance signals (starting with "
                f"\"{missing_texts[0]}\"), then run Verify current file again."
            )
        else:
            next_step = "Implement the missing acceptance signals, then run Verify current file again."
    else:
        status = "passed"
        passed = True
        reason = "all_signals_matched"
        summary = "The active IDE file matches the supplied practice acceptance signals with no blocking diagnostics."
        next_step = "Return to Training and mark the practice result as verified evidence."

    try:
        max_evidence = max(1, min(int(args.get("max_evidence", 8) or 8), 20))
    except Exception as exc:
        logger.debug("Suppressed exception in verification_and_excerpt: %s", exc)
        max_evidence = 8

    payload = {
        "ok": True,
        "tool": "verify_practice_current_file",
        "status": status,
        "passed": passed,
        "reason": reason,
        "evidence_source": "ide_current_file",
        "path": path,
        "language_id": language_id,
        "diagnostics_count": len(diagnostics),
        "blocking_diagnostics": error_diagnostics[:8],
        "warning_diagnostics": warning_diagnostics[:8],
        "criteria": criterion_results,
        "matched_signal_count": max(0, len(criterion_results) - len(missing_results)),
        "total_signal_count": len(criterion_results),
        "evidence": evidence[:max_evidence],
        "summary": summary,
        "next_step": next_step,
    }
    persistence = (
        _persist_practice_verification_result(
            context,
            payload=payload,
            args=args,
            current_file=current_file,
            missing_results=missing_results,
        )
        if pack.persists_practice_evidence
        else {}
    )
    if persistence:
        payload.update(persistence)
    return payload


def _practice_subject_family(context: ToolContext, current_file: dict[str, Any]) -> str:
    """Host-trusted subject family for practice routing (P1 #9).

    Only host-supplied data may name a family: the file snapshot the IDE sent
    and the coach context the host assembled. Tool *arguments* are
    model-authored, so accepting a family from there would let a model pick
    its own (weaker) verifier — the exact fail-open this routing must not have.
    """
    extra = context.extra if isinstance(context.extra, dict) else {}
    for candidate in (current_file.get("subject_family"), extra.get("subject_family")):
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip().lower()
    return DEFAULT_SUBJECT_FAMILY


def _practice_deliverable_kind(
    context: ToolContext,
    current_file: dict[str, Any] | None,
) -> DeliverableKind:
    """Host-trusted deliverable carrier (P1 #15, §7.2).

    Only host-supplied context or file snapshot may declare ``text_payload`` vs
    ``file_based``; model tool arguments are never consulted.
    """
    extra = context.extra if isinstance(context.extra, dict) else {}
    raw_kind: str | None = None
    for candidate in (
        current_file.get("deliverable_kind") if isinstance(current_file, dict) else None,
        extra.get("deliverable_kind"),
    ):
        if isinstance(candidate, str) and candidate.strip():
            raw_kind = candidate.strip().lower()
            break
    if raw_kind in {"file_based", "text_payload"}:
        return normalize_deliverable_kind(raw_kind)
    if "text_submission" in extra and not isinstance(current_file, dict):
        return "text_payload"
    return "file_based"


def _acceptance_signal_check(
    criterion_results: list[dict[str, Any]],
    missing_results: list[dict[str, Any]],
) -> CheckResult:
    """The acceptance-signal match, as a deterministic in-process check.

    The code lane reports these matches as evidence text only; a non-command
    pack needs them as a *check* so ``combine_verdict`` can count them toward
    "at least one deterministic pass". Matching stays the historical substring
    rule — no new leniency is introduced by routing. Zero criteria yields
    SKIPPED, never PASSED: an empty requirement list must not read as evidence.
    """
    total = len(criterion_results)
    if total == 0:
        return CheckResult(
            name="acceptance-signals",
            status=CheckStatus.SKIPPED,
            summary="No acceptance criteria were supplied for this practice card.",
        )
    matched = max(0, total - len(missing_results))
    return CheckResult(
        name="acceptance-signals",
        status=CheckStatus.PASSED if matched == total else CheckStatus.FAILED,
        summary=f"{matched}/{total} acceptance signals matched in the submission",
    )


def _host_rubric_spec(current_file: dict[str, Any]) -> RubricSpec | None:
    """Build a card's rubric from host-supplied data, never from model args.

    Items missing a statement or an anchor are dropped rather than repaired:
    ``RubricItem`` refuses anchor-free criteria, and a repair here would let an
    anchor-free rubric reach the reviewer through the back door.
    """
    raw_items = current_file.get("rubric_items")
    if not isinstance(raw_items, list):
        return None
    items: list[RubricItem] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        raw_criteria = raw.get("criteria")
        try:
            items.append(
                RubricItem(
                    statement=str(raw.get("statement") or ""),
                    anchor=str(raw.get("anchor") or ""),
                    criteria=(
                        tuple(str(entry) for entry in raw_criteria)
                        if isinstance(raw_criteria, (list, tuple))
                        else ()
                    ),
                )
            )
        except ValueError:
            continue
    if not items:
        return None
    anchor_text = current_file.get("anchor_text")
    return RubricSpec(
        items=tuple(items),
        anchor_text=str(anchor_text) if isinstance(anchor_text, str) else "",
    )


def _verify_practice_with_pack(
    pack: VerifierPack,
    *,
    content: str,
    args: dict[str, Any],
    current_file: dict[str, Any],
    diagnostics: list[str],
    error_diagnostics: list[str],
    warning_diagnostics: list[str],
    allow_warnings: bool,
    deliverable_kind: DeliverableKind = "file_based",
) -> dict[str, Any]:
    """Non-command practice lane (P1 #9): hooks + anchor-forced rubric.

    Blocking IDE diagnostics gate every family, so a text submission sitting in
    a file the language server flags is not verified either. The verdict is
    reported honestly — ``needs_review`` whenever deterministic evidence is
    missing — and evidence minting stays behind ``pack.persists_practice_evidence``
    so a pack whose source is not whitelisted can never write training evidence.
    """
    path = str(current_file.get("path") or "unknown")
    language_id = str(current_file.get("language_id") or "unknown")

    criteria = [
        str(item).strip()
        for item in args.get("acceptance_criteria", [])
        if isinstance(item, str) and item.strip()
    ] if isinstance(args.get("acceptance_criteria"), list) else []
    expected_symbols = [
        str(item).strip()
        for item in args.get("expected_symbols", [])
        if isinstance(item, str) and item.strip()
    ] if isinstance(args.get("expected_symbols"), list) else []
    check_items = [*criteria, *expected_symbols]
    content_lower = content.lower()
    criterion_results = [_criterion_result(item, content_lower) for item in check_items]
    missing_results = [item for item in criterion_results if item.get("status") != "matched"]

    try:
        max_evidence = max(1, min(int(args.get("max_evidence", 8) or 8), 20))
    except Exception as exc:
        logger.debug("Suppressed exception in verification_and_excerpt: %s", exc)
        max_evidence = 8

    card_config = current_file.get("card_config")
    rubric = _host_rubric_spec(current_file)
    human_adopted = current_file.get("human_adopted") is True
    locale = str(current_file.get("locale") or "").strip() or None
    verdict = verify_submission_with_pack(
        pack,
        submission=content,
        card_config=card_config if isinstance(card_config, dict) else None,
        rubric=rubric,
        human_adopted=human_adopted,
        locale=locale,
        extra_deterministic=(_acceptance_signal_check(criterion_results, missing_results),),
    )

    evidence = [
        f"Read active IDE file {path} ({language_id}) for subject family '{pack.subject_family}'.",
        f"Submission length: {len(content)} characters.",
        f"Deterministic checks run: {len(verdict.hook_results)}.",
    ]
    for result in verdict.hook_results:
        evidence.append(f"{result.name}: {result.status.value} — {result.summary}")
    if verdict.rubric_review is not None:
        review = verdict.rubric_review
        graded = len(review.matched) + len(review.missing)
        evidence.append(
            f"Rubric review ({review.source}): {len(review.matched)}/{graded} items matched."
            if graded
            else f"Rubric review ({review.source}): {review.summary}"
        )
    for item in criterion_results:
        if item.get("status") == "matched":
            evidence.append(f"Matched: {item.get('text')}")

    hook_errors = [
        result for result in verdict.hook_results if result.status == CheckStatus.ERROR
    ]
    if error_diagnostics:
        status = "blocked"
        passed = False
        reason = "error_diagnostics"
        summary = "Practice verification is blocked by VS Code error diagnostics."
        next_step = "Fix the error diagnostics in the active file, then run Verify current file again."
    elif warning_diagnostics and not allow_warnings:
        status = "needs_review"
        passed = False
        reason = "warning_diagnostics"
        summary = "The submission was read, but warning diagnostics need review before it can pass."
        next_step = "Review the warning diagnostics or rerun verification with warnings explicitly allowed."
    elif hook_errors:
        status = "blocked"
        passed = False
        reason = "verifier_error"
        summary = f"A deterministic check crashed: {hook_errors[0].name} — {hook_errors[0].summary}."
        next_step = "Fix the card's verification declaration, then run Verify current file again."
    elif verdict.status == CheckStatus.PASSED:
        status = "passed"
        passed = True
        reason = "pack_checks_passed"
        summary = verdict.summary
        next_step = "Return to Training and mark the practice result as verified evidence."
    elif verdict.status == CheckStatus.FAILED:
        status = "needs_review"
        passed = False
        reason = "failed_deterministic_checks"
        failed_names = [
            result.name
            for result in verdict.hook_results
            if result.status == CheckStatus.FAILED
        ]
        if failed_names:
            summary = f"{verdict.summary} Failing checks: {', '.join(failed_names[:3])}."
        else:
            summary = verdict.summary
        next_step = "Revise the submission to satisfy the failing checks, then run Verify current file again."
    else:
        status = "needs_review"
        passed = False
        reason = "deterministic_evidence_required"
        summary = verdict.summary
        next_step = (
            "Semantic review alone cannot verify a submission; satisfy at least one "
            "deterministic check or have the card adopted explicitly, then verify again."
        )

    payload: dict[str, Any] = {
        "ok": True,
        "tool": "verify_practice_current_file",
        "status": status,
        "passed": passed,
        "reason": reason,
        "subject_family": pack.subject_family,
        "deliverable_kind": deliverable_kind,
        "evidence_source": pack.evidence_source,
        "path": path,
        "language_id": language_id,
        "diagnostics_count": len(diagnostics),
        "blocking_diagnostics": error_diagnostics[:8],
        "warning_diagnostics": warning_diagnostics[:8],
        "criteria": criterion_results,
        "matched_signal_count": max(0, len(criterion_results) - len(missing_results)),
        "total_signal_count": len(criterion_results),
        "deterministic_checks": [
            {"name": result.name, "status": result.status.value, "summary": result.summary}
            for result in verdict.hook_results
        ],
        "rubric_review": (
            {
                "status": verdict.rubric_review.status.value,
                "summary": verdict.rubric_review.summary,
                "matched": list(verdict.rubric_review.matched),
                "missing": list(verdict.rubric_review.missing),
                "source": verdict.rubric_review.source,
            }
            if verdict.rubric_review is not None
            else None
        ),
        "evidence": evidence[:max_evidence],
        "summary": summary,
        "next_step": next_step,
        "practice_evidence_persisted": False,
    }
    if not pack.persists_practice_evidence:
        payload["evidence_trust_note"] = (
            f"'{pack.evidence_source}' is not yet a host-trusted verification source, "
            "so this verdict informs coaching but cannot mint training evidence."
        )
    return payload


def _excerpt_sentence_list(text: str) -> list[str]:
    """Split text into sentences with CJK-aware terminators (deterministic)."""
    sentences: list[str] = []
    current: list[str] = []
    for char in str(text or "").strip():
        current.append(char)
        if char in "。！？!?…；;":
            candidate = "".join(current).strip()
            if candidate:
                sentences.append(candidate)
            current = []
    tail = "".join(current).strip()
    if tail:
        sentences.append(tail)
    return sentences


def _sentence_stats(sentences: list[str]) -> dict[str, Any]:
    lengths = [len("".join(s.split())) for s in sentences if s.strip()]
    if not lengths:
        return {"sentence_count": 0, "mean_length": 0.0, "std_length": 0.0}
    mean = sum(lengths) / len(lengths)
    variance = sum((value - mean) ** 2 for value in lengths) / len(lengths)
    return {
        "sentence_count": len(lengths),
        "mean_length": round(mean, 2),
        "std_length": round(variance ** 0.5, 2),
    }


def _punctuation_density(text: str) -> float:
    if not text:
        return 0.0
    punctuation = sum(1 for char in text if char in "，。、；：？！""''（）[]《》“”\",.!?;:()[]{}")
    return round(punctuation * 100 / max(1, len(text)), 2)


def _compare_deterministic_signals(anchor_text: str, submission: str) -> dict[str, Any]:
    """Deterministic imitation-comparison statistics (no semantic judgment)."""
    anchor_stats = _sentence_stats(_excerpt_sentence_list(anchor_text))
    submission_stats = _sentence_stats(_excerpt_sentence_list(submission))
    delta = round(abs(anchor_stats["mean_length"] - submission_stats["mean_length"]), 2)
    rhythm_similarity = max(0.0, 1.0 - delta / max(1.0, anchor_stats["mean_length"] or 1.0))
    return {
        "anchor": {**anchor_stats, "punctuation_density": _punctuation_density(anchor_text)},
        "submission": {**submission_stats, "punctuation_density": _punctuation_density(submission)},
        "mean_sentence_length_delta": delta,
        "rhythm_similarity": round(rhythm_similarity, 3),
        "lane": "deterministic",
        "evidence_bearing": False,
    }


async def _resolve_excerpt_resource(context: ToolContext, args: dict[str, Any]) -> tuple[Any | None, str | None]:
    resource_service = getattr(context.runtime, "resource_service", None)
    if resource_service is None:
        return None, "service_unavailable"
    registry = getattr(resource_service, "registry", None)
    if registry is None:
        return None, "registry_unavailable"
    resource_id = str(args.get("resource_id") or "").strip()
    if resource_id:
        record = _workspace_scoped_registry_resource(context, resource_id)
        if record is None:
            return None, "resource_not_found"
        return record, None
    query = str(args.get("query") or "").strip()
    if not query:
        return None, "missing_selector"
    search = getattr(resource_service, "search_resources", None)
    if search is None:
        search = getattr(resource_service, "search", None)
    if search is None:
        return None, "unsupported"
    try:
        response = search(workspace_id=context.workspace_id, query=query, top_k=1)
        if inspect.isawaitable(response):
            response = await response
    except Exception as exc:
        logger.debug("Suppressed exception in verification_and_excerpt: %s", exc)
        return None, f"search_failed: {exc.__class__.__name__}"
    hits = getattr(response, "hits", None)
    if hits is None and isinstance(response, dict):
        hits = response.get("hits")
    record = None
    if hits:
        first = hits[0]
        candidate_id = getattr(first, "resource_id", None)
        if candidate_id is None and isinstance(first, dict):
            candidate_id = first.get("resource_id") or first.get("id")
        if candidate_id:
            record = _workspace_scoped_registry_resource(context, str(candidate_id))
    if record is None:
        return None, "no_resource_match"
    return record, None


def _canonical_excerpt_fallback(
    context: ToolContext,
    record: Any,
    args: dict[str, Any],
) -> dict[str, Any] | None:
    """Read excerpts from the durable canonical Markdown after a restart.

    The in-process chunk registry is empty on a fresh sidecar, but the Markdown
    digest on disk (and the persisted search index) still holds the text.
    """

    service = getattr(context.runtime, "resource_service", None)
    reader = getattr(service, "read_canonical_text", None)
    if not callable(reader):
        return None
    try:
        text = reader(context.workspace_id, str(getattr(record, "id", "") or ""))
    except Exception as exc:
        logger.debug("Suppressed exception in verification_and_excerpt: %s", exc)
        return None
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        max_chars = max(200, min(int(args.get("chars", 1600) or 1600), 4000))
    except Exception as exc:
        logger.debug("Suppressed exception in verification_and_excerpt: %s", exc)
        max_chars = 1600
    anchor = str(args.get("anchor_id") or "").strip()
    excerpt = text.strip()
    start_line = 1
    page_match = re.search(r"page(\d+)@", anchor)
    if page_match:
        page = page_match.group(1)
        marker = f"<!-- page: {page} -->"
        position = excerpt.find(marker)
        if position >= 0:
            start_line = excerpt.count("\n", 0, position) + 1
            following = excerpt.find("<!-- page:", position + len(marker))
            excerpt = excerpt[position + len(marker) : following if following > 0 else None]
    else:
        line_match = re.search(r"@(\d+)$", anchor)
        if line_match:
            start_line = max(1, int(line_match.group(1)))
            lines = excerpt.splitlines()
            excerpt = "\n".join(lines[start_line - 1 :])
    excerpt = excerpt.strip()
    truncated = len(excerpt) > max_chars
    if truncated:
        excerpt = excerpt[:max_chars] + "…"
    current_version = _current_resource_version(context, record)
    resource_display = _resource_display(record)
    return {
        "ok": True,
        "tool": "read_resource_excerpt",
        "read_only": True,
        "resource": resource_display,
        "excerpts": [
            {
                "anchor_id": anchor or f"¶chunk:0@{start_line}",
                "paragraph_anchor": anchor or None,
                "text": excerpt,
                "start_line": start_line,
                "end_line": None,
                "citation_id": None,
                "version_id": current_version.get("version_id")
                or resource_display.get("version_id"),
                "content_hash": current_version.get("content_hash")
                or resource_display.get("content_hash"),
                "location": {
                    "anchor": anchor or f"¶chunk:0@{start_line}",
                    "start_line": start_line,
                },
                "truncated": truncated,
            }
        ],
        "note": (
            "Excerpts come from the canonical Markdown document; the chunk "
            "registry was empty (for example after a sidecar restart)."
        ),
    }


def _repository_resource(context: ToolContext, resource_id: str) -> Any | None:
    """Look up a resource in durable storage when the in-memory registry is cold.

    A restarted sidecar starts with an empty registry; the repository still has
    every resource record, so read-only tools keep working.
    """

    repository = getattr(context.runtime, "repository", None)
    lister = getattr(repository, "list_resources", None)
    if not callable(lister):
        return None
    try:
        returned = lister(context.workspace_id)
    except Exception as exc:
        logger.debug("Suppressed exception in verification_and_excerpt: %s", exc)
        return None
    if not isinstance(returned, list):
        return None
    for item in returned:
        if str(getattr(item, "id", "") or "") == resource_id:
            return item
    return None


def _workspace_scoped_registry_resource(context: ToolContext, resource_id: str) -> Any | None:
    """Resolve a resource only when it belongs to the current workspace.

    The in-process registry is shared by every workspace in the sidecar, so a
    raw ``registry.get(resource_id)`` can cross the workspace boundary. The
    durable repository is the authority; the registry remains a fallback only
    for embedded/test runtimes that have no repository lister at all.
    """

    durable = _repository_resource(context, resource_id)
    if durable is not None:
        return durable
    repository = getattr(context.runtime, "repository", None)
    lister = getattr(repository, "list_resources", None)
    if callable(lister):
        return None
    resource_service = getattr(context.runtime, "resource_service", None)
    registry = getattr(resource_service, "registry", None)
    return registry.get(resource_id) if registry is not None else None


def _resource_fragments(resource: Any) -> list[dict[str, Any]]:
    """Knowledge fragments for either resource record shape.

    The registry dataclass stores them under ``metadata["knowledge_fragments"]``;
    the API Pydantic model also carries a top-level ``knowledge_fragments`` list.
    """
    fragments: Any = getattr(resource, "knowledge_fragments", None)
    if not isinstance(fragments, list):
        metadata = getattr(resource, "metadata", None)
        fragments = metadata.get("knowledge_fragments") if isinstance(metadata, dict) else None
    return [item for item in fragments if isinstance(item, dict)] if isinstance(fragments, list) else []


def _fragment_for_anchor(resource: Any, anchor_id: str) -> dict[str, Any] | None:
    """Return the knowledge fragment that carries this ¶ anchor, when present."""
    for fragment in _resource_fragments(resource):
        if fragment.get("paragraph_anchor") == anchor_id:
            return fragment
    return None


def _citation_for_anchor(resource: Any, anchor_id: str) -> str | None:
    """Look up the version-scoped citation for a ¶ anchor, when present."""
    fragment = _fragment_for_anchor(resource, anchor_id)
    if fragment is None:
        return None
    citation = fragment.get("citation_id")
    if isinstance(citation, str) and citation.strip():
        return citation
    return None


def _resource_display(resource: Any) -> dict[str, Any]:
    """Display fields for either resource record shape."""
    metadata = getattr(resource, "metadata", None)
    metadata = metadata if isinstance(metadata, dict) else {}
    name = str(getattr(resource, "name", None) or getattr(resource, "title", None) or "")
    source = str(
        getattr(resource, "canonical_source", None)
        or getattr(resource, "source", None)
        or getattr(resource, "source_uri", None)
        or ""
    )
    kind = getattr(resource, "kind", None)
    kind = getattr(kind, "value", kind)  # ResourceKind enum (registry dataclass shape)
    fragments = _resource_fragments(resource)
    first_fragment = fragments[0] if fragments else {}
    return {
        "id": str(resource.id),
        "name": name,
        "kind": str(kind or ""),
        "source": source,
        "content_language": (
            getattr(resource, "content_language", None) or metadata.get("content_language") or None
        ),
        "content_hash": (
            getattr(resource, "content_hash", None)
            or metadata.get("content_hash")
            or first_fragment.get("content_hash")
            or None
        ),
        "version_id": first_fragment.get("version_id") or None,
        "trust_score": getattr(resource, "trust_score", None),
        "freshness": getattr(resource, "freshness", None),
    }


def _chunk_for_anchor(chunks: list[Any], anchor_id: str) -> list[Any]:
    """Resolve an anchor id to the chunks that contain its location.

    Handles exact chunk ids, synthetic ``¶chunk:order@line`` anchors, and real
    heading/page/slide anchors (``¶h2@5``, ``¶page3@42``). The line fallback
    matters for long documents: only the first few chunks may have knowledge
    fragments, but every heading/page line still belongs to a chunk.
    """

    matched = [c for c in chunks if getattr(c, "chunk_id", None) == anchor_id]
    if matched:
        return matched
    matched = [
        c for c in chunks
        if f"¶chunk:{getattr(c, 'order', 0)}@{getattr(c, 'start_line', 0)}" == anchor_id
    ]
    if matched:
        return matched
    line_match = re.search(r"@(\d+)$", anchor_id)
    if line_match:
        line = int(line_match.group(1))
        containing = [
            c
            for c in chunks
            if (getattr(c, "start_line", None) or 0) <= line
            and (getattr(c, "end_line", None) or getattr(c, "start_line", None) or 0) >= line
        ]
        if containing:
            return containing[:1]
        following = [
            c for c in chunks if (getattr(c, "start_line", None) or 0) >= line
        ]
        if following:
            return sorted(following, key=lambda c: getattr(c, "start_line", 0))[:1]
    return []


def _chunk_id_for_paragraph_anchor(resource: Any, anchor_id: str) -> str | None:
    fragment = _fragment_for_anchor(resource, anchor_id)
    if fragment is None:
        return None
    location = fragment.get("location")
    if isinstance(location, dict) and location.get("chunk_id"):
        return str(location["chunk_id"])
    return None


def _current_resource_version(context: ToolContext, resource: Any) -> dict[str, Any]:
    """Best-effort current version for a resource; never blocks the read."""

    store = getattr(context.runtime, "resource_version_store", None)
    current_version = getattr(store, "current_version", None)
    if not callable(current_version):
        return {}
    try:
        payload = current_version(context.workspace_id, str(getattr(resource, "id", "") or ""))
    except Exception as exc:
        logger.debug("Suppressed exception in verification_and_excerpt: %s", exc)
        return {}
    return payload if isinstance(payload, dict) else {}


async def _handle_read_resource_excerpt(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Read a real excerpt from the resource library (read-only, P2 #15).

    Serves actual chunk text — never fabricated — and pins every excerpt to
    its stable ¶ anchor plus the version-scoped citation when the fragment is
    available, so coach answers can cite the passage without drifting on
    re-layout.
    """
    record, error = await _resolve_excerpt_resource(context, args)
    if record is None:
        if error in {"missing_selector"}:
            return {
                "ok": False,
                "error": error,
                "detail": "read_resource_excerpt requires resource_id or query.",
            }
        return {"ok": False, "error": error or "read_failed"}
    resource_service = getattr(context.runtime, "resource_service", None)
    registry = getattr(resource_service, "registry", None)
    chunks = registry.list_chunks(record.id) if registry is not None else []
    if not chunks:
        fallback_text = _canonical_excerpt_fallback(context, record, args)
        if fallback_text:
            return fallback_text
        return {
            "ok": False,
            "error": "index_missing",
            "detail": (
                "This resource has no indexed chunks yet; index it (or upload a "
                "text-bearing copy) before asking for excerpts."
            ),
            "resource_id": record.id,
        }
    anchor_id = str(args.get("anchor_id") or "").strip()
    anchor_line_match = re.search(r"@(\d+)$", anchor_id) if anchor_id else None
    anchor_line = int(anchor_line_match.group(1)) if anchor_line_match else None
    selected: list[Any] = []
    if anchor_id:
        matched = _chunk_for_anchor(chunks, anchor_id)
        if not matched:
            fragment_chunk_id = _chunk_id_for_paragraph_anchor(record, anchor_id)
            if fragment_chunk_id:
                matched = [c for c in chunks if getattr(c, "chunk_id", None) == fragment_chunk_id]
        if not matched:
            return {
                "ok": False,
                "error": "anchor_not_found",
                "detail": f"No chunk matches anchor {anchor_id!r}.",
                "resource_id": record.id,
                "available_anchors": [
                    f"¶chunk:{getattr(c, 'order', i)}@{getattr(c, 'start_line', 0)}"
                    for i, c in enumerate(chunks[:12])
                ],
            }
        selected = matched
    else:
        selected = list(chunks[:3])
    try:
        max_chars = max(200, min(int(args.get("chars", 1600) or 1600), 4000))
    except Exception as exc:
        logger.debug("Suppressed exception in verification_and_excerpt: %s", exc)
        max_chars = 1600
    per_excerpt = max(200, max_chars // max(1, len(selected)))
    resource_display = _resource_display(record)
    current_version = _current_resource_version(context, record)
    excerpts: list[dict[str, Any]] = []
    for chunk in selected:
        text = str(getattr(chunk, "text", "") or "").strip()
        if not text:
            continue
        chunk_anchor = f"¶chunk:{getattr(chunk, 'order', 0)}@{getattr(chunk, 'start_line', 0)}"
        truncated = len(text) > per_excerpt
        if truncated:
            text = text[:per_excerpt] + "…"
        # A real paragraph anchor (EPUB spine / PDF page) carries its fragment's
        # citation; the synthetic chunk anchor is the fallback identity.
        fragment_anchor = anchor_id or chunk_anchor
        fragment = _fragment_for_anchor(record, fragment_anchor)
        excerpt_version = (
            (fragment or {}).get("version_id")
            or current_version.get("version_id")
            or resource_display.get("version_id")
        )
        citation = (
            (_citation_for_anchor(record, anchor_id) if anchor_id else None)
            or _citation_for_anchor(record, chunk_anchor)
            or citation_id_for(record.id, excerpt_version)
        )
        raw_fragment_location = fragment.get("location") if isinstance(fragment, dict) else None
        fragment_location: dict[str, Any] = (
            dict(raw_fragment_location) if isinstance(raw_fragment_location, dict) else {}
        )
        excerpt_location = dict(fragment_location)
        excerpt_location.setdefault("anchor", chunk_anchor)
        if anchor_line is not None:
            excerpt_location["start_line"] = anchor_line
        elif getattr(chunk, "start_line", None) is not None:
            excerpt_location.setdefault("start_line", getattr(chunk, "start_line", None))
        if getattr(chunk, "end_line", None) is not None:
            excerpt_location.setdefault("end_line", getattr(chunk, "end_line", None))
        current_version_id = current_version.get("version_id")
        stale = bool(
            excerpt_version and current_version_id and excerpt_version != current_version_id
        )
        excerpts.append({
            "anchor_id": chunk_anchor,
            "paragraph_anchor": anchor_id or None,
            "text": text,
            "start_line": anchor_line
            if anchor_line is not None
            else getattr(chunk, "start_line", None),
            "end_line": getattr(chunk, "end_line", None),
            "citation_id": citation,
            "version_id": excerpt_version,
            "content_hash": (
                (fragment or {}).get("content_hash")
                or current_version.get("content_hash")
                or resource_display.get("content_hash")
            ),
            "location": excerpt_location,
            "truncated": truncated,
            "stale": stale,
            "current_version_id": current_version_id if stale else None,
            "current_content_hash": (
                current_version.get("content_hash") if stale else None
            ),
        })
    return {
        "ok": True,
        "tool": "read_resource_excerpt",
        "read_only": True,
        "resource": resource_display,
        "excerpts": excerpts,
        "note": (
            "Excerpts come from indexed chunk text with stable ¶ anchors; cite the "
            "anchor or citation id instead of re-describing the passage."
        ),
    }


async def _handle_compare_with_anchor(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Imitation comparison (P2 #15): deterministic stats against an anchor.

    The anchor can come inline (``anchor_text``) or from the library
    (``resource_id`` + ``anchor_id`` → real chunk text). This tool only
    produces deterministic signals — it never upgrades evidence, never
    verifies, and says so in every response.
    """
    submission = str(args.get("submission") or "").strip()
    if not submission:
        return {
            "ok": False,
            "error": "missing_submission",
            "detail": "compare_with_anchor requires the learner's submission text.",
        }
    anchor_text = str(args.get("anchor_text") or "").strip()
    anchor_citation: str | None = None
    anchor_resource: dict[str, Any] | None = None
    if not anchor_text:
        resource_id = str(args.get("resource_id") or "").strip()
        anchor_id = str(args.get("anchor_id") or "").strip()
        if not resource_id or not anchor_id:
            return {
                "ok": False,
                "error": "missing_anchor",
                "detail": (
                    "Provide anchor_text, or resource_id + anchor_id to load the "
                    "anchor passage from the resource library."
                ),
            }
        record, error = await _resolve_excerpt_resource(context, {"resource_id": resource_id})
        if record is None:
            return {"ok": False, "error": error or "anchor_unavailable"}
        resource_service = getattr(context.runtime, "resource_service", None)
        registry = getattr(resource_service, "registry", None)
        chunks = registry.list_chunks(record.id) if registry is not None else []
        matched = _chunk_for_anchor(chunks, anchor_id)
        if not matched:
            fragment_chunk_id = _chunk_id_for_paragraph_anchor(record, anchor_id)
            if fragment_chunk_id:
                matched = [c for c in chunks if getattr(c, "chunk_id", None) == fragment_chunk_id]
        if not matched:
            return {
                "ok": False,
                "error": "anchor_not_found",
                "detail": f"No chunk matches anchor {anchor_id!r}.",
                "resource_id": record.id,
            }
        anchor_text = str(getattr(matched[0], "text", "") or "").strip()
        anchor_citation = _citation_for_anchor(record, anchor_id)
        display = _resource_display(record)
        anchor_resource = {"id": display["id"], "name": display["name"], "source": display["source"]}
    if not anchor_text:
        return {"ok": False, "error": "empty_anchor", "detail": "The resolved anchor passage is empty."}
    signals = _compare_deterministic_signals(anchor_text, submission)
    return {
        "ok": True,
        "tool": "compare_with_anchor",
        "read_only": True,
        "anchor": {
            "resource": anchor_resource,
            "anchor_id": str(args.get("anchor_id") or "") or None,
            "citation_id": anchor_citation,
            "chars": len(anchor_text),
        },
        "signals": signals,
        "interpretation": (
            "Rhythm similarity is a deterministic ratio of mean sentence-length "
            "agreement; it says nothing about intent or quality."
        ),
        "evidence_note": (
            "Deterministic comparison alone never verifies a practice; evidence "
            "still flows only through the training verification flow with the "
            "trusted-source whitelist."
        ),
    }


async def _handle_run_rubric_review(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Explicitly-gated rubric review (P2 #15).

    The rubric ALWAYS comes from the host card context (``rubric_items`` on
    the host current_file) — never from model-authored arguments — and the
    reviewer lane is the deterministic local one. The result is advisory to
    the conversation: it never mints evidence on its own (§2.2 P4 fail-closed).
    """
    extra = context.extra if isinstance(context.extra, dict) else {}
    submission = str(args.get("submission") or "").strip()
    if not submission:
        return {
            "ok": False,
            "error": "missing_submission",
            "detail": "run_rubric_review requires the submission text to review.",
        }
    current_file = extra.get("current_file")
    rubric = _host_rubric_spec(current_file) if isinstance(current_file, dict) else None
    if rubric is None:
        # text_payload lane: the host also delivers the card rubric on the
        # text_submission payload (same host data, different carrier).
        text_submission = extra.get("text_submission")
        if isinstance(text_submission, dict) and isinstance(text_submission.get("rubric_items"), list):
            rubric = _host_rubric_spec({
                "rubric_items": text_submission.get("rubric_items"),
                "anchor_text": text_submission.get("anchor_text"),
            })
    if rubric is None:
        return {
            "ok": False,
            "error": "host_rubric_missing",
            "detail": (
                "run_rubric_review needs a host-supplied card rubric "
                "(rubric_items with non-empty anchors). Model-authored rubrics "
                "are refused by design."
            ),
        }
    review = LocalRubricReviewer().review(rubric, submission)
    return {
        "ok": True,
        "tool": "run_rubric_review",
        "read_only": True,
        "rubric_source": "host_card",
        "reviewer_lane": review.source,
        "status": review.status.value,
        "summary": review.summary,
        "matched": list(review.matched),
        "missing": list(review.missing),
        "item_count": len(rubric.items),
        "evidence_bearing": False,
        "note": (
            "Rubric review alone is not evidence: verification still requires a "
            "deterministic pass (or explicit human adoption) through the "
            "training verification flow."
        ),
    }


def _persist_practice_verification_result(
    context: ToolContext,
    *,
    payload: dict[str, Any],
    args: dict[str, Any],
    current_file: dict[str, Any],
    missing_results: list[dict[str, Any]],
) -> dict[str, Any]:
    runtime = context.runtime
    memory_service = getattr(runtime, "memory_service", None) if runtime is not None else None
    if memory_service is None or not hasattr(memory_service, "record_training_practice_evaluation_result"):
        return {}

    workspace_id = context.workspace_id
    card_id, card_title, focus_area = _training_card_context_for_persistence(
        context,
        args=args,
        current_file=current_file,
    )
    if not card_id and not card_title:
        return {}

    failed_checks = _practice_failed_checks(payload)
    missing_requirements = [
        str(item.get("text") or "").strip()
        for item in missing_results
        if str(item.get("text") or "").strip()
    ]
    if not missing_requirements and payload.get("passed") is False:
        missing_requirements = [
            str(item).strip()
            for item in [
                *(payload.get("blocking_diagnostics") or []),
                *(payload.get("warning_diagnostics") or []),
            ]
            if str(item).strip()
        ]
    try:
        workspace_update = memory_service.record_training_practice_evaluation_result(
            workspace_id=workspace_id,
            card_id=card_id,
            card_title=card_title,
            passed=bool(payload.get("passed")),
            summary=str(payload.get("summary") or ""),
            next_step=str(payload.get("next_step") or ""),
            focus_area=focus_area or str(current_file.get("path") or "practice verification"),
            failed_checks=failed_checks,
            missing_requirements=missing_requirements,
            evidence_source=str(payload.get("evidence_source") or "ide_current_file"),
            # This lane matches acceptance strings and diagnostics; it has no
            # executed controlled check, so it must stay self-reported/unverified.
            verified_by_evaluator=False,
        )
    except Exception as exc:
        logger.debug("Suppressed exception in verification_and_excerpt: %s", exc)
        return {
            "persisted_training_evidence": False,
            "training_evidence_error": exc.__class__.__name__,
            "training_evidence_detail": str(exc),
        }
    from ...training.reliability import busy_marker

    busy = busy_marker(workspace_update)
    if busy is not None:
        # Another training save held this workspace's slot for the whole
        # bounded wait: the result was NOT recorded. Reporting persistence
        # here would tell the coach a save landed that never ran.
        return {
            "persisted_training_evidence": False,
            "training_evidence_error": "training_reliability_busy",
            "training_evidence_detail": (
                "Another training save is still running in this workspace, so this "
                "verification result was not recorded. Verify again once it finishes."
            ),
            "training_reliability_busy": busy,
        }
    return {
        "persisted_training_evidence": True,
        "training_card_id": card_id,
        "training_card_title": card_title,
        "training_workspace_update": workspace_update,
    }


def _training_card_context_for_persistence(
    context: ToolContext,
    *,
    args: dict[str, Any],
    current_file: dict[str, Any],
) -> tuple[str, str, str]:
    from ...memory.workspace_recovery import live_training_card_title

    card_id = str(
        args.get("training_card_id")
        or args.get("card_id")
        or current_file.get("training_card_id")
        or ""
    ).strip()
    card_title = str(
        args.get("training_card_title")
        or args.get("card_title")
        or current_file.get("training_card_title")
        or ""
    ).strip()
    focus_area = str(args.get("focus_area") or current_file.get("focus_area") or "").strip()

    runtime = context.runtime
    memory_service = getattr(runtime, "memory_service", None) if runtime is not None else None
    if memory_service is not None and not (card_id and card_title and focus_area):
        try:
            snapshot = memory_service.snapshot(context.workspace_id)
        except Exception as exc:
            logger.debug("Suppressed exception in verification_and_excerpt: %s", exc)
            snapshot = None
        routing = getattr(snapshot, "active_training_card_routing", None) if snapshot is not None else None
        selected = getattr(routing, "selected_card", None) if routing is not None else None
        if not card_id:
            card_id = str(
                getattr(routing, "selected_card_id", "") or getattr(selected, "card_id", "") or ""
            ).strip()
        if selected is not None:
            if not card_title:
                card_title = str(getattr(selected, "title", "") or "").strip()
            if not focus_area:
                focus_area = str(
                    getattr(selected, "focus_area", "") or getattr(selected, "target_skill", "") or ""
                ).strip()
    leftover_plan, leftover_runtime, leftover_task_title = _leftover_training_persist_identity(context)
    card_title = live_training_card_title(
        plan=leftover_plan,
        runtime=leftover_runtime,
        existing=leftover_runtime,
        task_title=leftover_task_title,
        card_title=card_title,
    )
    if focus_area:
        focus_area = live_training_card_title(
            plan=leftover_plan,
            runtime=leftover_runtime,
            existing=leftover_runtime,
            task_title=leftover_task_title,
            card_title=focus_area,
        )
    return card_id, card_title, focus_area


def _practice_failed_checks(payload: dict[str, Any]) -> list[str]:
    if payload.get("passed") is True:
        return []
    reason = str(payload.get("reason") or "").strip()
    checks: list[str] = []
    if reason:
        checks.append(reason)
    if payload.get("blocking_diagnostics"):
        checks.append("vscode-diagnostics")
    if payload.get("warning_diagnostics"):
        checks.append("vscode-warnings")
    return list(dict.fromkeys(checks))


async def _handle_read_workspace_file(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    path_raw = str(args.get("path") or "").strip()
    if not path_raw:
        return {"ok": False, "error": "missing_path", "detail": "read_workspace_file requires a path."}
    try:
        max_chars = max(64, min(int(args.get("max_chars", 4000)), 16000))
    except Exception as exc:
        logger.debug("Suppressed exception in verification_and_excerpt: %s", exc)
        max_chars = 4000

    start_line_raw = args.get("start_line")
    end_line_raw = args.get("end_line")
    root = _resolve_workspace_root(context)
    target = _safe_path_under(root, path_raw) if root is not None else None
    if target is not None and target.is_file():
        try:
            text = target.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            logger.debug("Suppressed exception in verification_and_excerpt: %s", exc)
            return {"ok": False, "error": exc.__class__.__name__, "detail": str(exc)}
        sliced_info = _slice_text_by_lines(
            text,
            start_line_raw=start_line_raw,
            end_line_raw=end_line_raw,
            max_chars=max_chars,
        )
        return {
            "ok": True,
            "path": str(target.relative_to(root)) if root is not None else str(target),
            "absolute_path": str(target),
            "source": "workspace_disk",
            "byte_size": len(text.encode("utf-8", errors="replace")),
            **sliced_info,
        }
    record = _snapshot_file_record(context, path_raw)
    if record is not None:
        text = str(record.get("content") or "")
        sliced_info = _slice_text_by_lines(
            text,
            start_line_raw=start_line_raw,
            end_line_raw=end_line_raw,
            max_chars=max_chars,
        )
        return {
            "ok": True,
            "path": str(record.get("path") or path_raw),
            "source": "workspace_snapshot",
            "byte_size": len(text.encode("utf-8", errors="replace")),
            "language_id": record.get("language_id"),
            **sliced_info,
        }
    if _snapshot_file_listed(context, path_raw):
        relative = _normalize_workspace_relpath(path_raw)
        remember = getattr(context.runtime, "remember_requested_workspace_file", None) if context.runtime is not None else None
        if callable(remember):
            remember(context.workspace_id, relative)
        return {
            "ok": False,
            "error": "snapshot_content_unavailable",
            "listed": True,
            "path": relative,
            "detail": (
                f"Path {path_raw!r} is listed in the host workspace snapshot, "
                "but this turn did not include its file body. Open the file in the editor "
                "or import it on a later turn after the host refreshes the snapshot."
            ),
        }
    return {
        "ok": False,
        "error": "not_found",
        "detail": f"Path {path_raw!r} is not a readable file inside the active workspace.",
    }
