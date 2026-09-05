# Trainer Coach-First Task Packages Implementation Plan

> Historical snapshot from the superseded three-view phase.
> Current Trainer IA lives in [docs/ui-contract.md](../ui-contract.md): `Coach / Plan / Resources / Training / Settings`.

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 把 Trainer 理想蓝图继续下压成一组“AI 可直接执行”的任务包。每个任务包都要具备独立目标、固定读物、严格写入范围、明确禁区、细化交付物、可执行验收命令和统一交接格式，保证多个 AI/多个回合可以低摩擦协作，最终把 `Coach-first` 代码教练真正做出来。

**Architecture:** 先建立并行基础，再让前端视图、后端纯服务、集成总线分别演化。前端通过 shell 拆解和样式分层获得互不冲突的 write scope；后端通过 pedagogy / implementation / idea mining / adaptation / principle / review / source 等独立服务文件实现高并行；最终由 provider、router、bridge、mock data 这四个集成点完成收束。

**Tech Stack:** VS Code Extension Host (TypeScript), React + Zustand webview, FastAPI + Pydantic sidecar, SQLite repository, planner/memory/research/resource/provider services.

---

## 1. 这份任务包总册怎么用

这份文档不是普通计划，而是一份可以直接分发给 AI worker 的执行手册。

每个任务包都包含：

- `Package ID`
- `Mission`
- `Product Promise`
- `Read First`
- `Allowed Write Scope`
- `Forbidden / Do Not Touch`
- `Dependencies`
- `Inputs Expected From Upstream`
- `Implementation Checklist`
- `Acceptance`
- `Common Failure Modes`
- `Handoff Contract`
- `Suggested Commit`

如果严格按这份文档执行，多个任务包之间应该基本可以独立推进，不会频繁互相打架。

---

## 2. 产品目标和任务包之间的映射

理想 Trainer 的最终目标不是“功能多”，而是下面这些能力都成立：

1. 前台只有 `对话 / 计划 / 设置`。
2. 强功能体现在每次发送背后的理解与编排，而不是一堆显式开关。
3. 教练能持续带你把 idea 做成代码。
4. 教练能从当前项目里主动提炼训练机会。
5. 教练能指导你改造一个已经存在的项目。
6. 教练能解释改动背后的原理与权衡。
7. 教练有长期记忆、复习调度和语气调节，但这些都沉到底层。
8. 整体界面安静、极简、专业、Codex-like，而不是 AI dashboard。

本总册中的任务包，就是围绕这八个目标倒推出的。

---

## 3. 全局硬约束

### 3.1 产品硬约束

- 不允许重新把 `research` 做回一级主入口。
- 不允许把强能力重新拆成一堆显式 tab 或 toggle。
- 不允许让 `Plan` 退回成附属卡片。
- 不允许把 embedding 模型暴露成前台必填项。
- 不允许把“强制专注 / 强制退出限制”当作当前主线目标。

### 3.2 前端设计硬约束

- 视觉必须克制、工具化、低装饰。
- 所有字体层级整体偏小，消息流与输入区更紧凑。
- 用户消息与教练消息必须一眼区分。
- 结果块必须是消息流二级层，不能做成大面板矩阵。
- 发送左侧高频常驻图标最多 3 个。
- 真图标，不用字母缩写伪装图标。
- 不允许在组件里硬编码颜色，必须使用 token。
- Plan 更结构化，但不能更花。
- Settings 更系统化，但不能像后台表单页。

### 3.3 协作硬约束

- 每个任务包只能修改自己的 `Allowed Write Scope`。
- 如果发现必须修改其他任务包的文件，必须停止并上报为 integration 需求。
- 不允许顺手做超出任务包范围的“附加优化”。
- 所有任务完成后必须按统一格式回传。

---

## 4. 建议执行波次

### Wave A: 打地基

- `TP-00` Webview shell split
- `TP-01` CSS layer split
- `TP-02` Shared contract stabilization
- `TP-03` Review persistence

### Wave B: 并行生长

前端并行：

- `TP-10` Coach message system
- `TP-11` Composer system
- `TP-12` Plan system
- `TP-13` Settings system

后端并行：

- `TP-20` Pedagogy decision engine
- `TP-21` Implementation coach
- `TP-22` Project idea miner
- `TP-23` Project adaptation coach
- `TP-24` Principle explainer
- `TP-25` Review scheduler
- `TP-26` Project source scout

### Wave C: 集成收束

- `TP-30` Provider and prompt integration
- `TP-31` Router orchestration integration
- `TP-32` Extension bridge and bootstrap integration

### Wave D: 成品收尾

- `TP-40` Visual system polish
- `TP-41` End-to-end verification

---

## 5. 全局完成定义

只有当下面这些都成立时，才算蓝图真正落地：

- 用户进入产品后，自然理解“我在和一个代码教练对话”。
- `对话 / 计划 / 设置` 三视图稳定成立。
- idea implementation、project idea mining、project adaptation、principle explanation 四大场景可用。
- Plan 能承接长期训练、复习、弱点和轨迹。
- Settings 可完整配置大模型与训练偏好。
- 研究、记忆、评估、检索对用户来说都退到后台。
- 前端观感成熟，不再有重 AI 味。
- `npm run check --prefix /Users/Apple/Desktop/trainer/extension/webview`
- `npm run check --prefix /Users/Apple/Desktop/trainer/extension`
- `cd /Users/Apple/Desktop/trainer/server && python -m pytest tests/ -v`
- `cd /Users/Apple/Desktop/trainer && npm run build`

---

## 6. 统一任务包回传格式

每个任务包完成后，必须用下面的结构回传，方便下一包直接接手：

```md
## Task Result

Task: TP-xx
Status: done / partial / blocked

Files changed:
- /absolute/path/one
- /absolute/path/two

What was completed:
- ...

Tests run:
- command
- result

Open risks:
- ...

Follow-up expectations:
- ...

Needs integration from:
- TP-xx
```

---

## 7. Foundation Task Packages

这些任务包负责把当前代码改造成“可以并行开发”的形态。

### TP-00 Webview Shell Split

**Mission**

把当前过重的 [App.tsx](/Users/Apple/Desktop/trainer/extension/webview/src/app/App.tsx) 拆成稳定 shell，让 coach、composer、plan、settings、icons 能分别归位。

**Product Promise**

这是后续所有前端任务能否独立推进的基础。如果这一步做不好，后面的前端任务包都会互相冲突。

