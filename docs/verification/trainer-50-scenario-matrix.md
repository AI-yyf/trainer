# Trainer 50-Scenario Acceptance Matrix

## Scope and evidence rules

This is an auditable release matrix, not a declaration that the product is complete.
It records the baseline known on 2026-07-13 and separates a browser Preview from an
installed VSIX and a live provider. A green item is evidence only for the layer named
in its row; it must not be used as evidence for an unexecuted layer.

Live credentials are injected only into the one process that runs a probe. This file
does not contain an API key, an environment export containing a key, or provider
response bodies.

| Layer | Meaning |
| --- | --- |
| `PW` | Playwright against the standalone Vite browser Preview. It does not exercise the VS Code extension host. |
| `BR` | Browser Preview recovery script, including host-message and interrupted-stream recovery. |
| `PS` | Direct live-provider smoke test. |
| `TT` | Current-source FastAPI sidecar with a real provider, via `trainer-turn-smoke.mjs`. |
| `TR` | Current-source FastAPI sidecar training return state machine with a real provider. |
| `LP` | Live protocol-compatibility probe against a local sidecar. |
| `LR` | Live resource-grounding probe against a local sidecar. |
| `VSIX/PKG` | Packaged and installed extension validation, including the VS Code extension host. |

Status vocabulary:

- `Passed (run)` means a command completed successfully in this baseline.
- `Baseline failed` means the listed command was run but did not produce green evidence;
  it does not by itself prove the product behavior is wrong.
- `Not run` means there is no current-source, current-provider evidence yet.

The current main Preview suite result is `28/28` passing. An additional four governance
cases and eighteen locale-width cases are tracked in their own specs. Rows 5-8 split one
passing Plan composer test into four user intents, while rows 10-11 aggregate its six
width/language instances; this is why the matrix deliberately has a different row count
than the test runner.

## Matrix

