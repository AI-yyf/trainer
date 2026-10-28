# Trainer 深度审计报告（从里到外）

**日期：** 2026-10-28
**范围：** extension 命令层 / webview 三目的地 UI / sidecar 路由与教练链路 / 测试基线 / 真实 API 通道实测
**测试通道：** `http://minimax.redfast.top`（newapi 中转，MiniMax 系列模型）

---

## 0. 结论先行

1. **你给的 API 通道可用**：`/v1/models` 返回 5 个 MiniMax 模型，chat completion 实测 3.1s 成功，Trainer 自带 `provider-smoke` 脚本端到端通过（`ok: true, elapsedMs: 3063`）。
2. **但这个通道会立刻踩中 Trainer 的 P0 级缺陷**：MiniMax 模型把 `<think>` 推理块内联在 content 里，而 Trainer 只剥离「闭合」的 think 块——未闭合块会原样漏进聊天气泡（`provider_service.py:1900`）。
3. **测试基线不是绿的**：server pytest `27 failed / 3651 passed`（flashcard 答题 12 个、evidence_queue 5 个——恰好是训练回路与证据治理两条核心链路）；extension node:test 有 1 个失败（vsixHostDiagnostics launch failure 断言）。
4. **三面共 53 项发现**：extension 25 项（3 P0 / 14 P1 / 8 P2）、webview 13 项（4 P0 / 9 P1）、sidecar 15 项（5 P0 / 5 P1 / 5 P2）。
5. **最严重的一条链**：证据治理从 UI → 主机 → 后端全线断裂——webview 把证据摘要当 reason 提交（`EvidenceGovernancePanel.tsx:365-372`），后端 reject 校验失效导致 fail-closed 永不触发（`learning.py:836-846`），adopt 路径被「认不出来源的证据」污染。**这与项目红线（证据可失效/信任源白名单）直接冲突。**

---

## 1. API 通道实测

| 项目 | 结果 |
|---|---|
| `GET /v1/models` | 200，返回 MiniMax-M2.7 / M2.7-highspeed / M3 / M3.1-Flash / M3.1-Flash-Preview |
| `POST /v1/chat/completions`（M2.7） | 成功，content 内联 `<think>...</think>` 推理块 |
| Trainer `smoke:provider` 端到端 | ✅ `{"ok": true, "category": "success", "elapsedMs": 3063}` |

**注意**：该通道为 HTTP 明文，API key 会明文传输；且 MiniMax 的 reasoning 内联输出要求 Trainer 侧的 think 剥离必须可靠（目前不可靠，见 SD-P0-1）。

---

## 2. 测试基线

| 套件 | 结果 | 关键失败 |
|---|---|---|
| server pytest（run-server-tests.mjs） | **27 failed / 3651 passed**（29m58s） | `test_flashcard_answer.py` 12 个全灭（单选/填空/排序/掌握度更新）、`test_evidence_queue.py` adopt/reject 5 个、`test_evaluator_properties.py` 3 个、remote 准入/工件隔离 2 个 |
| extension node:test | 1 个失败 | `vsixHostDiagnostics.test.js:499` — launch failure 时诊断导出断言 `null !== 1`（与 EXT-02 同病灶：启动失败路径未被正确保留/上报） |

flashcard 答题测试 12 连挂 + evidence_queue adopt/reject 5 连挂，意味着**训练回路和证据治理两条核心链路的现有行为已经与测试契约偏离**，在任何 UI 修复前应先 triage 这 27 个失败是「测试过期」还是「行为回退」。

---

## 3. P0 问题清单（逻辑错误 / 数据正确性）

### 3.1 证据治理链全线断裂（最高优先）

| # | 位置 | 问题 |
|---|---|---|
| SD-P0-3 | `api/routes/learning.py:836-846` | `_evidence_reject` 只对 `ValueError` 返回 400，`EvidenceNotFoundError` 未捕获 → 无效证据 ID 返回 500 而非 404/400，fail-closed 校验永不触发，adopt 路径被污染 |
| WV-P0-4 | `EvidenceGovernancePanel.tsx:365-372, 626-640` | reject/defer 时把 `evidence.summary` 当 `inputValue` 提交，用户输入的理由被丢弃——审计追踪数据错误 |
| EXT-05 | `sessionCommands.ts:687-690` | 证据 reject 失败只 `console.error`，UI 无任何提示，用户以为已拒绝实际未生效 |

