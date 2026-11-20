# Branch Triage: `codex/trainer-convergence-verification`

- **Archive tag**: `archive/trainer-convergence-verification-2026-11-20` -> commit `1512c070` (`codex/trainer-convergence-verification`)
- **Active mainline**: `codex/trainer-unified-learning` (product truth: `.trainer-convergence/product-contract.md` v2, locked 2026-11-20)
- **Merge decision**: **No whole-branch merge.** Selectively ported applicable reliability and teaching-boundary fixes in Wave 3, then tag-archived. Remote branches remain untouched.

## Triage Summary

### 1. Selectively Ported in Wave 3
- **`10ca5e91`** (`Verify the native teaching boundary and recover from sidecar port races`)
  - Ported `racedPorts` retry loop in `extension/src/core/sidecarProcessManager.ts` (`start`, `resolveLaunchPort`, `findAvailablePort`) while preserving Wave 1 `<LibraryRoot>` migration (`migrateGlobalStorageToLibraryRootIfNeeded`) and `logSidecarLine`.
  - Ported launch-race regression test in `extension/tests/sidecarProcessManager.test.js`.
- **`4da9457f`** + prerequisite durable query alignment (`57cf7fdd`) (`Commit training evidence and its events in one SQLite transaction` / `Read and reverse durable ledger history across restarts`)
  - Ported `transaction: sqlite3.Connection | None = None` support across `server/app/core/event_ledger_store.py`, `server/app/core/event_ledger.py`, `server/app/training/attempt_store.py`, and `server/app/main.py` while preserving Wave 1 `set_library_root_resolver` and `<LibraryRoot>` wiring plus `recent_learning_activity` SQLite queries.
  - Ported `test_failed_reversal_rolls_back_evidence_and_ledger_together` into `server/tests/test_evidence_ledger_bridge.py`.
- **`3ede277e`** (`Enforce teaching-only replies and deny code-writing tools`)
  - Expanded `PROJECT_WRITE_TOOL_NAMES` in `server/app/llm/tools.py` to also block `insert_code`, `execute_command`, and `run_command` (keeping `write_sandbox_file` for sandbox library notes). `server/app/llm/mcp_client.py` already enforces `teaching_boundary` and skips non-read MCP tools.

### 2. Already Present or Superseded on `codex/trainer-unified-learning`
- Reasoning output headroom (`1b893d2e` -> `server/tests/test_provider_reasoning_budget.py` already present)
- Recall review prompt context & attempt isolation (`5600425c`, `6900e79d` -> `server/app/llm/training_review_context.py`, `server/tests/test_training_attempt_isolation.py` already present)
- Browser capture queue / sidepanel baseline (`9e75239e` — browser capture features consolidated on unified learning line; sidepanel chat frozen per v2 decision log)

### 3. Intentionally Rejected (Conflicts with Locked v2 Contract & Unified `<LibraryRoot>`)
- **`1512c070`** (`Make Learning and Resources composers drive their workflows`): encodes v1 3-destination workflow (`learningTodayCopy`, legacy plan composer flows) superseded by v2 two-destination IA (`Chat / Resources` + Learning drawer).
- **`8fc7d1b9`, `014e4851`** (`Publish/Complete the Trainer screenshot gallery`): v1 multi-destination UI screenshots.
- Commits on the divergent verification line that removed unified-learning runtime modules (`browser_chat.py`, `library_practice.py`, `research_brief.py`, `version_check.py`, `project_checks.py`) or weakened `<LibraryRoot>` storage unification.
