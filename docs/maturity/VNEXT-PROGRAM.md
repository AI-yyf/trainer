# Trainer VNext — 工程审计与总控程序（冻结契约 v1）

**日期：** 2026-11-05
**基线提交：** `7a0584a`（maturity/p1-final-convergence-2026-10-20）
**CI 全绿实证：** run 41975161211 + 41980840468 + 42005148779（连续三轮 9/9 jobs 全绿，含 Windows Server）
**性质：** 共享契约冻结 + 分阶段执行程序。所有后续会话（A–J）以本文档为唯一契约来源；修改契约须总控批准并同步全体。

---

## 一、真实工程审计（2026-11-05 实测）

以下结论全部来自本机实测（server 3787 passed、extension 2290 tests、三个真实 GUI 门禁），不是计划性描述。

### 已验证可用（保留，不重写）

| 模块 | 实测证据 |
| --- | --- |
| `resources/canonical.py` + `canonical_store.py` | DOCX/PPTX/PDF/HTML/URL → front matter Markdown；页/slide/标题锚点；原文件+资产落盘；21 个单测 |
| `resources/service.py` 分阶段导入 | analyze/materialize/index 三阶段接口；index 复用已物化文档（mtime 断言）；GUI 状态栏 5 阶段可见 |
| `resources/versioning.py` | 不可变版本 + citation；旧版本在 tombstone 后保留 |
| `resources/search.py`（FTS5 + CJK） | 命中带 `page/slide/heading/line_start`；200 场景矩阵通过 |
| `llm/agent_loop.py` + `harness.py` | 工具循环、压缩（`should_compact/find_cut_point`）、只读校验（`tools_are_read_only`）、Token 估算（`estimate_tokens`/`ProviderUsage`） |
| `llm/tools.py` 只读优先 | `PROJECT_WRITE_TOOL_NAMES` 默认拒绝铸造；资料库写工具仅在资料库上下文/显式请求时可用 |
| `llm/skill_draft.py` | 生成 trigger/title/detail/prompt 教练技能草稿 |
| `memory/transfer_skills.py` | 跨项目迁移场景、`should_promote_transferable_skill`、状态记录 |
| `workspace/classifier.py` | 远程快照分类 + 发现决策（browse-only） |
| Webview 三目的地 | 安装版 VSIX 全量门禁通过（canonical/coach/i18n-zoom/E2E） |

### 本轮已修复的 P0（以提交 `a7a1941` 进入主干）

1. **远程路径隔离**：classifier 对 remote 身份跳过本地目录探测；canonical 写入点全部收敛到 `_canonical_writable_root`（真实本地根才写）。根因（Path.mkdir 栈追踪实证）：`import_workspace_file → index → canonical store` 在 Windows 将 `/mnt/x` 解释为 `D:/mnt/x` 并创建目录，污染同进程内的 classifier/RAP/sandbox 测试（6 个 Windows 失败）＋ Pyright 5 错误。
2. **恢复契约与新文案对齐**：webview-recovery 校验改为“克制单行阶段”契约（无步骤号、无工具胶囊堆叠、阶段线跟随最新运行工具、完成后移除）。
3. **Ruff**：7 处全部修复，CI Ruff 门禁恢复。

### 已确认缺口（按优先级）

| 缺口 | 证据 | 归属 |
| --- | --- | --- |
| ~~跨平台 CI 全红~~ | run 41975161211 九 job 全绿 | 已关闭 |
| 真实 Provider 长讲义 `truncated_or_empty` | handoff 记录 | G |
| 导入阶段基于 host 调用边界，非 sidecar 推送 | `resourceCommands.ts` 轮询阶段 | C/B |
| URL 抓取仅限公网（SSRF 防护） | `network_fetch.py` 私网拒绝 | B |
| 规范文档无删除/恢复保留策略 | 隐藏目录常驻 | B |
| OCR 缺失（扫描件明确标注，不伪造） | `canonical.py` 警告 | B（低优先） |
| 200% 下部分长标签省略号回退 | i18n-zoom 截图 | I |

---

## 二、产品边界（冻结）

1. 三个一级入口不变：对话（Coach）/ 学习（Learn）/ 资料（Library）。不新增第四个一级入口。
2. Agent 默认教学型、只读优先：`READ_ONLY_TOOL_NAMES` + `PROJECT_WRITE_TOOL_NAMES` 双重闸门保持；任何写操作须显式上下文（资料库工作区/宿主卡）+ 可恢复。
3. 不引入第二套聊天系统、独立资料库或独立 Token 管理。

