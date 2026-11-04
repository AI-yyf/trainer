# Trainer 彻底成熟化：交接目标提示词（ZCode）

> 直接把下面全文作为新会话的目标提示词。  
> 仓库：`/Users/Apple/Desktop/trainer`  
> 先读 `AGENTS.md`，再读本文件。不要假设本文中的“当前状态”仍然成立，先自己验证。

---

## 0. 你的角色

你是 Trainer 的长期产品工程师、交互设计师和可靠性负责人。  
你的任务不是“再加一些功能”，而是把 Trainer 做成一个**成熟、克制、可信、可长期使用**的 AI 教练产品：

- 设计上：渐进披露，一次只显示当前阶段真正需要的信息。
- 功能上：资料库、学习、训练、对话、Agent 工具形成真实闭环。
- 体验上：所有状态真实、及时、可恢复；不伪造成功，不堆叠徽章/胶囊/步骤号。
- 工程上：每个结论都有代码、测试和真实 VS Code 证据。

本目标完成前，不要用“UI 看起来可以”代替真实旅程验证。

---

## 1. 产品原则（不可违背）

1. **成熟、克制、渐进披露**  
   每个界面只保留当前阶段必要的信息。默认隐藏高级事实，但随时可展开。  
   禁止：步骤号、工具胶囊堆叠、重复标题、重复主按钮、无意义图标、双 loading、假 skeleton。

2. **真实状态**  
   成功必须来自真实 sidecar/provider/tool 结果；失败必须明确说明失败在哪一层。  
   禁止：mock 当真实证据、伪造 provider 成功、把未验证说成已验证。

3. **对话信息流即时反馈**  
   用户发出消息后立即出现用户消息和当前状态；只显示一行当前阶段（如“正在检索资料/下载资料/整理资料/生成训练卡”）。  
   不要给“正在思考”加图标；不要在同一位置同时显示 skeleton 和状态行。

4. **资料库是唯一可信资料源**  
   任何输入资料都必须进入资料库，并在资料库中生成可检索、可引用、可被 Agent 阅读的 **Markdown 规范文档**。原始文件保留为不可变来源，但搜索、阅读、引用、建卡、Agent 上下文默认使用 Markdown 版本。

5. **Agent 有完整资料库权限，但破坏性操作必须可恢复**  
   导入、检索、下载、整理、删除、恢复、刷新索引、建卡都必须可用。删除进入回收站；恢复必须真实；刷新索引必须可见进度。

6. **不破坏既有基础**  
   保留 Design Tokens、8 语言、键盘优先、现有路由和真实数据契约。  
   禁止 `as any`、`@ts-ignore`、硬编码颜色、静默吞错。

7. **整体不要太蓝：暖中性色为基底，蓝色只做极少量信息提示**  
   Trainer 的主视觉不应让蓝色成为大面积底色或默认强调色。  
   - 品牌 accent 使用暖中性色（现有 token 方向：dark `#9d907a`、light `#7b6f5d`）；不要优先继承 VS Code 的蓝色 `button-background` / `textLink-foreground` 作为全局 accent。  
   - 选中行、hover、目录图标、进度环、主按钮、焦点态都用暖中性/石墨色系；避免大面积蓝色选中条、蓝色文件夹图标、蓝色渐变 hero。  
   - 蓝色最多保留为极少量的“可点击链接/信息”语义色，并且要和暖中性基底协调；不要全屏蓝。  
   - 保留 success / warning / danger 的语义色；深浅色、高对比、8 语言下都要有足够对比度。  
   - 验收：真实截图里，首屏、资料库、学习、对话的主色相应以暖中性/石墨为主；蓝色只作为局部、低频提示出现。  
   - 相关位置：`shared/src/tokens.ts`、`extension/webview/src/styles/sections/trainer-design-tokens-base-styles.css`、`resources-workbench-w1-collapsesection-collections-row.css`、`extension/webview/src/components/resources/resourceIconAssets.ts`。

---

## 2. 最高优先级：资料库摄入与 Markdown 消化

这是本轮新增的核心要求，必须端到端完成，不能只做“上传成功”。

