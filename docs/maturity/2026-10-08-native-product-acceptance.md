# Native product acceptance — 2026-10-08

This is installed-VSIX acceptance with a real frozen Python Sidecar and a clearly labelled local fixture provider. It proves installation, host/runtime identity, interaction and presentation. It does not prove real-model teaching quality or real learning evidence.

## Artifact and isolation

The installed artifact is `output/maturity/trainer-1.3.4-darwin-arm64.vsix`, SHA-256 `df1d1f5745cf8ee963ba0911f260fda2952ef5c88702a686aacc01b9929c4ee1`, 114,883,774 bytes. Its metadata records a dirty precommit `83e30ff` build. It is broadly the fddbe75 product baseline, but is **not a clean-commit release** and does not contain the fixes discovered below.

All installs and launches used separate `--user-data-dir` and `--extensions-dir` under the temporary `trainer-vsix-e2e-JJy1XO` root. The screenshot owner was verified by window ID and title: first 9052, then 9164 after the isolated restart, `[Extension Development Host] Trainer Native UX Acceptance — workspace`. Controlled CDP was limited to port 9337 and that title. Screenshot capture used the screenshot skill's window-ID helper. The original SSH window 436 was not used for product interaction or extension installation. Its before/after extension IDs and versions are identical (`output/maturity/native-product-acceptance/original-extension-inventory-{before,after}.txt`).

The separate UX profile initially reused a root bound by the first harness's different brain identity. The actual admission command correctly rejected it. A fresh owned pending root was then provisioned, and normal `trainer.workspace.adoptProject` returned the verified root/project/context identity. This was fixture setup correction, not a relaxation of admission.

## Installed journeys and original failure

The first native harness had **19 successful steps, then failed on the 20th attempted step**, `assert-training-theory-drill-visible-truth`. The fixture returned prose to a card-generation request that requires JSON. The frozen Sidecar reported `LLM response was not valid JSON for source=conversation_gap`; its normal validator rejected the result. Preserve `output/maturity/native-product-fixture-report.json` and `.log` as failed evidence.

The fixture now returns explicit `Fixture` card JSON only for the exact card-generation system/user prompts. Focus and target come from that prompt; no verdict, trusted evidence or mastery is manufactured. Other prose and capability probes keep their existing behavior. Transport tests cover non-streaming flash and streaming practice JSON. The second installed-VSIX/frozen-Sidecar run passed **34/34 steps**, including workspace reopen, history isolation, resource truth and the generated card. See `output/maturity/native-product-fixture-structured-report.json` and `.log`; the report explicitly records `provider.source = fixture`.

MacOS screenshot steps embedded in the old generic harness are Windows-only and were marked skipped; they are not visual evidence. The independent OS window captures below provide the native presentation evidence.

## Native presentation matrix

`output/maturity/native-product-acceptance/native-surface-ledger.json` records actual installed-webview DOM facts for Coach, Learning, Training, Resources and Settings at **340 and 460 CSS pixels**, under VS Code **Dark Modern and Light Modern**, with **20 OS window screenshots**. Sidebar widths were changed using the real VS Code sash. Host theme changes used the native theme chooser; light captures verify `vscode-light` and an actual light body background. Choosing Trainer's light fallback preference alone did not override native host theme tokens, so earlier filenames containing `light` are not counted as light evidence unless they say `host-light` or belong to this `native-*` matrix.

For every captured state:

- Primary navigation is exactly Coach / Learning / Resources. Training still highlights Learning and has a back-to-Learning control.
- Full CoachComposer appears only in Coach. Learning, Training, Resources and Settings have no CoachComposer.
- There is no document horizontal overflow at either width.
- The visible explicit primary-action count is at most one. Learning's active-card action is `Continue practice`; Training's current action is `Verify current file`. Settings index has no forced primary action; Resources offers one visible Add resources CTA, which is not tagged as an explicit template primary.
- Settings index actually has four entries: Connection, Coach, Workspace and Preferences. Skills and remote/advanced capabilities remain in their corresponding details.

Representative captures:

| Surface | Native capture | Consumer observation |
| --- | --- | --- |
| Coach | `output/maturity/native-product-acceptance/native-coach-dark-340.png` | Message stream is the main content; composer remains reachable. No independent skill strip or dashboard panels. |
| Learning | `output/maturity/native-product-acceptance/native-plan-light-340.png` | One named current practice and one Continue action. Additional plan actions are disclosed. No conversation input. |
| Training | `output/maturity/native-product-acceptance/native-training-light-340.png` | Current card, phase, task, completion standard and one verification action. Task details are collapsed; no former multi-panel training chrome. |
| Resources | `output/maturity/native-product-acceptance/native-resources-dark-340.png` | Search and Add resources are visible. Imported items require opening their folder; the extra disclosure is visible and labelled. |
| ResourceReader | `output/maturity/native-product-acceptance/resource-reader-light-460.png` | Actual imported markdown, source, indexed/trust status and governed actions are visible after selecting the item. |
| Settings | `output/maturity/native-product-acceptance/native-settings-light-460.png` | Four concise index entries, with host/data details available inside Workspace. |

