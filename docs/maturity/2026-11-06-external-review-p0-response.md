# 外部深度评估回应 — P0 验真修复 + P0/P1 差距对照（2026-11-06）

**对象**：《Trainer 项目深度进度评估》（基于远端 `main` @ `7ee45f9`，2026-10-31）。
**回应基线**：本分支 `maturity/p1-final-convergence-2026-10-20` 已领先 `main` 数十个提交
（规范 Markdown 管线、项目理解、Skill 生态、P2/P3 深化均只在分支上）——评估的多条
"缺失"在分支上已完成；两处具体 P0 缺陷**验真为真**并已修复。

## 一、评估两条具体缺陷的验真与修复（先复现、后修复）

### 问题 B — 文件夹索引截断：验真为真，且比报告看到的更严重

| 截断点 | 位置 | 状态 |
| --- | --- | --- |
| 上传归一化截断 | `resources/service.py` `_normalize_source_items` 内 `len >= 100: break` —— **上传时 `source_items` 就被砍到 100** | ✅ 已修（对齐 `MAX_FOLDER_INGEST_ITEMS`） |
| 索引循环截断 | `_ingest_resource_record` 内 `enumerate(resource.source_items[:100])`（报告引用的原句） | ✅ 已修（全量处理 + 响亮上限 2000） |
| 元数据说谎 | `folder_item_count` 记全量数，实际只索引 100 | ✅ 已修（新增 `folder_item_indexed` 成功数 / `folder_item_failed` 明细 / `folder_item_truncated` 标志） |
| 单项失败炸全局 | 一个条目异常 → 整个文件夹索引失败；删除文件 → index 入口 400 | ✅ 已修（逐项失败隔离，失败明细入元数据；`allow_missing` 放行缺失项到失败路径） |

**新增强量续接**：重索引时按 `mtime_ns` 复用未变化条目的 chunk，只重新抽取新增/变更条目
（`folder_item_mtimes` 元数据）。评估验收要求"有真实进度、失败明细和增量续接"——三项齐。

测试：`server/tests/test_p0_ingest_paths.py`
- 130 文件夹完整索引（旧代码只见前 100）+ 第 125 项可搜 ✅
- 逐项失败隔离（ghost 文件 + 二进制文件不炸全局，失败明细记录）✅
- 重索引增量续接（改 1 个文件 → 全量仍可搜、修订内容可搜）✅

### 问题 A — 预览/索引通路分叉：DOCX/PPTX/PDF/EPUB 分支上已统一；XLSX 验真为真

| 格式 | 评估时 main | 本分支 |
| --- | --- | --- |
| PDF/EPUB | — | ✅ PyMuPDF/EPUB 专路 + 段落锚点（既有） |
| DOCX/PPTX/HTML | 评估怀疑走 UTF-8 回落 | ✅ 本分支 P1 已接 canonical 解析器（`_extract_canonical_text`），评估描述的是 main 的旧状态 |
| **XLSX** | 未查 | ✅ **验真为真并修复**：预览层有完整 MarkItDown+结构化解析，但索引层 `.xlsx`→UNKNOWN→严格 UTF-8 读二进制必炸；且 MarkItDown 的 xlsx 路径因缺 openpyxl 静默降级为**仅第一个 sheet** |

修复内容：
1. `_extract_spreadsheet_text`：xlsx/xlsm/ods 索引复用 `preview.get_structured_preview_markdown` —— **预览与索引同一条转换通路**（评估的核心要求）。
2. `_xlsx_all_sheets`：回退解析器从"仅首个 sheet"扩为**全部 sheet 枚举**（无新依赖），每 sheet 一个 `### {名}` 章节。
3. sheet 级 heading 锚点（char-offset，kind=table）进入 `paragraph_anchors` → 引用可定位到 sheet。

测试：xlsx 双 sheet（Scores/Attendance）索引后**两个 sheet 内容都可搜** ✅。

## 二、评估 P0/P1 优先级表 vs 本分支实况

