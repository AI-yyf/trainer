# Learning 屏真实 VS Code 操作审计（2026-11-07）

环境：真实 VS Code Electron + v1.4.1 VSIX（隔离 profile）+ 真实 MiniMax Provider
（`PROBE_PROVIDER_*`），通过 `scripts/run-real-vscode-gui.mjs` 驱动。
证据：`output/real-vscode-gui/2026-11-07b/{04b-learning-screen.png,06-first-real-reply.png,report.json}`。

## 审计准则与结论

| # | 准则 | 结论 | 证据 |
| --- | --- | --- | --- |
| 1 | 单一主操作 | PASS | 学习屏只有一个主 CTA「选择工作区」；「训练/成长」为二级入口（chips 级） |
| 2 | 真实状态、无占位假数据 | PASS | 空态文案「先选择学习工作区 / 请选择：加入 Trainer、仅浏览，或忽略。」；「总计划 -> 尚未建立」如实 |
| 3 | 渐进披露 | PASS | 「从模板开始」「动作」「总计划」均为折叠项，默认收起 |
| 4 | 无重复标题 | PASS（3 次出现为：导航标签 + 标题「当前学习」+ 说明句） | `titleOccurrences=3` |
| 5 | 无内部工程术语 | **FAIL → 已修 → PASS** | 真实回复曾含过程叙事（「据此确定讲解重点与可验证的最小实验」）与未印证自检句（「这一步还没在刚才的回复或代码里得到印证，先确认再动手」）；修复后真实回复 2237 字为纯教学，两处句式消失（see §缺陷） |
| 6 | 三入口导航单行 | PASS | 截图「对话 / 学习 / 资料」单行，当前项下划线 |
| 7 | 深色主题与字体层级 | PASS | 标题/正文/eyebrow 层级清晰，无胶囊堆叠 |
| 8 | 与 Coach 的 composer 关系 | PASS（设计判定 §3.7） | Learning 复用同一 dock composer（持久底部输入），与 Coach 共享实例与草稿隔离 |

## 发现的缺陷与修复

| 缺陷 | 修复 | 位置 |
| --- | --- | --- |
| 可见回复夹带工具过程叙事（「读取 X…据此确定讲解重点与可验证的最小实验」）与未印证免责句（「这一步还没在刚才的回复或代码里得到印证，先确认再动手」） | ① 提示契约新增规则 22：禁止在可见回复中叙述工具调用/自检，未验证则取证或提一个精确问题；② 确定性过滤新增该句式族（含英文变体），代码围栏内容不受影响 | `server/app/llm/prompts.py`、`server/app/llm/coaching_replies.py` |
| 旅程脚本硬编码 1.3.4 VSIX（版本漂移） | 改为从 `extension/package.json` 读取版本 | `scripts/run-real-vscode-gui.mjs` |
| 旅程未覆盖 Learning 屏 | 新增 `04b-learning-screen` 步骤（真实点击导航、截图、结构断言） | 同上 |

## 如实记录的观察（非产品缺陷）

- `02-settings-index` 两次运行均 False：脚本在 bootstrap 恢复完成前读取设置屏，看到「Trainer 正在准备中」占位。
  这是**脚本时序**而非设置恢复失败；同一 journey 后续步骤全部拿到真实状态。未修改产品。
- `08-switch-reply-partial`：M3.1-Flash 在等待窗口内产出可见文本但流未按时关闭，按 PARTIAL 记录，不冒充 PASS。

## 门禁

- 真实旅程 exit 0（`GUI_JOURNEY_OK`）：06 真实回复 2237 字 PASS；04b Learning PASS
- `coaching_replies` 过滤新增测试（过程叙事/自检句移除、代码围栏保留）通过
- tsc / ruff / pyright clean；VSIX 重新打包