---

## 三、知识底座：六类对象 → 现有实现映射（冻结契约 v1）

| 对象 | 现有载体（不新建平行系统） | 冻结规则 |
| --- | --- | --- |
| **Source** | `ResourceRecord`（id/kind/source/canonical_source/remote 身份）+ `resource_versions` 表 | 来源身份 = `(workspace_id, resource_id, content_hash)`；远程根仅登记路径，禁止本地物化（`_canonical_writable_root` 契约） |
| **Artifact** | `Trainer Library/.trainer-resources/markdown/<id>.md` + assets + front matter（`parser/parser_version/anchors`） | 原文件不可变；Markdown 由 `parser_version + content_hash` 确定重生成；产物不因插件卸载消失 |
| **Evidence** | `resource_citations`（citation_id/version_id/content_hash/location）+ 搜索命中 location（page/slide/heading/line） | 一切引用必须带 version + location；禁止无版本引用 |
| **Project** | `workspace/classifier.py` 发现决策 + `workspace_paths` 登记 + 远程 browse-only 契约 | 远程根永不适配为本地相对路径；Project 分析产物走 Artifact/Evidence，不建第二资料库 |
| **Skill** | 现有：`llm/skill_draft.py`（Tutor 草稿）、`memory/transfer_skills.py`（迁移状态） | 三分法定义（见 §五），数据模型沿用现有表 + `skill_kind` 字段扩展，不合并为一张含义模糊的表 |
| **Learning State** | `memory/`（weaknesses、FSRS 复习、mastery）+ `transfer_skills`（Learner Competency） | Skill 使用成功 ≠ 掌握；掌握必须来自练习验证证据 |

**派生表示分工（不互相冒充）：** 原件=完整性；Markdown=可读知识；FTS5/符号=定位；关系=邻接表；DB=状态；Skill=方法。

---

## 四、Token 纪律（扩展 harness.py，不新建系统）

已有原语（实测存在）：`estimate_tokens`、`ProviderUsage`、`tool_output_limit`、`truncate_tool_payload`、`should_compact`、`find_cut_point`、`resolved_context_window/reserve/keep_recent`。

P1 增量（在 harness 上加，不另起炉灶）：

1. 任务级预算：`extra` 增加 `task_token_budget`，agent loop 超支时升级压缩档位。
2. 检索复用：同 `(workspace_id, content_hash, query)` 的检索结果短 TTL 缓存。
3. 成本账本：`ProviderUsage` 已采集 → 落盘为按任务/按 workspace 的 JSONL 账本。
4. 分层读取顺序固定：FTS5 命中 → 章节/符号 → 全文 → 扩展检索；证据不足才加宽。

**验收基准（P2 起）**：同一组代表性任务，“全仓库注入 / 普通 RAG / 分层理解”三模式对比 Token 消耗与定位/证据质量，形成可重复基准脚本。

---

## 五、Skill 分类法（冻结定义）

| 类型 | 载体 | 可执行 | 安装≠掌握 |
| --- | --- | --- | --- |
| Tutor Skill | `skill_draft.py` 草稿 + 审核 | 调用教学行为 | 是 |
| Knowledge Skill | 引用 Artifact/Evidence 的知识包 | 默认只读 | 是 |
| Action Skill | 声明式工具/流程（未来） | 按权限 | 是 |
| Learner Competency | `transfer_skills.py` 状态 + 练习证据 | —（是评估结果） | — |

规则：外部/未审核 Skill 默认只读不可执行；`SKILL.md` 渐进加载（先 front matter，正文按需）；Skill 引用已有 Artifact，不打包项目。

---

## 六、阶段计划与当前状态

