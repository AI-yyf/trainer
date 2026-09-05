# Unified Coach Workstreams

Date: 2026-06-29
Status: execution backlog for the unified-coach program
Parent: `docs/2026-06-29-unified-coach-master-plan.md`

This file breaks the unified-coach program into bounded implementation lanes.
Each lane is only complete when its acceptance tests and cross-view implications are proven.

## A. Coach Super-Entry

Outcome:
`Coach` becomes the single best place to start, continue, recover, and redirect work.

Primary anchors:

- `shared/src/skillCatalog.ts`
- `shared/src/protocol.ts`
- `extension/src/commands/sessionCommands.ts`
- `extension/src/core/webviewBridge.ts`
- `extension/webview/src/components/coach/*`
- `extension/webview/src/components/composer/*`

Key tasks:

- Normalize the slash/skill deck into stable command families.
- Keep typed parts attached to the message flow.
- Show runtime state as lightweight, honest activity instead of a hidden log.
- Add structured recovery notices for provider, sidecar, and card-resume failures.
- Make Coach capable of handing off into Plan, Resources, or Training without losing context.

Done when:

- the learner can begin from plain language or a skill command,
- the next action is always visible,
- recovery notices explain what failed and what can still be done,
- no important state has to be inferred from a separate console.

Verification:

- `node --test extension/tests/sessionMessageRoute.test.js`
- `node --test extension/tests/browserSidecar.test.js`
- `node --test extension/tests/webviewBridge.test.js`
- `npm run verify:webview-recovery --prefix extension`

## B. Plan Governance

Outcome:
`Plan` becomes the durable truth for long-running learning work instead of a loose text block.

Primary anchors:

- `server/app/planner/*`
- `shared/src/masterPlanGovernance.ts`
- `shared/src/planGovernance.ts`
- `shared/src/reviewQueueGovernance.ts`
- `extension/webview/src/components/plan/*`

Key tasks:

- Separate master plan, project subplans, and active stage truth.
- Make blockers explicit and actionable.
- Add governed evidence intake from training, evaluation, and resources.
- Make freeze/replan state visible and reversible.
- Make due reviews and repeated weaknesses visible without overwhelming the mainline.

Done when:

- the learner can always answer "what are we doing now, why, and how do we prove it,"
- evidence is clearly pending vs accepted,
- chat does not silently overwrite formal plan state.

Verification:

- `cd server && python -m pytest tests/test_planner.py -q`
- `cd server && python -m pytest tests/test_subplan.py -q`
- `node --test extension/tests/planGovernanceShared.test.js extension/tests/masterPlanGovernanceShared.test.js`

## C. Resources Sandbox

Outcome:
`Resources` becomes a governed, searchable knowledge workspace under Trainer control, not a shadow project filesystem.

Primary anchors:

- `docs/workspace-first-artifact-layout.md`
- `server/app/resources/*`
- `server/app/ingest/*`
- `server/app/workspace/*`
- `shared/src/resourceWorkbenchGovernance.ts`
- `shared/src/workspaceAuthority.ts`
- `extension/webview/src/components/resources/*`

Key tasks:

- Keep Trainer-managed artifacts under the carrier root with explicit provenance.
- Support import from file, folder, and URL.
- Preserve trust, freshness, and source metadata.
- Expand preview and extracted-knowledge paths.
- Make the path from resource -> knowledge atom -> card/plan evidence visible.
- Keep workspace-boundary and sandbox-boundary teaching copy truthful.

Done when:

- imported material can be found, previewed, cited, and converted,
- the learner can tell which files are Trainer-owned and which are project-owned,
- sandbox root selection and migration stay explainable across platforms.

Verification:

- `cd server && python -m pytest tests/test_resource_sidecar_routes.py -q`
- `cd server && python -m pytest tests/test_search_index.py -q`
- `node --test extension/tests/resourceWorkbenchGovernanceShared.test.js extension/tests/resourceSearch.test.js extension/tests/resourcePreviewBody.test.js`

## D. Training Engine

Outcome:
`Training` becomes the governed mastery engine for recall, execution, review, transfer, and recovery.

Primary anchors:

- `server/app/training/*`
- `shared/src/trainingCardRouting.ts`
- `shared/src/trainingHandoffGovernance.ts`
- `shared/src/trainingRecoveryGovernance.ts`
- `shared/src/transferEvidenceGovernance.ts`
- `extension/webview/src/components/training/*`

Key tasks:

- Expand card families while keeping `single-card-first`.
- Make verification steps first-class on every serious practice card.
- Tie completion results back into plan, memory, and review rhythm.
- Improve resume/skip/review/fallback behavior.
- Turn repeated weaknesses into future card-selection pressure.

Done when:

- the current card dominates the viewport,
- completion clearly returns somewhere,
- resume lands on the correct card and state,
- review cards are grounded in actual failed or fragile evidence.

Verification:

- `cd server && python -m pytest tests/test_training_endpoints_integration.py -q`
- `cd server && python -m pytest tests/test_training_handoff.py -q`
- `cd server && python -m pytest tests/test_review_scheduler_fsrs.py -q`
- `node --test extension/tests/trainingCardRoutingShared.test.js extension/tests/trainingRecoveryGovernanceShared.test.js extension/tests/workbenchDataTrainingState.test.js`

