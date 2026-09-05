# PROJECT KNOWLEDGE BASE

**Generated:** 2026-06-19
**Branch:** main

## OVERVIEW
Desktop-first VS Code extension + FastAPI Python sidecar for conversation-driven coding training. Five-view React workbench (`Coach / Plan / Resources / Training / Settings`) with keyboard-first navigation, ReAct coach agent loop, and FSRS-based spaced repetition.

## STRUCTURE

```
trainer_final/                      # Repository root
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
│   │   ├── testing/                # VS Code Testing API
│   │   │   └── testController.ts   # TrainerTestController
│   │   └── views/                  # Native VS Code tree views
│   ├── webview/                    # React workbench UI (Vite + Zustand + i18n)
│   │   └── src/
│   │       ├── app/
│   │       │   ├── App.tsx         # Root workbench (5843 lines — renders all 5 views)
│   │       │   ├── useWorkbenchState.ts  # Zustand store
│   │       │   ├── views/          # (empty)
│   │       │   └── useTrainingCommands.ts
│   │       ├── components/
│   │       │   ├── coach/          # CoachConversationView, CoachMessageBubble, etc.
│   │       │   ├── plan/           # CoachPlanView + evidence governance
│   │       │   ├── resources/      # ResourcesWorkbenchView (80814 lines)
│   │       │   ├── training/       # TrainingWorkbenchView, CardPanel, etc.
│   │       │   ├── settings/       # CoachSettingsView (62537 lines)
│   │       │   ├── composer/       # CoachComposer
│   │       │   ├── common/         # Shared UI parts
│   │       │   ├── flash/          # Flash card components
│   │       │   ├── firstlook/      # First-time experience
│   │       │   ├── icons/          # SVG icon components
│   │       │   ├── parts/          # Typed message part renderers
│   │       │   ├── preview/        # Preview-related components
│   │       │   ├── shell/          # App shell components
│   │       │   └── practice/       # Practice components
│   │       ├── lib/
│   │       │   ├── types.ts        # Webview-side types (29240 lines)
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
│   │       │       └── copy.ts     # 8-language i18n (2953 lines)
│   │       └── styles.css          # 2822 lines — token-driven design system
│   ├── bundled/                    # Bundled Python sidecar (286 MB, 104 .py files)
│   ├── tests/                      # 55 Jest test files
│   ├── dist/                       # Build output
│   └── package.json                # Extension manifest (24 commands, 1 webview view)
├── server/                         # FastAPI Python sidecar
│   ├── app/                        # Application package
│   │   ├── __init__.py
│   │   ├── main.py                 # create_app() — FastAPI app factory with DI
│   │   ├── api/
│   │   │   ├── routers.py          # 23 endpoints (6027 lines)
│   │   │   ├── runtime.py          # TrainerRuntime — wires all services
│   │   │   └── routes/
│   │   │       ├── research.py     # Research sub-router
│   │   │       └── provider_profiles.py
│   │   ├── core/
│   │   │   ├── models.py           # Pydantic models (970 lines)
│   │   │   ├── config.py / settings.py
│   │   │   └── event_ledger.py
│   │   ├── db/
│   │   │   ├── repository.py       # TrainerRepository — main SQLite
│   │   │   ├── research_repository.py
│   │   │   ├── repositories.py     # Additional repositories
│   │   │   └── database.py         # DB setup
│   │   ├── llm/
│   │   │   ├── provider_service.py # ProviderService (2200 lines)
│   │   │   ├── agent_loop.py       # ReAct coach agent loop
│   │   │   ├── agent_binding.py    # Tool binding
│   │   │   ├── prompts.py          # System prompts (1666 lines)
│   │   │   └── tools.py            # Tool implementations
│   │   ├── pedagogy/
│   │   │   ├── service.py          # PedagogyService (2068 lines)
│   │   │   ├── implementation_coach.py
│   │   │   ├── project_idea_miner.py
│   │   │   ├── project_adaptation_coach.py
│   │   │   ├── project_source_scout.py
│   │   │   └── principle_explainer.py
│   │   ├── affect/service.py       # AffectService
│   │   ├── planner/service.py      # PlannerService (54347 lines)
│   │   ├── memory/
│   │   │   ├── service.py          # MemoryService (4468 lines)
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
│   ├── tests/                      # 59 pytest files (60k+ lines total)
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
├── docs/                           # Architecture, verification, plans, UI contract
│   ├── architecture.md
│   ├── verification.md
│   ├── developer-workflows.md
│   ├── ui-contract.md
│   ├── implementation-master-plan.md
│   ├── implementation-status.md / implementation-progress.md
│   ├── ux-enhancement-roadmap.md / ux-improvements-summary.md
│   ├── trainer-view-ux-master-plan.md
│   ├── workspace-first-artifact-layout.md
│   ├── plans/                      # Historical plan documents (three-view era)
│   ├── shared/                     # Shared reference docs
│   └── verification/               # Verification reference docs
├── scripts/                        # Dev helper scripts
│   ├── bootstrap.ps1               # Full dependency bootstrap
│   ├── dev.ps1                     # Build webview + extension
│   ├── check.ps1                   # Staged verification
│   └── smoke.ps1                   # Smoke test
└── e2e/                            # Playwright black-box test
    └── trainer.spec.js             # Single e2e spec
```

