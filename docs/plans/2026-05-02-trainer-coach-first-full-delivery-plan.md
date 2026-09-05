# Trainer Coach-First Full Delivery Plan

> Historical snapshot from the superseded three-view phase.
> Current Trainer IA lives in [docs/ui-contract.md](../ui-contract.md): `Coach / Plan / Resources / Training / Settings`.

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 把 Trainer 从“已经有教练雏形的侧边栏插件”彻底推进成一个长期代码教练插件，让它在 VS Code 里以 `对话 / 计划 / 设置` 三视图承载极简前台与强大后台能力。

**Architecture:** 以前台收束、后端教练编排、长期记忆与复习调度、真实代码库理解四条主线并行推进。前台始终只暴露自然聊天、长期计划和完整设置；研究、检索、诊断、复习、记忆、项目理解全部沉入每次发送背后的教练能力层，通过同一条消息流回流结果。

**Tech Stack:** VS Code Extension Host (TypeScript), React + Zustand webview, shared TS protocol/models, FastAPI sidecar, SQLite repository, planner/memory/provider/resource services.

---

## 1. This Plan Exists To Finish The Right Product

Trainer 的目标不是做成“功能丰富的 AI 仪表盘”，而是做成一个你会长期打开、长期信任、长期一起写代码的教练。

这个最终产品必须同时满足下面七件事：

1. 顶层只保留 `对话 / 计划 / 设置`。
2. `研究`不再是一级视图，而是教练后台能力。
3. 对话流默认像 GPT/Codex 一样自然，不像系统报告页。
4. 计划页默认只强调当前主线，不把用户淹没在计划术语里。
5. 设置页完整而克制，只保留大模型接入，不制造 embedding 心智。
6. 教练真正具备长期记忆、复习节奏、教学模式、项目理解、idea 引导和情绪支持。
7. 所有强能力都通过“每一次发送”的后台编排体现，而不是前台堆入口。

---

## 2. Current Baseline

### 2.1 Already Landed

- 顶层 IA 已基本稳定到 `对话 / 计划 / 设置`。
- 后端已具备 workspace 级语言、回答方式、coach defaults 持久化能力。
- 对话流已支持 markdown、代码块、表格、公式、mermaid / 思维导图渲染。
- 浏览器预览模式已支持最多 100 个文件和文件夹导入。
- 计划页、消息流、设置页已经完成一轮去噪和 compact 化。
- 记忆层已经有 active thread、recent wins、teaching observations、due reviews 等基础结构。
- 主要构建和测试链路已经能通过。

### 2.2 Still Missing

- 真正的“长期教练连续性”还不够强，跨轮次续接还不够像真人教练。
- 教练提示词仍然有少量系统字段感，还不够自然。
- 计划页虽然比之前好很多，但还没做到“一眼就知道现在该做什么”。
- 对话里的补充信息、附带上下文、工件折叠文案还不够高级。
- 设置页虽然更完整了，但还缺少更清晰的保存状态、工作区覆盖和错误反馈。
- 复习节奏只是有基础，不是真正的长期训练系统。
- 教学模式骨架存在，但还没完全专业化。
- 项目理解、idea 提炼、已完成项目改造指导能力还需要系统化落地。

---

## 3. Product Contract

这是后续所有实现都不能违反的产品契约。

### 3.1 Top-Level Contract

- 一级导航只能是 `对话 / 计划 / 设置`。
- 不能再把 `研究 / memory / review / resources / tasks` 做回一级 tab。
- 不能把消息流重新做成大卡片拼贴。
- 不能把“功能强”理解成“可见入口多”。

### 3.2 Chat Contract

- 默认回复必须像自然教练对话，不像模板化分析报告。
- 非必要信息必须折叠。
- 教练和用户消息必须一眼区分，但不能太重 UI。
- 长内容允许折叠，但摘要必须清楚，不能只写“展开全文”。

### 3.3 Plan Contract

- 默认只强调：
  - 我现在在哪
  - 现在先做什么
  - 为什么先做
  - 做完怎么验证
  - 后面再看什么
- 完整阶段、回看队列、背景信号都放入二级折叠层。

### 3.4 Settings Contract

- 只保留大模型 provider 心智。
- 支持 API key、base URL、model、连接测试、打开配置文件。
- 支持语言、回答风格、上下文附带策略、记忆范围、复习策略。
- 设置页可以完整，但必须 calm。