## E. Provider Truth and Runtime Settings

Outcome:
`Settings` becomes the truthful runtime-control surface for provider, protocol, model, language, and workspace policy.

Primary anchors:

- `shared/src/providerProtocols.ts`
- `extension/src/provider/*`
- `extension/src/commands/providerCommands.ts`
- `server/app/llm/provider_service.py`
- `server/app/core/models.py`
- `extension/webview/src/components/settings/*`

Key tasks:

- Keep provider profiles durable and explicit.
- Make protocol, endpoint, and model capability visible.
- Preserve request defaults through save/import/test/refresh flows.
- Make auth, model-not-found, and protocol-mismatch states visible and recoverable.
- Align Coach, Settings, and resume paths on the same provider truth.
- Keep language and teaching defaults deterministic across restarts.

Done when:

- a provider failure cannot be misread as readiness,
- all critical provider actions preserve the active profile state,
- the learner knows what changed and what still works.

Verification:

- `node --test extension/tests/providerCommands.test.js extension/tests/providerConfigStore.test.js extension/tests/providerProtocols.test.js`
- `cd server && python -m pytest tests/test_provider_service.py -q`
- `node scripts/provider-smoke.mjs` with explicit env vars

Special runtime note:

- The user-supplied MiniMax-compatible smoke target failed with `401 authentication_failed` on 2026-06-29.
- That result should drive product truthfulness and recovery UX, not be hidden behind a generic green badge.

## F. Remote, Debug, and Function-Guidance Teaching Packs

Outcome:
Remote workspace, debugging, and function guidance become first-class teaching domains instead of ad hoc prompts.

Primary anchors:

- `extension/webview/src/lib/browserPreviewHarness.ts`
- `server/app/training/card_generator.py`
- `shared/src/remoteWorkspace.ts`
- `server/app/workspace/authority.py`
- `server/app/llm/provider_service.py`

Key tasks:

- Promote preview-only packs into live card-generation packs.
- Teach remote workspace type, path ownership, and credential mode explicitly.
- Teach the minimal trustworthy debug loop explicitly.
- Teach function-contract recovery explicitly.
- Ensure each pack has both practice and flash forms.
- Route pack outcomes into plan and memory.

Done when:

- these three scenario families can be invoked in real workspaces,
- each family produces one explainable practice card and one recall card,
- the learner can return with concrete evidence rather than vague completion claims.

Verification:

- Browser preview screenshots for all scenario packs
- `node --test extension/tests/browserPreviewHarnessSource.test.js extension/tests/trainingPracticeEvidenceCopy.test.js`
- targeted server tests for card generation once live routing lands

## G. Recovery, i18n, and Cross-Platform Hardening

Outcome:
Trainer can fail, pause, resume, and travel across platforms without losing its teaching contract.

Primary anchors:

- `docs/verification.md`
- `extension/webview/src/lib/i18n/*`
- `extension/src/core/runtimeRehydration.ts`
- `extension/src/core/workbenchData.ts`
- `scripts/check.ps1`
- `scripts/smoke.ps1`

Key tasks:

- Keep all top-level states restorable after reload.
- Make language fallback deterministic in all eight supported languages.
- Remove platform-specific assumptions from UI and workspace copy.
- Add non-PowerShell verification coverage for macOS/Linux.
- Add CI matrix coverage for Windows, macOS, and Linux.

Done when:

- restore paths keep the active coach, plan, resource, and card truth aligned,
- all supported UI languages resolve keys with clean fallback,
- cross-platform behavior is proven in automation, not only claimed in docs.

Verification:

- `node --test extension/tests/i18nCopyCompleteness.test.js extension/tests/i18nProvider.test.js`
- `scripts/check.ps1 -Strict`
- new cross-platform CI commands once added

## H. Self-Evolution and Reuse Pipeline

Outcome:
Trainer keeps improving its teaching corpus and implementation choices with explicit curation rules.

Primary anchors:

- `docs/open-source-fit-and-provider-strategy.md`
- `server/app/research/*`
- `server/app/resources/*`
- `server/app/pedagogy/*`
- `server/app/memory/*`

Key tasks:

- define the candidate-source registry,
- enforce permissive-license and quality filters,
- ingest into managed resources,
- derive knowledge atoms and scenario-pack candidates,
- score training usefulness from actual outcomes,
- retire weak or stale source material.

Done when:

- Trainer can improve its teaching corpus without hidden infra growth,
- source provenance and licensing remain explicit,
- reused upstream projects reduce implementation effort instead of multiplying maintenance debt.

Verification:

- research and ingest integration tests
- resource-to-card derivation tests
- manual review of source provenance and generated card quality

## Sequence

Recommended execution order:

1. E. Provider Truth and Runtime Settings
2. A. Coach Super-Entry
3. F. Remote, Debug, and Function-Guidance Teaching Packs
4. D. Training Engine
5. B. Plan Governance
6. C. Resources Sandbox
7. G. Recovery, i18n, and Cross-Platform Hardening
8. H. Self-Evolution and Reuse Pipeline

Rationale:

- Provider truth is a trust foundation.
- Coach is the product entry.
- Remote/debug/function packs are the user's most explicit scenario ask.
- Training, plan, and resources then close the teaching loop.
- Cross-platform hardening and self-evolution become durable multipliers after the core loop is coherent.
