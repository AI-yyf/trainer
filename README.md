# Trainer

Trainer is a desktop-first VS Code extension paired with a local Python FastAPI sidecar. It provides a conversation-driven learning coach inside VS Code for coding, debugging, writing, math, and resource-based study.

> Workbench layout: five fixed views, `Coach`, `Plan`, `Resources`, `Training`, and `Settings`.
> Coach loop: ReAct with tool calling for file access, diagnostics, search, and workspace authority.

---

## Platform Support / 跨平台支持

### Development entry points

Windows, macOS, and Linux use the same root-level Node lifecycle commands:

```bash
npm run bootstrap
npm run dev
npm run dev:sidecar -- --auto-port
npm run smoke
npm run smoke:strict
npm run test:server
npm run verify
```

`npm run test:server` resolves the local or system Python interpreter for the current host. The `scripts/*.ps1` files remain Windows conveniences rather than the cross-platform source-development entry point.

### Verification snapshot

| Area | Current status |
|------|----------------|
| Development | `npm run bootstrap`, `npm run dev`, `npm run smoke`, and `npm run test:server` are the shared source-development entry points. |
| CI | `.github/workflows/cross-platform-verify.yml` declares Linux x64/ARM64, macOS Apple Silicon/Intel, and Windows jobs. This repository still has no recorded cloud CI run, so the workflow is configuration rather than execution evidence. |
| Windows release | Packaging and bundled-sidecar validation have been completed on the Windows host. |
| Linux release | A native Linux binary and installed-VSIX evidence are still required. |
| macOS release | A target-matching Darwin manifest and installed-VSIX evidence are still required. |

The bundled Python source is portable, but native bundled assets are target-specific. An installed extension only runs a bundled binary with a valid manifest for its own `platform-arch`; otherwise Trainer stays unavailable and asks for the matching VSIX. A package should not be described as verified across all three desktop platforms unless the corresponding release artifacts and install checks exist.

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
└── e2e/                      # Playwright integration test
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

### 2. Build and run

```bash
npm run dev
```

This builds:
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

### 4. Start the sidecar manually

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

The output is target-qualified, for example `extension/trainer-extension-0.1.0-win32-x64.vsix`. Install only a VSIX that matches the machine that will run the extension:

| Machine | VSIX suffix |
|---------|-------------|
| Windows x64 | `win32-x64` |
| macOS on Apple Silicon | `darwin-arm64` |
| macOS on Intel | `darwin-x64` |
| Linux x64 | `linux-x64` |
| Linux ARM64 | `linux-arm64` |

Release artifacts are built natively; a VSIX is not interchangeable across these targets because it contains a platform-specific sidecar binary. Install the matching file via `Extensions: Install from VSIX...` in VS Code.

macOS artifacts are built and installation-tested on native macOS 15 runners,
so the supported release baseline is **macOS 15 or newer**. Older macOS
versions need an artifact built and tested on that older OS; freezing a Python
sidecar on a newer macOS version is not a sound compatibility guarantee.

Linux assets use the Ubuntu 22.04 glibc baseline (glibc 2.35 or newer). Alpine
and other musl-based distributions need a future musl-specific release; do not
install a glibc VSIX there expecting the bundled sidecar to start.

On macOS, if Gatekeeper reports a quarantine issue after installation, open **Settings → Runtime self-check** and use its copyable, sidecar-scoped repair command only after verifying the downloaded release asset.

## Workbench Layout

| View | Chinese | Purpose |
|------|---------|---------|
| **Coach** | 对话 | Conversation with the coach agent — messages, artifacts, suggested actions |
| **Plan** | 计划 | Learning plan stages, current task, evidence governance |
| **Resources** | 资料 | Uploaded materials (PDF, images, text, URL), FTS5 search, tiered preview |
| **Training** | 训练 | Active training card, flash cards, scenario lab, FSRS spaced reviews |
| **Settings** | 设置 | Provider config, coach defaults, language, workspace context controls |

### Startup states

- **No provider saved**: Webview shows a clear blocked state
- **Provider saved but no API key**: Sending is blocked with a settings hint
- **Sidecar cannot start**: Sidebar still renders and surfaces the failure state

### After installation

1. Open the `Trainer` activity bar icon
2. Go to **Settings** (设置)
3. Save `provider`, `base URL`, `model`, `API key`
4. Return to **Coach** (对话) and start coaching

## Sidecar Runtime

The installed extension runs only its verified bundled sidecar binary. If that runtime is missing or does not match the current platform, Trainer stays unavailable and asks for the matching VSIX. Source and local Python launch options are available only while developing the extension.

Sidecar data is stored under the VS Code global storage directory — not in the repo.

## Core Principles

- **Desktop-first** five-view workbench
- **Fixed top-level navigation**: Coach / Plan / Resources / Training / Settings
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
| Blank webview | `Trainer` output channel — webview startup errors are reported there |
| Provider saved but can't send | API key missing, invalid, or model unsupported by endpoint |
| Sidecar unavailable | Run `npm run package:vsix` to refresh bundled server; check `Trainer` output channel |
| TypeScript errors | `npm run check --prefix extension/webview` + `npm run check --prefix extension` |
| Python test failures | `cd server && python -m pytest tests/path/to/test.py -v` |

## Project Status (项目状态)

The table below captures the current direction of travel for Trainer. It is intentionally candid about what is already in place and what still needs verification or follow-through.

| Area | Target state | Current status |
|------|--------------|----------------|
| Cross-platform development | macOS, Windows, and Linux use the same Node lifecycle entry points | `npm run bootstrap`, `npm run dev`, `npm run smoke`, and `npm run test:server` are shared source-development entry points. Native CI paths exist for Linux x64/ARM64, macOS Apple Silicon/Intel, and Windows, but execution evidence still needs to be collected. |
| Zero-friction install | Install a VSIX, configure a provider, and start using Trainer | VSIX packages are target-specific. Installation evidence still needs to be gathered separately for Linux x64/ARM64, macOS Apple Silicon/Intel, and Windows. |
| Clear blocked states | No provider, no key, and sidecar offline states are all explicit | Implemented. |
| Coach loop closure | Coach → Plan → Resources → Training → feedback → Plan | Training handoff is not fully closed yet. |
| Training prompts | The first screen answers: what card, why now, what to deliver, how to verify, and where results go | Designed and still being validated. |
| Code health | TS strict, Ruff, Pyright, pytest, Jest, and E2E stay green, with oversized files split down over time | Large files still exist, including `server/tests/test_api.py`, `extension/webview/src/app/App.tsx`, and `server/app/api/routers.py`. |
| Cross-language contract | Python Pydantic and TypeScript interfaces stay aligned for `WorkbenchSnapshot` | No automated contract check is in place yet. |
| CI validation | GitHub Actions validates Linux, macOS, and Windows on every PR | The matrix is defined, but the repository does not yet contain recorded cloud execution evidence. |
