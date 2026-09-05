# Trainer 底层重构参考与开源移植蓝图
最后更新：2026-06-07

## 0. 这份文档到底要解决什么

这份文档不是在回答“Trainer 应不应该做强”，而是在回答：

1. **怎么把 Trainer 彻底做强。**
2. **怎么最大化复用、移植、借鉴现有成熟开源项目。**
3. **怎么保证最终交付仍然是“只需要配置大模型 API 就能用”。**
4. **怎么避免把 Trainer 做成一个需要用户自建一堆基础设施的半成品。**

结论先写在最前面：

- Trainer 应该大胆借代码、借组件、借目录组织、借状态机、借配置模型、借渲染 taxonomy。
- 但默认消费者交付必须保持：**安装扩展，配置 provider / model / API key，即可使用。**
- 因此，Trainer 的底层路线应该是：**强产品 + 大量移植成熟开源代码 + 零额外部署默认路径**。
- 远程访问也应该优先复用 **VS Code Remote SSH / Remote Tunnels / Dev Containers / WSL**，而不是自建一套传输层或远程 agent 网关。

这里的“零额外部署”不是“功能弱”，而是：

- 不要求用户部署 LiteLLM Gateway。
- 不要求用户部署 Qdrant server。
- 不要求用户部署 SearXNG。
- 不要求用户部署 Temporal。
- 不要求用户部署 OpenClaw / OpenHands / 自建 agent runtime。
- 不要求用户部署外部数据库、搜索服务、消息队列。

用户需要做的默认动作只能是：

1. 安装 VS Code 扩展。
2. 启动内置 sidecar。
3. 选择 provider 协议。
4. 配置 API key、base URL、模型别名或模型 ID。
5. 如需远程访问，只使用 VS Code 已有的远程工作区能力，不要求额外部署 Trainer 专属服务。

## 1. 最终目标定义

Trainer 最终应该是一个桌面优先、侧边栏优先、会话优先的强教练工具，而不是：

- 一个通用 agent 框架。
- 一个通用 RAG 平台。
- 一个通用文件管理器。
- 一个通用知识库 SaaS。
- 一个自动替学生写代码的执行 agent。

Trainer 的真正产品价值是：

- **Coach-first**：先教，再让学生做，再验收证据。
- **Project-aware**：围绕当前工程、当前文件、当前阻塞做训练。
- **Memory-rich**：有总计划记忆，也有分项目记忆、训练记忆、资料记忆。
- **Resource-grounded**：资料可检索、可预览、可引用、可追踪来源。
- **Training-native**：训练卡、复习节奏、迁移练习、项目 handoff 是一等公民。
- **Agent-assisted**：在显式授权的项目根目录内，agent 可以读写、整理、生成、检索、回收文件产物，但不变成无边界全局执行器。
- **Protocol-aware**：支持多协议、多模型配置，而不是把一切压成 OpenAI-compatible。
- **Remote-native**：本地文件夹、Remote SSH、Remote Tunnels、Dev Containers、WSL 走同一套工作区契约。
- **Renderable**：所有消息、工具、证据、计划、diff、表格、文件预览都能被完美渲染。

## 2. 核心非协商约束

### 2.1 对用户的约束

默认用户不能被要求：

- 安装 Docker。
- 跑本地服务集群。
- 配置 Redis / Postgres / Elastic / Qdrant / Kafka。
- 自建 RAG 基础设施。
- 自建 agent gateway。
- 部署 OnlyOffice / Collabora / LibreOffice Online 之类的文档预览服务器。
- 部署自建 SSH/SFTP 中转服务才能使用远程工作区。
- 打开独立 Web 面板管理内部状态。

默认用户只配置：

- provider 协议。
- API key。
- base URL（如需）。
- 模型或模型别名。

### 2.2 对工程的约束

- 能直接移植的成熟开源代码，就不要重复造轮子。
- 需要强产品适配的地方，只保留薄适配层。
- 不把底层依赖的复杂性直接暴露给最终用户。
- 优先选 MIT / Apache-2.0 / BSD 这类商业友好许可。
- 不直接移植 GPL / AGPL / 闭源 / 商业限制代码到核心产品。

### 2.3 对架构的约束

- 默认路径必须是 `extension + bundled sidecar + local storage + direct API adapters`。
- 高级功能可以扩展，但不能反向污染默认交付。
- 语义检索可以有，但不能设计成“必须部署向量数据库才有资料搜索”。
- 远程访问优先复用 VS Code Remote 能力、`workspace.fs`、远程 extension host，而不是自建第一套 SSH/SFTP/tunnel 协议栈。
- 工具层可以有，但不能让 Trainer 失去**显式工作区边界 + 教学优先**这两个核心约束。

## 3. 复用与移植总原则

### 3.1 允许的复用层级

把可复用对象分成四类：

| 级别 | 含义 | 可以怎么做 |
| --- | --- | --- |
| A. 直接移植代码 | 许可友好、实现成熟、与 Trainer 目标一致 | 可直接 port / copy / adapt |
| B. 移植模块结构 | 代码可借，但语言或 runtime 不同 | 借目录结构、状态模型、接口、测试形状 |
| C. 借设计不借代码 | 项目闭源、许可不合适、或太重 | 借交互契约、配置模型、消息 taxonomy |
| D. 明确不采用 | 会提高部署成本或引入维护灾难 | 不进入默认架构 |

### 3.2 商业可用许可规则

Trainer 应优先借这些许可：

- MIT
- Apache-2.0
- BSD-2 / BSD-3

可谨慎使用：

- LGPL / MPL（更适合作为依赖，而不是内联移植核心代码）

默认不直接移植：

- GPL
- AGPL
- 闭源
- 附加商业限制许可

### 3.3 商业安全复用红线

这些只能借思路，不能把代码直接抄进来：

- Claude Code 内部实现
- Cursor 内部实现
- 任何未明确开源的商业产品前端/后端代码
- 任何 AGPL/GPL 核心代码，如果它会污染 Trainer 的商业分发路径

这条对你提到的 Claude Code 尤其重要：

- **Claude Code 的公开文档、配置理念、模型选择逻辑可以借。**
- **Claude Code 自身闭源实现不能当作可直接移植代码。**
- **可以直接借的是 `cc-switch` 这种 MIT 开源工具。**

## 4. 可直接借用/移植的核心项目清单

这一节是 Trainer 底层改造最重要的落地地图。

### 4.1 复用总表

