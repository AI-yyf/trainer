# Trainer 规格说明书

版本：v1.0  
最后更新：2026-06-18  
项目路径：`H:\trainer_final`

## 1. 产品定义

Trainer 是一个嵌入 VS Code 侧边栏的长期代码教练系统，不是普通聊天插件，也不是网页工作台的缩小版。

### 核心职责
- 让用户在同一个教练主体下持续学习、练习、复盘、迁移
- 让对话、计划、资料、训练、设置五个视图各司其职
- 让任何学习结果都能回流到计划、资料和下一次训练
- 让 Trainer 只负责教练、解释、诊断、评估和编排，不替用户直接改代码

### 五视图架构
```
┌─────────────────────────────────────────────────┐
│                  Trainer Sidebar                 │
├──────────┬──────────┬──────────┬────────┬──────┤
│   对话    │   计划    │   资料    │  训练   │  设置 │
│  (Chat)  │  (Plan)  │ (Resources)│(Training)│(Settings)│
└──────────┴──────────┴──────────┴────────┴──────┘
```

## 2. 技术架构

### 前端
- **框架**: React 19
- **构建**: Vite + Rollup
- **样式**: CSS (全局样式表)
- **国际化**: 8 语言支持 (zh-CN, en-US, es-ES, fr-FR, de-DE, ja-JP, ko-KR, pt-BR)
- **状态管理**: Zustand
- **通信**: VS Code Webview API

### 后端
- **框架**: FastAPI (Python)
- **向量存储**: Qdrant
- **Provider**: OpenAI, Anthropic, Google Gemini 多协议支持

### 核心模块
```
extension/
├── webview/src/
│   ├── app/                    # 主应用
│   ├── components/             # 视图组件
│   │   ├── coach/             # 教练核心组件
│   │   ├── plan/              # 计划视图
│   │   ├── resources/         # 资料视图
│   │   ├── training/          # 训练视图
│   │   ├── settings/          # 设置视图
│   │   └── preview/           # 文件预览组件
│   ├── lib/                   # 工具库
│   │   ├── i18n/             # 国际化
│   │   ├── types.ts          # 类型定义
│   │   └── browserSidecar.ts  # 浏览器端代理
│   └── styles.css             # 全局样式
└── src/
    └── extension.ts            # VS Code 扩展入口

server/
├── server/                     # FastAPI 后端
├── tests/                     # 测试
└── shared/                    # 共享代码
    └── src/
        ├── workspaceAuthority/ # 工作区权限
        └── previewAssets/      # 预览资产
```

## 3. 五视图详细规格

### 3.1 对话视图 (ChatView)

**职责**: 超级入口，教练核心交互界面

**核心功能**:
- 消息流展示 (用户消息 + AI 回复)
- 即时追问、澄清、小测
- 轻量动作状态显示 (正在查资料、正在编排训练等)
- 卡片建议、任务拆解
- 训练触发入口

**关键状态**:
| 状态 | 显示要求 |
|------|---------|
| 空对话 | 给出可执行的起手建议 |
| 正在工作 | 轻量动作状态，不遮蔽消息 |
| 受阻 | 明确卡点和替代动作 |
| 结果回流 | 告知沉淀为证据/卡片/下一步 |

**交互规范**:
- 页面主角永远是消息流
- 用户发出物必须像消息
- Trainer 回复主形态也必须像消息
- 禁止变成完整工作台

### 3.2 计划视图 (CoachPlanView)

**职责**: 总计划 + 分项目子计划治理

**核心功能**:
- 主线、阶段、进度可视化
- 阻断、证据、回流关系显示
- 子计划折叠展开
- 计划与训练结果联动

**关键状态**:
| 状态 | 显示要求 |
|------|---------|
| 无正式计划 | 清晰告知下一步 |
| 有阻断 | 显示原因和建议动作 |
| 有证据待采纳 | 明确标注待处理 |
| 已冻结 | 一眼看出有意冻结 |

**交互规范**:
- 首屏可见当前主线
- 禁止变成聊天页
- 禁止普通问答偷偷改写正式计划

### 3.3 资料视图 (CoachResourcesView)

**职责**: 统一知识库 + 受控沙箱

**核心功能**:
- 资料搜索与检索
- 文件上传 (HTML, PDF, MD, 代码文档)
- 网页浏览与下载
- 知识原子抽取
- Workspace Authority 集成

**关键状态**:
| 状态 | 显示要求 |
|------|---------|
| 空库 | 告知可导入内容和起始方式 |
| 已索引 | 快速检索定位 |
| 来源不可信 | 清楚提示风险 |
| 可转化 | 明确可变成卡片/计划证据 |

**交互规范**:
- 首屏优先搜索和知识条目
- 禁止变成 CMS 或文件浏览器
- 禁止越权写用户工程代码

### 3.4 训练视图 (CoachTrainingView)

