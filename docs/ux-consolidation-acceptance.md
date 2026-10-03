# Trainer UX consolidation

Baseline: `33fd0fd99e1fc9f31ce8bb91bcca702c5f923644` (local and fetched origin/main).
Branch: `codex/trainer-ux-templates`.
User specification: `/Users/Apple/.codex/attachments/8b48b89d-31c9-4697-93f9-a2d7a280ab83/pasted-text-1.txt`.

Trainer is a long-term coding coach in VS Code. The learner writes code; the
coach supplies the next step, verifies real evidence, and updates lasting
capability records. This migration changes presentation and navigation while
preserving domain state, commands, routes, persistence, and trust boundaries.

## Baseline audit

- Six `ActiveWorkbenchView` routes are also used as the navigation inventory.
  App filters Settings out, leaving five permanent tabs.
- `showComposerShell = activeView !== "settings"` exposes four unrelated input
  semantics through CoachComposer. Training submission already has governed
  persistence handlers that can be reused by a dedicated activity form.
- App resets non-Coach scroll to zero and pins Coach to the bottom whenever a
  route changes. Surface components unmount on navigation, losing local state.
- CoachMessageBubble renders regenerate/share/save/training in an action row.
- Learning contains an inner progress dashboard despite the separate growth
  route. Review and capability strips precede the current action.
- Training renders simultaneous current action, why, deliverables, verification,
  return, hints, and multiple buttons. The five-phase state machine lives in
  governed state outside this presentation and must remain authoritative.
- Settings has four live categories but still measures bottom tab labels and
  falls back to short labels. Provider/workspace/teaching/preferences logic is
  reusable under an index/detail hierarchy.
- Styles are imported as sections with many historical refinement layers.
  Migrated template selectors will have one canonical owner; old selectors and
  responsive workarounds will be removed rather than overridden.
- Existing golden assets show older navigation/category arrangements. They are
  presentation references, not evidence of current behavior.
- Baseline `npm run check`: passed. No callable `lsp_diagnostics` tool is exposed;
  use TypeScript language-service diagnostics plus compiler checks after edits.

## Architecture and grammar

Three stable primary destinations: Coach, Learning, Library. All six routes
remain supported. Training and Progress select Learning in the navigation;
Settings is a utility destination. History and Settings stay in the header.

Templates own information order, primary-action budgets, secondary disclosure,
and accessible semantics. Feature components supply domain facts and existing
handlers. Templates never invent evidence, grades, verification counts, or
training identities.

| Template | Feature ownership |
| --- | --- |
| AppShell | identity, history/settings, stable three-destination navigation |
| Conversation / CoachReply | messages, evidence/code, one next action, overflow |
| NextAction | label, action title, concise completion/reason, one CTA |
| LearningHome | current learning/phase/action/completion; review/route/growth/evidence disclosures |
| FocusedPractice | same attempt and current LEARN/TRY/VERIFY/REFLECT/RETURN phase |
| VerificationResult | truthful check results; output/evidence details disclosure |
| GrowthEvidence | understanding/implementation/debugging/transfer, real evidence |
| Library / ResourceReader | FTS/folders/recent/trash, reading and contextual actions |
| SettingsIndex / SettingsDetail | connection, coach/Skills, workspace/remote, preferences/advanced |
| CommandPalette | searchable existing skill catalog and custom skills |
| SystemState | loading/empty/processing/success/error/recovery/disconnection and requirements |

Use VS Code typography/theme tokens, spacing 4/8/12/16/24, radii 6/8/12,
metadata/body/section/page hierarchy. Keep backgrounds flat and borders sparse.
One dominant action per initial viewport; at most two secondary actions in
focused activities. Advanced facts remain available through disclosure.

## Migration checkpoints

- [x] 1. Template contracts, design grammar, typed destination mapping.
- [x] 2. AppShell extraction, Coach-only chat composer, dedicated activity input,
      surface/draft/scroll preservation, contextual handoffs to Coach.
- [x] 3. Conversation/CoachReply template, action overflow, unified NextAction.
- [x] 4. LearningHome current action first, staged plan disclosures, internal growth.
- [x] 5. FocusedPractice five phases, verification results, identity-preserving forms.
- [x] 6. Library and ResourceReader, contextual Coach handoff, trash/search retention.
- [x] 7. Settings index/detail, removal of bottom tabs and measurement logic.
- [x] 8. Skill palette and canonical system states.
- [x] 9. Legacy CSS/layout cleanup, documentation in all eight README languages and regression migrations.

