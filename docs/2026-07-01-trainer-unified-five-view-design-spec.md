# Trainer 统一教练五视图设计总规范

日期：2026-07-01  
状态：统一设计文档（用于指导后续产品、交互、实现、评审与验收）  
适用范围：`Coach / Plan / Resources / Training / Settings` 五视图、训练卡体系、闪记卡体系、资源沙箱、自进化、i18n、跨平台与远程语义  

## 1. 文档目的

这份文档把 Trainer 的目标、五视图职责、教学逻辑、命令逻辑、恢复逻辑、资源逻辑、训练逻辑和配置逻辑收敛成一份统一规范。

它解决三个问题：

1. 防止 Trainer 再次滑回“聊天壳子 + 一堆功能入口”的松散状态。
2. 让五个视图围绕同一个统一教练工作，而不是五个彼此割裂的小工具。
3. 让设计、前端、后端、训练生成、资源治理、跨平台适配都对同一套产品真相负责。

## 2. 文档优先级

当文档之间冲突时，按以下顺序取真相：

1. [docs/ui-contract.md](./ui-contract.md)
2. [docs/2026-06-29-unified-coach-master-plan.md](./2026-06-29-unified-coach-master-plan.md)
3. 本文档
4. [docs/trainer-ideal/trainer-product-design-spec.md](./trainer-ideal/trainer-product-design-spec.md)
5. 旧计划、旧截图、历史讨论

说明：

- `ui-contract.md` 负责“当前 shipped IA 与视图归属”。
- `unified-coach-master-plan.md` 负责“下一阶段产品方向与统一教练目标”。
- 本文档负责“把方向翻译成可执行的五视图设计规范”。

## 3. Trainer 的唯一目标

Trainer 的唯一目标不是更会聊天，也不是更会自动写代码。  
Trainer 的唯一目标是：

**把 Trainer 做成“低理解成本、强教学、可恢复、可验证、可长期演进”的统一教练。**

这句话必须被拆成五个必须同时成立的条件：

1. **低理解成本**：用户一眼知道当前在发生什么、为什么、下一步做什么。
2. **强教学**：Trainer 不只回答问题，还要组织学习、安排练习、指导验证、推动迁移。
3. **可恢复**：任何阻塞都要说清楚当前卡在哪里、还能做什么、如何回到主线。
4. **可验证**：Trainer 不能把“说过了”当作“学会了”，必须有交付物、证据、验证方式。
5. **可长期演进**：Trainer 要能从资料、项目、结果反馈中持续变强，而不是每次靠重新提示。

## 4. 产品一句话定义

Trainer 是一个嵌入 VS Code 的、以对话为超级入口的 AI 原生统一教练。  
它围绕真实工作区、真实文件夹、真实代码、真实调试链路、真实资源材料，组织用户完成：

`理解 -> 计划 -> 学习 -> 练习 -> 验证 -> 复盘 -> 迁移`

它不是：

- 普通聊天插件
- 自动写业务代码的代理
- 文件管理器
- 训练后台
- 配置后台

## 5. 对成熟产品的吸收原则

Trainer 应深度借鉴成熟产品，但只能借鉴**交互逻辑、控制逻辑、恢复逻辑、配置分层、权限语义、知识组织方法**，不能机械抄布局。

### 5.1 应借鉴的成熟模式

1. **Codex**
   - `AGENTS.md` 的分层指导
   - Skills 的可复用工作流
   - Sandbox / approvals 的边界感
   - Subagents 的任务分派思维
2. **Claude Code**
   - 命令式入口
   - `/config`、`/permissions`、`/memory` 这种可见、可管理、可恢复的控制面
   - 项目记忆与自动记忆
   - hooks / checkpoints / rewind 背后的恢复心智
3. **Trae**
   - Project Rules
   - Skills & Commands
   - Models / provider / custom agent 的集中管理
   - SOLO 模式对长任务陪伴的组织方式
