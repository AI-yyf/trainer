# P1 R0/R1 audit — real evidence record

- Baseline: `312a5901674b547844b19e4b4f83378267fec422` (`maturity(round 1)`), branch `main`
- Audited: 2026-10-18
- Scope: R0 baseline freeze + R1 (CI, evidence consistency, data safety, permissions)
- Every row below is backed by a command run or a GitHub Actions run ID; no row
  is a plan or an intention.

## 1. CI (REL-01)

| Gate | Evidence | Result |
| --- | --- | --- |
| `ci` workflow on HEAD | run `39138488138` (push, 15m39s) | **success** |
| Cross-Platform Verify on HEAD | run `39138488151` | **success** — all 9 jobs green |
| — Server (ubuntu / windows / macos) | 14m15s / 21m47s / 11m10s | success |
| — UI (ubuntu / windows / macos) | 5m17s / 7m21s / 4m28s | success |
| — Package (ubuntu / windows / macos) | 3m19s / 4m56s / 4m11s | success |
| Nightly Remote-SSH E2E (re-dispatched on HEAD) | run `39140250312` | **success** — Server regression 14m0s + Remote-SSH E2E 7m3s (previous failure `39112644443` was the pre-`312a590` Ruff E402, fixed by round 1) |

Local gates on the same tree:

| Gate | Command | Result |
| --- | --- | --- |
| Ruff | `python -m ruff check app tests` | All checks passed |
| Pyright | `python -m pyright app` | 0 errors, 0 warnings |
| Server suite | `npm run test:server` | **3628 passed**, 28 subtests |
| Extension suite | `node --test extension/tests/*.test.js` | **2183 passed / 0 failed** (2184 total) |
| TypeScript | `npm run check` | pass (CSS sections + webview + host) |
| UI geometry | `node scripts/verify-ui-geometry.mjs` | **470 / 470** (after gate alignment, see §4) |
| Security/evidence focus | pytest on authority/attestation/evidence/reliability/MCP (125 tests) | **125 passed** |

## 2. SEC-02 — download safety (new coverage)

`library_downloads._extract_repository_archive` was already fail-closed
(absolute paths, `..`, symlink entries, entry/byte budgets, staging + atomic
move), but had **zero tests**. Added `server/tests/test_library_download_safety.py`:

| Case | Result |
| --- | --- |
| `../` traversal refused, nothing escapes the destination | pass |
| Absolute paths refused | pass |
| Symlink entries skipped, regular files intact | pass |
| Entry budget (`MAX_ARCHIVE_ENTRIES`) enforced | pass |
| Extracted-byte budget (`MAX_EXTRACTED_BYTES`) enforced | pass |
| Existing destination never overwritten | pass |

6/6 pass (`pytest tests/test_library_download_safety.py`).

## 3. Acceptance-case coverage map

Automated evidence exists for each case below; cases marked **device** still
need a real-machine run before release sign-off.

| ID | Automated evidence |
| --- | --- |
| UX-01 | `e2e/trainer.spec.js`, onboarding wizard guards (`extension/tests/firstLook*.test.js`), geometry `learning:*` |
| UX-02 | No pre-send probe gate: `sessionCommands.ts` (search `unverified-stream` → 0), `providerStatus` send-state tests |
| UX-03 | `useWorkbenchState` selector policy + streaming isolation tests (`coachConversationSource`, `R3` perf guard); **device**: 300-message scroll run |
| UX-04 | geometry 470 assertions across 340/420/460 × dark/light × zh/en; 8-language copy key tests; **device**: 200% font zoom |
| MD-01 | `providerCommands.test.js` (catalog failure → cache/manual still selectable) |
| MD-02 | `providerWebviewCommands` generation/mutex tests (rapid switch race) |
| MD-03 | `providerConfigStore.test.js` (failed save keeps previous config) |
| MD-04 | `providerStatus` failure attribution tests (401/429/timeout vocabulary) |
| CH-01 | stream reliability/checkpoint tests (`coachConversationSource`, training reliability) |
| CH-02 | round-1 draft-scope isolation + workspace-switch guards (`browserCaptureDrafts`, draft chain tests) |
| LR-01 | `test_browser_bridge.py`, capture tests |
| LR-02 | `test_library_download_safety.py` (new), library tests |
| LR-03 | download status/atomic-write tests (LR-02 file + capture rollback) |
| LR-04 | `browserCaptureDrafts.test.js`, offline-queue tests |
| TR-01 | `test_training_attestation_delivery.py`, `test_training_reliability*.py` |
| TR-02 | Nightly Remote-SSH run `39140250312`: both jobs green on HEAD |
| TR-03 | plan revision 409 tests (`test_api.py` plan conflict, `plan_revision` store) |
| TR-04 | grounding downgrade tests (`turn_grounding`, confirmation allocation e2e) |
| SEC-01 | `test_mcp_client.py` (authority-gated MCP tools) |
| SEC-02 | `test_library_download_safety.py` (new) |
| REL-01 | run `39138488151` (9/9) + run `39138488138` |
| REL-02 | **partial**: VSIX packaged and installed locally on macOS (`code --install-extension`); real-sidecar smoke is the next device step |

## 4. Geometry gate alignment (29 regressions resolved)

`scripts/verify-ui-geometry.mjs` still encoded the pre-dock IA and reported 29
failures on HEAD. The gate was stale, not the product:

- §3.7 (`composerDock.ts`, commit `e83eb92`) rules the persistent bottom
  composer onto **coach / learning / resources** and nowhere else. The gate now
  asserts exactly that instead of "coach only".
- §3.4 merged evidence-to-adopt into the review disclosure, so LearningHome
  carries **three** closed sections, not four.
- The one-primary-action budget now applies to **page** actions; the persistent
  dock send affordance is excluded as a constant input control.

After alignment: **470/470 geometry assertions pass**. Representative
screenshots (narrowest 340-dark-zh and 460-light-en) are stored beside this
file.

## 5. Known gaps (not yet P1-complete)

1. REL-02 real-device smoke (real sidecar + real browser capture + real
   workspace) must be run after the next VSIX install.
2. UX-03 300-message scroll baseline and UX-04 200% zoom are device runs.
3. Windows/Linux interactive install acceptance (CI package jobs are green;
   human acceptance is still outstanding).