**Read First**

- [2026-04-30-trainer-coach-first-product-definition.md](/Users/Apple/Desktop/trainer/docs/plans/2026-04-30-trainer-coach-first-product-definition.md)
- [2026-04-30-trainer-coach-first-ui-and-feature-design.md](/Users/Apple/Desktop/trainer/docs/plans/2026-04-30-trainer-coach-first-ui-and-feature-design.md)
- [2026-04-30-trainer-coach-first-execution-shards.md](/Users/Apple/Desktop/trainer/docs/plans/2026-04-30-trainer-coach-first-execution-shards.md)
- [App.tsx](/Users/Apple/Desktop/trainer/extension/webview/src/app/App.tsx)

**Allowed Write Scope**

- `/Users/Apple/Desktop/trainer/extension/webview/src/app/App.tsx`
- `/Users/Apple/Desktop/trainer/extension/webview/src/components/coach/`
- `/Users/Apple/Desktop/trainer/extension/webview/src/components/composer/`
- `/Users/Apple/Desktop/trainer/extension/webview/src/components/plan/`
- `/Users/Apple/Desktop/trainer/extension/webview/src/components/settings/`
- `/Users/Apple/Desktop/trainer/extension/webview/src/components/icons/`

**Forbidden / Do Not Touch**

- `/Users/Apple/Desktop/trainer/server/**`
- `/Users/Apple/Desktop/trainer/shared/**`
- `/Users/Apple/Desktop/trainer/extension/src/**`
- `/Users/Apple/Desktop/trainer/extension/webview/src/lib/types.ts`
- `/Users/Apple/Desktop/trainer/extension/webview/src/app/useWorkbenchState.ts`

**Dependencies**

- 无

**Inputs Expected From Upstream**

- 无

**Implementation Checklist**

1. 盘点 `App.tsx` 当前承担的职责。
2. 抽出 icons 组件，保证图标不再散落在 `App.tsx` 底部。
3. 抽出通用展示件：
   - message bubble
   - card/block
   - toolbar button
4. 抽出 coach view shell。
5. 抽出 composer shell。
6. 抽出 plan view shell。
7. 抽出 settings view shell。
8. 确保 `App.tsx` 最终只负责：
   - host message subscription
   - top-level state binding
   - active view switch
   - keyboard shortcut orchestration
9. 保留当前行为，不在这个包里重做视觉。

**Acceptance**

- `App.tsx` 行数明显下降。
- 后续前端任务能主要写自己的目录。
- `npm run check --prefix /Users/Apple/Desktop/trainer/extension/webview`
- `npm run build --prefix /Users/Apple/Desktop/trainer/extension/webview`

**Common Failure Modes**

- 一边拆壳一边改视觉，导致责任不清。
- 把 types/store 一起顺手改掉，污染后续任务。
- 把 research 视图逻辑又塞回新 shell。

**Handoff Contract**

- 列出新组件目录结构。
- 标记哪些 mount points 还需要后续任务接内容。

**Suggested Commit**

- `refactor(webview): split app shell for coach-first views`

---

### TP-01 CSS Layer Split

**Mission**

把当前集中式样式拆成可以按功能包并行维护的样式层。

**Product Promise**

如果前端所有任务都继续写同一个 `styles.css`，后续即使组件拆开，样式仍然会互相打架。

**Read First**

- [styles.css](/Users/Apple/Desktop/trainer/extension/webview/src/styles.css)
- [main.tsx](/Users/Apple/Desktop/trainer/extension/webview/src/main.tsx)
- [App.tsx](/Users/Apple/Desktop/trainer/extension/webview/src/app/App.tsx)

**Allowed Write Scope**

- `/Users/Apple/Desktop/trainer/extension/webview/src/styles.css`
- `/Users/Apple/Desktop/trainer/extension/webview/src/styles/`
- `/Users/Apple/Desktop/trainer/extension/webview/src/main.tsx`

**Forbidden / Do Not Touch**

- `/Users/Apple/Desktop/trainer/server/**`
- `/Users/Apple/Desktop/trainer/shared/**`
- `/Users/Apple/Desktop/trainer/extension/src/**`
- Component logic files except imports strictly needed for styles

**Dependencies**

- `TP-00`

**Inputs Expected From Upstream**

- 基础 shell 已拆开

**Implementation Checklist**

1. 新建样式分层目录，例如：
   - `styles/tokens.css`
   - `styles/base.css`
   - `styles/layout.css`
   - `styles/coach.css`
   - `styles/composer.css`
   - `styles/plan.css`
   - `styles/settings.css`
2. 把全局 token 和 reset 留在最底层。
3. 把布局壳层样式单独放在 `layout.css`。
4. 为后续四个前端任务包各留独立样式文件。
5. 在 `main.tsx` 或统一入口中按顺序导入。
6. 保持当前 UI 不崩，不做最终风格抛光。

**Acceptance**

- 以后前端任务不需要继续共享一个大 CSS 文件。
- `npm run build --prefix /Users/Apple/Desktop/trainer/extension/webview`

**Common Failure Modes**

- 样式拆分后导入顺序错乱。
- 仍把大部分样式留在旧 `styles.css`。

**Handoff Contract**

- 给出最终样式分层图。
- 标明哪些 CSS 文件归哪个任务包所有。

**Suggested Commit**

- `refactor(webview): split style layers for parallel coach-first work`

---

### TP-02 Shared Contract Stabilization

**Mission**

把 coach-first 所需的 shared/domain contract 一次性定稳。

**Product Promise**

没有稳定 contract，后续前端和后端只能互相猜字段，集成时一定返工。

**Read First**

- [core/models.py](/Users/Apple/Desktop/trainer/server/app/core/models.py)
- [shared/src/models.ts](/Users/Apple/Desktop/trainer/shared/src/models.ts)
- [shared/src/protocol.ts](/Users/Apple/Desktop/trainer/shared/src/protocol.ts)
- [webview types.ts](/Users/Apple/Desktop/trainer/extension/webview/src/lib/types.ts)
- [教学实施方案](/Users/Apple/Desktop/trainer/docs/plans/2026-04-30-trainer-teaching-memory-affect-implementation-plan.md)

**Allowed Write Scope**

- `/Users/Apple/Desktop/trainer/server/app/core/models.py`
- `/Users/Apple/Desktop/trainer/shared/src/models.ts`
- `/Users/Apple/Desktop/trainer/shared/src/protocol.ts`
- `/Users/Apple/Desktop/trainer/extension/webview/src/lib/types.ts`

