# Trainer

<div align="center">

<img src="assets/banner.png" alt="Trainer —— 训练你的 AI · 与 AI 共同成长 · 人与 AI 共同成长的地方" width="100%" />

**一位住进你 VS Code 侧边栏的长期编程教练。**

**它规划、操练、验证，并记住关于你的一切 —— 但从不替你写代码。**

**// 输出 ≠ 成长 // 验证 + 复习 = 成长**

[English](README.md) · 简体中文 · [Español](README_es-ES.md) · [Français](README_fr-FR.md) · [Deutsch](README_de-DE.md) · [日本語](README_ja-JP.md) · [한국어](README_ko-KR.md) · [Português](README_pt-BR.md)

[![Release](https://img.shields.io/badge/release-v1.0.3-1f6feb)](https://github.com/AI-yyf/trainer/releases/tag/v1.0.3)
[![License](https://img.shields.io/badge/license-MIT-3fb950)](LICENSE)
[![Platforms](https://img.shields.io/badge/platforms-macOS%20%C2%B7%20Linux%20%C2%B7%20Windows-8b949e)](#安装)
[![Tests](https://img.shields.io/badge/tests-3%2C328%20cases-F59E0B)](#质量门禁)
[![i18n](https://img.shields.io/badge/i18n-8%20languages-A78BFA)](#i18n--八种语言)

[为什么](#为什么需要-trainer) ·
[安装](#安装) ·
[配置](#三步搞定没有第四步) ·
[机制](#核心机制) ·
[五大视图](#五大视图) ·
[对比](#对比) ·
[五分钟演示](#五分钟演示) ·
[设计](#为什么它感觉不一样) ·
[架构](#架构) ·
[安全](#安全模型) ·
[质量](#质量门禁) ·
[致谢](#致谢) ·
[🎭 角色阵容](docs/CAST.md)

</div>

---

## 为什么需要 Trainer

> 开发者停滞不前，不是因为缺教程，
> 而是因为没有什么能把学习的闭环扣上。

与 LLM 的对话，一结束就蒸发；视频是单向灌输；周二似懂非懂的概念，到周五已无影无踪。

更糟的是 **vibe coding** —— 让 AI 替你写了三个月代码，而你一点都没看懂。

收藏夹越堆越高，产出却纹丝不动。仓库越来越大，脑子却越来越空。

**Trainer 从编辑器内部解决这个问题。**

它不是一个聊天壳子 —— 它是一位带着记忆、课程表和考核制度的教练：

- 它会把你的学习**规划**成阶段，并追踪你真实所在的位置 —— 而不是你自我感觉的位置
- 它用闪卡、理论操练和场景实验来**训练**你
- 它对照你的真实代码**验证**掌握程度 —— 嘴上聊过 FastAPI 不算数，当前文件能证明才算数
- 它跨会话、跨项目、跨周地**记住**你，并按 FSRS 遗忘曲线安排复习
- 它**绝不替你写生产代码** —— 你来写，它来教，**你们一起成长**

<div align="center">

| vibe coding · 当下常态 | Trainer · 本该如此 |
|:---:|:---:|
| `def ship(code):` <br> `    ai.write(code)` <br> `# 你懂了吗？` <br> `    return forget(code)` | `def ship(code):` <br> `    you.write(code)` <br> `    ai.verify(code)` <br> `    you.recall(code)` <br> `    return grown(code)` |
| 输出 = 遗忘 | 输出 + 记忆 + 复习 = 成长 |

</div>

---

## 安装

**通过 VSIX 安装（预构建，覆盖三大平台）：**

从 [v1.0.3 release](https://github.com/AI-yyf/trainer/releases/tag/v1.0.3) 下载适配你平台的 `.vsix`（`darwin-arm64` / `linux-x64` / `win32-x64`）。

VS Code 扩展面板 → `···` → *从 VSIX 安装* → 重载窗口。

**从源码安装：**

```bash
git clone https://github.com/AI-yyf/trainer.git
cd trainer && npm install
cd server && python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cd .. && npm run build
```

用 VS Code 打开本仓库并按 F5（Extension Development Host），或直接安装打包好的 VSIX。

**环境要求：** VS Code ≥ 1.96 · Python ≥ 3.12（源码构建）· macOS / Linux / Windows

---

## 三步搞定，没有第四步

1. 打开 Trainer 侧边栏 → 设置
2. 粘贴中转站连接信息（从中转站控制台复制的整段 JSON 会被自动解析 —— endpoint 和 key 已经帮你拆好）→ 再粘贴 API key
3. 点击 **Save & Connect**

Trainer 会拉取实时模型列表、选好默认模型，并一次性验证 streaming 通路。

key 不对就明确报 `invalid_key_or_permission` —— 而不是一个含糊的转圈。

<p align="center">
  <img src="assets/screenshots/settings-quick-setup.png" alt="快速配置" width="420" />
</p>

---

## 核心机制

### ① 验证门禁 —— 代码是你写的，也让代码来证明

训练卡在对你真实文件跑完验证之前，无法推进到「已实现」；手动「标记完成」按钮是刻意不存在的。

伪装学习最快的方式，就是把每个勾都打上。Trainer 拒绝这条路。

<p align="center"><img src="assets/feat-verify.png" alt="验证门禁" width="720" /></p>

**实现方式：**
- 服务端 `EvaluatorService` 会把当前文件**复制**进 `tempfile.TemporaryDirectory`，跑完 ruff + pyright + pytest 后拆除 tempdir
- 工具**绝不会**在学习者的项目里运行 —— 不产生 `.pytest_cache` 污染
- 每次检查都对照显式的 `acceptance_criteria` + `expected_symbols` 列表，逐条报告 Matched/Missing 明细
- 代码：`server/app/evaluator/service.py:198-312`

### ② 长期记忆 —— FSRS 遗忘曲线调度

掌握状态、薄弱点和到期复习都存在 SQLite 里，并由 Qdrant 做语义检索。

复习按 FSRS 遗忘曲线浮现 —— 快忘的时候才出现，还记得的时候就保持安静。

<p align="center"><img src="assets/feat-memory.png" alt="长期记忆" width="720" /></p>

**实现方式：**
- 两层记忆：结构化（`StructuredMemoryService`，约 480 条记录）+ 语义化（Qdrant + sentence-transformer 离线兜底）
- **`_should_delay_live_thread_reviews()`** —— 当灵感实现流程进行中时，复习会被主动抑制，思路永不被打断
- **可迁移技能跨工作区 fail closed**：在单个项目里成功绝不等于全局掌握；晋升要求在 ≥2 个工作区里都通过
- 关键代码：`server/app/memory/service.py:1357-1597` · `transfer_skills.py:81-113` · `review_scheduler.py:522-544`

### ③ 训练循环 —— 到期出现，验证后才推进

闪卡、理论操练和场景实验都排在训练视图的队列里：复习到期才出现，卡片验证后才推进，对话里的任何知识缺口都能一键转成训练卡。

<p align="center"><img src="assets/feat-training.png" alt="训练循环" width="720" /></p>

**实现方式：**
- **五阶段状态机** `LEARN → TRY → VERIFY → REFLECT → RETURN`，每次流转都写入 `phase_history`
- **可信验证来源白名单**：`automated_test` / `evaluator` / `ide_current_file` / `server_evaluator` / `test_runner` / `verification_service` —— 口头声称「我做完了」永远推不动卡片
- 卡片 UI 的 `onSkip` / `onRate` 处理器已被标记为 **`@deprecated Unused`** —— 唯一的推进路径是 `onCardStatusTransition`
- 关键代码：`server/app/training/handoff.py:40-47` · `extension/webview/src/components/training/TrainingCardPanel.tsx:78-85`

### ④ 你来写，教练引导

教练会读你的文件、查 diagnostics、搜工作区 —— 但生产代码永远出自你的手。

`direct` 模式即刻作答；`coach-first` 模式让你先想。**认知负担是你的，不是它的。**

<p align="center"><img src="assets/feat-youwrite.png" alt="你来写，教练引导" width="720" /></p>

**实现方式：**
- `PedagogyService` 每一轮都产出一份 12 字段的 `ImplementationGuide` —— 每个字段都是对教练下一步能问什么的约束
- `ImplementationCoach._current_step` 锚定在「第一个失败路径」或「第一个已知入口」—— 永远不会是「先探索一下代码库」
- 情绪驱动的语气：连续失败两次后，`AffectService` 切入 `concise_rescue` 模式
- 关键代码：`server/app/pedagogy/implementation_coach.py:140-186` · `affect/service.py:142-152`

---

## 五大视图

> 五个固定的顶级视图。每个视图都有严格的职责边界。

| 视图 | 定位 | 一句话 |
|-----------|------|--------|
| **Coach（对话）** | streaming 聊天 | **入口**：工具调用 + `$` 技能面板 + 图片附件 + 回答模式 |
| **Plan（学习）** | 学习计划 | **地图**：阶段、进度、证据、计划冻结/解冻 |
| **Resources（资料）** | 资料库 | **书架**：FTS5 搜索 + 三级沙箱预览 + 可恢复回收站 |
| **Training（训练）** | 训练 | **训练场**：FSRS 闪卡 + 理论操练 + 场景实验 + 验证门禁 |
| **Settings（设置）** | 设置 | **控制台**：59 条命令 + 端点测速 + thinking 强度 + 工作区准入 |

<p align="center">
  <img src="assets/screenshots/plan.png" alt="学习视图" width="260" />
  <img src="assets/screenshots/resources.png" alt="资料视图" width="260" />
  <img src="assets/screenshots/training.png" alt="训练视图" width="260" />
</p>

### Coach 视图（入口）

streaming 教练聊天，支持工具调用、`$` 技能面板、图片附件、回答模式、上下文用量环、会话历史与分享。

**每条教练回复下方都带着三个快捷操作：**

- **以 Markdown 复制回复**
- **存入资料库**（可搜索、可预览）
- **转成可验证的训练卡** —— 按消息粒度，不是按会话

<p align="center"><img src="assets/screenshots/message-actions.png" alt="消息级操作" width="520" /></p>

### 自定义 `$` 技能 —— 创建、分享、安装

输入 `$` 打开技能面板：除了内置技能，你可以把自己的提示词封装成带触发词和关键词的技能，分享给别人，或安装别人分享的技能 —— **全程纯数据通道，不执行任何代码**。

<p align="center">
  <img src="assets/screenshots/skill-deck.png" alt="技能面板" width="380" />
  <img src="assets/screenshots/skill-manager.png" alt="技能管理" width="380" />
</p>

<p align="center"><img src="assets/feat-skills.png" alt="自定义技能" width="720" /></p>

**实现方式：**
- 自定义技能是纯 JSON 导入 —— `{ _type, version, trigger, title, prompt, keywords }`；没有 `eval`，没有 `Function()`，没有代码路径
- 硬上限：prompt ≤ 4000 字符，title ≤ 160，keywords ≤ 16，用户技能 ≤ 24 个
- 触发词冲突时内置优先 —— 用户导入的 `$explain` 无法遮蔽内置版本
- 关键代码：`shared/src/skillCatalog.ts:614-764`

---

## 对比

> Trainer 不是来取代谁的 —— 它填补的是一块没人认领的空白。

| 维度 | vibe 工具 | 聊天 IDE | 闪卡应用 | **Trainer** |
|---|---|---|---|---|
| 替你写代码 | ✅ | ✅ | ❌ | ❌ |
| 验证你的代码 | ❌ | ❌ | ❌ | ✅ 对照当前文件 |
| 跨会话记忆 | ⚠️ 上下文窗口 | ⚠️ 摘要 | ✅ | ✅ SQLite + Qdrant |
| FSRS 间隔重复 | ❌ | ❌ | ✅ | ✅ + 实时流程抑制 |
| 工作区权限分级 | ❌ | ⚠️ 信任弹窗 | ❌ | ✅ 6 级 + 远程硬锁 |
| 卡片推进受门禁管控 | ❌ | ❌ | ⚠️ 手动打勾 | ✅ 强制已验证 |
| 可迁移技能晋升 | ❌ | ❌ | ❌ | ✅ 跨工作区 fail closed |
| i18n | ⚠️ | ⚠️ | ⚠️ | ✅ 600+ 条目 × 8 语言 |
| 测试规模 | 闭源 | 闭源 | 闭源 | ✅ **3,328 个用例**（公开） |
| 拒绝替你写 | ❌ | ❌ | 不适用 | ✅ 一条哲学底线 |

> 一句话：别的工具让你写得更快；Trainer 让你真的在写。

---

## 五分钟演示

> 你的头五分钟，实际上是这样的。

### T+0:00 —— 打开侧边栏

点击活动栏里的 Trainer 图标。侧边栏打开，默认落在 **Coach 对话视图**。

<p align="center">
  <img src="assets/screenshots/settings-quick-setup.png" alt="首次打开" width="420" />
</p>

### T+0:30 —— 配置 Provider（仅首次）

设置 → 粘贴中转站 JSON + API key → Save & Connect。

Trainer 拉取实时模型列表、选定默认模型、验证 streaming。key 不对 → 明确告诉你 `invalid_key_or_permission`。

### T+1:30 —— 第一次对话

切到 Coach，输入：`@current_file explain what this async/await is doing?`

Trainer 流式回复。**它不会重写你的代码。** 它指向第 17 行：「这是 fan-out」；第 23 行：「这是 barrier。想真正学会它，就写一个能在中途取消某个 task 的版本 —— 我会陪你跑验证。」

### T+2:30 —— 一键生成训练卡

悬停到这条回复上。三个按钮：`Copy` / `Save to library` / **`Create training card`**。

点击 `Create training card` → 卡片生成 → 进入训练视图 → FSRS 把它排到 3 天后。

### T+4:00 —— 自己写，接受验证

代码你来写。Trainer **绝不代笔**。

打开训练 → 翻卡 → 查看通过标准 → 动手写 → 点击 `Request verification` → Trainer 在沙箱里跑 ruff + pyright + pytest → 报告通过，或标出缺失的标准项。

### T+5:00 —— 第二天

明天打开 VS Code：Trainer 自动恢复 —— 上次会话、计划、卡片进度都在原处。

那张卡正在 FSRS 节律盘上脉动 —— 今天到期。

**你已经不是 vibe coding 型开发者了。**

---

## 为什么它感觉不一样

### 诚实的失败

key 不对就报 `invalid_key_or_permission`；连不上就报 `network`；回复解析坏了就说「这条回复没读清楚，请重发」—— **坏掉的输出绝不化妆成答案**。

不认识的网关，不会被默默当成 OpenAI 兼容。

**实现方式：** 错误分类器（`provider_service.py:2823-2874`）+ 凭证清洗（`provider_protocols.py:640-681`）+ 未知指纹探测（`provider_gateway.py:39-70`）。

### 端点测速

多个 Provider 端点并行竞速（**先预热以抵消冷启动惩罚，再计时**）。

500 ms 内绿灯，1 s 内黄灯。点一下就切换到最快端点。

<p align="center"><img src="assets/feat-speed.png" alt="端点测速" width="720" /></p>

**实现方式：** `Promise.all` + 每个 URL 在正式计时前先发一个丢弃的预热请求（`providerWebviewCommands.ts:2275-2352`）。

### 上下文用量环

对话顶部有一枚实时上下文用量环 —— **压缩发生之前，你就看得见它要来**。

### Thinking 强度

按每个模型的证据设门禁 —— 声明的能力 **或** 实测探针。绝不盲目透传。

### 火力全开的资料库

<p align="center"><img src="assets/feat-library.png" alt="火力全开的资料库" width="720" /></p>

上传即索引，FTS5 全文搜索，**三级沙箱预览**（A 富预览 / B 转换预览 / C 元数据 + 原生编辑器兜底），删除进可恢复的回收站。

**三区物理隔离**：工作区 / 沙箱 / 回收站。绝不混用。

教练回复一键入库 —— **能被你搜回来的东西，才是你真正学会的东西**。

### 长周期状态

计划可冻结、可解冻；会话能挺过重启；卡片进度存在 SQLite；复习按 FSRS 曲线到期 —— **而不是躺在待办清单里**。

---

## 架构

### 系统拓扑

```
┌─────────────────────────────────────────────────────────────┐
│                    VS Code Window                            │
│  ┌───────────────────────────────────────────────────────┐  │
│  │   Trainer Sidebar                                     │  │
│  │   (React 19 + Zustand, 8-language i18n, 24 governance)│  │
│  │                                                       │  │
│  │   ─── postMessage ─── CommandRegistry ── 59 commands  │  │
│  │                                       │               │  │
│  └───────────────────────────────────────┼───────────────┘  │
│                                          │                   │
│                          ┌───────────────▼──────────────┐    │
│                          │  FastAPI sidecar (127.0.0.1)│    │
│                          │  PyInstaller --onedir frozen│    │
│                          │  (250 MB / 6 platform arch) │    │
│                          │                              │    │
│                          │  ├── ReAct agent loop        │    │
│                          │  │   (dual-channel stream)   │    │
│                          │  ├── Pedagogy (12-field guide)│   │
│                          │  ├── Affect (failures→rescue)│    │
│                          │  ├── Memory                  │    │
│                          │  │   SQLite + Qdrant semantic│    │
│                          │  ├── FSRS scheduler          │    │
│                          │  ├── Authority (6 tiers)     │    │
│                          │  ├── Provider (5 protocols)  │    │
│                          │  ├── Training handoff (5 ph.)│    │
│                          │  └── Resources (3 zones+FTS5)│    │
│                          │                              │    │
│                          │  ─── 24 shared pure fns ────│    │
│                          │      (host + webview + test)  │    │
│                          └──────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

### 目录布局

| 目录 | 内容 | 体量 |
|---|---|---|
| `extension/src/` | 宿主：命令、工作区信任、密钥存储、sidecar 生命周期 | ~30k 行 TS |
| `extension/webview/` | React 工作台：5 视图 + Zustand + 8 语言 | ~50k 行 TSX |
| `extension/tests/` | node:test 套件（220 个文件 / 1,679 个用例） | 73,744 行 |
| `server/app/` | FastAPI 大脑：agent / pedagogy / memory / FSRS / training | ~120k 行 Python |
| `server/tests/` | pytest 套件（159 个文件 / 1,649 个用例） | 106,422 行 |
| `shared/src/` | **共享纯函数 + 24 个治理模块**（宿主 + webview + 测试） | ~3k 行 TS |
| `extension/bundled/` | 打进 VSIX 的 sidecar（PyInstaller onedir） | ~250 MB |

### 唯一的标准信封

> Trainer 的所有 HTTP 响应（`/health` 除外）都返回**同一个** `WorkbenchSnapshot`（31 个字段）。

| 类别 | 示例字段 | 生产者 |
|---|---|---|
| 会话 | `messages`, `coaching_state`, `learner_state` | `pedagogy/service.py` |
| 计划 | `plan`, `global_plan`, `project_plan_link`, `current_task` | `planner/service.py` |
| 记忆 | `memory`, `selected_teaching_assets`, `next_review_due` | `memory/service.py` |
| 教学 | `teaching_decision`, `implementation_guide`, `project_ideas` | `pedagogy/*` |
| 情绪 | `affect_state`, `tone_decision` | `affect/service.py` |
| 训练 | `evaluation`, `review_queue_summary` | `training/*` |
| 元信息 | `context_id`, `sidecar_status`, `snapshot_revision`, `active_panel` | `api/runtime.py` |

**为什么是单一信封：**
- webview **完全从这一个对象渲染** —— 12 个子系统各自写入字段，一次水合
- **轻量 CRDT 增量同步**：每个快照带 `snapshot_revision`；`GET /snapshot?since_revision=N` 仅在 N 过期时下发全量数据，否则返回 `{unchanged: true}`
- 关键代码：`server/app/core/models.py:2304-2336` · `server/app/api/routers.py:11648-11710`

### 共享治理模块

> Trainer 的架构主轴是 **24 个纯函数治理模块** —— 宿主、webview、测试跑的是同一套确定性逻辑。

| 模块 | 职责 |
|---|---|
| `planGovernance` · `masterPlanGovernance` | 计划编辑、跨项目总计划 |
| `trainingHandoffGovernance` · `trainingRecoveryGovernance` · `trainingReliabilityGovernance` | 卡片路由、恢复、可靠性 |
| `reviewQueueGovernance` · `reviewArtifactGovernance` | FSRS 队列排序、证据复核 |
| `workspaceAuthority` · `workspaceRecoveryGovernance` | 6 级权限、恢复 |
| `suggestedActionGovernance` · `conversationCandidateGovernance` | 建议操作、会话仲裁 |
| `transferEvidenceGovernance` · `transferSkillGovernance` | 跨项目证据、技能晋升 |
| `coachOrientationGovernance` · `resourcesOrientationGovernance` | Coach/资料视图定向 |
| `settingsCapabilityGovernance` · `operationReliabilityGovernance` | 设置能力门控、操作可靠性 |
| `hostLastTestGovernance` · `providerModelPolicy` | Provider 最近测试、模型策略 |
| `sandboxNetworkCapabilityNarrative` · `projectLaneGovernance` | 沙箱能力叙事、项目车道 |
| `previewAssets` · `materialRecommendationGovernance` | 预览资产分级、资料推荐 |

**为什么：** 同一个 `resolveSuggestedActionGovernance` 跑在宿主、webview 和测试里 —— **三方一致，零往返**。

---

## 安全模型

- API key 存放在 **VS Code SecretStorage**（操作系统级加密）—— 不进配置文件，不进 git
- 工作区遵循 **VS Code 原生信任机制** —— 未受信任时拒绝一切写入
- **6 级权限阶梯**：INSPECT < ANNOTATE < REORGANIZE < GENERATE < APPLY < DESTRUCTIVE —— 默认只读；写入/删除/修改需要逐级提升的 attestation
- **远程工作区硬锁在 REORGANIZE 以下** —— 即使用户授权也无法提级
- **删除先进回收站**：不存在 `delete` 操作，只有 `move to <root>/.trash/<timestamp-uuid>/`
- 沙箱预览执行严格的**路径治理** —— 越界路径一律 422
- 技能分享是**纯数据导入** —— 字段长度封顶、内置优先，**根本不存在代码路径**

**关键代码：** `server/app/workspace/authority.py:33-962` · `extension/src/provider/providerConfigStore.ts` · `shared/src/skillCatalog.ts:614-764`

---

## 质量门禁

> Trainer 把自己的验证体系当成产品来打磨。

| 门禁 | 覆盖 | 备注 |
|---|---|---|
| **服务端测试**（pytest） | **159 个文件 / 1,649 个用例 / 106,422 行** | 含 6 套 Hypothesis 基于属性的测试 |
| **扩展测试**（node:test） | **220 个文件 / 1,679 个用例 / 73,744 行** | 109 个源码守卫文件 + 111 个行为测试 |
| **E2E** | **11 个 spec / 4,335 行** | 真实 VS Code 实例对真实模型 |
| **体验矩阵** | **200 场景 × 2 层** | 预览 fixture + 真实 sidecar |
| **VSIX 宿主驱动** | **33 步** | 安装 → 激活 → streaming → 验证 → 断言 webview 真实渲染 |
| **静态分析** | ruff + pyright + tsc | 零警告 |
| **协议矩阵** | **5 种协议** | OpenAI Chat / Responses / Anthropic / Gemini / OpenAI-Compatible |
| **i18n** | **8 种语言 × 600+ 条目** | zh-CN / en-US / es-ES / fr-FR / de-DE / ja-JP / ko-KR / pt-BR |
| **bundled sidecar** | **6 平台二进制** | win32-x64 / win32-arm64 / darwin-x64 / darwin-arm64 / linux-x64 / linux-arm64 |

**E2E 套件跑在真实 VS Code 实例里、对着真实模型：**

> 激活打包好的扩展 → 启动内置 sidecar → 保存 Provider → streaming 完整教练轮次 → 生成并验证一张训练卡 → 断言 webview **实际渲染**的内容 → 截图 → 跨工作区重开并恢复历史。

**测试自我声明边界：**
每个 E2E 场景都带 `evidence: { realSidecar, limitation }` —— **测试自己声明它不能证明什么。**

---

## i18n · 八种语言

| 语言 | 代码 | 主要 |
|---|---|---|
| 简体中文 | `zh-CN` | ✅ |
| English | `en-US` | ✅ |
| Español | `es-ES` | ✅ |
| Français | `fr-FR` | ✅ |
| Deutsch | `de-DE` | ✅ |
| 日本語 | `ja-JP` | ✅ |
| 한국어 | `ko-KR` | ✅ |
| Português | `pt-BR` | ✅ |

**回退链：** 用户偏好 > VS Code `env.language` > `zh-CN`（默认）

**6 个界面级覆盖组：** `resourceView` / `contextRail` / `trainingUi` / `orientationRail` / `composerAccessibility` / `leftoverHonesty` —— 译者只需填写自己负责的界面，**而不是全部 600+ 条目表**。

关键代码：`extension/webview/src/lib/i18n/copy.ts`（5,283 行）

---

## 致谢

> Trainer 站在巨人的肩膀上。

### 🏃 运行时核心

| 项目 | 用途 | 为何不可替代 |
|---|---|---|
| [FastAPI](https://github.com/fastapi/fastapi) | 本地 sidecar 框架 | async + Pydantic + 自动生成 OpenAPI 文档 |
| [Uvicorn](https://github.com/encode/uvicorn) | ASGI 服务器 | HTTP/1.1 + WebSocket + 高并发 |
| [Pydantic](https://github.com/pydantic/pydantic) | 数据校验与序列化 | 31 字段的 WorkbenchSnapshot 全靠它跑 |
| [httpx](https://github.com/encode/httpx) | 异步 HTTP 客户端 | sidecar ↔ LLM 网关的全部协议路由 |

### 🤖 LLM 协议

| 项目 | 用途 |
|---|---|
| [openai-python](https://github.com/openai/openai-python) | OpenAI / Anthropic / Gemini 兼容客户端（5 协议路由） |

### 🧠 训练与记忆

| 项目 | 用途 |
|---|---|
| [py-fsrs](https://github.com/open-spaced-repetition/py-fsrs) | FSRS 遗忘曲线复习调度 · 驱动 `TrainingCardState` |
| [qdrant-client](https://github.com/qdrant/qdrant-client) | 语义记忆向量检索（带 sentence-transformer 兜底） |
| [PyMuPDF](https://github.com/pymupdf/PyMuPDF) | PDF 解析（资料库 Tier A 预览） |
| [trafilatura](https://github.com/adbar/trafilatura) | 网页内容抽取（资源摄取） |
| [markitdown](https://github.com/microsoft/markitdown) | 文档 → Markdown 转换（资料库 Tier B 预览） |

### ⚛️ 前端核心

| 项目 | 用途 |
|---|---|
| [React](https://github.com/facebook/react) | 侧边栏工作台 UI |
| [Vite](https://github.com/vitejs/vite) | 构建工具 + 开发服务器 |
| [Zustand](https://github.com/pmndrs/zustand) | 工作台状态管理 |
| [Zod](https://github.com/colinhacks/zod) | 运行时类型校验 |

### 🎨 渲染

| 项目 | 用途 |
|---|---|
| [react-markdown](https://github.com/remarkjs/react-markdown) | Markdown 渲染 |
| [remark-gfm](https://github.com/remarkjs/remark-gfm) | GFM 扩展（表格、任务列表） |
| [remark-math](https://github.com/remarkjs/remark-math) · [rehype-katex](https://github.com/remarkjs/rehype-katex) · [KaTeX](https://github.com/KaTeX/KaTeX) | 数学公式渲染 |
| [Shiki](https://github.com/shikijs/shiki) | 代码高亮（VS Code TextMate 语法） |
| [Mermaid](https://github.com/mermaid-js/mermaid) | 图表与流程图 |
| [@tanstack/react-table](https://github.com/TanStack/table) | 资料库 / 训练队列表格 |

### 📄 预览

| 项目 | 用途 |
|---|---|
| [mammoth](https://github.com/mwilliamson/mammoth.js) · [docx-preview](https://github.com/VolodymyrBaydalka/docx-preview) | DOCX 富渲染（Tier A） |
| PDF.js（内置） | PDF 富渲染（Tier A） |

### 🧪 测试与质量

| 项目 | 用途 |
|---|---|
| [pytest](https://github.com/pytest-dev/pytest) · [pytest-asyncio](https://github.com/pytest-dev/pytest-asyncio) | 服务端 159 个文件 / 1,649 个用例 |
| [Hypothesis](https://github.com/HypothesisWorks/hypothesis) | 基于属性的测试（planner / evaluator / scheduler） |
| [ruff](https://github.com/astral-sh/ruff) | Python lint + 格式化（E/F/I/B、py312、100 列） |
| [pyright](https://github.com/microsoft/pyright) | Python 静态类型检查 |
| [TypeScript](https://github.com/microsoft/TypeScript) | strict 模式，零警告 |
| [Playwright](https://github.com/microsoft/playwright) | E2E + 200 场景体验矩阵 |

### 📦 打包与分发

| 项目 | 用途 |
|---|---|
| [PyInstaller](https://github.com/pyinstaller/pyinstaller) | sidecar 冻结打包（6 平台，manifest sha256） |

### 💡 方法论启发

| 项目 | 启发 |
|---|---|
| [open-spaced-repetition/fsrs4anki](https://github.com/open-spaced-repetition/fsrs4anki) | FSRS 原始论文与参考实现 |
| [obra/superpowers](https://github.com/obra/superpowers) | 「强制工作流，而非建议」的教练纪律 |
| [HKUDS/CLI-Anything](https://github.com/HKUDS/CLI-Anything) | 「让所有软件 agent 原生」的雄心 |

### 🎨 视觉素材

| 项目 | 用途 |
|---|---|
| [dora-image](https://github.com/AI-yyf/trainer/tree/main/assets) | 本 README 里的每一张图（见 `assets/MASCOT.md` / `BANNER_PROMPT.md` / `FEATURE_PROMPTS.md`） |
| DeepSeek 官方萌娘 | Q 版比例 / 赛璐璐着色倾向参考 |
| 老彼得·勃鲁盖尔《巴别塔》 | 左右阵营群像构图参考 |
| 伦勃朗《夜巡》 | 7:1 明暗对比参考 |
| 吉卜力角色设计 | 带三点高光的大眼睛、克制的表情 |

---

## 许可证

[MIT](LICENSE)

---

## 引用 Trainer

如果 Trainer 对你的工作流有帮助，欢迎在博客 / 论文 / 演讲中引用它：

```bibtex
@software{trainer2026,
  title  = {Trainer: A Long-Term Coding Coach Living in Your Editor},
  author = {AI-yyf and contributors},
  year   = {2026},
  url    = {https://github.com/AI-yyf/trainer},
  note   = {v1.0.3}
}
```

---

<div align="center">

**// 训练你的 AI · 与 AI 共同成长**

`v1.0.3` · 由咖啡、FSRS、24 个纯函数、3,328 个测试，以及一颗拒绝替你写代码的心打造。

</div>
