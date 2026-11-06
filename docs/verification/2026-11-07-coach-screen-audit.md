# Coach 屏真实 VS Code 操作审计（2026-11-07）

环境：真实 VS Code Electron（Extension Development Host）+ v1.4.1 VSIX（隔离 profile），
延迟回环 fixture Provider（受控延迟，非真实公网模型——UI 为真实宿主）。
证据目录：`output/coach-gui/2026-11-06T23-22-46-899Z/`（修复后）、
`output/coach-gui/2026-11-06T22-51-13-439Z/`（修复前）、
`output/i18n-zoom/2026-11-06T23-24-20-575Z/`（8 语言 200% 缩放）。

## 审计准则与结论

| # | 准则 | 结论 | 证据 |
| --- | --- | --- | --- |
| 1 | 单一主操作（composer 一次发送/停止） | PASS | 01/02 截图：仅一个发送（或停止）圆形按钮，无并列 CTA |
| 2 | 真实状态：单行、无步骤号、无骨架屏、无双 loading | PASS | report facts：`statusNodeCount=1`、`statusText=正在思考`、`skeletonCount=0`、`stepNumberCount=0` |
| 3 | 无内部工程术语 / 冗余横幅 | **FAIL → 已修 → PASS** | 修复前：回复上方出现英文 `Stream message completed.`（随后本地化为「本轮教练回复已完成。」）；根因：`deriveTrainerStreamingOperationMessage` 对每个成功回复都生成完成横幅，且 `webviewBridge` 把命令 `result.message` 当 operation 状态投递。修复后（23-22-46 截图）：无横幅，消息流即反馈 |
| 4 | 回复可读性与可操作性 | PASS | 正文连续 prose；下方图标行（复制/导出/收藏/…）宽度克制，无重复标题、无胶囊堆叠 |
| 5 | 新会话首条消息不丢 | PASS | 03/04 截图 + report：新会话后立即发送，首条消息可见且收到回复 |
| 6 | 三入口单行导航（对话/学习/资料） | PASS | 每张截图导航均单行、当前项下划线 |
| 7 | 8 语言 × 200% 缩放不溢出 | PASS | `verify:i18n-zoom` exit 0，`failures: []` |
| 8 | 键盘可达（Enter 发送 / Esc 关闭菜单） | PASS（既有守卫） | mention/命令面板键盘导航守卫测试通过；本审计未做逐键录屏 |

## 发现的缺陷与修复（本轮）

| 缺陷 | 修复 | 位置 |
| --- | --- | --- |
| 成功回复上方出现完成横幅（内部命令文案；中文环境仍重复「本轮教练回复已完成。」） | ① `shared/src/protocol.ts`：普通成功回复不再生成完成横幅（仅保留带 summary/nextStep/工具步数/token/非名义 stopReason 或 reliability 失败的提示）；② `extension/src/core/webviewBridge.ts`：会话流式命令成功时不再投递 operation 状态（失败仍投递） | `shared/src/protocol.ts`、`extension/src/core/webviewBridge.ts` |
| 合同测试断言旧行为 | 更新 `extension/tests/typedMessagePartsShared.test.js`：普通成功 → `undefined`；保留工具步数/失败/截断断言 | — |

## 门禁

- `verify:coach-gui` exit 0（修复后两次，`failures: []`）
- `verify:i18n-zoom` exit 0（8 语言 × 200%）
- `npm run test:extension` exit 0（0 断言失败）
- `npm run build`（extension + shared）成功；VSIX 重新打包

## 限制（如实）

- 本审计使用 delayed loopback fixture Provider（真实 VS Code 宿主、非真实公网模型）：
  验证的是界面/状态契约，不是模型教学质量（后者见真实 Provider 回归证据）。
- 本审计覆盖深色主题与 zh-CN 主流程；浅色与 8 语言覆盖来自 `verify:i18n-zoom` 截图。
- Learning / Resources / Settings 屏的逐屏审计尚未进行（下一轮）。