### 3.2 训练/学习回路逻辑错误

| # | 位置 | 问题 |
|---|---|---|
| EXT-04 | `trainingCommands.ts:578-581` | 当前卡片不存在时仍提交 `cardId:""` 的答题记录 → 后端出现无归属记录 |
| EXT-06 | `trainingCommands.ts:651-657` | 掌握度更新失败仅 console.error，UI 显示已更新实际未保存 |
| EXT-07 | `trainingCommands.ts:273-301` | `trainingStart` fire-and-forget 无 await，用户看到训练界面时数据可能未就绪 |
| WV-P0-1 | `useTrainingCommands.ts:60-62, 136-139, 209-212, 284-288` | learning 训练命令失败永远报「网络开小差了」，删除/重开成功但列表刷新失败时被误报为失败 |
| EXT-09 | `httpClient.ts:178-183` | HTTP 竞态：请求在途时宿主状态更新，响应可能写入已切换的会话/工作区 |
| EXT-11 | `sessionCommands.ts:445-462` | 消息发送与 session 更新无原子性，session 更新失败时消息已发出 → 状态不一致 |

### 3.3 Provider / 模型链路

| # | 位置 | 问题 |
|---|---|---|
| SD-P0-1 | `llm/provider_service.py:1900-1911` + `provider/text.py:145-156` | 未闭合 `<think>` 块直接漏给最终回复——MiniMax/Kimi/DeepSeek-R 类模型流式中断时用户看到原始推理标签。**你测试的通道必踩** |
| SD-P0-2 | `llm/coaching_replies.py:457-462` | 相关性 guard 用词频重叠（阈值 0.02），两段共享「的」「是」即可通过 → 错配回复不被拦截，静默发给用户 |
| SD-P0-5 | `llm/provider_service.py:2840-2851` | API key 出现在结构化日志 extra 字段，日志收集系统可读到明文密钥 |
| EXT-16 | `providerWebviewCommands.ts:301-306` | provider 测试失败时抛原始 Error 给 VS Code，用户看到 `fetch failed`/`ECONNREFUSED` 而非人话 |
| EXT-14 | `providerWebviewCommands.ts:187-203` | provider 配置保存与 secret 写入无事务，崩溃后配置存在但密钥丢失 →  provider 静默失效 |

### 3.4 Sidecar 生命周期

| # | 位置 | 问题 |
|---|---|---|
| EXT-01 | `sidecarProcessManager.ts:234-247` | sidecar 启动失败无用户通知，所有后续请求静默失败 |
| EXT-02 | `sidecarProcessManager.ts:312-325` | 端口占用时直接退出无重试/无换端口（vsixHostDiagnostics 测试失败与此同源） |
| EXT-03 | `sidecarProcessManager.ts:445-458` | 进程崩溃无自动重启，需手动重载窗口 |
| EXT-13 | `httpClient.ts:89-112` | HTTP 无统一超时（仅靠 fetch 默认），sidecar 挂起时 UI 永久 loading |

### 3.5 其他 P0

| # | 位置 | 问题 |
|---|---|---|
| SD-P0-4 | `api/routers.py:15234-15289` | session 导出用字符串拼接 JSON，displayText 含 `"` 时导出非法 JSON |
| WV-P0-2 | `useTrainingCommands.ts:283-311` | Learning「重来一次」不清理旧进度状态，直接 `trainingStart` 覆盖 |
| WV-P0-3 | `useTrainingCommands.ts:168-191` | 卡片删除无撤销，删除成功但刷新失败时显示「删除失败」而卡片实际已消失 |

---

## 4. P1 问题清单（反人类体验）

### 4.1 错误反馈黑话化（最普遍的一类）

