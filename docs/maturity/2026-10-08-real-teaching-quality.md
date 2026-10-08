# 真实模型教学质量人工审阅

开始：2026-10-08；更新：2026-10-09（Asia/Shanghai）。状态：**in progress；上游额度阻塞，28 个教学旅程未验收通过**。

本报告只审阅已经落盘的实际回复，不把 HTTP 200、`completed`、连接测试成功或脚本断言通过直接算成教学质量通过。审阅时产品源码基线为 `fddbe75e85acb452db010ebf09ec49fd9882b612` 加未提交的成熟化修复；它不是一个已发布的干净提交。后续修复与本次采样必须分别记录。

## 证据范围与限制

- 最终有效 harness 目录：`output/maturity/real-teaching-journeys-1791474902877`。脚本：`output/maturity/real-teaching-journeys.py`；运行日志：`output/maturity/real-teaching-journeys-paced-final.log`。
- 使用实际 OpenRouter `openai/gpt-4o` 与真实 Sidecar。learner 消息和修改后的代码由脚本预先准备；Python/Node/SQLite 示例在隔离项目真实执行。它们可验证教学响应是否贴合输入，不能证明真人学习效果。
- 每次请求前磁盘文件与 `current_file.content` 使用同一份源码。旧 `1791474826937` 存在第一回合 body/disk 不一致，属于 **harness-invalid**；旧案例、报错和原回复保留，但不计教学通过。更早并发运行受限流，不拼接成完整通过结果。
- 运行是单并发、回合间隔 12 秒，已在第 4 案例后停止。落盘 4 个完整双回合 report，共 8 个回合：**3 个真实模型完成回复，5 个 `provider_error` / `fell_back=true`**。计划中的其余 24 案例未在最终有效运行完成。
- 4 个案例实际执行均为修改前 exit 1、预置修改后 exit 0；恢复均 HTTP 200、相同 session、4 条消息。这证明运行和恢复链路，不能代替教师质量，也不构成 VS Code host attestation。
- Root 只读核验得到当前提供者 HTTP 402，账户 `total_credits=0`。key 的 100 使用上限不是余额；不要将 HTTP 200 的本地兜底计成实际 GPT-4o 输出。本文不保存 API key、私人端点、账户标识或原始上游响应正文。

## 人工判定规则

每回合一起读 `reply.content`、`agent_meta.steps`、`coach_turn.next_step`、`memory` 与 `learner_state`，以用户实际看到的最终回复为主。raw steps 用来定位改写，不替代最终产品输出。

| 维度 | 通过条件 |
| --- | --- |
| 事实准确 | 因果、代码行为和边界正确；不能用正确修复掩盖错误解释 |
| 难度适配 | 新手获得可观察的小实验；熟练用户获得直接、短而精确的判断 |
| direct / guided 尊重 | 回答当前问题，不强行生成任务、计划或长入门课；保留用户亲自实现 |
| 下一步一致 | 正文、结构化下一步和当前问题对齐，不能重复索要已经给出的错误或要求不存在的函数 |
| 记忆与证据 | 持续保留技术主题；不把消息前缀当能力，不把自述或一次断言通过当 verified mastery |

`pass` 表示该维度满足；`concern` 表示有可用内容但存在影响学习的限制；`fail` 表示明确错误、缺失关键交付或请求未获得模型教学。完整旅程要求两个回合和下一步/记忆均合格。外部额度导致的 fail 与模型教学内容错误分别标注。

## 最终有效运行：逐案审阅

| 案例 | 第 1 / 第 2 回合 | 事实与难度 | 下一步与记忆 | 总判定 |
| --- | --- | --- | --- | --- |
| 01 mutable-default，新手 | fallback / fallback | 未获得默认参数创建时机解释或模型复盘；不能评价模型教学准确度 | 泛化为文件名/AssertionError；第 2 回合主题变成消息前缀 | **fail：外部额度 + recovery 缺少教学交付** |
| 02 late-binding，新手 | fallback / fallback | 未获得闭包调用时机解释或模型复盘 | 与 01 几乎相同的泛化下一步；没有保留闭包主题 | **fail：外部额度 + recovery 缺少教学交付** |
| 03 nested-alias，新手 | completed / completed | 核心引用解释、`is` 实验和列表推导式修复正确；篇幅偏长，第 2 回合的“反例”只重放原失败例，缺少新的覆盖边界 | 两回合结构化下一步均要求函数名/call site，实际源码是顶层列表；主题漂移到消息前缀 | **fail：下一步/记忆；正文事实主体 pass，边界与篇幅 concern** |
| 04 binary-search-boundary，有基础 | completed / fallback | 第 1 回合正确建议闭区间 `hi=len(xs)-1`，但循环轨迹解释错误；第 2 回合未获得模型复盘 | 结构化下一步再次索要已提供的报错；记忆未保留闭区间语义 | **fail：事实错误 + 下一步；第 2 回合外部额度** |

### 01 / 02：兜底与实际问题脱节

初始请求明确给出实际 AssertionError，分别要求默认参数创建时机和闭包调用时机。可见回复却再次要求“带回第一条实际输出或报错”。第二回合要求检查已经真实通过的修改和未覆盖边界，兜底则把“我亲自写了下面的修改”当成要讲解的主题。

两回合 `agent_meta.steps=[]`，因此没有可评为通过的实际模型内容。`memory.coach_anchor` 从 `lesson.py` 变成消息前缀，`current_focus` 同样丢失了技术概念。恢复相同 session 成功，并不意味着恢复的教学主题正确。

### 03：正确解释没有成为正确的下一步

