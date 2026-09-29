# Trainer 规格说明书

版本：v1.1
最后更新：2026-09-29
项目路径：本仓库根目录（`trainer/`）
状态：P1 Release Candidate

## 1. 产品定位

Trainer = **AI Programming Coach / AI 通用技术教练**

核心价值链：

```text
理解用户 → 理解当前水平 → 理解真实项目和环境
→ 判断用户真正卡在哪里 → 采用合适方式教学
→ 让用户自己尝试 → 必要时逐级提示
→ 验证用户真实结果 → 形成可信 Evidence
→ 更新 Learner Model → 决定下一步教学 / 训练 / 复习
```

核心原则：**Trainer 的目标不是完成用户的代码，而是让用户最终有能力自己完成代码。**

## 2. 信息架构

### 一级日常导航（永久固定）

```text
对话 (Coach)     学习 (Learning)     资料 (Resources)
```

### 情境入口

- **Training**（训练）：活动驱动，有活跃训练卡或用户说"练一下"时出现
- **Progress**（成长）：学习视图的证据下钻表面，非独立一级
- **History**（历史）：Header 抽屉，ChatGPT 式时间线
- **Settings**（设置）：Header 齿轮，Utility Surface

> Route ≠ Primary Navigation
> 内部 route（coach/plan/resources/training/progress/settings）继续存在
> 但一级导航只显示三个日常 tab + 活动驱动的 Training + Settings 齿轮

## 3. 五层技术架构

```text
1. Webview Product Layer
   React 19 / Zustand / 8 语言 i18n / CSS design tokens
   components: coach/ learning/ resources/ training/ settings/
               progress/ common/ composer/ firstlook/ preview/

2. VS Code Extension Host
   commands/ (25+) / core/ (workspace/sidecar/webview bridge)
   provider/ (SecretStorage) / testing/ (VS Code Testing API)
   workspace/ (gateway: local + remote)

3. Shared Governance Layer
   shared/src/ (50+ modules: protocol/models/commands/tokens
   + training/workspace/provider/recovery/plan governance
   + remoteProtocol (v2 ProcessSpec) + skillCatalog
   + settingsCapability + trainingHandoff 等)

4. Python Trainer Runtime (FastAPI)
   api/ (routers + routes/ 领域路由)
   llm/ (provider_service + coaching_* 子模块 + provider/ 包)
   pedagogy/ (teaching_depth + skill_projection + implementation_coach)
   memory/ (service + review_scheduler + workspace_recovery)
   training/ (card_generator + card_router + fsrs_scheduler + handoff
             + skill_projection + plan_revision + attempt_store)
   planner/ resources/ evaluator/ affect/ workspace/ specs/
   db/ (repository + attempt_store + plan_revision + resource_version)

5. Remote Companion (workspace-kind extension)
   read / search / hash / diagnostics / environment / verify (ProcessSpec v2)
```

## 4. 视图详细规格

### 4.1 对话视图 (Coach)

**定位**：超级入口，教练核心交互，日常默认视图

**核心**：
- Composer (Ask Trainer / context chips / + 附件 / Send)
- 消息流（用户 + AI，cards + actions + artifacts）
- Skill Projection Strip（当前能力状态一览）
- Coach streaming dots + streaming cancellation
- History drawer（Header 入口）
- 训练触发入口（教练推荐 → 情境进入 Training）

**交互**：页面主角永远是消息流，禁止变成完整工作台

### 4.2 学习视图 (Learning)

**定位**：回答"我现在学什么？下一步做什么？学会了吗？"

**核心**：
- 当前目标 + 当前重点 + 下一步
- 学习计划（主线/阶段/进度/冻结状态）
- 成长/能力状态（4 维度状态阶梯，非百分比）
- 真实 Evidence（最近训练/复习/Transfer）

**交互**：首屏可见当前主线，禁止变成聊天页

### 4.3 资料视图 (Resources)

**定位**：统一知识库 + 受控沙箱

**核心**：搜索与检索、文件上传、网页浏览与下载、知识原子抽取

**交互**：首屏优先搜索和知识条目，禁止越权写用户工程代码

### 4.4 训练视图 (Training) — 情境 Focus Mode

**定位**：单卡片沉浸流，FSRS 调度

**子模式**：闪记卡 / 实战卡 / 复盘卡 / 场景卡

**核心**：单卡片状态机 + 训练结果回流 + 项目 handoff + 远程验证

**交互**：默认一次只显示一张当前卡片，禁止变成多模块平铺大网站

### 4.5 成长视图 (Progress) — Learning 的证据下钻

**定位**：能力状态 + 可解释的证据明细

**核心**：四维度状态阶梯（无百分比）+ 可点击展开证据明细
（时间 · 协助级别 · 场景）+ 迁移 nudge + 空态引导

### 4.6 设置视图 (Settings) — Utility Surface

**定位**：系统控制面，Header 齿轮进入

**六分类**（§四十：键盘导航覆盖全部六项）：
connection / workspace / teaching / skills / preferences / advanced

**Remote Support**（§四十一）：安装状态机（8 态）+ 八语言 +
Remote-SSH E2E nightly + 远程验证面板（流式 + 停止 + 诚实中断态）

## 5. 核心能力矩阵

