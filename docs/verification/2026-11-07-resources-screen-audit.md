# Resources 屏真实 VS Code 操作审计（2026-11-07）

环境：真实 VS Code Electron + v1.4.1 VSIX（隔离 profile）。两套证据：
- 有内容库：`verify:canonical-gui`（真实 DOCX/PPTX/PDF 导入 + 阅读 + 搜索），
  证据 `output/canonical-gui/2026-11-07T00-54-55-380Z/`（含深/浅两套截图）；
- 空库：`run-real-vscode-gui.mjs` 新增 `04c-resources-screen` 步骤（真实点击 资料），
  证据 `output/real-vscode-gui/2026-11-07g/04c-resources-screen.png`。

## 审计准则与结论

| # | 准则 | 结论 | 证据 |
| --- | --- | --- | --- |
| 1 | 单一主操作 | **FAIL → 已修 → PASS** | 空库同视口曾同时出现工具栏「添加资料」与空态「导入资料」两个导入主操作；修复后 `importAffordanceCount=1`（仅空态 CTA） |
| 2 | 真实状态与空态 | PASS | 「还没有资料 / 导入文件、文件夹或网页快照，它们会出现在这里供搜索和复用。」 |
| 3 | 阅读优先、单卡片 | PASS | DOCX 阅读器：返回「‹ 资料库」、标题、来源/状态、「可作为 Coach 上下文 · Plan 证据或 Training 学习素材」、脚注标记 |
| 4 | 结构数据呈现 | PASS | 阅读器表格渲染（Level/fsync）；PPTX/PDF 各自截图（02–04） |
| 5 | 搜索与命中定位 | PASS | 搜索输入 + 清除按钮 + 结果树；命中打开回到阅读器（05/06） |
| 6 | 深浅主题 | PASS | 01（深）与 07（浅）同布局、零硬编码色（既有 token 守卫） |
| 7 | 导航单行、无重复标题 | PASS | 三入口单行；无英文内部术语（"Inline-resources" 为 fixture 真实文件夹名） |
| 8 | 键盘可达 | PASS（既有守卫） | 搜索/菜单键盘导航守卫通过 |

## 发现的缺陷与修复

| 缺陷 | 修复 | 位置 |
| --- | --- | --- |
| 空库首视口两个导入主操作（工具栏「添加资料」+ 空态「导入资料」） | orientation 卡片存在时隐藏工具栏导入按钮（CTA 归空态卡片） | `ResourcesWorkbenchView.tsx` |
| 真实模型回复再现过程叙事变体（「已读取…确认」「教学顺序：」「教学重点：」「当前阻塞：」） | 过滤族扩充至已观测变体（中英），提示规则 22 仍为主控制；代码围栏不受影响 | `coaching_replies.py`、`prompts.py` |
| 旅程脚本无 Resources 步骤 | 新增 `04c-resources-screen`（真实点击 + 截图 + `importAffordanceCount` 断言） | `scripts/run-real-vscode-gui.mjs` |

## 2026-11-07 追加：添加动作与回收站

- 工具栏导入从文字按钮改为搜索框右侧的 **+ 图标**；菜单同时承载「添加文件 / 添加文件夹 / 导入网页快照 / 新建文件夹」。
- 没有真实文件夹时不再渲染空的「文件夹」行；新建文件夹仍可从 + 菜单进入。
- 回收站改为资料库页脚：只在有内容时出现，去掉重复的底边，与文件夹行同一视觉层级。
- 预览证据：`output/ui-replica-2026-11-07/resources-loaded.png`（+ 图标在搜索右侧，回收站为页脚行）。

## 门禁

- `verify:canonical-gui` exit 0（真实 DOCX/PPTX/PDF 导入/阅读/搜索）
- 真实旅程 exit 0：`04c-resources-screen` PASS（导入主操作=1）、`06-first-real-reply` PASS
- `resourcesWorkbenchActionsSource` 新增单主操作守卫；extension suite 0 失败
- 说明：一次旅程运行中真实网关返回空回复（重试未完成）——按 provider 偶发失败记录，未冒充 PASS；重跑通过

## 限制（如实）

- 空库审计使用真实宿主 + fixture Provider（非公网模型）；有内容库审计为真实文档管线。
- 模型过程叙事的确定性过滤只能覆盖已观测句式族；提示契约（规则 22）是主控制，残余风险需持续采样。
- Settings 屏审计尚未进行。