Additional actual states: first configuration, connection loading, backend recovery, lazy Learning loading, streamed Coach reply and expanded task details are saved in the same directory. Transient captures are labelled by state; a loading screenshot does not stand in for a ready-state screenshot.

## Defects found and corrective path

| Observed defect | Root cause and correction | Validation boundary |
| --- | --- | --- |
| First connection quick setup promised automatic model selection but failed when only address and API key were filled. | UI submitted `model: ''`; `saveProviderFromWebviewCommand` treated the empty string as explicit and rejected it before live discovery. Root's host fix treats omitted/empty/whitespace model identically, continues live discovery, then tests the selected model. | Three host behavior cases plus the existing provider suite pass. Actual old-VSIX failure is retained. Requires installation of a rebuilt artifact before native green can be claimed. |
| After project/session identity changed, clicking Save could leave `Connecting…` disabled indefinitely. | Bridge rejected the outdated request without a final lifecycle/status or refreshed handshake. Runtime now emits an old-request interrupted result and forces a full snapshot. App clears busy/old feedback when generation/workspace/session changes, while preserving the address, model and API-key draft. Hydration also checks the originating action scope. The rejection marker localizes in all eight languages and explicitly says the action was not run. | Pure eight-language behavior checks and browser native-message fixture pass. Late executed results remain isolated; the new marker applies only to requests rejected before dispatch. Native rebuilt-artifact replay remains required. |
| Cloud macOS/Linux `verify-webview-recovery` expected removed training chrome and read `null` for restored title. | The script now reads FocusedPractice/ActivityHeader and exact card identity. Existing task-details disclosure carries the actual `currentFocus` prop. Card ID is only a data identity, never consumer-facing copy. | Full recovery script passes 13/13; it asserts internal training route, exact `card-provider-truth`, title, summary and visible restored focus. Plan 300/360 cases use a plan-only fixture and assert one visible executable primary action. Native rebuilt-artifact focus capture remains required. |

The native captures also show English generic success notices when the test driver invokes a public command without a response language in Chinese UI. Those are not evidence of model translation quality. Future locale acceptance should invoke the full localized UI path and inspect host notices separately. No speculative geometry or layout changes were made from that observation.

### Screenshot review follow-ups

A second consumer review of the actual captures on 2026-10-09 confirms the three stable destinations, one clear Learning action and Training's current phase/task/completion standard. It also records two presentation concerns rather than claiming every captured screen is fully polished:

| Actual screenshot | Consumer concern | Next correction in the existing product path |
| --- | --- | --- |
| `output/maturity/native-product-acceptance/native-settings-light-460.png` | The Workspace index subtitle displays the full internal Sidecar root path across five lines. It takes substantially more space than the other three entries and makes the index harder to scan. | Prefer a meaningful short workspace/project summary in SettingsIndex; keep the real full root path inside Workspace detail. Recheck 340/460 and actual root identity before accepting a change. |
| `output/maturity/native-product-acceptance/resource-reader-light-460.png` | The same source path appears above the content and again in the metadata. The explanation also uses the internal names `Plan` and `Training` in a Chinese consumer flow. | Consolidate the source presentation and use the localized learning/coach terms in the existing ResourceReader copy while retaining governed source, evidence and training handoffs. Recheck the actual Ask Coach context path. |

These are recorded concerns, not implemented fixes in this frozen UI snapshot. They do not invalidate the installation/identity checks, but they remain part of the consumer acceptance follow-up. Real teaching quality is reviewed separately in `docs/maturity/2026-10-08-real-teaching-quality.md`; actual model errors and provider fallback are not credited to this fixture UI matrix.

## Source regression and pending native recheck

Current source checks: strict webview TypeScript passes; actual TypeScript LanguageService reports zero syntax/semantic diagnostics for App, TrainingWorkbenchView and operationMessageGovernance. Learning actions, session recovery and Settings lifecycle browser checks pass **30/30**, including draft retention under a new generation with changed provider metadata. Operation/Plan/fixture Node checks pass **48/48**; additional Settings/Training checks pass **8/8**, with rendered card identity, collapsed disclosure and supporting facts replacing the stale source-order assumption. The final recovery script is **13/13**. Logs are in `output/maturity/product-native-*` and `native-webview-recovery-final.log`.

The dated historical UX reports have not been rewritten. SPEC.md now distinguishes six internal routes from three primary destinations, documents four Settings index entries, and no longer describes a Coach skill strip as shipped first-screen UI.

Before calling the fixes installed-VSIX verified, rebuild and install only into the owned profile, record the new artifact hash/source provenance, and replay the true first address+key/empty-model path, the scope interruption and the restored focus disclosure. Real-model native quality acceptance remains separate from this fixture report.