### 2.1 支持的输入

至少支持：

- Word：`.docx`（`.doc` 若不支持，必须明确提示“不支持旧格式，请另存为 .docx”，不能假装成功）
- PowerPoint：`.pptx`（`.ppt` 同理）
- PDF：`.pdf`（文本层优先；扫描件如无 OCR，明确标记“未做 OCR”）
- HTML / URL：网页正文抽取后生成 Markdown 快照
- Markdown / 纯文本 / 代码文件
- 图片：可作为资源保存；如无 OCR，不要伪造文字内容

### 2.2 统一产物

每一条资料必须有一个稳定的 **Markdown 规范文档**，例如：

```text
resources/
  originals/<resource_id>/<original_filename>
  markdown/<resource_id>.md
```

Markdown 文件必须带 YAML front matter，至少包含：

```yaml
---
resource_id: res_...
source_type: docx | pptx | pdf | html | markdown | text | code | image
original_filename: ...
original_mime: ...
original_size: ...
content_hash: sha256:...
version_id: ...
imported_at: ...
source_url: ...            # URL/HTML 时必填
parser: docx-v1 | pptx-v1 | pdf-v1 | html-v1
parser_version: ...
page_count: ...            # PDF/Word 可选
slide_count: ...           # PPTX 必填
warnings: []               # 解析降级、缺失图片、未 OCR 等
---
```

正文要求：

- **Word**：保留标题层级、段落、列表、表格、图片引用、脚注/尾注（能解析则解析）。图片抽出到资源资产目录，并在 Markdown 中用相对路径引用。不要把所有内容压成一段纯文本。
- **PPTX**：按 slide 分节，每节包含 `## Slide N — 标题`、正文、表格、图片、演讲者备注（speaker notes）。隐藏页要标记。不要把整份 PPT 只抽成标题列表。
- **PDF**：保留页码锚点，例如 `<!-- page: 3 -->`；引用能定位到页。
- **HTML/URL**：去脚本/样式/导航噪声，保留正文、标题、列表、表格、链接；记录抓取时间。
- **所有来源**：保留原文顺序；解析失败要产生可读的 failure，而不是空文档。

### 2.3 引用与检索

- 搜索命中必须能回到 Markdown 的具体位置（标题/页码/slide/段落锚点）。
- 阅读器默认渲染 Markdown；提供“打开原始文件”动作。
- Agent 引用资料时必须带 `resource_id`、`version_id`、`content_hash`、`location`（page/slide/section）。
- 原文被删除或替换时，引用要标记为失效，直到同 hash 重新索引。
- 相同内容按 `content_hash` 去重；重复导入应返回已有资源或明确合并策略。
- 解析器版本升级后，必须能重新解析并生成新版本，不丢历史。

### 2.4 导入体验

导入流程必须可见：

1. 选择/拖入文件
2. 类型识别
3. 解析
4. 生成 Markdown
5. 抽取图片/表格
6. 建立索引
7. 完成，可在资料库打开

每一步都有真实状态；失败时说明是哪一步、为什么、下一步怎么办。不要用一个永远转圈的“处理中”掩盖失败。

### 2.5 Agent 工具

Agent 必须能：

- `import_resource_file` / `import_resource_url`
- `list_resources`
- `search_resources`
- `read_resource_excerpt`
- `organize_resources`
- `delete_resource`（进回收站）
- `restore_resource`
- `refresh_resource_index`
- `generate_training_card`

工具结果必须是结构化、可审计的；成功的结果不能被通用“我回到你刚才问的……”文案覆盖。

---

## 3. 必须完成的产品主线

### A. 资料库 / Resources

- 像 VS Code Explorer：文件夹/文件层级清楚，图标成熟，文件行不要有多余左侧空白。
- 单击文件直接在 VS Code 打开；Space 才在 Reader 预览；打开时回到文件顶部。
- 搜索、筛选、排序、来源、状态、回收站、恢复、刷新索引都要真实可用。
- 资料库空态、加载态、失败态都要克制且真实。
- Word/PPTX 导入后，资料库中必须出现对应的 Markdown 资源，并能阅读/搜索/引用。

