# PROJECT KNOWLEDGE BASE

**Generated:** 2026-06-19
**Updated:** 2026-09-18 — refreshed structure, sizes, and test-stack notes
**Branch:** main

## OVERVIEW
Desktop-first VS Code extension + FastAPI Python sidecar for conversation-driven coding training. Three-destination React workbench (`Coach / Learning / Resources`, with six internal routes) with keyboard-first navigation, ReAct coach agent loop, and FSRS-based spaced repetition.

## STRUCTURE

```
trainer/                            # Repository root
├── extension/                      # VS Code extension host (TypeScript)
│   ├── src/                        # Extension commands, core services, webview bridge
│   │   ├── commands/               # 25+ command handlers grouped by domain
│   │   │   ├── index.ts            # Command registration
│   │   │   ├── sessionCommands.ts  # Send/receive messages
│   │   │   ├── providerCommands.ts # Provider config commands
│   │   │   ├── providerWebviewCommands.ts  # Webview ↔ provider bridge
│   │   │   ├── researchCommands.ts # Research orchestration commands
│   │   │   ├── resourceCommands.ts # Resource upload/index/open
│   │   │   ├── trainingCommands.ts # Training commands
│   │   │   ├── evaluationCommands.ts
│   │   │   ├── memoryCommands.ts
│   │   │   ├── sidecarCommands.ts
│   │   │   ├── openWorkbench.ts
│   │   │   └── workspaceContext.ts
│   │   ├── core/                   # Core extension services
│   │   │   ├── webviewBridge.ts    # WorkbenchSidebarController (VS Code ↔ webview)
│   │   │   ├── httpClient.ts       # SidecarHttpClient
│   │   │   ├── sidecarProcessManager.ts  # Sidecar lifecycle
│   │   │   ├── workbenchData.ts    # Host state ↔ webview data adaptation
│   │   │   ├── runtimeRehydration.ts     # Session restore on startup
│   │   │   ├── workspaceTrust.ts   # WorkspaceTrustGuard
│   │   │   ├── workspaceRoots.ts
│   │   │   ├── commandContext.ts   # CommandContext type
│   │   │   ├── commandRegistry.ts
│   │   │   ├── constants.ts       # COMMAND_IDS, STORAGE_KEYS, SIDECAR_DEFAULTS
│   │   │   └── types.ts           # TrainerHostState, ProviderConfig, etc.
│   │   ├── provider/               # Provider config store
│   │   │   └── providerConfigStore.ts  # SecretStorage-backed provider config
│   │   ├── workspace/              # Workspace gateway (URI + local/remote fs)
│   │   │   ├── remoteUri.ts        # Strict workspace URI parsing/DTO helpers
│   │   │   ├── workspaceGateway.ts # WorkspaceGateway interface + protocol DTOs
│   │   │   ├── localWorkspaceGateway.ts  # vscode.workspace.fs implementation
│   │   │   └── remoteWorkspaceGateway.ts # Companion command-bridge client
│   │   └── testing/                # VS Code Testing API
│   │       ├── testController.ts   # TrainerTestController
│   │       └── trainingAttestation.ts  # Host-trusted /training/verification/attest
│   ├── webview/                    # React workbench UI (Vite + Zustand + i18n)
│   │   └── src/
│   │       ├── app/
│   │       │   ├── App.tsx         # Root workbench (single-file orchestrator; line count drifts with each consolidation round)
│   │       │   ├── useWorkbenchState.ts  # Zustand store
│   │       │   └── useTrainingCommands.ts
│   │       ├── components/
│   │       │   ├── coach/          # CoachConversationView, CoachMessageBubble, etc.
│   │       │   ├── plan/           # CoachPlanView + evidence governance
│   │       │   ├── resources/      # ResourcesWorkbenchView
│   │       │   ├── training/       # TrainingWorkbenchView, CardPanel, etc.
│   │       │   ├── settings/       # CoachSettingsView
│   │       │   ├── composer/       # CoachComposer
│   │       │   ├── common/         # Shared UI parts
│   │       │   ├── firstlook/      # First-time experience
│   │       │   ├── icons/          # SVG icon components
│   │       │   ├── parts/          # Typed message part renderers
│   │       │   ├── preview/        # Preview-related components
│   │       │   └── shell/          # App shell components
│   │       ├── lib/
│   │       │   ├── types.ts        # Webview-side types (~2k lines)
│   │       │   ├── mockData.ts     # Mock bootstrap data for dev
│   │       │   ├── rlMockData.ts   # RL training mock data
│   │       │   ├── rlTrainingData.ts  # RL training card data
│   │       │   ├── rlTrainingPlan.ts  # RL training plan
│   │       │   ├── coachIntelligence.ts  # Coach AI logic
│   │       │   ├── coachConversationEngine.ts
│   │       │   ├── browserSidecar.ts    # Browser-only sidecar stub
│   │       │   ├── browserPreviewHarness.ts  # Standalone Vite dev
│   │       │   ├── theme.ts        # applyWorkbenchTheme
│   │       │   ├── vscode.ts       # VS Code webview message helpers
│   │       │   ├── htmlSanitizer.ts
│   │       │   └── i18n/
│   │       │       └── copy.ts     # 8-language i18n
│   │       └── styles/             # Token-driven design system (styles.css is a tombstone; the live sections live in styles/sections/)
│   ├── bundled/                    # Bundled Python sidecar (~245 MB, 98 .py files)
│   │   └── remote/                 # trainer-workspace-companion.vsix (build output, gitignored)
│   ├── tests/                      # node:test suite (many are source-text guards — prefer behavior tests for new work)
│   ├── dist/                       # Build output
│   └── package.json                # Extension manifest (24 commands, 1 webview view)
├── remote-extension/               # Trainer Workspace Companion (extensionKind: ["workspace"])
│   ├── src/extension.ts            # File/search/hash/diagnostics/environment/verify ops
│   ├── package.json                # Serialized via trainer.remote.capabilities/request commands
│   └── tsconfig.json               # Compiles shared/src/remoteProtocol.ts into dist/
├── server/                         # FastAPI Python sidecar
│   ├── app/                        # Application package
│   │   ├── __init__.py
│   │   ├── main.py                 # create_app() — FastAPI app factory with DI
│   │   ├── api/
│   │   │   ├── routers.py          # Core HTTP endpoints (~25.5k lines — largest file)
│   │   │   ├── runtime.py          # TrainerRuntime — wires all services
│   │   │   └── routes/             # Extracted domain routers (build_*_router(runtime, deps))
│   │   │       ├── _deps.py        # RouterDeps — shared closure helpers
│   │   │       ├── workspace.py    # /workspace/* discovery, adoption, reconcile
│   │   │       ├── memory.py       # /memory/* + /evidence/*
│   │   │       ├── learning.py     # stage materials, pedagogy, training attest
│   │   │       ├── resources.py    # /assets + /resource/* library routes
│   │   │       ├── provider.py     # /provider/test + /provider/models
│   │   │       ├── sandbox.py      # /sandbox/* + /workspace/authority
│   │   │       ├── research.py     # Research sub-router
│   │   │       └── training_handoff.py
│   │   ├── core/
│   │   │   ├── models.py           # Pydantic models (~3.5k lines)
│   │   │   ├── config.py / settings.py
│   │   │   └── event_ledger.py
│   │   ├── db/
│   │   │   ├── repository.py       # TrainerRepository — main SQLite
│   │   │   ├── research_repository.py
│   │   │   ├── repositories.py     # Additional repositories
│   │   │   └── database.py         # DB setup
│   │   ├── llm/
│   │   │   ├── provider_service.py # ProviderService (~8.1k lines)
│   │   │   ├── coaching_recovery.py # Recovery overrides (provider error/timeout/language)
│   │   │   ├── coaching_replies.py  # Reply continuity + relevance guards
│   │   │   ├── coaching_first_turn.py # First-turn lane selection
│   │   │   ├── coaching_patches.py  # Reply patch composition
│   │   │   ├── coaching_reply_drafts.py # Reply drafts + final patches
│   │   │   ├── coaching_scaffold.py # Task scaffolding helpers
│   │   │   ├── agent_tool_context.py # Agent tool-context assembly
│   │   │   ├── provider/           # Transport modules (errors/text/capability/
│   │   │   │                       #   streaming/redaction/language/assessment)
│   │   │   ├── agent_loop.py       # ReAct coach agent loop
│   │   │   ├── agent_binding.py    # Tool binding
│   │   │   ├── prompts.py          # System prompts (~3.7k lines)
│   │   │   └── tools.py            # Tool implementations
│   │   ├── pedagogy/
│   │   │   ├── service.py          # PedagogyService (~2.4k lines)
│   │   │   ├── implementation_coach.py
│   │   │   ├── project_idea_miner.py
│   │   │   ├── project_adaptation_coach.py
│   │   │   ├── project_source_scout.py
│   │   │   └── principle_explainer.py
│   │   ├── affect/service.py       # AffectService
│   │   ├── planner/service.py      # PlannerService (~2k lines)
│   │   ├── memory/
│   │   │   ├── service.py          # MemoryService (~9k lines)
│   │   │   ├── models.py
│   │   │   ├── review_scheduler.py # FSRS review scheduler
│   │   │   ├── semantic.py         # Qdrant semantic memory
│   │   │   └── embedder.py
│   │   ├── evaluator/service.py    # EvaluatorService
│   │   ├── research/
│   │   │   ├── service.py          # ResearchOrchestratorService
│   │   │   ├── scheduler.py        # ResearchScheduler
│   │   │   ├── models.py
│   │   │   └── material_intelligence.py
│   │   ├── training/
│   │   │   ├── card_generator.py   # TrainingCardGenerator
│   │   │   ├── card_router.py      # TrainingCardRouter
│   │   │   ├── fsrs_scheduler.py   # FSRS scheduler
│   │   │   └── handoff.py          # Training handoff state machine
│   │   ├── workspace/
│   │   │   ├── authority.py        # WorkspaceAuthority
│   │   │   └── classifier.py       # WorkspaceClassifier
│   │   ├── resources/service.py    # ResourceService
│   │   ├── ingest/service.py       # IngestService (file parsing)
│   │   └── specs/service.py        # SpecService
│   ├── tests/                      # pytest suite (test_api.py is the largest file)
│   └── pyproject.toml              # Package config (ruff, pytest, setuptools)
├── shared/                         # Shared TypeScript types & protocol
│   └── src/
│       ├── index.ts                # Re-exports all modules
│       ├── models.ts               # Core domain types
│       ├── protocol.ts             # WorkbenchSnapshot, HTTP request/response shapes
│       ├── commands.ts             # Command catalog and IDs
│       ├── tokens.ts               # Design tokens
│       ├── sendIntelligence.ts     # Send intent analysis
│       ├── sidebarCommands.ts      # Sidebar view control
│       ├── providerStatus.ts       # Provider health helpers
│       ├── providerProtocols.ts    # Provider protocol support
│       ├── providerProfileDiagnostics.ts
│       ├── providerTest.ts
│       ├── partsRendererRegistry.ts  # 16+ typed message parts
│       ├── trainingHandoffGovernance.ts
│       ├── trainingCardCopy.ts
│       ├── trainingCardRouting.ts
│       ├── trainingCoachBridge.ts
│       ├── trainingRecoveryGovernance.ts
│       ├── trainingHandoffGovernance.ts
│       ├── trainingReturn.ts
│       ├── transferEvidenceGovernance.ts
│       ├── reviewQueueGovernance.ts
│       ├── workspaceAuthority.ts
│       ├── workspaceResourceSearch.ts
│       ├── masterPlanGovernance.ts
│       ├── planGovernance.ts / planGovernance.d.ts
│       ├── projectLaneGovernance.ts
│       ├── resourceWorkbenchGovernance.ts
│       ├── reviewArtifactGovernance.ts
│       ├── suggestedActionGovernance.ts
│       ├── conversationCandidateGovernance.ts
│       ├── remoteWorkspace.ts
│       ├── sandboxNetworkCapabilityNarrative.ts
│       ├── previewAssets.ts
│       ├── coachLanguage.ts
│       └── types.ts
├── scripts/                        # Dev helper scripts
│   ├── bootstrap.ps1               # Full dependency bootstrap
│   ├── dev.ps1                     # Build webview + extension
│   ├── check.ps1                   # Staged verification
│   ├── smoke.ps1                   # Smoke test
│   ├── run-server-tests.mjs        # Pytest runner (creates venv if needed)
│   ├── run-verification-matrix.mjs # Release verification matrix
│   ├── run-real-sidecar-experience-matrix.mjs  # E2E against a real sidecar
│   ├── provider-smoke.mjs / lifecycle.mjs / trainer-turn-smoke.mjs
│   └── verify-workspace.mjs / vsix-ci-capability.mjs
└── e2e/                            # Playwright black-box specs
    ├── trainer.spec.js             # Main sidebar/workbench spec
    ├── trainer-experience-matrix.spec.js       # 50-case experience matrix
    ├── trainer-settings-lifecycle.spec.js      # Provider save/test lifecycle
    ├── trainer-locales.spec.js / trainer-rtl-i18n.spec.js
    ├── trainer-provider-configuration-human.spec.js
    ├── trainer-governance.spec.js / trainer-error-surface.spec.js
    └── trainer-experience-matrix.js            # Shared matrix helpers
```

