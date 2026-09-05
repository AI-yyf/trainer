# Trainer 终极完善目标

## 总目标

将 Trainer 建设为真正的 **AI Native Learning Operating System**：以用户多年成长为中心，以真实代码项目为学习现场，以 Coach 对话为统一超级入口，以全局记忆和全局计划维护长期方向，以项目记忆和项目计划承载每个项目的独立状态，以 Resources 提供可信知识，以受控 Sandbox 作为后端承载空间，以 Training 驱动单卡实践，以 Evidence、Evaluator、FSRS 和跨项目迁移持续更新用户能力模型。

Trainer 不只是帮助用户完成任务，也要从用户的 Idea、提问、回答、代码、测试、错误、反馈、纠正、成功和失败中持续学习，逐步改进：

- 对用户水平、目标和偏好的理解；
- 对项目结构、技术栈和风险的理解；
- 对教学方法、提示阶梯和任务难度的选择；
- 对计划安排和训练卡路由的判断；
- 对资料质量、可信度和适用场景的判断；
- 对界面、交互、性能和恢复机制的设计。

最终形成：

```text
用户成长
↔ Trainer 对用户的理解成长
↔ 项目理解成长
↔ 教学策略成长
↔ 产品质量持续改进
```

## 一、唯一中心闭环

```text
用户提出目标、问题、Idea 或学习需求
→ 理解用户、项目、资料和历史
→ 诊断当前能力缺口
→ 讨论学习或实现路径
→ 绑定全局目标与项目目标
→ 形成全局计划和项目计划
→ 提供可信资料和真实上下文
→ 拆成一个足够小的行动
→ 用户通过底部对话框和真实代码完成
→ 通过对话、文件、测试、诊断或评估验证
→ AI 追问、提示、纠错和反馈
→ 记录项目证据
→ 更新项目记忆、项目计划和复习状态
→ 将高质量、可迁移的证据汇总到全局记忆和全局计划
→ 安排复习、迁移和下一次挑战
```

用户最终应从“不知道如何理解、开始或解决”，成长到“能够独立理解、实现、验证、设计、迁移和创造”。

掌握度必须区分：

- **理解**：能解释为什么；
- **记忆**：延迟后仍能回忆；
- **做出**：能在代码中实现；
- **迁移**：换项目或场景仍能使用。

单次答对、读完资料、完成卡片或 AI 宣布完成，都不能直接代表掌握。

## 二、必须覆盖的真实使用场景

### 项目与工程

- 陌生项目、Python/TypeScript/JavaScript 服务、算法和模型仓库理解；
- 项目入口、调用链、函数契约、模块边界和 VS Code 诊断分析；
- Idea 收窄、MVP 设计、实现路线和逐步落地；
- 空白项目从零创建、运行、测试、调试和重构；
- 依赖库、API、算法、数学和工程原理学习；
- Debug、最小复现、假设验证和根因定位；
- 代码阅读、PR、Issue、Review、技术债和重构；
- GitHub、arXiv、官方文档及互联网资料学习；
- Remote workspace、SSH、文件归属和权限边界；
- AI 输出质量评估；
- 技术英语、Issue、PR 回复和技术写作；
- 连续失败降级、连续成功升级、弱点修复、复习和跨项目迁移。

### 长期成长

- 目标记忆；
- 弱点追踪；
- 重复错误识别；
- 教学偏好；
- 复习队列；
- 新项目迁移；
- 从初学者到熟练开发者，再到架构、设计和创造能力。

## 三、全局记忆、项目记忆和计划

系统必须维护分层状态：

```text
Trainer 全局身份
├── 全局记忆
├── 全局能力画像
├── 全局弱点
├── 全局教学偏好
├── 全局复习队列
├── 全局计划
└── 跨项目迁移证据

项目
├── project identity
├── project memory
├── project plan
├── project resources
├── project training state
├── project evidence
├── project review queue
├── workspace authority
└── handoff/recovery history
```

新增项目必须：

```text
发现项目
→ 建立稳定 project identity
→ 识别技术栈、入口、风险和学习机会
→ 创建或恢复项目记忆
→ 创建或恢复项目计划
→ 挂接全局计划
→ 继承全局能力和弱点
→ 生成项目专属学习路径
```

项目事实先写入项目层，只有可信且具迁移价值的证据才能更新全局层。项目切换、迁移、恢复和删除不能造成记忆、计划、资源或证据串线。

## 四、五个视图

- **Coach**：理解问题、项目和用户，解释、诊断、搜索资料、压缩下一步、承接所有回流和恢复。
- **Plan**：维护全局计划、项目计划、阶段、任务、阻塞和证据；支持持续讨论、候选变更、差异预览、确认、冻结和恢复；普通对话不能静默修改正式计划。
- **Resources**：展示和治理本地资料、GitHub、arXiv、官方文档和互联网来源，保留 provenance、可信度、新鲜度、引用和派生关系；支持导入、索引、搜索、预览、删除、恢复、训练和计划交接。
- **Training**：保持单卡优先，完成 `Learn → Try → Verify → Reflect → Return`，支持实践卡、闪卡、理论、Debug、API、Review、Research、英语和写作训练。
- **Settings**：提供简单但完善的多协议配置和真实能力状态，支持 OpenAI、Responses、Anthropic、Gemini、MiniMax 及兼容网关；自动处理 URL、协议、模型、SecretStorage 和能力探测。

底部对话框必须是超级入口，并明确当前模式：Coach 对话、Plan 讨论或正式候选、Resources 资料上下文、Training 回答/提示/验证/反思/回流、Settings 配置解释和恢复。

## 五、多协议 Provider

Trainer 必须做到：**对用户简单，对协议完善；对能力开放，对真实状态诚实。**

支持：

