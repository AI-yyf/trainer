# Trainer Coach-First Implementation Plan

> Historical snapshot from the superseded three-view phase.
> Current Trainer IA lives in [docs/ui-contract.md](../ui-contract.md): `Coach / Plan / Resources / Training / Settings`.

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 把 Trainer 从“带研究面板的训练工作台”收束为 `Coach-first` 产品，并补齐长期教练、计划中枢、项目 idea 提炼、已完成项目改造指导、原理解释与复习调度能力。

**Architecture:** 以前端收束和后端编排增强并行推进。前端把一级结构稳定为 `对话 / 计划 / 设置`，后端在单次发送链路中加入 pedagogy、affect、review scheduler、project adaptation、principle explanation 和 project source scout 等能力层，并通过现有 provider、planner、memory、research、resource 脚手架整合输出。

**Tech Stack:** VS Code Extension Host (TypeScript), React + Zustand webview, FastAPI + Pydantic sidecar, SQLite repository, existing research/resource/memory services.

---

## 1. 范围与非目标

### 1.1 本轮必须完成的产品收束

- 一级导航稳定为 `对话 / 计划 / 设置`
- `研究`退出一级主视图，降为后台深入分析能力
- 对话成为唯一主入口，承接 idea 实现、项目改造指导、代码讲解、评审、计划更新
- 计划成为长期训练与复习中枢
- 设置成为完整模型/语言/记忆/工作区配置面板
- 前台只保留大模型配置，不要求 embedding 前台配置

### 1.2 本轮必须补齐的底层教练能力

- `Idea Implementation Coaching`
- `Project Idea Mining`
- `Completed Project Adaptation Guidance`
- `Principle Explanation`
- `Spaced Review Scheduling`
- `Affect / Tone Regulation`
- `Project Sourcing` 作为可调用底层能力

### 1.3 非目标

- 不做强制退出、强制全屏、写够代码才能关闭的专注控制模式主线
- 不新造独立研究 UI
- 不把记忆、诊断、资源、复习拆成多个一级导航
- 不在本轮追求 embedding 前台配置、复杂向量设置页

---

## 2. 代码现状与改造落点

### 2.1 后端主要落点

**Files:**
- Modify: `/Users/Apple/Desktop/trainer/server/app/core/models.py`
- Modify: `/Users/Apple/Desktop/trainer/server/app/api/routers.py`
- Modify: `/Users/Apple/Desktop/trainer/server/app/llm/provider_service.py`
- Modify: `/Users/Apple/Desktop/trainer/server/app/llm/prompts.py`
- Modify: `/Users/Apple/Desktop/trainer/server/app/memory/service.py`
- Modify: `/Users/Apple/Desktop/trainer/server/app/memory/models.py`
- Modify: `/Users/Apple/Desktop/trainer/server/app/db/repository.py`
- Modify: `/Users/Apple/Desktop/trainer/server/app/planner/service.py`
- Create: `/Users/Apple/Desktop/trainer/server/app/pedagogy/service.py`
- Create: `/Users/Apple/Desktop/trainer/server/app/pedagogy/implementation_coach.py`
- Create: `/Users/Apple/Desktop/trainer/server/app/pedagogy/project_idea_miner.py`
- Create: `/Users/Apple/Desktop/trainer/server/app/pedagogy/project_adaptation_coach.py`
- Create: `/Users/Apple/Desktop/trainer/server/app/pedagogy/principle_explainer.py`
- Create: `/Users/Apple/Desktop/trainer/server/app/pedagogy/project_source_scout.py`
- Create: `/Users/Apple/Desktop/trainer/server/app/affect/service.py`
- Create: `/Users/Apple/Desktop/trainer/server/app/memory/review_scheduler.py`

### 2.2 前端主要落点

**Files:**
- Modify: `/Users/Apple/Desktop/trainer/extension/webview/src/app/App.tsx`
- Modify: `/Users/Apple/Desktop/trainer/extension/webview/src/app/useWorkbenchState.ts`
- Modify: `/Users/Apple/Desktop/trainer/extension/webview/src/lib/types.ts`
- Modify: `/Users/Apple/Desktop/trainer/extension/webview/src/lib/mockData.ts`
- Modify: `/Users/Apple/Desktop/trainer/extension/webview/src/styles.css`
- Modify: `/Users/Apple/Desktop/trainer/extension/src/core/webviewBridge.ts`
- Modify: `/Users/Apple/Desktop/trainer/extension/src/core/workbenchData.ts`
- Modify: `/Users/Apple/Desktop/trainer/extension/src/provider/providerConfigStore.ts`
- Modify: `/Users/Apple/Desktop/trainer/shared/src/models.ts`
- Modify: `/Users/Apple/Desktop/trainer/shared/src/protocol.ts`