## SIDEBAR IA (SHIPPED)

Three stable primary destinations: **Coach / Learning / Resources**. History and
Settings are permanent header utilities. Keep all six internal routes and their
commands, deep links and restore actions.

| Route | UI destination | Template |
| --- | --- | --- |
| `coach` | 对话 / Chat | Conversation, CoachReply, NextAction |
| `plan` | 学习 / Learning | LearningHome |
| `resources` | 资料 / Resources | Library, ResourceReader |
| `training` | 学习内部 | FocusedPractice, VerificationResult |
| `progress` | 学习 → 成长 | GrowthEvidence |
| `settings` | header gear | SettingsIndex, SettingsDetail |

`lib/workbenchDestinations.ts` owns route mapping. The full CoachComposer renders
only in Coach; training owns PracticeResponse. Plan and Resource CTAs return
structured context to Coach. Choose a `templates/` owner before adding feature
UI. Preserve governed state and actual verification identities. Use SystemState
for product status, one primary action per initial viewport and disclosure for
advanced facts. `scripts/verify-ui-geometry.mjs` checks the three destinations,
composer ownership, overflow and primary-action budget at 340/420/460 across
dark/light and Chinese/English. Browser fixtures prove layout, not real evidence.

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| **Add VS Code command** | `extension/src/commands/` | Add ID to `shared/src/commands.ts`, handler in `commands/*.ts`, register in `extension/src/commands/index.ts` and `extension/package.json` |
| **Add webview component** | `extension/webview/src/components/` | Add types to `extension/webview/src/lib/types.ts` |
| **Add API endpoint** | `server/app/api/routers.py` | Add route inside `build_router()`, wire via `TrainerRuntime` |
| **Add Pydantic model** | `server/app/core/models.py` | `WorkbenchSnapshot` is the main snapshot contract |
| **Add shared TS type** | `shared/src/models.ts` | Sync with `server/app/core/models.py` |
| **Fix CSS/token** | `extension/webview/src/styles.css` + `shared/src/tokens.ts` | Token-driven, no hardcoded colors |
| **Configure provider** | `extension/src/provider/providerConfigStore.ts` | VS Code SecretStorage for API keys |
| **Coach agent loop** | `server/app/llm/agent_loop.py` + `agent_binding.py` | ReAct loop with tool execution |
| **Training card flow** | `server/app/training/` | card_generator, card_router, fsrs_scheduler, handoff |
| **Test backend** | `server/tests/` | pytest + FastAPI TestClient |
| **Test frontend** | `extension/tests/` | `node --test` (many are source-text guards — prefer behavior tests for new work) |

