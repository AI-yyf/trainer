# Trainer 产品与工程战略（Strategy）

> 生效日期：2026-11-21 · 分支：`main`
> 配套产品契约：[.trainer-convergence/product-contract.md](file:///Users/Apple/Desktop/trainer/.trainer-convergence/product-contract.md)（v2.2，locked）

---

## 1. 产品定位与北极星

- **定位**：Trainer 是一个**记得你、守在你项目里、只认你亲手做到的事**的通用技术教练（从编程起步）。它的目标不是替学习者完成代码，而是让学习者最终有能力自己完成。
- **北极星指标**：**这周你比上周多了哪些能独立做到的事，而且有证据。**
  - 一段学习对话至少落下一项产出：**一次尝试**、**一条证据**或**一个约好的复习**（明确要求直接回答的除外）。
  - 教练话越少越好，学习者动手时间越多越好。
  - 界面上的任何进度表达都必须能追溯到具体证据；不允许假分数、假百分比或自报代替验证。

---

## 2. 单一资料库根目录架构（Single Unified Library Root）

**硬性原则：所有学习者数据、资料与记忆，统一存储在用户选定的同一个本地资料库根目录（`<LibraryRoot>`）之内；代码工程目录保持零污染。**

### 2.1 目录真相（Single Directory of Truth）

当用户选定资料库根目录 `<LibraryRoot>`（即 `TrainerWorkspaceRoot` / `provisioning.root_path`）后，整个本地存储布局如下：

```text
<LibraryRoot>/
├── Trainer Library/                        # 用户可见的资料库（文件夹分组 / 下载的 PDF 与仓库）
│   ├── .trash/                             # 软删除回收站（可恢复）
│   └── .trainer-resources/
│       └── markdown/                       # 规范化 Markdown 与配套资源（唯一资料产物）
│           └── assets/
├── Knowledge/                              # 结构化知识资产目录
├── Projects/                               # 被管理项目的投影视图
├── Skills/                                 # 个人与项目技能资产
└── .trainer/
    ├── workspace.json                      # 根工作区清单与项目上下文绑定
    └── runtime/                            # sidecar TRAINER_DATA_DIR（全部运行时库与记忆）
        ├── trainer.db                      # SQLite 主库：会话/消息、记忆、画像、计划、目标、练习卡、FSRS、尝试与证据、统一事件账本
        ├── research.db                     # Research Brief 与研究状态库
        ├── qdrant/                         # 语义记忆向量索引
        ├── search-indexes/                 # SQLite FTS5 检索索引
        ├── inline-resources/               # 临时内联上传暂存（写入规范 Markdown 后清理）
        ├── sandboxes/                      # 受控学习沙箱
        ├── cost-ledger/                    # 成本账本
        ├── telemetry/                      # 默认关闭的可选匿名遥测导出
        └── browser_bridge.json             # 浏览器配对凭据哈希与待确认草稿队列
```

### 2.2 四条数据边界规则

1. **零代码仓库污染**：用户的代码工程目录（`project_path`）**绝不**写入 Trainer 资料库（`Trainer Library/`）、规范 Markdown 或数据库文件。代码工程目录只供阅读、检索、诊断和真实测试验证。
2. **选定根目录后不再静默落回隐藏目录**：一旦 `<LibraryRoot>` 可用，Extension Host 的 `SidecarProcessManager` 必须将 `TRAINER_DATA_DIR` 指向 `<LibraryRoot>/.trainer/runtime`，不得静默回退到 VS Code 隐藏的 `globalStorageUri`。若此前在 `globalStorageUri` 中存在冷启动前遗留的 `trainer.db`，首次绑定 `<LibraryRoot>` 时自动做非破坏性迁移（目标已有 `trainer.db` 时绝不覆盖）。
3. **Local Brain + Remote Hands（Remote SSH 一致性）**：在 Remote SSH 场景下，`<LibraryRoot>` 始终驻留在本地 UI 宿主机器上。对话、记忆、计划、证据、`Trainer Library/` 下载与规范 Markdown 全部保存在本地 `<LibraryRoot>`，绝不把本地学习资产写入远程代码目录；远程 Companion 只负责只读代码检索、diagnostics 与受控验证执行（`shell=false`）。未信任工作区与无本地根目录的远程会话对写入保持 fail-closed。
4. **唯一例外——密钥与可丢弃 UI 缓存**：
   - **密钥绝不进 `<LibraryRoot>`**：Provider API Key 只保存在 VS Code `SecretStorage`（操作系统钥匙串），确保整体备份或同步 `<LibraryRoot>` 不会泄露任何凭据。
   - **UI 临时态不作为真相**：VS Code `globalState` / `workspaceState` 与 webview `localStorage` 仅保留工作区指针、面板折叠与草稿等可重建/可丢弃 UI 状态；所有学习事实均可从 `<LibraryRoot>` 完整恢复。

---

## 3. 体验与概念减法（唯一输入框主权）

- **两个一级入口 + 一条主对话 + 一个唯一输入框**：一级导航固定为「对话 / 资料」；学习是对话的记忆（顶部学习条 + Header 纯只读学习抽屉），不是第三个目的地。一切作答、追问、反思、学习真相细节查询（完整阶段、具体证据、复习依据）与计划调整，均收敛到底部唯一 `CoachComposer` 输入框。
- **消灭双输入框与后台管理感**：对话页脚不再叠加练习作答第二输入框或训练卡库 CRUD 管理面板；练习卡收束为克制、可折叠的「当前动作/验证卡」。资料页顶部仅做本地文件名快速筛选，底部唯一输入框明确用于围绕资料提问或生成状态流讲稿；点击 `.md` 资料默认以 VS Code Markdown 图文预览打开，源码编辑退为次要入口。
- **学习者只理解四个正式概念**：`目标`、`练习`、`掌握进度`、`资料`。禁用术语（候选卡、入库、确认入库、训练卡库、账本、投影、修订号、到期队列、练习记录确认、后续和回看、UI proxy 等）禁止出现在学习者可见文案中。
- **同一事实只说一次 & 目标归一**：所有待复习内容统一为「今天要复习 N 个」；抽屉目标卡与 `Goal mode` 统一收归服务端目标真相，不再双轨并行；新项目允许零准入墙拦截直接开聊，首次沉淀资产时再温和绑定 `<LibraryRoot>`。
- **对话内敛与静噪**：进度先给一句追溯到证据的人话，学习抽屉以单一 4 段正式能力条呈现 5 态投影（无百分比）；每条回复常驻快捷操作不超过 3 个（`复制 · 练一下 · 更多`）。
- **浏览器端以捕获为主，并提供侧栏对话**：Popup 快速捕获与右键菜单直达本地 `<LibraryRoot>/Trainer Library/`；侧栏复用 VS Code 侧边栏的同一套工作台界面与唯一输入框，不另写对话逻辑，也不新增浏览器专属的学习功能（产品契约 v2.2 §9，2026-11-28）。

---

## 4. 教学内核、节奏与延迟预算（RethinkFun 状态流 + Wave 3）

- **RethinkFun 状态流理论重建内核**：快节奏引导、深度讲透与推理型 FSRS 复习共享同一内核（状态 → 缺口 → 对象构造 → 变量先于公式 → 约束推出公式/设计 → 代码回指理论 → 真实校验 → 认知回收），零废话垫词，并支持将深度讲稿沉淀为 `<LibraryRoot>/Trainer Library/` 规范 `.md` 笔记。
- **延迟就是教学法**：首屏可见反馈 `TTFT <= 2s`（含工具读取阶段的极简真实进度提示），短回合完整回复 `<= 6s`；代理配置支持直连/忽略系统代理并在代理冲突时明确提示。
- 默认「先动手、后讲解」；能力探针结果按传输特征缓存，不阻塞首轮首 token；按意图裁剪 prompt；连续多轮未产生尝试/证据/复习时由教练主动收敛。

---

## 5. 主动性与治理（Wave 4）

- 诊断报错命中历史薄弱维度时，在每日打扰预算内轻声提示并引导自行定位。
- 复习时机贴合编码间隙，不打断正在输入的学习者。
- 长期计划的变更永远是「提议 + 理由 + 学习者显式确认」。

---

## 6. 分支纪律与总验收

- **单一主线**：仅在唯一主干分支 `main` 推进（原 `codex/trainer-unified-learning` 已快进合入 `main` 并清理其余分支；历史分支 `codex/trainer-convergence-verification` 已完成只读梳理与修复移植，并以 tag `archive/trainer-convergence-verification-2026-11-20` 归档）。
- **打包解耦**：`server/app` 与 `extension/bundled/server/app` 保持同步并通过 parity 测试（后续评估打包脚本在构建时同步，减少提交噪声）。
- **测试原则**：停止新增只锁源码文本形态的守卫测试，优先编写行为测试与真实布局/语义门禁。
- **总验收标准**：在安装态 VSIX 中、用真实模型、在同一份 `<LibraryRoot>` 数据上，从头到尾跑通契约第 10 节的「幂等性」跨周学习与受控时钟复查故事，并完成一次人工教学质量签核（T-0028）。
