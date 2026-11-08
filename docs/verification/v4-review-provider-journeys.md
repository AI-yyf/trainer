# V4 复习旅程 9/11/12（真实 Provider + 时钟）

**结论：3 PASS（真实 sidecar + 真实模型；10 仍未执行）**

- Provider：`https://linksub.fun` / `deepseek-v4.1-flash`
- 时钟：`TRAINER_TEST_NOW` day0 → day3 → day30
- 原始产物：`docs/verification/v4-review-provider-journeys.json`
- 脚本：`scripts/record-v4-review-provider-journeys.py`
- Key 仅通过 `TRAINER_TEST_API_KEY` 注入

## 旅程 9 — 数天后忘记，自然安排复习

- Day 0：写入 10 条 `repeated_error` 学习信号；
- Day 3：真实 sidecar 返回 4 条 due reviews（tuple mutability、dict key hashing、list aliasing、closure capture）；
- 真实模型回复先问一个最小问题，而不是一次讲完。

**PASS**：due queue 真的跨天出现，真实模型按复习回合回应。

## 旅程 11 — 拒绝复习/忙碌，不被打扰

- 对 due concept 执行 `skip`：返回 `next_review_at` 为次日，当前 due 队列移除该条；
- 真实模型回合：“我现在很忙，先别安排复习；只用一句话提醒我 tuple 为什么不可变。”
- 回复只给一句解释，没有重新拉起复习队列。

**PASS**：跳过动作真实生效，模型回合不强行打断。

## 旅程 12 — 长期未上线返回，不积压提醒

- Day 30 重新启动；
- due 列表 4 条，concept 无重复；
- 真实模型只给一个最小回顾问题。

**PASS**：没有重复堆积；仍保留最小复习入口。

## 旅程 10 — 未执行

`review-queue/action=done` 只会把下一次复习推到 10 分钟后，不会产生 FSRS 的天级间隔；真实 FSRS 间隔需要一张真实训练卡。
本次没有生成可用训练卡，因此 **10 仍为 NOT_EXECUTED**，不把复习动作当作 FSRS 间隔延长。

## 边界

- 时钟是 `TRAINER_TEST_NOW` 注入，不是真实等待数天。
- 这是真实 sidecar + 真实模型，但训练卡/FSRS 间隔未进入本 run。
