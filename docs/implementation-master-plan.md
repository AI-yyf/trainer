# Trainer 实施总计划

> Canonical planning docs now live in `docs/MASTER_IMPLEMENTATION_PLAN.md` and `docs/WORK_PLAN.md`.
> This file is kept as an implementation snapshot and older rollout reference.

版本：v1.0  
创建时间：2026-06-18  
目标：将 `H:\trainer_final` 打造成"跨项目统一的最强代码教练"

## 1. 产品愿景

Trainer 是一个嵌入 VS Code 侧边栏的长期代码教练系统，不是普通聊天插件，也不是网页工作台的缩小版。

**核心目标**：
- 让用户在同一个教练主体下持续学习、练习、复盘、迁移
- 让对话、计划、资料、训练、设置五个视图各司其职
- 让任何学习结果都能回流到计划、资料和下一次训练
- 让 Trainer 只负责教练、解释、诊断、评估和编排，不替用户直接改代码

## 2. 核心非协商约束

### 2.1 用户约束
默认用户不能被要求：
- 安装 Docker
- 跑本地服务集群
- 配置 Redis / Postgres / Elastic / Qdrant / Kafka
- 自建 RAG 基础设施
- 部署外部数据库、搜索服务、消息队列

**默认用户只配置**：
- provider 协议
- API key
- base URL（如需）
- 模型或模型别名

### 2.2 工程约束
- 能直接移植的成熟开源代码，就不要重复造轮子
- 需要强产品适配的地方，只保留薄适配层
- 不把底层依赖的复杂性直接暴露给最终用户
- 优先选 MIT / Apache-2.0 / BSD 这类商业友好许可

### 2.3 架构约束
- 默认路径必须是 `extension + bundled sidecar + local storage + direct API adapters`
- 语义检索可以有，但不能设计成"必须部署向量数据库才有资料搜索"
- 优先复用 VS Code Remote SSH / Remote Tunnels / Dev Containers / WSL

## 3. 八大核心能力矩阵

| 能力 | 状态 | 目标 | 复用项目 |
|------|------|------|----------|
| Provider v2 | ✅ 已就绪 | 多 profile、协议支持、Task binding | cc-switch, Pydantic AI |
| Workspace Authority | ⚠️ 进行中 | 权限梯度、operation ledger、checkpoint | Pi, Claude Code |
| File Preview | ⚠️ 进行中 | Tier A/B/C 三级预览 | CodeMirror 6, react-pdf, PDF.js, Shiki |
| Search | ⚠️ 进行中 | SQLite FTS5、metadata filters | Trafilatura |
| Training | ⚠️ 进行中 | FSRS 调度、单卡片状态机 | ts-fsrs, py-fsrs |
| Memory | ✅ 已就绪 | 分层记忆系统 | Claude Code |
| Remote | ✅ 已就绪 | SSH/Tunnels/Dev Containers/WSL | VS Code Remote |
| Rendering | ✅ 已就绪 | typed parts registry | assistant-ui |

## 4. 五视图职责定义

### 4.1 对话视图 (CoachConversationView)
- **职责**: 超级入口，教练核心交互界面
- **理想状态**: 
  - 页面主角永远是消息流
  - 用户发出的东西必须像消息
  - Trainer 回复的主形态也必须像消息
  - 轻量可见地展示"教练正在做什么"
- **禁止**: 
  - 把对话页变成完整工作台
  - 把计划、资料、训练的大块内容直接铺满消息流
  - 在没有明确计划动作的情况下静默修改正式计划

### 4.2 计划视图 (CoachPlanView)
- **职责**: 总计划 + 分项目子计划治理
- **理想状态**:
  - 一打开就能看到当前主线
  - 顶层始终强调"当前在做什么、为什么现在做、下一步做什么、如何验证"
  - 子计划可以折叠展开
- **禁止**:
  - 变成聊天页
  - 允许普通浏览或普通问答直接改正式计划
  - 以大量任务清单掩盖计划结构

### 4.3 资料视图 (CoachResourcesView)
- **职责**: 统一知识库 + 受控沙箱
- **理想状态**:
  - 首屏优先是搜索和知识条目
  - 每条资料都应该能追溯来源链、处理日志、新鲜度和可信度
  - 资料可以转成知识原子、卡片候选、计划证据
- **禁止**:
  - 退化成 CMS 或文件浏览器
  - 越权写用户工程代码
  - 把资料沙箱伪装成用户项目工作区

### 4.4 训练视图 (CoachTrainingView)
- **职责**: 单卡片沉浸流，FSRS 调度
- **子模式**:
  - 闪记卡 (Flash cards) - 压缩记忆
  - 实战卡 (Drill cards) - 知识压到动作
  - 复盘卡 (Review cards) - 错误回流
  - 场景卡 (Scenario cards) - 能力迁移
- **理想状态**:
  - 默认一次只显示一张当前卡片
  - 用户一眼知道当前要做什么
- **禁止**:
  - 变成多模块平铺的大网站
  - 把历史、复盘、依赖图全部抢占当前卡片区域
  - 让用户看不到当前唯一任务

