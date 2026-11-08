# V4 旅程 18 — 双客户端并发（真实 Provider + 计划 revision）

**结论：PASS（真实 sidecar + 真实模型 + 两个并发客户端）**

- Provider：`https://linksub.fun` / `deepseek-v4.1-flash`
- 运行方式：真实 `run_sidecar.py` 子进程；两个独立 `session_id`（同一 workspace，模拟两个窗口）
- 原始产物：`docs/verification/v4-dual-window-journey.json`
- 脚本：`scripts/record-v4-dual-window-journey.py`
- Key 仅通过 `TRAINER_TEST_API_KEY` 注入

## 结果

1. 用真实模型生成正式计划，初始 revision = 1；
2. 两个客户端同时提交正式标题变更，均携带 `expected_revision=1`；
3. 结果：一个 `200`，一个 `409 plan_revision_conflict`；
4. 存储计划只保留赢家标题，revision 只前进一次（2）。

| 断言 | 结果 |
| --- | --- |
| 恰好一个写入成功 | ✅ |
| 另一个返回 revision 冲突 | ✅ |
| 存储标题等于赢家 | ✅ |
| revision 只前进一次 | ✅ |

## 边界

- 这是两个独立客户端/session 的并发，不是两个真实 VS Code Electron 窗口；GUI 双窗口仍未执行。
- 计划生成使用真实模型；并发写入本身是 sidecar/SQLite 行为。
- 不把本结果当作 G（真实双窗口）证据。
