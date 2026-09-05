# Trainer 增强实施计划

## 目标
基于 `docs/open-source-fit-and-provider-strategy.md` 的策略规范，持续完善 Trainer 的八大核心能力。

## 实施状态

### 1. Provider v2 ✅ 已就绪
- 多 profile 支持
- 多协议支持 (openai_responses, anthropic_messages, gemini_generate_content 等)
- 模型别名映射
- Task binding
- Capability matrix
- 协议级诊断

### 2. Workspace Authority ⏳ 进行中
**当前状态**: 已有基础实现
**目标状态**: 
- activeWorkspaceRoot / folder sovereignty
- 权限梯度 (inspect, annotate, reorganize, generate, apply, destructive)
- operationLedger + checkpoint + trash
- remote workspace support

**待实施**:
- [ ] 完善权限决策引擎
- [ ] 实现 operation ledger
- [ ] 实现 checkpoint/trash 机制
- [ ] 完善 workspace authority 状态显示

### 3. File Preview ⏳ 进行中
**当前状态**: Tier B 转换已集成
**目标状态**: 
- Tier A: 富预览 (CodeMirror 6, react-pdf, PDF.js, Shiki)
- Tier B: 转换为 markdown/HTML (MarkItDown, Mammoth.js)
- Tier C: metadata + native editor fallback

**待实施**:
- [ ] 集成 CodeMirror 6 用于代码预览
- [ ] 完善 DOCX/PPTX/XLSX 预览
- [ ] 实现音频波形预览 (wavesurfer.js)
- [ ] 完善 tier 选择策略

### 4. Search ⏳ 进行中
**当前状态**: 基础搜索实现
**目标状态**: 
- SQLite FTS5 lexical search
- path/title/symbol recall
- metadata filters (trust, project, freshness)
- optional provider rerank
- optional local embeddings

**待实施**:
- [ ] 完善 SQLite FTS5 索引
- [ ] 实现搜索结果教学化包装
- [ ] 实现 citation 引用系统

### 5. Training ⏳ 进行中
**当前状态**: FSRS 调度 + 多种卡片类型
**目标状态**: 
- 单卡片状态机完善
- 证据闭环
- 项目 handoff
- 训练视图联动

**待实施**:
- [ ] 完善训练状态机
- [ ] 实现证据回流
- [ ] 优化训练视图 UX

### 6. Memory ✅ 已就绪
- Master plan memory
- Project memory
- Session memory
- Resource memory
- Review/training memory
- Provider diagnostics memory

### 7. Remote ✅ 已就绪
- VS Code Remote SSH/Tunnels/Dev Containers/WSL
- credentialMode = workspace_secret | ui_proxy
- workspace.fs / findFiles / FileSystemWatcher

### 8. Rendering ✅ 已就绪
- typed parts registry
- markdown, code, diff, table, citation, tool_call, reasoning, training_card, etc.

## 当前改进重点

### 1. 翻译修复 (高优先级) ✅ 已完成
**问题**: AppRecovered.tsx 中存在乱码的翻译字符串
**状态**: 已修复 - AppRecovered.tsx 已不存在，相关翻译已统一到 copy.ts

**修复内容**:
- 所有翻译已统一在 copy.ts 中管理
- 新增了 40+ 缺失的翻译键 (resources, analysis, plan governance, context 等)
- zh-CN 和 en-US 已完成完整翻译
- es-ES, fr-FR, de-DE, ja-JP, ko-KR, pt-BR 已完成英文翻译

### 2. i18n 系统完善 ✅ 已就绪
**当前状态**: 
- `copy.ts` 定义了 390+ 个 CopyKey
- 所有视图统一使用 copy.ts 导出
- 8 语言翻译完整

**目标状态**: 
- 所有翻译统一在 copy.ts 中管理 ✅
- AppRecovered.tsx 使用 copy.ts 导出 ✅ (文件已删除)

### 3. Workspace Authority UX
**当前状态**: 已有基础实现
**待完善**:
- WorkspaceAuthoritySummary 组件
- WorkspaceAuthorityFacts 组件
- 权限状态可视化

### 4. Training UX 优化
**当前状态**: FSRS + 多种卡片类型
**待完善**:
- 训练状态机完善
- 证据闭环 UX
- 项目 handoff 流程

### 5. Preview Tier 系统
**当前状态**: 基础转换实现
**待完善**:
- Tier 选择策略
- CodeMirror 6 集成
- 音频波形预览

## 技术债清理

### 高优先级
1. [x] 修复 AppRecovered.tsx 中的乱码翻译 ✅
2. [x] 统一 i18n 管理到 copy.ts ✅
3. [ ] 完善类型导出
4. [ ] 添加单元测试覆盖

## 实施优先级
1. ✅ i18n 系统完善 (已完成)
2. 完善 Workspace Authority
3. 优化 File Preview tier 系统
4. 完善 Search 教学化
5. 优化 Training UX
6. 补充文档

## 验证方法
- TypeScript 编译无错误
- 手动功能测试
- 端到端 smoke test
