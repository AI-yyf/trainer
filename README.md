# Trainer

Trainer is a **desktop-first VS Code extension** paired with a **local Python FastAPI sidecar**. It acts as a conversation-driven learning coach inside VS Code for code, remote/debug/function guidance, math, writing, and resource-based study — not just a code-generation assistant.

> **Current sidebar IA**: Five-view workbench: `Coach / Plan / Resources / Training / Settings`.
> **Coach agent**: ReAct loop with tool calling (read file, diagnostics, search, workspace authority).

---

## Cross-Platform Compatibility (跨系统兼容)

### Source development

Windows, macOS, and Linux source development use the same root Node lifecycle
commands. Do not manually translate the PowerShell helpers for normal work:

```bash
npm run bootstrap
npm run dev
npm run dev:sidecar -- --auto-port
npm run smoke
npm run smoke:strict
npm run test:server
npm run verify
```

`npm run test:server` resolves the local or system Python interpreter for the
current host. The `scripts/*.ps1` files remain supported Windows conveniences,
not the cross-platform source-development entry point.

### Evidence boundaries

| Scope | Current evidence |
|-------|------------------|
| Source development | The Node lifecycle and `npm run test:server` are the Windows/macOS/Linux development entry points. |
| CI | `.github/workflows/cross-platform-verify.yml` declares Ubuntu, macOS, and Windows jobs, but this repository has no recorded cloud CI run; the workflow is configuration, not execution evidence. |
| VSIX on the Windows host | Packaging and bundled-sidecar validation have been completed on the Windows host. |
| VSIX for Linux targets | A native Linux binary and installed-VSIX evidence are required; a missing binary remains an explicit coverage gap. |
| VSIX for macOS targets | A target-matching Darwin manifest and installed-VSIX evidence are required; an unverified binary leaves Trainer unavailable until the matching VSIX is installed. |

The bundled Python source is portable, but native bundled assets are target
specific. An installed extension only runs a bundled binary with a valid
manifest for its own `platform-arch`; otherwise Trainer stays unavailable and
asks for the matching VSIX. The current VSIX must not be presented as a
verified three-platform package.

---

## Repository Layout

```
trainer_final/
├── extension/                # VS Code extension host (TypeScript)
│   ├── src/                  # Extension commands, core services, webview bridge
│   ├── webview/              # React workbench UI (Vite + Zustand + i18n)
│   ├── bundled/              # Bundled Python sidecar (for .vsix distribution)
│   ├── tests/                # 55 Jest test files
│   └── package.json          # Extension manifest & commands
├── server/                   # FastAPI Python sidecar
│   ├── app/                  # Core modules (api, core, db, llm, pedagogy, memory, etc.)
│   └── tests/                # 59 pytest files
├── shared/                   # Shared TypeScript types, protocol, commands, tokens
│   └── src/
├── docs/                     # Architecture, verification, plans, UI contract
├── scripts/                  # Node lifecycle plus Windows PowerShell convenience helpers
├── e2e/                      # Playwright integration test
└── .claude/                  # Claude Code project config
```

## Portable Lifecycle

Use these Node lifecycle commands on Windows, macOS, and Linux. They select the
appropriate `server/.venv` interpreter and are the normal source-development
entry points.

```bash
npm run bootstrap
npm run dev
npm run dev:sidecar -- --auto-port
npm run smoke
npm run smoke:strict
npm run test:server
```

The PowerShell scripts remain Windows-only conveniences. The CI matrix declares
the portable lifecycle for Ubuntu, macOS, and Windows, but no cloud execution
result is recorded in this repository.

## Quick Start

### Prerequisites
- Node.js 24+
- Python 3.12+

### 1. Bootstrap all dependencies

```bash
npm run bootstrap
```

This installs:
- `extension/` npm dependencies
- `extension/webview/` npm dependencies
- Python virtual environment at `server/.venv` with all packages

Use `npm run bootstrap -- --use-uv` to request `uv` instead of pip.

### 2. Build

```bash
npm run dev
```

Builds:
1. Webview (Vite) — `extension/webview/dist/`
2. Extension host (tsc) — `extension/dist/`

Run `npm run dev:sidecar -- --auto-port` to also start the FastAPI sidecar.

### 3. Verify

```bash
npm run verify
npm run smoke
npm run smoke:strict
npm run test:server

# Provider-dependent smoke entrypoints
npm run smoke:provider
npm run smoke:trainer-turn
```

### 4. Start sidecar manually (alternative)

```bash
# Windows
server/.venv/Scripts/python.exe server/run_sidecar.py --host 127.0.0.1 --port 8765 --reload

# macOS / Linux
server/.venv/bin/python server/run_sidecar.py --host 127.0.0.1 --port 8765 --reload
```

### 5. Launch in VS Code

Open the `extension/` folder as the VS Code workspace, then press `F5` (Run Extension).

### 6. Package as installable VSIX

```bash
npm run package:vsix
```

Output: `extension/trainer-extension-0.1.0.vsix` (120 MB).

Install via `Extensions: Install from VSIX...` in VS Code.

## Five-View Sidebar IA

