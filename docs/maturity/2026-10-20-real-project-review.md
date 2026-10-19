# 非固定真实项目教学样本 — 两回合原始回复与独立审阅

> **审阅者声明**：本记录由独立 AI agent 审阅，**不是真人审阅**。按任务书
> §7.2 “不得将独立 Agent 评价自动记作真人审阅”，owner/人工签核仍为
> **Pending**。本文件只提供可复核的原始回复、测量与审阅意见。

## 1. 样本与请求

- 项目：本仓库 `AI-yyf/trainer`（非固定夹具，真实文件）
- 文件：`server/app/network_fetch.py`
- 附件：只含连接段（`_ResolvedAddress` / `_ResolvedTarget` /
  `_connect_verified` / `_remaining_timeout`），**57 行 / 2,158 字符**，
  SHA-256 `b12d0be223cf23e667d8583ec4892b640db0e3882763d68849c4150a936eaef2`
  （与 raw JSON 的 `request.current_file_sha256` 一致）。
  这样避开测试中转对长上下文的截断；前两次全文件探针只得到 intake 模板，
  已不作为教学样本。
- 模型：`minimax-m3` 与 `glm-5.3`（OpenAI 兼容中转 `https://linksub.fun`）
- 模式：`guided`，`zh-CN`，两回合同一 session。

### 回合 1

> 附件是 trainer 项目 network_fetch.py 的连接段（当前实现）。在 IPv6 不可达的
> 机器上，旧实现会超时；现在改成了 IPv4 优先、每次 connect 有 5s 上限。请按
> 教练方式引用真实的函数/常量，解释这个修复为什么有效、在什么情况下仍会失败；
> 只给我一个最小验证动作，不要直接给完整改法。

### 回合 2

> 我按你说的最小动作验证了 IPv4 能连通。现在想补回归测试：请基于同一段代码，
> 告诉我最小测试切入点和你希望断言的可观察行为，不要写完整测试代码。

## 2. 原始产物

| 模型 | 原始响应 | 回合 1 | 回合 2 |
| --- | --- | --- | --- |
| `minimax-m3` | [`2026-10-20-real-project-probe-minimax-m3.json`](2026-10-20-real-project-probe-minimax-m3.json) | 2,535 chars / **508.73s** | 803 chars / 3.91s |
| `glm-5.3` | [`2026-10-20-real-project-probe-glm-5.3.json`](2026-10-20-real-project-probe-glm-5.3.json) | 1,496 chars / **398.43s** | 1,348 chars / 35.48s |

两份 JSON 保存了完整 HTTP 响应（含 `coach_turn`、`agent_meta`、`snapshot`），
API key 已脱敏；`grep sk-` 为 0。

## 3. 审阅意见（独立 AI agent）

| 维度 | minimax-m3 | glm-5.3 | 说明 |
| --- | --- | --- | --- |
| 技术解释正确 | **pass** | **pass** | 正确说明 AAAA 优先 + `connect()` 阻塞耗尽 deadline，以及 `_connect_verified` 的排序 + 单次 5s 上限 |
| 真正回答问题 | **pass** | **pass** | 两回合都围绕“为什么有效 / 何时仍失败 / 如何测” |
| 教学深度适配 | **pass** | **pass** | guided 模式下解释机制并留出下一步，没有直接重写实现 |
| 是否泄露完整答案 | **pass** | **partial** | GLM 回合 2 含一个约 5 行的 `class FakeSocket` 片段；不是完整测试，但接近边界 |
| 下一步可执行 | **pass（正文）** | **pass（正文）** | 正文给出可执行验证；“结构化 next_step”见 §4 |
| 引用正确文件/符号 | **pass** | **pass** | `network_fetch.py`、`_connect_verified`、`_remaining_timeout`、`_ResolvedTarget`、`getaddrinfo`、`socket.connect` 均真实存在 |
| Direct 模式 | N/A | N/A | 本次为 guided |
| 过度教学 | 轻微 | 轻微 | 回合 1 偏长（2.5k / 1.5k 字符），但仍在讲解范围 |
| 多回合连续性 | **pass** | **pass** | 回合 2 直接沿用回合 1 的连接顺序/假 socket 切入点 |
| 能力迁移 | **partial** | **pass** | GLM 的“反转排序让测试变红”能证明测试有效 |

### 关键原文摘录

`minimax-m3`（回合 1）：

> `getaddrinfo` 在很多机器上确实把 AAAA 排在前面，而 `socket.connect()` 会一直
> 阻塞到底层握手超时……结果就是 IPv6 这条死路把整个 deadline “吃”光……
> 核心改动落在 `_connect_verified` 这一个循环里……

`glm-5.3`（回合 2）：

> 你现在缺的不是新的实现，而是一个能“看见尝试顺序”的观测点：
> `_connect_verified` 对外只返回一个 socket 或抛 `ControlledFetchError`……
> 最小切入点不是去真连网络，而是把 `socket.socket` 替换成可控的假对象……

## 4. 发现的问题

1. **结构化 next_step 与正文不一致**：两份响应里的
   `coach_turn.next_step` 都是泛化句（“先说清规则…” / “先在 network_fetch.py
   里改一个小点…”），而正文给出了具体的验证/测试动作。若 UI 只显示结构化
   字段，用户会看到较弱的一步。**这是教学呈现缺口**，不是崩溃。
   `agent_meta.grounding_outcome` 缺失符合“clean grounded reply 保持
   agent_meta 精简”的约定，不等于接地失败。
2. **延迟**：`minimax-m3` 回合 1 508.73s，超过 `coachTurnRequestTimeoutMs`
   (480s)；扩展在该模型上会先超时。`glm-5.3` 398.43s 在预算内，但 6.6 分钟
   仍然很慢。回合 2 很快（3.9s / 35.5s）。这是模型/中转性能，不是发送链路
   逻辑错误；产品已用流式与 480s 上限兜底。
3. 全文件版本（前两次探针）在中转上返回空/截断，产品落到 intake 模板；
   这说明“完整文件 + 长 system prompt”会触发中转限制，不能作为教学质量证据。
   本次 57 行连接段是可用样本。

## 5. 结论

- **非固定真实项目样本的内容质量：独立审阅通过（附 §4 两项 caveat）。**
- **真人签核：Pending。**
- 不得把本记录当作 §7.2 的“人工审阅已完成”。固定 64/64 矩阵与本样本是
  两类证据；本样本证明了真实项目文件上的解释/下一步可用，但不能替代
  人工对教学深度与迁移的判断。
