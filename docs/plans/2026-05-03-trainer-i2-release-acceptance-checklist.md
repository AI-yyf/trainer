# Trainer I2 Release Acceptance Checklist

> Historical snapshot from the superseded 2026-05-03 three-view phase.
> Current source of truth for Trainer IA is [docs/ui-contract.md](../ui-contract.md): `Coach / Plan / Resources / Training / Settings`.

> **For Claude/Codex:** Use this checklist to verify the final delivery before packaging or installation.

**Goal:** Ensure Trainer is stable, readable, and installable as a VS Code coach sidebar.

**Architecture:** Validate the real extension/webview path, the startup fallback path, and the main user flows in both Chinese and English. Keep the front panel minimal: 对话 / 计划 / 设置.

**Tech Stack:** VS Code extension host, React webview, FastAPI sidecar, OpenAI-compatible provider.

---

### Task 1: Confirm startup states

**Files:**
- Test: `extension/webview/src/main.tsx`
- Test: `extension/src/core/webviewContent.ts`

**Step 1: Verify the startup shell appears before the webview is ready.**

**Step 2: Verify no-key, bad-key, and sidecar-offline cases show a clear fallback.**

**Step 3: Verify the shell never goes black on load.**

### Task 2: Verify the three main views

**Files:**
- Test: `extension/webview/src/app/App.tsx`
- Test: `extension/webview/src/components/coach/CoachConversationView.tsx`
- Test: `extension/webview/src/components/plan/CoachPlanView.tsx`
- Test: `extension/webview/src/components/settings/CoachSettingsView.tsx`

**Step 1: Verify 对话 reads like a normal chat stream.**

**Step 2: Verify 计划 reads like a single training mainline, not a dashboard.**

**Step 3: Verify 设置 reads like a system panel, but stays visually calm.**

### Task 3: Verify composer behavior

**Files:**
- Test: `extension/webview/src/components/composer/CoachComposer.tsx`

**Step 1: Verify Enter sends, Shift+Enter inserts newline, and Esc clears.**

**Step 2: Verify the icon row stays compact and aligned.**

**Step 3: Verify resource upload supports files and folders in the expected limits.**

### Task 4: Verify content rendering

**Files:**
- Test: `extension/webview/src/components/coach/MessageRichContent.tsx`
- Test: `extension/webview/src/components/coach/CoachMessageBubble.tsx`

**Step 1: Verify long replies collapse cleanly.**

**Step 2: Verify code blocks, tables, formulas, and Mermaid render correctly.**

**Step 3: Verify assistant/user messages remain easy to distinguish.**

### Task 5: Verify packaging

**Files:**
- Test: `extension/package.json`
- Test: `package.json`

**Step 1: Run `npm run build`.**

**Step 2: Run `npm run package:vsix --prefix extension`.**

**Step 3: Install the generated `.vsix` into a normal VS Code window and confirm the sidebar opens without a black screen.**

**Step 4: Record any remaining risks before release.**

## Acceptance

- No black screen on startup
- Main views are readable and calm
- Composer is compact and functional
- Build and VSIX packaging succeed