## CODE MAP

### Extension Host (TypeScript)

| Symbol | File | Role |
|--------|------|------|
| `WorkbenchSidebarController` | `extension/src/core/webviewBridge.ts` | VS Code ↔ webview message bridge, lifecycle management |
| `SidecarHttpClient` | `extension/src/core/httpClient.ts` | HTTP client to FastAPI sidecar |
| `SidecarProcessManager` | `extension/src/core/sidecarProcessManager.ts` | Start/stop/health-check sidecar process |
| `WorkspaceTrustGuard` | `extension/src/core/workspaceTrust.ts` | Workspace trust policy |
| `TrainerHostState` | `extension/src/core/types.ts` | Host state shape (provider, sidecar, workspace) |
| `runtimeRehydration` | `extension/src/core/runtimeRehydration.ts` | Restore session/workbench state on startup |
| `ProviderConfigStore` | `extension/src/provider/providerConfigStore.ts` | Provider config + SecretStorage API key management |
| `TrainerTestController` | `extension/src/testing/testController.ts` | VS Code Testing API integration |

### Webview (React + Zustand)

| Symbol | File | Role |
|--------|------|------|
| `App` | `extension/webview/src/app/App.tsx` | Root workbench — renders the three destinations and all six internal routes |
| `useWorkbenchState` | `extension/webview/src/app/useWorkbenchState.ts` | Zustand store — workbench data + actions |
| `CoachConversationView` | `extension/webview/src/components/coach/` | Coach message history + streaming |
| `CoachPlanView` | `extension/webview/src/components/plan/` | Plan stages, current task, evidence |
| `ResourcesWorkbenchView` | `extension/webview/src/components/resources/` | Resource list, upload, search, preview |
| `TrainingWorkbenchView` | `extension/webview/src/components/training/` | Focused single-card practice + verification (the former multi-panel training chrome was removed) |
| `RemoteVerificationPanel` | `extension/webview/src/components/training/` | Remote verify streaming + unknown-verdict rendering |
| `CoachSettingsView` | `extension/webview/src/components/settings/` | Provider config, coach defaults, language |