### 3.5 Coaching Contract

- Trainer 不只是回答代码问题，而是长期教练。
- 它必须具备：
  - idea 实现引导
  - 基于项目提炼训练题
  - 已完成项目改造指导
  - 原理讲解
  - 长期记忆
  - 复习节奏
  - 情绪支持

---

## 4. Final Definition Of Done

只有当下面这些都成立时，Trainer 才算真的达到目标：

1. 用户第一次打开时会自然理解“这是一个代码教练”。
2. 日常使用时，绝大多数行为都从 `对话` 进入。
3. `计划` 是长期训练中枢，而不是附属卡片。
4. `设置` 足够完整，用户不必跳出主流程才能完成接入与配置。
5. 教练能在连续多轮对话里稳定记住：
   - 当前目标
   - 当前主线
   - 上次验证结果
   - 当前卡点
   - 下一步
   - 近期复习点
   - 长期偏好
6. 教练能够从当前项目中提炼训练 idea，并持续带用户落地。
7. 教练能指导用户在已有项目上渐进改造，而不是只会从零解释。
8. 教练能讲原理、会安排复习、能给稳定的情绪价值，但不会变成空泛鼓励机器人。
9. 真机 VS Code 扩展链路和浏览器预览链路都稳定可用。

---

## 5. Execution Order

这份计划按“先修主链，再做能力升级，最后做系统收口”的顺序执行。

### Phase 0: Real Integration Stabilization

**Goal:** 确保当前 Trainer 在真实 VS Code 扩展场景里可稳定使用，而不是只在本地构建和预览里看起来可用。

**Why first:** 如果真实链路不稳，后面的高级能力很难被用户信任。

### Phase 1: Conversation Flow Finishing

**Goal:** 把聊天流彻底打磨成自然、清楚、低系统味的信息流。

### Phase 2: Plan View Rebuild

**Goal:** 把计划页做成真正的“当前训练主线执行视图”。

### Phase 3: Settings System Completion

**Goal:** 把设置页做成真正完整、可信、好用的侧栏系统面板。

### Phase 4: Memory 2.0

**Goal:** 把 Trainer 的长期记忆做成可持续续接的教练记忆，而不是几个松散摘要字段。

### Phase 5: Pedagogy And Teaching Modes

**Goal:** 把“会教”正式做成后端能力层。

### Phase 6: Review Rhythm And Spaced Practice

**Goal:** 把复习机制做成真正的长期训练引擎。

### Phase 7: Project Understanding And Idea Mining

**Goal:** 让 Trainer 基于真实项目给出训练机会、改造路径和实现引导。

### Phase 8: Deep Quality And Polish

**Goal:** 做完端到端验证、视觉精修、性能收口和回归护栏。

---

## 6. Workstream A: Real Integration Stabilization

### Task A1: Verify VS Code Extension End-To-End

**Files:**
- Modify: `/Users/Apple/Desktop/trainer/extension/src/commands/sessionCommands.ts`
- Modify: `/Users/Apple/Desktop/trainer/extension/src/core/webviewBridge.ts`
- Modify: `/Users/Apple/Desktop/trainer/extension/src/core/workbenchData.ts`
- Modify: `/Users/Apple/Desktop/trainer/server/app/api/routers.py`
- Test: `/Users/Apple/Desktop/trainer/server/tests/test_api.py`

**What this task must finish:**
- 真实扩展中侧栏打开、session 启动、消息发送、流式回复、刷新恢复、coach defaults 持久化全部跑通。
- 真实扩展与浏览器预览链路的行为差异被记录并最小化。

**Acceptance:**
- 真实 VS Code 中完成一轮：
  - 打开侧栏
  - 发送中文消息
  - 切到计划
  - 调整设置
  - 关闭再打开
  - 再发一轮未显式指定语言/模式的消息
- 语言与 answer mode 能正确续接。

### Task A2: File And Folder Resource Import Reliability

**Files:**
- Modify: `/Users/Apple/Desktop/trainer/extension/src/commands/resourceCommands.ts`
- Modify: `/Users/Apple/Desktop/trainer/extension/webview/src/app/App.tsx`
- Modify: `/Users/Apple/Desktop/trainer/extension/webview/src/lib/browserSidecar.ts`
- Test: `/Users/Apple/Desktop/trainer/server/tests/test_api.py`