## SIDEBAR IA (SHIPPED)

Five fixed top-level views:

| View | ID | Chinese | Purpose |
|------|----|---------|---------|
| Coach | `coach` | 对话 | Conversation with the coach agent (messages, artifacts, composer) |
| Plan | `plan` | 计划 | Learning plan stages, current task, evidence governance |
| Resources | `resources` | 资料 | Uploaded materials, search (FTS5), preview (Tier A/B/C) |
| Training | `training` | 训练 | Active training card, flash cards, scenario lab, FSRS reviews |
| Settings | `settings` | 设置 | Provider config, coach defaults, language, workspace control |

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
| **Test backend** | `server/tests/` | pytest + FastAPI TestClient (59 files) |
| **Test frontend** | `extension/tests/` | Jest (55 files) |

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
| `App` | `extension/webview/src/app/App.tsx` (5843 lines) | Root workbench — handles all 5 view renders, state, messaging |
| `useWorkbenchState` | `extension/webview/src/app/useWorkbenchState.ts` | Zustand store — workbench data + actions |
| `CoachConversationView` | `extension/webview/src/components/coach/` | Coach message history + streaming |
| `CoachPlanView` | `extension/webview/src/components/plan/` | Plan stages, current task, evidence |
| `ResourcesWorkbenchView` | `extension/webview/src/components/resources/` | Resource list, upload, search, preview |
| `CoachTrainingView` | `extension/webview/src/components/training/` | Training cards, flash, scenario lab |
| `TrainingWorkbenchView` | `extension/webview/src/components/training/` | Training entry-point container |
| `CoachSettingsView` | `extension/webview/src/components/settings/` | Provider config, coach defaults, language |

### Sidecar (Python/FastAPI)

| Symbol | File | Role |
|--------|------|------|
| `create_app` | `server/app/main.py` | FastAPI app factory — DI wiring of all services |
| `TrainerRuntime` | `server/app/api/runtime.py` | Wires all services, manages sessions |
| `build_router` | `server/app/api/routers.py` (6027 lines) | All 23 HTTP endpoints |
| `ProviderService` | `server/app/llm/provider_service.py` (2200 lines) | OpenAI-compatible provider abstraction |
| `AgentLoop` | `server/app/llm/agent_loop.py` | ReAct tool-calling loop |
| `AgentBinding` | `server/app/llm/agent_binding.py` | Tool definition binding |
| `Prompts` | `server/app/llm/prompts.py` (1666 lines) | System prompts for coach modes |
| `Tools` | `server/app/llm/tools.py` | Tool implementations (read_file, diagnostics, search, etc.) |
| `MemoryService` | `server/app/memory/service.py` (4468 lines) | Profile, reflections, weaknesses, teaching assets |
| `ReviewScheduler` | `server/app/memory/review_scheduler.py` | FSRS-based spaced repetition scheduling |
| `SemanticMemory` | `server/app/memory/semantic.py` | Qdrant vector storage for semantic search |
| `PedagogyService` | `server/app/pedagogy/service.py` (2068 lines) | Teaching decision engine |
| `ImplementationCoach` | `server/app/pedagogy/implementation_coach.py` | Idea implementation guidance |
| `ProjectIdeaMiner` | `server/app/pedagogy/project_idea_miner.py` | Project idea mining from codebase |
| `ProjectAdaptationCoach` | `server/app/pedagogy/project_adaptation_coach.py` | Cross-project migration guidance |
| `PrincipleExplainer` | `server/app/pedagogy/principle_explainer.py` | Concept/principle explanation |
| `ProjectSourceScout` | `server/app/pedagogy/project_source_scout.py` | Reference repo suggestion |
| `AffectService` | `server/app/affect/service.py` | Learner affect detection + tone decisions |
| `PlannerService` | `server/app/planner/service.py` (54347 lines) | Learning plan generation |
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
- **State**: Zustand for webview, dataclass for Python domain models
- **API**: FastAPI with Pydantic models, snake_case payload with camelCase aliases
- **Messages**: webview→extension via `postMessage`, extension→webview via `HostMessage`
- **i18n**: 8 languages (zh-CN, en-US, es-ES, fr-FR, de-DE, ja-JP, ko-KR, pt-BR), keyed via `CopyKey`
- **Training**: FSRS-based spaced repetition (`py-fsrs`), dual definition in Python and TS