### Sidecar (Python/FastAPI)

| Symbol | File | Role |
|--------|------|------|
| `create_app` | `server/app/main.py` | FastAPI app factory — DI wiring of all services |
| `TrainerRuntime` | `server/app/api/runtime.py` | Wires all services, manages sessions |
| `build_router` | `server/app/api/routers.py` (~25.5k lines) | All HTTP endpoints |
| `ProviderService` | `server/app/llm/provider_service.py` (~8.1k lines) | OpenAI-compatible provider abstraction |
| `Coaching modules` | `server/app/llm/coaching_*.py` + `agent_tool_context.py` | Extracted recovery/reply/scaffold/tool-context subsystems (§五十二) |
| `AgentLoop` | `server/app/llm/agent_loop.py` | ReAct tool-calling loop |
| `AgentBinding` | `server/app/llm/agent_binding.py` | Tool definition binding |
| `Prompts` | `server/app/llm/prompts.py` (~3.7k lines) | System prompts for coach modes |
| `Tools` | `server/app/llm/tools.py` | Tool implementations (read_file, diagnostics, search, etc.) |
| `MemoryService` | `server/app/memory/service.py` (~9k lines) | Profile, reflections, weaknesses, teaching assets |
| `ReviewScheduler` | `server/app/memory/review_scheduler.py` | FSRS-based spaced repetition scheduling |
| `SemanticMemory` | `server/app/memory/semantic.py` | Qdrant vector storage for semantic search |
| `PedagogyService` | `server/app/pedagogy/service.py` (~2.4k lines) | Teaching decision engine |
| `ImplementationCoach` | `server/app/pedagogy/implementation_coach.py` | Idea implementation guidance |
| `ProjectIdeaMiner` | `server/app/pedagogy/project_idea_miner.py` | Project idea mining from codebase |
| `ProjectAdaptationCoach` | `server/app/pedagogy/project_adaptation_coach.py` | Cross-project migration guidance |
| `PrincipleExplainer` | `server/app/pedagogy/principle_explainer.py` | Concept/principle explanation |
| `ProjectSourceScout` | `server/app/pedagogy/project_source_scout.py` | Reference repo suggestion |
| `AffectService` | `server/app/affect/service.py` | Learner affect detection + tone decisions |
| `PlannerService` | `server/app/planner/service.py` (~2k lines) | Learning plan generation |
| `EvaluatorService` | `server/app/evaluator/service.py` | Static/dynamic/semantic code evaluation |
| `ResearchOrchestratorService` | `server/app/research/service.py` | Multi-theme deep research (background, no primary UI) |
| `ResearchScheduler` | `server/app/research/scheduler.py` | Time-based research checkpoints |
| `TrainingCardGenerator` | `server/app/training/card_generator.py` | Training card generation |
| `TrainingCardRouter` | `server/app/training/card_router.py` | Card type routing |
| `FSRSScheduler` | `server/app/training/fsrs_scheduler.py` | FSRS scheduling (py-fsrs) |
| `TrainingHandoff` | `server/app/training/handoff.py` | Training handoff state machine |
| `WorkspaceAuthority` | `server/app/workspace/authority.py` | Workspace permission model |
| `WorkspaceClassifier` | `server/app/workspace/classifier.py` | Workspace type classification |
| `TrainerRepository` | `server/app/db/repository.py` | SQLite data access (main) |
| `ResearchRepository` | `server/app/db/research_repository.py` | Research SQLite data access |

