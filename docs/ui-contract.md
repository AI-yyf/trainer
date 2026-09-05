# Trainer UI Contract

This file is the shipping UI/source-of-truth contract for Trainer. Use it before older plans or ideal-state essays.

Priority when docs disagree:
- `docs/ui-contract.md` for shipped IA and view ownership
- `docs/architecture.md` and `docs/developer-workflows.md` for current transport/runtime behavior
- `docs/trainer-ideal/` for ideal-state product direction
- `docs/plans/` for historical planning context only

Trainer follows the UI baseline documents: `ui设计基准.md` and `ui设计基准.pdf` (repo root).

## Required UI Characteristics

- Narrow-sidebar workbench with exactly **five top-level views**: Coach / Plan / Resources / Training / Settings
- Keyboard-first navigation with visible focus rings
- Low-decoration neutral surfaces
- One high-contrast accent color
- Collapsible sidebars with remembered width
- Command-oriented entry points over deep menus
- WCAG-aware contrast throughout

## Five-View IA Contract

### Immutable rules

1. Trainer has exactly **five fixed top-level views**: `Coach`, `Plan`, `Resources`, `Training`, `Settings`
2. `First Look`, training submodes, restore surfaces, and debug tooling are **contained flows** — not extra top-level navigation
3. Any new capability must first fit one of the five existing views before a new IA surface is considered

### What each view must provide

#### Coach (对话)
- Conversation message history (user + assistant + system roles)
- Route contract: Coach/default turns use `/session/message`; non-Coach structured intents may use `/turn`
- Streaming contract target: Coach/default turns use SSE via `/session/message/stream`; non-Coach structured intents should use `/turn/stream`
- Current implementation: browser preview and desktop extension both split streaming by intent. Coach/default turns use `/session/message/stream`; structured Plan, Resources, and Training turns use `/turn/stream`.
- Typed artifact blocks: task, plan, evaluation, idea_implementation, project_idea, principle, review, etc.
- Typed message parts attach lightly to the conversation truth: tool calls/results, reasoning summaries, plan updates, test results, file previews, and training cards should render inside the message flow rather than as a separate job console
- Current message-parts truth path: sidecar `metadata.parts` -> `shared/src/protocol.ts` normalization -> extension/webview mapping -> `CoachMessageParts.tsx` inside `CoachMessageBubble.tsx`
- Slash / skill command deck: `shared/src/skillCatalog.ts` drives context-aware quick actions, so Coach stays the super-entry for commands rather than splitting into a separate top-level surface
- Suggested action pills (context-sensitive command suggestions)
- Composer with context indicators (current file, diagnostics, selection)
- Agent activity strip (animations during agent loop execution)

#### Plan (计划)
- Learning plan stages with status (pending / active / completed)
- Current stage details: goal, outcomes, why now, verify method
- Next step and blocked reason display
- Evidence governance controls (submit learning signal, track progress)
- Review queue summary and due reviews list
- Plan freeze/unfreeze controls

#### Resources (资料)
- Resource list with upload and index controls
- Support for: PDF, image, markdown, text, code, URL
- Search via SQLite FTS5
- Preview contract:
  - Tier A: the sidebar gives a bounded indexed decision aid: source chain, indexing, trust, freshness, and any available summary or preview metadata. It does not render a full document or media body.
  - Tier B: converted or indexed material may supply a bounded summary and preview tier/kind metadata for search and reuse. Conversion is not a Trainer-owned reader.
  - Tier C: **Open in VS Code** is the canonical full-content preview. Managed local and sandboxed resources open through VS Code's native editors; a remote link opens externally only when no managed local copy is available.
- Resources remains a governed knowledge library and guarded sandbox, not a general file manager or an embedded document/media reader.
- Knowledge fragments display

#### Training (训练)
- Active training card — **single-card-first** (not a dashboard)
- Five questions answered on first viewport without reading chat history:
  1. What is the current card?
  2. Why now?
  3. What should the learner deliver?
  4. How should it be verified?
  5. Where should the result return?
- Flash cards (spaced repetition)
- Scenario lab
- Theory drills
- Review queue (FSRS-based)
- Motivation/tip panels

#### Settings (设置)
- Provider configuration: name, base URL, model, API key
- Provider protocol selection (OpenAI Chat, OpenAI Responses, Anthropic, Gemini)
- Provider test connection button
- Model list refresh with capability matrix display
- Coach defaults: language (8 supported), teaching style, answer policy
- Memory scope: project / personal / session
- Review cadence: light / steady / active
- Workspace context controls: follow current file, include diagnostics, include selection
- Clear config / open config file

## Training Contract

- Shipped `Training` is **single-card-first**, not a backend dashboard
- The first viewport must answer the five questions without reading chat history (the authoritative source is backend memory/snapshot training state, not chat messages)
- Plan summaries, evaluation copy, and coach narration are **fallback context** only when governed training state is absent
- `review_artifact`, `scenario_lab`, `theory_drill`, and due reviews may surface as secondary carry-over items, but must not compete with the current card

## Shared Tokens

The canonical token source is `shared/src/tokens.ts`:

| Token family | Tokens | Purpose |
|-------------|--------|---------|
| **Background** | `bg0`, `bg1`, `bg2`, `bg3` | Surface hierarchy |
| **Foreground** | `fg0`, `fg1`, `fgMuted` | Text hierarchy |
| **Status** | `accent`, `success`, `warning`, `danger` | Semantic colors |
| **Line** | `line` | Dividers and borders |
| **Focus** | `focusRing` | Focus indicator |
| **Overlay** | `overlay` | Modal/dropdown backgrounds |
| **Shadow** | `shadowSoft` | Elevation |
| **Spacing** | `space1`(4px) – `space6`(32px) | Layout scale |
| **Radius** | `radiusS`(6px), `radiusM`(10px), `radiusL`(16px) | Border radius |
| **Typography** | `ui`, `body`, `mono` font families; `sizeSm`(12px), `sizeMd`(13px), `sizeLg`(14px) | Type scale |

Both the extension webview and native view summaries should align to these tokens semantically.

## History

- **Three-view IA** (Coach / Plan / Settings): Historical, superseded by the five-view IA. Referenced in older plan documents under `docs/plans/`.
- **Current IA** (Coach / Plan / Resources / Training / Settings): **Shipping** since June 2026.

---

## Cross-Platform UI Contract

| UI 特性 | Windows | macOS | Linux | 实现方式 |
|---------|---------|-------|-------|---------|
| Webview 渲染 | ✅ 一致 | ✅ 一致 | ✅ 一致 | Vite build 平台无关 |
| 侧边栏宽记忆 | ✅ | ✅ | ✅ | VS Code `workspaceState` |
| Focus ring | ✅ | ✅ | ✅ | CSS `outline` token |
| 快捷键 | ✅ Ctrl+Key | ✅ Cmd+Key | ✅ Ctrl+Key | VS Code `when` clause |
| 字体回退 | `Segoe UI` | `SF Pro Text` | system-ui | CSS font-family stack |
| IME 输入 | ✅ | ✅ | ✅ | React controlled input |
| 文件路径显示 | `C:\path` | `/path` | `/path` | VS Code API 自动处理 |
| 拖拽上传 | ✅ | ✅ | ✅ | HTML5 Drag & Drop |
| 右键菜单 | ✅ 原生 | ✅ 原生 | ✅ 原生 | VS Code `menus` contribution |

**规则**：UI 组件永远不直接硬编码 `\` 路径、Win32 API、或平台字体。所有平台差异通过 VS Code API 或 CSS font-family stack 自动适配。
