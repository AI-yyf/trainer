# Trainer Architecture

Trainer runs as **two local processes**:

1. **VS Code extension host** — owns commands, storage, views, Testing API, and webview orchestration
2. **FastAPI sidecar** — owns provider calls, planning, memory, pedagogy, resource ingestion, evaluation, training, research

## Repository Layout

```
trainer_final/
├── extension/                    # VS Code extension host source, manifest, commands, views, build
│   ├── src/
│   │   ├── commands/             # 25+ command handlers organized by domain
│   │   ├── core/                 # WebviewBridge, SidecarHttpClient, SidecarProcessManager, types
│   │   ├── provider/             # ProviderConfigStore (SecretStorage-backed)
│   │   ├── testing/              # VS Code Testing API integration
│   │   └── views/                # Native VS Code tree views
│   ├── webview/                  # React workbench (Vite + Zustand + Zod + i18n)
│   │   └── src/
│   │       ├── app/              # App.tsx (root), useWorkbenchState (Zustand store)
│   │       ├── components/       # View components for all 5 views
│   │       ├── lib/              # Types, mockData, i18n (8 languages), theme
│   │       └── types/            # Additional type definitions
│   ├── bundled/                  # Bundled Python sidecar for distribution (286 MB)
│   └── tests/                    # 55 Jest test files
├── server/                       # FastAPI sidecar source & tests
│   ├── app/                      # Application package
│   │   ├── api/                  # HTTP layer: routers.py (23 endpoints) + routes/
│   │   ├── core/                 # Pydantic models, config, event ledger
│   │   ├── db/                   # SQLite repository layer
│   │   ├── llm/                  # Provider abstraction, agent loop, tools, prompts
│   │   ├── affect/               # Learner affect detection & tone
│   │   ├── pedagogy/             # Teaching decision + 5 sub-coaches
│   │   ├── planner/              # Learning plan generation
│   │   ├── memory/               # Memory, review scheduler, semantic (Qdrant)
│   │   ├── evaluator/            # Static/dynamic/semantic evaluation
│   │   ├── research/             # Multi-theme research orchestration
│   │   ├── training/             # Card generator, router, FSRS scheduler, handoff
│   │   ├── workspace/            # Workspace authority & classifier
│   │   ├── resources/            # Resource lifecycle & search
│   │   ├── ingest/               # File parsing
│   │   └── specs/                # Spec-driven pipeline
│   └── tests/                    # 59 pytest files
├── shared/                       # Shared TypeScript protocol, models, commands, tokens
│   └── src/                      # models.ts, protocol.ts, commands.ts, tokens.ts, etc.
├── scripts/                      # bootstrap.ps1, dev.ps1, check.ps1, smoke.ps1
├── docs/                         # Architecture, verification, plans
└── e2e/                          # Playwright integration test
```

## Model Routing

Trainer's provider model is configured in the Settings view. The extension-side default model is `gpt-4.1-mini` (set in `extension/src/provider/providerConfigStore.ts` and `extension/package.json`). The coach agent loop forwards all LLM calls to the sidecar's `ProviderService`, which supports OpenAI-compatible endpoints.

The Codex delegation tier table lives in `docs/shared/agent-tiers.md`.

## Runtime Flow

```
1. Extension boots
   ├── Validates workspace trust (WorkspaceTrustGuard)
   ├── Loads provider preferences from VS Code settings
   ├── Loads API key from SecretStorage
   ├── Ensures sidecar is reachable (starts if needed, SidecarProcessManager)
   └── Opens webview, sends bootstrap data (HostMessage → webview)

2. Webview renders (App.tsx)
   ├── Choose view: Coach / Plan / Resources / Training / Settings
   ├── User types → CoachComposer → postMessage to extension
   └── Extension → HTTP POST to sidecar (`/session/message` for Coach/default turns, `/turn` for non-Coach intents) → response → HostMessage → webview update

3. Sidecar processes request
   ├── router.py handler → TrainerRuntime method
   ├── Memory snapshot → PedagogyService (teaching decision)
   ├── AffectService (tone decision)
   ├── PlannerService (plan generation)
   ├── ProviderService (LLM call with tool execution via AgentLoop)
   ├── Response wrapped in WorkbenchSnapshot
   └── Persist to SQLite + Qdrant semantic index

4. Response flows back
   ├── Extension adapts snapshot → update webview + tree views + Test Explorer
   └── Webview re-renders with new state
```

## Data Ownership

| Store | What it holds | Backend |
|-------|--------------|---------|
| `SecretStorage` | Provider API keys | VS Code |
| `globalState` | User profile, UX preferences | VS Code |
| `workspaceState` | Current plan, active task, resource bindings | VS Code |
| `SQLite` | Structured learning records (profile, sessions, plans, reviews) | Sidecar |
| `Qdrant local` | Semantic resource & reflection embeddings | Sidecar |

## UI Contract

The UI is driven by `WorkbenchSnapshot` (defined in `shared/src/protocol.ts`) and the extension host view models. The extension adapts sidecar API responses into this shape for the webview to render.

### Five-View Sidebar Contract

- **Fixed top-level views**: Coach / Plan / Resources / Training / Settings
- **Contained flows**: First Look, training submodes, restore surfaces, debug tooling — NOT extra top-level navigation
- **New capabilities**: Must first fit one of the five existing views before a new IA surface is considered