| 项目 | 许可 | 复用等级 | Trainer 应借什么 | 默认用户是否增加部署成本 |
| --- | --- | --- | --- | --- |
| `cc-switch` | MIT | A/B | profile 管理、current marker、history、template、empty mode、API 测试逻辑 | 否 |
| `OpenClaw` | MIT | B/C | workspace 布局、bootstrap/memory/workspace 分离、active workspace 思想 | 否 |
| `Pi` | MIT | C | project-local settings、cwd/project trust、permission rule 设计、remote execution 抽象 | 否 |
| `Pydantic AI` | MIT | A/B | provider/model abstraction、typed outputs、fallback、test model 思想 | 否 |
| `CodeMirror 6` | MIT | A | 文本/代码/差异预览编辑核心 | 否 |
| `react-pdf` | MIT | A | PDF viewer React 适配 | 否 |
| `PDF.js` | Apache-2.0 | A | PDF 渲染引擎 | 否 |
| `MarkItDown` | MIT | A/B | PDF / DOCX / PPTX / XLSX / HTML / 图片 / 音频 / ZIP -> Markdown/text fallback 管线 | 否 |
| `docx-preview` (`docxjs`) | Apache-2.0 | A | DOCX 富预览 HTML 渲染 | 否 |
| `Mammoth.js` | BSD-2-Clause | A/B | DOCX -> 干净 HTML / Markdown 的轻转换 | 否 |
| `Shiki` | MIT | A | 代码高亮 | 否 |
| `react-arborist` | MIT | A | 文件树 / 资源树 | 否 |
| `TanStack Table` | MIT | A | CSV/TSV/表格预览 | 否 |
| `wavesurfer.js` | BSD-3-Clause | A/C | 音频波形预览与时间轴交互 | 否 |
| `ts-fsrs` | MIT | A/B | FSRS 算法、状态更新逻辑 | 否 |
| `py-fsrs` | MIT | A/B | Python sidecar 端 FSRS 调度 | 否 |
| `assistant-ui` | MIT | B/C | chat/tool/source 组件思想、渲染 primitives | 否 |
| `Vercel AI Elements` | Apache-2.0 | C | message/tool/artifact/test/file-tree taxonomy | 否 |
| `Trafilatura` | Apache-2.0 | A | URL 正文抽取 | 否 |
| `qdrant-client` | MIT | B | 如保留本地向量索引，可继续用 local mode | 否 |
| `LiteLLM` | MIT 主体 | C/D | gateway 思路与兼容矩阵 | 默认否，高级可选 |

### 4.2 结论

Trainer 最优路线不是“自己重新做一套平台”，而是：

- **Provider 配置层借 `cc-switch` 风格**
- **Workspace / 资料沙箱借 `OpenClaw` 风格**
- **工作区权限 / 项目本地设置 / 远程执行抽象借 `Pi` 的思路**
- **训练算法借 `FSRS`**
- **文件树借 `react-arborist`**
- **预览借 `CodeMirror + react-pdf/PDF.js + Shiki + TanStack Table + MarkItDown + docx-preview + Mammoth.js + wavesurfer.js`**
- **消息渲染借 `assistant-ui / AI Elements` 的 taxonomy**
- **provider adapter 借 `Pydantic AI` 和官方 SDK**

## 5. Provider 与模型配置：必须彻底重做

当前 Provider 层最大问题不是“功能少”，而是配置抽象太弱。只要抽象错了，未来再加 10 个模型也是一团乱。

### 5.1 最终目标

Trainer 的 Provider 层必须支持：

- 多 profile。
- 多协议。
- 多模型别名。
- 手动模型与 provider live catalog 混合。
- 可选模型配置。
- 任务到模型的映射。
- 模型能力矩阵。
- request-level options。
- 协议级测试与诊断。
- 不同 provider 的能力降级说明。

### 5.2 最强默认路线

默认路线不是 LiteLLM，不是 LangChain，也不是自建 adapter 大全。

默认路线应是：

1. **Direct API adapters**
2. **Official SDKs / stable open-source adapters**
3. **Profile-based model registry**
4. **Task-to-model binding**
5. **Capability-aware UI**

也就是说：

- OpenAI 用官方 SDK。
- Anthropic 用官方 SDK 或 Pydantic AI adapter。
- Gemini 用官方 SDK 或 Pydantic AI adapter。
- OpenAI-compatible 用 OpenAI SDK 指向自定义 `base_url`。
- OpenRouter / Ollama / DeepSeek / Kimi / Together 等统一进入 compatible profile。

### 5.3 为什么你提到的 cc-switch 值得直接借

`cc-switch` 是 MIT，可以直接借代码和思路，但要注意它是 Go CLI 工具，Trainer 是 TS + Python，所以最合理的是**逻辑移植**。

可直接借的点：

1. `profiles/` 目录设计。
2. `.current` 当前配置标记。
3. `.history` 配置切换历史。
4. `template` 模型。
5. 原子写入、备份、回滚机制。
6. 空配置模式（对 Trainer 可改造成“provider disabled / no active profile”）。
7. profile 内容验证。
8. API connectivity tester 的整体结构。

不该原样照搬的点：

- `ANTHROPIC_AUTH_TOKEN` 这类 Claude 专属 env 键。
- Claude CLI 特定流程。
- 纯 CLI 导向的交互方式。
- 针对 `.claude/` 的目录语义。

### 5.4 Claude Code 可借什么，不可借什么

可借：

- `modelAliases`
- `availableModels`
- `modelOverrides`
- provider identity 与 capability 分离
- reasoning / prompt cache / long context 这些能力不靠 provider 名猜

不可借：

- Claude Code 闭源实现代码
- Claude Code 内部具体状态管理实现
- Claude Code 私有 UI 代码

所以正确表述应该是：

- **借 Claude Code 的公开配置契约思想**
- **直接移植 `cc-switch` 这种 MIT 开源实现中的 profile 管理逻辑**

### 5.5 Trainer 的 Provider v2 配置模型

建议配置模型：

