# Trainer Sidebar Minimalist Redesign Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rebuild the Trainer sidebar into a Codex-like, VS Code-native, single-chat surface with fewer visible controls, fewer overlapping entry points, and stronger send-time intelligence.

**Architecture:** Keep the current single-sidebar shell, but invert the UI hierarchy so conversation and composer become the primary surface and all advanced controls collapse behind lightweight chips, popovers, or slash commands. Reuse the existing webview host/runtime pipeline and shared command infrastructure, while slimming the React shell and introducing a shared send-intelligence layer that explains each send before it happens.

**Tech Stack:** VS Code webview, React 18, Zustand, TypeScript strict mode, shared TS models/utilities, FastAPI sidecar compatibility, Node test runner.

---

## Product Direction

This redesign should treat the current sidebar as functionally rich but visually over-exposed. The current problems are:

- Too many always-visible controls compete with the conversation stream.
- Multiple areas describe the same thing: current context, send package, and attach-on-send all overlap.
- Navigation reflects internal modules (`task`, `review`, `plan`, `memory`) instead of a user’s actual workflow.
- Styling reads as a standalone mini web app instead of a native-feeling VS Code sidebar.
- Powerful capabilities are distributed across tabs, buttons, cards, and slash commands rather than being centered on a single send action.

The redesign target is:

- One primary surface: conversation + composer.
- One compact send summary line.
- Three compact control groups at most: intent, context, and more.
- No always-visible theme control.
- No always-visible quick actions section.
- Rich capabilities preserved through slash commands, artifact cards, and collapsed controls.

## Non-Goals

- Do not redesign backend trainer semantics or session APIs.
- Do not rewrite the whole extension host or sidecar architecture.
- Do not add a new persistence system.
- Do not reintroduce multi-panel workbench patterns.

## Implementation Principles

- Remove overlapping controls before adding new ones.
- Prefer progressive disclosure over always-visible toggles.
- Preserve all current capabilities even when reducing visible UI.
- Treat VS Code as the primary design system; avoid heavy standalone-app chrome.
- Keep bilingual support first-class in every new abstraction.

---

### Task 1: Establish shared send-intelligence primitives

**Files:**
- Create: `shared/src/sendIntelligence.ts`
- Modify: `shared/src/index.ts`
- Test: `extension/tests/sendIntelligence.test.js`

**Step 1: Write the failing test**

Create a focused shared-logic test file that verifies:

- local sidebar commands are classified as `local_command`
- `/review` remains a trainer turn, not a local command
- `review` intent warns when there is no active file
- `review` intent warns when current file attachment is disabled
- selection-related warnings appear when selection is available but not attached
- related-file warnings appear when related files are available but not attached
- research mode drafts classify as `research`

Use Node test runner so it aligns with the existing extension tests.

**Step 2: Run test to verify it fails**

Run:

```bash
node --test extension/tests/sendIntelligence.test.js
```

Expected: FAIL because the shared classifier does not exist yet.

**Step 3: Write minimal implementation**

Implement `shared/src/sendIntelligence.ts` with:

- `analyzeSendIntent(input)`
- `SendTarget`, `SendIntent`, `SendWarning`, and related input/output types
- intent resolution logic for trainer turns
- warning generation for missing/disabled context
- local command detection using `shared/src/sidebarCommands.ts`

Update `shared/src/index.ts` to export the new module.

**Step 4: Run test to verify it passes**

Run:

```bash
node --test extension/tests/sendIntelligence.test.js
```

Expected: PASS.

**Step 5: Commit**

```bash
git add shared/src/sendIntelligence.ts shared/src/index.ts extension/tests/sendIntelligence.test.js
git commit -m "feat: add shared send intelligence model"
```

---

### Task 2: Collapse top-level navigation to a chat-first information architecture

**Files:**
- Modify: `extension/webview/src/app/App.tsx`
- Modify: `extension/webview/src/lib/types.ts`
- Modify: `extension/webview/src/app/useWorkbenchState.ts`
- Test: `extension/tests/webviewBridge.test.js`

**Step 1: Write the failing test**

Add or update a view-level behavior test around bootstrap/view handling to reflect the new top-level IA assumptions:

- primary view defaults to `coach`
- secondary information surfaces are not represented as always-visible peer tabs unless still required
- the webview still boots and patching still works when the visible nav is reduced

If a direct component-level test is too expensive in the current setup, document the intended delta with a narrower behavior assertion in the existing bridge/store tests.

**Step 2: Run test to verify it fails**

Run:

```bash
node --test extension/tests/webviewBridge.test.js
```

Expected: FAIL or expose outdated assumptions about visible navigation.

**Step 3: Write minimal implementation**

Refactor the sidebar IA so that:

- only `coach` and `research` remain top-level visible modes, or equivalent reduced-mode presentation
- `task`, `review`, `plan`, and `memory` become contextual artifact surfaces inside chat or lightweight subpanels rather than persistent peer navigation
- artifact open buttons still jump users to the correct contextual surface
- state model remains backward compatible where practical

Avoid deleting useful state types unless necessary; the goal is UI simplification, not data loss.

**Step 4: Run test to verify it passes**

Run:

```bash
npm run check --prefix extension/webview
node --test extension/tests/webviewBridge.test.js
```

Expected: PASS.

**Step 5: Commit**

```bash
git add extension/webview/src/app/App.tsx extension/webview/src/lib/types.ts extension/webview/src/app/useWorkbenchState.ts extension/tests/webviewBridge.test.js
git commit -m "refactor: collapse trainer navigation into chat-first shell"
```

---

### Task 3: Remove overlapping control zones and merge them into one send summary strip

**Files:**
- Modify: `extension/webview/src/app/App.tsx`
- Modify: `extension/webview/src/styles.css`
- Test: `extension/tests/workbenchData.test.js`

**Step 1: Write the failing test**

Add assertions or a small new test helper that validates the underlying data needed for the new send summary:

- resolved intent label
- file presence
- selection presence
- diagnostics presence
- related file count

This can be a logic-level test extracted into pure helpers if UI rendering tests are not in place.

**Step 2: Run test to verify it fails**

Run:

```bash
node --test extension/tests/workbenchData.test.js
```

Expected: FAIL because the summary helper does not exist or current assumptions still reflect multiple redundant panels.

**Step 3: Write minimal implementation**

In `App.tsx`:

- remove the dedicated `quick-actions` section
- remove the duplicated “send package” vs “attachments” split as separate large blocks
- replace them with a single compact send-summary strip above the composer
- keep intent, context, and more as compact grouped controls rather than full rows of repeated pills
- ensure no duplicate display of `language`, `answer mode`, and `context detail`

In `styles.css`:

- reduce card weight and padding
- align spacing, borders, and surface contrast more closely with VS Code sidebars
- tone down oversized pills and blue-heavy emphasis

**Step 4: Run test to verify it passes**

Run:

```bash
npm run build --prefix extension/webview
node --test extension/tests/workbenchData.test.js
```

Expected: PASS.

**Step 5: Commit**

```bash
git add extension/webview/src/app/App.tsx extension/webview/src/styles.css extension/tests/workbenchData.test.js
git commit -m "refactor: merge overlapping send controls into compact summary"
```

---

### Task 4: Add send analysis card with warnings and one-click corrections

**Files:**
- Modify: `extension/webview/src/app/App.tsx`
- Modify: `extension/webview/src/lib/types.ts`
- Modify: `extension/webview/src/styles.css`
- Test: `extension/tests/sendIntelligence.test.js`

**Step 1: Write the failing test**

Extend send-intelligence tests to cover user-facing warning cases that the UI will consume:

- review with no file
- review with file attachment disabled
- selection available but not attached
- related files available but not attached
- review with non-full context detail

**Step 2: Run test to verify it fails**

Run:

```bash
node --test extension/tests/sendIntelligence.test.js
```

Expected: FAIL for any missing warning behavior.

**Step 3: Write minimal implementation**

In `App.tsx`:

- compute send analysis using `shared/src/sendIntelligence.ts`
- render a compact analysis card above the composer only when useful
- show:
  - target (`trainer`, `research`, or local command)
  - resolved intent
  - attached context summary
  - warnings
  - one-click fix actions, such as enabling file context or switching review to full detail