4. **VS Code**
   - Remote SSH / Tunnels / Dev Containers / WSL 的原生远程语义
   - Debugging 的运行、断点、变量、调用栈、调试控制台结构
   - IntelliSense 的 hover / signature help / definition / call site 证据链
   - Prompt files 的“手动触发、可复用、可版本化”思路
5. **Finder / Files**
   - 搜索优先
   - 标签、列表、预览、位置信息
   - “浏览 + 查找 + 快速预览”的低理解成本文件心智

### 5.2 不应照抄的部分

- 不照抄 Claude Code / Codex 的终端外形
- 不照抄 Trae 的完整 IDE 布局
- 不照抄 Finder 的大面积桌面式文件浏览
- 不做第六个顶层视图
- 不把所有高级能力摊平成仪表盘

## 6. 统一教练的总体心智模型

Trainer 不是五个平行功能页。  
Trainer 的真实结构应该是：

- **Coach**：统一教练主体，超级入口，恢复中心
- **Plan**：教学主线与证据治理中心
- **Resources**：知识供给链与受控沙箱
- **Training**：单卡片训练执行器
- **Settings**：能力真相与配置控制中心

用户应当感受到的不是“我要去哪个功能页”，而是：

1. 我先跟教练说当前目标或困惑。
2. 教练帮我理解、拆解、安排下一步。
3. 真正的主线被沉淀到计划里。
4. 需要资料时，资料页负责把材料变成可用知识。
5. 需要练习时，训练页只给我当前这一张卡。
6. 完成或卡住时，结果会回流给教练与计划。
7. 配置与能力状态始终在设置页说真话。

## 7. 五视图全局约束

### 7.1 不可破坏的 IA 规则

1. 只有五个顶层视图：`Coach / Plan / Resources / Training / Settings`
2. `First Look`、训练子模式、恢复页、诊断页都只能是五视图内部流程
3. 任何新能力都必须先被塞进这五类职责之一

### 7.2 全局交互规则

1. **对话是超级入口**
   - 新任务从 Coach 进入
   - slash / skill / action pill 从 Coach 可见
2. **正式主线只能由 Plan 记账**
   - 普通聊天不能静默修改正式计划
3. **训练必须单卡优先**
   - 默认一次只让用户面对一个当前任务
4. **资料必须可追溯**
   - 来源、时间、可信度、转化去向都必须可查
5. **设置必须说真话**
   - provider、model、sidecar、workspace、权限、远程状态都不能假绿灯
6. **任何结果都必须能回流**
   - 训练结果回流到计划
   - 资料转知识回流到训练
   - 配置阻塞回流到 Coach 的恢复路径

### 7.3 全局状态模型

每个视图都必须显式处理这些状态：

- `empty`：还没有内容，但要告诉用户最可信的下一步
- `loading`：正在检查、生成、索引或恢复
- `ready`：当前可操作
- `blocked`：受阻，但要说清阻塞原因和替代动作
- `degraded`：部分功能可用，部分不可用
- `completed`：当前阶段闭环已完成，并给出回流方向

### 7.4 全局跨视图回流结构

所有跨视图 handoff 都应带上统一元信息：

- `sourceView`
- `targetView`
- `reason`
- `status`
- `evidence`
- `nextAction`
- `returnPath`

这意味着 Trainer 不能只是“点一下跳过去”，而必须让用户始终知道：

- 为什么跳转
- 现在处于什么状态
- 做完以后回哪

## 8. 学习总流程：先学习，再测试/验证

Trainer 的训练默认顺序必须是：

`Learn -> Try -> Verify -> Reflect -> Return`

而不是：

`Question -> Submit -> Grade`

### 8.1 Learn 阶段的要求

进入正式练习前，Trainer 必须先判断用户是否已具备最低必要理解。

当用户尚未建立最小理解时，Trainer 应优先提供：

- 一段极短的概念引导
- 一个最小示例
- 一张闪记卡
- 一条“先看哪里”的材料指引
- 一个与当前文件夹直接相关的观察任务