**职责**: 单卡片沉浸流，FSRS 调度

**子模式**:
- 闪记卡 (Flash cards) - 压缩记忆
- 实战卡 (Drill cards) - 知识压到动作
- 复盘卡 (Review cards) - 错误回流
- 场景卡 (Scenario cards) - 能力迁移

**核心功能**:
- 单卡片状态机
- FSRS 调度算法
- 训练结果回流
- 项目 handoff

**关键状态**:
| 状态 | 显示要求 |
|------|---------|
| 当前卡 | 必须突出 |
| 已完成 | 带结果回流 |
| 跳过 | 说明原因和去向 |
| 复盘 | 连接错误与下一张卡 |

**交互规范**:
- 默认一次只显示一张当前卡片
- 用户一眼知道要做什么
- 禁止变成多模块平铺大网站

### 3.5 设置视图 (CoachSettingsView)

**职责**: 系统控制面

**核心功能**:
- Provider 配置 (OpenAI, Anthropic, Gemini)
- 模型选择与别名映射
- 语言偏好 (8 语言)
- 训练偏好
- 工作区级配置
- 连接测试

**关键状态**:
| 状态 | 显示要求 |
|------|---------|
| 缺 key | 直说 |
| provider 不可用 | 直说 |
| 当前配置生效 | 显示生效范围 |

**交互规范**:
- 禁止承载业务正文
- 禁止伪装后台管理台
- 禁止隐瞒不可用状态

## 4. 核心能力矩阵

| 能力 | 状态 | 说明 |
|------|------|------|
| Provider v2 | ✅ | 多 profile、协议支持、Task binding |
| Workspace Authority | ✅ | 权限梯度、operation ledger、checkpoint |
| File Preview | ✅ | Tier A/B/C 三级预览 |
| Search | ✅ | SQLite FTS5、metadata filters |
| Training | ✅ | FSRS 调度、单卡片状态机 |
| Memory | ✅ | Master/Session/Project/Resource 分层 |
| Remote | ✅ | SSH/Tunnels/Dev Containers/WSL |
| Rendering | ✅ | Markdown/Code/Diff/Table/Citation |

## 5. i18n 规范

### 支持语言
- `zh-CN` - 简体中文 (首选)
- `en-US` - 英文 (首选)
- `es-ES` - 西班牙语
- `fr-FR` - 法语
- `de-DE` - 德语
- `ja-JP` - 日语
- `ko-KR` - 韩语
- `pt-BR` - 葡萄牙语

### 退化策略
1. 首选语言完整翻译
2. 回退到 `en-US`
3. `en-US` 为英文翻译基准

### 翻译管理
- 统一在 `copy.ts` 管理
- 390+ 翻译键
- 所有视图使用 copy.ts 导出

## 6. Workspace Authority

### 权限梯度
```
inspect < annotate < reorganize < generate < apply < destructive
```

### 核心组件
- `WorkspaceAuthoritySummary` - 权限摘要
- `WorkspaceAuthorityFacts` - 权限事实
- `describeWorkspaceAuthoritySummary` - 权限描述

### 状态字段
- `root` - 工作区根目录
- `source` - 来源 (workspaceFolder/folder/external)
- `permission` - 当前权限级别
- `ledgerEntryCount` - 日志条目数
- `checkpointCount` - 检查点数
- `trashRoot` - 回收站路径

## 7. 文件预览 Tier 系统

| Tier | 类型 | 说明 |
|------|------|------|
| A | Rich preview | CodeMirror 6, PDF.js, 富预览 |
| B | Converted | MarkItDown/Mammoth.js 转换 |
| C | Metadata | 元数据 + native editor 回退 |

## 8. 开发规范

### 组件命名
- 视图组件: `Coach{ViewName}View`
- 子组件: `{ComponentName}`
- 共享组件: `../coach/parts/`

### 状态管理
- 优先使用 Zustand store
- 避免前端自造核心真相
- 状态变化经由后端同步

### 样式规范
- 使用 `.css` 文件
- BEM-like 命名
- CSS 变量用于主题
- 适配 VS Code 主题

### 验证要求
- TypeScript 编译无错误
- 手动功能测试
- 端到端 smoke test
- i18n 多语言回退检查

## 9. 禁止事项

1. ❌ 不做形而上的设计口号
2. ❌ 不做只有概念、没有实现的壳
3. ❌ 不做与当前实现真相冲突的假完成态
4. ❌ 不做会破坏跨项目统一主体的碎片化设计
5. ❌ 不做把 VS Code 侧栏伪装成网页后台的设计
6. ❌ 不做"看起来高级但实际上更难懂"的交互

## 10. 参考文档

- `docs/trainer-ideal/trainer-product-design-spec.md` - 产品设计说明书
- `docs/trainer-ideal/trainer-development-prompt.md` - 开发提示词
- `docs/implementation-status.md` - 实施状态
