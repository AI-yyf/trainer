# V4 时钟 harness（FSRS 数天跨度）

**结论：PASS（测试级时钟；不是真实等待数天的 GUI 旅程）**

- 实现：`server/app/core/clock.py`，`TRAINER_TEST_NOW=<ISO>`
- 接入：`FSRSTrainerCardScheduler` 的 create/review/due 全部走 `utc_now()`
- 测试：`server/tests/test_clock_harness.py`（2 passed）

## 断言

| 步骤 | 结果 |
| --- | --- |
| Day 0 创建卡片并 Good | 首次 due 在 10 分钟后 |
| Day 0 + 5 分钟 | 卡片尚未 due |
| 到 due 时刻 | `get_due_cards()` 返回该卡 |
| 第二次 Good | interval 不缩短 |
| Again | `lapses += 1`，interval 不增长 |

## 复现

```bash
cd server
TRAINER_TEST_NOW=2026-11-01T09:00:00Z .venv/bin/python -m pytest tests/test_clock_harness.py -q
```

## 边界

- 这是确定性的 FSRS 时钟 harness；没有真实等待数天。
- ReviewScheduler 的 due horizon 仍使用其自身 `utc_now()`；本次没有把 env 时钟扩散到所有 memory 时间戳。
- 旅程 9/10 的 P/G 证据仍为 NOT_EXECUTED；不能把本测试当作真实模型/真实 GUI 的 PASS。