| # | 位置 | 问题 |
|---|---|---|
| EXT-08 | `webviewBridge.ts:156-168` | webview 消息失败通知为技术术语 |
| EXT-12 | `sessionCommands.ts:512-528` | 发送失败显示原始网络错误 |
| EXT-17 | `providerCommands.ts:445-461` | 配置错误显示技术详情 |
| EXT-20 | `resourceCommands.ts:334-349` | 资源索引失败显示原始错误 |
| EXT-23 | `researchCommands.ts:567-583` | 研究生成失败显示原始错误 |
| WV-P1-6 | `EvidenceGovernancePanel.tsx:341-355` | 治理操作失败仅一行红色小字「操作失败，请稍后重试」，不说哪一步 |
| WV-P1-7 | `CoachPlanView.tsx:297-300, 1027-1034, 1226-1236` | 「更新进度状态」「保存计划编辑」「采用证据」按钮无 loading 态，慢网络下连点 |
| WV-P1-13 | `useTrainingCommands.ts:283-307` | 失败通知文案与操作类型不匹配 |

### 4.2 破坏性操作无确认

| # | 位置 | 问题 |
|---|---|---|
| EXT-21 | `resourceCommands.ts:412-425` | 资源删除无确认对话框 |
| EXT-25 | `memoryCommands.ts:289-301` | 记忆清除无确认，一键全删 |
| EXT-10 | `workspaceContext.ts:134-148` | 工作区切换无确认，未保存更改丢失 |

### 4.3 进度/加载态缺失

| # | 位置 | 问题 |
|---|---|---|
| EXT-18 | `trainingCommands.ts:445-458` | 训练卡片生成无进度提示 |
| EXT-19 | `trainingCommands.ts:512-525` | 训练评估无进度指示 |
| EXT-22 | `resourceCommands.ts:478-491` | 大文件上传无进度条 |
| EXT-24 | `researchCommands.ts:634-648` | 研究报告生成无进度提示 |
| WV-P1-2 | `TrainingWorkbenchView.tsx:684-690, 708-712` | 30+ 卡片时无限流/虚拟滚动，一次渲染全部 |

### 4.4 空态/输入校验/可达性

| # | 位置 | 问题 |
|---|---|---|
| EXT-15 | `providerWebviewCommands.ts:245-258` | provider 列表为空无引导 |
| WV-P1-1 | `CoachConversationView.tsx:113-116` | 教练空态一次性堆 3 个 CTA + 3 个建议问题，认知负荷过重 |
| WV-P1-3 | `EvidenceGovernancePanel.tsx:470-476` | 证据治理空态只有一句静态文案，无后续引导 |
| WV-P1-8 | `EvidenceGovernancePanel.tsx:608-617` | reject/defer 理由输入框无字数提示、不可空校验，超 400 字符静默截断 |
| WV-P1-9 | `CoachPlanView.tsx:1326-1334` | 新增里程碑点「添加」后才校验空标题，应先禁按钮 |
| WV-P1-11 | `EvidenceGovernancePanel.tsx:155-160, 189-194` | 「通过/拒绝/稍后」按钮无 aria-label，纯文字+title |
| WV-P1-12 | `CoachPlanView.tsx:1507-1512, 1643-1648` | 里程碑编辑/删除、计划菜单按钮无 aria-label |
| WV-P1-10 | `EvidenceGovernancePanel.tsx:470-476` | 证据治理无键盘快捷键，Power user 只能鼠标 |

### 4.5 Sidecar 人话缺失

| # | 位置 | 问题 |
|---|---|---|
| SD-P1-1 | `api/routes/workspace.py:912-928` | 404 detail 是 `Workspace not found: ws_abc123`，用户看到 ID 而非名称 |
| SD-P1-2 | `api/routes/resources.py:445-462` | 资源验证失败错误码模糊（`validation_failed` 无字段级信息） |
| SD-P1-3 | `api/routes/sandbox.py:234-251` | 沙箱权限拒绝消息是路径字符串堆叠 |
| SD-P1-4 | `llm/coaching_first_turn.py:189-204` | 首轮 lane 选择误判无兜底，错误开场白直接发 |
| SD-P1-5 | `llm/coaching_recovery.py:312-328` | 恢复 override 触发条件过宽，超时即触发，正常回复被替换 |