### 2.3 测试落点

**Files:**
- Modify: `/Users/Apple/Desktop/trainer/server/tests/test_api.py`
- Modify: `/Users/Apple/Desktop/trainer/server/tests/test_provider_service.py`
- Modify: `/Users/Apple/Desktop/trainer/server/tests/test_memory.py`
- Modify: `/Users/Apple/Desktop/trainer/server/tests/test_planner.py`
- Modify: `/Users/Apple/Desktop/trainer/server/tests/test_training_flow_integration.py`
- Modify: `/Users/Apple/Desktop/trainer/server/tests/test_repositories.py`
- Create: `/Users/Apple/Desktop/trainer/server/tests/test_pedagogy.py`
- Create: `/Users/Apple/Desktop/trainer/server/tests/test_review_scheduler.py`
- Create: `/Users/Apple/Desktop/trainer/server/tests/test_project_adaptation.py`

---

## 3. Workstream A: 前端 IA 收束为 Coach-first

### Task A1: 去除 research 作为一级主视图

**Files:**
- Modify: `/Users/Apple/Desktop/trainer/extension/webview/src/lib/types.ts`
- Modify: `/Users/Apple/Desktop/trainer/extension/webview/src/app/useWorkbenchState.ts`
- Modify: `/Users/Apple/Desktop/trainer/extension/webview/src/app/App.tsx`

**Step 1: 写出需要保留的视图模型**

- `SidebarView` 收束为 `coach | plan | settings`
- 保留后台 `research` 数据结构，但不作为前台主导航依赖

**Step 2: 先让类型变为编译失败点**

Run: `npm run check --prefix /Users/Apple/Desktop/trainer/extension/webview`
Expected: 暴露仍然依赖 `research` 视图的分支与文案

**Step 3: 最小实现**

- 删除一级视图里对 `research` 的展示入口
- 将相关 UI 入口降为 coach 消息流中的“深入分析”结果块
- 如暂时仍保留 research 数据，只保留内部兼容映射，不暴露一级 tab

**Step 4: 验证**

Run: `npm run check --prefix /Users/Apple/Desktop/trainer/extension/webview`
Expected: PASS

### Task A2: 重做消息流层级

**Files:**
- Modify: `/Users/Apple/Desktop/trainer/extension/webview/src/app/App.tsx`
- Modify: `/Users/Apple/Desktop/trainer/extension/webview/src/styles.css`
- Modify: `/Users/Apple/Desktop/trainer/extension/webview/src/lib/types.ts`

**Step 1: 明确三层消息类型**

- 用户消息
- 教练消息
- 结构化结果块

**Step 2: 为结果块增加明确 kind**

- `next_step`
- `review`
- `plan_update`
- `deep_analysis`
- `idea_implementation`
- `project_idea`
- `project_adaptation`
- `principle`

**Step 3: 最小实现**

- 让用户与教练内容一眼分清
- 让结果块成为消息流的二级层，不是到处散卡片
- 让“研究结果”在 UI 上只表现为 `deep_analysis`

**Step 4: 验证**

Run: `npm run build --prefix /Users/Apple/Desktop/trainer/extension/webview`
Expected: PASS

### Task A3: 做强计划视图

**Files:**
- Modify: `/Users/Apple/Desktop/trainer/extension/webview/src/app/App.tsx`
- Modify: `/Users/Apple/Desktop/trainer/extension/webview/src/lib/types.ts`
- Modify: `/Users/Apple/Desktop/trainer/extension/webview/src/styles.css`

**Step 1: 为计划页补齐以下区块**

- 目标摘要
- 当前阶段
- 任务队列
- 教练观察
- 该复习
- 最近进展
- 当前 idea/项目改造轨迹

**Step 2: 最小实现**

- 计划页不再只是 plan summary
- 能承接 review queue、idea progress、adaptation progress

**Step 3: 验证**

Run: `npm run build --prefix /Users/Apple/Desktop/trainer/extension/webview`
Expected: PASS

### Task A4: 设置页收束为完整系统面板

**Files:**
- Modify: `/Users/Apple/Desktop/trainer/extension/webview/src/app/App.tsx`
- Modify: `/Users/Apple/Desktop/trainer/extension/webview/src/lib/types.ts`
- Modify: `/Users/Apple/Desktop/trainer/extension/webview/src/styles.css`
- Modify: `/Users/Apple/Desktop/trainer/extension/src/provider/providerConfigStore.ts`