## UNIQUE PATTERNS
- `LearningPlan` dual-field sync (`id`/`plan_id`, `cadence`/`weekly_cadence`, `stages`/`phases`) — `server/app/core/models.py`
- Typed Parts Registry: 16+ message artifact kinds, rendered via `shared/src/partsRendererRegistry.ts`
- Coach agent loop: ReAct pattern with tool calling (`server/app/llm/agent_loop.py`)
- Training handoff state machine: card generation → routing → feedback → next card
- Research uses `dataclass(slots=True)`, core uses `BaseModel` (Pydantic) — intentional separation
- `WorkbenchSnapshot` is the universal response envelope across most API endpoints
- Apple ._ metadata files (`._*.py`, `._*.ts`) are byproducts of macOS copy tools — safe to ignore on Windows/Linux

## CROSS-PLATFORM GUIDE

本项目默认用 **Windows + PowerShell** 开发，但代码本身三平台通用。

### What is cross-platform

| 代码 | 平台 | 说明 |
|------|------|------|
| `extension/src/` (TS) | ✅ 三平台 | 纯 TypeScript，VS Code API 三平台一致 |
| `extension/webview/` (React) | ✅ 三平台 | Vite build 产物平台无关 |
| `shared/src/` (TS) | ✅ 三平台 | 纯类型定义 |
| `server/app/` (Python) | ✅ 三平台 | Python 3.12+ 跨平台 |
| `extension/bundled/` (Python source) | ✅ 三平台 | 104 个 `.py` 文件，平台无关 |
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
| `._*` 文件 | macOS AppleDouble 元数据 (Finder/rsync 创建) | ✅ `.gitignore` 未覆盖，建议添加 `._*` |
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
# Bootstrap
powershell -ExecutionPolicy Bypass -File scripts/bootstrap.ps1

# Build webview + extension
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1

# Start sidecar
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 -StartSidecar
# Manually:
server/.venv/Scripts/python.exe server/run_sidecar.py --host 127.0.0.1 --port 8765 --reload

# Verification
powershell -ExecutionPolicy Bypass -File scripts/check.ps1
powershell -ExecutionPolicy Bypass -File scripts/check.ps1 -Strict

# Smoke test
powershell -ExecutionPolicy Bypass -File scripts/smoke.ps1
powershell -ExecutionPolicy Bypass -File scripts/smoke.ps1 -Strict
scripts/smoke.ps1 -Port 8765  # Probe specific port

# TypeScript checks
npm run check --prefix extension/webview
npm run check --prefix extension

# Build all
npm run build

# Package VSIX
npm run package:vsix
npm run verify:delivery  # Build + tests + package

# Python tests
cd server && python -m pytest tests/ -v

# E2E
cd e2e && npx playwright test trainer.spec.js
```

## NOTES
- Sidecar port default: 8765, extension-managed range: 34891-34911
- Mock data in `extension/webview/src/lib/mockData.ts` for browser-only dev
- Browser preview: `extension/webview/src/lib/browserPreviewHarness.ts` — standalone Vite dev without VS Code
- Workspace data stored under VS Code global storage directory, not in repo
- Bundled sidecar: `extension/bundled/` (286 MB, 104 .py files) — for .vsix distribution
- Largest files: `routers.py` (6027 lines), `App.tsx` (5843 lines), `test_api.py` (219117 lines), `CoachResourcesView.tsx` (80814 lines)
- i18n covered: zh-CN, en-US, es-ES, fr-FR, de-DE, ja-JP, ko-KR, pt-BR
