# Trainer Learning-Loop Master Delivery Index

> Historical snapshot from the superseded three-view phase.
> Current Trainer IA lives in [docs/ui-contract.md](../ui-contract.md): `Coach / Plan / Resources / Training / Settings`.

> **For Claude/Codex:** REQUIRED EXECUTION MODE: implement one task document at a time, keep write scope tight, and stop for review between tasks.

**Goal:** 把 Trainer 从“有教练雏形的插件”推进成“会长期陪你写代码、会持续学习、会沉淀教学能力”的长期代码教练。

**Architecture:** 前台始终收束为 `对话 / 计划 / 设置`。真正的强能力全部沉到底层闭环里：项目理解、用户理解、外部资料学习、知识沉淀、教学生成、复习调度、效果评估、自我改进。

**Tech Stack:** VS Code Extension Host, React + Zustand webview, FastAPI sidecar, SQLite repository, shared TS protocol, pedagogy/memory/planner/research/resource services.

---

## 1. 最终目标不是“功能多”，而是闭环完整

Trainer 的最终目标是形成下面这条长期教练闭环：

1. **观察你和你的项目**
   - 读取当前工作区、当前文件、选区、诊断、历史对话、长期目标、最近卡点。
2. **理解项目结构和训练机会**
   - 看懂当前项目的入口、模块边界、改造路径、训练机会和可验证步骤。
3. **按需向外学习**
   - 能联网查最新实践，下载代码库、README、issue、PR、论文、文档，并提取有用内容。
4. **清洗并沉淀知识**
   - 去重、打来源分、判断时效，沉淀为概念卡、模式卡、反例卡、练习素材和教学策略。
5. **自然教学**
   - 像 GPT/Codex 一样自然对话，但背后能自动调取项目理解、长期记忆、外部知识和教学策略。
6. **计划与训练**
   - 让 `计划` 视图成为长期训练主线，而不是展示型卡片。
7. **评估与记忆**
   - 根据代码结果、测试、重复错误、回答质量更新你的掌握度、弱点和复习节奏。
8. **自我改进**
   - 教练会根据教学结果更新自己的知识库、训练题策略和讲解套路。

只有这 8 个环节贯通，Trainer 才算真正“会学习”。

## 2. 当前代码基线

当前项目已经具备一部分教练底座，可作为这轮分阶段任务的出发点：

- 后端已有服务编排入口：[runtime.py](../../server/app/api/runtime.py)
- 教学决策与模式骨架：[pedagogy/service.py](../../server/app/pedagogy/service.py)
- 长期记忆与复习节奏骨架：[memory/service.py](../../server/app/memory/service.py)、[review_scheduler.py](../../server/app/memory/review_scheduler.py)
- 研究仍是后台兼容通道，而非真正联网学习层：[research/service.py](../../server/app/research/service.py)
- URL 摄取存在，但默认不开网络抓取：[ingest/service.py](../../server/app/ingest/service.py)

这意味着本轮计划不是从零开始，而是要把已有雏形推进成完整系统。

## 3. 交付原则

- 顶层 IA 只能保留 `对话 / 计划 / 设置`
- `研究` 只能作为后台能力，不再回到一级视图
- 强能力来自后端编排，不来自前台堆开关
- 所有任务都必须能独立推进、独立验收、独立交接
- 所有新知识能力都必须有“来源、时效、可信度、沉淀方式”
- 所有教学能力都必须可回写到记忆，而不是一次性输出

## 4. 阶段顺序

按下面顺序执行：

1. `A1 + A2` 先把入口和输入主链做稳定、真实、可解释
2. `B1 + B2` 把对话流做成自然、低理解成本的教练信息流
3. `C1 + C2` 把计划变成长期训练主线
4. `D1 + D2` 把设置做成真实可用的系统面板
5. `E1 + E2` 把记忆和复习节奏做成长期连续体
6. `F1 + F2 + F3` 把项目理解、idea 落地、项目改造训练打通
7. `G1 + G2` 打通外部资料学习和可信摄取
8. `H1 + H2 + H3` 建立知识沉淀、教学模式、教学效果自我改进
9. `I1 + I2` 做端到端联调、安装分发、视觉和性能收口