**Step 1: 只保留大模型配置**

- provider name
- base URL
- chat model
- API key
- test connection
- clear config
- open config file

**Step 2: 移除 embedding 必填心智**

- capability 里如果保留 embeddings 字段，也不在前台要求用户配置
- 默认文案不再强调 embedding model

**Step 3: 增加训练偏好设置入口**

- 语言
- 回答风格
- 是否跟随当前文件
- 是否启用长期记忆
- 是否启用复习提醒

**Step 4: 验证**

Run: `npm run check --prefix /Users/Apple/Desktop/trainer/extension/webview && npm run check --prefix /Users/Apple/Desktop/trainer/extension`
Expected: PASS

---

## 4. Workstream B: 单次发送链路升级为教练编排管线

### Task B1: 扩展核心模型

**Files:**
- Modify: `/Users/Apple/Desktop/trainer/server/app/core/models.py`
- Modify: `/Users/Apple/Desktop/trainer/server/app/memory/models.py`
- Modify: `/Users/Apple/Desktop/trainer/shared/src/models.ts`
- Modify: `/Users/Apple/Desktop/trainer/shared/src/protocol.ts`

**Step 1: 新增后端模型**

- `TeachingMode`
- `LearnerState`
- `TeachingDecision`
- `ImplementationGuide`
- `ProjectIdea`
- `ProjectOpportunitySignal`
- `ProjectAdaptationGuide`
- `AffectState`
- `ToneDecision`

**Step 2: 扩展快照模型**

- `MemorySnapshot.due_reviews`
- `MemorySnapshot.teaching_observations`
- `WorkbenchSnapshot.coaching_state`
- `WorkbenchSnapshot.review_queue_summary`
- `WorkbenchSnapshot.next_review_due`

**Step 3: 同步 shared/webview types**

- 让 extension / webview / server 的模型投影一致

**Step 4: 验证**

Run: `cd /Users/Apple/Desktop/trainer/server && python -m pytest tests/test_api.py -v`
Expected: 若 API 依赖模型变化，先失败再修复

### Task B2: 新增 pedagogy service

**Files:**
- Create: `/Users/Apple/Desktop/trainer/server/app/pedagogy/service.py`
- Create: `/Users/Apple/Desktop/trainer/server/tests/test_pedagogy.py`

**Step 1: 写失败测试**

覆盖以下输入判断：

- idea 实现意图
- 项目 idea 提炼意图
- 已完成项目改造意图
- 概念解释意图
- review/reflection 意图

**Step 2: 最小实现**

- 根据 message + current_file + memory snapshot + profile 输出 `TeachingDecision`

**Step 3: 验证**

Run: `cd /Users/Apple/Desktop/trainer/server && python -m pytest tests/test_pedagogy.py -v`
Expected: PASS

### Task B3: 新增 implementation coach / idea miner / adaptation coach

**Files:**
- Create: `/Users/Apple/Desktop/trainer/server/app/pedagogy/implementation_coach.py`
- Create: `/Users/Apple/Desktop/trainer/server/app/pedagogy/project_idea_miner.py`
- Create: `/Users/Apple/Desktop/trainer/server/app/pedagogy/project_adaptation_coach.py`
- Create: `/Users/Apple/Desktop/trainer/server/tests/test_project_adaptation.py`

**Step 1: 写失败测试**

- idea implementation 输出 `ImplementationGuide`
- project idea mining 输出 1 到 3 个高质量 `ProjectIdea`
- project adaptation 输出 `ProjectAdaptationGuide`

**Step 2: 最小实现**

- 使用当前文件、recent files、related files、diagnostics、plan、weaknesses 生成指导结构

**Step 3: 验证**

Run: `cd /Users/Apple/Desktop/trainer/server && python -m pytest tests/test_project_adaptation.py tests/test_planner.py -v`
Expected: PASS

### Task B4: 新增 affect service

**Files:**
- Create: `/Users/Apple/Desktop/trainer/server/app/affect/service.py`
- Modify: `/Users/Apple/Desktop/trainer/server/tests/test_provider_service.py`

**Step 1: 写失败测试**

- 用户烦躁时返回 `concise_rescue`
- 连续失败时提高 reassurance / avoid_overwhelm
- 正常推进时返回 `steady` 或 `encouraging`

**Step 2: 最小实现**

- 仅基于 message 语气 + recent failures + evaluation outcome 做初版 heuristics

**Step 3: 验证**