### B. 学习 / Learning

- 顶部“今日学习”只显示当前阶段真正需要的信息：今日进度、待复习、待推进。
- 不要重复 header，不要第二个主按钮。
- 计划、阶段、当前任务、证据、复习形成闭环；FSRS 复习真实调度。
- 证据必须区分 self-reported 与 host-trusted；不要伪造 verified。

### C. 训练 / Training

- 单卡专注练习，不堆叠多面板。
- 提交、验证、证据、下一张卡、复习队列形成闭环。
- 远程验证失败/未知/超时都要有诚实状态和恢复路径。
- 训练卡生成失败时，明确是 provider、解析还是治理失败。

### D. Coach 对话与 Agent

- 发消息后立即显示用户消息和一行当前阶段。
- 工具开始/结束只改变这一行；完成后工具细节进入 work-trail 折叠。
- 成功的 tool result 不得被 generic reanchor 替换。
- Provider 错误、截断、空响应、语言损坏都要有可见、可恢复、8 语言的说明。
- 新会话 + 立即发送不能丢第一条消息；会话切换/恢复不能覆盖更新的会话。
- 多窗口、关闭重开、sidecar 重启后要能恢复真实会话。

### E. 首次使用与设置

- 首次进入要清楚：当前工作区、Provider 状态、下一步动作。
- Provider 配置、测试、模型选择、密钥保存要真实；失败要可诊断。
- 设置页只显示当前需要的层级，高级项渐进披露。
- 8 语言完整；RTL、窄宽度、200% 缩放不溢出。

---

## 4. 实施顺序

### Phase 0：基线

- 读 `AGENTS.md`、`docs/maturity/2026-10-28-deep-audit.md` 和本文件。
- 检查当前分支、未提交改动、测试基线。
- 不要 reset 或覆盖用户未提交的工作。

### Phase 1：资料库 Markdown 摄入

- 设计 Resource/Markdown 版本模型和迁移。
- 实现 DOCX/PPTX/PDF/HTML/Markdown/代码解析。
- 原文件 + Markdown + 资产 + front matter + 引用锚点。
- 导入进度、失败、去重、重解析、索引。
- 单元测试 + 真实文件样例 + 真实 GUI 导入。

### Phase 2：Resources UI

- Explorer 树、文件打开、Reader、搜索、回收站、整理、刷新。
- Word/PPTX 资源在 UI 中可读、可搜、可引用。
- 空态/加载/失败/窄宽度/8 语言。

### Phase 3：学习与训练闭环

- 今日学习、计划阶段、训练卡、FSRS、证据、复习。
- 真实提交与验证；未知/失败状态。

### Phase 4：Coach/Agent 可靠性

- 即时状态、单行阶段、work-trail。
- Agent 资料库权限。
- Provider 截断/错误/重连/会话竞态。
- 新会话立即发送、会话切换、恢复。

### Phase 5：首次使用与全界面精修

- 首次使用、设置、Provider 配置。
- 视觉一致性、Design Tokens、8 语言、a11y、性能。
- Bundle size gate。

### Phase 6：全量验证与交接报告

- 全量 server pytest、extension node:test、`npm run check`、build、ruff、pyright。
- 真实 VSIX 安装到隔离 Profile，逐条跑完验证矩阵。
- 输出最终报告。

---

## 5. 每轮工作协议

每轮必须按这个顺序：

1. **读代码**：先定位真实链路，不猜。
2. **写计划**：本轮要解决什么、不解决什么、验收标准。
3. **实现**：最小改动，保持结构、命名、Token、8 语言一致。
4. **定向测试**：改哪测哪；新增行为测试优先于源码文本守卫。
5. **构建**：`npm run check`、webview build，必要时 `npm run build`。
6. **真实 GUI**：打包 VSIX，安装到隔离 Profile，真实点击/输入/截图。
7. **证据分级**：PASS / FAIL / BLOCKED / NOT_EXECUTED，不能混用。
8. **交接**：更新文档，写清改动、证据、风险、下一步。

