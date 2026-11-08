# V4 旅程 2/3 真实 Provider 证据（2026-11-08）

**结论：PASS（真实 Sidecar + 真实 Provider + 真实重启持久化）**

- Provider：`https://linksub.fun`，OpenAI-compatible
- 模型：`deepseek-v4.1-flash`
- 运行方式：真实 `run_sidecar.py` 子进程（临时数据目录），非 TestClient/mock
- 原始产物：`docs/verification/v4-journey-2-3-goal-deepseek-v4.1-flash.json`
- 可复现脚本：`scripts/record-v4-goal-journeys.py`
- Key 仅通过 `TRAINER_TEST_API_KEY` 进程环境注入，未写入本文件/仓库

## 旅程 2 — 随口提问，不建 Goal

Prompt：

> PPO 是什么？请用两句话解释。

真实回复（110 字，节选）：

> PPO（Proximal Policy Optimization，近端策略优化）是一种强化学习策略梯度算法，通过最大化期望回报来训练策略。它用“裁剪”的目标函数限制每次策略更新的幅度，从而在实现简单的同时提高训练稳定性。

断言：

| 断言 | 结果 |
| --- | --- |
| 收到非空真实回复 | ✅ |
| `/goal/current` 为 `null` | ✅ |
| snapshot `plan` 为 `null` | ✅ |
| 未创建 active training card | ✅ |

## 旅程 3 — 明确能力目标自动建立、重启续接

Prompt：

> 我想真正学会实现 PPO Clip，请先判断我该从哪里开始。

真实回复（1359 字，节选）：

> 先别急着读 PPO 论文或抄库。要判断你从哪里开始，先做一个**最小分诊**：PPO-Clip 的真正前置不是“会调用 stable-baselines3”，而是下面这条链是否打通……策略梯度 → baseline/优势函数 → on-policy rollout → 重要性采样 ratio → clip 目标 → 多 epoch 更新……

Goal 结果：

| 字段 | 值 |
| --- | --- |
| title | `实现 PPO Clip` |
| source | `coach_detected` |
| status | `active` |
| workspace | 独立临时工作区 |
| goalId | 单次运行内稳定 |

真实重启：

1. 停止 sidecar 进程；
2. 用同一数据目录重新启动真实 sidecar；
3. `/session/start` 后 `/goal/current` 返回**同一个 goalId**、同一标题、`active`。

续接 Prompt：

> 继续，从最小实现开始，先给我第一步。

断言：

| 断言 | 结果 |
| --- | --- |
| Goal 自动建立 | ✅ |
| 标题未吞入“请先判断…”请求从句 | ✅ |
| 重启后 Goal 仍存在且 id 相同 | ✅ |
| 续接回合仍绑定同一 Goal | ✅ |
| 两次真实回复均非空 | ✅ |

## 复现命令

```bash
TRAINER_TEST_API_KEY=... \
TRAINER_TEST_BASE_URL=https://linksub.fun \
TRAINER_TEST_MODEL=deepseek-v4.1-flash \
server/.venv/bin/python scripts/record-v4-goal-journeys.py
```

## 边界

- 这是一次单模型、单工作区、单次运行的真实证据；不是 20 条旅程的完整验收。
- 未覆盖真实 VS Code GUI、Remote-SSH、多窗口或数天时间推进。
- 未把聊天记作学习完成：Goal 活动计数保持 0，符合“纯聊天不产生学习证据”。
