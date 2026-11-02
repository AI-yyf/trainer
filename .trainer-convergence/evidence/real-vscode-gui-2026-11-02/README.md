# Real Microsoft VS Code GUI journey — 2026-11-02

Code: `1c82a41` (source), packaged VSIX `local.trainer-extension@1.3.4`.
Environment: macOS, real Microsoft VS Code 1.127, isolated `--user-data-dir`
and `--extensions-dir`, real Trainer sidecar, owner-supplied OpenAI-compatible
relay. Playwright Electron drove the actual workbench window and the webview
frame with mouse clicks and keyboard input. The provider key was supplied only
through `PROBE_PROVIDER_API_KEY` and is not stored in this repository.

The learning-folder native picker cannot be driven headlessly on macOS without
System Events accessibility (not granted), so the script seeds the same
extension global state the picker writes and then exercises the real UI. This
is stated here rather than presented as a machine-clicked native dialog.

| step | result |
| --- | --- |
| 01 first run | real sidebar, dark theme, first-run setup card |
| 02 settings index | workspace row shows the chosen learning folder, never globalStorage/sidecar |
| 03 provider saved | real relay URL/key/model entered in the installed UI |
| 04 provider test | PASS on attempt 1: streaming/tools/model verified; "模型已就绪" |
| 05 project found | "加入 Trainer / 仅浏览 / 忽略" admission card |
| 05b project joined | managed admission completed; composer unlocked |
| 06 first real reply | PASS: MiniMax-M2.7 read `src/queue_lock.py` and `README.md` and explained the actual lock invariant (322 chars) |
| 07 model switch | PASS: refreshed live model list, switched to `MiniMax-M3.1-Flash`, saved and tested |
| 08 second reply | PARTIAL: M3.1 produced visible text but the provider stream did not close within 240 s; no success is claimed |

The first real reply is grounded in the workspace file, not a guess: the
previous build could only say it had the filename. The fix enables the verified
tool loop when the learner names a concrete workspace file.

Screenshots in this directory are the real VS Code window captures for the
steps above. `08-switch-reply-partial.png` intentionally shows the unresolved
streaming state; it is residual evidence, not a pass.
