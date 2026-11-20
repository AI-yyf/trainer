# Trainer 规格说明书

版本：v1.1
最后更新：2026-10-17
项目路径：本仓库根目录（`trainer/`）
状态：P1 Release Candidate

> 产品真相以 `.trainer-convergence/product-contract.md`（v2，2026-11-20 锁定）与 [`docs/STRATEGY.md`](docs/STRATEGY.md) 为准；本文描述规格与实现细节，与契约冲突时以契约为准并在同一提交中修正本文。所有数据、资料与记忆统一保存在用户选定的资料库根目录 `<LibraryRoot>` 下。

## 1. 产品定位

Trainer = **通用技术教练（编程起点） / General Technology Coach, coding-first**

定位说明：编程是第一学科与默认入口，产品架构（SubjectProfile 数据化注册表 + Verifier Pack）保证其他技术学科乃至文学可零代码接入；但对外表述统一为"技术教练（编程起点）"，不再自称"编程教练"。

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
对话 (Chat)     资料 (Resources)
```

学习不是一级导航，而是**对话当前所处的状态**：

- **学习条**：对话顶部一行，只显示当前目标 · 当前步骤 · 待复习数，点击打开学习抽屉
- **学习抽屉**：Header 学习图标打开，单一滚动，三段式——当前目标 / 到期练习 / 成长进度，每段只保留一个主动作

### 情境入口

- **练习卡**：练习以卡片出现在消息流中，作答、提示、验证、反思、下一张都在卡内完成
- **进度卡**：练习完成后在消息流中出现，只显示本次变化
- **History**（历史）：Header 抽屉，ChatGPT 式时间线
- **Settings**（设置）：Header 齿轮，Utility Surface

> Route ≠ Primary Navigation
> 内部 route（coach/plan/resources/training/progress/settings）继续存在
> 一级导航始终只有对话、资料两个目的地。plan/training/progress 是兼容 alias，统一重定向到"对话 + 学习抽屉对应段"；命令 ID、深链与恢复入口全部保留。
> `lib/workbenchDestinations.ts` 负责六个内部 route 到这两个目的地的映射。

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

### 4.1 对话视图 (Chat)

**定位**：超级入口，教练核心交互，日常默认视图

**核心**：
- Composer (Ask Trainer / context chips / + 附件 / Send)
- 消息流（用户 + AI，cards + actions + artifacts）
- 学习条（当前目标 · 当前步骤 · 待复习数）
- 练习卡与进度卡（学习内容以卡片形式出现在消息流中）
- Coach streaming dots + streaming cancellation
- History drawer（Header 入口）
- 学习抽屉入口（Header 学习图标）

**交互**：页面主角永远是消息流，禁止变成完整工作台

Skill Projection 的能力状态与可信证据继续存在，通过学习抽屉的成长进度段查看；Coach 首屏不展示独立能力条。

### 4.2 学习抽屉 (Learning Drawer)

**定位**：回答"我现在学什么？下一步做什么？学会了吗？"——但它不是一个"去哪里"

**核心**（单一滚动，三段式，每段一个主动作）：
- 当前目标：计划名、当前阶段/步骤、继续这一步或生成计划
- 到期练习：到期数、当前卡标题、开始/继续练习、查看复习队列
- 成长进度：理解/实现/调试/迁移四行，证据数，最近变化

**形态**：抽屉是**模态浮层**（浮在对话与输入框之上，输入框保留在下面、草稿与焦点不丢；顶部识别行 / 导航行 / 工具按钮仍可点）。内部是三张同构卡片（标题 + 右侧指标 + 内容 + 至多一个主动作），不是 tab；计划里的阶段与证据是**平铺行**，没有「更多」这类总折叠，也没有模板画廊。

**成长卡 = 热力格**：每个能力维度一列，3 个方块按档位**自下而上**填充（像一条在生长的加载条），列下是该档位的名称与证据条数，底部给一条「少 → 多」图例。档位是 `not_verified / emerging / assisted / independent` 四档（`capabilityLevel` 映射到 0–3），**不是百分比**。方块渐次淡入（`--heat-delay` 交错延迟）并尊重 `prefers-reduced-motion`；填充色走中性 accent 色阶（`color-mix` 叠 `--accent`），不引入品牌色。

**交互**：抽屉是阅读面，不放调整入口——所有调整从输入框发起（关掉抽屉，在唯一的输入框里说你要做什么）。受治理的动作（下一步、解除阻塞、开始复习、采纳证据）仍是卡片上的按钮。

**去重**：每张卡只说一件事、只说一次。目标卡说出计划与下一步；练习卡若与下一步是同一张卡，就不再复述标题（`isSameLearningFact`）；成长卡不再重复总数。整张抽屉只保留一个 accent 动作（目标卡的），其余为次级动作。

**交互**：由 Header 学习图标打开；不再有 tab，不再复制 Progress 页的 plan

### 4.3 资料视图 (Resources)

**定位**：统一知识库 + 受控沙箱

**核心**：搜索与检索、文件上传、网页浏览与下载、知识原子抽取

**交互**：首屏优先搜索和知识条目，禁止越权写用户工程代码

### 4.4 训练卡片 (Training Card) — 消息流内联

**定位**：单卡片沉浸流，FSRS 调度，出现在对话消息流中

**子模式**：闪记卡 / 实战卡 / 复盘卡 / 场景卡

**核心**：单卡片状态机 + 训练结果回流 + 项目 handoff + 远程验证

**交互**：默认一次只显示一张当前卡片，禁止变成多模块平铺大网站

### 4.5 成长进度 (Progress) — 学习抽屉的证据下钻

**定位**：能力状态 + 可解释的证据明细，位于学习抽屉第三段

**核心**：四维度状态阶梯（无百分比）+ 热力格可视化（每维度一列，3 格自下而上填充）+ 档位名与证据数 + 「少→多」图例 + 迁移 nudge + 空态引导

### 4.6 设置视图 (Settings) — Utility Surface

**定位**：系统控制面，Header 齿轮进入

**四个索引入口**（原生 VSIX 窗口验收，2026-10-08）：

- 连接：模型服务、密钥与连接测试
- 教练：教学偏好与 Skills
- 工作区：项目、数据与远程支持
- 偏好：语言、主题与高级配置

原有 connection / workspace / teaching / skills / preferences / advanced 配置能力仍保留，由这四个入口进入详情和 disclosure；它们不再是六个并列展示入口。

**Remote Support**（§四十一）：安装状态机（8 态）+ 八语言 +
Remote-SSH E2E nightly + 远程验证面板（流式 + 停止 + 诚实中断态）

## 5. 核心能力矩阵

| 能力 | 状态 | 说明 |
|------|------|------|
| Provider | ✅ | 5 协议 + Capability Truth + SecretStorage |
| Workspace Authority | ✅ | 六级权限梯度 + ledger + checkpoint |
| Library | ✅ | md-only：canonical Markdown 唯一产物，导出也是 md |
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

## 11. 资料库 md-only

资料库只有一种产物：**canonical Markdown**。不再有"预览 Tier"——任何支持格式在导入时就被解析成同一形状的 Markdown，资料库只展示、索引、打开 md。

| 环节 | 规则 |
|------|------|
| 对齐 | 资料行 icon/标题同中心线（≤1px）；菜单标签共用一条左边线；行内代码是 inline 且不撑高行框；CJK 行高 ≥1.4；消息元信息（角色 + 时间戳）共一条基线；RTL 用逻辑属性镜像，不另写覆盖 |
| 捕获入口 | 资料库只有一个「添加到资料库」入口：先选来源（网页链接 / PDF 文件 / 扫码 PDF / GitHub / Gitee / GitLab），再选目标知识库（资料库文件夹），最后加入；仓库支持三个平台（`parse_source_repo`），扫码用平台自带 `BarcodeDetector`，不引入额外依赖 |
| 导入 | DOCX / PPTX / HTML / PDF / 纯文本 → `build_canonical_document` → 统一标题、摘要、标签 |
| 规范化 | `normalize_canonical_body`：唯一 H1、无重复标题行、无三连空行、无行尾空白、行尾统一 |
| 落盘 | canonical Markdown 是唯一文件；原件不落盘（`originals/` 仅作为旧库遗留，成功写入后删除） |
| 打开 | 只开 canonical Markdown；没有"打开原件"动作；导出也是 md（`text/markdown`） |
| 旧库迁移 | 先 dry-run 预览（数量 + 备份清单），再一次确认才执行；服务端先写备份清单再删原件；转换失败的资源被标记，原件保留 |

实现：`server/app/resources/canonical.py`（解析与规范化）、`server/app/resources/canonical_store.py`（落盘）、`shared/src/resourceOpen.ts`（只开 md）、`trainer.resource.markdownOnlyMigration`（迁移桥）。

## 12. 设计原则

### Composer 是核心交互
Composer 常驻于 Chat / Resources 两个目的地；对话所有权唯一，归属教练线程——所有目的地发出的消息进入同一线程，surface 只决定草稿与上下文锚的隔离。练习作答在卡片内完成，不占用 composer（composer 只服务对话）。
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
6. 遥测默认关闭、可选加入：导出仅含白名单事件的粗粒度本地计数聚合 —— 无内容、无路径、无身份；opt-out 导出为空（fail-closed），consent 变更入本地事件账本审计，载荷由 CI schema 门禁守卫（`scripts/verify-telemetry-payload.mjs`）

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
