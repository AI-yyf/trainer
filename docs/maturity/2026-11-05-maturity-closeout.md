# Trainer 彻底成熟化 — 本轮收口报告

**日期：** 2026-11-05  
**分支：** `maturity/p1-final-convergence-2026-10-20`  
**验证载体：** `extension/trainer-extension-1.3.4-darwin-arm64.vsix`（真实安装包，隔离 user-data / extensions 目录）

---

## 0. 结论

资料库的「Word / PowerPoint / PDF / HTML / URL → 带 YAML front matter 的 Markdown 规范文档」链路已端到端打通；阅读器默认渲染 Markdown，原始文件保留；搜索命中能定位到页 / slide / 标题；视觉效果改为完全由 VS Code 主题变量驱动（产品源码中已无硬编码颜色），主视觉为石墨中性，蓝色不再作为按钮/图标/选中条底色。

真实证据：

- 服务器测试：**3787 passed / 0 failed**
- 扩展测试：**2290 tests / 2289 passed / 0 failed / 1 skipped**
- 安装版 VSIX E2E：`output/playwright/sidebar-audit/vsix-e2e-report.json` → `ok: true`（36 步，含 sidecar 重启、Provider、训练/复习、资源详情/沙盒预览、主题、跨工作区恢复）
- 真实对话状态 GUI（隔离 Profile + 安装版 VSIX）：`output/coach-gui/2026-11-04T17-49-13-689Z/report.json` → `ok: true`
  - 发送后 350ms 实测：用户消息可见、状态节点恰好 1 个（"正在思考"）、skeleton 0、步骤号 0
  - 新会话立即发送：首条消息可见、状态 1 行、无 skeleton
- 真实 GUI 文档旅程（隔离 Profile + 安装版 VSIX）：`output/canonical-gui/2026-11-04T17-41-51-216Z/report.json` → `ok: true`
  - 导入阶段实测（状态栏）：`identify → parse → markdown → assets → index` 五个真实阶段全部可见
- 200% 缩放 × 8 语言门禁（安装版 VSIX）：`output/i18n-zoom/2026-11-04T17-39-59-441Z/report.json` → `ok: true`
  - 8 张窗口截图；三种目的地在每个语言下 `scrollWidth == clientWidth`；导航标签单行（无按字换行）
  - `01-resources-list-dark.png` / `02-docx-reader-dark.png` / `03-pptx-reader-dark.png` / `04-pdf-reader-dark.png` / `05-search-dark.png` / `06-search-hit-open-dark.png` / `07-resources-list-light.png`；对话状态 `output/coach-gui/2026-11-04T17-49-13-689Z/01-sending-status.png` / `03-new-session-first-send.png`

---

## 1. 代码改动

### 1.1 规范 Markdown 摄入（新增）

| 文件 | 行为 |
| --- | --- |
| `server/app/resources/canonical.py`（新增） | DOCX / PPTX / PDF / HTML / Markdown / 文本 / 代码 / 图片 → 规范 Markdown；YAML front matter（`resource_id/source_type/original_filename/original_mime/original_size/content_hash/version_id/imported_at/source_url/parser/parser_version/page_count/slide_count/warnings/anchors`）；DOCX 标题/列表/表格/图片/脚注/超链接；PPTX 按 slide 分节 + 演讲者备注 + 隐藏页标记 + 表格/图片；PDF 保留 `<!-- page: N -->` 页锚点；HTML 去脚本/样式/导航；图片不伪造 OCR 文本；旧版 `.doc/.ppt` 给出可执行的失败文案 |
| `server/app/resources/canonical_store.py`（新增） | `Trainer Library/.trainer-resources/originals/<id>/<原文件名>`、`markdown/<id>.md`、`markdown/assets/<id>/…`；原文件字节不变；隐藏目录不进入资料库文件夹树 |
| `server/app/resources/service.py` | 索引时优先生成/读取规范文档；按 content_hash 去重；返回 `canonical_markdown_path/canonical_original_path/parser/parser_version/page_count/slide_count`；搜索索引与 Agent 上下文使用 Markdown；命中定位 `page/slide/heading/line_start`；`read_canonical_text()` 供重启后的 Agent 读取 |
| `server/app/resources/search.py` | `document_metadata()`，供搜索命中解析锚点 |
| `server/app/ingest/service.py` | DOCX/PPTX/HTML 走规范解析；URL 抓取优先生成结构化 Markdown；修复 `<style>/<script>` 泄漏到正文的正则错误 |
| `server/app/core/models.py` / `resources/models.py` | 资源类型新增 `docx/pptx/html`；资源模型新增规范文档字段 |
| `server/app/llm/tools.py` | `read_resource_excerpt` 在冷启动（注册表为空）时回退到持久化 Markdown / 持久搜索索引与仓库记录 |
| `server/app/resources/service.py` + `api/routes/resources.py` | 导入分阶段接口：`/resource/canonicalize/analyze`（识别类型 + 解析，返回页/slide/图片/表格计数并缓存解析结果）与 `/resource/canonicalize/materialize`（写规范 Markdown/原文件/资产）；`/resource/index` 复用已物化文档，不重复解析或重写 |
| `extension/src/commands/resourceCommands.ts` | 导入状态栏按真实工作推进：识别类型 → 解析文档结构 → 生成 Markdown → 已抽取 N 张图片/M 个表格 → 建立索引 → 刷新资料库；每阶段最小可读时长 450ms |