### Shared (TypeScript)

| Symbol | File | Role |
|--------|------|------|
| `models.ts` | `shared/src/models.ts` | Core domain types (Plan, Memory, TeachingDecision, etc.) |
| `protocol.ts` | `shared/src/protocol.ts` | WorkbenchSnapshot, SessionMessageRequest/Response, etc. |
| `commands.ts` | `shared/src/commands.ts` | Command catalog and IDs |
| `tokens.ts` | `shared/src/tokens.ts` | Design tokens (colors, spacing, radius, typography) |
| `sidearCommands.ts` | `shared/src/sidebarCommands.ts` | Sidebar view control commands |
| `sendIntelligence.ts` | `shared/src/sendIntelligence.ts` | Send intent analysis (coach vs plan vs review) |

## API ENDPOINTS

FastAPI sidecar (port 8765, extension-managed range 34891-34911):

| Method | Path | Response | Purpose |
|--------|------|----------|---------|
| GET | `/health` | `{status}` | Health check |
| POST | `/session/start` | WorkbenchSnapshot | Start or restore session |
| POST | `/session/message` | WorkbenchSnapshot | Single-turn coaching message |
| POST | `/turn` | WorkbenchSnapshot | Full coaching turn with pedagogy |
| POST | `/session/message/stream` | Streaming | Streaming coaching reply |
| POST | `/turn/stream` | Streaming | Streaming full coaching turn |
| POST | `/plan/generate` | WorkbenchSnapshot | Generate learning plan |
| POST | `/plan/update` | WorkbenchSnapshot | Freeze/update plan |
| POST | `/provider/test` | test result | Test provider connectivity |
| POST | `/provider/models` | model list | List available models |
| POST | `/resource/upload` | ResourceRecord | Upload/attach resource |
| POST | `/resource/index` | ResourceRecord | Index resource for search |
| POST | `/task/next` | TaskSpec | Generate next task |
| POST | `/task/specify` | TaskSpec | Convert NL goal → task spec |
| POST | `/evaluate/current-file` | EvaluationReport | Evaluate current file |
| POST | `/evaluate/snippet` | EvaluationReport | Evaluate code snippet |
| POST | `/learning/signal` | WorkbenchSnapshot | Record learning outcome |
| GET | `/memory/summary` | WorkbenchSnapshot | Memory summary |
| GET | `/memory/profile` | UserProfile | User profile |
| GET | `/memory/weaknesses` | list[str] | Known weaknesses |
| GET | `/memory/reviews` | list[str] | Review queue |
| GET | `/memory/teaching-assets` | TeachingAsset[] | Teaching assets |
| POST | `/memory/settings` | WorkbenchSnapshot | Save coach settings |