- OpenAI Chat Completions；
- OpenAI Responses；
- Anthropic Messages；
- Gemini；
- OpenAI-compatible gateway；
- MiniMax；
- 可扩展其他协议。

用户配置流程：

```text
选择 Provider
→ 选择模型
→ 输入 API key
→ 测试连接
→ 开始使用
```

自动处理：Provider 模板、Base URL、endpoint、协议、模型列表、request defaults、MiniMax thinking、chat probe、streaming probe、tools probe、vision probe、中文完整性、capability cache、SecretStorage、profile 切换和失败恢复。

能力必须独立判断：

```text
chat / streaming / tools / vision / structured output / embeddings / model listing
```

声明能力不等于实测能力。能力不足时平滑降级：tools 不可用仍可聊天；streaming 不可用切换非流式；vision 不可用阻止图片发送并解释；tools 不可用时正式计划/Agent 显示替代路径。

## 六、界面、内容和性能

在不减少功能的前提下做到凝练、克制和高级：

- 首屏只突出当前对象、状态、唯一主动作和下一步；
- 次要信息使用 details、折叠、弹层和二级面板；
- 图标、按钮和状态提示不重复；
- 训练、资料、计划、设置职责清晰；
- 280/340/420px 窄侧栏无溢出；
- 键盘、焦点、屏幕阅读器和多语言可用；
- 全局字体、字号、行高、字重、颜色、间距、代码块、表格、公式、Mermaid、引用和错误状态统一；
- AI 回复不能出现 raw JSON、traceback、HTTP 内部信息、API key、上游响应体或隐藏 reasoning 泄漏。

建立并验证性能预算：Preview app-ready、Extension activation、sidecar health、首屏和首次可交互、Provider 首字和流式间隔、搜索、索引、批量导入、Plan/Training 切换、workspace/session 恢复、内存和 bundle 体积。

采用懒加载、代码分割、缓存、单飞请求、请求取消、增量索引、批量处理和 workspace snapshot 复用，但不能牺牲正确性、权限和恢复能力。

## 七、真实状态和安全

每个重要操作都必须具备：

```text
intent
→ pending
→ executing
→ success/failure
→ authoritative ack
→ state patch/snapshot
→ retry/recovery
```

必须支持 request id、幂等、超时、取消、版本或 revision、错误原因、重试、ledger、checkpoint 和恢复。

禁止：

- 页面显示可用但点击必然失败；
- Preview 冒充真实 Host；
- upload 冒充 indexed；
- verified 冒充 Plan 完成；
- evidence 入队冒充已采用；
- Provider 声明能力冒充实测能力；
- Trainer sandbox 权限冒充项目源码权限；
- 超时重试导致重复持久化；
- 旧 workspace 污染新 workspace；
- 用删除测试、放宽权限、假数据或隐藏错误制造通过。

## 八、Trainer 的自我完善机制

每轮工作必须执行：

```text
发现问题
→ 分类为功能/逻辑/体验/性能/安全/协议/验证问题
→ 选择最高价值且可证明的问题
→ 最小修复
→ 更新必要契约和测试
→ 局部验证
→ 跨层验证
→ 检查旧文案、注释和 parity
→ 检查新回归
→ 继续下一问题
```

用户反馈必须产生后果：

- “太难”→ 任务拆小、降低难度、增强提示；
- “太简单”→ 减少基础解释、增加真实场景和迁移；
- “你理解错了”→ 修正用户/项目模型、降低旧判断置信度；
- “资料不对”→ 降低来源权重、标记受影响知识和卡片；
- “计划不适合”→ 生成候选重排、展示差异、确认后更新；
- “这张卡不像真实工作”→ 改进卡片路由和生成规则。

记录并评估教学动作的效果：解释、提示、追问、资料、训练卡、计划和复习是否真正促进用户理解、实现、验证和迁移。

## 九、完成标准

只有以下条件全部满足才算完成：

1. Coach→Plan→Resources→Training→Verify→Reflect→Return→Memory→FSRS→Migration 真实闭环可重复运行。
2. 全局记忆、项目记忆、全局计划、项目计划和 Trainer 教学策略能够正确同步、隔离、恢复和持续更新。
3. Plan、Resources、Training、Settings 的真实 Host mutation、持久化和恢复可验证。
4. 50 个 canonical 场景按 Preview、Recovery、Live Provider、Real Sidecar、Training Return、Resource Grounding、Protocol、VSIX/Host 分层通过。
5. 200 个体验场景通过五视图、多语言、主题、窄侧栏、输入、状态、导航、恢复、无溢出和无 console error 验证。
6. Webview/Extension TypeScript、production/preview build、Python compile、Ruff、Pyright、后端全量测试、前端全量测试和 Playwright 通过。
7. `server/app` 与 `extension/bundled/server/app` 逐文件一致。
8. 浏览器预览、当前平台 VSIX、VS Code Host、SecretStorage、sidecar 重启和 workspace reopen 可稳定运行并恢复状态。
9. MiniMax 真实 Chat、中文、Streaming、Trainer turn、Plan、Training 和错误恢复通过；Tools/Vision 按真实 probe 判断，不伪造支持。
10. API key 只能通过 SecretStorage 或临时安全环境使用，不进入代码、日志、snapshot、测试产物或回复。
11. 每轮工作都完成发现问题、分类、最小修复、局部测试、跨层测试、检查回归和检查 parity 的循环。
12. 外部 Provider、网络、磁盘、VSIX、Host 或系统依赖阻塞时，记录原始证据并停止伪造成功。

## 最终目标

> **把 Trainer 做成一个对用户配置极简、对协议和后端能力强大、对界面极度克制、对状态和权限极度诚实、对性能持续可测、对教学结果真正负责，并且能从用户反馈中持续改进自身的 AI Native Learning Operating System。**