### 1.2 资料库 UI / 阅读器

| 文件 | 行为 |
| --- | --- |
| `extension/src/commands/resourceCommands.ts` | 打开资源改为「点击 → 规范 Markdown（VS Code 文本编辑器）」；搜索命中按 `line_start` 定位；新增「打开原始文件」；预览命令在无显式路径时读取规范 Markdown（含图片 URI 重写），沙盒内文件仍走沙盒预览；导入/索引用一个真实进度阶段 |
| `shared/src/resourceOpen.ts` | 读取候选优先 `canonicalMarkdownPath`；原始文件候选 `canonicalOriginalPath`；URL 行为不变 |
| `extension/webview/src/components/resources/ResourcesWorkbenchView.tsx` | 阅读器默认显示 Markdown（打开即预览）；整块内容收进一个带边框的卡片；文件管理/整理动作在预览时仍可用；新增「打开原始文件」；文件夹/文件图标改为主题色 mask |
| `extension/src/core/workbenchData.ts`、`types.ts`、`webview/src/lib/types.ts`、`App.tsx` | 新增 `resourceDocument`（阅读器文档，跨快照刷新保留）与 `liveResourceFocus`（显式资料焦点，不被“恢复计划的残留清理”误删） |

### 1.3 视觉：完全跟随 VS Code 主题

- 产品源码（`extension/webview/src`、`extension/src`、`shared/src` 的 TS/TSX/CSS）中**已无硬编码颜色**（十六进制/`rgb()`）。
- `--accent` 由主题前景色 + 主题图表暖色 `color-mix` 派生；`--focus-ring` 使用 `--vscode-focusBorder`；选中行使用主题中性 `color-mix`，不再使用编辑器蓝色选中条。
- 主按钮（`button--primary/button--accent`、`action-button--accent`）改为 VS Code 中性 secondary button 样式；不再有蓝色/米色实心底。
- 文件夹与文件类型图标统一改为 `currentColor` + CSS mask，继承 `--vscode-icon-foreground`；`shared/src/tokens.ts` 只保留几何/字体，不再提供颜色表。
- 主导航补齐单行网格契约（此前无样式）：200% 缩放 / ~170 CSS px 时标签使用省略号而非按字换行，完整名称保留在 `aria-label`/`title`。
- `theme.ts` 只同步 light/dark 与 `color-scheme`，不再注入颜色；浏览器预览回退使用 CSS 系统色（`Canvas/CanvasText/GrayText/Highlight`）。

### 1.4 对话/Agent 可靠性

- 工具成功后的 grounded completion 不再被通用 reanchor 覆盖（`grounded_completion`，含测试）。
- 会话激活 fence（`sessionActivationFence.ts`）与历史测试保留；本次未改坏。
- 工具自动铸造保持克制：资料库写工具仅在资料库工作区或显式请求时可用（`agent_tool_context.py`），其余轮次保持只读。

---

## 2. 测试与门禁

| 门禁 | 命令 | 结果 |
| --- | --- | --- |
| Server pytest | `cd server && .venv/bin/python -m pytest tests/ -q -n 2` | **3787 passed / 0 failed**（28 subtests passed） |
| Extension node:test | `node --test --test-reporter=spec extension/tests/*.test.js` | **2290 tests / 2289 passed / 0 failed / 1 skipped** |
| TypeScript | `npm run check` | PASS（webview + extension + CSS sections） |
| Build | `npm run build` | PASS |
| 打包 | `npm run package:vsix` | PASS（136 MB，VSIX 内含最新 bundled sidecar） |
| 安装版 E2E | `npm run test:vsix-e2e` | **PASS**（36 步，`ok: true`） |
| 真实文档 GUI | `npm run verify:canonical-gui` | **PASS**（8 步，`ok: true`） |
| 真实对话 GUI | `npm run verify:coach-gui` | **PASS**（5 步，`ok: true`；发送中/回复/新会话首条） |
| 窄宽度几何 | `node scripts/verify-ui-geometry.mjs` | **PASS**（340/420/460 × 深/浅 × zh/en） |
| 200% × 8 语言 | `npm run verify:i18n-zoom` | **PASS**（zoomLevel=4；8 张截图；无横向溢出；导航单行） |