## 5. 任务文档清单

- [A1 Coach Shell And Truthful States](./2026-05-02-trainer-task-A1-coach-shell-and-truthful-states.md)
- [A2 Composer Context And Resource Attachments](./2026-05-02-trainer-task-A2-composer-context-and-resource-attachments.md)
- [B1 Natural Chat Message System](./2026-05-02-trainer-task-B1-natural-chat-message-system.md)
- [B2 Background Intelligence In Message Flow](./2026-05-02-trainer-task-B2-background-intelligence-in-message-flow.md)
- [C1 Plan Mainline Experience](./2026-05-02-trainer-task-C1-plan-mainline-experience.md)
- [C2 Plan Lifecycle And Replanning Engine](./2026-05-02-trainer-task-C2-plan-lifecycle-and-replanning-engine.md)
- [D1 Provider And Model Settings System](./2026-05-02-trainer-task-D1-provider-and-model-settings-system.md)
- [D2 Language Teaching And Memory Policies](./2026-05-02-trainer-task-D2-language-teaching-and-memory-policies.md)
- [E1 Learner Memory And Coaching Continuity](./2026-05-02-trainer-task-E1-learner-memory-and-coaching-continuity.md)
- [E2 Review Rhythm And Affect Regulation](./2026-05-02-trainer-task-E2-review-rhythm-and-affect-regulation.md)
- [F1 Workspace Understanding Engine](./2026-05-02-trainer-task-F1-workspace-understanding-engine.md)
- [F2 Idea-To-Code Coaching Engine](./2026-05-02-trainer-task-F2-idea-to-code-coaching-engine.md)
- [F3 Project Idea Mining And Adaptation Training](./2026-05-02-trainer-task-F3-project-idea-mining-and-adaptation-training.md)
- [G1 External Research And Source Acquisition](./2026-05-02-trainer-task-G1-external-research-and-source-acquisition.md)
- [G2 Knowledge Ingestion Curation And Trust](./2026-05-02-trainer-task-G2-knowledge-ingestion-curation-and-trust.md)
- [H1 Teaching Knowledge Base](./2026-05-02-trainer-task-H1-teaching-knowledge-base.md)
- [H2 Teaching Modes And Exercise Generation](./2026-05-02-trainer-task-H2-teaching-modes-and-exercise-generation.md)
- [H3 Learning Evaluation And Self-Improvement Loop](./2026-05-02-trainer-task-H3-learning-evaluation-and-self-improvement-loop.md)
- [I1 End-To-End Integration And VSIX Delivery](./2026-05-02-trainer-task-I1-end-to-end-integration-and-vsix-delivery.md)
- [I2 Quality Polish Performance And Release Acceptance](./2026-05-02-trainer-task-I2-quality-polish-performance-and-release-acceptance.md)

## 6. 全局完成定义

全部任务完成后，Trainer 应该达到下面这条用户级标准：

- 用户第一次打开就知道“这是一个长期代码教练”
- 没有 API key 时不会黑屏，而是明确引导去设置
- 主要交互从 `对话` 进入，`计划` 承接长期主线，`设置` 完成接入与偏好配置
- 中文用户默认得到自然中文讲解，英文同理
- 教练能基于当前项目给训练题、改造建议、实现路线和原理解释
- 教练能记住长期目标、弱点、进展和下一步，并安排复习
- 教练能按需联网查资料、下载代码库/论文/文档，并把有用内容沉淀下来
- 教练会根据教学效果不断调整自己的计划、知识和讲解策略

## 7. 每个任务完成后的统一回传格式

```md
## Task Result

Task: A1
Status: done / partial / blocked

Files changed:
- /absolute/path/one
- /absolute/path/two

What was completed:
- ...

Validation:
- command
- result

Open risks:
- ...

Next recommended task:
- A2
```