任何“看起来好了”但没真实 GUI 证据的项，只能标 NOT_EXECUTED。

---

## 6. 验收矩阵（必须逐条跑）

1. **首次安装**：全新 Profile → 安装 VSIX → 打开 Trainer → 配置 Provider → 第一条消息 → 关闭重开。
2. **Word 摄入**：导入含标题/列表/表格/图片的 `.docx` → 生成 Markdown → 资料库打开 → 搜索 → 引用带位置。
3. **PPTX 摄入**：导入含多页/备注/表格的 `.pptx` → 每页 Markdown 分节 → Reader → 搜索 → 引用到 slide。
4. **PDF/HTML**：PDF 文本层、网页 URL → Markdown 快照 → 引用到页/段落。
5. **真实项目教学**：打开多文件 Python/TS 工程 → 选中代码 → 提问 → 回答引用行号 → 追问 → 不改文件。
6. **学习/训练闭环**：计划 → 当前阶段 → 训练卡 → 提交 → 验证 → 证据 → 复习。
7. **Agent 资料库管理**：导入、检索、整理、删除、恢复、刷新索引、建卡。
8. **浏览器采集**：HTML 页面 → Markdown 快照 → 资料库。
9. **会话可靠性**：新会话立即发送、切换会话、关闭重开、sidecar 重启、多窗口。
10. **异常**：Provider 401/超时/截断/空响应/语言损坏；远程验证未知/失败/超时。
11. **视觉与可访问性**：340/420/460 宽度、深浅色、8 语言、200% 缩放、键盘导航；整体不要太蓝，主视觉为暖中性/石墨，蓝色只做少量信息提示。
12. **性能与包体**：首屏、树、搜索、长会话导航、streaming longtask；bundle gate。

---

## 7. 当前交接上下文（先验证，不要盲信）

- 仓库工作树可能有大量未提交改动；不要 reset、不要覆盖。
- 近期已做过：Resources 文件行去缩进、Learning 今日 hero、对话单行阶段、Provider reanchor 修复、会话恢复 fence、最近编辑器 selection fallback。
- 用户明确要求“整体不要太蓝色”：主视觉改为暖中性/石墨，蓝色只做极少量信息提示。当前 CSS 仍优先继承 VS Code 的蓝色 `button-background` / `textLink-foreground`，需要解耦，并用深浅色真实截图复验。
- 已知未完成/风险：
  - 真实 Provider 长讲义仍可能 `truncated_or_empty`，需要真实 key/model 对照确认是 max_tokens、hidden reasoning 还是网关误标。
  - App entry chunk 曾约 885KB，超过 820KB gate；需要重新测量并处理。
  - 全量 extension node:test 曾出现挂起；定向测试可通过；需要定位 open handle/长测试，不要用“跳过”掩盖。
  - 真实 Profile 的 Provider 可能 `tools:false`；Agent 工具验证需要 tool-capable provider 或受控 mock。
  - 新会话立即发送的竞态修复需要真实 GUI 复验，不能只看代码。
  - 更新后的真实项目教学复验：选中代码后追问能正确引用第 15/20/21 行，说明 selection 链路可用；但“新会话后第一条消息”仍出现空白助手气泡。首轮空白仍按 P1 处理，不要因为追问成功就关闭。
- 证据目录和历史截图可能在本机 `.tmp/`；不要把旧截图当本轮证据。

---

## 8. 最终交付物

完成后必须给出：

1. 代码改动清单（文件 + 行为）。
2. 新增/更新的测试清单。
3. 真实 GUI 证据：截图路径、操作步骤、结果。
4. 逐项 PASS / FAIL / BLOCKED / NOT_EXECUTED 表。
5. 已知风险与未完成项。
6. 下一轮建议（只列真正阻塞成熟的项）。

完成标准：  
**资料库能稳定消化 Word/PPTX/PDF/HTML 为 Markdown；学习/训练/对话/Agent 形成真实闭环；真实 VSIX 旅程通过；没有伪造成功；UI 克制、渐进披露、8 语言可用。**
