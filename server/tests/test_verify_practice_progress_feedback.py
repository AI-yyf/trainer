"""Progressive acceptance feedback for `verify_practice_current_file` (batch 4).

The tool must report matched/total signal progress and name the missing
signals instead of a bare failure sentence. The passed verdict stays strict.
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[0].parent))

from app.llm.tools import ToolContext, _handle_verify_practice_current_file  # noqa: E402


def _context(content: str) -> ToolContext:
    return ToolContext(
        runtime=None,
        workspace_id="workspace-1",
        session_id="session-1",
        extra={
            "current_file": {
                "path": "src/search.ts",
                "language_id": "typescript",
                "content": content,
                "diagnostics": [],
            }
        },
    )


class VerifyPracticeProgressFeedbackTest(unittest.TestCase):
    def test_partial_match_reports_progress_and_first_missing_signal(self) -> None:
        result = asyncio.run(
            _handle_verify_practice_current_file(
                _context("export function searchNow(query: string) { return query; }\n"),
                {
                    "acceptance_criteria": [
                        "Implement debounceSearch for the search input.",
                        "Keep the search function pure.",
                    ],
                    "expected_symbols": ["debounceSearch"],
                },
            )
        )

        self.assertFalse(result["passed"])
        self.assertEqual(result["status"], "needs_review")
        self.assertEqual(result["matched_signal_count"], 1)
        self.assertEqual(result["total_signal_count"], 3)
        self.assertIn("1/3 acceptance signals matched", result["summary"])
        self.assertIn("Still missing:", result["summary"])
        self.assertIn("debounceSearch", result["summary"])
        self.assertIn("Implement the missing acceptance signals (starting with", result["next_step"])
        self.assertIn("debounceSearch", result["next_step"])

    def test_full_match_reports_progress_without_missing_list(self) -> None:
        content = (
            "export function debounceSearch(fn: unknown) { return fn; }\n"
            "export const debounceSearchPure = debounceSearch;\n"
        )
        result = asyncio.run(
            _handle_verify_practice_current_file(
                _context(content),
                {
                    "acceptance_criteria": [
                        "debounceSearch",
                        "debounceSearchPure",
                    ],
                    "expected_symbols": [],
                },
            )
        )

        self.assertTrue(result["passed"])
        self.assertEqual(result["matched_signal_count"], result["total_signal_count"])
        self.assertEqual(result["total_signal_count"], 2)
        self.assertNotIn("Still missing:", result["summary"])

    def test_zero_match_names_every_missing_signal(self) -> None:
        result = asyncio.run(
            _handle_verify_practice_current_file(
                _context("const nothing = 1;\n"),
                {"acceptance_criteria": ["retryFetch", "abortController"]},
            )
        )

        self.assertFalse(result["passed"])
        self.assertIn("0/2 acceptance signals matched", result["summary"])
        self.assertIn("Still missing:", result["summary"])


if __name__ == "__main__":
    unittest.main()
