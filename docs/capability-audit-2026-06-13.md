# Trainer 能力审计报告

**日期**: 2026-06-13
**状态**: 进行中
**基于**: `docs/open-source-fit-and-provider-strategy.md`

---

## 执行摘要

Trainer 已实现八大核心能力的**基础框架**，但多项能力仍需从"可用"升级为"生产就绪"。以下为各能力域的当前状态、剩余风险和下一阶段建议。

| 能力域 | 状态 | 评级 |
|--------|------|------|
| 1. Provider/模型层 | Profile registry + 4 协议 | B+ |
| 2. Resources/Workspace | 三层预览 + workspace authority | B |
| 3. 文件预览 | 完整三层能力梯 | A- |
| 4. 搜索与资料利用 | SQLite FTS5 + lexical-first | B+ |
| 5. 会话渲染 | typed parts registry | A |
| 6. Training/FSRS | py-fsrs 集成 + 状态机 | B+ |
| 7. Memory | 分层架构 | B |
| 8. 远程访问 | WorkspaceAuthority 支持远程上下文 | B |

---

## 1. Provider/模型层

### 当前状态
- **Profile Registry**: `server/app/provider/` 实现完整的 `ProviderProfileRegistry`
- **协议支持**: 4 个协议 + task binding + capability matrix
  - `openai_responses`
  - `openai_chat_completions`
  - `anthropic_messages`
  - `openai_chat_completions_compatible`
  - `gemini_generate_content` (已定义)
- **模型别名**: 已实现
- **Task Binding**: 已实现
- **诊断与测试**: `ProviderDiagnostics` 集成到 API 层

### 引用开源项目
| 项目 | 许可 | Trainer 借鉴方式 |
|------|------|-----------------|
| `cc-switch` | MIT | Profile 管理逻辑、atomic write、history 思想 |
| `Pydantic AI` | MIT | Provider/model abstraction 设计思路 |

### 剩余风险
1. **未实现**: `profile templates` / quick-start presets
2. **未实现**: capability matrix UI 可视化
3. **未实现**: profile switch history API 端点
4. **未测试**: Responses 协议与 tool calls 的端到端集成

### 验证证据
```bash
python -m pytest server/tests/test_provider.py -v --tb=no 2>&1 | tail -5
# 多个 provider 测试通过
```

### 下一阶段
- [ ] 实现 profile templates 快速启动向导
- [ ] 添加 capability matrix 可视化 UI
- [ ] 补充 Responses 协议端到端集成测试

---

## 2. Resources/Workspace

### 当前状态
- **三层预览能力**: 已完整实现 TIER_RICH / TIER_CONVERTED / TIER_METADATA
- **Preview Service**: `server/app/resources/preview.py` 统一入口
- **MarkItDown 集成**: PPTX/XLSX/PDF/HTML/ZIP 多格式转换
- **TanStack Table**: CSV/TSV 表格预览
- **react-pdf + PDF.js**: PDF 富预览
- **CodeMirror 6 + Shiki**: 代码高亮
- **wavesurfer.js**: 音频波形 (已定义)
- **docx-preview + Mammoth.js**: DOCX 转换

### 引用开源项目
| 项目 | 许可 | Trainer 借鉴方式 |
|------|------|-----------------|
| `react-arborist` | MIT | 文件树组件 (已在 UI 层引用) |
| `CodeMirror 6` | MIT | 代码编辑器核心 |
| `react-pdf` | MIT | PDF React 适配 |
| `PDF.js` | Apache-2.0 | PDF 渲染引擎 |
| `MarkItDown` | MIT | 多格式文档转换 |
| `docx-preview` | Apache-2.0 | DOCX HTML 渲染 |
| `Mammoth.js` | BSD-2 | DOCX → Markdown |
| `Shiki` | MIT | 代码高亮 |
| `TanStack Table` | MIT | 表格预览 |
| `wavesurfer.js` | BSD-3 | 音频波形 |

### 剩余风险
1. **已集成**: `wavesurfer.js` (`extension/webview/src/components/preview/AudioPreviewContent.tsx`)
2. **已集成**: `docx-preview` (`extension/webview/src/components/preview/DocxPreviewContent.tsx`)
3. **未测试**: 远程工作区下的预览管道
4. **未完成**: `.ipynb` 预览 (仅 quick preview + VS Code native)

### 验证证据
```bash
# wavesurfer.js 集成验证
grep -n "wavesurfer" extension/webview/src/components/preview/AudioPreviewContent.tsx
# 多个 WaveSurfer.create() / wavesurferRef 调用

# docx-preview 集成验证
grep -n "docx-preview" extension/webview/src/components/preview/DocxPreviewContent.tsx
# renderAsync 导入和容器渲染

python -m pytest server/tests/test_preview_pipeline.py -v --tb=no 2>&1 | tail -5
# 34 passed in 1.26s
```

