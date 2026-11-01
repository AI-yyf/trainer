# Real VS Code GUI acceptance — 2026-11-02

Environment: macOS, Microsoft VS Code 1.127, isolated `--user-data-dir` and
`--extensions-dir`, installed VSIX `local.trainer-extension@1.3.4`, real
Trainer sidecar. Playwright Electron controlled the real workbench window:
command palette → `Trainer: Open Coach Sidebar`, then mouse click on the
webview frame. Not a browser preview.

Captured:
- `real-vscode-first.png` — first-run Trainer sidebar, dark theme, 1440×900.
- `real-vscode-onboarding-200.png` — narrow window + 200% zoom after the setup
  row wrap fix; "连接模型" stays one line, action moves below.
- `real-vscode-settings.png` — real click on「设置」, settings index, dark.
- `real-vscode-settings-narrow-200.png` — settings at narrow + 200%.

Findings:
- The 200% onboarding row no longer breaks Chinese into one glyph per line.
- P1 found, not yet fixed: the Settings workspace summary shows the internal
  `globalStorage/.../sidecar` path as “工作区” while a project folder is open,
  and asks “先在上方选择工作区根目录”. This is the managed data area, not the
  learner's project folder. It needs a separate learning-folder summary and a
  direct choose action.
- Training verification and model-switch screens were not exercised in this
  GUI pass; provider-gated teaching was verified separately via host E2E and
  the real-model journey. Human visual sign-off remains separate.
