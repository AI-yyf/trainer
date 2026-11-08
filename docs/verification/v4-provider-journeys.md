# V4 真实 Provider 旅程 5/6/15/19/20（2026-11-08）

**结论：本文件覆盖的 5/6/15/19/20 全部 PASS**（9/10/11/12/18 见独立证据文件）

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

- 保存 `teaching_style=hands-on`，真实模型回复；
- 清空 global preferences / long-term goals，`teaching_style=concept-first`，同一问题再回复；
- 两次回复均非空且不同，存储状态确实清空。

**记为 PASS**，状态清空另由 `v4-integrity-journeys` 的 S 证据覆盖。

## 旅程 15 — 资料版本变化

- 上传并索引 Project A（AlphaQueue）；
- 真实模型先引用 `AlphaQueue`；
- 修改为 BetaQueue 后重新索引，真实模型引用 `BetaQueue`，不残留旧队列。

**记为 PASS**。

修复：`build_coaching_messages` 现在把请求附带的 resource 摘要/current file 内容再放到最后一条 user message 的 `## Attached material for this request` 区块，避免模型把系统提示里的 Runtime Context 当作无关背景。

## 旅程 20 — 多项目

- 项目 A 只引用 `ALPHA_QUEUE = "AlphaQueue"`；
- 项目 B 只引用 `BETA_QUEUE = "BetaQueue"`；
- 没有跨项目泄漏。**记为 PASS**（同一上下文注入修复）。

## 未执行

9/10/11/12/18 已由独立脚本记录：

- `v4-review-provider-journeys.md`（9/11/12）
- `v4-fsrs-delayed-recall.md`（10）
- `v4-dual-window-journey.md`（18，两个并发客户端）

## 复现

```bash
TRAINER_TEST_API_KEY=... \
TRAINER_TEST_BASE_URL=https://linksub.fun \
TRAINER_TEST_MODEL=deepseek-v4.1-flash \
server/.venv/bin/python scripts/record-v4-provider-journeys.py
```