### 8.2 Try 阶段的要求

Try 必须落在真实文件夹、真实文件、真实命令、真实调试动作上。  
不允许大量纯空中考试。

### 8.3 Verify 阶段的要求

验证必须尽量依赖以下证据：

- 运行结果
- 调试观察
- 文件内容
- 函数契约恢复结果
- 资源引用与解释
- 用户复述

### 8.4 Reflect 阶段的要求

复盘不是“你答对了/答错了”，而是：

- 你卡在哪里
- 你误解了什么
- 哪条证据不足
- 下一张卡为何出现

## 9. Coach 视图规范

### 9.1 设计定位

Coach 是统一教练的主体，是自然语言、命令、技能、恢复、追问、转场的超级入口。

### 9.2 首屏承诺

用户一进入 Coach，就能看明白：

- Trainer 当前理解了什么
- 现在正在做什么
- 下一步建议是什么

### 9.3 这个视图要回答的核心问题

1. 教练听懂我了吗？
2. 它现在在帮我做什么？
3. 我要继续问、继续做，还是转去计划/资料/训练/设置？
4. 如果现在不能继续，卡在哪？

### 9.4 第一层信息架构

按首屏优先级排序：

1. 当前消息流
2. 当前回合的关键 typed parts
3. 轻量状态轨道（检查资料、对齐计划、生成训练卡、评估结果）
4. 上下文 chips（文件、选区、诊断、资源、工作区类型）
5. Composer
6. slash / skill deck

### 9.5 交互规则

1. 消息流必须永远是主角
2. 工具执行、计划更新、训练卡建议只能“附着”在消息里
3. 不允许把大块 Plan / Resources / Training 面板嵌进消息流抢主角
4. Composer 必须是常驻的、可继续的，不让用户失去推进感

### 9.6 命令与技能逻辑

Coach 应把命令分成五组，且分组始终稳定：

1. `Explain / Review`
2. `Plan / Next`
3. `Practice / Flash`
4. `Resource / Sandbox`
5. `Provider / Model / Runtime`

每组都要让用户形成肌肉记忆，而不是每次重新找入口。

### 9.7 教学逻辑

Coach 的回答结构默认应是：

1. 直接回答
2. 说清当前判断依据
3. 给出最小下一步
4. 必要时给出 handoff

对 remote / debug / function guidance，Coach 应分别优先触发：

- `remote`：工作区类型、主机归属、凭据归属、路径事实
- `debug`：复现、暂停点、坏状态观察
- `function guidance`：hover、signature、definition、call site 四段证据链

### 9.8 恢复逻辑

Coach 必须成为一切阻塞的恢复中心。

例如：

- provider 失败时：告诉用户还能做资料学习、计划整理、理论闪记，而不是只会报错
- sidecar 未就绪时：告诉用户哪些本地 UI 还可用，哪些不可用
- remote 语义不清时：先退回“确认工作区边界”

### 9.9 状态模型

- `empty`：给出 2-3 个可信起手式，而不是大段营销文案
- `loading`：显示当前动作，但不要像 job console
- `blocked`：明确原因、当前安全边界、替代路径
- `degraded`：明确“还能做什么”
- `completed`：明确“结果已回流到哪里”

### 9.10 这个视图绝不能出现什么

- 第二个 dashboard
- 伪终端日志页
- 会静默修改正式计划的聊天
- 假装模型可用的绿色状态

### 9.11 与其他视图的回流

- 去 Plan：沉淀正式阶段、证据、阻塞、下一步
- 去 Resources：补材料、索引材料、查看来源
- 去 Training：开始当前训练卡或恢复上次训练
- 去 Settings：修 provider、model、权限、工作区上下文

## 10. Plan 视图规范

### 10.1 设计定位

Plan 是教学主线、阶段治理、证据采纳、阻塞管理和长期演进的正式账本。

### 10.2 首屏承诺

用户一进入 Plan，就能看见：