### 4.5 设置视图 (CoachSettingsView)
- **职责**: 系统控制面
- **理想状态**:
  - 清楚显示 provider、模型、语言、训练偏好和运行状态
  - 诚实显示可用性、缺失项、测试结果和环境限制
- **禁止**:
  - 承载计划、资料、训练的业务正文
  - 伪装成后台管理台
  - 隐瞒当前不可用状态

## 5. 实施阶段

### 阶段 1: 核心闭环修复 (P0)

#### 1.1 i18n 系统完善
- [ ] 验证 8 语言回退链路
- [ ] 补充缺失的翻译键
- [ ] 确保 zh-CN 和 en-US 完整
- [ ] 其他 6 语言使用英文回退

#### 1.2 Training 视图完善
- [ ] 单卡片状态机完善
- [ ] FSRS 调度集成
- [ ] 证据回流 UX
- [ ] 卡片类型区分（闪记/实战/复盘/场景）

#### 1.3 App.tsx 重构
- [ ] 拆分巨型 App.tsx (6949 行 → 模块化)
- [ ] 提取常量到独立文件
- [ ] 提取翻译到 copy.ts
- [ ] 按视图拆分组件

### 阶段 2: Workspace Authority (P1)

#### 2.1 权限梯度实现
- [ ] 实现 6 级权限梯度 (inspect, annotate, reorganize, generate, apply, destructive)
- [ ] 实现 operation ledger
- [ ] 实现 checkpoint/trash 机制

#### 2.2 Authority UI
- [ ] WorkspaceAuthoritySummary 组件完善
- [ ] WorkspaceAuthorityFacts 组件完善
- [ ] 权限状态可视化

### 阶段 3: File Preview 系统 (P1)

#### 3.1 Tier 系统完善
- [ ] Tier A: 富预览 (CodeMirror 6, react-pdf, PDF.js, Shiki)
- [ ] Tier B: 转换为 markdown/HTML (MarkItDown, Mammoth.js)
- [ ] Tier C: metadata + native editor fallback

#### 3.2 文件类型支持
- [ ] PDF 预览 (react-pdf)
- [ ] DOCX 预览 (docx-preview)
- [ ] CSV/TSV 表格 (TanStack Table)
- [ ] PPTX/XLSX 转换

### 阶段 4: Search 系统 (P2)

#### 4.1 SQLite FTS5 集成
- [ ] 实现 FTS5 索引
- [ ] 实现 metadata filters
- [ ] 实现 path/title/symbol recall

#### 4.2 搜索结果教学化
- [ ] teaching signals
- [ ] citation 引用系统
- [ ] 可注入训练卡 toggle

### 阶段 5: 交互精修 (P2)

#### 5.1 空状态优化
- [ ] 对话空状态
- [ ] 资料空状态
- [ ] 训练空状态
- [ ] 计划空状态

#### 5.2 Loading 状态
- [ ] Skeleton loaders
- [ ] 进度指示器

#### 5.3 键盘导航
- [ ] Tab 导航
- [ ] 快捷键支持
- [ ] Focus 管理

## 6. 技术债务清理

### 高优先级
- [ ] 修复 AppRecovered.tsx 中的乱码翻译 ✅ (已修复)
- [ ] 统一 i18n 管理到 copy.ts ✅ (已修复)
- [ ] 完善类型导出
- [ ] 添加单元测试覆盖

### 中优先级
- [ ] 组件文档完善
- [ ] 代码注释规范
- [ ] 错误处理完善

## 7. 验证方法

1. **TypeScript 编译无错误**
2. **手动功能测试**
3. **端到端 smoke test**
4. **i18n 多语言回退检查**
5. **VS Code 侧栏场景检查**:
   - 窄宽度
   - 主题切换
   - 长文本
   - 空状态
   - 错误态

## 8. 开源复用清单

| 目标 | 可借项目 | 许可 | 如何借 |
|------|----------|------|--------|
| Provider 配置 | cc-switch | MIT | profile 管理、history、template |
| 训练算法 | ts-fsrs / py-fsrs | MIT | FSRS 状态更新算法 |
| 文件树 | react-arborist | MIT | 资源树组件 |
| 代码预览 | CodeMirror 6 | MIT | 文本/代码预览 |
| PDF 预览 | react-pdf | MIT | PDF viewer |
| 表格预览 | TanStack Table | MIT | CSV/TSV 预览 |
| 文档转换 | MarkItDown | MIT | 通用文档转换 |
| 文档预览 | docx-preview | Apache-2.0 | DOCX 预览 |

## 9. 禁止事项

1. ❌ 不做形而上的设计口号
2. ❌ 不做只有概念、没有实现的壳
3. ❌ 不做与当前实现真相冲突的假完成态
4. ❌ 不做会破坏跨项目统一主体的碎片化设计
5. ❌ 不做把 VS Code 侧栏伪装成网页后台的设计
6. ❌ 不做"看起来高级但实际上更难懂"的交互

## 10. 最高标准

**最高级的设计，是把巧思放进极简的设计和完美的交互中。**

Trainer 的目标不是"功能看起来完整"，而是"真正成熟、低理解成本、人性化、强教学、长期可用"。