```yaml
providerConfigVersion: 2
activeProfileId: openai-default

profiles:
  - id: openai-default
    label: OpenAI
    mode: direct
    protocol: openai_responses
    baseUrl: https://api.openai.com/v1
    apiKeyRef: trainer.provider.openai-default
    catalog:
      source: provider_live
      cacheTtlSeconds: 43200
    modelAliases:
      coach-fast: gpt-5-mini
      coach-deep: gpt-5.4
      critic: gpt-5.4
      summary: gpt-5-mini
      embed: text-embedding-3-small
    availableModels:
      allow: [gpt-5-mini, gpt-5.4, text-embedding-3-small]
      deny: []
    taskBindings:
      coach_reply:
        alias: coach-fast
        fallbackAliases: [coach-deep]
        requiredCapabilities: [structuredOutput, streaming]
      coach_critique:
        alias: critic
      plan_summary:
        alias: summary
      resource_embedding:
        alias: embed
    requestDefaults:
      store: false
      reasoningEffort: medium
      serviceTier: auto
      promptCache: auto
    capabilities:
      gpt-5-mini:
        chat: true
        responses: true
        streaming: true
        structuredOutput: true
        tools: true
        vision: true
        embeddings: false
        promptCache: true
      text-embedding-3-small:
        embeddings: true

  - id: anthropic-default
    label: Anthropic
    mode: direct
    protocol: anthropic_messages
    baseUrl: https://api.anthropic.com
    apiKeyRef: trainer.provider.anthropic-default
    modelAliases:
      coach-fast: claude-haiku-4-5
      coach-deep: claude-sonnet-4-6
    taskBindings:
      coach_reply:
        alias: coach-fast
        fallbackAliases: [coach-deep]
        requiredCapabilities: [structuredOutput, streaming]
    requestDefaults:
      maxTokens: 4096
      thinkingBudget: auto
      promptCache: auto

  - id: openrouter-default
    label: OpenRouter
    mode: direct
    protocol: openai_chat_completions_compatible
    baseUrl: https://openrouter.ai/api/v1
    apiKeyRef: trainer.provider.openrouter-default
    modelAliases:
      coach-fast: openai/gpt-5-mini
      coach-deep: anthropic/claude-sonnet-4-6
```

### 5.6 协议支持优先级

第一波必须支持：

1. `openai_responses`
2. `openai_chat_completions`
3. `anthropic_messages`
4. `openai_chat_completions_compatible`

第二波建议支持：

5. `gemini_generate_content`

高级而非默认波次：

6. `bedrock_converse`
7. `vertex_ai`
8. `litellm_gateway`

### 5.7 为什么 Responses 与 Anthropic Messages 是必须的

因为 Trainer 不是普通聊天框，而是需要：

- structured output
- tool calls
- reasoning-aware response
- multimodal inputs
- source-aware citations
- 可控的教学式输出

OpenAI Responses 与 Anthropic Messages 都更贴近这个形态，不应该继续被压平到一个“OpenAI-compatible chat”抽象里。

### 5.8 Provider 层该直接移植什么

#### 来自 `cc-switch`

可移植到 Trainer 的模块概念：

- `ConfigManager` -> `ProviderProfileRegistry`
- `.current` -> `activeProfileId`
- `.history` -> `profileSwitchHistory`
- template detection -> `profile templates / quick-start presets`
- API tester -> `protocol-specific provider diagnostics`
- atomic file write -> `safe config persistence`
- empty mode -> `provider disabled / no active profile / safe offline state`

#### 来自 `Pydantic AI`

可借：

- model/provider abstraction
- typed output contract
- fallback models
- test model / fake model
- provider-specific settings surface

最佳用法不是让 Pydantic AI 接管 Trainer 整体状态机，而是让它做：

- 多 provider 统一调用层
- structured output 层
- 测试替身层

### 5.9 Provider UI 应如何落地

Settings 视图必须显示：

- 当前 active profile。
- 当前协议。
- 当前任务绑定。
- 当前 alias -> 实际模型映射。
- 当前模型能力。
- live catalog / cached catalog。
- API key 是否存在。
- profile test 结果。
- 降级原因。

不能只显示：

- provider name
- base URL
- model

### 5.10 Provider 部分的最优工程原则

- 默认只走 direct API。
- gateway 是高级选项，不是默认依赖。
- 官方 SDK + Pydantic AI + cc-switch 风格 config 足够强。
- 不要自研多协议 parser / transport 层。
- 不要继续把兼容 endpoint 叫做“provider 已支持一切协议”。

## 6. Training 视图：做成真正的训练工具，而不是功能堆积

### 6.1 训练视图的核心原则

Training 必须是 **single-card-first**。

不是：

- dashboard
- 统计面板
- 题库列表
- CMS
- 多列功能中心

而是：

- 当前这一张卡为什么出现
- 学生现在该做什么
- 做完之后如何交证据
- 系统如何根据表现安排下一步

### 6.2 可直接借用的开源基础

| 目标 | 可借项目 | 怎么借 |
| --- | --- | --- |
| 复习算法 | `ts-fsrs` / `py-fsrs` | 直接移植状态更新算法 |
| 卡片评级 | FSRS/Anki 思路 | 借 `Again/Hard/Good/Easy` 四档 |
| 训练节奏 | FSRS + retrieval practice | 借策略，不借 Anki 代码 |

### 6.3 为什么不直接借 Anki 代码

Anki 很强，但核心许可路径对商业产品不够轻。最优做法不是移植 Anki 代码，而是：

- 用 MIT 的 `ts-fsrs` / `py-fsrs`
- 借 Anki/FSRS 的调度逻辑和交互概念
- 自己做 Trainer 特化 UI 与状态机

### 6.4 Training 状态机

建议明确状态机：

```text
idle
 -> queued
 -> present_card
 -> learner_attempt
 -> evidence_submit
 -> coach_feedback
 -> rating
 -> next_action
 -> handoff_to_project or next_card
```

### 6.5 卡片类型

| 类型 | 目的 | 学生动作 | 教练动作 |
| --- | --- | --- | --- |
| Recall | 主动回忆 | 先说，不先看答案 | 只给小提示 |
| Explain | 自我解释 | 解释原因和机制 | 追问误区 |
| Predict | 预测行为 | 预测输出/bug/测试结果 | 强化因果 |
| Drill | 刻意练习 | 做一个最小实现 | 不替做，只设验收 |
| Debug | 调试训练 | 提出假设并验证 | 强迫证据驱动 |
| Transfer | 迁移训练 | 把概念用到项目里 | 生成项目 handoff |
| Review | 间隔重复 | 自评难度 | 更新复习状态 |

### 6.6 最符合记忆惯性的交互方案

Trainer 最好的教育交互不是“讲很多”，而是：

1. 诊断学生当前误区。
2. 先让学生回忆。
3. 如果卡住，再给第一层提示。
4. 仍卡住，再给结构提示。
5. 最后才给示例或局部答案。
6. 要求学生提交证据。
7. 给出简短反馈。
8. 更新 mastery 与复习时间。
9. 给出回到项目的最小 handoff。

这就是最接近：

- retrieval practice
- desirable difficulty
- self-explanation
- worked examples fading
- deliberate practice

### 6.7 训练卡的 UI 组成

一张卡推荐只有这些区块：

- 标题
- 为什么现在练
- 学生动作
- 允许的提示层级
- 证据上传入口
- 通过标准
- 复习评级
- handoff 到项目

不要让训练卡变成长文档。

