# V4 旅程 10 — 真实 FSRS 天级间隔 + 延迟回忆（2026-11-08）

**结论：PASS（真实 sidecar + guided-pack 训练卡 + 真实 Provider 延迟回忆）**

- Provider：`https://linksub.fun` / `deepseek-v4.1-flash`
- 卡：guided pack `remote_workspace`，真实训练卡
- 时钟：Day0 09:00 → 09:10 → Day2 09:10
- 原始产物：`docs/verification/v4-fsrs-delayed-recall.json`
- 脚本：`scripts/record-v4-fsrs-delayed-recall.py`
- Key 仅通过 `TRAINER_TEST_API_KEY` 注入

## 结果

| 复习 | 时间 | 验收 | interval | 下一次 due |
| --- | --- | --- | --- | --- |
| 1 | Day0 09:00 | PASS | 0 | Day0 09:10 |
| 2 | Day0 09:10 | PASS | **2 天** | Day2 09:10 |
| 延迟回忆 | Day2 09:10 | 真实模型 200 | — | — |

真实延迟回忆回复：

> 你远程工作区的边界，是只允许你本人访问，还是也允许其他同事/外部人员访问？

## 修复的真实缺陷

FSRS 的 learning `step` 之前没有随 workspace payload 持久化。每次 sidecar 重启后 Good 都回到 10 分钟，卡片永远无法毕业到天级间隔。现在：

- `TrainingCardState.step` 参与序列化/反序列化；
- `_create_fsrs_card` 恢复 `step`；
- 第二次 Good 正常进入 `Review`，interval = 2 天；
- 回归测试：`server/tests/test_clock_harness.py::test_learning_step_survives_persistence_and_graduates`。

## 边界

- 时钟是 `TRAINER_TEST_NOW` 推进，不是真实等待两天。
- 训练卡生成使用 guided pack（确定性、可验证），不是模型自由生成卡；真实模型用于连接测试和延迟回忆回合。