**Forbidden / Do Not Touch**

- `/Users/Apple/Desktop/trainer/server/app/api/routers.py`
- `/Users/Apple/Desktop/trainer/server/app/llm/**`
- `/Users/Apple/Desktop/trainer/extension/webview/src/app/App.tsx`
- `/Users/Apple/Desktop/trainer/extension/webview/src/components/**`

**Dependencies**

- 无

**Inputs Expected From Upstream**

- 无

**Implementation Checklist**

1. 从产品文档提取必须稳定的概念。
2. 在 server 侧建立 canonical 模型：
   - `TeachingMode`
   - `LearnerState`
   - `TeachingDecision`
   - `AffectState`
   - `ToneDecision`
   - `ImplementationGuide`
   - `ProjectIdea`
   - `ProjectAdaptationGuide`
   - `ReviewItem`
3. 在 shared/protocol 建立前端投影模型。
4. 扩展 snapshot 可见字段：
   - due reviews
   - coaching state
   - teaching observations
   - idea progress
   - adaptation progress
5. 保持兼容字段逻辑，不拆旧 plan 兼容。
6. 所有新字段默认可空，但命名必须稳定。

**Acceptance**

- `npm run check --prefix /Users/Apple/Desktop/trainer/extension`
- `npm run check --prefix /Users/Apple/Desktop/trainer/extension/webview`

**Common Failure Modes**

- server/shared/webview 命名不一致。
- 一边加后端模型，一边偷偷加 UI 专用字段。
- 改坏现有 plan 兼容逻辑。

**Handoff Contract**

- 输出一份字段映射摘要。
- 明确哪些字段现在只是契约，还没有真实来源。

**Suggested Commit**

- `feat(shared): stabilize coach-first domain contracts`

---

### TP-03 Review Persistence

**Mission**

给 review 和 spaced repetition 打真实落库基础。

**Product Promise**

Trainer 要成为长期教练，就不能只有临时内存判断，必须能记住哪些东西该复习。

**Read First**

- [memory/models.py](/Users/Apple/Desktop/trainer/server/app/memory/models.py)
- [repository.py](/Users/Apple/Desktop/trainer/server/app/db/repository.py)
- [test_repositories.py](/Users/Apple/Desktop/trainer/server/tests/test_repositories.py)

**Allowed Write Scope**

- `/Users/Apple/Desktop/trainer/server/app/memory/models.py`
- `/Users/Apple/Desktop/trainer/server/app/db/repository.py`
- `/Users/Apple/Desktop/trainer/server/tests/test_repositories.py`

**Forbidden / Do Not Touch**

- `/Users/Apple/Desktop/trainer/server/app/api/**`
- `/Users/Apple/Desktop/trainer/server/app/llm/**`
- `/Users/Apple/Desktop/trainer/server/app/planner/service.py`
- Any webview/extension files

**Dependencies**

- `TP-02`

**Inputs Expected From Upstream**

- `ReviewItem` 结构已稳定

**Implementation Checklist**

1. 定义 review item 存储结构。
2. 在 SQLite 初始化脚本中新增 `review_items` 表。
3. 增加 repository API：
   - save
   - list
   - list due
   - update
4. 保证 workspace 维度隔离。
5. 写真实数据库测试。

**Acceptance**

- `cd /Users/Apple/Desktop/trainer/server && python -m pytest tests/test_repositories.py -v`

**Common Failure Modes**

- 忘记 workspace_id 过滤。
- 把 review data 混进旧 reflection 表。
- schema 变更没有测试覆盖。

**Handoff Contract**

- 列出 repository 新增方法名和返回结构。

**Suggested Commit**

- `feat(memory): persist review items for coach-first review loop`

---

## 8. Frontend Task Packages

这些任务包在 `TP-00`、`TP-01`、`TP-02` 完成后可以高质量并行。

### TP-10 Coach Message System

**Mission**

把对话区做成真正的教练消息流系统。

**Product Promise**

用户必须在第一眼就知道谁在说话、现在发生了什么、哪些是结构化结果，而不是被一堆卡片和模式概念干扰。

**Read First**

- [UI 设计文档](/Users/Apple/Desktop/trainer/docs/plans/2026-04-30-trainer-coach-first-ui-and-feature-design.md)
- `TP-00` 结果
- `/Users/Apple/Desktop/trainer/extension/webview/src/components/coach/`
- `/Users/Apple/Desktop/trainer/extension/webview/src/styles/coach.css`

**Allowed Write Scope**

- `/Users/Apple/Desktop/trainer/extension/webview/src/components/coach/`
- `/Users/Apple/Desktop/trainer/extension/webview/src/styles/coach.css`
- Optional mount touch in coach shell only

**Forbidden / Do Not Touch**

- Composer files
- Plan files
- Settings files
- `/Users/Apple/Desktop/trainer/extension/webview/src/lib/types.ts`
- `/Users/Apple/Desktop/trainer/extension/webview/src/app/useWorkbenchState.ts`
- `/Users/Apple/Desktop/trainer/extension/webview/src/styles/composer.css`
- `/Users/Apple/Desktop/trainer/extension/webview/src/styles/plan.css`
- `/Users/Apple/Desktop/trainer/extension/webview/src/styles/settings.css`

**Dependencies**

- `TP-00`
- `TP-01`
- `TP-02`

**Inputs Expected From Upstream**

- Coach-related artifact kinds 已有基础契约

**Implementation Checklist**

1. 建立消息流主组件。
2. 建立用户/教练 message bubble。
3. 建立 artifact block 系统。
4. 建立以下结果块：
   - deep analysis
   - project idea
   - project adaptation
   - principle
5. 结果块视觉上比普通消息更结构化，但不能大而厚。
6. 深入分析默认只显示结论，细节可折叠。
7. 去掉任何显式 research 心智词。
8. 确保字体偏小、行高紧、区分明显。

**Acceptance**

- 用户消息和教练消息一眼区分。
- 没有独立 research 页也能表达深入分析。
- 消息流视觉安静，不像 AI dashboard。
- `npm run build --prefix /Users/Apple/Desktop/trainer/extension/webview`

**Common Failure Modes**

- 用户和教练视觉差不够大。
- artifact block 过厚、像独立模块。
- 引入新的 research 文案或研究线程术语。

**Handoff Contract**

- 标记所有 artifact kind 与组件映射关系。