### 6.8 FSRS 在 Trainer 中怎么落地

优先方案：

- 如果主要逻辑在 Python sidecar，优先移植 `py-fsrs`。
- 如果更多状态在 webview/TS，优先移植 `ts-fsrs`。

建议存储字段：

- `card_id`
- `concept_id`
- `project_scope`
- `state`
- `stability`
- `difficulty`
- `retrievability`
- `last_reviewed_at`
- `next_due_at`
- `evidence_score`
- `transfer_score`

关键原则：

- LLM 负责出题、点评、挑选合适下一练习。
- FSRS 负责时间调度。
- **不要让 LLM 自己随便发明复习间隔。**

## 7. Resources：做成 mini OpenClaw，但不把 OpenClaw 变成依赖

### 7.1 正确理解 mini OpenClaw

你说的“像一个 mini OpenClaw 一样在一个文件夹沙箱内容支配所有内容”，最合理的翻译不是：

- 真的把 OpenClaw 嵌进来

而是：

- **借 OpenClaw 的 workspace-first 思想**
- **把 Trainer 的资料、记忆、计划、索引、证据统一放在一个受控工作区**

### 7.2 OpenClaw 真正值得借的地方

`OpenClaw` 是 MIT，能借的点很明确：

- 单一 active workspace
- config 与 workspace 分离
- workspace 作为 memory/home
- bootstrap files 作为稳定上下文
- private backup 与 git 思路
- 文件布局先于数据库

### 7.3 Trainer Resource Workspace

建议默认目录：

```text
trainer-workspace/
  workspace.json
  README.md
  .trainerignore
  AGENT_POLICY.md
  .trainer/
    checkpoints/
    operations/
    previews/
    mounts.json
  resources/
    inbox/
    library/
    uploads/
    links/
    extracted/
  projects/
    <project-id>/
      project.json
      goals.md
      plan.md
      subplans/
      evidence/
      tasks/
      cards/
      notes/
      summaries/
      outputs/
  memory/
    master-plan.md
    preferences.md
    concepts/
    projects/
    sessions/
  search/
    index.sqlite3
    cache/
    chunks/
    embeddings/
  remote/
    manifests/
  exports/
  trash/
```

关键边界：

- workspace 中放资料、记忆、证据、计划。
- secret 不进 workspace。
- provider key 不进 workspace。
- sidecar state 可索引 workspace，但不以数据库替代 workspace。
- `trash/` 与 `.trainer/checkpoints/` 是强约束，不是可选糖衣。
- 远程挂载信息与同步元数据要进 `remote/` / `.trainer/mounts.json`，但认证信息不能落盘到 workspace。

### 7.4 资料导入原则

导入资料时，必须产生一条 manifest 记录：

- `resource_id`
- `source_type`
- `origin_path_or_url`
- `hash`
- `imported_at`
- `project_scope`
- `trust_state`
- `preview_type`
- `preview_strategy`
- `index_state`
- `chunk_strategy`
- `extractor`
- `derived_artifacts`
- `mount_id`
- `remote_origin`

不要把导入结果做成“黑箱”。

### 7.5 文件树不要再手搓

Resources 的文件树最适合直接借：

- `react-arborist`（MIT）

理由：

- 已经是成熟文件树交互组件。
- 支持重命名、展开、键盘导航、树形状态。
- 比继续手搓 tree 维护成本低很多。

Trainer 的最佳做法：

- 借 `react-arborist` 做 Resources tree。
- Resource metadata 与 preview state 放到自有 store。
- 只做 Trainer 风格的 item renderer 和 action row。
- 文件树数据源统一走 `workspace.fs` / 资源服务，不要让 webview 直接假定本地绝对路径。

### 7.6 文件预览不能只赌一个 viewer，必须做成三层能力梯

真正强的资料系统，不是“找到一个万能 file viewer”，而是：

1. **Tier A: native rich preview**
2. **Tier B: convert-to-markdown / HTML / structured text**
3. **Tier C: metadata-only fallback + open in native editor**

Trainer 的最佳实践应该是：

- 侧边栏做 **quick preview**。
- 详情区做 **rich preview**。
- 需要高保真时，直接 **open in VS Code native editor**。
- agent 检索与教学引用优先消费 **Tier B 的结构化导出**，不要强依赖 UI 级富预览。

### 7.7 文件预览兼容矩阵

| 文件类型 | Tier A：富预览 | Tier B：agent 友好转换 | Tier C：兜底 | 推荐项目/方案 |
| --- | --- | --- | --- | --- |
| 文本/代码/JSON/YAML/TOML/INI/日志 | `CodeMirror 6` + `Shiki` | 原文切块 + heading/symbol/path 索引 | 超大文件只做片段 + metadata | `CodeMirror 6`、`Shiki` |
| Markdown/MDX | `react-markdown` + KaTeX + Mermaid | Markdown AST / heading 提取 | source view | 现有 markdown 链路 |
| PDF | `react-pdf` + `PDF.js` | `MarkItDown` 或现有 PDF text 抽取 | 页数/标题/hash/外部打开 | `react-pdf`、`PDF.js`、`MarkItDown` |
| DOCX | `docx-preview` (`docxjs`) | `Mammoth.js` 或 `MarkItDown` | metadata + native open | `docx-preview`、`Mammoth.js`、`MarkItDown` |
| CSV/TSV | `TanStack Table` | 保留原表头与行号切块 | metadata + download | `TanStack Table` |
| XLSX/XLS | 工作表切换 + 表格预览 | `MarkItDown` / sidecar 提取为 sheet JSON/CSV | sheet 名、行列数、native open | `TanStack Table` + `MarkItDown` |
| PPTX | 幻灯片目录 + 提取图片/备注 | `MarkItDown` 导出 slide outline | 页数、标题、native open | `MarkItDown` |
| 图片 | 浏览器原生图片预览 | OCR/说明文字/EXIF 摘要 | metadata only | 原生 `<img>`，可选 LLM vision |
| 音频 | 原生 `<audio>` + 波形 | transcript / metadata | metadata + native open | 原生 `<audio>`、`wavesurfer.js` |
| 视频 | 原生 `<video>` + poster | transcript / chapter / metadata | metadata + native open | 原生 `<video>` |
| Notebook (`.ipynb`) | 只读 cell 列表 + 输出摘要 | notebook JSON -> typed parts | 直接交给 VS Code notebook editor | VS Code 原生 notebook 能力 |
| HTML/XML/EML/EPUB/ZIP | 安全结构预览 | `MarkItDown` 或 archive listing | metadata + external open | `MarkItDown`、现有 archive audit |
| 二进制/未知文件 | 不做假富预览 | strings/sample/manifest | hash + mime + size + external open | metadata fallback |