## CONVENTIONS
- **Python**: Ruff (E/F/I/B, line-length 100), Pyright, Python 3.12+
- **TypeScript**: Strict mode, no `as any`/`@ts-ignore`
- **CSS**: Design tokens only (`--bg-0`, `--accent`, etc.), no hardcoded colors
- **Loading idioms** (§四十八): one per surface — `.skeleton` for known-structure content, `.coach-streaming-dots` for coach thinking/streaming, `.trainer-spinner` for inline operations; never stack two, always keep the `prefers-reduced-motion` fallback
- **State**: Zustand for webview, dataclass for Python domain models
- **API**: FastAPI with Pydantic models, snake_case payload with camelCase aliases
- **Messages**: webview→extension via `postMessage`, extension→webview via `HostMessage`
- **i18n**: 8 languages (zh-CN, en-US, es-ES, fr-FR, de-DE, ja-JP, ko-KR, pt-BR), keyed via `CopyKey`
- **Training**: FSRS-based spaced repetition (`py-fsrs`), dual definition in Python and TS

## UNIQUE PATTERNS
- **Local Brain + Remote Hands**: identity/memory/plans/resources/evidence stay on the local UI host; remote project access goes through the `WorkspaceGateway` (`extension/src/workspace/`) and the separate workspace-kind Companion (`remote-extension/`, `trainer.remote.capabilities` / `trainer.remote.request`)
- `LearningPlan` dual-field sync (`id`/`plan_id`, `cadence`/`weekly_cadence`, `stages`/`phases`) — `server/app/core/models.py`
- Formal plan saves are optimistic-locked: every plan write advances `_plan_revision` under the SQLite write lock (`save_plan_with_revision` / `save_plan_advancing_revision`); clients must send `expected_revision`, conflicts return 409 `plan_revision_conflict`
- Evidence honesty: `/training/attempt/evidence` always records `self_reported` (client `trust_level` is ignored); host-trusted evidence only via `/training/verification/attest`; evidence citations resolve `resource_id`/`version_id`/`content_hash`/`location` server-side, and a deleted source flags citations until a same-hash re-index clears them
- Host attestation delivery (R1): `/training/verification/attest` accepts an optional `idempotency_key`; remote verification sends `remote-verify:{companionSessionId}:{cardId}` (`attestationIdempotencyKey`, `extension/src/testing/trainingAttestation.ts`) so a resend replays via the training-reliability ledger instead of double-recording. Delivery failures are classified (`classifyAttestationDeliveryFailure`): `not_arrived` (typed pre-send guard `AttestationNotArrivedError`, connect/DNS-class error codes) is resent once; `ambiguous` (timeout, lost response, HTTP error) never auto-resends and surfaces the language-neutral marker `[[trainer-attestation-undelivered]]`, which the webview maps to eight-language Training-scoped copy (`operationMessageGovernance.ts`). Boundary: the replay window is the workspace's single-slot `latest_training_reliability` record — once another training save replaces it, a same-key retry executes again. Fail-closed unchanged: interrupted/cancelled/timed-out runs record NO evidence.
- Typed Parts Registry: 16+ message artifact kinds, rendered via `shared/src/partsRendererRegistry.ts`
- Coach agent loop: ReAct pattern with tool calling (`server/app/llm/agent_loop.py`)
- Training handoff state machine: card generation → routing → feedback → next card
- Research uses `dataclass(slots=True)`, core uses `BaseModel` (Pydantic) — intentional separation
- `WorkbenchSnapshot` is the universal response envelope across most API endpoints
- Apple ._ metadata files (`._*.py`, `._*.ts`) are byproducts of macOS copy tools — already covered by `.gitignore` (`._*`), safe to ignore on Windows/Linux

