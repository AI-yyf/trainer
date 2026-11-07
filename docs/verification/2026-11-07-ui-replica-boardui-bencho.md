# UI 复刻：BoardUI + Bencho 的克制模式（2026-11-07）

按本轮要求，只学习前两个来源，不安装任何依赖、不引入第二套组件库：
- **BoardUI**（`boardui.com`）：React 19 + Tailwind v4 + React Aria + TanStack Table；
  103 个组件、19 个图表；260px 浮动侧栏（快速搜索 + Kbd + 徽章 + 用户菜单）；
  设置对话框按 General/Profile/Tools/Storage 分页，触发器与打开状态归宿主；
  token 分四层（`@theme` 原语 → `:root` 语义 → `.dark` 覆盖 → `@theme inline` 工具类）。
- **Bencho**（`bencho.dev`）：交互/微动效块；上下文计量是「一条堆叠条或点阵」，
  悬停点亮类别，Compact 时收紧聊天；动效基于 transform，尊重减弱动效；无声音、无玻璃拟态依赖。

复刻原则：只取「信息密度、单一主操作、状态事实、渐进披露」四类模式，
全部落在现有 design tokens 与既有组件上，不新增框架、不改 IA。

## 复刻清单

| 来源模式 | Trainer 落地 | 位置 |
| --- | --- | --- |
| Bencho 上下文计量：一条细条 + 数值，替代大圆环 | Learning「今日学习」移除 68px 环形进度与径向渐变卡面，改为扁平卡 + 3px 进度条 + `1/3` 数值；`prefers-reduced-motion` 只关宽度过渡 | `LearningHome.tsx`、`coach-plan-view.css` |
| BoardUI 侧栏：安静行式导航，不做卡片堆叠 | Learning 的「训练 / 成长」由两张描边卡片改为一行安静入口（图标 + 文案 + `›`），并上移到主操作之后、披露之前 | `CoachPlanView.tsx`、`templates.css` |
| BoardUI 设置分页：事实摘要而非解释句 | Settings 索引「连接」在未配置时显示「未配置」，不再塞入整句要求；行距收紧（10px/2px），四行一屏可扫完 | `CoachSettingsView.tsx`、`templates.css` |
| BoardUI 渐进披露：默认只留当前任务 | 空资料库且方向卡已持有唯一导入 CTA 时，隐藏搜索/展开工具栏（死掉的 chrome），只保留一张卡与一个主操作 | `ResourcesWorkbenchView.tsx` |
| 统一分隔符，不用 ASCII 箭头 | 「总计划 -> 尚未建立」改为「总计划 · 尚未建立」 | `CoachPlanView.tsx` |
| 无强调色：只用前景/字重/间距表达层级 | `--accent` 与 `--link` 收敛为中性前景；焦点环不再借主题彩色 `focusBorder`；所有 `color-mix` 只混合中性 token | `trainer-design-tokens-base-styles.css` |
| 无硬编码颜色 | 新增守卫扫描 webview/shared 源码：禁止 hex、rgb()、hsl()、命名色；token 层禁止 `charts-orange`/`focusBorder`/`textLink-foreground` | `colorLiteralGuard.test.js`、`themeBridgeSource.test.js` |
| 空回复不再留白卡 | 已结束的 assistant 消息若无 body/parts/status，显示八语言的一句话兜底，而不是空白卡片 | `CoachMessageBubble.tsx`、`coachMessageBubbleCopy.ts` |
| 公式不再被反引号降级 | 模型把公式写成反引号时，只有强公式信号（单字母下标/上标/LaTeX 宏 + 运算符）才提升为 `$...$`；snake_case 与普通代码保持原样；提示契约禁止反引号包公式 | `shared/src/latexDelimiters.ts`、`prompts.py` |

## 刻意不复制

- 不引入 BoardUI/Bencho 的组件包、Tailwind、React Aria 或 Motion。
- 不复制玻璃拟态、声音反馈、磁吸/粒子等表现层特效；它们与 VS Code 侧栏的克制目标冲突。
- 不增加新的一级入口或第二套设置页；沿用 Coach / Learning / Resources 与现有六路由。

## 证据

- 真实 VS Code（v1.4.1 VSIX + 隔离 profile）：`output/real-vscode-gui/2026-11-07m/`
  - `04b-learning-screen.png`：空学习态 = 主操作 → 训练/成长安静行 → 模板/动作/总计划披露；
  - `04c-resources-screen.png`：空资料库 = 一张卡 + 一个「导入资料」，`searchInputCount=0`、`importAffordanceCount=1`；
  - `02-settings-index.png`：四行索引，连接摘要为「未配置」。
- 浏览器预览（真实 webview bundle）：`output/ui-replica-2026-11-07/learning-ready.png`
  验证细进度条与扁平卡面；`settings-index.png`、`resources-empty.png` 对照。

## 门禁

- `npm run check` clean
- `npm run test:extension` exit 0
- `npm run verify:ui-geometry` **477/477**
- 真实旅程 `2026-11-07m`：全步骤 `ok:true`（含 02/03/04/04b/04c）
- 最终带进度条/中性色的 VSIX 旅程：`output/real-vscode-gui/2026-11-07o/`（见提交说明）
- `npm run verify:local-latency`：五条本地导航/检查动作 **43–384ms**，全部 <1000ms
  （`output/local-action-latency.json`）；Provider 网络测试只测量派发，不把公网延迟算进本地预算
- 公式：`scenario=rich-content` 的 `` `E = p * c_retry + ...` `` 已渲染为 KaTeX 行内公式
  （`output/ui-replica-2026-11-07/rich-light.png`）
- 中性色：历史抽屉/搜索/新对话均为中性前景与边框（`history-neutral.png`）

## 限制（如实）

- 预览 mock 在 `scenario=empty` 下仍带学习计划，无法在预览里复现「无计划」学习态；
  该状态由真实 VS Code 旅程 `04b` 覆盖。
- 本轮只改三屏的层级与密度，不改信息架构、不新增设置项、不改变任何数据契约。