Ensure the card is small, skimmable, and collapsible if needed.

**Step 4: Run test to verify it passes**

Run:

```bash
npm run build --prefix extension/webview
node --test extension/tests/sendIntelligence.test.js
```

Expected: PASS.

**Step 5: Commit**

```bash
git add extension/webview/src/app/App.tsx extension/webview/src/lib/types.ts extension/webview/src/styles.css extension/tests/sendIntelligence.test.js
git commit -m "feat: add send analysis warnings and correction actions"
```

---

### Task 5: Convert advanced controls into popovers or menus instead of always-visible rows

**Files:**
- Modify: `extension/webview/src/app/App.tsx`
- Modify: `extension/webview/src/styles.css`
- Optional create: `extension/webview/src/components/CompactControlMenu.tsx`
- Test: `extension/tests/webviewBridge.test.js`

**Step 1: Write the failing test**

Create a narrow test or assertion that ensures the composer still sends the same message payloads after control relocation:

- `responseLanguage`
- `answerMode`
- `contextDetail`
- include flags

This can be done by extracting and testing a payload builder helper if needed.

**Step 2: Run test to verify it fails**

Run:

```bash
node --test extension/tests/webviewBridge.test.js extension/tests/workbenchData.test.js
```

Expected: FAIL because the control extraction helper does not yet exist or behavior is not preserved.

**Step 3: Write minimal implementation**

Move advanced controls behind compact menus:

- `Intent` menu
- `Context` menu
- `More` menu

Keep only a tiny number of visible triggers in the composer region.

Requirements:

- no always-visible theme control
- no repeated toggle rows
- no separate control slab that is taller than the textarea itself
- all current payload semantics preserved

**Step 4: Run test to verify it passes**

Run:

```bash
npm run check --prefix extension/webview
node --test extension/tests/webviewBridge.test.js extension/tests/workbenchData.test.js
```

Expected: PASS.

**Step 5: Commit**

```bash
git add extension/webview/src/app/App.tsx extension/webview/src/styles.css extension/webview/src/components/CompactControlMenu.tsx extension/tests/webviewBridge.test.js extension/tests/workbenchData.test.js
git commit -m "refactor: collapse advanced trainer controls into compact menus"
```

---

### Task 6: Make slash commands the hidden power layer, not a competing navigation system

**Files:**
- Modify: `shared/src/sidebarCommands.ts`
- Modify: `extension/webview/src/app/App.tsx`
- Test: `extension/tests/sidebarCommands.test.js`

**Step 1: Write the failing test**

Add tests for:

- command suggestions remain bilingual
- local control commands remain distinct from remote trainer commands
- slash deck suggestions use reduced, non-overlapping local command vocabulary

**Step 2: Run test to verify it fails**

Run:

```bash
node --test extension/tests/sidebarCommands.test.js
```

Expected: FAIL if command labels or aliases do not match the simplified IA.

**Step 3: Write minimal implementation**

Tighten the local command system so it complements the minimalist UI:

- keep control commands that matter for power users
- remove any command alias that duplicates a visible top-level action unnecessarily
- keep `/open ...`, `/lang ...`, `/mode ...`, `/detail ...`, `/attach ...`, `/follow ...`
- ensure suggestions appear only when genuinely useful

**Step 4: Run test to verify it passes**

Run:

```bash
node --test extension/tests/sidebarCommands.test.js
```

Expected: PASS.

**Step 5: Commit**

```bash
git add shared/src/sidebarCommands.ts extension/webview/src/app/App.tsx extension/tests/sidebarCommands.test.js
git commit -m "refactor: align sidebar slash commands with minimalist shell"
```

---

### Task 7: Reduce visual weight to match VS Code native surfaces

**Files:**
- Modify: `extension/webview/src/styles.css`
- Modify: `shared/src/tokens.ts` if token adjustments are required
- Test: manual smoke in VS Code

**Step 1: Write the failing test**

No strong automated CSS visual test exists today. Instead, create a manual acceptance checklist in the plan and document the expected visual delta.

Checklist:

- fewer stacked bordered boxes
- smaller radii
- less saturated blue emphasis
- tighter vertical rhythm
- composer visually dominant over control chrome
- artifact cards lighter than before