**Suggested Commit**

- `feat(webview): build coach-first message system`

---

### TP-11 Composer System

**Mission**

把输入区做成低理解成本、高完成度的工作输入器。

**Product Promise**

Trainer 的强应该发生在发送背后，而不是输入区上摆一堆能力按钮。

**Read First**

- [UI 设计文档输入区章节](/Users/Apple/Desktop/trainer/docs/plans/2026-04-30-trainer-coach-first-ui-and-feature-design.md)
- `/Users/Apple/Desktop/trainer/extension/webview/src/components/composer/`
- `/Users/Apple/Desktop/trainer/extension/webview/src/styles/composer.css`

**Allowed Write Scope**

- `/Users/Apple/Desktop/trainer/extension/webview/src/components/composer/`
- `/Users/Apple/Desktop/trainer/extension/webview/src/styles/composer.css`
- Optional icons import wiring

**Forbidden / Do Not Touch**

- Coach message files
- Plan files
- Settings files
- Shared/store/protocol/server files

**Dependencies**

- `TP-00`
- `TP-01`
- `TP-02`

**Inputs Expected From Upstream**

- Shell 与 styles layer 已经分开

**Implementation Checklist**

1. 文本输入区保持单一主动作：发送。
2. 高优先级常驻图标最多 3 个：
   - context
   - current file
   - selection
3. 其余能力进入更多菜单。
4. 做一条极小字号状态线，表达：
   - 当前上下文
   - 当前风格
   - 当前是否深入分析
5. 输入区高度收紧。
6. 输入文字略大于提示，但仍比常规聊天产品更克制。
7. 确保 hover/click 命中足够，不因极简变难用。

**Acceptance**

- 输入区不再像功能面板。
- 发送左侧常驻图标不超过 3 个。
- 文本层级和图标对齐自然。
- `npm run build --prefix /Users/Apple/Desktop/trainer/extension/webview`

**Common Failure Modes**

- 把太多控制塞回输入区。
- 为了极简把点击命中区做得很难用。
- 字体和图标基线不对齐。

**Handoff Contract**

- 说明哪些控制常驻，哪些被收入 menu。

**Suggested Commit**

- `feat(webview): compress composer into coach-first input system`

---

### TP-12 Plan System

**Mission**

把 Plan 从“摘要卡”升级成真正的训练中枢。

**Product Promise**

用户打开 Plan，必须能马上知道我现在练什么、下一步是什么、最近哪里弱、哪些内容该复习。

**Read First**

- [产品总纲关于计划的定义](/Users/Apple/Desktop/trainer/docs/plans/2026-04-30-trainer-coach-first-product-definition.md)
- [UI 设计文档计划章节](/Users/Apple/Desktop/trainer/docs/plans/2026-04-30-trainer-coach-first-ui-and-feature-design.md)
- `/Users/Apple/Desktop/trainer/extension/webview/src/components/plan/`
- `/Users/Apple/Desktop/trainer/extension/webview/src/styles/plan.css`

**Allowed Write Scope**

- `/Users/Apple/Desktop/trainer/extension/webview/src/components/plan/`
- `/Users/Apple/Desktop/trainer/extension/webview/src/styles/plan.css`

**Forbidden / Do Not Touch**

- Coach message system files
- Composer files
- Settings files
- Shared/store/protocol/server files

**Dependencies**

- `TP-00`
- `TP-01`
- `TP-02`
- `TP-03`

**Inputs Expected From Upstream**

- due review / coaching state / idea/adaptation fields 已在 contract 中预留

**Implementation Checklist**

1. 建立目标摘要区。
2. 建立当前阶段区。
3. 建立任务队列区。
4. 建立该复习区。
5. 建立教练观察区。
6. 建立 recent progress 区。
7. 建立 idea progress 区。
8. 建立 adaptation progress 区。
9. 确保结构感比聊天更强，但视觉不能更吵。

**Acceptance**

- 用户打开计划页能立刻回答三件事：
  - 我现在练什么
  - 下一步是什么
  - 该复习什么
- `npm run build --prefix /Users/Apple/Desktop/trainer/extension/webview`

**Common Failure Modes**

- 又做成信息大杂烩。
- 每块都等权，缺少主次。
- 把 Plan 做成一个漂亮仪表盘而不是训练面板。

**Handoff Contract**

- 标出每个 panel 期望吃哪些 snapshot 字段。

**Suggested Commit**

- `feat(webview): rebuild plan view as coach-first training hub`

---

### TP-13 Settings System

**Mission**

把 Settings 做成完整系统面板，而不是临时配置层。

**Product Promise**

用户应当可以在一个地方完成大模型配置、语言/风格设置、记忆/复习设置、学习档案设置。

**Read First**

- [UI 设计文档设置章节](/Users/Apple/Desktop/trainer/docs/plans/2026-04-30-trainer-coach-first-ui-and-feature-design.md)
- `/Users/Apple/Desktop/trainer/extension/webview/src/components/settings/`
- `/Users/Apple/Desktop/trainer/extension/webview/src/styles/settings.css`

**Allowed Write Scope**

- `/Users/Apple/Desktop/trainer/extension/webview/src/components/settings/`
- `/Users/Apple/Desktop/trainer/extension/webview/src/styles/settings.css`

**Forbidden / Do Not Touch**

- Extension host provider config plumbing
- Shared/store/protocol/server files
- Coach/Plan/Composer files

**Dependencies**

- `TP-00`
- `TP-01`
- `TP-02`

**Inputs Expected From Upstream**

- provider config view / profile view 基础类型稳定

**Implementation Checklist**

1. 建立 provider settings group。
2. 建立 interface settings group。
3. 建立 memory settings group。
4. 建立 profile settings group。
5. provider 区只强调大模型配置，不出现 embedding 必填心智。
6. 训练偏好区聚焦：
   - 语言
   - 回答风格
   - follow 当前文件
   - 长期记忆
   - 复习提醒
7. 学习档案区展示：
   - 目标
   - 背景
   - 每周时间
   - 技术偏好
8. 整体像专业系统面板，不像冗长 AI 表单。

**Acceptance**

- 设置页功能完整，但页面不吵。
- `npm run build --prefix /Users/Apple/Desktop/trainer/extension/webview`

**Common Failure Modes**

- 把所有输入堆成一个长表单。
- 出现 embedding 模型配置主路径。
- 页面太像后台系统，不像侧栏工具。