新增/更新的定向测试：

- `server/tests/test_canonical_markdown.py`（12）：DOCX/PPTX/PDF/HTML/图片/旧格式/扫描 PDF/摘要纯文本/front matter 往返/存储布局。
- `server/tests/test_canonical_resource_pipeline.py`（7）：真实 HTTP API 的 DOCX→Markdown→搜索/引用、PPTX slide 锚点、PDF 页码、旧 `.doc` 失败、content_hash 去重、重索引版本、冷注册表 Agent 摘录。
- `server/tests/test_ingest.py`：新增 HTML 噪声/URL Markdown 结构回归。
- `extension/tests/resourceOpenPreference.test.js`（4）：读取/原始文件候选行为。
- `extension/tests/workbenchData.test.js`：live 资源预览在恢复计划清理中保留。
- 更新源码守卫：资源打开/预览、主题桥、无硬编码颜色、阅读器文档绑定。

---

## 3. 真实 GUI 证据（隔离 Profile）

**脚本：** `npm run verify:canonical-gui`（新增）
**方式：** 安装 `trainer-extension-1.3.4-darwin-arm64.vsix` 到临时 `--user-data-dir/--extensions-dir`；通过扩展自身命令导入真实 DOCX/PPTX/PDF；Playwright Electron 驱动真实 VS Code 窗口。

证据目录：`output/canonical-gui/2026-11-04T17-41-51-216Z/`

| 步骤 | 结果 |
| --- | --- |
| 导入 DOCX / PPTX / PDF（扩展命令） | PASS（"Imported 3 resource(s) and indexed 3."） |
| 资料库列表 | PASS（`01-resources-list-dark.png`） |
| DOCX 阅读器（Markdown 渲染、表格、脚注、无 front matter） | PASS（`02-docx-reader-dark.png`） |
| PPTX 阅读器（`Slide 1 — Consensus`、演讲者备注） | PASS（`03-pptx-reader-dark.png`） |
| PDF 阅读器（两页正文） | PASS（`04-pdf-reader-dark.png`） |
| 资料库搜索 | PASS（`05-search-dark.png`） |
| 命中打开 Markdown（按引用行） | PASS（`06-search-hit-open-dark.png`） |
| 浅色主题资料库 | PASS（`07-resources-list-light.png`） |

同时复制的磁盘产物：`output/canonical-gui/2026-11-04T17-41-51-216Z/trainer-library/`（规范 Markdown + 原文件 + 图片资产）。

服务器/URL 实测（真实 sidecar 进程，非 TestClient）：

- `POST /resource/upload` + `POST /resource/index`（DOCX/PDF/URL）→ `parse_status=parsed`、`index_status=indexed`、`parser=docx-v1/pdf-v1/html-v1`
- 搜索命中：DOCX → `heading=Quorum Ack`；PDF → `page=2`；URL → `source_url=https://example.com/`
- 生成文件：`Trainer Library/.trainer-resources/markdown/<id>.md` + `originals/<id>/<原名>` + `assets/<id>/docx-image-001.png`

---

## 4. 逐项验收表

