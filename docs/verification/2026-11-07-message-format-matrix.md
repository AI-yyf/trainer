# 回复格式矩阵（2026-11-07）

目标：模型输出里的公式、字符格式和块级结构都要渲染；不支持时也要优雅降级，不能空白或崩溃。

## 公式

| 输入 | 处理 | 结果 |
| --- | --- | --- |
| `$x^2$` | `remark-math` → `rehype-katex` | 行内公式 |
| `$$ ... $$` | 同上，display mode | 块级公式 |
| `\( ... \)` / `\[ ... \]` | 归一化为 `$` / `$$`（代码外） | 行内 / 块级 |
| 反引号包公式 `` `E = p * c_retry + ...` `` | 仅在强公式信号（单字母下标/上标/LaTeX 宏 + 运算符）时提升为 `$...$` | 公式；snake_case 代码保持原样 |
| 反引号包 `\( E = mc^2 \)` | 含运算符时剥离反引号并提升 | 行内公式 |
| ` ```math ` / ` ```latex ` / ` ```tex ` 围栏 | 归一化为 `$$` 块 | 块级公式 |
| 表格单元格内的 `$a^2$` | 与 GFM 表格共存 | 单元格内公式 |
| `$ x + y $` | remark-math 允许定界符内空白 | 行内公式 |
| 裸 `\begin{aligned}...\end{aligned}` | remark-math 直接识别环境 | 块级公式 |
| 紧邻标点 `$x^2$。` | 无空格也能解析 | 行内公式 |
| 加粗/列表/引用/表格内的公式 | 段落内节点共存 | 全部排版 |
| `~~~math` 围栏 | 与 ```math 同一路径 | 块级公式 |
| `$\text{中文}$` | KaTeX text 模式 | 中文公式标签 |
| `\$5` / `\$10` | 转义美元符号 | 保留货币文本，不误判公式 |
| `\textcolor{red}{x}` / `\color{blue}` | 只在数学片段内剥离颜色命令 | 中性排版，不引入第二个色相 |
| 非法公式 `$\frac{1}{$` | `throwOnError:false` + 中性 errorColor | 可读的错误片段，整条回复不崩 |

## 字符与块级格式

| 格式 | 输入 | 结果 |
| --- | --- | --- |
| 粗体 | `**文本**` | `<strong>` |
| 斜体 | `*文本*` | `<em>` |
| 删除线 | `~~文本~~` | `<del>` |
| 行内代码 | `` `code` `` | `<code>` |
| 链接 | `[文本](https://...)` | 中性色 + 下划线，新窗口打开 |
| 单换行 | 段内 `\n` | `<br>`（`remarkChatBreaks`） |
| 标题 | `## 标题` | `<h2>` |
| 引用 | `> 引用` | `<blockquote>` |
| 列表 / 任务 | `- 项`、`- [x] 项`、`1. 步` | `<ul>/<ol>/<li>` + checkbox |
| 分隔线 | `---` | `<hr>` |
| 表格 | GFM 表格 | 富表格（列上下文、无障碍 caption） |
| 脚注 | `[^1]` + 定义 | `<sup>` + `.footnotes` |
| 代码块 | ```ts | Shiki 高亮 + 复制 |
| Mermaid | ```mermaid | 图表或诚实降级 |

## 证据

- `output/ui-replica-2026-11-07/formats-dark.png`：同一条回复内同时出现粗体/斜体/删除线/行内代码/链接/换行/标题/引用/列表/任务/分隔线/脚注/三种公式/表格/Mermaid。
- `output/ui-replica-2026-11-07/rich-light.png`：浅色主题下反引号公式已升级为 KaTeX。
- 浏览器实测计数（`playwright`）：`strong 3 / em 2 / del 1 / inlineCode 1 / link 3（含脚注回链）/ br 1 / katex 13 / table 1 / h2 2 / blockquote 2 / li 5 / checkbox 1 / hr 1 / footnotes 1`；非法公式 `pageerror=[]`、`.katex-error=1`。

## 门禁

- `node --test extension/tests/latexDelimiters.test.js`（含围栏公式、反引号公式、snake_case 边界、代码围栏不变）
- `node --test extension/tests/remarkChatBreaks.test.js`（换行、代码/公式叶子不变）
- `npm run check`
- `npm run verify:ui-geometry`
- `npm run verify:local-latency`

## 边界（如实）

- 未启用 `rehype-raw`：原始 HTML 仍按文本显示，这是安全边界，不为了“格式全”放开。
- `\textcolor`/`\color` 等颜色命令只在数学片段内剥离；代码与围栏字节不变。
- 公式提升只覆盖可判定的强信号；`foo_bar = 1` 这类代码不会被误判成公式。
- 非法公式显示 KaTeX 的错误片段而不是静默删除，便于发现模型输出问题。