这里最重要的工程判断有四个：

1. **不要把 Office 在线服务依赖型 viewer 当默认路线。**
2. **PPTX / XLSX / DOCX 不要执着追求“浏览器内像 Office 一样 100% 像素级还原”。**
3. **agent 使用资料时，优先读结构化转换结果，不优先读 UI 富预览。**
4. **Notebook、图片、视频这类格式，Trainer 应该允许“侧边栏预览 + 原生编辑器打开”双轨并存。**

### 7.8 文件夹中打开后，agent 对内容“完全支配”应该怎样定义

这里不能只写一句“像 Claude Code 一样”，必须写成明确契约。

建议 Trainer 定义一个 **active workspace root**：

- 用户显式打开一个本地或远程文件夹。
- 该文件夹成为当前 `activeWorkspaceRoot`。
- agent 的读写、搜索、重命名、移动、生成、归档、预览、索引、计划、记忆回流，都默认只在这个 root 内发生。

建议把权限梯度写死为六级：

| 级别 | 含义 | 是否默认开启 |
| --- | --- | --- |
| `inspect` | read/list/search/index/preview/summarize | 是 |
| `annotate` | 写笔记、写计划、写 evidence，不改源码 | 是 |
| `reorganize` | mkdir/move/rename，在 root 内重组资料 | 否 |
| `generate` | 生成新文件、新卡片、新总结、新脚本 | 否 |
| `apply` | 修改已有文件 | 否 |
| `destructive` | 删除、覆盖、批量移动 | 仅通过 `trash` / review 路径 |

真正的“完全支配”不是“无条件危险写盘”，而是：

- 在 **active root 内完全自治**
- 在 **active root 外默认无写权限**
- destructive 操作走 **trash / checkpoint / ledger**

也就是说，Trainer 应该实现的是 **folder sovereignty**，不是 **global machine sovereignty**。

### 7.9 Folder sovereignty 的底层实现契约

为了让这个模型真正可落地，底层契约至少要有：

1. `activeWorkspaceRoot`
2. `rootUri`（本地或远程 URI）
3. `authorityMode`
4. `allowedOperations`
5. `mountedSources`
6. `operationLedger`
7. `checkpointId`
8. `previewArtifacts`
9. `resourceManifest`

执行规则必须非常硬：

- 所有文件操作先做 **path normalization**，再验证是否仍在 root 内。
- 删除不是直接 `rm`，而是移入 `trash/` 并登记 ledger。
- 批量改动先产出 patch / diff / plan，再 apply。
- 远程工作区与本地工作区共用同一套 authority contract，不允许出现“远程模式就绕过边界”。
- 资料目录与项目目录可以共存，但都必须挂在同一个 root 主权模型下。

这也解释了为什么当前仓库里的 sandbox 不能只停留在“只读预览 + 威胁提示”。

下一步应该做的是：

- 从 `read-heavy sandbox` 升级为 `root-scoped workspace authority service`
- 把 command ledger、checkpoint、trash、preview artifact、import manifest 串起来
- 让 agent 能真正支配 **root 内内容**，而不是只会展示“blocked” 文案

### 7.10 远程访问：必须是一等公民，但绝不能引入重部署

“支持远程访问”最正确的工程翻译不是：

- 自己造一个 Web IDE
- 自己造 SSH 网关
- 自己造 remote sync 服务

而是：

- **优先复用 VS Code 官方远程工作区体系**

推荐优先级：

1. **Remote SSH**
2. **Remote Tunnels**
3. **Dev Containers / WSL**
4. **普通本地工作区**

对应的 Trainer 落地原则：

| 场景 | 正确路线 | 为什么 |
| --- | --- | --- |
| 远程 Linux / GPU / 服务器目录 | VS Code Remote SSH | 扩展与 sidecar 直接跑在远端，最像本地 |
| 无 SSH 但要穿透访问 | VS Code Remote Tunnels | 不要求 Trainer 自己实现传输层 |
| 容器内项目 | Dev Containers | 工作区、解释器、sidecar 都与项目共处 |
| WSL 项目 | WSL Remote | 避免路径/编码/解释器混乱 |
| 纯资源 URL/网页 | 走资源导入而不是假装成文件系统 | 更简单也更可控 |

底层实现要点：

- 扩展文件访问优先走 `vscode.workspace.fs`、`findFiles`、`FileSystemWatcher`。
- webview 资源 URI 统一走 `asWebviewUri`。
- sidecar 应该跑在 **workspace extension host** 一侧，这样搜索、预览、索引都贴着文件发生。
- 不要把整个远程工作区镜像回本地再让 Trainer 工作。
- 远程访问时仍然只要求用户“装扩展 + 配 API”；远程能力由 VS Code 现成体系承担。

这里还需要一个很现实的补充设计：

- 如果 sidecar 在远端运行，而用户不希望把 API key 存到远端，就要支持 `credentialMode = workspace_secret | ui_proxy`。
- `workspace_secret` 最简单，适合私人远程机。
- `ui_proxy` 更安全，适合团队远程主机或不可信远程环境。

### 7.11 Pi 可以借什么，不可以借什么

你提到借鉴 Pi，这个方向是对的，但要借得非常克制。

**Pi 最值得借的不是“整套 agent 外壳”，而是三类基础契约：**

1. **project-local settings**
   - 全局设置 + 项目内设置叠加
   - 不同工作区可以有不同权限、不同 provider、不同工具默认值
2. **permission rules**
   - allow / ask / deny
   - 按路径、按工具、按命令类别做规则
   - 权限决策可审计
3. **remote operation abstraction**
   - 把远程执行视为一种能力，不把它写死进主逻辑

Trainer 值得直接借的设计形状：

- `.pi/settings.json` 这种 project-local settings 思想，可改造为 `workspace.json + AGENT_POLICY.md + mountedSources`
- `@pi-lab/permissions` 这种显式权限层，可改造为 Trainer 的 `authorityMode + allowedOperations + root policy`
- Pi 的 cwd / project 发现思路，可改造为 Trainer 的 `activeWorkspaceRoot` 发现与恢复机制

Trainer 不该直接借的部分：

- 把 Pi 整体当成 Trainer 的运行时骨架
- 把通用 coding agent 的开放权限姿态照搬进来
- 把远程执行默认做成无边界 shell

一句话总结：

- **借 Pi 的权限模型、项目局部配置、远程抽象**
- **不借 Pi 的通用 agent 产品边界**

## 8. 搜索与资料利用：不要把默认方案做成复杂 RAG

你明确说了不要考虑部署复杂的 RAG 方案。这一点非常对。

### 8.1 最强默认搜索路线