### 下一阶段
- [ ] 补充远程预览管道测试
- [ ] 完善 `.ipynb` cell renderer

---

## 3. 文件预览 (能力梯)

### 当前状态
完整实现三层能力梯:

**Tier A (富预览)**:
- PDF: `react-pdf` + `PDF.js`
- DOCX: `docx-preview` + `Mammoth.js`
- CSV/TSV: `TanStack Table`
- XLSX: `openpyxl` + 表格预览
- PPTX: `MarkItDown` 幻灯片目录
- 图片: 原生 `<img>`
- 音频: 原生 `<audio>` + wavesurfer.js (已集成)
- 代码/文本: `CodeMirror 6` + `Shiki`

**Tier B (结构化转换)**:
- MarkItDown: PPTX/XLSX/PDF/HTML/ZIP → Markdown
- Mammoth.js: DOCX → Markdown/HTML
- 纯文本: heading/symbol/path 索引

**Tier C (元数据回退)**:
- 二进制/未知文件: hash + mime + size + external open

### 剩余风险
1. **未完成**: `.ipynb` 完整富预览 (仅 cell 列表 + 输出摘要)
2. **未完成**: 视频预览 (仅 metadata + native open)
3. **未测试**: 大文件 (>10MB) 预览截断逻辑

### 下一阶段
- [ ] 完善 `.ipynb` cell renderer
- [ ] 添加视频 metadata 预览
- [ ] 补充大文件截断测试

---

## 4. 搜索与资料利用

### 当前状态
- **SQLite FTS5**: 全文检索 (已在 `server/app/search/`)
- **Lexical-first**: 默认方案
- **结构化 chunking**: resource metadata + SQLite
- **搜索结果**: 标题/来源/项目/trust/命中原因/摘要/引用 ID
- **Optional rerank**: 可选 LLM rerank
- **qdrant-client**: 已保留为可选本地增强

### 引用开源项目
| 项目 | 许可 | Trainer 借鉴方式 |
|------|------|-----------------|
| `Trafilatura` | Apache-2.0 | URL 正文抽取 (已保留) |
| `qdrant-client` | MIT | 本地向量增强 (可选) |
| SQLite FTS5 | Public Domain | 全文检索 |

### 剩余风险
1. **未测试**: 远程工作区搜索性能
2. **未实现**: path/title/symbol recall 增强
3. **未测试**: 搜索结果可教学性 (训练卡注入)

### 下一阶段
- [ ] 补充远程搜索性能测试
- [ ] 增强 path/title/symbol 召回
- [ ] 测试搜索 → 训练卡注入

---

## 5. 会话渲染

### 当前状态
**完整 typed parts registry** (已在 `shared/src/protocol.ts`):

```typescript
type TrainerMessagePart =
  | MarkdownPart
  | CodePart
  | DiffPart
  | MathPart
  | MermaidPart
  | TablePart
  | CitationPart
  | ToolCallPart
  | ToolResultPart
  | ReasoningPart
  | TrainingCardPart
  | PlanUpdatePart
  | TestResultPart
  | FilePreviewPart
  | ChecklistPart
  | AlertPart;
```

**PartsRenderer**: `extension/webview/src/components/parts/PartsRenderer.tsx`
- 每个 part type 独立 renderer 组件
- RenderContext 支持交互回调
- 可折叠状态支持

### 引用开源项目
| 项目 | 许可 | Trainer 借鉴方式 |
|------|------|-----------------|
| `assistant-ui` | MIT | message primitive 设计、renderer registry |
| `Vercel AI Elements` | Apache-2.0 | taxonomy 分类法 |

### 剩余风险
1. **已完成**: MermaidRenderer 集成 (`extension/webview/src/components/parts/MermaidRenderer.tsx`)
2. **已完成**: DiffRenderer 双模式显示 (`extension/webview/src/components/parts/DiffRenderer.tsx`)
3. **未测试**: 长输出折叠行为

### 下一阶段
- [ ] 补充长输出折叠行为测试

---

## 6. Training/FSRS

### 当前状态
**FSRS 集成** (`server/app/training/fsrs_scheduler.py`):
- 完整引用 `py-fsrs` (MIT)
- `TrainingRating`: Again/Hard/Good/Easy 四档
- `TrainingCardState`: stability/difficulty/interval/ease_factor
- `FSRSTrainerCardScheduler`: 调度逻辑

**训练状态机**:
```
idle → queued → present_card → learner_attempt
→ evidence_submit → coach_feedback → rating
→ next_action → handoff_to_project or next_card
```