### Integration Rules

| Layer | Owns |
|-------|------|
| Extension host | VS Code APIs, process control, provider config |
| Webview | Visual rendering, ephemeral interaction state |
| Sidecar | Business logic, durable learning state |
| Shared types | Cross-process contracts |

### HTTP Transport

Extension-to-sidecar uses compatibility payload adapters (snake_case FastAPI ↔ camelCase TS). `WorkbenchSnapshot` is the primary response envelope for most endpoints. `shared/src/protocol.ts` documents the intended stable contract surface.

Coach conversation transport contract:
- Default Coach turns use `/session/message` so the sidecar can run the agent loop and return structured `metadata.parts` on assistant messages.
- Non-Coach structured intents such as `review`, `plan`, and `task` may continue to use `/turn`.
- Streaming target contract is `/session/message/stream` for Coach/default turns and `/turn/stream` for non-Coach structured intents.
- Current implementation:
  - desktop extension non-stream and stream sends split by intent in `extension/src/commands/sessionCommands.ts`
  - browser preview sync and stream sends split by intent in `extension/webview/src/lib/browserSidecar.ts`
  - Coach/default streams use `/session/message/stream`; structured Plan, Resources, and Training streams use `/turn/stream`, with focused route tests covering both paths
- Tool calls/results are conversation-attached data, not a separate top-level view. The webview should render them as lightweight message parts inside Coach.

Current Coach message truth path:
- sidecar assistant metadata builds `parts` in `server/app/api/routers.py`
- shared normalization lives in `shared/src/protocol.ts`
- extension state mapping lives in `extension/src/core/workbenchData.ts`
- browser preview mapping lives in `extension/webview/src/lib/browserSidecar.ts`
- Coach UI rendering currently lands in `extension/webview/src/components/coach/CoachMessageParts.tsx` via `CoachMessageBubble.tsx`

## Key Dependencies

### Sidecar (Python)
- **FastAPI** + **Uvicorn** — HTTP server
- **Pydantic** + **Pydantic-Settings** — schema & config
- **OpenAI SDK** — LLM provider calls
- **httpx** — HTTP client for provider requests
- **PyMuPDF** — PDF parsing
- **qdrant-client** — vector search
- **py-fsrs** — spaced repetition scheduling

### Webview (TypeScript)
- **React 18** — UI framework
- **Zustand** — state management
- **Vite** — bundler & HMR
- **KaTeX** — math rendering
- **Mermaid** — diagram rendering
- **react-markdown** + **rehype-katex** — rich content

### Extension Host (TypeScript)
- **VS Code API** (v1.96+)
- **TypeScript** (strict mode)

---

## Cross-Platform Architecture (跨平台架构)

Trainer 的公共扩展代码可跨平台运行，但安装版 sidecar 是原生二进制。因此发布方式是“同一份功能代码 + 每个系统和架构各一份 VSIX”，而不是一个安装包通用所有系统。

| 组件 | 跨平台策略 |
|------|-----------|
| **VS Code 扩展 (TS)** | VS Code Extension Host API 在 Windows、macOS、Linux 上一致。`npm run build` 与 `npm run check` 可在三端运行。 |
| **Webview (React)** | Vite 构建产物与操作系统无关。 |
| **Sidecar 源码** | `server/` 与 `extension/bundled/server/` 保持跨平台源码一致，用于构建和发布校验。 |
| **安装版 sidecar** | 已安装的 VSIX 只启动 `bundled/bin/<platform>-<arch>/` 中与当前 Extension Host 匹配、且带有有效 manifest 的原生 sidecar；缺失或不匹配时会提示安装对应 VSIX，不会改用电脑上的 Python。 |
| **VSIX 打包** | `npm run package:vsix` 为当前构建机生成带 target 的安装包，例如 `trainer-extension-0.1.0-win32-x64.vsix`。原生 sidecar 不能跨系统伪装或重标；必须在目标系统和架构上构建。 |
| **脚本与数据** | `scripts/*.ps1` 是 Windows 辅助脚本；交付 CI 使用 Node/npm 路径。SQLite、Qdrant 与 sidecar 数据写入 VS Code global storage，由扩展宿主提供本机路径。 |

### 发布覆盖与已知缺口

- GitHub Actions 在 Windows、macOS、Linux runner 上构建 target-specific VSIX，并验证 bundled sidecar 能在 loopback `/health` 启动。
- 每个产物还会检查 VSIX target、原生二进制和 manifest 是否一致；有可用 VS Code CLI 的 runner 会额外安装 VSIX 后再检查其中的 sidecar。
- 完整的已安装 VSIX host E2E 仍是显式触发的发布门槛：当 runner 没有 VS Code CLI 或图形环境时，工作流会记录未完成，而不会把它当作通过。
- 打包代码可识别 Windows ARM64 和 Linux ARM64，但当前没有这两个架构的专用 CI 构建、安装验证和发布产物证据。发布前不得把它们标为已交付；需要在对应原生 runner 上完成构建与验证。

---

## Sidebar IA Evolution

| Phase | Views | Status |
|-------|-------|--------|
| Original three-view | Coach / Plan / Settings | Historical (plans in `docs/plans/`) |
| Current five-view | Coach / Plan / Resources / Training / Settings | **Shipping** |