Trainer 默认不应该围绕“向量数据库 + 外部检索服务”设计。

默认最优路线：

1. 结构化 chunking
2. SQLite metadata
3. SQLite FTS5 lexical search
4. metadata filters
5. recency / trust / project weighting
6. optional provider rerank
7. optional local embeddings enhancement

也就是：

```text
query
 -> normalize
 -> SQLite FTS5 lexical recall
 -> project/trust/freshness filter
 -> top-k chunk merge
 -> optional LLM rerank
 -> citations
```

这已经足够强，而且完全不需要用户部署任何搜索基础设施。

### 8.2 为什么默认不以向量检索为核心

因为对 Trainer 来说：

- 大多数资料是代码、文档、课程笔记、项目说明。
- 这些内容的定位很多时候 lexical + structural chunking 更可靠。
- 向量检索更适合作为增强，而不是产品的存在前提。

所以默认路线应该是：

- **lexical-first**
- **semantic-optional**

### 8.3 什么时候启用语义增强

如果当前 active provider 支持 embeddings，可以启用：

- provider embeddings
- local cache
- internal local index

但原则仍然是：

- 不要求外部向量数据库服务。
- 不把 semantic memory 写成“必须有”。
- 不把 HashingEmbedder 伪装成真正语义检索。

### 8.4 如果保留 qdrant-client，应如何定位

仓库里已经有 `qdrant-client`。

最合理定位：

- 作为 sidecar 内部、完全本地、可选增强索引。
- 不在用户文档中要求“部署 Qdrant”。
- 不把它设计成默认依赖能力。

更强的默认方案仍然是：

- SQLite FTS5 + provider rerank

### 8.5 URL 内容抽取该直接借什么

最优选择：

- `Trafilatura`（Apache-2.0）

它应直接替换：

- 手写 HTML regex
- 脆弱网页正文抽取逻辑

Trainer 只保留：

- network policy
- trust / provenance
- import bookkeeping

### 8.6 搜索结果必须是可教学结果

每个结果不能只是 chunk 文本，必须附带：

- 标题
- 来源路径/URL
- 所属项目
- trust 状态
- 命中原因
- 摘要片段
- 可否注入训练卡
- 引用 ID

这样搜索才服务训练，而不是只服务上下文堆叠。

### 8.7 最好的资料搜索不是只搜 chunk，而是搜五层信号

真正强的 Trainer 搜索，至少要同时利用：

1. 文件名 / 路径
2. 标题 / heading / symbol
3. 正文 chunk
4. 资源元数据（项目、标签、trust、时间、文件类型）
5. 训练相关信号（最近引用过、最近练过、是否卡住过）

推荐排序链路：

```text
query
 -> path/title/symbol recall
 -> FTS5 content recall
 -> metadata filter
 -> project/trust/recentness weighting
 -> optional provider rerank
 -> teaching-oriented packaging
```

这比“只有向量召回”更符合代码学习、资料回看、项目训练三种核心场景。

### 8.8 远程工作区搜索必须贴着工作区执行

只要支持远程访问，搜索就必须遵守一个规则：

- **索引与搜索尽量在工作区侧发生，结果而不是整个文件树回传到 UI**

原因很简单：

- 更快
- 更省流量
- 更少编码/路径问题
- 更适合大目录

所以：

- 本地工作区：sidecar 本地索引本地搜索
- Remote SSH / Tunnels / Dev Container：sidecar 远程索引远程搜索
- UI 只拿结果、预览片段、引用信息、必要的富预览字节流

## 9. 如何彻底发挥大模型能力

Trainer 不是简单聊天工具，所以要把不同协议的长处发挥出来。

### 9.1 OpenAI Responses

适合：

- structured outputs
- tool calls
- reasoning models
- multimodal inputs
- future file/web/tool integration

Trainer 里应优先用在：

- coach reply
- plan update
- training card generation
- message parts generation
- resource-grounded synthesis

### 9.2 Anthropic Messages

适合：

- tool use
- long-context coaching
- critique / explanation
- thinking budget controls
- prompt cache

Trainer 里应优先用在：

- critique
- deep explanation
- dialogue-heavy coaching

### 9.3 Gemini

适合：

- multimodal understanding
- long context
- function calling
- Google 生态资料能力

Trainer 里应优先用在：

- 大体量资料理解
- multimodal 资源说明

### 9.4 OpenAI-compatible profiles

这类 profile 不是降级，而是适配层。

应支持：

- OpenRouter
- Ollama
- DeepSeek
- Kimi
- Together
- 其他兼容端点

但必须诚实展示：

- 这个端点支持哪些能力
- 哪些能力只是兼容 chat，而不支持 Responses 级能力

### 9.5 大模型能力最大化的关键不是“更大 prompt”

真正有效的是：

- typed outputs
- task binding
- capability gating
- memory retrieval hierarchy
- resource citations
- evidence loop
- teaching policy

大模型能力在 Trainer 里的正确位置是：

- 生成高质量教学动作
- 解释与追问
- 结构化总结
- 训练卡生成
- 搜索结果 rerank
- 计划/项目/能力图更新

而不是：

- 代替学生做题
- 直接写完整项目代码
- 把所有消息都变成长回答

## 10. 会话渲染：必须从 markdown-only 升级为 typed parts

如果 Trainer 想成为强工具，会话渲染绝不能停留在“一个 markdown 字符串”。

### 10.1 推荐 part 类型

```ts
type TrainerMessagePart =
  | { type: "markdown"; markdown: string }
  | { type: "code"; language?: string; code: string }
  | { type: "diff"; patch: string }
  | { type: "math"; tex: string; display: boolean }
  | { type: "mermaid"; source: string }
  | { type: "table"; columns: string[]; rows: unknown[][] }
  | { type: "citation"; resourceId: string; chunkId?: string; label: string }
  | { type: "tool_call"; id: string; name: string; status: string; args: unknown }
  | { type: "tool_result"; callId: string; result: unknown; error?: string }
  | { type: "reasoning"; summary: string; redacted?: boolean }
  | { type: "training_card"; cardId: string }
  | { type: "plan_update"; planId: string; changes: unknown[] }
  | { type: "test_result"; command: string; status: "pass" | "fail" | "unknown"; outputRef?: string }
  | { type: "file_preview"; resourceId: string; path: string }
  | { type: "checklist"; items: Array<{ label: string; done: boolean }> }
  | { type: "alert"; level: "info" | "warn" | "error"; title: string; detail?: string };
```

### 10.2 可以直接借的项目

#### `assistant-ui`（MIT）

适合直接借：

- message primitive 设计
- tool/source block 组件思想
- composable renderer registry
- artifacts / citations / tools 的布局思路

