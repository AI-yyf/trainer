# Trainer 总实施计划

Trainer 的目标只有一个：把它做成一个低理解成本、强教学、可恢复、可验证、可长期演进的统一教练。

它不是普通聊天框，也不是代码代写器。它是一个以 `Coach` 为超级入口、围绕真实工作区持续陪伴用户学习与迁移的 AI 原生学习工具。

## 0. 读图顺序

优先级从高到低：

1. `docs/ui-contract.md`
2. `docs/trainer-ideal/trainer-product-design-spec.md`
3. `docs/open-source-fit-and-provider-strategy.md`
4. `docs/architecture.md`
5. `docs/verification.md`
6. `docs/plans/` 下的历史计划

## 1. 现状基线

当前仓库已经具备以下底座：

- 五视图骨架：`Coach / Plan / Resources / Training / Settings`
- typed parts 会话渲染
- 8 语言 i18n
- Provider v2 / profile registry / capability matrix
- Workspace Authority / remote workspace 语义
- 三层资源预览 + SQLite FTS5 搜索
- FSRS 训练调度
- skill catalog / slash command 入口
- 真实 provider smoke 能力

这意味着后续工作不是“再造一套平台”，而是把已存在的骨架收敛成一个连贯的教学系统。

## 2. 产品北极星

### 2.1 Core promise

- 对话是超级入口
- 命令和 skill 是加速器，不是旁支
- 计划负责主线
- 资料负责沉淀与转化
- 训练负责掌握与迁移
- 设置负责可用性与边界

### 2.2 必须始终诚实

- provider 不可用时要诚实降级
- sidecar 未就绪时要诚实降级
- 正在加载、正在恢复、正在验证都必须可见
- 未采纳证据不能伪装成正式结论
- root 外默认无写权限，sandbox 边界必须清晰

## 3. 目标能力图

### 3.1 Coach 作为超级入口

Coach 视图要承担：

- 自然语言对话
- 即时追问
- 即时小测
- 即时卡片建议
- 任务拆解
- debug / review / restore 入口
- command deck / skill catalog 入口
- function hint 和上下文提示
- typed artifact blocks / tool parts / reasoning summary

建议固定暴露的 skill / command 族包括：

- `$explain`
- `$review`
- `$selection`
- `$plan`
- `$task`
- `$next`
- `$practice`
- `$flash`
- `$resource`
- `$index`
- `$sandbox`
- `$provider`
- `$models`

### 3.2 Plan 负责主线与子计划

Plan 视图要承担：

- 总计划
- 项目计划
- 子计划
- 当前阶段
- 下一步
- 阻塞原因
- 证据治理
- 冻结 / 恢复 / 重新规划
- review queue / due items

### 3.3 Resources 负责受控沙箱

Resources 视图要承担：

- 资料导入
- URL / 网页抓取
- 资源索引
- 本地预览
- provenance / trust / freshness
- active workspace root / folder sovereignty
- sandbox 载体目录的可配置、可迁移、可校验

### 3.4 Training 负责掌握与迁移

Training 视图要承担：

- single-card-first 主卡片
- flash card
- practice card
- review card
- scenario lab
- transfer / backflow
- FSRS 调度
- 恢复后继续

### 3.5 Settings 负责可用性与运行时

Settings 视图要承担：

- provider profile
- protocol selection
- model list refresh
- connection test
- capability matrix
- language / teaching style
- remote credential mode
- workspace context control

## 4. 场景覆盖面

Trainer 必须覆盖的场景包括：

- 纯对话答疑
- 即时追问
- 即时小测
- 即时卡片建议
- 打开新项目
- 打开已有工程
- 打开算法或模型仓库
- 打开 idea 文件夹
- 上传和浏览资料
- 从网页抓取有用内容
- 对依赖库和 API 进行学习
- 现有项目的深度优化
- 空项目的最小场景训练
- 中英文切换
- 8 语言切换与语言偏好持久化
- provider 不可用时的诚实降级
- sidecar 未就绪时的诚实降级
- 跨工作区恢复

每个场景都必须落到五个一级视图中的一个主职责上，不能为每个场景再造一个新顶层页面。

## 5. 开源复用策略

优先复用现成的、可商用的、许可清晰的项目：

- `cc-switch`：provider profile / history / template 形状
- `Pydantic AI`：provider/model abstraction 思路
- `OpenClaw`：workspace-first / active workspace
- `Pi`：project-local settings / permission / remote abstraction
- `ts-fsrs` / `py-fsrs`：FSRS
- `react-arborist`：资源树
- `CodeMirror 6`：代码/文本预览
- `PDF.js` / `react-pdf`
- `MarkItDown`
- `docx-preview`
- `Mammoth.js`
- `Shiki`
- `TanStack Table`
- `wavesurfer.js`
- `assistant-ui` / AI Elements：typed parts taxonomy

不要把以下东西变成默认架构前提：

- 外部 gateway
- 外部 vector DB
- 重型 office online
- 通用 agent runtime
- 复杂 Docker sandbox

## 6. 记忆分层

Trainer 的记忆必须分层，而不是把所有东西塞进一个聊天摘要：

- Master plan memory
- Project memory
- Session memory
- Resource memory
- Training memory
- Provider diagnostics memory

## 7. 交互原则

- Coach message-first
- command-oriented over deep menus
- typed parts over markdown-only
- honest states over silent failure
- narrow sidebar over dashboard sprawl
- one accent color, low-decoration surfaces
- 300-420px sidebar 优先
- 语言、状态、布局都要可恢复
- 所有重要状态都必须可验证

## 8. 交付阶段

### Phase 1

把 Coach 的命令/skill/上下文提示收拢成统一入口，确保对话、命令、工具、typed parts、恢复状态是一条线。

### Phase 2

把 Plan / Resources 的主线、子计划、沙箱边界、来源链和证据链统一起来。

### Phase 3

把 Training 的 flash / practice / review / scenario / transfer 闭环打通，并把完成结果稳定回流到计划与记忆。

### Phase 4

把 Settings、provider、remote、语言、能力矩阵和故障态做诚实、可解释、跨平台一致。

### Phase 5

做最后的 UX 收束：密度、文案、对齐、空态、错误态、焦点、窄边栏和多语言回归。

## 9. 定义完成

当且仅当以下条件满足时，Trainer 才算达到这个目标：

- 五视图固定不漂移
- Coach 作为超级入口成立
- skill / command 逻辑可见且好用
- 计划 / 资料 / 训练 / 设置都能闭环
- 文件夹沙箱边界清晰
- 训练卡和闪记卡可以恢复、可验证、可回流
- provider 和 sidecar 的失败态都诚实
- 8 语言可用且回退正确
- Windows / macOS / Linux 语义一致