**Handoff Contract**

- 标明哪些设置字段还只是前端展示，哪些已联通。

**Suggested Commit**

- `feat(webview): build complete coach-first settings system`

---

## 9. Backend Capability Task Packages

这些任务包在 `TP-02` 完成后大多可以并行，因为它们主要创建新服务文件。

### TP-20 Pedagogy Decision Engine

**Mission**

建立教练的“先判断怎么教，再决定怎么答”的能力。

**Product Promise**

Trainer 不是普通问答助手，必须会判断当前是 idea 实现、项目提炼、改造指导、原理解释、计划、评审还是救火。

**Read First**

- [教学实施方案](/Users/Apple/Desktop/trainer/docs/plans/2026-04-30-trainer-teaching-memory-affect-implementation-plan.md)
- [provider_service.py](/Users/Apple/Desktop/trainer/server/app/llm/provider_service.py)
- [test_provider_service.py](/Users/Apple/Desktop/trainer/server/tests/test_provider_service.py)
- [core/models.py](/Users/Apple/Desktop/trainer/server/app/core/models.py)

**Allowed Write Scope**

- `/Users/Apple/Desktop/trainer/server/app/pedagogy/service.py`
- `/Users/Apple/Desktop/trainer/server/tests/test_pedagogy.py`

**Forbidden / Do Not Touch**

- `/Users/Apple/Desktop/trainer/server/app/api/routers.py`
- `/Users/Apple/Desktop/trainer/server/app/llm/**`
- `/Users/Apple/Desktop/trainer/server/app/planner/**`
- Any frontend files

**Dependencies**

- `TP-02`

**Inputs Expected From Upstream**

- `TeachingDecision` / `TeachingMode` 契约稳定

**Implementation Checklist**

1. 设计 message-level heuristic。
2. 覆盖至少这些模式：
   - idea implementation
   - project idea mining
   - project adaptation
   - principle explanation
   - planning
   - review/reflection
3. 生成 `TeachingDecision.reason`。
4. 决定是否：
   - end with question
   - produce plan artifact
   - trigger deep analysis
   - focus on implementation steps
5. 为中英文输入写测试。

**Acceptance**

- `cd /Users/Apple/Desktop/trainer/server && python -m pytest tests/test_pedagogy.py -v`

**Common Failure Modes**

- 规则过于模糊，导致所有输入都回落为 guided。
- decision 没理由字段，后续难排错。

**Handoff Contract**

- 给出 decision matrix 摘要。

**Suggested Commit**

- `feat(pedagogy): add coach-first teaching decision engine`

---

### TP-21 Implementation Coach

**Mission**

把 idea 输入转换成持续实现指导。

**Product Promise**

这是 Trainer 第一核心模式，必须非常稳。

**Read First**

- [教学实施方案中 implementation guide 章节](/Users/Apple/Desktop/trainer/docs/plans/2026-04-30-trainer-teaching-memory-affect-implementation-plan.md)
- [core/models.py](/Users/Apple/Desktop/trainer/server/app/core/models.py)
- [planner/service.py](/Users/Apple/Desktop/trainer/server/app/planner/service.py)

**Allowed Write Scope**

- `/Users/Apple/Desktop/trainer/server/app/pedagogy/implementation_coach.py`
- `/Users/Apple/Desktop/trainer/server/tests/test_pedagogy.py`

**Forbidden / Do Not Touch**

- router/provider/prompt
- other pedagogy service files
- frontend files

**Dependencies**

- `TP-02`
- `TP-20`

**Inputs Expected From Upstream**

- 意图已被识别为 idea implementation

**Implementation Checklist**

1. 接收 current file / related files / diagnostics / plan / weaknesses。
2. 输出 implementation guide：
   - idea summary
   - scope boundary
   - MVP
   - current step
   - next steps
   - validation strategy
   - open questions
3. 强制小步化，不允许一次性整包方案。
4. 上下文不足时必须明确 open questions。

**Acceptance**

- 典型 idea 输入能产出 stepwise guide。

**Common Failure Modes**

- 输出泛泛 roadmap，不够可执行。
- 忘记 validation strategy。
- 直接写大而全方案。

**Handoff Contract**

- 给出 2 到 3 个实际输入样例的输出结构。

**Suggested Commit**

- `feat(pedagogy): add implementation coach guidance engine`

---

### TP-22 Project Idea Miner

**Mission**

从现有项目里挖出值得练的东西。

**Product Promise**

当用户没有明确 idea 时，教练也应该能主动推动训练，而不是干等。

**Read First**

- [教学实施方案中 project idea 章节](/Users/Apple/Desktop/trainer/docs/plans/2026-04-30-trainer-teaching-memory-affect-implementation-plan.md)
- [memory/service.py](/Users/Apple/Desktop/trainer/server/app/memory/service.py)
- [planner/service.py](/Users/Apple/Desktop/trainer/server/app/planner/service.py)

**Allowed Write Scope**

- `/Users/Apple/Desktop/trainer/server/app/pedagogy/project_idea_miner.py`
- `/Users/Apple/Desktop/trainer/server/tests/test_pedagogy.py`

**Forbidden / Do Not Touch**

- router/provider/prompt
- adaptation/principle files
- frontend files

**Dependencies**

- `TP-02`
- `TP-20`

**Inputs Expected From Upstream**

- recent files / diagnostics / weaknesses / current stage can be read by caller

**Implementation Checklist**

1. 提取 opportunity signals：
   - repetition
   - missing test
   - coupling hotspot
   - rough edge
   - feature gap
2. 每次只输出 1 到 3 个高质量 idea。
3. 每个 idea 必须包含：
   - why now
   - learning value
   - engineering value
   - suggested scope
   - first step
4. 输出不能脱离当前项目。

**Acceptance**

- idea 输出数量少、质量高、直接可做。

**Common Failure Modes**

- 输出 brainstorm 列表而不是训练机会。
- 过于宏大，无法在当前项目中落地。

**Handoff Contract**

- 给出 signal 到 idea 的映射规则。

**Suggested Commit**

- `feat(pedagogy): add project idea miner`

---

### TP-23 Project Adaptation Coach

**Mission**

让教练能指导用户低风险地改造已有项目。

**Product Promise**

用户不只是从零做 demo，更常见的是拿一个现成项目来改。Trainer 必须能带这种场景。

**Read First**