- 当前主线是什么
- 为什么是现在做它
- 如何证明它完成

### 10.3 这个视图要回答的核心问题

1. 我现在到底在学什么主线？
2. 当前阶段为什么排在这里？
3. 什么算完成？
4. 哪些训练结果已经被采纳？哪些还只是证据？

### 10.4 第一层信息架构

按首屏优先级排序：

1. 当前主线卡
2. 当前阶段卡
3. 当前下一步
4. 阻塞原因 / 风险
5. 待采纳证据
6. 项目子计划
7. 复习队列摘要

### 10.5 交互规则

1. 首屏永远优先显示当前主线，而不是全量历史
2. 子计划可以展开，但不能盖过当前阶段
3. “证据”与“正式采纳”必须分层显示
4. freeze / replan 是正式动作，不能藏在聊天语义里

### 10.6 教学逻辑

Plan 不是任务管理器，它必须把每个阶段解释清楚：

- `goal`
- `whyNow`
- `expectedOutcome`
- `verifyMethod`
- `recommendedTraining`
- `blockingReason`

### 10.7 针对 remote / debug / function guidance 的设计要求

Plan 中要把这三类场景当作正式教学主线，而不是零碎 FAQ：

1. `remote`
   - 工作区边界理解
   - 凭据与宿主机归属
   - 容器 / 隧道 / WSL 迁移语义
2. `debug`
   - 最小复现
   - 单点暂停
   - 状态证明
3. `function guidance`
   - 编辑器证据链恢复
   - 安全修改范围
   - 调用点迁移

### 10.8 恢复逻辑

当用户卡住时，Plan 不能只写一句“blocked”。  
必须至少交代：

- 卡在哪个阶段
- 为什么卡住
- 暂时不建议推进什么
- 可替代的回退动作是什么

### 10.9 状态模型

- `no-plan`：先定义目标还是先生成第一版计划
- `active`：当前阶段、下一步、验证法清楚
- `blocked`：阻塞原因明确，替代路径明确
- `frozen`：这是有意冻结，不是系统失效
- `pending-evidence`：有证据待采纳
- `completed`：当前阶段闭环完成，并给出下一阶段

### 10.10 这个视图绝不能出现什么

- 聊天式长文
- 没有阶段层级的任务堆
- 浏览即修改的计划真相

### 10.11 与其他视图的回流

- 从 Coach 接正式目标
- 从 Resources 接资源证据和知识原子
- 从 Training 接完成结果、失败原因、复盘信号
- 从 Settings 接 provider / runtime 约束，影响计划推进方式

## 11. Resources 视图规范

### 11.1 设计定位

Resources 是 Trainer 的知识供给链，也是 AI 教练可支配的受控资料沙箱，但它不是普通文件管理器。

### 11.2 首屏承诺

用户一进入 Resources，就能快速完成：

- 找资料
- 看来源
- 看可信度
- 看能转成什么

### 11.3 这个视图要回答的核心问题

1. 我有哪些可用资料？
2. 这些资料值不值得信？
3. 它能不能变成知识、训练卡或计划证据？
4. 资料沙箱现在在哪个路径，它和用户项目有什么边界？

### 11.4 第一层信息架构

按首屏优先级排序：

1. 搜索输入与筛选
2. 资源条目列表
3. 当前资源快速预览
4. 来源 / 可信度 / 新鲜度 / license / 转化状态
5. 导入与索引动作
6. 沙箱根路径与治理说明

### 11.5 交互规则

1. 搜索优先，浏览其次
2. 列表项必须轻量，避免后台表格感
3. 预览必须是服务于判断与转化，不是大型阅读器替代品
4. 导入、索引、转卡、提炼知识必须是同一条供给链，而不是四套入口

### 11.6 资料沙箱设计

资料文件夹路径必须被明确设计为：

- 由用户选择或确认的 carrier root
- 由 AI 教练在该路径内组织、下载、整理、派生
- 与用户项目代码目录明确区分

这个路径要满足：