第一回合 raw step 与可见正文一致：重复的是内层列表引用，修改后两行都是 `[1, 0]`，`grid[0] is grid[1]` 为 True。实验能让新手观察原因；列表推导式创建独立行的修复与实际 exit 0 相符。一个措辞不精确之处是正文把外层 `[[0] * 2]` 描述成含两个元素的 `[0, 0]`，应区分内外层列表。

第二回合正确说明独立内层列表为何通过，明确一次通过只是开始，没有宣称掌握。但“没覆盖的反例”仍是原来的重复引用写法；可以进一步检查第三层可变对象或外部传入对象，才能回答新的覆盖边界。

产品交付的主要缺陷是 `coach_turn.next_step` 两回合都要求“给我函数名”。源码没有函数，正文也没有产生这个要求。它随后进入 `memory.current_focus`、review task hint；第二回合 `coach_anchor` 与 `lowest_mastery_concepts` 出现消息前缀。于是用户面对的是一篇对的解释和一个无关的下一步。

### 04：修复建议正确，教学事实错误

可见回复称“当 lo 大于 hi 时，循环条件 lo <= hi 仍然成立”。这与条件本身矛盾。原例 `find([1], 2)` 的真实轨迹是：

| 循环 | lo | hi | mid | 结果 |
| --- | --- | --- | --- | --- |
| 1 | 0 | 1 | 0 | `xs[0] < 2`，令 lo=1 |
| 2 | 1 | 1 | 1 | 条件成立，但访问 `xs[1]` 越界 |

因此错误来自闭区间上界初始化为长度，越界发生时 lo 与 hi 相等。建议 `hi=len(xs)-1` 是对的，但不能用修复能通过来判解释通过。raw step 也包含同一错误，说明不是最终改写单独造成。结构化下一步仍要求带回已经给出的错误，没有转成用户所请求的区间/反例实验。

## 已完成的单回合 pilot

这些是独立小样本，不是 28 个教学旅程的替代验收。多个实际 GPT-4o 回复正确讲解了可变默认参数；也存在事实错误与下一步泛化。

| 原始目录 | 模型/链路证据 | 人工审阅 |
| --- | --- | --- |
| `real-pilot-1791472160081` | provider probe 拒绝访问，fallback；不是 GPT-4o 成功样本 | **fail：访问阻塞，不计模型质量** |
| `real-pilot-1791473289249` | GPT-4o probe connected，非 agent-loop 的实际可见回复 | **concern**：默认对象在定义时创建、跨调用复用及打印实验正确；下一步泛化为参数/返回值契约 |
| `real-pilot-1791473889066` | GPT-4o probe connected，非 agent-loop 的实际可见回复 | **concern**：共享列表因果、最小实验与 None 修复正确；结构化下一步只是通用 code review 规则 |
| `real-pilot-1791473998899` | GPT-4o，agent `completed` / `fell_back=false`，1 个真实 step | **concern**：定义时创建解释正确，没有直接改文件；结构化下一步切成英文且没有绑定当前实验 |
| `real-pilot-1791474104767` | GPT-4o probe connected，非 agent-loop 的实际可见回复 | **fail：事实错误**，称默认列表第一次调用时创建；正确输出/修复不能补偿创建时机误教 |

在本地定义函数但尚未调用时，`__defaults__` 已含空列表，直接证明最后一条 pilot 的创建时机解释错误。由于 pilot 没有两回合学习/恢复/证据过程，不能宣称 learner 已掌握或长期记忆已可靠。

## 实际随机图像语义检查

`output/maturity/real-vision-diagnostics.json` 保存三张实际图片请求的可见响应；三个响应的 JSON 值分别与期望 `80/84/36`、`23/15/23`、`12/90/93` 完全一致。它们证明这三个图片数字识别样本的语义正确，不证明所有视觉教学能力。

旧诊断记录仍保留 `match=false` / `outcome=visible_text`：实际响应带 Markdown JSON fence，原解析器没有识别它。Root 已修复 fence 解析。实际请求后的完整脱敏 probe 保存在 `output/maturity/real-pilot-1791474104767/probe.json`，字段 `$.body.vision_ready=true`、`$.body.vision_probe_status="verified"`，人工复核一致。它证明这次真实视觉探测通过；同目录 `turn.json` 的默认参数创建时机解释仍判事实错误，两项不混算。不能把手填 `capabilities.vision=true` 或旧 probe 返回该旗标当成实际视觉执行证据，也不能抹去旧解析失败记录。

## 证据诚实与后续验收

已审阅的 8 个回合 `learning_outcomes`、`recent_flash_attempts` 和 `training_event_ledger` 均为空。可见回复未声称获得 host-trusted 验证或 verified mastery。观察到的 `current_confidence` 是 learner-state 推断，不能当能力分数。`lowest_mastery_concepts` 收入文件名/消息前缀，以及“真实训练过程”泛化措辞，需要按概念身份和证据来源核查；本次不能据此断言跨工作区污染。

Root 接管 relevance/recovery 与 typed quota 分类修复。原始报告只读保留；单元测试修复可以证明局部行为，不能代替真实模型复测。额度恢复后，必须使用 body/disk 一致的最终 harness 重新运行至少失败案例，再完成全部 28 个双回合案例，并单独覆盖 direct expert、跨语言迁移、review、一次通过不算 mastery 等尚未在最终运行完成的维度。继续检查最终正文、主下一步与记忆主题一致，不能只读 raw step 或 HTTP 状态。

**当前结论：真实模型接通和三个数字视觉样本已发生；28 个教学旅程没有通过质量验收。4 个最终有效案例已人工审阅，0 个完整旅程判 pass。剩余 24 个维持未验收；上游额度是继续真实模型检查的外部阻塞。**