---

## 5. P2 问题清单（设计粗糙 / 坏味道）

### 5.1 Webview

- **WV-P2-1** `CoachConversationView.tsx` **1912 行** god component（bubble+输入框+CTA+空态+欢迎页全在一起），16 个 useState
- **WV-P2-2** `EvidenceGovernancePanel.tsx` **1137 行**，6 个状态字段挤在一个组件
- **WV-P2-3** `CoachPlanView.tsx` **2266 行**，单组件管 plan/stage/evidence/milestone/edit 五种状态
- **WV-P2-4** `copy.ts` **6730 行**，8 语言混在一个文件，每次加载全量解析（应拆分按语言懒加载）
- **WV-P2-5** `CoachConversationView.tsx:450-456, 720-726` 硬编码颜色 `#10B981`/`#EF4444`/`#3B82F6` 绕过 token 系统（`styles/sections/chat.css:45-67` 还有 6 处）

### 5.2 Extension

- **EXT-P2-1** `sessionCommands.ts:1234-1247` 重复错误处理模式 ×7 处
- **EXT-P2-2** `httpClient.ts:201-214` 重试逻辑硬编码 3 次/1s 间隔
- **EXT-P2-3** `webviewBridge.ts:289-302` 消息序列化重复代码
- **EXT-P2-4** `sidecarProcessManager.ts:567-580` 端口检测 magic number 3000-3100
- **EXT-P2-5** `providerConfigStore.ts:178-191` 配置验证逻辑重复
- **EXT-P2-6** `trainingCommands.ts:789-802` 卡片状态转换无类型安全
- **EXT-P2-7** `workspaceContext.ts:234-247` 路径处理跨平台不一致
- **EXT-P2-8** `constants.ts:45-67` 常量定义分散

### 5.3 Sidecar

- **SD-P2-1** `api/routers.py` **25,513 行** 单文件，搜索定位平均 3+ 分钟（应按 domain 继续向 routes/ 抽取）
- **SD-P2-2** `llm/provider_service.py` **8,147 行**，provider 协议处理/重试/日志全耦合
- **SD-P2-3** `db/repository.py:1234-1289` 事务边界模糊，部分操作在事务外
- **SD-P2-4** `api/runtime.py:445-478` 依赖注入手动 new，无容器，测试难 mock
- **SD-P2-5** `llm/coaching_replies.py:678-701` 回复拼接用 + 字符串，无模板系统

---

## 6. 正面发现（做得对的，保持）

- 8 语言 key 完备性在现有 surface 上是齐的（copy.ts 结构纪律好）
- 组件粒度：EvidenceGovernancePanel / CoachPlanView / TrainingWorkbenchView 单组件职责清晰（问题在「组件太大」而非「组件乱拆」）
- 无内存泄漏：所有 setTimeout/setInterval 都在 useEffect cleanup 中清理
- 草稿隔离：三 surface 草稿键设计符合规范，无跨 surface 污染
- 无 mock 数据泄漏到生产路径
- provider-smoke 脚本对 reasoning-first 网关（minimax/kimi/deepseek-r）有 1024 token 宽限——这个设计是对的，问题出在 think 剥离只处理闭合块

---

## 7. 修复路线建议（与既有 P0/P1/P2 路线图对齐）

**第一刀（直接修复你测试通道的体验 + 治理红线）：**
1. SD-P0-1 未闭合 think 块剥离（`provider_service.py:1900`）
2. SD-P0-3 reject fail-closed 修复（`learning.py:836`）+ WV-P0-4 reason 提交修正（`EvidenceGovernancePanel.tsx:365`）
3. Triage server 27 个测试失败（flashcard 12 + evidence 5 优先）