1. 可见
2. 可配置
3. 可迁移
4. 可校验
5. 跨系统语义稳定

Resources 里必须显式显示：

- 当前 carrier root
- 当前工作区与 carrier root 的关系
- AI 可以在其中做什么
- 不会越权做什么

### 11.7 自进化与资料治理逻辑

Resources 不只是存资料，而是要完成：

1. 导入
2. 索引
3. 打标签
4. 提取知识原子
5. 生成训练候选
6. 生成计划证据候选

对开源项目、文档、教程、URL，至少要记录：

- 来源 URL / repo
- 获取时间
- license 或许可判断
- 是否适合商用复用
- 是否已被 Trainer 转化

### 11.8 针对 remote / debug / function guidance 的设计要求

Resources 需要支持以下类型材料成为一等公民：

- 远程开发官方文档
- 调试文档、报错日志、trace、launch 配置示例
- API 文档、函数定义、调用样例、类型说明

并能把它们转成：

- remote 边界卡
- debug 最小闭环卡
- function contract 恢复卡

### 11.9 恢复逻辑

当资料不可索引、来源可疑、provider 不可用时，要明确区分：

- 现在无法索引
- 现在只能保存条目
- 现在只能本地预览
- 现在还不能生成训练卡

### 11.10 状态模型

- `empty`：告诉用户支持导入什么，以及导入后能干什么
- `indexing`：显示索引进度和当前阶段
- `ready`：可搜索、可预览、可转化
- `warning`：来源可疑 / 许可证待确认 / 内容过旧
- `blocked`：当前无法下载、无法解析、无法转化
- `derived`：已变成知识原子、训练卡候选或计划证据

### 11.11 这个视图绝不能出现什么

- CMS 后台
- 通用文件浏览器复制品
- 直接写入用户业务工程的行为
- 与用户项目工作区边界混淆

### 11.12 与其他视图的回流

- 给 Coach 提供引用资料与下一步建议
- 给 Plan 提供证据与学习材料
- 给 Training 提供闪记卡、练习卡、迁移卡素材
- 给 Settings 提供路径、下载、权限相关真相

## 12. Training 视图规范

### 12.1 设计定位

Training 是统一教练的训练执行器。  
它负责把“知道”压缩成“做到”，把“做到”变成“能验证、能迁移”。

### 12.2 首屏承诺

用户一进入 Training，第一屏不用读聊天历史，就要知道五件事：

1. 当前是哪张卡
2. 为什么现在是它
3. 我要交什么
4. 怎么验证
5. 做完回到哪里

### 12.3 这个视图要回答的核心问题

1. 我现在唯一要做的事是什么？
2. 这是学习卡、练习卡、复盘卡还是迁移卡？
3. 我该在什么文件夹、什么文件里动手？
4. 如何判断我真的完成了？

### 12.4 第一层信息架构

按首屏优先级排序：

1. 当前卡主体
2. `whyNow`
3. `learnerDeliverable`
4. `verificationSteps`
5. `returnWith`
6. 次级支持信息（来源、资料、前置概念、fallback）

### 12.5 训练子模式

Training 内只允许存在子模式，不允许长成第六视图。

必须支持的子模式：

- `learn-primer`
- `flash`
- `practice`
- `review`
- `scenario`
- `transfer`

### 12.6 Learn-first 训练逻辑

如果当前卡需要前置理解，则 Training 首先显示 primer，而不是直接考试。

primer 可以是：

- 一个最小概念框
- 一个极短示例
- 一张闪记卡
- 一条先去看的资源摘要
- 一个观察任务

当 primer 结束后，再进入实际 practice。

### 12.7 训练卡统一字段

每张 serious card 至少必须包含：

- `type`
- `scenarioPack`
- `title`
- `whyNow`
- `targetSkill`
- `problemStatement`
- `learnerDeliverable`
- `verificationSteps`
- `returnWith`
- `fallbackAction`
- `nextAfterCompletion`

### 12.8 训练卡设计要求

