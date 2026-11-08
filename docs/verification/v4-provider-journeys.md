# V4 真实 Provider 旅程 5/6/15/19/20（2026-11-08）

**结论：3 PASS / 2 PARTIAL / 5 NOT_EXECUTED**

- Provider：`https://linksub.fun` / `deepseek-v4.1-flash`
- 运行方式：真实 `run_sidecar.py` 子进程 + 真实公网模型，非 TestClient/mock
- 原始产物：`docs/verification/v4-provider-journeys.json`
- 可复现脚本：`scripts/record-v4-provider-journeys.py`
- Key 仅通过 `TRAINER_TEST_API_KEY` 注入，未写入仓库/文档

## 旅程 5/6 — 教学偏好适配 / 改变

同一问题：

> 解释 Python 元组里的列表为什么还能修改，控制在 6 行内，并给一个最小可运行例子。

| 存储偏好 | 回复字数 | 观察 |
| --- | --- | --- |
| `hands-on` | 245 | 先给操作规则，再给可运行例子 |
| `concept-first` | 261 | 先给“浅层不可变”的概念，再给例子 |

两次回复内容不同、均非空、均围绕同一问题。**5/6 记为 PASS（GUI/真实模型下的偏好切换可见）**；不把“风格差异”夸大为掌握证据。

## 旅程 19 — 记忆撤销

- 保存 `teaching_style=guided`，真实模型回复；
- 清空 global preferences / long-term goals，`teaching_style=auto`，同一问题再回复；
- 两次回复均非空，存储状态确实清空。

清空 global preferences / long-term goals 后，teaching_style 从 `hands-on` 改为 `concept-first`；同一问题两次真实回复不同。**记为 PASS**，状态清空由 `v4-integrity-journeys` 的 S 证据覆盖。

## 旅程 15 — 资料版本变化

- 上传并索引 Project A（AlphaQueue）；
- 真实模型引用该资料回答：模型未读取附件，回答“资料中没有提到”；
- 修改为 BetaQueue 后重新索引，模型同样未读取。

标记 **PARTIAL**：真实模型这一轮没有消费 resource context；版本冲突本身由 `v4-integrity-journeys` 的真实 sidecar 409 证据覆盖。

## 旅程 20 — 多项目

- 项目 A 使用 AlphaQueue，项目 B 被告知使用 BetaQueue；
- 项目 A 回答未出现 BetaQueue（无跨项目泄漏）；
- 项目 B 回答为 RabbitMQ，没有保留 BetaQueue 事实。

标记 **PARTIAL**：没有观察到泄漏，但项目 B 的事实保持失败，不能记为 PASS。

## 未执行

| 旅程 | 原因 |
| --- | --- |
| 9 数天后忘记 | 需要真实数天时钟 |
| 10 正确延迟回忆 | 需要真实延迟回忆 |
| 11 拒绝复习/忙碌 | 需要真实 due queue 与真实模型回合 |
| 12 长期未上线返回 | 需要真实长离线时钟 |
| 18 多窗口并发 | 需要两个真实 VS Code 窗口 |

这些不以单元测试或 fixture 替代 PASS。

## 复现

```bash
TRAINER_TEST_API_KEY=... \
TRAINER_TEST_BASE_URL=https://linksub.fun \
TRAINER_TEST_MODEL=deepseek-v4.1-flash \
server/.venv/bin/python scripts/record-v4-provider-journeys.py
```