不一定要整套迁入：

- runtime
- 服务端协议

#### `Vercel AI Elements`（Apache-2.0）

适合借：

- 消息类型分类法
- reasoning / sources / tool / artifact / terminal / test-result / file-tree 这些 UI taxonomy

不适合直接依赖为核心 runtime：

- 它更适合做设计参照和局部组件灵感

### 10.3 Renderer 原则

- Unknown part 安全回退为 JSON preview。
- 不渲染 raw HTML。
- 长输出默认折叠。
- 引用必须可跳转到 Resources。
- test result / diff / file preview 绝不能塞回 markdown。
- reasoning 只展示允许展示的摘要。

## 11. 顶级记忆架构：总计划记忆 + 分项目记忆 + 训练记忆

“顶级记忆能力”不等于“向量库越大越好”。

真正强的记忆是分层的。

### 11.1 记忆层

| 层 | 内容 | 默认存储 | 是否总注入 |
| --- | --- | --- | --- |
| Master plan memory | 长期能力目标、路线、阶段 | SQLite + `memory/master-plan.md` | 否，只注入摘要 |
| Project memory | 当前项目目标、约束、阻塞 | SQLite + `projects/<id>/plan.md` | 仅当前项目 |
| Session memory | 当前对话中的局部上下文 | 会话状态 + summary | 当前会话 |
| Episodic memory | 训练事件、错误、反馈、证据 | append-only SQLite | 检索式 |
| Resource memory | 资源 provenance、trust、chunks | workspace + SQLite | 检索式 |
| Skill mastery map | 概念掌握度、误区、迁移能力 | structured table | 训练时 |
| Review memory | FSRS 卡状态 | structured table | 训练时 |
| Preference memory | 学习节奏、语言、风格偏好 | SQLite / VS Code state | 少量 |
| Provider memory | profile 健康、失败模式、能力缓存 | provider cache | 仅设置/诊断 |

### 11.2 记忆更新规则

每次 turn 后不要全量写记忆，而是只写高价值事件：

- 新的长期目标
- 项目约束变更
- 新识别出的稳定误区
- 已验证的能力提升
- 关键资源引用
- 训练卡评级
- 重要 handoff

### 11.3 最好的检索顺序

每次回答的上下文优先级建议：

1. 教练边界和系统策略
2. 当前用户问题
3. 当前文件/选区/工程上下文
4. 当前项目计划与 blocker
5. 最近训练卡和 mastery
6. 当前查询相关资源
7. 最近相关证据与错误
8. 用户偏好

不要：

- 每轮注入整份 master plan
- 每轮注入整份资料库
- 每轮注入所有历史消息

### 11.4 可参考但不默认依赖的记忆项目

| 项目 | 借什么 | 默认是否依赖 |
| --- | --- | --- |
| LangMem | 记忆分类与工具化思路 | 否 |
| Mem0 | 记忆抽取层思路 | 否 |
| Letta | memory blocks / hierarchy | 否 |
| Zep | temporal memory / graph 思路 | 否 |

这些项目最多做“参考设计”，不要把默认架构建立在外部 memory SaaS 之上。

## 12. 彻底做强但仍保持 API-only 的最优实现路径

这一节给未来真正改代码的人或 agent 看。

### 第 1 阶段：配置与协议

目标：

- Provider v2 schema
- profile registry
- protocol enum
- model aliases
- task bindings
- provider diagnostics

直接借：

- `cc-switch` 的 profile 管理、history、template、atomic write 思想

### 第 2 阶段：Direct adapters

目标：

- OpenAI Responses
- OpenAI Chat Completions
- Anthropic Messages
- OpenAI-compatible

直接借：

- 官方 SDK
- `Pydantic AI` 的 provider/model abstraction 思想

### 第 3 阶段：Training 引擎

目标：

- 单卡片状态机
- FSRS 调度
- 证据闭环
- handoff 回项目

直接借：

- `ts-fsrs` 或 `py-fsrs`

### 第 4 阶段：Resources workspace

目标：

- active workspace
- manifest
- provenance
- resource tree
- preview pipeline
- preview artifacts
- authority ledger
- trash / checkpoint
- open-in-editor fallback

直接借：

- `OpenClaw` 的 workspace 思路
- `Pi` 的 project-local settings / permission 形状
- `react-arborist`
- `CodeMirror 6`
- `react-pdf` / `PDF.js`
- `MarkItDown`
- `docx-preview`
- `Mammoth.js`
- `Shiki`
- `TanStack Table`
- `wavesurfer.js`

### 第 5 阶段：搜索与引用

目标：

- SQLite FTS5
- path/title/symbol recall
- structured chunking
- citations
- optional rerank
- remote-side execution

直接借：

- `Trafilatura` URL 抽取
- SQLite FTS5
- 现有远程工作区能力，不自建同步层

### 第 6 阶段：会话渲染

目标：

- typed parts
- tool/source/test/diff/file preview renderer

借：

- `assistant-ui` 组件思想
- `Vercel AI Elements` taxonomy

### 第 7 阶段：记忆分层

目标：

- master/project/session/resource/review 分层
- retrieval hierarchy
- memory update policies

借：

- `OpenClaw` workspace / memory 文件组织思想
- `LangMem` / `Letta` 的层次设计思想

## 13. 明确不建议进入默认路径的方案

这些东西不是不能支持，而是不应该成为默认架构基础：

- LiteLLM Gateway 作为消费者默认依赖
- Qdrant server / cloud 作为资料搜索前提
- SearXNG 作为默认搜索前提
- Temporal 作为默认任务系统
- LangChain/LangGraph 作为整个 Trainer 核心骨架
- 通用 agent runtime 嵌入
- 外部 memory SaaS 作为默认记忆层
- 复杂 Docker sandbox 作为默认资料能力前提
- OnlyOffice / Collabora / LibreOffice Online 作为默认文件预览基础
- 自建 SSH/SFTP 网关或远程同步守护进程作为默认远程访问前提
- 先把远程工作区镜像回本地再让 Trainer 工作

理由只有一个：

- **会破坏“只配 API 就能用”的用户路径。**

## 14. 哪些东西必须自研

尽管我们要大量借现有项目，但这些东西必须是 Trainer 自己的：

- active workspace root / folder sovereignty 契约
- 训练卡生成与证据回流状态机
- 计划与训练的联动
- 项目 handoff 机制
- 能力地图与项目迁移
- provider capability 的诚实展示
- 资源信任状态与教学使用策略
- preview tier 选择策略
- 远程工作区下的 credentialMode 与权限策略
- 训练时的提示层级
- 记忆更新策略