| # | 要求 | 结论 | 证据 |
| --- | --- | --- | --- |
| 1.1 | Word `.docx` 解析（标题/段落/列表/表格/图片/脚注/超链接） | PASS | 单测 + 真实 GUI DOCX 阅读器截图 |
| 1.2 | PowerPoint `.pptx`（按 slide、备注、表格、图片、隐藏页） | PASS | 单测 + 真实 GUI PPTX 阅读器截图 |
| 1.3 | PDF 文本层 + 页锚点 | PASS | 单测 + 真实 sidecar 搜索 `page=2` |
| 1.4 | HTML / URL → Markdown 快照 + 抓取时间 | PASS | 真实 URL 抓取（example.com），front matter `source_url` |
| 1.5 | Markdown / 纯文本 / 代码 / 图片 | PASS | 单测（图片不伪造 OCR） |
| 1.6 | 旧 `.doc/.ppt` 明确失败、不假装成功 | PASS | 单测 + 管线测试 |
| 1.7 | 扫描 PDF 无 OCR 明确说明 | PASS | 单测抛错文案 |
| 2.1 | 每条资料一个稳定 Markdown 规范文档 + YAML front matter | PASS | 磁盘产物 + front matter 往返测试 |
| 2.2 | 原文件保留、不可变 | PASS | `originals/<id>/<原名>` + 字节比对测试 |
| 2.3 | 搜索/阅读/引用/建卡/Agent 上下文默认用 Markdown | PASS | 搜索命中 markdown_path、Agent 摘录、阅读器截图 |
| 2.4 | 引用可定位到页 / slide / 标题 / 行 | PASS | 搜索 location `page/slide/heading/line_start`；命中按行打开 |
| 2.5 | content_hash 去重 | PASS | 管线测试（同字节不同路径 → duplicate） |
| 2.6 | 重新解析 / 版本历史 | PASS | 重索引测试（新 version_id + 旧版本保留） |
| 2.7 | 导入可见进度 | PASS | 真实 GUI 状态栏依次出现：识别资料类型 → 解析文档结构 → 生成 Markdown → 已生成 Markdown/已抽取 N 张图片、M 个表格 → 建立索引 → 刷新资料库；对应服务端 analyze/materialize/index 三个阶段测试通过（含“索引复用已物化文档、不重写”断言） |
| 3.1 | 资料库：导入 / 检索 / 整理 / 删除恢复 / 刷新索引 / 建卡 | PASS | server 资源套件 + 安装版 E2E + Agent 工具 |
| 3.2 | 破坏性操作可恢复（回收站） | PASS | `test_resource_delete_api.py` + 安装版 E2E 恢复步骤 |
| 4.1 | 发消息立即显示、只一行当前阶段、无步骤号/胶囊/思考图标/双 loading | PASS | 安装版 VSIX + fixture Provider 真实 GUI：350ms 时用户消息可见、状态节点=1、skeleton=0、步骤号=0（`output/coach-gui/2026-11-04T17-49-13-689Z/01-sending-status.png`） |
| 4.2 | 成功工具结果不被 generic reanchor 覆盖 | PASS | `grounded_completion` + `test_reply_relevance_guard.py` |
| 4.3 | 新会话立即发送不丢第一条消息 | PASS | 真实 GUI：新对话后立即发送，首条消息可见 + 1 行状态 + 最终回复（`03-new-session-first-send.png` / `04-new-session-reply.png`） |
| 5.1 | 整体不要太蓝，蓝色只做少量信息提示 | PASS | 侧栏像素统计：饱和色像素 0.000%（PPTX 截图 0.067%，蓝色占比 0%）；主按钮/图标/选中条均为主题中性 |
| 5.2 | 与 VS Code 风格绝对通用 | PASS | 产品源码零硬编码颜色；全部 `--vscode-*` / CSS 系统色；图标 `currentColor` mask |
| 5.3 | 一个框框住（阅读器布局） | PASS | `02-docx-reader-dark.png`（单卡片 + 分隔线） |
| 6.1 | 真实 VSIX + 隔离 Profile 验证 | PASS | E2E `ok: true` + 文档 GUI `ok: true` |
| 6.2 | 8 语言 / 窄宽度 / 深色浅色 / 200% 缩放 | PASS | 8 语言键完整；`verify-ui-geometry` 340/420/460 × 深/浅 × zh/en 全量 PASS；真实浅色截图 PASS；200% 缩放 × 8 语言真实 VSIX 截图 + 无溢出/导航单行断言 PASS |

---

## 5. 已知风险与未完成

1. **真实 Provider key**：本机无真实 key；对话状态/新会话使用**本地延迟 fixture Provider**（真实 VS Code + 真实 sidecar，仅模型端点替换）验证。长讲义截断、网关误标等仍需真实 key 复核。
2. **OCR**：扫描件按设计明确标注「未做 OCR」，不伪造文本。
3. **URL 抓取**：需要 `trainer.research.networkEnabled`（默认 true）且目标为公网地址；localhost/私网被 SSRF 防护拒绝。
4. **macOS 原生窗口截图**：现有 E2E 的原生截图仅 Windows 实现，本机使用 Playwright Electron 截图替代。
5. **长讲义截断**：Provider `truncated_or_empty` 的 max_tokens / 推理块问题需要真实 key 复核。
6. **删除资源后的规范文档**：原文件与 Markdown 保留在隐藏目录，引用靠版本库判定失效；未实现「物理清理规范文档」的保留策略（当前设计偏向可恢复）。
7. **200% 极窄侧栏**：~170 CSS px 时主导航与“添加资料”使用省略号/图标回退（完整名称在 aria-label/title）；这是有意的渐进披露，不伪装成完整标签。

---

## 6. 下一轮建议（仅阻塞成熟的项）

1. 用真实 Provider key 重跑：长讲义、空响应、截断、工具成功 reanchor、新会话首条消息。
2. 把「规范文档 + 原文件」纳入删除/恢复的显式保留策略（清理或墓碑），并补测试。
3. 将导入阶段从 host 调用边界升级为 sidecar 推送事件（当前每个阶段都可见，但阶段切换由 host 发起）。