- [教学实施方案中 adaptation 章节](/Users/Apple/Desktop/trainer/docs/plans/2026-04-30-trainer-teaching-memory-affect-implementation-plan.md)
- [core/models.py](/Users/Apple/Desktop/trainer/server/app/core/models.py)

**Allowed Write Scope**

- `/Users/Apple/Desktop/trainer/server/app/pedagogy/project_adaptation_coach.py`
- `/Users/Apple/Desktop/trainer/server/tests/test_project_adaptation.py`

**Forbidden / Do Not Touch**

- principle explainer
- router/provider/prompt
- frontend files

**Dependencies**

- `TP-02`
- `TP-20`

**Inputs Expected From Upstream**

- 意图已被识别为 project adaptation

**Implementation Checklist**

1. 提炼用户真正想改变的目标。
2. 识别：
   - affected areas
   - preserve areas
   - current constraints
3. 生成：
   - first migration step
   - migration sequence
   - validation checkpoints
   - rollback notes
4. 强调“渐进、小步、可验证”，禁止默认推倒重来。

**Acceptance**

- 用户改造型输入能得到低风险改造路线。

**Common Failure Modes**

- 给出重写建议。
- 只讲愿景，不讲受影响区域和验证点。

**Handoff Contract**

- 给出至少一个“UI 改造”和一个“架构改造”示例输出。

**Suggested Commit**

- `feat(pedagogy): add project adaptation coach`

---

### TP-24 Principle Explainer

**Mission**

让教练不仅给建议，还能讲清楚为什么这样做。

**Product Promise**

Trainer 是教练，不是只会报修改清单。

**Read First**

- [教学实施方案 principle explanation 章节](/Users/Apple/Desktop/trainer/docs/plans/2026-04-30-trainer-teaching-memory-affect-implementation-plan.md)
- [prompts.py](/Users/Apple/Desktop/trainer/server/app/llm/prompts.py)

**Allowed Write Scope**

- `/Users/Apple/Desktop/trainer/server/app/pedagogy/principle_explainer.py`
- `/Users/Apple/Desktop/trainer/server/tests/test_project_adaptation.py`

**Forbidden / Do Not Touch**

- adaptation coach
- provider/prompt/router
- frontend files

**Dependencies**

- `TP-02`
- `TP-20`

**Inputs Expected From Upstream**

- 当前建议、上下文和目标已经可读

**Implementation Checklist**

1. 生成 principle notes：
   - current principle
   - common wrong intuition
   - why this approach
   - transferable lesson
2. 语气保持教学感，不写学术论文。
3. 输出结构要适合后续消息流中的 principle block。

**Acceptance**

- 用户问“为什么这样改”，能得到有教学价值的解释骨架。

**Common Failure Modes**

- 只说大道理，不贴当前代码语境。
- 输出太散，无法进入 UI block。

**Handoff Contract**

- 列出 principle note 的最终字段结构。

**Suggested Commit**

- `feat(pedagogy): add principle explainer`

---

### TP-25 Review Scheduler

**Mission**

把复习机制做成稳定、可解释的底层能力。

**Product Promise**

Trainer 要帮用户记住东西，而不是只会不断往前推。

**Read First**

- [教学实施方案 spaced review 章节](/Users/Apple/Desktop/trainer/docs/plans/2026-04-30-trainer-teaching-memory-affect-implementation-plan.md)
- [memory/service.py](/Users/Apple/Desktop/trainer/server/app/memory/service.py)
- [planner/service.py](/Users/Apple/Desktop/trainer/server/app/planner/service.py)

**Allowed Write Scope**

- `/Users/Apple/Desktop/trainer/server/app/memory/review_scheduler.py`
- `/Users/Apple/Desktop/trainer/server/tests/test_review_scheduler.py`

**Forbidden / Do Not Touch**

- router
- provider/prompt
- repository
- planner/service.py
- frontend files

**Dependencies**

- `TP-03`

**Inputs Expected From Upstream**

- review items 已可持久化

**Implementation Checklist**

1. 定义 1 / 3 / 7 / 14 天节奏。
2. 成功复习前移 mastery，失败则回退。
3. due item 需要有排序策略。
4. 提供纯函数或小服务 API，后续易接入 planner/router。

**Acceptance**

- `cd /Users/Apple/Desktop/trainer/server && python -m pytest tests/test_review_scheduler.py -v`

**Common Failure Modes**

- 调度逻辑写死在 repository 或 router 中。
- 无法解释为什么某条 due item 优先。

**Handoff Contract**

- 列出 scheduler API。

**Suggested Commit**

- `feat(memory): add spaced review scheduler`

---

### TP-26 Project Source Scout

**Mission**

在当前工作区不合适时，给出更适合训练的外部项目来源建议。

**Product Promise**

Trainer 不能只围着当前仓库打转，也要知道什么时候该建议更适合的训练素材。

**Read First**

- [教学实施方案 project sourcing 章节](/Users/Apple/Desktop/trainer/docs/plans/2026-04-30-trainer-teaching-memory-affect-implementation-plan.md)
- [resources/service.py](/Users/Apple/Desktop/trainer/server/app/resources/service.py)
- [research service files if needed for context only]

**Allowed Write Scope**

- `/Users/Apple/Desktop/trainer/server/app/pedagogy/project_source_scout.py`
- `/Users/Apple/Desktop/trainer/server/tests/test_pedagogy.py`

**Forbidden / Do Not Touch**

- router/provider/prompt
- resource ingestion internals
- frontend files

**Dependencies**

- `TP-02`
- `TP-20`

**Inputs Expected From Upstream**

- training goal / preferred stack / difficulty preference 可由 caller 提供

**Implementation Checklist**

1. 输出 source candidate 结构。
2. 第一版只做“建议和筛选逻辑”，不做真实下载。
3. 每个 candidate 至少包含：
   - why fit
   - stack fit
   - difficulty fit
   - suggested training use
4. 保证这是“训练项目候选”，不是泛资源清单。

**Acceptance**

- 输出有筛选逻辑，而不是杂乱链接列表。

**Common Failure Modes**

- 直接变成资源推荐器。
- 输出没有训练价值说明。

**Handoff Contract**

- 给出 source candidate 字段定义。

**Suggested Commit**

- `feat(pedagogy): add project source scout`

---

## 10. Integration Task Packages

这些任务包负责修改总线文件，必须在前置能力成熟后再做。

### TP-30 Provider and Prompt Integration

**Mission**

让 provider/prompt 真正理解教练上下文，而不是只认识 profile 和 current file。