这部分是 Trainer 的灵魂，不该外包给框架。

## 15. Agent 与工程守则

未来任何 agent 修改 Trainer，必须先按这个顺序判断：

1. 这是通用基础设施还是 Trainer 特化逻辑？
2. 如果是通用基础设施，是否已有 MIT/Apache/BSD 项目可直接借？
3. 借这个项目会不会给默认用户增加部署成本？
4. 如果会增加部署成本，能不能降级成内置本地能力？
5. 如果仍不能，是否应只保留为高级可选项？
6. 这次改动是“直接移植代码”“移植结构”还是“只借设计”？
7. 是否需要补充 license / attribution 说明？
8. 这次改动是否仍然尊重 active workspace root 与 remote-safe 契约？

严禁：

- 为了“做强”而把默认用户路径做重。
- 为了“支持更多 provider”继续堆 if/else。
- 为了“做搜索”默认要求外部向量服务。
- 为了“做记忆”把一切聊天都塞进语义索引。
- 为了“更像 agent”把 root 外全局写权限交给模型。
- 为了“做远程”继续假定所有路径都是本地绝对路径。
- 为了“做预览”把重型 Office 在线服务变成默认依赖。

## 16. 最终推荐结论

如果现在就问：**Trainer 最优的底层改造参考到底是什么？**

答案是：

### Provider / 模型配置

- **直接借 `cc-switch` 的 profile/config 管理形状**
- **借 Claude Code 的公开 model config 思路**
- **借 `Pydantic AI` 的 provider/model abstraction**
- **默认 direct API，不默认 gateway**

### Training

- **直接借 `ts-fsrs` / `py-fsrs`**
- **借 retrieval practice / deliberate practice / worked-example fading 的教育策略**

### Resources / Sandbox

- **借 `OpenClaw` 的 workspace-first 思想**
- **借 `Pi` 的权限模型、project-local settings、remote abstraction**
- **借 `react-arborist` 做文件树**
- **借 `CodeMirror 6`、`react-pdf`、`PDF.js`、`Shiki`、`TanStack Table`、`docx-preview`、`Mammoth.js`、`MarkItDown`、`wavesurfer.js` 做预览与转换**
- **对 `.ipynb`、图片、视频等格式坚持“quick preview + native editor”双轨**

### Workspace authority / Remote

- **active workspace root 是第一公民**
- **root 内可完全自治，root 外默认无写权限**
- **远程访问优先复用 VS Code Remote SSH / Tunnels / Dev Containers / WSL**
- **sidecar 贴着工作区运行，不自建远程同步层**

### Search

- **默认 path/title/symbol + SQLite FTS5 + metadata + rerank**
- **semantic enhancement 只做 optional local enhancement**
- **不让默认方案依赖外部 RAG 基础设施**

### Conversation rendering

- **借 `assistant-ui` / `Vercel AI Elements` 的渲染 taxonomy**
- **建立自己的 typed parts registry**

### Memory

- **借 OpenClaw 的 workspace memory 组织方式**
- **借 LangMem / Letta 的层次设计思想**
- **但实现仍用 Trainer 本地分层记忆**

这条路线能同时满足：

- 强功能
- 高复用
- 可商用
- 易实现
- 易维护
- 默认只配 API 就能用

## 17. 参考来源与许可

### 17.1 Provider / 配置

- OpenAI Responses API：https://platform.openai.com/docs/api-reference/responses
- Anthropic Messages API：https://docs.anthropic.com/en/api/messages
- Gemini GenerateContent：https://ai.google.dev/gemini-api/docs/text-generation
- Claude Code model config：https://code.claude.com/docs/en/model-config
- `cc-switch`（MIT）：https://github.com/HoBeedzc/cc-switch
- `Pydantic AI`（MIT）：https://pydantic.dev/docs/ai/models/overview/

### 17.2 Workspace / 权限 / 远程

- `OpenClaw` agent workspace（MIT）：https://github.com/openclaw/openclaw/blob/main/docs/concepts/agent-workspace.md
- `Pi`（MIT）：https://github.com/earendil-works/pi
- Pi settings：https://pi.dev/docs/latest/settings
- `@pi-lab/permissions`：https://pi.dev/packages/%40pi-lab/permissions
- Pi extensions / remote execution：https://pi.dev/docs/latest/extensions
- VS Code Remote SSH：https://code.visualstudio.com/docs/remote/ssh
- VS Code Remote Tunnels：https://code.visualstudio.com/docs/remote/tunnels
- VS Code API `workspace.fs`：https://code.visualstudio.com/api/references/vscode-api#workspace
- VS Code webview guide：https://code.visualstudio.com/api/extension-guides/webview
- `react-arborist`（MIT）：https://github.com/brimdata/react-arborist
- `CodeMirror 6`（MIT）：https://codemirror.net/docs/
- `react-pdf`（MIT）：https://github.com/wojtekmaj/react-pdf
- `PDF.js`（Apache-2.0）：https://mozilla.github.io/pdf.js/
- `Shiki`（MIT）：https://github.com/shikijs/shiki
- `TanStack Table`（MIT）：https://tanstack.com/table/latest

### 17.3 预览 / 转换

- `MarkItDown`（MIT）：https://github.com/microsoft/markitdown
- `docx-preview`（Apache-2.0）：https://github.com/VolodymyrBaydalka/docxjs
- `Mammoth.js`（BSD-2-Clause）：https://github.com/mwilliamson/mammoth.js
- `wavesurfer.js`（BSD-3-Clause）：https://github.com/katspaugh/wavesurfer.js

### 17.4 搜索 / 抽取

- SQLite FTS5：https://www.sqlite.org/fts5.html
- `Trafilatura`（Apache-2.0）：https://trafilatura.readthedocs.io/en/stable/
- `qdrant-client`（MIT）：https://github.com/qdrant/qdrant-client

### 17.5 训练 / 记忆

- `ts-fsrs`（MIT）：https://github.com/open-spaced-repetition/ts-fsrs
- `py-fsrs`（MIT）：https://github.com/open-spaced-repetition/py-fsrs
- FSRS wiki：https://github.com/open-spaced-repetition/fsrs4anki/wiki
- Retrieval Practice：https://www.retrievalpractice.org/why-it-works
- `assistant-ui`（MIT）：https://www.assistant-ui.com/docs
- `Vercel AI Elements`（Apache-2.0）：https://elements.ai-sdk.dev/
- `LangMem`：https://langchain-ai.github.io/langmem/
- `Mem0`：https://docs.mem0.ai/
- `Letta`：https://docs.letta.com/
- Model Context Protocol：https://modelcontextprotocol.io/docs/getting-started/intro