Run: `cd /Users/Apple/Desktop/trainer/server && python -m pytest tests/test_provider_service.py -v`
Expected: PASS

### Task B5: 升级 router turn pipeline

**Files:**
- Modify: `/Users/Apple/Desktop/trainer/server/app/api/routers.py`

**Step 1: 在 `execute_turn()` 前半段插入编排**

- `memory_snapshot = runtime.memory_service.snapshot(...)`
- `learner_state = pedagogy service infer state`
- `teaching_decision = pedagogy service decide mode`
- `tone_decision = affect service decide tone`
- `due_reviews = review scheduler due items`
- 条件触发 `implementation_guide / project_ideas / adaptation_guide / principle_notes / source_candidates`

**Step 2: 将这些结果注入 provider**

- prompt 输入扩大，但消息流输出保持安静

**Step 3: 写回 memory / plan**

- 记录 session summary
- 更新 review items
- 在必要时更新 current plan progress

**Step 4: 验证**

Run: `cd /Users/Apple/Desktop/trainer/server && python -m pytest tests/test_api.py tests/test_training_flow_integration.py -v`
Expected: PASS

---

## 5. Workstream C: 复习调度与长期记忆闭环

### Task C1: 新增 review item 数据模型与 repository 存储

**Files:**
- Modify: `/Users/Apple/Desktop/trainer/server/app/memory/models.py`
- Modify: `/Users/Apple/Desktop/trainer/server/app/db/repository.py`
- Modify: `/Users/Apple/Desktop/trainer/server/tests/test_repositories.py`

**Step 1: 写失败测试**

- `review_items` 表初始化
- 保存 / 查询 / 更新 due review item

**Step 2: 最小实现**

- 新表：`review_items`
- repository API：
  - `save_review_item`
  - `list_review_items`
  - `list_due_review_items`
  - `update_review_item`

**Step 3: 验证**

Run: `cd /Users/Apple/Desktop/trainer/server && python -m pytest tests/test_repositories.py -v`
Expected: PASS

### Task C2: 新增 review scheduler

**Files:**
- Create: `/Users/Apple/Desktop/trainer/server/app/memory/review_scheduler.py`
- Create: `/Users/Apple/Desktop/trainer/server/tests/test_review_scheduler.py`

**Step 1: 写失败测试**

- 首次学习后 1 天
- 成功后扩到 3 / 7 / 14 天
- 失败后回退

**Step 2: 最小实现**

- 用简化 spaced repetition 策略，不追求学术最优

**Step 3: 验证**

Run: `cd /Users/Apple/Desktop/trainer/server && python -m pytest tests/test_review_scheduler.py -v`
Expected: PASS

### Task C3: 让 planner 先消费 due review，再给新任务

**Files:**
- Modify: `/Users/Apple/Desktop/trainer/server/app/planner/service.py`
- Modify: `/Users/Apple/Desktop/trainer/server/tests/test_planner.py`

**Step 1: 写失败测试**

- due review 存在时优先推荐巩固任务
- 无 due review 时再按 phase progression 推荐

**Step 2: 最小实现**

- 保留现有 weakness review 逻辑
- 但先看 review items，再看 weaknesses

**Step 3: 验证**

Run: `cd /Users/Apple/Desktop/trainer/server && python -m pytest tests/test_planner.py -v`
Expected: PASS

---

## 6. Workstream D: Provider / Prompt 升级为真正的教练上下文

### Task D1: 扩展 provider_service 入参

**Files:**
- Modify: `/Users/Apple/Desktop/trainer/server/app/llm/provider_service.py`

**Step 1: 修改 `coaching_reply()` 与 `coaching_reply_stream()` 签名**

- 接收：
  - `teaching_decision`
  - `learner_state`
  - `tone_decision`
  - `review_due_items`
  - `implementation_guide`
  - `project_ideas`
  - `project_adaptation_guide`
  - `principle_notes`
  - `project_source_candidates`

**Step 2: 保持无 API key scaffold 模式**

- scaffold 回复也要反映更好的教练结构，而不是只回一个泛化 checkpoint

**Step 3: 验证**

Run: `cd /Users/Apple/Desktop/trainer/server && python -m pytest tests/test_provider_service.py -v`
Expected: PASS

### Task D2: 升级 prompts.py

**Files:**
- Modify: `/Users/Apple/Desktop/trainer/server/app/llm/prompts.py`

**Step 1: 重写 system prompt 结构**

- 教练目标
- 当前教学模式
- 当前语气策略
- 当前复习提示
- 当前 idea / adaptation / principle context