**Product Promise**

所有后端强能力最终都必须通过 prompt assembly 收束成“像教练”的回复。

**Read First**

- [provider_service.py](/Users/Apple/Desktop/trainer/server/app/llm/provider_service.py)
- [prompts.py](/Users/Apple/Desktop/trainer/server/app/llm/prompts.py)
- [test_provider_service.py](/Users/Apple/Desktop/trainer/server/tests/test_provider_service.py)
- 已完成的 `TP-20` 到 `TP-26` 输出契约

**Allowed Write Scope**

- `/Users/Apple/Desktop/trainer/server/app/llm/provider_service.py`
- `/Users/Apple/Desktop/trainer/server/app/llm/prompts.py`
- `/Users/Apple/Desktop/trainer/server/tests/test_provider_service.py`

**Forbidden / Do Not Touch**

- routers.py
- repository
- webview/extension files

**Dependencies**

- `TP-20`
- `TP-21`
- `TP-22`
- `TP-23`
- `TP-24`
- `TP-25`
- `TP-26`

**Inputs Expected From Upstream**

- teaching decision / tone decision / due reviews / guides / ideas 契约稳定

**Implementation Checklist**

1. 扩展 provider reply 入参。
2. 扩展 stream reply 入参。
3. 升级 system prompt 结构，加入：
   - current teaching mode
   - current tone
   - review due summary
   - implementation guide
   - project ideas
   - project adaptation guide
   - principle notes
4. scaffold mode 也要 reflect coach-first。
5. 保持 `guided / balanced / direct` 兼容。
6. 增加测试覆盖新上下文拼装。

**Acceptance**

- `cd /Users/Apple/Desktop/trainer/server && python -m pytest tests/test_provider_service.py -v`

**Common Failure Modes**

- 只改 prompt，不改 provider method 签名。
- API key 缺失时 scaffold mode 退化。
- prompt 太长太散，没有聚焦当前教学模式。

**Handoff Contract**

- 给出新 provider method 参数列表。
- 给出 system prompt 大纲。

**Suggested Commit**

- `feat(llm): inject coach-first teaching context into provider prompts`

---

### TP-31 Router Orchestration Integration

**Mission**

把 turn 流程升级成真正的教练 orchestrator。

**Product Promise**

产品的“强”最终要在这里形成：一次发送，背后自动读取上下文、判断模式、安排复习、必要时深入分析，再回写记忆与计划。

**Read First**

- [routers.py](/Users/Apple/Desktop/trainer/server/app/api/routers.py)
- [test_api.py](/Users/Apple/Desktop/trainer/server/tests/test_api.py)
- [test_training_flow_integration.py](/Users/Apple/Desktop/trainer/server/tests/test_training_flow_integration.py)
- 已完成的 `TP-20` 到 `TP-30`

**Allowed Write Scope**

- `/Users/Apple/Desktop/trainer/server/app/api/routers.py`
- `/Users/Apple/Desktop/trainer/server/tests/test_api.py`
- `/Users/Apple/Desktop/trainer/server/tests/test_training_flow_integration.py`

**Forbidden / Do Not Touch**

- provider_service.py
- prompts.py
- frontend files
- repository internals

**Dependencies**

- `TP-03`
- `TP-20`
- `TP-21`
- `TP-22`
- `TP-23`
- `TP-24`
- `TP-25`
- `TP-26`
- `TP-30`

**Inputs Expected From Upstream**

- provider 可接受新上下文
- review items / scheduler 可工作

**Implementation Checklist**

1. 在 `execute_turn()` 中读取 memory snapshot。
2. 生成 learner state / teaching decision / tone decision。
3. 读取 due reviews。
4. 按 decision 触发对应服务。
5. 注入 provider。
6. 记录 message / reflection / review updates / plan progress。
7. 产出最小 snapshot patch 给前台。
8. 增加集成测试覆盖四条黄金路径。

**Acceptance**

- `cd /Users/Apple/Desktop/trainer/server && python -m pytest tests/test_api.py tests/test_training_flow_integration.py -v`

**Common Failure Modes**

- 把 orchestration 逻辑散落到多个 helper，难追踪。
- snapshot patch 暴露太多底层内部术语。
- 没有真正写回 memory/review/plan。

**Handoff Contract**

- 给出 turn pipeline 摘要。
- 给出 snapshot 中新增字段列表。

**Suggested Commit**

- `feat(api): orchestrate coach-first turn pipeline`

---

### TP-32 Extension Bridge and Bootstrap Integration

**Mission**

让 extension host、bootstrap、patch、mock data 和 Zustand store 全部理解 coach-first 新字段。

**Product Promise**

前端如果只靠老字段渲染，就算后端做强了，前台也接不住。

**Read First**

- [webviewBridge.ts](/Users/Apple/Desktop/trainer/extension/src/core/webviewBridge.ts)
- [workbenchData.ts](/Users/Apple/Desktop/trainer/extension/src/core/workbenchData.ts)
- [mockData.ts](/Users/Apple/Desktop/trainer/extension/webview/src/lib/mockData.ts)
- [useWorkbenchState.ts](/Users/Apple/Desktop/trainer/extension/webview/src/app/useWorkbenchState.ts)
- 已完成的 `TP-02`、`TP-31`

**Allowed Write Scope**

- `/Users/Apple/Desktop/trainer/extension/src/core/webviewBridge.ts`
- `/Users/Apple/Desktop/trainer/extension/src/core/workbenchData.ts`
- `/Users/Apple/Desktop/trainer/extension/webview/src/lib/mockData.ts`
- `/Users/Apple/Desktop/trainer/extension/webview/src/app/useWorkbenchState.ts`
- `/Users/Apple/Desktop/trainer/extension/webview/src/lib/types.ts`
- `/Users/Apple/Desktop/trainer/extension/src/provider/providerConfigStore.ts`

**Forbidden / Do Not Touch**

- UI component implementation files except typing fallout
- server files
- shared model files

**Dependencies**

- `TP-00`
- `TP-02`
- `TP-10`
- `TP-11`
- `TP-12`
- `TP-13`
- `TP-31`

**Inputs Expected From Upstream**

- snapshot fields and patch semantics 已稳定

**Implementation Checklist**

1. 扩展 bootstrap data 组装。
2. 扩展 session merge / memory merge / patch merge。
3. mock data 至少覆盖：
   - idea implementation
   - project idea
   - adaptation
   - principle explanation
   - due reviews
   - coaching state