## CROSS-PLATFORM GUIDE

本项目默认用 **Windows + PowerShell** 开发，但代码本身三平台通用。

### What is cross-platform

| 代码 | 平台 | 说明 |
|------|------|------|
| `extension/src/` (TS) | ✅ 三平台 | 纯 TypeScript，VS Code API 三平台一致 |
| `extension/webview/` (React) | ✅ 三平台 | Vite build 产物平台无关 |
| `shared/src/` (TS) | ✅ 三平台 | 纯类型定义 |
| `server/app/` (Python) | ✅ 三平台 | Python 3.12+ 跨平台 |
| `extension/bundled/` (Python source) | ✅ 三平台 | 98 个 `.py` 文件，平台无关 |
| `.vsix` 打包文件 | ✅ 三平台 | ZIP 格式，任何平台打包/安装一致 |

### What is NOT cross-platform (yet)

| 代码 | 当前平台 | 问题 |
|------|---------|------|
| `scripts/*.ps1` | ❌ Windows 独占 | PowerShell 脚本，macOS/Linux 无 `.sh` 等价版本 |
| `extension/bundled/bin/darwin-arm64/` | ❌ macOS-only | 包含 `.dylib`/`.so` 原生库，仅 darwin-arm64 架构 |

### Migrating to a new platform

在 macOS / Linux 上使用本仓库时：

1. **忽略 `.ps1` 脚本** — 使用 README 中的跨平台等价命令
2. **设置 Python venv**:
   ```bash
   cd server && python3.12 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
   ```
3. **构建**：`npm run build`（三平台通用）
4. **启动 sidecar**：`cd server && python run_sidecar.py --host 127.0.0.1 --port 8765 --reload`
5. **运行测试**：`cd server && python -m pytest tests/ -v`

### Platform-specific artifacts to ignore

