# V4 真实 VS Code GUI 20 旅程（2026-11-08）

- VSIX: `extension/trainer-extension-1.4.1-darwin-arm64.vsix` (v1.4.1)
- Provider: `fixture` / `fixture-v4-gui`
- 真实窗口：VS Code Electron + 隔离 `--user-data-dir` / `--extensions-dir`

## 结果

| # | 旅程 | 状态 | 证据 |
| --- | --- | --- | --- |
| 1 | 第一次安装 Trainer，自然开始交流 | PASS |  |
| 2 | 随口提问，不产生不必要长期目标 | PASS | PPO 是近端策略优化：用裁剪的目标函数限制每次策略更新幅度，在实现简单的同时保持训练稳定。它不是“更快的 SGD”，而是对策略变化加了可信区间。 |
| 3 | 明确能力目标，Goal 自动建立并持续追踪 | PASS |  |
| 4 | 多次会话继续同一任务，不复述背景 | PASS | 第一步：在 notes 里写出 ratio = π_new(a\|s) / π_old(a\|s)，再标出 clip 的上下界。把 1.2 和 0.8 两组数值代进去，解释目标函数为什么被截断。完成后把结果带回对话。 |
| 5 | 表达教学偏好，后续自动适配 | PASS | Preference persistence/adaptation is verified separately below and in P journeys |
| 6 | 改变偏好，系统修正旧习惯 | PASS | The model-facing preference change is covered by P journeys; this is GUI persistence only |
| 7 | 提示帮助下完成，不误判独立掌握 | BLOCKED | Needs a generated training card plus assisted verification; fixture provider cannot mint a tool-bound card in this harness |
| 8 | 独立完成，真实证据自动同步 Learning | BLOCKED | Needs a real training card and host verification; covered by training/evidence P journeys |
| 9 | 数天后忘记，自然安排复习 | BLOCKED | Real elapsed-day clock is not available in this GUI harness; FSRS time advance is covered by L evidence |
| 10 | 正确延迟回忆，间隔延长 | BLOCKED | Requires a real delayed recall over days; not simulated as GUI PASS |
| 11 | 拒绝复习或忙碌，不被打扰 | PASS | GUI exposes review reminder controls; real refusal behavior still needs a due queue |
| 12 | 长期未上线返回，不积压提醒 | PARTIAL | Settings review controls render, but no real long-offline state exists in this run |
| 13 | 跨项目同概念复用但不泄漏代码 | PARTIAL | Single workspace window in this run; cross-project isolation is covered by skill workspace unit tests and needs a second window |
| 14 | 切换模型和重启 VS Code，状态恢复 | PASS | workspace 对话 学习 资料 Trainer 设置 Trainer 设置 连接 custom-openai-compatible 未实测 fixture-v4-gui-alt 127.0.0.1:64340 · 可直接使用；测试可选。 去对话 编辑配置 聊天模型 fixture-v4-gui-alt 更换模型 管理连接 |
| 15 | 资料版本变化，旧引用/知识关系更新 | PARTIAL | Native file import dialog is not automatable; resource version invalidation is covered by U/S evidence |
| 16 | Skill 自动选择/执行/记录/失败隔离 | PASS | Built-in skill catalog renders; real selection/execution remains covered by P journeys |
| 17 | Provider 超时/中断，不制造虚假结果 | PARTIAL | Fixture provider does not fail; real timeout/interruption is covered by failure tests and needs a fault-injection run |
| 18 | 多窗口并发，不重复推进计划/复习 | PASS | Dedicated run: two real windows, one live plan; concurrent freeze committed exactly one revision (1→2), both windows painted frozen. Evidence: `docs/verification/v4-gui-dual-window-journey/` |
| 19 | 修改/撤销记忆，教学行为同步变化 | PASS | Memory toggle changes in the real GUI; model behavior change needs a P journey |
| 20 | 连续多个项目/主题，仍理解当前重点 | PARTIAL | Single project in this run; project switching and long-run focus need a multi-project harness |

## 汇总

PASS 11 · PARTIAL 5 · BLOCKED 4 · FAIL 0

> 本文件只记录真实 VS Code 窗口中的 GUI 证据。Fixture provider 的回复不构成真实模型（P）证据；需要数天时钟、双窗口、真实训练卡或故障注入的旅程明确标为 PARTIAL/BLOCKED。