4. 收紧前端 `SidebarView` 心智，不再依赖 research 作为默认视图。
5. provider config store 与前台口径对齐：
   - 大模型配置
   - 不把 embedding 当主路径

**Acceptance**

- `npm run check --prefix /Users/Apple/Desktop/trainer/extension`
- `npm run check --prefix /Users/Apple/Desktop/trainer/extension/webview`

**Common Failure Modes**

- mock data 和真实 snapshot 字段脱节。
- Store 里仍然把 research 当主视图。
- provider 配置口径前后不一致。

**Handoff Contract**

- 给出 bootstrap/patch 新字段清单。

**Suggested Commit**

- `feat(extension): align bridge and bootstrap with coach-first state`

---

## 11. Finish Task Packages

### TP-40 Visual System Polish

**Mission**

在功能接通后，统一做最后一轮视觉收束。

**Product Promise**

Trainer 最终必须看起来像高级开发工具，而不是“许多功能拼起来的 AI 产品”。

**Read First**

- 全部前端组件结果
- [UI 设计文档](/Users/Apple/Desktop/trainer/docs/plans/2026-04-30-trainer-coach-first-ui-and-feature-design.md)
- `/Users/Apple/Desktop/trainer/extension/webview/src/styles/`

**Allowed Write Scope**

- `/Users/Apple/Desktop/trainer/extension/webview/src/styles/`
- Small surgical edits in component files for class name alignment only

**Forbidden / Do Not Touch**

- server files
- shared/protocol files
- host bridge/orchestration files
- large logic rewrites

**Dependencies**

- `TP-10`
- `TP-11`
- `TP-12`
- `TP-13`
- `TP-32`

**Inputs Expected From Upstream**

- 基本功能已联通

**Implementation Checklist**

1. 统一字体等级。
2. 统一 icon baseline。
3. 统一 spacing scale。
4. 统一 border/background 对比。
5. 收窄过宽、过厚、过高的组件。
6. 清理所有 AI 味过重的视觉表达。
7. 检查 coach/plan/settings 三视图是否同一设计语言。

**Acceptance**

- 打开侧栏后整体观感成熟、凝练、克制。

**Common Failure Modes**

- 试图在这一步做功能重构。
- 为了“精致”又引入过多装饰。

**Handoff Contract**

- 总结最终视觉 token / 密度 / 字号结论。

**Suggested Commit**

- `style(webview): polish coach-first visual system`

---

### TP-41 End-to-End Verification

**Mission**

做最终自动化和手工验收，确保蓝图不是“局部可用”，而是整体成品可用。

**Product Promise**

只有全链路通过，Trainer 才算真的从蓝图进入产品。

**Read First**

- 全部前述任务结果
- [implementation roadmap](/Users/Apple/Desktop/trainer/docs/plans/2026-04-30-trainer-coach-first-implementation-roadmap.md)

**Allowed Write Scope**

- `/Users/Apple/Desktop/trainer/server/tests/`
- Minimal bug-fix changes if tests暴露问题

**Forbidden / Do Not Touch**

- 大规模重构
- 新增大功能

**Dependencies**

- 所有前述任务

**Inputs Expected From Upstream**

- 产品核心路径已联通

**Implementation Checklist**

1. 跑 server 全量测试。
2. 跑 extension/webview 检查与构建。
3. 手工走四条黄金路径：
   - idea implementation
   - project idea mining
   - project adaptation
   - principle explanation
4. 验证 plan 可以承接 review queue 和 progress。
5. 验证 settings 可配大模型和偏好。
6. 验证没有一级 research 导航。
7. 汇总最终风险清单。

**Acceptance**

- `cd /Users/Apple/Desktop/trainer/server && python -m pytest tests/ -v`
- `npm run check --prefix /Users/Apple/Desktop/trainer/extension/webview`
- `npm run check --prefix /Users/Apple/Desktop/trainer/extension`
- `cd /Users/Apple/Desktop/trainer && npm run build`

**Common Failure Modes**

- 只验证 happy path。
- 忘记检查 mock data / bootstrap / real API 是否一致。

**Handoff Contract**

- 提供最终验收报告。
- 明确 residual risks。

**Suggested Commit**

- `test: verify coach-first trainer end-to-end experience`

---

## 12. 给 AI Worker 的统一启动提示词模板

如果你要把其中一个任务包直接分发给 AI，可以使用下面这个模板：

```md
你现在负责实现任务包 TP-xx。

先阅读：
- 任务包总册中 TP-xx 的完整章节
- 其中列出的 Read First 文件

你必须遵守：
- 只能修改 Allowed Write Scope
- 不能修改 Forbidden / Do Not Touch 中的文件
- 如果发现必须改 scope 外文件，停止并报告 blocked
- 不要顺手做额外优化
- 完成后必须按统一 Task Result 模板回传

你的目标不是“尽量多做”，而是“把这个任务包单独做到稳、做到可集成”。
```

---

## 13. 为什么这些任务包足够“省心”

这套任务包不是只写“做什么”，而是把最麻烦的几件事提前解决了：

- 先把前端壳层和样式层拆开，减少并行冲突。
- 先把 shared contract 定稳，减少前后端返工。
- 把 review persistence 单独打底，避免长期记忆悬空。
- 把 backend 能力拆成纯服务文件，尽量不互相写同一个地方。
- 把 provider/router/bridge 集中到 integration 阶段，避免总线文件被多人同时改。
- 把设计要求写进全局硬约束，避免风格做散。

也就是说，做完这些任务包之后，产品不只是“功能上接近目标”，而是`结构、实现、体验、协作方式`都在朝理想 Trainer 靠近。

---

## 14. 最终产品应该让人兴奋的地方

当这些任务包全部落地后，Trainer 最动人的地方会是：

- 你不需要学习一堆模块，就能直接开始用。
- 你告诉它一个想法，它不是立刻糊你一坨答案，而是像教练一样带你拆、带你做、带你验证。
- 你没有想法时，它又能从真实项目里替你发现值得做的机会。
- 你拿一个已经存在的项目来，它也能顺着你的意图陪你改，而不是只会建议重写。
- 你问“为什么”，它真的能讲明白原理。
- 它长期记得你的节奏、弱点和目标，但这些记忆不会吵闹地摆在前台。
- 整个界面非常安静，但每一次发送都很强。

`这才是一个真正值得长期留在 VS Code 侧边栏里的代码教练。`