| 阶段 | 内容 | 完成门槛 | 状态 |
| --- | --- | --- | --- |
| **P0** 工程可靠性 | 远程隔离、恢复契约、Ruff、CI | Windows/macOS/Linux CI 全绿 | **完成**：run 41975161211 九个 job 全部通过（含首次 Windows Server 全绿） |
| **P1** 知识底座 | 六对象契约落库、哈希缓存、分层读取、成本账本 | 重启/更新/恢复后资料与引用仍正确 | **主体完成**：成本账本（`llm/cost_ledger.py`，agentic turn 记录 estimated tokens）、检索复用缓存（TTL 120s + index/delete 失效）、Source/Artifact/Evidence 契约已冻结 |
| **P2** GitHub 项目理解 | 仓库导入、源码索引、结构分析、增量更新、可追溯问答 | 真实项目持续追问 + 引用可验证 | **核心导入+索引+搜索已实现**：`app/project/importer.py`（clone→Source→symbol index）、`/project/import/github` + `/local` 路由、真实 psf/requests 验证通过；增量更新和项目导学待 P3 |
| **P3** 分析器与 Skill 生态 | Analysis Adapter 契约、SKILL.md 兼容、权限 | 外部分析可替换、Skill 跨任务复用 | 未开始 |
| **P4** 教学与体验深度 | 项目导学、练习验证、信息流、模板 | 完整真实学习旅程 | 主体已有，深度打磨中 |
| **P5** 发布治理 | 三平台 + Remote + 真实 Provider + 发布证据 | 同一提交同一安装包完整证据 | 门禁已部分自动化 |

---

## 七、会话 A–J 责任域与文件所有权（冲突规避）

| 会话 | 责任 | 主要文件所有权（独占写） |
| --- | --- | --- |
| A | 数据身份、Remote-SSH、存储正确性 | `workspace/classifier.py`、`runtime_path_recovery.py`、`api/routes/workspace.py` |
| B | Canonical Markdown、解析、版本 | `resources/canonical*.py`、`resources/versioning.py`、`ingest/service.py` |
| C | 搜索、证据、Token 账本 | `resources/search.py`、`llm/harness.py`、`resources/service.py`（检索部分） |
| D | GitHub 项目导入与分析 | 新 `project/` 模块（P2 立项后创建） |
| E | 分析插件适配 | 新 `analysis/` 模块（P3 立项后创建） |
| F | Skill 注册与权限 | `llm/skill_draft.py`、`memory/transfer_skills.py`、新 `skills/` 注册表 |
| G | Agent、Provider、会话生命周期 | `llm/agent_loop.py`、`llm/provider_service.py`、`api/runtime.py` |
| H | 教学、计划、练习、记忆 | `pedagogy/`、`memory/service.py`、`training/` |
| I | Webview 全部 UI | `extension/webview/src/**`、`shared/src/tokens.ts` |
| J | CI、安全、打包、回归 | `.github/workflows/`、`extension/scripts/verify-*`、`scripts/` |

**集成规则**：共享文件（`core/models.py`、`resources/service.py`、`useWorkbenchState.ts`）变更须总控评审后串行合入；每轮以真实门禁绿 + 真实 GUI 证据收口。

---

## 八、验收基准（可重复运行）

已存在的可重复门禁（本轮全部实测通过）：

```bash
cd server && python -m pytest tests/ -q -n 2        # 3787 passed
npm run test:extension                              # 2290 tests
npm run check                                       # TS + CSS 门禁
node scripts/verify-ui-geometry.mjs                 # 340/420/460 × 深/浅 × zh/en
npm run verify:canonical-gui                        # 文档导入/阅读/搜索 GUI
npm run verify:coach-gui                            # 单行状态 + 新会话首条
npm run verify:i18n-zoom                            # 200% × 8 语言
npm run test:vsix-e2e                               # 安装版 36 步
npm run verify:webview-recovery --prefix extension  # 恢复契约
npm run verify:credentials                          # 明文凭据扫描
```

P1–P3 追加基准（立项时定义输入/输出/阈值）：

- `bench:token`：三模式 Token 对比（全仓库 / RAG / 分层理解）
- `bench:incremental`：同一仓库二次分析成本 ≤ 首次 20%
- `bench:provenance`：关键回答引用可验证率 ≥ 95%

---

## 九、本轮已完成 vs 下一轮入口

**已完成（本轮，全部有实测证据）：** P0 三项修复（远程隔离/恢复契约/Ruff）、导入五阶段、200%×8 语言门禁、真实对话状态门禁、规范 Markdown 阅读/搜索/引用全链路。

**下一轮入口（按序）：**
1. P2 深化：项目概览 Artifact（架构图/模块依赖图）→ Evidence 表；项目问答 Agent 工具（read_project_symbol / list_project_modules）（D）。
2. P3 Skill 生态深化：SKILL.md 外部 Skill 导入 + 供应链安全审查 + cross-workspace Skill 激活 runtime API（F）。
3. P4：真实 Provider key 验证 + 教学体验打磨（需要用户提供 key）。
3. P2 立项：GitHub 仓库导入（clone → Source 登记 → 符号索引）设计稿（D）。