**What this task must finish:**
- 最多 100 个文件、单文件夹导入、浏览器预览导入、导入失败提示、跳过不支持文件提示都清楚可用。
- 用户能明确知道“哪些东西被带上了”。

**Acceptance:**
- 支持文件导入成功。
- 文件夹导入成功。
- 超过 100 个文件时反馈清楚。
- 不支持文件被跳过时反馈清楚。

---

## 7. Workstream B: Conversation Flow Finishing

### Task B1: Make The Assistant Reply Feel Like Natural Chat

**Files:**
- Modify: `/Users/Apple/Desktop/trainer/extension/webview/src/components/coach/CoachMessageBubble.tsx`
- Modify: `/Users/Apple/Desktop/trainer/extension/webview/src/components/coach/MessageRichContent.tsx`
- Modify: `/Users/Apple/Desktop/trainer/extension/webview/src/styles.css`
- Modify: `/Users/Apple/Desktop/trainer/server/app/llm/prompts.py`
- Test: `/Users/Apple/Desktop/trainer/server/tests/test_provider_service.py`

**What this task must finish:**
- 教练回复默认像自然 prose。
- 工件和补充信息默认折叠。
- 折叠摘要必须是“人话”，不是系统标签。
- 后端 prompt 保持足够上下文，但不再重复罗列字段。

**Acceptance:**
- 中文输入时，中文回复自然稳定。
- 长回复默认可读，不需要先懂系统术语。
- 结构化内容仍然支持代码块、表格、公式、mermaid。

### Task B2: Clarify What Was Used For This Reply

**Files:**
- Modify: `/Users/Apple/Desktop/trainer/extension/webview/src/components/coach/CoachMessageBubble.tsx`
- Modify: `/Users/Apple/Desktop/trainer/extension/webview/src/app/App.tsx`
- Modify: `/Users/Apple/Desktop/trainer/extension/webview/src/styles.css`

**What this task must finish:**
- 用户能轻松理解这条回复参考了什么。
- 当前文件、选区、诊断、相关文件、资源不需要大面板解释，但需要轻量可读的反馈。

**Acceptance:**
- 发送前后都能明白本轮上下文来源。
- 不显得像“发送分析面板”。

---

## 8. Workstream C: Plan View Rebuild

### Task C1: Rebuild The Plan View Around One Visible Mainline

**Files:**
- Modify: `/Users/Apple/Desktop/trainer/extension/webview/src/components/plan/CoachPlanView.tsx`
- Modify: `/Users/Apple/Desktop/trainer/extension/webview/src/styles.css`
- Modify: `/Users/Apple/Desktop/trainer/extension/webview/src/lib/types.ts`

**What this task must finish:**
- 计划页默认只呈现一条主线。
- “当前阶段 / 现在做什么 / 为什么 / 如何验证 / 后面再做什么”五件事必须高度清楚。
- 阶段列表、复习队列、辅助上下文进入折叠层。

**Acceptance:**
- 新用户第一次看到计划页时，不需要学习额外术语就知道现在要做什么。
- 页面默认不拥挤、不像仪表盘。

### Task C2: Connect Plan With Real Training State

**Files:**
- Modify: `/Users/Apple/Desktop/trainer/server/app/planner/service.py`
- Modify: `/Users/Apple/Desktop/trainer/server/app/api/routers.py`
- Modify: `/Users/Apple/Desktop/trainer/extension/src/core/workbenchData.ts`
- Test: `/Users/Apple/Desktop/trainer/server/tests/test_planner.py`
- Test: `/Users/Apple/Desktop/trainer/server/tests/test_api.py`

**What this task must finish:**
- 计划不只是静态 plan summary。
- 当前阶段、当前主线、回看点、教练判断、下一次训练动作都能稳定进入计划视图。

**Acceptance:**
- 计划页能真实反映当前训练状态，而不是只显示历史结构。

---

## 9. Workstream D: Settings System Completion

### Task D1: Complete The Provider And Runtime Settings Panel

**Files:**
- Modify: `/Users/Apple/Desktop/trainer/extension/webview/src/components/settings/CoachSettingsView.tsx`
- Modify: `/Users/Apple/Desktop/trainer/extension/webview/src/styles.css`
- Modify: `/Users/Apple/Desktop/trainer/extension/src/provider/providerConfigStore.ts`
- Modify: `/Users/Apple/Desktop/trainer/server/app/api/routers.py`
- Test: `/Users/Apple/Desktop/trainer/server/tests/test_api.py`