每张卡都必须具备三个明确锚点：

1. **文件夹锚点**
   - 这个训练属于哪个工作区 / 子目录
2. **证据锚点**
   - 这张卡基于哪个计划缺口、哪个资源、哪个上下文
3. **回流锚点**
   - 完成后回到 Coach 还是 Plan，还是触发下一张卡

### 12.9 针对 remote / debug / function guidance 的设计要求

这三类必须是首批一等场景包：

1. `remote boundary pack`
   - 判断工作区类型
   - 判断宿主机归属
   - 判断凭据放置位置
   - 说出一个路径事实
2. `minimal debug loop pack`
   - 复现一次
   - 停住一次
   - 证明一个坏状态
3. `function contract recovery pack`
   - hover
   - signature help
   - definition
   - call site
   - 安全下一步修改

### 12.10 闪记卡设计要求

闪记卡要解决的是记忆负担，而不是替代实战。

适合做闪记卡的内容：

- 远程语义规则
- debug 最小闭环规则
- 函数契约判断规则
- 依赖库关键 API
- 易混淆理论点

闪记卡一张只抓一个知识点或一个微技能。

### 12.11 复盘设计要求

复盘必须回答：

- 哪一步理解错了
- 哪条证据没拿到
- 为什么下一张卡比上一张更小或更换场景

### 12.12 恢复逻辑

Training 必须允许四种真实结果：

- `completed`
- `blocked`
- `skipped`
- `needs-primer`

每种结果都必须明确回流去向。

### 12.13 状态模型

- `no-card`：告诉用户为什么现在没有卡，以及如何生成下一张
- `primer`：先学习，再进入练习
- `active`：只有当前卡是主角
- `blocked`：显示 fallbackAction
- `verified`：完成并显示回流
- `review-due`：该复盘或复习，但不能抢走当前卡主角地位

### 12.14 这个视图绝不能出现什么

- 多列并排的大训练后台
- 当前卡被历史、资源、图谱、说明文压下去
- 用户看不出“现在该做哪一件事”

### 12.15 与其他视图的回流

- 回 Coach：说明结果、追问、继续陪伴
- 回 Plan：更新证据与阶段判断
- 回 Resources：沉淀经验、产出知识原子
- 回 Settings：暴露训练过程中发现的 provider / runtime 限制

## 13. Settings 视图规范

### 13.1 设计定位

Settings 是 Trainer 的能力真相中心和配置控制中心。  
它负责让用户知道 Trainer 现在到底能不能工作，为什么，差什么。

### 13.2 首屏承诺

用户一进入 Settings，应该第一眼知道：

- 现在能不能正常使用 Trainer
- 如果不能，缺哪块
- 如果能，当前配置影响范围是什么

### 13.3 这个视图要回答的核心问题

1. Provider 与 model 真正可用吗？
2. 当前配置作用于个人、项目还是会话？
3. 当前工作区上下文、远程模式、凭据建议是什么？
4. 哪些功能是降级可用的？

### 13.4 第一层信息架构

按首屏优先级排序：

1. 当前可用性摘要
2. Provider profile 与 model
3. 连接测试结果
4. 协议 / capability matrix
5. 语言与教学偏好
6. memory scope / review cadence / workspace context policy
7. remote credential guidance

### 13.5 配置分层要求

Trainer 的设置必须明确作用域：

- `personal`
- `project`
- `session`

每项设置都要让用户知道：

- 改了什么
- 影响什么
- 什么时候生效

### 13.6 针对成熟产品可借鉴的控制面

Settings 应吸收这些模式：

- Claude Code 的 `/config`、`/permissions`、`/memory`
- Codex 的 config、sandbox、approval、skills、AGENTS.md
- Trae 的 project rules、skills & commands、models

但在 Trainer 中必须转译成“教练能不能工作”和“教学能力受什么约束”的语言。

### 13.7 针对 remote / debug / function guidance 的设计要求

Settings 必须能明确表达：

