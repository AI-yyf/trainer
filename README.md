# Trainer

**A long-term coding coach that lives in your VS Code sidebar — it plans, drills, verifies, and remembers, but never writes code for you.**

[中文文档](README_ZH.md)

---

## Background

Most developers don't stall because they lack tutorials. They stall because nothing closes the loop: chats with an LLM evaporate, videos get watched passively, and the one concept you almost understood on Tuesday is gone by Friday.

Trainer attacks that problem from inside the editor. It is not a chat wrapper. It is a coach with a memory, a curriculum, and an exam policy:

- it **plans** your learning in stages and tracks where you actually are,
- it **drills** you with flash cards, theory questions, and scenario labs,
- it **verifies** mastery against your real code — passing a chat about FastAPI counts for nothing until the current file proves it,
- it **remembers** across sessions, projects, and weeks, and schedules reviews with FSRS,
- and it **never writes production code for you**. You write; it coaches.

## What it is

A VS Code extension (sidebar workbench, five fixed views) paired with a local FastAPI sidecar. Your API key stays in VS Code SecretStorage; the sidecar runs on `127.0.0.1`; your workspace is governed by a six-level permission model (read-only by default, writes gated behind verification).

Works with any OpenAI-compatible provider — official APIs and relays alike. Paste your provider's connection JSON and Trainer parses the URL and key for you.

### The five views

| View | What it owns |
|------|--------------|
| **Coach** | Streaming conversation with tool access (read files, diagnostics, workspace search), `$`-triggered skill palette, attachments, answer modes (`direct` gives answers; `coach-first` makes you think first) |
| **Plan** | Stage-based curriculum generated from your goal, progress dashboard, plan freeze/unfreeze, material generation per stage |
| **Resources** | Your library: markdown/PDF/DOCX/CSV/notebook/media upload, full-text search, tiered sandbox preview, trash |
| **Training** | FSRS-scheduled flash cards, theory drills with acceptance criteria, scenario labs, verification-gated card advancement, review queue with snooze/done |
| **Settings** | Provider profiles (paste-and-go), model switching, endpoint speed test, thinking controls, teaching style, memory scopes, workspace admission |

### Highlights

**Three-step provider setup.** Paste your relay's connection JSON (the `{"_type":"newapi_channel_conn","key":"…","url":"…"}` blob that Chinese relay services hand you) — Trainer splits URL and key automatically, fetches the live model list, picks a sensible default model, and verifies the connection in the same pass. Wrong key? You get `invalid_key_or_permission`, not a vague spinner.

**Endpoint speed test.** Race multiple provider endpoints in parallel (warm-up request, then timed). Green under 500 ms, yellow under 1 s. Click a row to adopt it.

**Verification-gated mastery.** The fastest way to fake learning is to mark everything done. Trainer refuses: advancing a training card to *implemented* requires current-file verification against acceptance criteria. Manual "mark done" is intentionally blocked.

**Honest failure.** Wrong key reads `invalid_key_or_permission`. Unreachable host reads `network`. A reply the model garbled is never shown as an answer — Trainer tells you it was unreadable and asks you to resend. Unknown gateways are never silently assumed OpenAI-compatible.

**Thinking controls, per protocol.** Reasoning effort for OpenAI-style providers, budget for Anthropic, on/off for MiniMax-class providers that reject effort levels — selected in the UI, mapped into request defaults per provider.

**Long-horizon state.** Plans freeze and unfreeze. Sessions survive restarts. Card progress persists in SQLite. Reviews come due on an FSRS schedule, not a to-do list.

## Install

**From VSIX** (prebuilt, macOS ARM64): grab `extension/trainer-extension-0.1.0-darwin-arm64.vsix` from this repository's build, then in VS Code: Extensions panel → `···` → *Install from VSIX…*

**From source:**

```bash
git clone https://github.com/AI-yyf/trainer.git
cd trainer
npm install                 # installs the extension + webview workspaces
cd server && python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cd .. && npm run build      # compiles shared + extension + webview
```

Then open the repo in VS Code and press F5 (Extension Development Host), or install the packaged VSIX.

**Provider setup (first run):** open the Trainer sidebar → Settings → paste your relay connection info or service address → paste your API key → **Save & connect**. Trainer fetches the live model list, picks a default, and verifies the streaming path. That's the whole setup.

## Quality gates

This repository treats its own verification as a product:

| Gate | Count |
|------|-------|
| Extension tests (node --test) | 1,550 |
| Server tests (pytest) | 2,825 |
| Real-VSCode end-to-end | 33 steps, live provider |
| Experience matrix (Playwright) | 200 scenarios |
| Static analysis | ruff + pyright + tsc, zero findings |

The end-to-end suite runs against a live provider in a real VS Code instance: it activates the packaged extension, starts the bundled sidecar, saves a provider, streams a coaching turn, generates and verifies training cards, and asserts what the webview actually shows.

## Architecture

```
VS Code window
└── Trainer sidebar (React 19 + Zustand, 8 languages)
    └── postMessage bridge ── CommandRegistry ── 30+ commands
                                     │
                     FastAPI sidecar (127.0.0.1, PyInstaller-bundled)
                     ├── ReAct agent loop (read/diagnostics/search tools)
                     ├── Planner · Pedagogy · FSRS scheduler
                     ├── Memory (SQLite + Qdrant semantic)
                     └── Resources (FTS + tiered sandbox preview)
```

- `shared/` — protocol types used by both sides (single source of truth)
- `extension/` — host: commands, workspace trust/admission, secret storage, sidecar lifecycle
- `server/` — the coach brain: agent loop, planner, pedagogy, FSRS, memory, resources
- `extension/bundled/` — the sidecar packaged for VSIX distribution (PyInstaller)

## Documentation

- [SPEC.md](SPEC.md) — the original product specification (Chinese)
- [AGENTS.md](AGENTS.md) — repository layout and conventions for agents
- 中文完整文档见 [README_ZH.md](README_ZH.md)

## License

[MIT](LICENSE)