| 文件/目录 | 来源 | 应被忽略 |
|-----------|------|---------|
| `._*` 文件 | macOS AppleDouble 元数据 (Finder/rsync 创建) | ✅ `.gitignore` 已覆盖 (`._*`)，无需处理 |
| `.tmp-debug*` | Windows 开发调试遗留目录 | ✅ 安全删除 |
| `server/.venv/` | Python 虚拟环境 | ✅ `.gitignore` 已覆盖 |
| `extension/bundled/bin/darwin-arm64/` | macOS 原生二进制 | ✅ windows/linux 上无影响 |
| `extension/node_modules/` | npm 依赖 | ✅ `.gitignore` 已覆盖 |

## ANTI-PATTERNS
- NEVER hardcode color values in components — use CSS variables
- NEVER use `as any` or `@ts-ignore` — fix the types
- NEVER catch and swallow errors silently
- NEVER skip `lsp_diagnostics` after file edits
- NEVER modify `server/app/core/models.py` Pydantic models without checking `model_validator`
- Research models use `dataclass` (not Pydantic) — don't mix patterns

## COMMANDS

```bash
# TypeScript checks (webview + extension host)
npm run check

# Extension tests (node:test)
npm run test:extension

# Backend tests (pytest; creates server/.venv if needed)
npm run test:server
# or directly:
cd server && python -m pytest tests/ -v

# Build all
npm run build

# Browser-preview E2E (Playwright; builds the preview bundle first)
npm run test:experience-matrix
npx playwright test e2e/trainer.spec.js
npx playwright test e2e/trainer-settings-lifecycle.spec.js

# Webview performance probe (long-session nav latency + streaming longtasks;
# serves the existing preview dist, report-only unless --strict; budgets:
# streaming burst longtask = 0, warm nav p90 < 100ms. Baseline:
# docs/verification/perf-probe-baseline.json)
# Discipline: re-shoot the baseline JSON whenever UI geometry or surface
# structure changes (banner/list moves, keep-alive changes, new surfaces) —
# single-machine single-sample deltas under ~20% are noise. --strict verdict:
# NOT part of the verify matrix — headless single-sample numbers are too noisy
# to gate CI; run it locally (or in a dedicated perf job) before/after
# performance-relevant changes and fail on budget misses there.
npm run perf:probe

# Release verification + packaging
npm run verify
npm run package:vsix
npm run verify:delivery  # verify + experience matrix + package

# Remote Workspace Companion (built automatically by vscode:prepublish)
npm run build:remote-companion --prefix extension
npm run package:remote-companion --prefix extension
./extension/node_modules/.bin/tsc -p remote-extension/tsconfig.json --noEmit

# Windows-only helpers (PowerShell)
powershell -ExecutionPolicy Bypass -File scripts/bootstrap.ps1
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1
powershell -ExecutionPolicy Bypass -File scripts/check.ps1 -Strict

# Start sidecar manually (dev)
cd server && .venv/bin/python run_sidecar.py --host 127.0.0.1 --port 8765 --reload

# Standalone webview preview (no VS Code needed)
cd extension/webview && npm run dev   # then open the printed URL
```

## NOTES
- Sidecar port default: 8765, extension-managed range: 34891-34911
- Mock data in `extension/webview/src/lib/mockData.ts` for browser-only dev
- Browser preview: `extension/webview/src/lib/browserPreviewHarness.ts` — standalone Vite dev without VS Code
- Workspace data stored under VS Code global storage directory, not in repo
- Bundled sidecar: `extension/bundled/` (~245 MB, 98 .py files) — for .vsix distribution
- Companion VSIX (`extension/bundled/remote/`) and native sidecar binaries are build-time artifacts (gitignored, `*.vsix`); `vscode:prepublish` rebuilds the companion before packaging, and `verify-package.mjs` asserts its presence and entrypoint
- Provider API keys always live in the local UI host's SecretStorage (`ui_proxy`); the remote Companion never receives credentials
- Largest files (approximate; line counts drift with each consolidation round — re-measure before relying on them): `routers.py`, `App.tsx`, `test_api.py`, `memory/service.py`, `CoachSettingsView.tsx`, `provider_service.py`, `copy.ts`; webview CSS lives across `webview/src/styles/sections/` (the top-level `styles.css` is a tombstone)
- i18n covered: zh-CN, en-US, es-ES, fr-FR, de-DE, ja-JP, ko-KR, pt-BR
