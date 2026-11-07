# Settings 屏真实 VS Code 操作审计（2026-11-07）

环境：真实 VS Code Electron + v1.4.1 VSIX（隔离 profile）+ 真实 MiniMax Provider
（`PROBE_PROVIDER_*`），由 `scripts/run-real-vscode-gui.mjs` 驱动。
修复后证据：`output/real-vscode-gui/2026-11-07k/{02-settings-index.png,03-provider-saved.png,04-provider-test.png,07-model-switched.png,report.json}`
（`02/03/04` 均 PASS）；修复前对照：`output/real-vscode-gui/2026-11-07g/`（选择器展开、通知截断）。

## 审计准则与结论

| # | 准则 | 结论 | 证据 |
| --- | --- | --- | --- |
| 1 | 单一主操作 | PASS | 唯一实心主按钮「保存并使用此连接」；「重新测试」为安静次级；`04a-test-buttons.count=1` |
| 2 | 真实状态与诚实空态 | PASS | 「连接未测试 / 还没有验证 / 连接已保存。可以直接使用；测试连接只是可选的提前检查。」→「模型已就绪 / 当前工作区 · 对话、计划和训练都会使用这组连接。」；「访问密钥 已保存」 |
| 3 | 渐进披露 | **FAIL → 已修 → PASS** | 首次进入时模型选择器保持展开：摘要行与内层下拉重复显示同一模型（`聊天模型 MiniMax-M2.7` 出现两次）。修复后 `03/04` 的 `modelPickerExpanded=false`，文本只剩一行模型 |
| 4 | 通知完整、不截断 | **FAIL → 已修 → PASS** | 测试成功 toast 曾拼接探测详情，单行被截成「…虽然…」；现只输出完整短句「custom-openai-compatible 已连通。」（07i 截图） |
| 5 | 无内部工程术语 | PASS | 界面无英文内部术语；`custom-openai-compatible` 是用户连接名 |
| 6 | 返回路径 | PASS | 顶部「‹ Trainer 设置」返回索引 |
| 7 | 键盘可达 | PASS（既有守卫） | 模型搜索/选择、设置分区跳转的键盘守卫通过 |
| 8 | 深浅主题与 8 语言 | PASS（既有门禁） | 设计 token 守卫 + `verify:i18n-zoom`（8 语言 × 200%） |
| 9 | 保存 → 测试生命周期 | PASS | 先保存再测试；测试通过后状态与主操作保持一致，连接详情显示当前工作区与模型 |

## 发现的缺陷与修复

| 缺陷 | 根因 | 修复 | 位置 |
| --- | --- | --- | --- |
| 模型选择器首次进入即展开，摘要与下拉重复同一模型 | 展开状态在 Provider 配置水合前按「空模型」初始化，水合后未回收 | 记录「自动展开」来源；模型到达后自动收起；用户手动切换后不再自动收起 | `CoachSettingsView.tsx` |
| 连接测试成功通知被截断（「…虽然…」） | 成功文案拼接了探测详情，toast 单行渲染 | 成功只输出一句「{name} 已连通。」；完整探测信息留在设置面板 | `providerCommands.ts` |
| 旅程 `02-settings-index` 在恢复完成前断言，两次误报 | 脚本在「Trainer 正在准备中」占位期间读取 | 先等待占位消失再断言并截图 | `scripts/run-real-vscode-gui.mjs` |
| 旅程未断言模型选择器折叠状态 | 无结构断言 | 新增 `03/04` 的 `modelPickerExpanded` 断言 | 同上 |

## 如实记录的观察（非产品缺陷）

- 「保存并使用此连接」在已就绪状态仍保留：它是表单的单一实心主操作，测试/刷新为次级；本轮不视为并列主操作。
- `08-switch-reply-partial`：M3.1-Flash 在等待窗口内已产出正确文本但流未按时关闭，按 PARTIAL 记录，不冒充 PASS（与 Settings 无关）。

## 门禁

- 真实旅程 exit 0（`GUI_JOURNEY_OK`）：`02-settings-index` PASS（恢复完成后断言）、`03-provider-saved`/`04-provider-test` PASS 且 `modelPickerExpanded=false`
- `npm run test:extension` exit 0（模型选择器状态守卫更新为新契约）
- `npm run build`、VSIX 重新打包成功
- 真实 Provider：保存 → 测试通过 → 切换模型 → 新模型回答（07/08）

## 限制（如实）

- 本审计覆盖 zh-CN 深色主流程；浅色与 8 语言由既有 `verify:i18n-zoom` 与 token 守卫覆盖，未逐语言截图 Settings。
- 通知文案的完整性以本轮真实 toast 截图为准；不同 DPI/窗口宽度下的换行仍由单行省略策略兜底，不再拼接长句。