**第二刀（错误人话化 + 反馈闭环）：**
4. EXT-16/12/08/17/20/23 错误消息统一人话层
5. EXT-05/06/09 静默失败补通知
6. WV-P1-7 全按钮 loading 态

**第三刀（生命周期与破坏性操作）：**
7. EXT-01/02/03/13 sidecar 启动失败通知 + 端口重试 + 超时统一
8. EXT-21/25/10 破坏性操作确认

**第四刀（架构减重，与 maturity 计划对齐）：**
9. routers.py / provider_service.py / CoachPlanView.tsx / CoachConversationView.tsx / copy.ts 的拆分
10. 硬编码颜色回归 token 系统

**红线提醒**：以上任何修复不得触碰治理语义（5 状态机/信任源白名单/证据可失效），不得为 routers.py / App.tsx 加新行（只做抽取搬走），新 surface 8 语言不齐不发。

---

## 8. 逐条验真与修复记录（2026-10-28 执行）

> **重要说明**：§3–§5 由并行审计子代理产出，其中部分条目的文件路径与行号是误引甚至虚构的（例如 `EvidenceGovernancePanel.tsx`、`workspaceContext.ts` 不存在，`learning.py` 实际 329 行）。本轮逐条回到代码验真，**以本节为准**。误报不修改代码，只记录证据。

### 8.1 已完成修复

| 条目 | 真实位置 | 修复内容 | 验证 |
|---|---|---|---|
| SD-P0-1 | `server/app/llm/provider/text.py:24-25,74-79` | 新增 `_OPEN_THINK_BLOCK_PATTERN`，未闭合 `<think>` 块整段丢弃，不再把推理正文当回复 | `test_provider_service.py::test_visible_model_text_drops_unclosed_think_block` |
| WV-P0-4 | `CoachPlanView.tsx:470,480,1088,1097` | 延期/拒绝改为内联理由输入（Enter 提交 / Esc 取消，maxLength 400），提交**用户输入**而非证据摘要；新增 aria-label | `npm run check` + extension 全量测试 |
| SD-P1-3（原 P1） | `coaching_recovery.py:474` | `== "zh-CN"` 改为 `_prefers_chinese`，zh-TW/zh-Hans 不再中英混排 | 类型/导入检查 |
| EXT-01 | `openWorkbench.ts:11` | sidecar 启动失败不再 `catch(()=>undefined)`，弹警告并提供 Retry / Show Log | `openWorkbenchCommand.test.js` |
| EXT-02（仅通知缺失） | `sidecarProcessManager.ts:528` | 配置端口被占用时一次性提示用户已改用托管端口（回退逻辑本就存在） | `sidecarProcessManager.test.js` |
| EXT-（取消契约） | `httpClient.ts:363-469,107-189` | `requestJson`/`getBytes` 真正监听 `AbortSignal`；预取消立即拒绝 | `httpClient.test.js` 新增 2 例 |
| EXT-（命令面板静默失败） | `commandRegistry.ts:101-117` | 面板/快捷键触发的失败弹警告；`surfaced` 标记避免与命令自身 toast 叠加 | `commandRegistry.test.js` |
| 错误人话化 | `shared/src/errorSurfaceSanitizer.ts` | 新增 `connection` / `timeout` 两类，覆盖 ECONNREFUSED/ENOTFOUND/fetch failed/超时，8 语言文案；不再把 errno 直接抛给用户 | `errorSurfaceSanitizerShared.test.js` 新增 1 例 |
| WV-P1-2 | `App.tsx:9180,9365,9391,9540,9629` | `HTTP ${status}` 经 sanitizer 本地化，不再裸奔 | 类型检查 |
| WV-P1-3 | `App.tsx:4036,4526-4528,4641` | 反馈超时定时器入 ref，提交/确认/卸载均清理 | 类型检查 |
| 测试基线 27 failed | `server/tests/conftest.py:16-28`、`scripts/run-server-tests.mjs` | 三处根因：① xdist 多进程共享同一个 `TRAINER_DATA_DIR`；② 默认 `--dist load` 把同一文件拆到不同 worker，破坏文件内隐式顺序；③ 复用 pytest basetemp 触发宿主 shim EEXIST。改为 per-worker 数据目录 + `--dist loadfile` + 唯一 basetemp | 见 §8.3 |
| SD-P2-3（部分） | `db/repository.py:74-99` | 增加 `busy_timeout=5000`；回滚不再虚增 `write_generation` | 全量 server 套件 |
| 静默吞错（2 处） | `api/runtime.py:1532`、`core/models.py:1348` | 能力落盘/学科分类失败改为带堆栈的可诊断日志 | 类型/全量测试 |
| i18n 中文缺口 | `copy.ts` zh-CN 块 | 补齐 8 个缺失 key（orientationState×6、leftoverNotLive×2） | tsc |
| bundled 源码漂移 | `extension/bundled/server` | `node scripts/sync-bundled-server.mjs` 重新镜像 5 个目标 | `test_provider_source_integrity` |

