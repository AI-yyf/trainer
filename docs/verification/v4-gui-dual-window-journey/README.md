# V4 真实双窗口 GUI 旅程 18（2026-11-09）

- VSIX: `extension/trainer-extension-1.4.1-darwin-arm64.vsix` (v1.4.1)
- Provider: fixture `http://127.0.0.1:53480/v1`（GUI 证据，不是真实模型证据）
- 窗口 1：直接打开项目文件夹；窗口 2：通过同一文件夹的 `.code-workspace` 在同一个 VS Code 实例中打开第二个真实窗口。
- 两个窗口共享同一个 `--user-data-dir`，因此共享学习根目录、Provider 凭据与 sidecar 数据目录。

## 结果

- 状态：**PASS**
- 计划：`plan-5e592327e8154c5a8d2186863c3bfee9`，并发前 revision 1，并发后 2，重载后 2
- 窗口 1 冲突文案：false
- 窗口 2 冲突文案：false

## 断言

- twoRealWindows: true
- sameManagedContext: true
- bothWindowsRenderedPlan: true
- exactlyOneCommittedRevision: true
- noDoubleAdvance: true
- bothWindowsObservedFrozen: true
- frozenStatePersisted: true



> 本文件只记录真实 VS Code 窗口中的 GUI 证据。Fixture provider 的回复不构成真实模型（P）证据。
