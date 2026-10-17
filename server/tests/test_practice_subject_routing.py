"""P1 #9: ``verify_practice_current_file`` routes on the host-declared subject family.

What has to stay true no matter which family runs:

* the code lane is the fail-closed default — no family, an unknown family, or a
  family the *model* tried to pass in tool arguments all land on it unchanged;
* a non-command pack reports honestly (``needs_review`` when deterministic
  evidence is missing) and never mints training evidence while its evidence
  source is outside the host-trusted whitelist;
* a malformed card declaration or a crashed hook degrades to "no evidence",
  never to a pass.
"""

from __future__ import annotations

from typing import Any

from app.evaluator.models import CheckStatus
from app.evaluator.verifiers import (
    IDE_CURRENT_FILE_EVIDENCE_SOURCE,
    RUBRIC_DUAL_REVIEW_EVIDENCE_SOURCE,
    literature_pack,
    python_toolchain_pack,
    verify_submission_with_pack,
)
from app.llm.tools import ToolContext, build_default_tool_registry

_CODE_FILE: dict[str, Any] = {
    "path": "src/search.ts",
    "language_id": "typescript",
    "content": (
        "export function debounceSearch(query: string) {\n"
        "  const normalizedQuery = query.trim();\n"
        "  return normalizedQuery.length > 0 ? normalizedQuery : '';\n"
        "}\n"
    ),
    "diagnostics": [],
}

_ESSAY = (
    "The lantern keeper walked the pier every night.\n"
    "\n"
    "He counted the boats and let the dark do the rest.\n"
)

_LITERATURE_CARD: dict[str, Any] = {
    "word_count": {"min": 5, "max": 5000},
    # Substring matching is the hook's documented rule, so the watched phrase
    # must not be a substring of legitimate prose ("very" would hit "every").
    "banned_phrases": ["perhaps"],
    "min_paragraphs": 1,
    "quote_balance": True,
}


def _context(current_file: dict[str, Any], *, extra: dict[str, Any] | None = None) -> ToolContext:
    merged: dict[str, Any] = {"current_file": dict(current_file)}
    if extra:
        merged.update(extra)
    return ToolContext(
        runtime=None,
        workspace_id="workspace-test",
        session_id="session-test",
        extra=merged,
    )


def _literature_file(**overrides: Any) -> dict[str, Any]:
    file: dict[str, Any] = {
        "path": "drafts/pier.md",
        "language_id": "markdown",
        "content": _ESSAY,
        "diagnostics": [],
        "subject_family": "literature",
        "card_config": dict(_LITERATURE_CARD),
        "rubric_items": [
            {"statement": "Opening image is concrete", "anchor": "The lantern keeper"},
            {"statement": "Closes on restraint", "anchor": "let the dark do the rest"},
        ],
    }
    file.update(overrides)
    return file


async def test_absent_subject_family_keeps_the_code_lane_unchanged() -> None:
    registry = build_default_tool_registry()
    result = await registry.invoke(
        _context(_CODE_FILE),
        "verify_practice_current_file",
        {
            "acceptance_criteria": ["Implement debounceSearch for the search input"],
            "expected_symbols": ["debounceSearch", "normalizedQuery"],
        },
    )
    assert result["status"] == "passed"
    assert result["passed"] is True
    assert result["reason"] == "all_signals_matched"
    assert result["evidence_source"] == IDE_CURRENT_FILE_EVIDENCE_SOURCE
    assert "subject_family" not in result


async def test_unknown_subject_family_falls_back_to_the_code_lane() -> None:
    registry = build_default_tool_registry()
    result = await registry.invoke(
        _context({**_CODE_FILE, "subject_family": "linguistics"}),
        "verify_practice_current_file",
        {
            "acceptance_criteria": ["Implement debounceSearch for the search input"],
            "expected_symbols": ["debounceSearch"],
        },
    )
    assert result["status"] == "passed"
    assert result["evidence_source"] == IDE_CURRENT_FILE_EVIDENCE_SOURCE
    assert "subject_family" not in result


async def test_model_arguments_cannot_select_the_subject_family() -> None:
    """A model-authored ``subject_family`` must not switch the verifier."""
    registry = build_default_tool_registry()
    result = await registry.invoke(
        _context(_CODE_FILE),
        "verify_practice_current_file",
        {
            "subject_family": "literature",
            "acceptance_criteria": ["Implement debounceSearch for the search input"],
            "expected_symbols": ["debounceSearch"],
        },
    )
    assert result["evidence_source"] == IDE_CURRENT_FILE_EVIDENCE_SOURCE
    assert result["reason"] == "all_signals_matched"
    assert "deterministic_checks" not in result


async def test_host_declared_family_routes_to_the_literature_lane() -> None:
    registry = build_default_tool_registry()
    result = await registry.invoke(
        _context(_literature_file()),
        "verify_practice_current_file",
        {
            "acceptance_criteria": ["the lantern keeper"],
            "expected_symbols": ["counted the boats"],
        },
    )
    assert result["ok"] is True
    assert result["subject_family"] == "literature"
    assert result["evidence_source"] == RUBRIC_DUAL_REVIEW_EVIDENCE_SOURCE
    assert result["status"] == "passed"
    assert result["passed"] is True
    assert result["reason"] == "pack_checks_passed"
    check_names = {item["name"] for item in result["deterministic_checks"]}
    assert {"acceptance-signals", "word-count", "banned-phrases"} <= check_names
    assert result["rubric_review"]["status"] == CheckStatus.PASSED.value
    assert result["matched_signal_count"] == 2