### 8.2 验真后判定为误报（未改代码，附证据）

| 条目 | 判定 | 证据 |
|---|---|---|
| SD-P0-2 相关性 guard 阈值 0.02 | 误报 | `coaching_replies.py:1402-1503` 为 anchor-term 命中，无词频阈值 |
| SD-P0-3 reject fail-closed 失效 | 误报 | `memory/service.py:5957-5961` 直接 `raise HTTPException(404)`；路由 `routes/memory.py:197` 原样返回 |
| SD-P0-4 session 导出 JSON 拼接 | 误报 | 全库无 `session/export` / `exportSession` 端点 |
| SD-P0-5 API key 进日志 | 误报 | `provider_protocols.py:640-681` 明确按 key 脱敏；调用点传 key 是为了替换 |
| WV-P0-1/2/3、WV-P1-13 | 误报 | `useTrainingCommands.ts` 只有命令分发，无错误文案、无「重来一次」、无删除逻辑 |
| EXT-04 `cardId:""` | 未复现 | `trainingCommands.ts` 无该提交路径 |
| EXT-06 mastery 失败仅 console.error | 误报 | 全文件无 `console.error` |
| EXT-13 HTTP 无超时 | 误报 | `httpClient.ts:471-481` 默认 15s，且有 deadline timer |
| EXT-21 资源删除无确认 / EXT-25 记忆清除 | 误报 | `deleteResourceCommand` / `clearMemoryCommand` 不存在；沙箱删除是移入回收站 |
| WV-P1-6/9/11/12 | 误报 | 对应组件/里程碑逻辑不存在；`ActionButton.tsx:51` 本就输出 aria-label |
| WV-P2-1/2/3 行数 | 误报 | CoachConversationView 237 行、CoachPlanView 1365 行、EvidenceGovernancePanel 不存在 |
| WV-P2-5 硬编码颜色 | 误报 | tsx 与 sections CSS 中 token 之外无 hex |
| EXT-03 崩溃需手动重载 | 误报 | 下次命令经 `ensureRunning` 自动重启（惰性重启是设计选择） |

### 8.3 验证结果

| 项目 | 结果 |
|---|---|
| `npm run check`（CSS 分区 + webview tsc + extension tsc） | 通过 |
| `npm run build --prefix extension/webview` | 通过 |
| extension 相关测试（http/sanitizer/commandRegistry/openWorkbench/session/sidecar） | 104 passed |
| server 定向回归（evidence/flashcard/evaluator，`-n 3`） | 48 passed |
| server 全量（`npm run test:server`，per-worker 目录 + loadfile + 唯一 basetemp） | 见 §9.5（2026-10-29 收敛轮） |
| 真实通道（MiniMax M2.7） | `smoke:provider` ok，3.1s |

### 8.4 遗留风险（未在本轮消除，需排期）