## Validation ledger

Checks run on the final source (2026-10-03):

| Check | Result |
| --- | --- |
| Full backend pytest suite, including real-sidecar experience matrix | 3,169 passed, 28 subtests; 53 existing warnings |
| Full extension node:test suite | 1,778 passed; one existing skip; zero failures |
| `npm run check` | CSS sections balanced; webview and extension TypeScript passed |
| TypeScript language-service diagnostics | 40 edited files, zero errors; callable LSP tool unavailable |
| Full Playwright suite | 347 / 347 passed |
| Geometry: 340/420/460 × dark/light × Chinese/English | 182 / 182 assertions passed on final source |
| Golden screenshots | All 12 regenerated; goldens and dark/light width matrix visually inspected |
| Installed VSIX with real MiniMax provider and local Python sidecar | 34 / 34 harness steps passed; provider source `external` |
| Actual native Remote-SSH window on `34s` | 7 / 7 steps passed; installed gateway and Companion; actual Linux subprocesses |

The browser suite retains the existing domain/lifecycle assertions and adds
three-destination mapping, Coach-only composer, draft/scroll/session continuity,
reader selection, overlay focus, dedicated activity inputs and settings reading
height. It covers configured/missing/bad-key providers, plan/no plan, active/no
training, verification pass/fail, reflection/return, resource search/reader/
trash/restore, growth, custom skills, history/reload and backup/restore.

Preview scenarios establish presentation and interaction behavior only. They
do not prove real provider, workspace, verification or evidence behavior. The
native test uses the installed VSIX, actual sidecar and configured provider;
SSH verification uses the installed UI-host gateway and remote Companion with
real remote bytes, hashes, search and subprocess outcomes.

## Native acceptance findings

Native checks exposed two existing Remote-SSH defects that blocked truthful
verification: the UI host uses `vscode-remote:` workspace URIs while the remote
extension host uses `file:` URIs, and `verifyStart` unwrapped a process spec that
its dispatcher had already unwrapped. The gateway now translates only within
the active workspace/authority, preserves host remote identity in responses,
and the Companion consumes the existing flat spec. Protocol v2 and all backend
and shared contracts remain unchanged. Behavior tests exercise both hosts with
different URI schemes and actual pass/fail/cancelled processes.

The installed-VSIX harness now authenticates to its own sidecar, waits for the
real provider connection test, and asserts the new ResourceReader ownership.
Model card generation retries only the exact existing validator rejection,
up to three calls to the same public endpoint; rejected output is never treated
as a card and there is no fixture fallback. The final native run passed all 34 steps. Seven automatic screenshot steps are
Windows-only and not required on macOS; two macOS window captures were inspected
separately. Its cross-workspace model card was
accepted on the second attempt; the initial rejection was never promoted.

## Review and maintenance

Canonical template ownership and extension rules are documented in
`extension/webview/src/templates/README.md`. Old bottom Settings tabs, redundant
plan growth dashboards, shared non-Coach composers and displaced CSS selectors
were removed. App orchestration is smaller and surface rendering, destination
mapping, pane scroll restoration and attachment handling have separate owners.
All six route/deep-link targets and their governed handlers remain available.

No backend model, database, API or shared domain-contract changes were needed.
Provider secrets and machine-specific test fixtures/reports are excluded from
version control. Work was prepared on `codex/trainer-ux-templates`. On
2026-10-04, the user authorized committing, pushing to GitHub and integrating
the completed change into `main`.

## Retained local evidence

- `output/ux-consolidation/native-report.json`: all 34 installed-VSIX checks,
  real external provider, accepted model card, sidecar and workspace isolation.
- `output/ux-consolidation/ssh-report.json`: seven actual Remote-SSH checks on
  `34s`, including remote file/search/hash, exit 0 / exit 1, real cancellation
  with no verdict, UI-host lifecycle acknowledgement and public remote command.
- `output/ux-consolidation/ssh-driver.js`: the isolated native test driver.
- `output/ux-consolidation/native-local.png` and `native-ssh.png`: actual native
  window captures inspected after the runs. These are distinct from preview
  golden screenshots.

Reports and captures stay local under the gitignored output directory. Tests
used dedicated VS Code profiles, local storage roots and temporary remote files.
Only owned test windows were closed. The test-installed remote Companion was
uninstalled from `34s`, restoring its prior extension inventory. The developer's
global VS Code profile, provider credentials and unrelated remote projects were
not changed.