- 当前工作区类型
- 当前远程环境
- 建议凭据放置位置
- 是否可访问诊断、选区、当前文件
- 哪些训练场景因此受影响

### 13.8 恢复逻辑

Settings 不是只给错误文案，它必须给恢复路径：

- 缺 key：去哪里填
- model 不存在：该刷新还是改 profile
- provider 认证失败：当前可降级做什么
- sidecar 未就绪：当前哪些 UI 还能用

### 13.9 状态模型

- `setup-needed`
- `testing`
- `ready`
- `degraded`
- `auth-failed`
- `model-missing`
- `runtime-unavailable`

### 13.10 这个视图绝不能出现什么

- 业务内容页
- 假绿色健康面板
- 隐藏性失败
- 一大堆品牌特化 copy

### 13.11 与其他视图的回流

- 回 Coach：恢复对话继续推进
- 约束 Plan：决定哪些计划动作可执行
- 约束 Resources：决定下载、索引、联网能力
- 约束 Training：决定能否生成、验证、评估某些卡

## 14. 资源自进化与开源复用策略

Trainer 的自进化，不是“让代理随便重写自己”，而是让 Trainer 更会：

1. 找资料
2. 选资料
3. 组织资料
4. 把资料转成教学资产
5. 从结果里学会改进下一轮教学

### 14.1 自进化流水线

1. 发现来源
2. 过滤 license / 维护状态 / 场景匹配度
3. 导入资料沙箱
4. 提取知识原子
5. 生成训练卡 / 闪记卡 / 计划证据候选
6. 用学习效果反向评分

### 14.2 复用原则

优先采用成熟、可商用、边界清楚的现成能力，而不是重造轮子。

优先复用：

- provider / model 抽象
- 资料解析与索引
- spaced repetition
- agent workflow grammar
- message / artifact primitives

避免默认引入：

- 重型外部 agent runtime
- 对部署环境要求高的向量数据库
- 与 VS Code 远程语义冲突的自建远程层

## 15. 跨平台与远程语义规范

Trainer 的产品语义必须在 Windows、macOS、Linux 上一致。

### 15.1 平台一致性要求

1. 路径展示允许平台差异，但边界语义不能变
2. 配置作用域不能因平台改变
3. 资料沙箱语义不能因平台改变
4. i18n fallback 链不能因平台改变

### 15.2 远程工作区类型矩阵

Trainer 至少要明确识别并表达：

- `local`
- `ssh`
- `tunnels`
- `dev-container`
- `wsl`

对每类都必须让用户看到：

- 代码实际位于哪里
- 命令实际运行在哪里
- 凭据默认该放哪里
- 一个可验证的路径事实

### 15.3 凭据与边界表达

Trainer 不能只说“远程已连接”。  
必须帮助用户形成以下判断：

- 我现在操作的是本地文件还是远程文件
- 当前 extension / sidecar / model 调用跨越了哪些边界
- 这个场景下把凭据放本地更安全，还是放远程更合理

## 16. i18n 规范

Trainer 必须保证：

- `zh-CN`
- `en-US`
- `es-ES`
- `fr-FR`
- `de-DE`
- `ja-JP`
- `ko-KR`
- `pt-BR`

都共享同一套结构，而不是只有中文可用。

要求：

1. 五视图的信息层级在所有语言里都不变
2. 长文本状态不挤爆窄栏
3. fallback 可预期
4. 不允许出现 mojibake

## 17. 当前实现锚点

本文档要落地，当前工程中的主要锚点如下：

- 顶层视图渲染：
  - `extension/webview/src/app/App.tsx`
- 五个核心视图：
  - `extension/webview/src/components/coach/CoachConversationView.tsx`
  - `extension/webview/src/components/plan/CoachPlanView.tsx`
  - `extension/webview/src/components/resources/ResourcesWorkbenchView.tsx`
  - `extension/webview/src/components/training/TrainingWorkbenchView.tsx`
  - `extension/webview/src/components/settings/CoachSettingsView.tsx`