| View | Chinese | Purpose |
|------|---------|---------|
| **Coach** | 对话 | Conversation with the coach agent — messages, artifacts, suggested actions |
| **Plan** | 计划 | Learning plan stages, current task, evidence governance |
| **Resources** | 资料 | Uploaded materials (PDF, images, text, URL), FTS5 search, tiered preview |
| **Training** | 训练 | Active training card, flash cards, scenario lab, FSRS spaced reviews |
| **Settings** | 设置 | Provider config, coach defaults, language, workspace context controls |

### First-launch expectations

- **No provider saved**: Webview shows a truthful blocked state (not a black screen)
- **Provider saved but no API key**: Sending is blocked with a settings hint
- **Sidecar cannot start**: Sidebar still renders and surfaces the failure state

### After installing the VSIX

1. Open the `Trainer` activity bar icon
2. Go to **Settings** (设置)
3. Save `provider`, `base URL`, `model`, `API key`
4. Return to **Coach** (对话) and start coaching

## Sidecar Runtime

The installed extension runs only its verified bundled sidecar binary. If that
runtime is missing or does not match the current platform, Trainer stays
unavailable and asks for the matching VSIX. Source and local Python launch
candidates are available only while developing the extension.

Sidecar data is stored under the VS Code global storage directory — not in the repo.

## Core Principles

- **Desktop-first** five-view workbench
- **Fixed top-level IA**: Coach / Plan / Resources / Training / Settings
- **Keyboard-first** flows with visible focus states
- **Shared design tokens** across webview and native VS Code surfaces
- **OpenAI-compatible** provider config with explicit capability flags
- **Layered memory**: SecretStorage → preferences → workspace state → SQLite → semantic index → session summary
- **Coach agent** with ReAct tool-calling loop (read file, diagnostics, search, authority)
- **FSRS spaced repetition** for training review scheduling
- **Spec-driven evaluation** pipeline (static, dynamic, semantic checks)

## Key Commands

```bash
# Portable source development (Windows / macOS / Linux)
npm run bootstrap                          # Install JavaScript + Python dependencies
npm run dev                                # Build webview + extension
npm run dev:sidecar -- --auto-port         # Build + start server
npm run smoke                              # Readiness probe
npm run smoke:strict                       # Strict readiness probe
npm run test:server                        # Server pytest suite
npm run verify                             # Portable full verification

# Build and delivery
npm run build                              # Build webview + extension
npm run check                              # TypeScript typecheck only
npm test                                   # Extension + server tests
npm run package:vsix                       # Package VSIX
npm run verify:delivery                    # Build + tests + package

# Windows PowerShell conveniences
powershell -ExecutionPolicy Bypass -File scripts/bootstrap.ps1
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 -StartSidecar
powershell -ExecutionPolicy Bypass -File scripts/check.ps1 -Strict
powershell -ExecutionPolicy Bypass -File scripts/smoke.ps1 -Strict
```

## Troubleshooting

| Symptom | Check |
|---------|-------|
| Black screen | `Trainer` output channel — webview startup errors reported there |
| Provider saved but can't send | API key missing, invalid, or model unsupported by endpoint |
| Sidecar unavailable | Run `npm run package:vsix` to refresh bundled server; check `Trainer` output channel |
| TypeScript errors | `npm run check --prefix extension/webview` + `npm run check --prefix extension` |
| Python test failures | `cd server && python -m pytest tests/path/to/test.py -v` |

## Project Ideal State (项目理想状态)

Trainer 的最终形态应该满足以下条件。当前状态与理想状态的差距即项目的迭代方向：

| 维度 | 理想状态 | 当前状态 |
|------|----------|---------|
| **跨平台开发** | macOS / Windows / Linux 使用同一 Node lifecycle 入口 | ⚠️ `npm run bootstrap`、`dev`、`smoke` 与 `test:server` 已是源码开发入口；各目标平台的执行证据仍需持续采集 |
| **零配置安装** | 安装 VSIX → 配 provider → 直接使用 | ⚠️ 仅本机目标的 VSIX manifest 可验证；Linux、Darwin 与其他 target 的安装证据仍必须分别收集 |
| **诚实阻塞状态** | 无 provider / 无 key / sidecar 离线各显示明确状态 | ✅ 已实现 blocked state |
| **教练闭环** | Coach → Plan → Resources → Training → feedback → Plan | ⚠️ Training handoff 未完全闭环 |
| **训练五问** | 首屏回答：当前卡片？为什么现在？交付什么？怎么验证？结果去哪？ | ✅ 已设计，需持续验证 |
| **工程质量** | TS strict / Ruff / Pyright / pytest / Jest / E2E 全绿，monster 文件已拆分 | ❌ `test_api.py` 219k 行、`App.tsx` 5843 行、`routers.py` 6027 行 |
| **跨语言契约** | Python Pydantic ↔ TypeScript interface 自动校验 WorkbenchSnapshot 一致性 | ❌ 无自动校验 |
| **CI 持续验证** | GitHub Actions matrix (ubuntu + macos + windows) 每次 PR 全平台验证 | ⚠️ matrix workflow 已静态定义，但仓库内无云端运行记录 |
