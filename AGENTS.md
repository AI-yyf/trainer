# PROJECT KNOWLEDGE BASE

**Generated:** 2026-06-19
**Updated:** 2026-09-18 — refreshed structure, sizes, and test-stack notes
**Branch:** main (active)

> **Product truth:** `.trainer-convergence/product-contract.md` (v2.1, locked 2026-11-21) and strategy [`docs/STRATEGY.md`](docs/STRATEGY.md). If this file, `SPEC.md` or any plan disagrees with the contract, the contract wins — fix the other side in the same commit. Roadmap: two destinations + one conversation + single-composer sovereignty; RethinkFun state-flow pedagogy kernel; learning is the conversation's read-only memory; four formal learner-visible concepts (目标 / 练习 / 掌握进度 / 资料); all data, resources, and memory live under one unified `<LibraryRoot>`.

## OVERVIEW
Desktop-first VS Code extension + FastAPI Python sidecar for conversation-driven coding training. Two-destination React workbench (`Chat / Resources`, with six internal routes where the three learning routes are compatibility aliases into the learning drawer) with keyboard-first navigation, ReAct coach agent loop, and FSRS-based spaced repetition.

## STRUCTURE

```
trainer/                            # Repository root
├── extension/                      # VS Code extension host (TypeScript)
│   ├── src/                        # Extension commands, core services, webview bridge
│   │   ├── commands/               # Command handlers grouped by domain
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
│   ├── bundled/                    # Bundled Python sidecar source + native binaries (~270 MB; server/app mirrors ~236 .py files)
│   │   └── remote/                 # trainer-workspace-companion.vsix (build output, gitignored)
│   ├── tests/                      # node:test suite (many are source-text guards — prefer behavior tests for new work)
│   ├── dist/                       # Build output
│   └── package.json                # Extension manifest (82 commands, 1 webview view)
├── remote-extension/               # Trainer Workspace Companion (extensionKind: ["workspace"])
│   ├── src/extension.ts            # File/search/hash/diagnostics/environment/verify ops
│   ├── package.json                # Serialized via trainer.remote.capabilities/request commands
│   └── tsconfig.json               # Compiles shared/src/remoteProtocol.ts into dist/
├── server/                         # FastAPI Python sidecar
│   ├── app/                        # Application package
│   │   ├── __init__.py
│   │   ├── main.py                 # create_app() — FastAPI app factory with DI
│   │   ├── api/
│   │   │   ├── routers.py          # Core HTTP endpoints (~13.9k lines; domain routers live in routes/)
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

Two stable primary destinations: **Chat / Resources**. Learning is not a
destination — it is a drawer opened from the header icon beside the session
history, plus a one-line learning strip above the conversation. History and
Settings are permanent header utilities. All six internal routes and their
commands, deep links and restore actions stay valid.

| Route | UI destination | Template |
| --- | --- | --- |
| `coach` | 对话 / Chat | Conversation, CoachReply, NextAction |
| `plan` | alias → 对话 + 学习抽屉"当前目标" | LearningHome (inside the drawer) |
| `resources` | 资料 / Resources | Library, ResourceReader |
| `training` | alias → 对话 + 学习抽屉"到期练习" | FocusedPractice (inline card) |
| `progress` | alias → 对话 + 学习抽屉"掌握进度" | inline progress card |
| `settings` | header gear | SettingsIndex, SettingsDetail |

`lib/workbenchDestinations.ts` owns route mapping; `plan/training/progress` are
compatibility aliases that resolve to Chat with the learning drawer opened on
the matching section (`normalizeLearningSection`). The drawer is a **modal
sheet** at the shell level: it floats over the conversation and the composer
together (the composer stays mounted underneath, so its draft and focus
survive), while the header — identity row, navigation row and utilities —
stays above it and clickable. Its content is a stack of three same-grammar
**cards** (`.learning-drawer__card`: titled header + optional right-aligned
metric + body + at most one action) for 当前目标 / 到期练习 / 掌握进度 — it is
not a tab set. Each card owns one fact and says it once: the goal card names
the plan step, so the practice card drops a title that repeats it
(`isSameLearningFact` in `lib/learningSummary.ts`), and the drawer keeps one
accent action (the goal card's) while the other cards stay secondary. The
progress card («掌握进度») renders **one single unified 4-segment capability bar**
above formal 2-column capability rows (`理解 / 实现 / 调试 / 迁移`), **never a
percentage**: one plain-language summary sentence followed by the single bar
whose segments map 1:1 to server projection states (`capabilityLevel` in
`lib/learningSummary.ts`: `not_verified`/`needs_review` → 0, `assisted` → 1,
`independent` → 2, `repeat_verified` → 3), and formal status rows (`未验证 /
需辅助 / 独立完成 / 稳定掌握 / 待巩固` with verification counts). Filled
segments use the neutral accent ramp (`color-mix` over `--accent`), never a
hardcoded brand color.
`templates/LearningHome.tsx` takes `variant="drawer"` for that compact form: the
plan's stages and evidence stay as plain read-only rows, the starter
template gallery is gone, and every adjustment or detail inquiry happens in the
single docked `CoachComposer` — the drawer is a read-only reference surface, and
the inline practice card is a calm collapsible action/verification card with no
second textarea and no card-library CRUD chrome; practice answers, reflections,
and detail queries all route through the single `CoachComposer`. Keep the
composer's appearance, placement, and toolbar controls fixed unless the user
explicitly asks for a design change. Choose a `templates/` owner before adding
feature UI. Preserve governed state and actual verification identities. Use
SystemState for product status, one primary action per initial viewport and
disclosure for advanced facts. `scripts/verify-ui-geometry.mjs` checks the two
destinations, the learning drawer sections, single-composer sovereignty,
overflow and primary-action budget at 340/420/460 across dark/light and
Chinese/English. Browser fixtures prove layout, not real evidence.

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| **Add VS Code command** | `extension/src/commands/` | Add ID to `shared/src/commands.ts`, handler in `commands/*.ts`, register in `extension/src/commands/index.ts` and `extension/package.json` |
| **Add webview component** | `extension/webview/src/components/` | Add types to `extension/webview/src/lib/types.ts` |
| **Add API endpoint** | `server/app/api/routes/<domain>.py` | New domains get a `build_*_router(runtime, deps)` module; legacy core endpoints still live in `routers.py`'s `build_router()` |
| **Add Pydantic model** | `server/app/core/models.py` | `WorkbenchSnapshot` is the main snapshot contract |
| **Add shared TS type** | `shared/src/models.ts` | Sync with `server/app/core/models.py` |
| **Fix CSS/token** | `extension/webview/src/styles/sections/` + `shared/src/tokens.ts` | Token-driven, no hardcoded colors (`styles.css` is a 9-line tombstone) |
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
| `App` | `extension/webview/src/app/App.tsx` | Root workbench — renders the two destinations, the learning drawer and all six internal routes |
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
| `build_router` | `server/app/api/routers.py` (~13.9k lines) | Core HTTP endpoints; heavy domains are extracted into `api/routes/` |
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
- **Host payloads are untrusted at runtime**: the webview declares precise types, but a field can arrive as a record, a number or blank text. Text that the view treats as text is normalized once, at the boundary (`lib/hostText.ts` for the training state), so a malformed field degrades instead of throwing inside a render and blanking the whole workbench with the error boundary. Never call `.trim()` / `.replace()` on a host value that has not been normalized.
- **App.tsx is wiring only**: `extension/webview/src/app/App.tsx` stays an orchestrator. New behavior goes into its own owner — `lib/learningSummary.ts` + `components/learning/*` for learning, `lib/useHostOperationResolver.ts` for host operation correlation, `components/<area>/*` for a surface. When a feature needs logic inside App.tsx, extract it instead of appending; re-measure the line count before claiming the file did not grow.
- **GUI gates verify the delivered artifact**: the real-VS Code gates (`verify:coach-gui`, `verify:canonical-gui`, `verify:i18n-zoom`, `verify:resource-grounding-gui`) install the packaged VSIX, so they first call `ensureFreshVsix` (`extension/scripts/prepare-current-vsix.mjs`): it repackages under the shared build lock and proves the artifact still matches the sources it packages (`scripts/vsix-freshness.mjs`). A stale artifact stops the gate instead of producing a report about code the tree no longer contains. `TRAINER_SKIP_VSIX_REBUILD=1` skips the repackage and then refuses to run with a stale artifact. `verify:frozen-sidecar` goes one layer further: it boots the frozen `bundled/bin/<platform>-<arch>/trainer-sidecar` that actually ships and checks behaviour over HTTP (instance-token guard, plan `expected_revision` 428/200/409, two real processes over one data directory keeping both writes) — the unit suites only ever run the Python sources.

## UNIQUE PATTERNS
- **Local Brain + Remote Hands**: identity/memory/plans/resources/evidence stay on the local UI host; remote project access goes through the `WorkspaceGateway` (`extension/src/workspace/`) and the separate workspace-kind Companion (`remote-extension/`, `trainer.remote.capabilities` / `trainer.remote.request`)
- `LearningPlan` dual-field sync (`id`/`plan_id`, `cadence`/`weekly_cadence`, `stages`/`phases`) — `server/app/core/models.py`
- Formal plan saves are optimistic-locked: every plan write advances `_plan_revision` under the SQLite write lock (`save_plan_with_revision` / `save_plan_advancing_revision`); clients must send `expected_revision`. A versioned plan saved without it is refused with 428 `plan_revision_required` (only an explicit `legacy`/`migration` label takes the compatibility path), and a stale revision returns 409 `plan_revision_conflict`
- Evidence honesty: `/training/attempt/evidence` always records `self_reported` (client `trust_level` is ignored); host-trusted evidence only via `/training/verification/attest`; evidence citations resolve `resource_id`/`version_id`/`content_hash`/`location` server-side, and a deleted source flags citations until a same-hash re-index clears them
- FSRS ownership is narrow and explicit: `MasteryRecord` persists the full card identity (`stability`, `difficulty`, `state`, `step`, `last_reviewed_at`, `due`, `interval`, `reps`, `lapses`), and a concept review rebuilds from all of it — dropping the review time or learning step made py-fsrs treat a reviewed concept as new. Retrievability comes from `Scheduler.get_card_retrievability`, never a second exponential curve. A review rating schedules memory; it never changes the capability `score`/`confidence`. Review-frequency preference/`apply_review_frequency_bias` is queue surfacing only and must not rewrite the FSRS due date. The training-verify path persists card, FSRS state and mastery schedule in one `_persist_structured` write (`upsert_card(..., persist=False)`), and `run_training_reliability` executes every body inside `structured_write_batch`: the card status, evidence, handoff, mastery and FSRS mutations land as one structured-memory revision, while a raised body discards the pending write. A failed write cannot leave a verified card without its review history. FSRS requires `fsrs>=6.3.1`.
- Training acceptance (`app/evaluator/service.py::_training_acceptance_check`): a backticked identifier in a card criterion is a required code symbol, and comments/strings never count as evidence for one. Model-authored cards also name artifacts and process words with backticks, which no correct answer contains as an identifier, so each gets its own rule: `docstring` and type hints are checked structurally against the Python AST on the definition the criterion names; `pytest`/`python` are satisfied by a run that actually executed and passed; comments and out-of-file documentation (`README`, docs) defer to reflection instead of failing forever. `TrainingCardCandidateSnapshot` normalizes the card side to match: `files_to_touch` keeps only path-shaped targets (a model once appended a whole sentence to the file name, which made host verification refuse every real artifact), and a symbol the card's own text presents as an alternative ("`torch.minimum`（或 `torch.min`）") stops being required on its own. A backticked callable signature ("`ppo_clip_loss(new_logprobs, old_logprobs, advantages, clip_eps=0.2)`") requires only the callable; its parameter names illustrate the interface and are never scanned as symbols, so an answer that names them differently still passes.
- Host attestation delivery (R1): `/training/verification/attest` accepts an optional `idempotency_key`; remote verification sends `remote-verify:{companionSessionId}:{cardId}` (`attestationIdempotencyKey`, `extension/src/testing/trainingAttestation.ts`) so a resend replays via the training-reliability ledger instead of double-recording. Delivery failures are classified (`classifyAttestationDeliveryFailure`): `not_arrived` (typed pre-send guard `AttestationNotArrivedError`, connect/DNS-class error codes) is resent once; `ambiguous` (timeout, lost response, HTTP error) never auto-resends and surfaces the language-neutral marker `[[trainer-attestation-undelivered]]`, which the webview maps to eight-language Training-scoped copy (`operationMessageGovernance.ts`). Boundary: the replay window is the workspace's single-slot `latest_training_reliability` record — once another training save replaces it, a same-key retry executes again. Fail-closed unchanged for runs that never persisted: interrupted/cancelled/timed-out runs whose `work()` did not complete record NO evidence. A cancel/timeout that races a *completed* persistence keeps the already-written evidence and the ledger records `outcome=success` annotated with `cancel_after`/`timeout_after` (`server/app/training/reliability.py` `mark_succeeded`; `memory/training_reliability_mixin.py` `_cancel_raced_work`) instead of rewriting it as failed/cancelled — the client is never told a persisted save failed.
- Typed Parts Registry: 16+ message artifact kinds, rendered via `shared/src/partsRendererRegistry.ts`
- The Chrome popup is a quick-capture card: it captures the current page and, for a downloadable source (PDF, repository), it also offers "download to the library". The destination is resolved by the sidecar (`/browser/status` → `download_target`) and is **always the library root** (`Trainer Library/`) — never a per-project folder — so every capture lands in one place; the popup shows that target read-only and never types or stores a path, and there is no "other sources" or focus-binding section in it. The Chrome right-click menu still covers links, PDF pages and repositories, and the side panel carries the conversation. The VS Code capture entry (`components/resources/ResourceCaptureDialog.tsx`) recognizes its own source: an address (web / PDF / GitHub / Gitee / GitLab via `lib/captureSourceKind.ts`) or one file (a PDF, or a QR image whose link is read with the platform `BarcodeDetector` — no extra dependency), plus the target knowledge base. The forge lane is shared by `parse_source_repo` (GitHub, Gitee, GitLab)
- The library is Markdown-only: the canonical document (`server/app/resources/canonical_store.py`) is the only artifact — `resolveResourceOpenTarget` opens it, there is no "open original" action, and the legacy originals directory is removed only after a verified Markdown write. The migration bridge (`trainer.resource.markdownOnlyMigration`) previews first, writes a backup manifest, and only runs the destructive pass after one explicit confirmation; a resource that fails to convert is marked, never silently deleted. The destructive pass converts **before** it deletes: an original is only removed behind a readable, non-empty canonical Markdown, and a resource whose originals are the only copy keeps them and is reported as a failure (`originals_kept`, `status: "partial"`) instead of being deleted behind a promise it cannot keep.
- The library never drops the last copy of a resource: every path that removes bytes checks the replacement first. `ResourceService._remove_originals_behind_markdown` is the **only** place the migration drops legacy originals, and it refuses unless the canonical document is readable and non-empty (`_has_readable_markdown`); `_discard_managed_inline_source` applies the same rule to the inline upload copy. A download rollback removes only the artifact the capture itself created (`download.created`). When a new path deletes a file, it has to name the artifact that stands behind it.
- The alignment gate (`scripts/verify-ui-geometry.mjs`) locks the visible rules, not just the overflow: library rows keep their icon and title on one center line (≤1px), every menu label shares one left edge (the icon column is fixed, not `auto`), inline code stays an inline box inside the paragraph's line height, CJK lines keep a readable line height, the message meta (role + timestamp) shares one baseline instead of being centred against each other, and RTL mirrors the row icon without overflowing. The style sections use logical properties (`margin-inline-start`, `border-inline-start`, …) so an RTL shell mirrors without a second set of overrides
- The Chrome side panel is a real conversation client over the paired credential: `/browser/chat/*` (`server/app/api/routes/browser_chat.py`) is a bearer-authenticated proxy over the existing `/session/*` routes, so the browser never sees the sidecar token or a provider key, and provider overrides from the browser are stripped. The side panel only captures in the popup; the side panel carries the session, the streamed reply, the history and the practice card.
- The browser panel completes a practice, it does not merely talk about one: an answer typed in the panel's practice card travels the server's training lane (`/browser/chat/training/attempt/start` → `attempt/update` → `attempt/evidence` → `training/practice-return`), and the credential — not the client — names the workspace. The panel has no runner and no verifier, so the evidence is a self report: the server fixes its trust level (`self_reported`), which keeps it visible in the drilldown without attesting executable capability. A refused recording is reported as "not recorded" — no progress receipt, no coaching turn, no claim of completion.
- Browser pairing state is shared by every sidecar over one LibraryRoot (`server/app/browser_bridge/service.py`). Credentials and trusted origins are the union of what is on disk and what the process holds, re-read on every credential lookup and every write; revocation leaves tombstones that only an explicit host trust or a new code exchange forgives. A revocation in one window must retire the browser in every other window, and no process may write a retired credential back. The read-merge-replace cycle runs under an OS-level lock (`browser_bridge.json.lock`, `fcntl.flock`/`msvcrt.locking`) and writes a unique fsynced temp file before `os.replace`; the in-process RLock alone allowed two windows to sync, then replace each other's tombstone. Auto-issued credentials past the per-workspace cap are tombstoned, and `issue_auto_credential` re-checks a route-authorized extension origin under the lock so a revoke racing the mint cannot leave a valid credential.
- The auto-pair boundary is the browser, not the host: `/browser/auto-pair` is exempt from the instance token and trusts the extension Origin, which web pages and other extensions cannot forge but a native loopback process can send freely. It defends against pages and extensions; a local process that already knows the paired extension id can reach the browser lane. Nothing outside the browser lane relies on it.
- Every process the sidecar spawns gets `child_process_environment()` (`server/app/core/process_env.py`): the sidecar token never reaches a learner tool, a repository's test suite or a language server. `tests/test_child_process_environment.py` parses every spawn call in `app/` — `subprocess.*`, aliased/`from subprocess import` forms, `asyncio.create_subprocess_*`, and `os.system`/`os.exec*`/`os.spawn*` (which inherit and accept no `env=`) — and fails on one that inherits the environment or builds it any other way. Other ambient host variables are deliberately inherited (these children already run as the learner), so the guarantee is scoped to the sidecar token rather than every secret-shaped name. `python -m pylsp` also runs with `PYTHONSAFEPATH=1` because it starts inside the learner's repository.
- Remote images are classified by the address the browser will fetch (`new URL`), never by a string prefix: `https:\host\x.png`, `http:host/x.png`, a network-path reference and an address with embedded newlines are all remote. Untrusted HTML cannot forge a placeholder: the sanitizer strips the `data-remote-*` / `data-trainer-remote-image` attributes the delegated click handler trusts. SVG attributes are checked too: only same-document fragment references survive (`fill="url(#grad)"`), while paint-server/transform URLs, CSS escapes and external `href`s fail closed — a `fill="url(https://…)"` is fetched on render without a click.
- A training save that could not run is never reported as success. When another request holds the workspace's reliability slot for the whole bounded wait, `run_training_reliability` returns the unmutated workspace with a `training_reliability_busy` marker; every route and the `verify_practice_current_file` tool check it (`busy_marker`) and answer 409 instead of "saved". Only a true duplicate (same request id or idempotency key) coalesces with an in-flight save — matching on command + card used to swallow a different result for the same card.
- A provider outage during card generation is not a rejected card. `CardGenerationService` classifies the transport cause in the exception chain (`status_code`/`provider_retryable`/timeouts) and `CardGenerationProviderFailure` carries `provider_unavailable` (localized "temporarily unavailable", retryable, HTTP 503 + `Retry-After: 5`) or `provider_quota_exhausted` (HTTP 402) separately from model-content failures (HTTP 400). Each synchronous attempt is bounded (`_CARD_GENERATION_ATTEMPT_TIMEOUT_SECONDS`); the generation client itself intentionally keeps no read ceiling. An upstream 502 used to read as "the model card was not accepted", which blamed the model for an outage. A host `lastTestResult` is evidence only for the exact base URL/model/protocol it tested: both generate-card routes reject a mismatched passed record with 400 before any provider call instead of adopting it as this connection's capability proof.
- Learning cards are minted from a reply with one click each: a practice card (动手) and a flash card (闪记). Both land inline in the conversation, where the learner answers, verifies and reflects inside the card — the flash card carries its own bolt glyph so the two never read as the same action
- One conversation, two lanes: learning is not a destination, so `plan/training/progress` are reply-lane markers (`active_view`) while the destination is Chat. `composer_conversation_scope` (`server/app/llm/conversation_scope.py`) therefore maps only `resources` to its own scope — learning turns read and write the one coach conversation, and the webview never filters the conversation by `sourceView`
- The context ring opens one model list (`components/composer/ComposerModelMenu.tsx`): provider identity, always-visible search, flat model rows with a vision badge and the active check, and a single thinking-intensity slider at the bottom. Saved providers are groups with their own model rows; selecting a row carries the profile half of `{profileId, modelId}` (`switchProviderModel` payload) so the host switches provider and model atomically. Thinking is per model (`modelThinkingConfig`, mirrored to the flat `thinkingConfig` for the active model): switching to a model restores its own effort, and the slider saves the current model's choice. Preview-only cross-provider selection applies the profile patch before selecting the model; the host does not have that ordering window. At a ≤220px container (200% zoom) the identity row keeps the provider name and hides the decorative API pill and row badges; the footer still names the active model's effort.
- Explicit restore targets own the training foreground (`trainingRestoreContext`); the store retires that intent when a later `state/patch` selects another card, so a restored card never outlives the live selection it was restoring
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
- Bundled sidecar: `extension/bundled/` (~270 MB, 98 .py files) — for .vsix distribution
- Companion VSIX (`extension/bundled/remote/`) and native sidecar binaries are build-time artifacts (gitignored, `*.vsix`); `vscode:prepublish` rebuilds the companion before packaging, and `verify-package.mjs` asserts its presence and entrypoint
- Provider API keys always live in the local UI host's SecretStorage (`ui_proxy`); the remote Companion never receives credentials
- Largest files (measured 2026-11-24; re-measure before relying on them): `routers.py` (~13.9k), `App.tsx` (~12.3k), `test_api.py` (~11.6k), `memory/service.py` (~9.4k), `CoachSettingsView.tsx` (~8k), `provider_service.py` (~7.1k); i18n copy lives in `webview/src/lib/i18n/segments/` (`copy.ts` is a thin aggregator); webview CSS lives across `webview/src/styles/sections/` (the top-level `styles.css` is a tombstone)
- i18n covered: zh-CN, en-US, es-ES, fr-FR, de-DE, ja-JP, ko-KR, pt-BR