**What this task must finish:**
- provider 名称、base URL、model、API key、保存、测试、清空、打开配置文件都清楚可用。
- 增加保存状态、失败原因、当前工作区有效状态的表达。
- 明确只保留大模型配置，不做 embedding 心智。

**Acceptance:**
- 用户能独立完成 provider 接入与检查。
- 出错时能知道为什么错。

### Task D2: Complete Coach Defaults And Workspace Control

**Files:**
- Modify: `/Users/Apple/Desktop/trainer/extension/webview/src/components/settings/CoachSettingsView.tsx`
- Modify: `/Users/Apple/Desktop/trainer/extension/webview/src/app/App.tsx`
- Modify: `/Users/Apple/Desktop/trainer/server/app/core/models.py`
- Modify: `/Users/Apple/Desktop/trainer/server/app/api/routers.py`
- Test: `/Users/Apple/Desktop/trainer/server/tests/test_api.py`

**What this task must finish:**
- 语言、中英切换、回答方式、记忆范围、工作集范围、上下文附带策略、复习节奏设置都稳定可保存。
- 工作区级设置在刷新后仍正确生效。

**Acceptance:**
- 设置保存后，后续未显式指定的 turn 会使用保存值。

---

## 10. Workstream E: Memory 2.0

### Task E1: Strengthen Thread Continuity Memory

**Files:**
- Modify: `/Users/Apple/Desktop/trainer/server/app/memory/service.py`
- Modify: `/Users/Apple/Desktop/trainer/server/app/memory/models.py`
- Modify: `/Users/Apple/Desktop/trainer/server/app/db/repository.py`
- Test: `/Users/Apple/Desktop/trainer/server/tests/test_memory.py`

**What this task must finish:**
- active thread 不只是一个摘要，而是一条真实主线。
- 必须稳定记住：
  - 上次已验证结果
  - 当前卡点
  - 下一步
  - 当前 focus area
  - 可迁移教学信号

**Acceptance:**
- 连续多轮对话中，教练默认会续上同一主线。
- memory evidence 优先给出最能帮助续接的信息。

### Task E2: Add Long-Term Learner Memory

**Files:**
- Modify: `/Users/Apple/Desktop/trainer/server/app/memory/service.py`
- Modify: `/Users/Apple/Desktop/trainer/server/app/core/models.py`
- Test: `/Users/Apple/Desktop/trainer/server/tests/test_memory.py`

**What this task must finish:**
- 记录并召回：
  - 长期目标
  - 偏好教学方式
  - 高频卡点
  - 稳定错误模式
  - 跨项目可迁移习惯

**Acceptance:**
- personal memory 模式下，跨项目仍能保留合理的教练连续性。

---

## 11. Workstream F: Pedagogy And Teaching Modes

### Task F1: Add A Real Pedagogy Decision Layer

**Files:**
- Create: `/Users/Apple/Desktop/trainer/server/app/pedagogy/service.py`
- Create: `/Users/Apple/Desktop/trainer/server/app/pedagogy/models.py`
- Modify: `/Users/Apple/Desktop/trainer/server/app/api/routers.py`
- Modify: `/Users/Apple/Desktop/trainer/server/app/llm/provider_service.py`
- Test: `/Users/Apple/Desktop/trainer/server/tests/test_pedagogy.py`

**What this task must finish:**
- 每次 turn 先判断当前最适合的教学模式。
- 至少支持：
  - idea_implementation
  - project_idea_mining
  - project_adaptation
  - planning
  - concept_teaching
  - engineering_challenge
  - review_reflection
  - principle_explanation

**Acceptance:**
- 相同输入在不同上下文下会得到不同教学策略，而不是只有一种固定答法。

### Task F2: Make Idea Implementation Coaching The Primary Mode

**Files:**
- Create: `/Users/Apple/Desktop/trainer/server/app/pedagogy/implementation_coach.py`
- Modify: `/Users/Apple/Desktop/trainer/server/app/llm/prompts.py`
- Modify: `/Users/Apple/Desktop/trainer/server/app/api/routers.py`
- Test: `/Users/Apple/Desktop/trainer/server/tests/test_pedagogy.py`