| 评估要求 | 本分支状态 | 证据 |
| --- | --- | --- |
| P0 统一文档预览与索引通路 | ✅ 完成（XLSX 缺口今日补齐） | 本文件 §一 + `test_p0_ingest_paths.py` + 规范管线 21 测试 |
| P0 修复文件夹索引截断 | ✅ 完成（两处截断点 + 进度/明细/续接） | 本文件 §一 |
| P0 重新真实学习旅程验收 | ✅ 今日重跑 11 步全 PASS（真实 MiniMax 双模型，含重启/切工作区/切模型中断恢复、锚点引用验证、跨工作区隔离）；主观教学质量留人工 | `docs/maturity/p4-journey-2026-11-06/` + 本文件 §三 |
| P1 统一 Markdown 知识资产 | ✅ 分支已完成（原文件不可变保留 + front matter + 页/slide/标题/行锚点 + 重索引复用物化文档 + bench:provenance ≥95% + 搜索缓存） | closeout §4 逐项表 + P1 管线测试 |
| P1 完整 GitHub 项目理解 | 🟡 大部分完成：clone→Source→符号索引→FTS 代码定位→概览 Artifact（模块表/依赖图/mermaid 架构图/入口/热点）→Git SHA→Evidence→问答工具；**调用链/改动影响分析未做** | `test_project_import/overview.py` + bench:token/incremental |
| P1 真实 Skills 体系 | 🟡 注册表/权限/审核 gate/供应链扫描/SKILL.md 渐进加载/跨工作区持久化 ✅；**Agent 运行时按条件自动选技能 + 执行结果回流**未做 | `test_skill_api.py`（HTTP e2e 含重启持久化） |
| P1 真实 VS Code 全流程 | 🟡 安装版 36 步 E2E/恢复契约/重启会话恢复有；**Remote-SSH L2 真窗口验收未闭环**（评估属实） | closeout §5 风险 #4 |
| P2 大组件模块化 | ❌ 未开始（App.tsx 万行级属实） | — |
| 发布对齐 | ⏸ 分支未合 main、无新 Release（评估属实）；P5 待用户批准 | — |

## 三、真实学习旅程验收（今日重跑，真实模型）— PASS

环境：MiniMax 网关（`openai_chat_completions_compatible`），主模型 MiniMax-M3.1-Flash，
中断切换模型 MiniMax-M2.7；隔离 sidecar（独立数据目录）。**11 步全部 PASS**
（`docs/maturity/p4-journey-2026-11-06/*.json`，脚本 `scripts/run-real-teaching-journey.mjs`）：

| 步骤 | 结果 | 关键证据 |
| --- | --- | --- |
| 会话启动 / 资源上传 | ✅ 200 | 真实 queue_lock.py 入库 |
| Provider 探针（02b/08a） | ✅ ok=true ×2 | 双模型连通 |
| 理解轮（03） | ✅ | 3154 可见字符、`has_complete`、**引用真实资源锚点 `¶chunk:0@1`** 并引用真实代码 |
| 计划生成（04） | ✅ 200 | — |
| **sidecar 重启恢复（05）** | ✅ | `same_session=true`，对话完整还原 |
| 重启后续接轮（06） | ✅ | 基于重启前上下文继续（引用同一资源 + 前述边界改动），`has_complete` |
| **工作区切换（07）** | ✅ | 新工作区新会话，`cross_workspace_leak=false` |
| **模型切换（08）** | ✅ | M3.1-Flash → M2.7 热切换后正常出字 |
| 记忆摘要（09） | ✅ | `has_summary=true` |

这回应了评估 P0 第 3 条"重新进行真实学习旅程验收"的自动化部分：回复不是只判成功，
而是验了**引用真实性（锚点+代码）、重启/切工作区/切模型三种中断恢复、跨工作区隔离**。
教学质量的最终人工评价（准确性/难度/提示有效性的主观面）仍留待人工，如实标注。

## 四、下一步（按评估优先级剩余项）

1. Agent 运行时自动选择已激活 Skill（条件触发）+ 执行结果回流记忆（P1 Skills 剩余面）。
2. 调用链/改动影响分析（P1 项目理解剩余面）。
3. Remote-SSH L2 真窗口验收闭环（需要远端环境）。
4. App.tsx / ResourcesWorkbenchView / CoachSettingsView 模块化拆解（P2，保持行为不变逐块迁移）。
5. 分支合 main + 统一提交发布（v1.3.4 发布早于全部新能力；P5 待批准）。