async def test_literature_lane_never_mints_training_evidence() -> None:
    """The rubric source is outside the whitelist until P2 #23."""
    registry = build_default_tool_registry()
    result = await registry.invoke(
        _context(_literature_file()),
        "verify_practice_current_file",
        {"acceptance_criteria": ["the lantern keeper"]},
    )
    assert result["passed"] is True
    assert result["practice_evidence_persisted"] is False
    assert "persisted_training_evidence" not in result
    assert "not yet a host-trusted verification source" in result["evidence_trust_note"]


async def test_failed_hook_is_needs_review_not_a_pass() -> None:
    registry = build_default_tool_registry()
    result = await registry.invoke(
        _context(_literature_file(content=f"{_ESSAY}Perhaps the dark knew more.\n")),
        "verify_practice_current_file",
        {"acceptance_criteria": ["the lantern keeper"]},
    )
    assert result["status"] == "needs_review"
    assert result["passed"] is False
    assert result["reason"] == "failed_deterministic_checks"
    assert "banned-phrases" in result["summary"]


async def test_missing_rubric_anchor_fails_the_review() -> None:
    registry = build_default_tool_registry()
    result = await registry.invoke(
        _context(
            _literature_file(
                rubric_items=[
                    {"statement": "Opening image is concrete", "anchor": "The lantern keeper"},
                    {"statement": "Unsupported claim", "anchor": "a sentence that is not there"},
                ]
            )
        ),
        "verify_practice_current_file",
        {"acceptance_criteria": ["the lantern keeper"]},
    )
    assert result["status"] == "needs_review"
    assert result["passed"] is False
    assert "Rubric review failed" in result["summary"]
    assert result["rubric_review"]["missing"] == ["Unsupported claim"]


async def test_rubric_alone_cannot_verify() -> None:
    """No deterministic check and no human adoption ⇒ PENDING, never a pass."""
    registry = build_default_tool_registry()
    result = await registry.invoke(
        _context(
            _literature_file(
                card_config={},
                rubric_items=[{"statement": "Opening image is concrete", "anchor": "The lantern keeper"}],
            )
        ),
        "verify_practice_current_file",
        {},
    )
    assert result["status"] == "needs_review"
    assert result["passed"] is False
    assert result["reason"] == "deterministic_evidence_required"
    assert result["deterministic_checks"][0]["status"] == CheckStatus.SKIPPED.value


async def test_blocking_diagnostics_gate_every_family() -> None:
    registry = build_default_tool_registry()
    result = await registry.invoke(
        _context(_literature_file(diagnostics=["[error] line 1: stray delimiter."])),
        "verify_practice_current_file",
        {"acceptance_criteria": ["the lantern keeper"]},
    )
    assert result["status"] == "blocked"
    assert result["passed"] is False
    assert result["reason"] == "error_diagnostics"
    assert result["subject_family"] == "literature"


async def test_hook_only_card_can_pass_on_deterministic_checks() -> None:
    """#8's rule: a satisfied deterministic hook *is* evidence.

    No rubric, no acceptance criteria — the card's own hook declaration is the
    contract, and every hook passed.
    """
    registry = build_default_tool_registry()
    result = await registry.invoke(
        _context(_literature_file(rubric_items=None)),
        "verify_practice_current_file",
        {},
    )
    assert result["status"] == "passed"
    assert result["passed"] is True
    assert result["reason"] == "pack_checks_passed"
    # Still no evidence minting: the source is unwhitelisted (#23).
    assert result["practice_evidence_persisted"] is False


async def test_literature_lane_without_declared_checks_needs_review() -> None:
    """Nothing declared anywhere ⇒ no deterministic evidence ⇒ never a pass."""
    registry = build_default_tool_registry()
    result = await registry.invoke(
        _context(_literature_file(card_config={}, rubric_items=None)),
        "verify_practice_current_file",
        {},
    )
    assert result["status"] == "needs_review"
    assert result["passed"] is False
    assert result["reason"] == "deterministic_evidence_required"
    assert result["deterministic_checks"][0]["status"] == CheckStatus.SKIPPED.value
    assert result["rubric_review"] is None


def test_malformed_card_declaration_yields_no_hooks_and_no_pass() -> None:
    """A broken declaration must degrade to "no evidence", not to a pass."""
    pack = literature_pack()
    verdict = verify_submission_with_pack(
        pack,
        submission=_ESSAY,
        card_config={"word_count": {"min": 50, "max": 10}},
    )
    assert verdict.status == CheckStatus.PENDING
    assert verdict.hook_results == ()


def test_pack_trust_declarations() -> None:
    code_pack = python_toolchain_pack()
    assert code_pack.evidence_source == IDE_CURRENT_FILE_EVIDENCE_SOURCE
    assert code_pack.persists_practice_evidence is True

    lit_pack = literature_pack()
    assert lit_pack.evidence_source == RUBRIC_DUAL_REVIEW_EVIDENCE_SOURCE
    assert lit_pack.persists_practice_evidence is False