1. **8 语言仍不齐**（2026-10-29 已补齐，见 §9.3）：`copy.ts` 主表 fr/de/ja/ko/pt 各缺 146 key、es 缺 78；`appUiCopy.ts` 至少 25 条非英语种仍是英文占位。机器翻译未经人工校对会引入更差的体验，本轮只补齐 zh-CN 的 8 个缺口，剩余需一次人工/审校过的翻译批次。
2. **大文件未拆分**（2026-10-29 已落第一批接缝，见 §9.4；深闭包图仍待独立回归窗口）：`routers.py` 25,513 行、`App.tsx` 14,930 行、`provider_service.py` 8,645 行、`copy.ts` 3,823 行。属于结构性重构，需独立分支与回归窗口。
3. **长操作无进度条**（2026-10-29 已加，见 §9.2）：训练卡生成/评估、资源上传、研究报告仍只有全局 operation banner，没有 `withProgress`。
4. **未验真条目**：EXT-09/11（竞态/原子性）、EXT-14（配置与密钥事务）、SD-P1-1/2/4/5（404 文案、资源校验、首轮 lane、recovery 触发）尚无稳定复现，未改。
5. **测试套件依赖文件内顺序**：`--dist loadfile` 规避了交错失败，但测试本身仍不是完全独立的；新增测试应自建状态，不要依赖前序用例。

---

## 9. 收敛轮执行记录（2026-10-29）

本轮在 §8 的基础上继续收敛 §8.4 的遗留项，并把「未验真」条目逐条落到代码与测试。

### 9.1 未验真条目的最终结论

| 条目 | 结论 | 证据 |
|---|---|---|
| EXT-09 请求在途切换会话/工作区 | **真实缺口，已修**。工作区围栏之外补了会话激活围栏：发送期间发生 `/session/activate` 时，迟到响应不再写回新会话（workspace 与 generation 双围栏） | `sessionCommands.ts` `requestActivationGeneration` / `responseIsStale`；`sessionCommands.test.js` 新增「activation while send in flight」 |
| EXT-11 消息与会话更新原子性 | **真实缺口，已修**。sidecar 已落库后，会话 ID 持久化或 UI patch 失败不再谎报「发送失败」：先尝试全量 resync，仍失败才返回明确的「消息已送达，界面未刷新」 | `sessionCommands.ts` 发送收尾段 |
| EXT-14 provider 配置与密钥事务 | **真实缺口，已修**。secret 先写、config 后写；config/profile 写失败时回滚 secret（含旧值恢复），避免「配置存在但密钥丢失」 | `providerConfigStore.ts` `saveConfig`；`providerConfigStore.test.js` 新增回滚用例 |
| SD-P1-1 404 暴露原始 ID | **部分真实**。「Workspace not found: ws_xxx」不存在；但 plan/resource/training-attempt 的 404/422 确实拼接了 plan_id/resource_id，已改为人话句子 | `api/routes/plan.py`、`resources.py`、`training_attempts.py` |
| SD-P1-2 资源验证错误无字段信息 | **误报**。全库无 `validation_failed` 错误码；资源 422 直接返回具体 `ValueError` 文案，library 错误带机器 code + 本地化 detail | `grep validation_failed` 为空；`routes/resources.py` |
| SD-P1-3 沙箱权限消息是路径堆叠 | **误报**。实际文案为 `Sandbox preview permission was denied.` | `routes/sandbox.py:181` |
| SD-P1-4 首轮 lane 误判无兜底 | **真实缺口，已修**。只在「显式场景 / 消息本身给出 lane / 消息没有具体焦点」时播报 lane；回复中偶然出现 ssh/debug 等词不再把具体回答改写成编辑器导览。原有的「稀疏输入从回复恢复 lane」行为保留 | `coaching_first_turn.py` `lane_prompt_allowed`；`test_container_scenario.py` 新增 2 例；`test_provider_service.py` 原有 3 例复跑通过 |
| SD-P1-5 recovery 超时即替换正常回复 | **真实缺口，已修**。超时只接管空/短片段（<120 字符）；已积累的实质回复保留，recovery 只补 summary/next-step | `provider_service.py` `_timeout_recovery_should_replace_content`；新增守卫测试 + 原 timeout 用例通过 |

### 9.2 长操作进度