**Step 2: Run the baseline build**

Run:

```bash
npm run build --prefix extension/webview
```

Expected: PASS before visual edits so regressions can be isolated.

**Step 3: Write minimal implementation**

Adjust CSS and tokens to:

- reduce border radius
- reduce card count and nested surfaces
- flatten heavy gradients where they fight VS Code
- keep enough contrast for readability
- make the shell feel like a native sidebar, not a mini dashboard

**Step 4: Verify manually**

Run:

```bash
npm run build --prefix extension/webview
npm run build --prefix extension
```

Then open the extension in VS Code and confirm:

- the sidebar feels visually aligned with native panels
- the conversation stream is the dominant surface
- controls no longer overpower content

**Step 5: Commit**

```bash
git add extension/webview/src/styles.css shared/src/tokens.ts
git commit -m "style: align trainer sidebar with vscode surface language"
```

---

### Task 8: Update verification docs to reflect the new chat-first sidebar

**Files:**
- Modify: `docs/verification.md`
- Optional modify: `docs/architecture.md`

**Step 1: Write the failing test**

No automated doc test required. Instead, identify documentation lines that still describe the old multi-section shell and manual smoke flow.

**Step 2: Review current docs**

Run:

```bash
sed -n '1,220p' docs/verification.md
sed -n '1,220p' docs/architecture.md
```

Expected: current docs still reflect older workbench assumptions.

**Step 3: Write minimal implementation**

Update docs so they describe:

- single-sidebar chat-first shell
- compact context controls
- send analysis expectations
- new manual smoke checklist focused on composer, artifact cards, and context correction

**Step 4: Verify**

Run:

```bash
git diff -- docs/verification.md docs/architecture.md
```

Expected: docs match the new architecture.

**Step 5: Commit**

```bash
git add docs/verification.md docs/architecture.md
git commit -m "docs: update trainer verification for minimalist sidebar"
```

---

## Final Verification Sequence

After all tasks are complete, run:

```bash
npm run build --prefix extension/webview
npm run check --prefix extension/webview
npm run build --prefix extension
npm run check --prefix extension
node --test extension/tests/*.test.js
python3 -m py_compile server/app/core/models.py server/app/api/routers.py server/app/llm/prompts.py server/app/llm/provider_service.py
```

If Python dependencies are installed later, also run:

```bash
cd server && python -m pytest tests/ -v
```

## Manual Acceptance Checklist

- The sidebar reads as a native VS Code panel, not a mini dashboard.
- The first thing the eye sees is conversation and composer, not configuration chrome.
- There is no duplicated context presentation across multiple sections.
- Users can understand “what will happen if I send now” without guessing.
- Users can fix missing context in one click before sending.
- The number of always-visible controls is materially smaller than today.
- Remote trainer commands and local sidebar commands do not conflict.
- Chinese and English modes both feel intentional, not partially translated.

## Risks and Guardrails

- Biggest risk: over-simplifying the UI while accidentally hiding critical controls.
  Guardrail: preserve every current payload feature and expose it through menus or slash commands.

- Biggest risk: chat-first reduction breaks discoverability for plan/review/task artifacts.
  Guardrail: use conversation artifact cards and lightweight context menus, not permanent peer tabs.

- Biggest risk: send analysis becomes another bulky panel.
  Guardrail: keep it conditional, compact, and action-oriented.

- Biggest risk: local command system drifts away from visible UI.
  Guardrail: maintain shared command definitions in `shared/src/sidebarCommands.ts`.

## Handoff Notes

- Start with Task 1 and Task 3 together only if helper boundaries are clean; otherwise do them sequentially.
- Do not attempt a full rewrite of `App.tsx` in one patch. Prefer extracting pure helpers as you go.
- Keep test coverage expanding as UI logic moves into helpers.
- Favor deleting UI over redesigning every old section.

Plan complete and saved to `docs/plans/2026-04-30-trainer-sidebar-minimalist-redesign.md`. Two execution options:

1. Subagent-Driven (this session) - I dispatch fresh subagent per task, review between tasks, fast iteration

2. Parallel Session (separate) - Open new session with executing-plans, batch execution with checkpoints

Which approach?