**What this task must finish:**
- 当用户提出一个 idea 时，教练自动把它压成：
  - 最小可实现版本
  - 当前第一刀
  - 为什么先做它
  - 如何验证
  - 下一步

**Acceptance:**
- Trainer 不再只是解释 idea，而是持续带用户把 idea 落成代码。

### Task F3: Add Principle Explanation And Emotional Support

**Files:**
- Create: `/Users/Apple/Desktop/trainer/server/app/pedagogy/principle_explainer.py`
- Create: `/Users/Apple/Desktop/trainer/server/app/affect/service.py`
- Modify: `/Users/Apple/Desktop/trainer/server/app/llm/provider_service.py`
- Test: `/Users/Apple/Desktop/trainer/server/tests/test_provider_service.py`

**What this task must finish:**
- 教练能在需要时解释原理、常见误区、迁移场景。
- 教练能根据 learner signal、frustration、confidence 调整语气和节奏。
- 情绪支持必须克制、可信、不过度夸张。

**Acceptance:**
- 被卡住时得到的不是泛泛鼓励，而是更稳、更小、更适合当前状态的引导。

---

## 12. Workstream G: Review Rhythm And Spaced Practice

### Task G1: Build A Real Review Scheduler

**Files:**
- Create: `/Users/Apple/Desktop/trainer/server/app/memory/review_scheduler.py`
- Modify: `/Users/Apple/Desktop/trainer/server/app/memory/service.py`
- Modify: `/Users/Apple/Desktop/trainer/server/app/planner/service.py`
- Test: `/Users/Apple/Desktop/trainer/server/tests/test_review_scheduler.py`

**What this task must finish:**
- 不再只是简单 due review 列表。
- 至少支持：
  - 到期提醒
  - 提前提醒
  - digest 合并
  - 与真实代码任务绑定
  - 按掌握度调节节奏

**Acceptance:**
- 复习点不会只是静态摘要，而会真实进入下一轮训练决策。

### Task G2: Bring Spaced Practice Into The Plan And Chat Loop

**Files:**
- Modify: `/Users/Apple/Desktop/trainer/server/app/api/routers.py`
- Modify: `/Users/Apple/Desktop/trainer/extension/src/core/workbenchData.ts`
- Modify: `/Users/Apple/Desktop/trainer/extension/webview/src/components/plan/CoachPlanView.tsx`
- Test: `/Users/Apple/Desktop/trainer/server/tests/test_api.py`

**What this task must finish:**
- 复习节奏和待回看点要稳定进入：
  - 教练回复上下文
  - 计划页折叠层
  - 后续下一题推荐

**Acceptance:**
- 用户能感受到教练在安排长期训练，而不是只回答当前一次问题。

---

## 13. Workstream H: Project Understanding And Idea Mining

### Task H1: Mine Training Opportunities From The Current Project

**Files:**
- Create: `/Users/Apple/Desktop/trainer/server/app/pedagogy/project_idea_miner.py`
- Modify: `/Users/Apple/Desktop/trainer/server/app/api/routers.py`
- Modify: `/Users/Apple/Desktop/trainer/server/app/llm/prompts.py`
- Test: `/Users/Apple/Desktop/trainer/server/tests/test_pedagogy.py`

**What this task must finish:**
- 教练能基于当前项目主动提炼：
  - 新功能 idea
  - 重构机会
  - 工程题
  - 边界条件练习
  - 测试补强机会

**Acceptance:**
- 用户可以直接说“基于当前项目给我出题”。

### Task H2: Add Completed Project Adaptation Guidance

**Files:**
- Create: `/Users/Apple/Desktop/trainer/server/app/pedagogy/project_adaptation_coach.py`
- Modify: `/Users/Apple/Desktop/trainer/server/app/api/routers.py`
- Modify: `/Users/Apple/Desktop/trainer/server/app/llm/prompts.py`
- Test: `/Users/Apple/Desktop/trainer/server/tests/test_project_adaptation.py`

**What this task must finish:**
- 用户面对一个已有项目时，教练能按用户目标给出改造路径。
- 输出必须强调：
  - 目标变化
  - 受影响边界
  - 先改哪里
  - 哪些地方先别动
  - 如何验证不把原项目改坏

**Acceptance:**
- Trainer 能带用户改造现有项目，而不只是说“可以改这里”。

### Task H3: Add Project Sourcing As A Background Ability