- 命令与技能：
  - `shared/src/skillCatalog.ts`
- 远程工作区语义：
  - `shared/src/remoteWorkspace.ts`
- 训练卡路由：
  - `shared/src/trainingCardRouting.ts`
- 训练卡生成：
  - `server/app/training/card_generator.py`
- 对话意图与场景语义：
  - `server/app/llm/prompts.py`

## 18. 当前五视图截图参考

最新截图（生成时间：2026-07-01）：

- Coach：`output/playwright/trainer-coach-latest.png`
- Plan：`output/playwright/trainer-plan-latest.png`
- Resources：`output/playwright/trainer-resources-latest.png`
- Training：`output/playwright/trainer-training-latest.png`
- Settings：`output/playwright/trainer-settings-latest.png`

这些截图是“当前实现状态”的观察样本，不是未来设计真相本身。

## 19. 验收标准

只有当以下条件同时满足时，Trainer 才算接近目标状态：

1. 用户默认从 Coach 开始，而不是被迫理解系统结构
2. Plan 真正承载正式主线，而不是聊天摘要
3. Resources 真正能把资料变成知识资产与训练资产
4. Training 真正执行“先学习，再验证”的单卡闭环
5. Settings 在 provider、model、runtime、remote 上始终说真话
6. remote / debug / function guidance 成为一等教学场景
7. 五视图没有再长出第六个视图或隐形大后台
8. 结果能在 Coach / Plan / Resources / Training 之间稳定回流
9. i18n 和跨平台语义不破

## 20. 外部参考（2026-07-01 访问）

### OpenAI Codex

- Agent Skills  
  <https://developers.openai.com/codex/skills>
- AGENTS.md  
  <https://developers.openai.com/codex/guides/agents-md>
- Sandbox  
  <https://developers.openai.com/codex/concepts/sandboxing>
- Subagents  
  <https://developers.openai.com/codex/subagents>
- Best practices  
  <https://developers.openai.com/codex/learn/best-practices>

### Claude Code

- Overview  
  <https://code.claude.com/docs/en/overview>
- Commands  
  <https://code.claude.com/docs/en/commands>
- Settings  
  <https://code.claude.com/docs/en/settings>
- Permissions  
  <https://code.claude.com/docs/en/permissions>
- Memory  
  <https://code.claude.com/docs/en/memory>
- Hooks  
  <https://code.claude.com/docs/en/hooks-guide>
- Permission modes  
  <https://code.claude.com/docs/en/permission-modes>

### Trae

- Rules  
  <https://docs.trae.ai/ide/rules?_lang=en>
- Skills  
  <https://docs.trae.ai/ide/skills>
- Models  
  <https://docs.trae.ai/ide/models>
- IDE settings overview  
  <https://docs.trae.ai/ide/ide-settings-overview>
- SOLO Agent  
  <https://docs.trae.ai/ide/solo-coder>

### VS Code

- Remote Tunnels  
  <https://code.visualstudio.com/docs/remote/tunnels>
- Dev Containers  
  <https://code.visualstudio.com/docs/devcontainers/containers>
- WSL  
  <https://code.visualstudio.com/docs/remote/wsl>
- Debugging  
  <https://code.visualstudio.com/docs/debugtest/debugging>
- IntelliSense  
  <https://code.visualstudio.com/docs/editing/intellisense>
- Prompt files  
  <https://code.visualstudio.com/docs/copilot/customization/prompt-files>

### Finder / Files

- Finder tags  
  <https://support.apple.com/guide/mac-help/tag-files-and-folders-mchlp15236/mac>
- Finder organization and preview patterns  
  <https://support.apple.com/guide/mac-help/organize-your-files-in-the-finder-mchlp2605/mac>
- Files browse/search  
  <https://support.apple.com/en-us/102570>
- Finder view modes  
  <https://support.apple.com/guide/mac-help/change-folders-displayed-finder-mac-mchldaafb302/mac>