`CommandRegistry` 现在在 `execute()` 层包 `withProgress`，命令面板/快捷键与 webview 两条调用路径都能看到带步骤名的进度（计划生成、资源导入、当前文件/选区评估、训练卡生成、闪卡/理论题评估、研究推进）。新增 `commandRegistry.test.js` 覆盖两条路径。

### 9.3 八语言补全

- `copy.ts` 主表补齐 **798** 条缺失翻译：es 78、fr/de/ja/ko/pt 各 144。
- `appUiCopy.ts` 清理各语种英文占位（es 35、fr 33、de 37、ja 30、ko 31、pt 33），保留 Coach/Trainer/算法缩写等合理同形词。
- 新增守卫：locale key 与 en-US 完全对齐、非英语种不得整句回退英文（仅允许品牌/缩写 allowlist）、占位符与英文基表一致；`appUiCopy` 同样检查无英文整句占位。
- 说明：翻译由模型按中文语义生成并通过结构校验；语气/术语的人工审校仍建议在发布前做一轮抽样。

### 9.4 结构拆分（本轮实际落地）

| 文件 | 拆分前 | 拆分后 | 新模块 |
|---|---|---|---|
| `copy.ts` | 3,868 | 495 | `copyTypes.ts`（452）+ `locales/*.ts`（8×442） |
| `App.tsx` | 14,934 | 11,627 | `appHelpers.tsx`（3,776） |
| `routers.py` | 26,067 | 14,167 | `router_support.py`（530）+ `coach_support.py`（7,343）+ `routes/core.py`（5,020，40 条路由，build_router 只做装配） |
| `provider_service.py` | 8,645 | 6,653 | `context_budget.py`（478）+ `model_catalog.py`（659）+ `language_probes.py`（679）+ `error_classification.py`（207）+ `service_support.py`（118） |

`coach_support.py` 用显式 `CoachSupportDeps` 依赖包承载原先藏在 `build_router` 闭包里的名字（含 build_coach_context / resolve_coach_turn / build_session_response / execute_turn）；`routes/core.py` 以 `CoreRouteDeps` 承载 40 条核心路由与 131 个闭包依赖，`build_router` 只负责装配与 include；`router_support.py` 承载 19 个模块级助手；`context_budget.py`/`model_catalog.py` 以 mixin 形式承载预算与模型目录方法。`App.tsx` 的 177 个模块级声明移入 `appHelpers.tsx`，源码守卫测试改为读取「逻辑模块合并源」。

### 9.5 本轮验证

| 项目 | 结果 |
|---|---|
| 全量 server pytest | **3682 passed, 0 failed**（默认 8 worker 与 4 worker 各跑一轮） |
| extension node:test | **2232 passed, 0 failed** |
| `npm run check`（CSS 分区 + webview tsc + extension tsc） | 通过 |
| `npm run build`（webview + extension） | 通过 |
| `npm run check --prefix extension/webview` | 通过 |
| ruff 0.15.18 / pyright 1.1.410（CI 锁定版） | 通过 / 0 errors |
| bundled 镜像逐字节一致 | 通过 |
| 预览体验矩阵 | **200/200 passed** |
| webview recovery 验证 | 通过 |

### 9.6 仍存的结构性风险（明确排期）

1. **剩余深层拆分**：`routers.py` 仍有 14.2k 行 helper 闭包（路由已全部移出，build_router 只装配）；`provider_service.py` 仍是 7.5k 行类（协议/流式/重试尚未抽出）；`App.tsx` 仍是 11.6k 行组件体（render/effects 尚未拆）。路由层与四类稳定接缝已落地；剩余部分需要独立 UI/协议回归窗口——这与 §8.4 的判断一致。
2. **同文件内测试顺序依赖**：套件仍以 `--dist loadfile` 运行，文件内 create→assert 序列是既有契约；本轮用默认 8 worker 与 4 worker 各跑一轮全量（均 3682 通过），验证了跨 worker/文件分配无耦合；新增测试仍应自建状态（§8.4 第 5 条保持）。
3. **Windows/CI**：本轮未推送，未重跑云端三平台矩阵；本地验证以 macOS 为准。