**Files:**
- Create: `/Users/Apple/Desktop/trainer/server/app/pedagogy/project_source_scout.py`
- Modify: `/Users/Apple/Desktop/trainer/server/app/api/routers.py`
- Test: `/Users/Apple/Desktop/trainer/server/tests/test_pedagogy.py`

**What this task must finish:**
- 当当前仓库不适合某个训练目标时，教练可以在后台给出公开项目或参考实现建议。
- 这仍然必须通过教练消息流表达，而不是独立页面。

**Acceptance:**
- 用户可以让教练帮忙找适合训练的项目来源。

---

## 14. Workstream I: Deep Quality And Polish

### Task I1: Unify Typography, Density, And Interaction Baseline

**Files:**
- Modify: `/Users/Apple/Desktop/trainer/extension/webview/src/styles.css`
- Modify: `/Users/Apple/Desktop/trainer/extension/webview/src/app/App.tsx`
- Modify: `/Users/Apple/Desktop/trainer/extension/webview/src/components/**`

**What this task must finish:**
- 全局字体渲染、字号层级、边距、图标基线、输入区密度统一。
- 避免出现一处细腻、一处粗糙的割裂感。

**Acceptance:**
- 侧栏整体像一个成熟插件，而不是多个阶段产物拼起来的页面。

### Task I2: Add End-To-End Regression Gates

**Files:**
- Modify: `/Users/Apple/Desktop/trainer/server/tests/test_api.py`
- Modify: `/Users/Apple/Desktop/trainer/server/tests/test_provider_service.py`
- Modify: `/Users/Apple/Desktop/trainer/server/tests/test_memory.py`
- Modify: `/Users/Apple/Desktop/trainer/server/tests/test_planner.py`

**What this task must finish:**
- 为关键 coach-first 行为补齐回归测试：
  - saved defaults 生效
  - 中文回复续接
  - active thread continuity
  - plan state continuity
  - review rhythm integration
  - idea/adaptation/principle modes

**Acceptance:**
- 关键训练能力后续重构时不容易被悄悄打坏。

---

## 15. Verification Matrix

在每个阶段结束后，至少运行这些命令：

```bash
server/.venv-mac/bin/python -m pytest /Users/Apple/Desktop/trainer/server/tests/test_api.py -q
server/.venv-mac/bin/python -m pytest /Users/Apple/Desktop/trainer/server/tests/test_memory.py -q
server/.venv-mac/bin/python -m pytest /Users/Apple/Desktop/trainer/server/tests/test_provider_service.py -q
npm run check --prefix /Users/Apple/Desktop/trainer/extension/webview
npm run build --prefix /Users/Apple/Desktop/trainer/extension/webview
npm run build --prefix /Users/Apple/Desktop/trainer/extension
```

在关键 UI 阶段结束后，还要补充真实操作验证：

1. 打开 VS Code 侧栏。
2. 用中文发起一轮 idea 实现请求。
3. 刷新后继续下一轮，不显式指定语言与模式。
4. 切到计划页，确认当前主线与下一步清楚可见。
5. 切到设置页，修改 provider 或默认设置并保存。
6. 导入文件与文件夹，确认状态反馈清楚。

---

## 16. Recommended Delivery Sequence

如果要按最稳的顺序持续推进，我建议是：

1. `A1 + A2`
2. `B1 + B2`
3. `C1 + C2`
4. `D1 + D2`
5. `E1 + E2`
6. `F1 + F2 + F3`
7. `G1 + G2`
8. `H1 + H2 + H3`
9. `I1 + I2`

这个顺序的好处是：

- 先把真实主链路修稳。
- 再把前台理解成本压低。
- 然后强化长期记忆与教学能力。
- 最后再做更复杂的项目理解与系统精修。

---

## 17. What The Finished Trainer Should Feel Like

最终的 Trainer 不应该让人感觉“这里面藏了很多 AI 功能”，而应该让人感觉：

- 我在和一个很懂代码、也很懂教学的教练对话。
- 它知道我正在做什么，也记得我前面做过什么。
- 它不会把我淹没在系统结构里。
- 它能贴着当前项目，带我把想法一步步做成代码。
- 它能在我卡住时稳住节奏，在我进步时给出更高质量的下一步。
- 它像 Codex 一样克制、自然、专业，但比普通聊天助手更像长期训练伙伴。