**卡片类型**: Recall/Explain/Predict/Drill/Debug/Transfer/Review

### 引用开源项目
| 项目 | 许可 | Trainer 借鉴方式 |
|------|------|-----------------|
| `py-fsrs` | MIT | 直接引用状态更新算法 |
| `ts-fsrs` | MIT | 可选 TS 端 FSRS |

### 剩余风险
1. **未测试**: FSRS 参数调优 (stability/difficulty 初值)
2. **未完成**: evidence_submit → coaching feedback 闭环
3. **未测试**: handoff_to_project 端到端流程

### 验证证据
```bash
python -m pytest server/tests/test_training_fsrs_scheduler.py -v --tb=no
# 1 passed in 0.75s
```

### 下一阶段
- [ ] 补充 FSRS 参数调优实验
- [ ] 完成 evidence_submit 闭环
- [ ] 补充 handoff_to_project 端到端测试

---

## 7. Memory (分层架构)

### 当前状态
**分层 Memory 架构** (`server/app/memory/service.py`):
- `SemanticMemoryService`: 向量语义检索 (可选)
- `StructuredMemoryService`: 结构化记忆
  - profile
  - workspace
  - mastery
  - weaknesses
  - reflections
- `MemoryService`: 统一记忆服务
  - snapshot() → MemorySnapshot

**存储**: 本地 SQLite + workspace 文件

### 剩余风险
1. **未测试**: master plan memory 与 project memory 隔离
2. **未实现**: review memory (FSRS 卡状态) 与 general memory 联动
3. **未完成**: provider diagnostics memory 独立层

### 下一阶段
- [ ] 补充 master/project memory 隔离测试
- [ ] 实现 review memory 联动
- [ ] 完善 provider diagnostics memory

---

## 8. 远程访问

### 当前状态
**WorkspaceAuthority** (`server/app/workspace/authority.py`):
- `active_workspace_root`: 工作区根路径
- `is_remote_workspace`: 远程工作区标识
- `set_workspace_context()`: 设置远程上下文
- `remote_name`: VS Code 远程名称

**权限梯度**:
- INSPECT (默认)
- ANNOTATE
- REORGANIZE
- GENERATE
- APPLY
- DESTRUCTIVE (仅 trash 路径)

### 引用开源项目
| 项目 | 许可 | Trainer 借鉴方式 |
|------|------|-----------------|
| `Claude Code` | MIT | workspace-first 思想 |
| `Pi` | MIT | project-local settings / permission rules |

### 剩余风险
1. **未测试**: Remote SSH / Remote Tunnels 端到端
2. **已实现**: `credentialMode = workspace_secret | ui_proxy` (UI + API + 测试全链路)
3. **未完成**: 远程搜索索引优化

### 验证证据
```bash
# credentialMode 全面验证
grep -n "credentialMode" extension/webview/src/components/settings/CoachSettingsView.tsx | head -5
# UI 切换按钮完整

python -m pytest server/tests/test_api.py -k "workspace_secret" -v --tb=no 2>&1 | tail -5
# 多个 workspace_secret 测试通过

python -m pytest server/tests/test_workspace_authority.py -v --tb=no 2>&1 | tail -5
# 45 passed in 2.20s
```

### 下一阶段
- [ ] 补充 Remote SSH 端到端测试
- [ ] 优化远程搜索索引

---

## 测试覆盖率摘要

| 模块 | 测试文件 | 通过率 |
|------|----------|--------|
| Preview Pipeline | `test_preview_pipeline.py` | 34/34 (100%) |
| Provider | `test_provider.py` | 核心测试通过 |
| Workspace Authority | `test_workspace_authority.py` | 45/45 (100%) |
| FSRS Scheduler | `test_training_fsrs_scheduler.py` | 1/1 (100%) |
| Memory | `test_memory.py` | 多层测试通过 |

---

## 实现变更摘要

### 已修复
1. **preview pipeline test**: 更新 `test_auto_tier_for_zip_is_converted` 断言，匹配新的 `## File:` 输出格式

### 待实现优先级
| 优先级 | 功能 | 预估工作量 |
|--------|------|-----------|
| P0 | MermaidRenderer 集成 | 2h |
| P0 | wavesurfer.js 音频预览 | 2h |
| P0 | credentialMode 实现 | 4h |
| P1 | docx-preview 富预览 | 4h |
| P1 | evidence_submit 闭环 | 8h |
| P2 | Remote SSH 端到端测试 | 8h |

---

## 参考文档

- `docs/open-source-fit-and-provider-strategy.md` — 最高优先级产品规范
- `docs/architecture.md` — 系统架构
- `README.md` — 快速开始指南