**Step 2: 保持 answer policy 兼容**

- `guided | balanced | direct`
- 同时映射到新的 coach-first 产品口径

**Step 3: 验证**

Run: `cd /Users/Apple/Desktop/trainer/server && python -m pytest tests/test_provider_service.py tests/test_api.py -v`
Expected: PASS

---

## 7. Workstream E: Extension 与 Webview 数据桥接

### Task E1: 同步 workbench snapshot 投影

**Files:**
- Modify: `/Users/Apple/Desktop/trainer/extension/src/core/workbenchData.ts`
- Modify: `/Users/Apple/Desktop/trainer/extension/src/core/webviewBridge.ts`
- Modify: `/Users/Apple/Desktop/trainer/extension/webview/src/lib/types.ts`
- Modify: `/Users/Apple/Desktop/trainer/extension/webview/src/lib/mockData.ts`

**Step 1: 暴露新的 coach-first 字段**

- coaching state
- due reviews
- teaching observations
- idea progress
- adaptation progress

**Step 2: 保证 mock data 不崩**

- mock 数据必须覆盖新增字段，便于独立 UI 开发

**Step 3: 验证**

Run: `npm run build --prefix /Users/Apple/Desktop/trainer/extension/webview && npm run build --prefix /Users/Apple/Desktop/trainer/extension`
Expected: PASS

### Task E2: Provider 设置桥接

**Files:**
- Modify: `/Users/Apple/Desktop/trainer/extension/src/provider/providerConfigStore.ts`
- Modify: `/Users/Apple/Desktop/trainer/extension/webview/src/app/App.tsx`

**Step 1: 统一前后端 provider 配置口径**

- 前台不再强调 embedding
- 支持自定义 base URL、model、API key、测试连接、清空、打开配置

**Step 2: 验证**

Run: `npm run check --prefix /Users/Apple/Desktop/trainer/extension && npm run check --prefix /Users/Apple/Desktop/trainer/extension/webview`
Expected: PASS

---

## 8. Workstream F: 集成测试与验收

### Task F1: API 与训练流集成测试

**Files:**
- Modify: `/Users/Apple/Desktop/trainer/server/tests/test_api.py`
- Modify: `/Users/Apple/Desktop/trainer/server/tests/test_training_flow_integration.py`

**Step 1: 增加用例**

- 发送 idea，返回 implementation guidance
- 请求项目 idea，返回 1 到 3 个 project ideas
- 请求改造现有项目，返回 adaptation guide
- due review 存在时，plan 优先给复习动作

**Step 2: 验证**

Run: `cd /Users/Apple/Desktop/trainer/server && python -m pytest tests/test_api.py tests/test_training_flow_integration.py -v`
Expected: PASS

### Task F2: Webview 构建与类型验收

**Files:**
- No code changes required if previous tasks pass

**Step 1: 运行前端检查**

Run: `npm run check --prefix /Users/Apple/Desktop/trainer/extension/webview`
Expected: PASS

**Step 2: 运行扩展检查**

Run: `npm run check --prefix /Users/Apple/Desktop/trainer/extension`
Expected: PASS

**Step 3: 运行整体构建**

Run: `cd /Users/Apple/Desktop/trainer && npm run build`
Expected: PASS

### Task F3: 手工验收清单

**Files:**
- Verify in local VS Code extension / app browser

**Step 1: 验证主导航**

- 只看到 `对话 / 计划 / 设置`

**Step 2: 验证消息流**

- 用户 / 教练 / 结果块层级清晰
- 深入分析不再是独立研究页

**Step 3: 验证设置**

- 能配大模型
- 不要求 embedding
- 支持语言与风格

**Step 4: 验证教练能力**

- 可以让教练带着实现一个 idea
- 可以让教练从现有项目提炼 idea
- 可以让教练指导改造已有项目
- 可以要求解释原理

---

## 9. 推荐执行顺序

1. 先做 `Workstream B + C` 的最小后端能力骨架，否则前端会继续假装强大。
2. 再做 `Workstream E + A`，把前台真正收束到 coach-first。
3. 最后做 `Workstream D + F`，让 provider/prompt 和集成体验对齐。

---

## 10. 建议提交切片

- `feat(server): add pedagogy and review scheduler skeleton`
- `feat(server): add implementation coach and project adaptation flow`
- `feat(webview): simplify nav to coach plan settings`
- `feat(webview): redesign coach message flow artifacts`
- `feat(settings): complete provider and training preferences panel`
- `test: cover coach-first teaching and adaptation flows`
