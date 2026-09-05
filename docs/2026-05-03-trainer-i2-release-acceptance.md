# Trainer I2 Release Acceptance

> Historical snapshot from the superseded 2026-05-03 three-view phase.
> Current source of truth for Trainer IA is [docs/ui-contract.md](./ui-contract.md): `Coach / Plan / Resources / Training / Settings`.

Date: 2026-05-03
Scope: I2 quality polish, performance, and release acceptance

## Goal

Close the Trainer sidebar into a calmer, installable, coach-first product:

- top-level stays `对话 / 计划 / 设置`
- research remains a background capability, not a top-level page
- first load is lighter
- message flow is easier to read
- plan and settings stay powerful without feeling like an admin console

## Implemented In This Pass

### Performance and packaging

- moved browser preview runtime behind dynamic import in [App.tsx](/Users/Apple/Desktop/trainer/extension/webview/src/app/App.tsx)
- lazy-loaded `CoachPlanView` and `CoachSettingsView` from [App.tsx](/Users/Apple/Desktop/trainer/extension/webview/src/app/App.tsx)
- lazy-loaded Mermaid in [MermaidBlock.tsx](/Users/Apple/Desktop/trainer/extension/webview/src/components/coach/MermaidBlock.tsx)
- lazy-loaded markdown/math plugins in [MessageRichContent.tsx](/Users/Apple/Desktop/trainer/extension/webview/src/components/coach/MessageRichContent.tsx)
- added `manualChunks` and disabled release sourcemaps in [vite.config.ts](/Users/Apple/Desktop/trainer/extension/webview/vite.config.ts)

### UX polish

- tightened message density and bubble sizing in [styles.css](/Users/Apple/Desktop/trainer/extension/webview/src/styles.css)
- refined composer height, icon sizing, placeholder rhythm, and footer density in [styles.css](/Users/Apple/Desktop/trainer/extension/webview/src/styles.css) and [CoachComposer.tsx](/Users/Apple/Desktop/trainer/extension/webview/src/components/composer/CoachComposer.tsx)
- added lightweight loading fallback states for lazy views in [App.tsx](/Users/Apple/Desktop/trainer/extension/webview/src/app/App.tsx)
- kept markdown, table, formula, and Mermaid support while reducing first-load cost

## Verification Results

### Automated checks

- `npm run build --prefix extension/webview` passed
- `npm run build --prefix extension` passed
- `npm run test:extension` passed: `34/34`
- `npm run test:server` passed: `382 passed`
- `npm run verify:delivery` passed

### Packaging

- VSIX built at [trainer-extension-0.1.0.vsix](/Users/Apple/Desktop/trainer/extension/trainer-extension-0.1.0.vsix)
- packaged size: `73.89 MB`
- webview dist size: `4.56 MB`

### Webview bundle snapshot

- main app entry chunk reduced to about `163 KB`
- plan view split to about `11 KB`
- settings view split to about `26 KB`
- browser preview client split to about `24 KB`
- markdown vendor split to about `432 KB`
- mermaid vendor split to about `2.75 MB`

This means the normal installed sidebar no longer pays the full cost of preview, plan, settings, markdown, and Mermaid on first paint.

## Acceptance Checklist

### Passed now

- top-level navigation is limited to `对话 / 计划 / 设置`
- preview-only browser sidecar logic is no longer part of the normal first-load path
- long rich messages still support code blocks, tables, formulas, and Mermaid
- installed extension build and packaging path are healthy
- no regression in extension host or backend automated tests

### Manual QA still required

- install the generated VSIX into a normal VS Code window and confirm sidebar boot end-to-end
- Chinese coach conversation readability in real VS Code sidebar
- English coach conversation readability in real VS Code sidebar
- no-key blocked state in real sidebar
- API key configured state in real sidebar
- file attach flow in real sidebar
- folder attach flow in real sidebar
- long reply folding behavior with real model output
- plan readability with real generated plan data
- settings readability with both incomplete and fully configured provider states

## Current Known Risks

- Mermaid is now deferred, but the `mermaid` runtime itself is still very large once requested. The first diagram render will remain heavier than normal text/code replies.
- The in-app browser QA backend was unavailable during this pass, so visual verification in the Codex browser could not be completed truthfully.
- Settings and plan readability are improved structurally, but they still deserve another focused pass once we can inspect them in a live sidebar again.

## Recommended Next Step

1. Re-open the packaged VSIX in a clean VS Code extension host.
2. Manually verify `对话 / 计划 / 设置` with both no-key and configured-key states.
3. Capture any remaining plan/settings density issues from the live sidebar.
4. If Mermaid remains too expensive, replace full `mermaid` with a smaller diagram strategy or a narrower supported subset.