| # | User scenario | User goal | Validation layer and command | Current evidence status | Gap or acceptance criterion |
| --- | --- | --- | --- | --- | --- |
| 1 | Chinese five-view shell | Find Coach, Plan, Resources, Training, and Settings in Chinese. | `PW` - `npx playwright test e2e/trainer.spec.js --reporter=line` (`exposes ... zh-CN`) | Passed (run) | Keep five visible localized labels, correct active state, no horizontal overflow, and no browser console errors. |
| 2 | English five-view shell | Find the same five work areas in English. | `PW` - same suite (`exposes ... en-US`) | Passed (run) | Same acceptance criteria as row 1. |
| 3 | Persist selected view after reload | Open Settings, reload, and resume in Settings without a composer. | `PW` - `npx playwright test e2e/trainer.spec.js --reporter=line` | Passed (run) | `previewStorageKey` is now scoped inside the Preview harness and the full suite passed after reload. |
| 4 | Explicit destination beats stored state | Follow a Coach Preview link even when stale browser state says Settings. | `PW` - same suite (`explicit preview view authoritative`) | Passed (run) | The explicit `view` parameter must remain authoritative after reload. |
| 5 | Plan explanation | Ask for an explanation from Plan without changing the formal plan. | `PW` - same suite (`routes Plan composer modes ...`, `explain`) | Passed (run) | Request must set `intent: plan` and `formal_plan_mutation: false`; rendered plan remains unchanged. |
| 6 | Plan evidence discussion | Discuss evidence in Plan without silently mutating the formal plan. | `PW` - same suite (`evidence`) | Passed (run) | Same transport and no-mutation contract as row 5. |
| 7 | Plan blocker discussion | Report a blocker in Plan without silently mutating the formal plan. | `PW` - same suite (`blocker`) | Passed (run) | Same transport and no-mutation contract as row 5. |
| 8 | Generate a formal plan | Explicitly request plan generation. | `PW` - same suite (`generate`) | Passed (run) | Request must be the sole mode that sets `formal_plan_mutation: true`. |
| 9 | Missing-key recovery | Understand why a Coach turn cannot continue and where to fix the key. | `PW` - same suite (`missing-key recovery`) | Passed (run) | Recovery copy must state that the saved connection lacks a key and direct the user to Settings without hiding the composer. |
| 10 | Chinese narrow sidebar | Scan all five Chinese labels at 300, 360, and 420 px. | `PW` - same suite (`five visible top-level labels`, `zh-CN`) | Passed (run) | Labels stay visible rather than collapsing to ambiguous icon-only navigation; no horizontal overflow. |
| 11 | English narrow sidebar | Scan all five English labels at 300, 360, and 420 px. | `PW` - same suite (`five visible top-level labels`, `en-US`) | Passed (run) | Same acceptance criteria as row 10. |
| 12 | Chinese Resources workspace | Search, select, clear, and inspect archived resources in Chinese. | `PW` - same suite (`Resources ... zh-CN`) | Passed (run) | Search/tree/selection semantics and unavailable destructive actions must be visible and correctly disabled. |
| 13 | English Resources workspace | Perform the same resource navigation in English. | `PW` - same suite (`Resources ... en-US`) | Passed (run) | Same acceptance criteria as row 12. |
| 14 | Chinese Learn-first card | See exactly one Chinese training card with the five required facts. | `PW` - same suite (`Training single-card ... zh-CN`) | Passed (run) | Card must start at Learn, expose current/why-now/deliverable/verify/return, and omit multi-card navigation. |
| 15 | English Learn-first card | See exactly one English training card with the five required facts. | `PW` - same suite (`Training single-card ... en-US`) | Passed (run) | Same acceptance criteria as row 14. |
| 16 | Chinese verification affordance | Verify the current file from the Chinese Training composer. | `PW` - same suite (`Training verification ... zh-CN`) | Passed (run) | Verify action belongs in the composer, not duplicated inside the card. |
| 17 | English verification affordance | Verify the current file from the English Training composer. | `PW` - same suite (`Training verification ... en-US`) | Passed (run) | Same acceptance criteria as row 16. |
| 18 | Training state-machine visibility | Move through Learn, Try, Verify, Reflect, and Return with visible evidence. | `PW` - `npx playwright test e2e/trainer.spec.js --reporter=line` | Passed (run) | The current five card facts and composer-owned phase controls are verified without restoring removed markup. |
| 19 | Remote-workspace training card | Receive a remote-workspace card with concrete task, verification, and return evidence. | `PW` - same suite (`remote training scenario`) | Passed (run) | Current card facts, verification, and return evidence are visible. |
| 20 | Debug-loop training card | Receive a focused debug-loop card with concrete evidence. | `PW` - same suite (`debug training scenario`) | Passed (run) | Current card facts, verification, and return evidence are visible. |
| 21 | Function-contract training card | Receive a function-guidance card grounded in a call site. | `PW` - same suite (`function training scenario`) | Passed (run) | Current card facts, verification, and return evidence are visible. |
| 22 | Spanish Training localization | Keep a selected Spanish card, next-hop text, and composer fully Spanish. | `PW` - same suite (`selected Spanish training card`) | Passed (run) | The Spanish next-hop and five card facts are localized with no visible English fallback. |
| 23 | Inline model switch | Select a model from the Coach input shell without a second Settings-like control. | `PW` - same suite (`composer model switch`) | Passed (run) | Model menu remains inside the composer shell in Chinese and English. |
| 24 | Host-directed navigation | Honor a host `ui/restoreView` message that sends the user to Training. | `PW` - same suite (`restores a requested ... host message`) | Passed (run) | Active view must become Training with no console errors. |
| 25 | Paste or drop an image into Coach | Send a scratch-paper image through the vision coaching path. | `PW` - same suite (`vision coach path`) | Passed (run) | `DataTransfer` drag/drop on `.composer__frame` sends one image attachment with `use_agent_loop: true`. |
| 26 | Open contextual controls from Coach | Open both context and resource panels from the input shell. | `PW` - same suite (`context and resource panels`) | Passed (run) | Both icon actions and their menus remain available in Chinese and English. |
| 27 | Settings protocol truth | Inspect protocol, diagnostics, profiles, and model readiness in Settings. | `PW` - same suite (`protocol truth inside Settings`) | Passed (run) | Details must not claim a connection needs testing when the Preview state is connected. |
| 28 | First-run Coach empty state | Start with no conversation, no plan, and no resources. | `PW` - `npx playwright test e2e/trainer-governance.spec.js --workers=1` | Passed (run) | Empty welcome state keeps a disabled blank submit that becomes available after user input, without fabricated workbench facts. |
| 29 | Plan with no formal plan | Enter Plan before any plan exists. | `PW` - `e2e/trainer-governance.spec.js` | Passed (run) | Connected no-plan state shows the honest entry surface and does not render Generate, Next, or Freeze controls without plan authority. |
| 30 | Frozen formal plan | Freeze an existing plan and inspect its immutable state. | `PW` - `e2e/trainer-governance.spec.js` | Passed (run) | Frozen state and live recovery control render with no browser console error. |
| 31 | Blocked plan and evidence queue | Surface a blocker, queue evidence, then resolve or defer it. | `PW` - `e2e/trainer-governance.spec.js` | Passed (run) | Blocker and pending evidence count render; Adopt dispatches an evidence command rather than mutating formal plan truth implicitly. |
| 32 | Save a provider profile | Edit Settings, save a provider profile, reload the workbench, and retain non-secret metadata. | `PW` plus extension-host test or installed `VSIX` flow | Not run | Persist base URL/model/protocol without rendering or logging the secret; show the resulting connection state accurately. |
| 33 | Provider failure and retry | See a failed provider test, correct it, retry, and return to coaching. | `PW` plus extension-host test or installed `VSIX` flow | Not run | Failure must be actionable and honest; successful retry must clear obsolete failure state. |
| 34 | Actual resource lifecycle | Upload/index a resource, open it, delete it, restore it, and confirm selection state. | `PW` with real bridge or `VSIX` flow | Not run | Current Preview covers disabled controls only; prove actual command dispatch and restored resource identity. |
| 35 | Remaining locale mobile visual QA | Use es-ES, fr-FR, de-DE, ja-JP, ko-KR, and pt-BR at 300/360/420 px. | `PW` - `npx playwright test e2e/trainer-locales.spec.js --workers=1` | Passed (run) | All 18 locale-width cases keep five labels and five card facts visible without horizontal overflow; Spanish next-hop has no English leakage. |
| 36 | Preview recovery after interruptions | Recover notices, completed/failed/in-progress streams, restored Training/Resources, and Plan first viewport. | `BR` - `npm run verify:webview-recovery --prefix extension` | Passed (run) | All 13 recovery cases passed against a freshly built Preview. |
| 37 | Configure the supplied Anthropic-compatible provider | List the configured model and get visible Chinese-capable output without exposing reasoning. | `PS` - `npm run smoke:provider` with transient provider environment | Passed (run) | The direct smoke passed for `anthropic_messages`, model catalog, and language integrity; rerun whenever provider config or adapter code changes. |
| 38 | Real remote-workspace coaching | Ask the real Coach how to establish a tiny verified Remote SSH boundary. | `TT` - `npm run smoke:trainer-turn` | Passed (run) | Current-source sidecar returned the `remote_workspace` scenario and rejected debug/function focus markers. |
| 39 | Real debug-loop coaching | Ask the real Coach for one breakpoint and one value. | `TT` - `npm run smoke:trainer-turn` | Passed (run) | Current-source sidecar returned `debug_loop` and excluded remote-workspace focus. |
| 40 | Real function-guidance coaching | Ask the real Coach to recover one function contract from a call site. | `TT` - `npm run smoke:trainer-turn` | Passed (run) | Current-source sidecar returned `function_guidance` and excluded remote/debug focus. |
| 41 | English remote Learn-first routing | Ask for Remote SSH training before being tested. | `TT` - `npm run smoke:trainer-turn` (`training_route`) | Passed (run) | Response must route to the remote-workspace card with Learn-first training metadata. |
| 42 | Chinese remote Learn-first routing | Ask for the same Remote SSH training flow in Chinese. | `TT` - `npm run smoke:trainer-turn` (`training_route_zh`) | Passed (run) | Reply, current focus, and selected card must be Chinese and route to `remote_workspace`. |
| 43 | Chinese debug Learn-first routing | Ask for a Chinese debug training flow. | `TT` - `npm run smoke:trainer-turn` (`debug_training_route_zh`) | Passed (run) | Reply, focus, and card must be Chinese and route to `debug_loop`. |
| 44 | English function Learn-first routing | Ask for function-guidance training in English. | `TT` - `npm run smoke:trainer-turn` (`function_training_route`) | Passed (run) | Response must route to `function_guidance` with training metadata. |
| 45 | Chinese function Learn-first routing | Ask for function-guidance training in Chinese. | `TT` - `npm run smoke:trainer-turn` (`function_training_route_zh`) | Passed (run) | Reply, focus, and card must be Chinese and route to `function_guidance`. |
| 46 | Complete a passing training return | Verify work, record a reflection, return to Coach, and mark the handoff complete. | `TR` - `npm run smoke:training-return` | Passed (run) | Live run completed `evaluate -> reflect -> return`; `extension/tests/trainingReturnSmokeScript.test.js` also passed 7/7 for runner behavior. |
| 47 | Block an invalid training return | Fail evaluation and prevent an unearned return to Coach. | `TR` - `npm run smoke:training-return` | Passed (run) | Live run reported the failure branch as blocked rather than marking the card implemented. |
| 48 | Live protocol compatibility | Start sessions and turns using the configured protocol case through the current local sidecar. | `LP` - `python scripts/live-protocol-probe.py` with transient `TRAINER_LIVE_PROTOCOL_*` values | Passed (run) | `anthropic_messages` provider test, model discovery, and localized remote/debug/function routing all passed. |
| 49 | Live resource grounding | Import the fixture document and require the real Coach to cite the Resources first-viewport promise and its boundary. | `LR` - `python scripts/live-resource-grounding-probe.py` with transient `TRAINER_LIVE_GROUNDING_*` values | Passed (run) | The real Coach searched, hit, and grounded its Chinese reply in the uploaded resource. |
| 50 | Installed VSIX delivery and stability | Install the packaged extension, use the real provider, reopen across workspaces, and retain Resources/Training truth under stability runs. | `VSIX/PKG` - `npm run verify`; `npm run package:vsix`; `node extension/scripts/verify-vsix-install.mjs`; `node extension/scripts/verify-vsix-e2e.mjs`; `node extension/scripts/verify-vsix-e2e-resource-training-stability.mjs`; `node extension/scripts/verify-vsix-e2e-multi-workspace-stability.mjs` with transient `TRAINER_E2E_PROVIDER_*` values | Blocked (environment) | Current-source VSIX rebuild stopped at PyInstaller with `ENOSPC`; free several GB, then rerun package/install/E2E. The E2E driver now supports `TRAINER_E2E_PROVIDER_PROTOCOL=anthropic_messages`, but that support is source-tested only until a current package exists. |

## Release gate

The matrix is not release-ready: 46 of 50 rows have current evidence at their stated
layer. Rows 32-34 still need real Settings/Resources host interactions, and row 50 is
blocked by disk capacity before a current-source package can be produced. In particular,
a passing `PW` row does not close a `VSIX/PKG` row, and a direct `PS` provider smoke does
not close an end-to-end `TT`, `TR`, `LP`, `LR`, or `VSIX/PKG` row.