| 能力 | 状态 | 说明 |
|------|------|------|
| Provider | ✅ | 5 协议 + Capability Truth + SecretStorage |
| Workspace Authority | ✅ | 六级权限梯度 + ledger + checkpoint |
| File Preview | ✅ | Tier A/B/C |
| Search | ✅ | SQLite FTS5 + metadata filters |
| Training | ✅ | FSRS + 单卡片状态机 + 尝试持久化 |
| Memory | ✅ | Master/Session/Project/Resource 分层 |
| Remote v2 | ✅ | ProcessSpec + streaming + cancel + timeout |
| Rendering | ✅ | Markdown/Code/Diff/Table/Citation |
| Evidence | ✅ | AttemptStore + hash 绑定 + 可失效 + drilldown |
| Skill Projection | ✅ | 4 维度确定性投影 + AST parity |
| Teaching Depth | ✅ | L0-L5 + 过度教学抑制 |
| i18n | ✅ | 8 语言（Progress/Remote/Settings/SpeedTest/Integrity 全覆盖） |

## 6. Evidence 与 Skill Projection

### Evidence 核心原则
- 说会了 ≠ 验证过
- 一次通过 ≠ 长期掌握
- AI 帮用户做出来 ≠ 用户独立会做
- 文件改变 → hash 变化 → 旧 Evidence 失效

### Skill Projection（确定性，非 LLM）
```
Evidence → Deterministic Projection → Skill State
```
- 4 维度：comprehension / implementation / debugging / transfer
- 5 状态：not_verified / assisted / independent / repeat_verified / needs_review
- transfer 需两个不同上下文（scenario/environment/constraints）
- evidence 删除或失效 → 重新计算
- drilldown：每维度可展开证据明细（时间 · 协助 · 场景）

## 7. Teaching Engine

### L0-L5 深度阶梯
L0 Direct Answer / L1 Explain+Example / L2 Explain+Check
L3 Guided Practice / L4 Independent Practice / L5 Transfer

### 过度教学抑制
"直接告诉我/别问我/我赶时间" → 强制 L0，不绑架进 Training
之后可轻量："如果你愿意，我可以把这一点变成一个短练习"

## 8. Remote 架构

### Local Brain + Remote Hands
```
Local: identity / memory / provider / learning state / trainer data
Remote: read / search / hash / diagnostics / environment / verification
```
API Key 永远留在本地 SecretStorage。

### Remote Protocol v2
```json
{ "executable": "...", "args": ["..."], "cwd": "...",
  "env": {...}, "timeout_ms": 60000 }
```
shell=false 恒定。禁止回退 shell 字符串。

### 诚实性
Interrupted / timeout / connection_lost → outcome unknown → 不写 Evidence
只有 completed + exit_code → 可写 passed/failed

### Nightly Remote-SSH E2E
localhost sshd：exec / byte-exact read / search / sha256 hash
/ verification pass/fail / interrupted outcome-unknown / reconnect

## 9. i18n

8 语言：zh-CN / en-US / es-ES / fr-FR / de-DE / ja-JP / ko-KR / pt-BR

关键 surface 全覆盖：
- Progress（4 维度 + 5 状态 + 证据 + nudge + 空态）
- Remote Support（8 安装状态）
- SpeedTest（8 标签）
- Language Integrity（22 事实标签）
- Settings 单行三元（115 处）+ capability/protocol/cadence/action

退化：zh-CN → en-US → 技术术语英文

## 10. Workspace Authority

六级权限：inspect < annotate < reorganize < generate < apply < destructive

Coach 默认工作在 inspect / annotate。destructive 需用户明确授权 + trash + checkpoint + ledger。

## 11. 文件预览 Tier

| Tier | 类型 | 说明 |
|------|------|------|
| A | Rich | CodeMirror 6, PDF.js, mermaid |
| B | Converted | MarkItDown/Mammoth.js |
| C | Metadata | 元数据 + native editor 回退 |

## 12. 设计原则

### Composer 是核心交互
context chips / Ask Trainer... / + / Send
支持 current file / selection / resource / image，统一从 + 展开。

### Icon 规范
- 不全 16px 同权重；靠 optical weight 区分层级
- 默认 neutral / active accent / semantic state color
- 不做永久彩色导航

### 信息复杂度原则
底层复杂（AttemptStore / SkillProjection / RemoteProtocol v2），前台简单（"你已经连续两次独立完成这一类问题"）。

### Card 密度控制
依靠 spacing / typography / divider / hierarchy。只有真正独立内容才 card。

## 13. 安全底线

1. API Key 只存 VS Code SecretStorage
2. write_file / apply_patch / edit_file 不向 Coach Agent 注册
3. destructive 需用户明确授权 + trash + checkpoint + ledger
4. Provider Capability Truth：不信任声明，真实 probe
5. Sidecar 生命周期：sidebar reopen ≠ restart / switch view ≠ model reload

## 14. CI / Release

| Workflow | 平台 | 覆盖 |
|----------|------|------|
| Cross-Platform Verify | ubuntu/macOS/windows ×3 Job | Server(pytest+SSH E2E+ruff+pyright) / UI(check+tests+200 矩阵×2+recovery) / Package(sidecar+companion+VSIX+smoke) |
| ci | ubuntu | ruff + tsc + build + extension + server tests |
| Nightly Remote-SSH E2E | ubuntu | SSH 传输 8 步 + integrity + extension + 200 矩阵 + server regression |

## 15. 禁止事项

1. 不做形而上的设计口号
2. 不做只有概念没有实现的壳
3. 不做假完成态
4. 不做碎片化设计
5. 不做 VS Code 侧栏伪装网页后台
6. 不做"看起来高级但实际上更难懂"的交互
7. 不做 Multi-agent / Autonomous Coding / Deployment Agent
8. 不做 Session Branch UI / Plugin Marketplace
9. 不做假百分比 / 假分数

## 16. 参考

- `AGENTS.md` — 项目结构知识库
- `README.md` — 构建与验证命令
- `docs/pr6-extraction-plan.md` — routers.py 拆分测量
- `docs/remote-ssh-acceptance.md` — 141s 真实验收指南
