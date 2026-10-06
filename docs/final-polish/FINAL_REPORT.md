# FINAL_REPORT — trainer 收口交付（final-polish）

日期：2026-10-07 · 本版为响应独立读者反馈的修订版：补术语定义、证据限制声明、Progress 信息流、发布风险汇总与下一步行动；事实未变。

## 0. 阅读指南：角色、轮次、术语、数据源
**角色**（文中「××实跑」=该角色亲自执行命令并记录输出）
- **审计**：收口前四领域（product/visual/arch/platform）只读审计的执行者。
- **规划员**：收口前负责现状综合与三轮计划的子代理（撰写 docs/final-polish/CURRENT_PRODUCT_TRUTH.md 与修复计划）。
- **批判**：三轮批判循环的独立审查者，每轮产出 improved/worsened/newComplexity/deletable/focusNext 清单与 structuralProblem 判定。
- **编排**：运行验证门并汇总门数据的工作流脚本；「门记录」即其输出（每门为 ok 布尔 + repairs 计数）。

**轮次**：R1/R2/R3 = 三轮「收口轮」，每轮 = 四领域并行修复 + 验证门 + 批判记录；§9 门清单史与 §10 截图审查用的是同一套 R1-R3。R3 之后另有「最终」验证门（五门）与最终金图审查，都运行在冻结树上。

**术语**
- **金图**：金标准截图（验收基准图），12 张存于 assets/screenshots/（完整清单见 §10）；**冻结树**：代码冻结后的工作树（HEAD a45c9cc555a0）；**重摄**：用 scripts/capture-ui-golden.mjs 重新截图。
- **governed direct send**：「开始：X」（恢复当前学习步骤）与 clear_blocker（清除学习阻塞器）两个恢复链按钮点击后，由前端代发的合成 coach 消息。与普通 composer 发送的区别：文本与载荷由代码构造、不经用户编辑，且携带 planRuntimeRecovery 治理载荷（服务端 persist_plan_runtime_recovery 落库供学习恢复状态回读，server/app/api/routers.py:16465）——改成普通预填会丢失载荷、断恢复闭环，故保留为例外；「唯一事实源」指该例外的说明只写在 App.tsx:13362-13364 注释里。
- **admission / reconciliation / epoch-0**：admission=工作区接管确认面板（WorkspaceAdmissionPanel，工作区尚未被 Trainer 确认接管时的阻塞 UI）；reconciliation=该面板展示的工作区后台核对状态（reason/state 字段）；「epoch-0 不渲染时间」=核对时间为初始纪元值时不渲染时间字符串，避免显示无意义的 1970 时间戳。
- **presence bar**：composer 上方的常驻状态条；provider 发送被阻塞时显示为可点击的 blocked 按钮（App.tsx:14363-14401）。
- **ghost / accent / 芯片**：ghost=无实底、仅描边与文字的次级按钮样式；accent=主题强调色 token（--accent）；芯片=小圆角标签状元素（如供应商卡内的模型名胶囊）。
- **wait 态**：plan 恢复主按钮策略的分支之一（recoveredPlanPrimary="wait"，App.tsx:13284）——等待学习者完成当前步，此时主按钮即「开始：X」。
- **L1**：Remote-SSH 真实 sshd e2e 的基础层级（真实 sshd 上的最小连接/文件回路）；分级体系全貌未在材料中出现，仅见 L1 一级。
- **structuralProblem**：批判记录的结构化判定字段；true=该轮存在无法在轮内消化的结构性问题，false=无。R1=true（test:extension 红门带病合入），R2/R3=false；§12 的 rc 判据引用 R3=false。
- **repairs**：门记录中「该门通过前的修复次数」计数字段。其机制定义（自动修复还是人工修复、由谁审查）**未在提供的材料中给出**——本报告只能报告计数与「无留痕」事实（§11-10），机制说明为诚实限制。
- **deletable 清单**：每轮批判维护的「可删除物」清单（零引用死代码/死文案候选）。
- **i18nCopyCompleteness 反锚守卫**：extension/tests 中的守卫测试，防止已删除的死键被重新写回 copy.ts（「反锚」=防回流）。
- **provider 4 副本**：provider 配置事实在 webview 的四份存放——store 的 data.providerConfig、data.connection.provider、持久化 layout.previewProviderConfig、App 本地 providerDraft。
- **防静默重置**：设置保存逻辑防止 customSkills 字段被空值/默认值无意覆盖清空（server/app/memory/service.py:1805-1833）。
- **「第一幕」注释**：coach-conversation-view.css 里以「第一幕/第二幕」叙事比喻写的设计注释；旧「第一幕」段为已被锚底方案取代的顶对齐布局辩护。
- **冷启动「5 层叠加」**：收敛前冷启动首屏同时存在多个接管层（向导、工作区接管面、provider 提示等）的审计记法；逐层清单存于首轮审计、未随本报告材料入库（限制）。收敛后 Coach 根视图仅向导一个接管面（App.tsx:12241-12260，admission 分支互斥）。

**数据源与限制**：①三轮门记录（含最终门）②最终金图审查 ③三轮批判记录 ④docs/final-polish/CURRENT_PRODUCT_TRUTH.md。①②③由编排流程随任务提供，**未发现入库文件**（实查 `ls docs/ docs/final-polish docs/verification`：仅有 truth 文档、perf 基线与两份更早的验收文档），故「批判实跑/审查记录在案」类引用无法给出 repo 路径，只能标注来源角色——限制。门与 HEAD 的对应：材料声明代码冻结于 a45c9cc555a0、最终门标注为「最终」、最终金图审查确认冻结树重摄与验收态字节一致（md5 diff 为空），据此判断门运行于冻结状态；但门记录不含原始输出与执行时间戳，**无法逐门钉到该 commit**——限制。门结果只有 ok 布尔与 repairs 计数，无命令输出可引——限制。

## 1. HEAD 与状态
- HEAD：`a45c9cc555a0`（refine: 最终收口 — 金标准截图与最终代码状态）〔实查：git rev-parse/log〕
- 分支：`product-final-polish`，工作树干净，未推送（无 upstream：`git rev-parse @{u}` → fatal: no upstream configured）〔实查〕。合并 main 计划与目标版本号未在材料中确定（见 §13 下一步）。

## 2. 核心修改（按领域）
**product（组件与文案）**
- 首装语域改写：plan 证据句改「正式计划会等你亲手验证后再更新」×8 语言（CoachPlanView.tsx:313-871 实测齐）；训练卡阶段标题改教练式问句「做完这一步，验证一下结果」（TrainingWorkbenchView.tsx:714-749 本地文案表 ×8、:2805/:2811 接线），标题与按钮动词解耦。
- admission 面板 reconciliation 枚举映射本地化+未知值回退+epoch-0 不渲染时间（语义见 §0；WorkspaceAdmissionPanel.tsx:111-139）；AppShell 品牌/工作区同名去重（AppShell.tsx:31-33）。
- plan 主按钮对齐学习者主语：证据态「我做完这步了，整理证据」（App.tsx:13253-13258 + copy.ts:421,642）；「开始：X」文案迁 appUiCopy ×8 修复源码守卫红门（App.tsx:13302-13305）。
- 首屏恢复行「继续」从裸文本链改有框 ghost 按钮（App.tsx:12229-1240）；chat 恢复行迁入消息列表实现锚底（App.tsx:12221-12241/:11938，CoachConversationView.tsx:41/71/151 插槽）。
- settings：保存动作改「保存并使用此连接」×8（CoachSettingsView.tsx:940-996）；accent 归位（ready 态「重新测试」降 ghost、保存禁用、芯片左对齐；:6294/:7329 + SystemState actionTone 向后兼容）。
- viewLabels es/fr/de 的「学习=Plan」命名：**关闭而非修复**——成本端有实证（3 个 e2e spec 断言 Plan 标签，改名需同步改测试：trainer-locales.spec.js:14-17 等）；「收益不抵成本」是批判轮的判断，本报告不对其收益侧做独立论证。
- progress 斜体重复句 transferNudge 删净（全仓 grep 0 残留）。

**visual（样式/门/金图）**
- 主按钮实底 accent 与次级灰底分离（training.png 实证主次可辨）。
- 几何门规则 1 由假绿变真门：此前选择器 `.coach-training-resume` 恒返回 null、断言容忍 null（连续两轮假绿）；现改 `[data-coach-training-resume]`、断言 fail-closed（`!== null &&`）、新增 bottomGap≤24 贴底探针（verify-ui-geometry.mjs:244-259/:272-281/MAX_BOTTOM_GAP=24 :57）。
- $ 面板防遮挡守卫（coach-conversation-view.css:286-290 `:has()`）+ palette 打开时线程锚底联动；死 CSS（.notice 双文件）删除；.template-back 焦点圈、spinner primitive 守卫钉到新不变量。

**arch（App.tsx/store/结构）**
- operationMessageGovernance.ts：279 行纯函数模块，仅 import 两个类型、无 React/store 依赖（操作消息解析/surface 归位从 App.tsx 抽出），node --test 14 pass 0 fail（批判实跑）；App.tsx 侧留薄适配。
- 冷启动「5 层叠加」（见 §0）收敛为单接管面：向导优先、admission 分支互斥（App.tsx:12241-12260）。
- 「下一任务」改预填不发送（App.tsx:13365-13371）；「开始：X」恢复链保留 governed direct send（见 §0）并注释固化（App.tsx:8868-8891/:13362-13364）。
- 死代码删除：10 个零引用组件（约 2,478 行）+ shared/src/motivation.ts + icons/trainerIndex.ts barrel + LearningNavIcon/NavProgressIcon。
- composer 草稿「内存即时/持久化防抖 500ms」时序不变量（e2e 草稿恢复断言兜底）；perf-probe 三件套接线（见 §7）。

**platform（extension commands/server/shared）**
- attest 幂等闭环：marker 协议（trainingAttestation.ts:25）、idempotency_key 下发（:81/:193）、not_arrived/ambiguous 失败分类与单次重发；端点级重放测试 server/tests/test_attestation_idempotency_endpoint.py。
- 协议入文档：AGENTS.md:388 记 marker 字符串、失败分类语义、幂等键格式 remote-verify:{runId}:{cardId}、server 端 latest_training_reliability 单槽顶替边界、fail-closed 声明。
- 远程验证摘要 8 语言本地化 + en-US 病句修复：原文「Verified passed (exit {exit})」（R2 批判指认）→ 修为「Verification passed (exit {exit})」（remoteVerificationCommands.ts:223，本会话实读确认）。
- 训练卡 scenario pack 学习者语域 pass（guided_training_scenario_packs.json 7 处 + problemStatement :331/:374 同卡收尾，training.png 整卡统一）。

## 3. 复杂度：删了什么 / 新增了什么
**删除**：R2 单轮实测 33 文件 +267/−1,743（批判 git diff --stat）；**R1/R3 的净行数未在材料中，「收口期持续负增长」仅有 R2 一个样本支撑，不外推整期趋势**。copy.ts 5,284→3,794 行（死键清扫：capability/streak/greeting/learningHomeDueTitle/masteryLevel 族；动态构键风险已排查——全仓唯一 `as CopyKey` 在 useTranslation.ts:11 查询机制本身）+ i18nCopyCompleteness 反锚守卫（:217，见 §0）。死物：10 个零引用组件、motivation.ts、trainerIndex.ts、.notice 死 CSS、saveAndUse(model)、transferNudge——三轮后 deletable 清单（见 §0）首次清空。交互：冷启动叠加层→单接管面；provider 双提示→presence bar 单提示；「验证当前文件」三现解耦；settings 模型名 4→3；progress 同义重复句删除。
**新增（真正必要）**：锚底 5 件耦合簇（DOM listHead + margin-top:auto + `:has()` 守卫 + 门两断言 + palette 规则，跨 4 文件）——chat 死区修复的必要代价，规则 1 已 fail-closed 缓解；`:has()` 行为性选择器首次入库（coach-conversation-view.css:286-290），CSS 约定尚未记载该模式的目标限定（VS Code webview 为 Chromium 内核，版本下限未核，见 §13）；i18n 文案机制 4 套并存（copy.ts/appUiCopy.ts/组件本地表/宿主本地表 REMOTE_VERIFICATION_SUMMARY_COPY），≥20 文件各有文案表——「新键放哪」认知税上升，双机制合并两轮共识「记账不动」；perf-probe 基线 JSON 机器/负载敏感（已立重拍纪律，AGENTS.md:470-481，属长期维护承诺）；SystemState actionTone 使主按钮权重有 prop+CSS 双来源；attest marker 协议横跨 4 文件（已入 AGENTS.md:388，证据诚实的必要复杂度）；settings ready 态无 enabled 主按钮是「无待办」的诚实语义，记录防后续误修。

## 4. 各 Surface 最终信息流（六路由全覆盖）
- **Coach（对话）**：首屏在一个视觉组内回答首用三问——我在哪=对话、在做什么=「正在进行：X」恢复行、下一步=有框 ghost「继续」钮（App.tsx:12229-1240）；恢复行与消息组锚定在输入框正上方，死区移到顶部（聊天惯例空位）。唯一阻塞表达：provider 阻塞走 presence bar 单提示；冷启动只有向导一个接管面。次级信息收在消息级 evidence 折叠与 composer「···」菜单。
- **Learning（学习首页）**：当前学习/段次/下一步/完成标准层级 + 唯一 accent 主按钮，且与下一步文本同主语（wait 态「开始：X」对准下一步；证据态「我做完这步了，整理证据」）。次级动作全部收进「详情」折叠。遗留：六个同外观折叠行竖排、底部约 35% 空白。
- **Training（学习→专注练习）**：单卡 FocusedPractice，主 CTA「验证当前文件」实底 accent 与「提示 1/3」灰底分层；阶段标题为教练式问句，完成标准四条全学习者语域。卡外仅「任务详情」折叠，终态留在卡上；恢复链 governed direct send 例外（§0）。
- **Progress（学习→成长）**：GrowthEvidence 模板——四维能力（理解/实现/调试/迁移）状态行 + 可展开明细 + 全页唯一 accent CTA（迁移验证或去练习）；R3 删除了与按钮同义重复的斜体句，现在表格后直接是按钮。遗留：底部约 50% 空白。
- **Library（资料）**：hero 搜索 + 添加菜单 + 分组树 + 列表，单击进 reader（Ask Coach/加入学习/生成练习 + 返回）。遗留：路径式分组名、底部约 55% 空白。
- **Settings（header 齿轮）**：Index（4 类+一句话状态）→Detail 深链；编辑层 accent 归位（ready 态重测 ghost、保存禁用=诚实「无待办」、芯片左对齐），保存动作已去模型名。遗留：模型名同屏 3 处、connected 金图 fixture 混装、底部约 70% 空白。

## 5. Skill / Remote SSH 最终模型
- **Skill**：「本地展开」模型未变——自定义技能存 coachDefaults.customSkills（带防静默重置保护，见 §0），composer $trigger 匹配后本地替换为 prompt 随用户消息发送（App.tsx:9502-9522）；server/app/llm 仍无 custom_skills 消费者，教练后续轮次无法感知技能定义（注入属功能增强，维持 deferred，不在收口范围）。本轮只修呈现层：$ 面板防遮挡守卫与 palette 锚底联动，skill-deck.png 两态目检正确，R1 时的底部裁切缺陷已消失。
- **Remote SSH**：本地 Brain + 远端 Hands 心智模型保持：身份/记忆/计划/证据留本地 UI 宿主，远端文件操作经 Companion 命令桥（trainer.remote.capabilities/request）。**凭据边界**：AGENTS.md:512「Provider API keys always live in the local UI host's SecretStorage (ui_proxy); the remote Companion never receives credentials」（repo 内权威声明；本会话未做独立的传输层抓包验证）。异常语义 fail-closed 并在本轮补齐证据侧：远程验证中断/连接丢失永不产生训练证据；attestation 有 marker 协议 + not_arrived/ambiguous 失败分类 + 幂等键 remote-verify:{runId}:{cardId}（防「已到达仅响应丢失→重发双记」），单槽顶替边界入 AGENTS.md:388；摘要 8 语言（remoteVerificationCommands.ts:223）。边界：真实 sshd L1 e2e 仅 Linux CI，本机未实证传输层。

## 6. Controller 架构变化
拆了第①步：operationMessageGovernance 纯模块（279 行纯函数，组件侧薄适配），把操作消息解析/surface 归位从 App.tsx 模块层抽出并配 node:test 行为测试（批判实跑 14 pass 0 fail）。边界：App.tsx 仍是单文件编排器（全量订阅 store、surface 无 memo 结构本轮未动）；新增两个需知晓契约——governed direct send 例外（§0）与草稿防抖 500ms 时序不变量。下一步（deferred）：②useProviderConnectionController（含 provider 4 副本收敛，见 §0）→③training→④plan→⑤conversation controller、surface memo+selector 化、几何门「探针必须命中」元断言制度化（见 §11-9）。

## 7. 性能 profiling
- 方法：headless Chromium + preview 通道，经 window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__ 注入 300 条消息 bootstrap 与 300×100 字符@4ms 合成流式；度量导航延迟（点击→data-surface 取消 hidden）、longtask(>50ms) 计数、5-surface 全保活 vs 仅 coach 两配置。
- **入库基线**（docs/verification/perf-probe-baseline.json，generatedAt 2026-10-06T18:34Z，本会话实读）：warm 导航 p90 逐 surface = plan 37 / resources 36 / training 12 / settings 36 ms（n=3 采样），对比预算 100ms → pass；流式 longtask 观测 0 vs 预算 0 → pass；流中导航 7ms；5-surface 与仅 coach 的隐藏面开销差 = 0（longtaskDelta 0）。冷启动首访逐 surface 15-83ms。
- **审计基线实测**（收口前 arch 审计会话的一次性测量，未入库，方法与本轮探针相同）：300 消息会话导航 warm p50 22-72ms——**是一个区间，因为跨多路由/多配置采样汇总**（材料未给逐 surface 细分，限制）；流式 0 个 long task、流中导航 23ms。
- 纪律：AGENTS.md:470-481——UI 几何/表面结构变更后重拍基线；--strict 明确不进 verify 矩阵（单机样本 <20% 差异视为噪声）。
- 测不了/未测：真实 provider 流式（合成 chunk 经 store 路径注入）、longtask 50ms 地板以下的逐 chunk 成本、Windows/低配环境；结论是「当前规模无卡顿证据」而非「结构免费」（headless、单机单样本）。

## 8. 跨平台结果
- 本机（macOS）已验证（含实跑者）：Companion `tsc -p remote-extension/tsconfig.json --noEmit` 退出码 0（规划员实跑）、`build:remote-companion` 退出码 0（审计实跑）。最终门 npm run check / test:extension / test:server 三门绿——**来源为编排门数据（ok 布尔），本会话未实跑这三个套件（纪律禁止），且无原始输出（见 §0 限制）**。
- fixture 审查：信息流报告的两个 Windows 红灯已修复（workspaceContext F:\ opaque 4/4、remoteCompanionBridge 3/3 本机过）；darwin simulation 的 SIM_ROOT=/tmp/... 为真实触 fs fixture（trainerWorkspaceServiceDarwinSimulation.test.js:55/:167-168），按 os.tmpdir() 类处置——该修复结果无批判记录逐项佐证，如实标注未复核。
- 未跑：Windows/Linux 实机（本机 macOS）；真实 sshd L1 e2e 仅 Linux CI 生效（scripts/run-remote-ssh-e2e.mjs:36-37），远程传输层真实性本机无法实证。Windows 行为维持「未证伪」而非「已验证」。

## 9. 体验矩阵结果
硬校验恰 200 场景（e2e/trainer-experience-matrix.js:700 `SCENARIOS.length !== 200`）。最终门 npm run test:experience-matrix **ok:true（repairs:1）**。
**repairs 机制说明（限制）**：repairs 是门记录中的修复计数字段，表明该门在报告 ok:true 之前经历过 N 次修复往返；修复内容是自动修复还是人工修复、由谁审查，材料未定义，三轮均无留痕——读者应把「repairs>0 的绿门」视为「通过但变更链不透明」（§11-10）。
**门清单史与 R1 红门事件链还原**：R1 的 test:extension 门失败（repairs:2 未能修绿）但该轮代码仍合入——这就是「红门跨轮携带」；R2 批判实锤定位到 App.tsx:13299-13300 的内联中英三元式违反 planViewLocaleSource 守卫（3 个失败测试）→ R2 轮内修复（「开始：X」迁 appUiCopy ×8）并经批判实跑 10 pass/0 fail 确认。R2 门清单缺 test:extension/experience-matrix（编排层选择问题——npm run verify 内本就含 test:extension，verify-workspace.mjs:74）；R3 test:extension 回归清单且绿（repairs:1）；最终五门（check/test:extension/test:server/experience-matrix/verify）全绿。

## 10. 截图审查结果（三轮演变）
**金图清单**：12 张，全部位于 assets/screenshots/：chat-first-run、coach-narrow、plan、training、resources、progress、settings-connected、settings-quick-setup、skill-manager、skill-deck、message-actions、message-actions-row（均为 zh-CN dark 420×900@2x）。
R1→R2：chat 死区（当时头号 medium）催生锚底方案；「继续」钮可供性、plan 主按钮同主语、settings accent 归位、训练卡语域统一依次落地。R2→R3：几何门假绿史终结（选择器+fail-closed+bottomGap，见 §2），chat 首屏 2 秒三问首次全部可答；progress 斜体句删净、settings 模型名 4→3、en-US 病句修复。最终冻结树重摄 12/12 成功且与上一轮验收态字节级一致（md5 diff 为空）——锚底、防遮挡守卫、accent 归位、主按钮分离等修复稳定生效，无新回归。遗留 6 条 low/medium（§11 前六条）。

## 11. 剩余技术债（恰 12 条，为设定上限；每条带建议处理时序。「独立复核」阶段返回空，verified 均指批判轮/最终金图审查记录在案的一手检查，无第三方复核轮）
| # | where | what | status | severity | evidence | 建议时序 |
|---|---|---|---|---|---|---|
| 1 | assets/screenshots/plan|resources|progress|settings-connected 底部 | 四面死区：≈35%/55%/50%/70%（chat 已锚底） | verified | medium | 最终金图审查逐张目检：内容贴顶结束于 y≈700-1340，下方纯背景 | **rc 后尽快**（chat 配方已定型可复制） |
| 2 | plan.png（y≈800-1340） | 六个同外观折叠行竖排、「更多」语义空 | verified | low | 最终金图审查；与上轮 md5 字节一致；连续三轮 low | 下轮排期 |
| 3 | settings-quick-setup.png（y≈920/1400/1655） | 模型名同屏 3 处（芯片/下拉/meta 行；保存按钮 4→3 已落地） | verified | low | 最终金图审查坐标 | 下轮排期（small） |
| 4 | settings-connected.png（y≈420-520） | fixture 混装：未信任警告占首屏主位，连接成功仅一行芯片 | verified | low | 最终金图审查 vs y≈640-710 连接状态行 | 下轮排期（small） |
| 5 | chat-first-run.png（输入框下 y≈1730） | composer 两图标按钮无文字标识；title/aria-label 是否齐全未核（本轮无 a11y 专项维度） | unconfirmed | low | 最终金图审查目检；aria 状态无一手检查记录 | 与 a11y 核查合并（§13 风险 4） |
| 6 | resources.png（y≈390-620） | 路径式分组名「Docs / Coach / Patterns」 | verified | low | 最终金图审查；browserPreviewHarness fixture 数据驱动 | 下轮排期（small） |
| 7 | coach-conversation-view.css:262-268 | 旧「第一幕」注释（见 §0）仍为顶对齐辩护，与锚底决定矛盾 | verified | low | R3 批判读码引述原文 | **rc 后尽快**（一行改写） |
| 8 | verify-ui-geometry.mjs:329-334 + coach-conversation-view.css:286-290 | palette 门规则语义放宽未经 platform 追认；`:has()` 行为性选择器未记入 CSS 约定 | verified | low | R3 批判读码确认追认未完成 | **rc 后尽快**（注释/文档级） |
| 9 | verify-ui-geometry.mjs（除规则 1 外约 15 个 check()） | 「探针必须命中」元断言未制度化，探针仍 null 容忍，假绿温床未根除 | unconfirmed | medium | R3 批判转述 platform 自提未排期；仅规则 1 已 fail-closed（:254-259）；15 个 check 逐个状态无一手复核 | **rc 后尽快启动**（门体系健康） |
| 10 | 门记录（最终 experience-matrix/verify 各 repairs:1；R3 test:extension repairs:1） | 修复无留痕不可追溯（机制定义亦缺失，见 §0/§9） | verified | low | 门数据 repairs 字段 + R3 批判「无从追溯」 | 随编排流程改进（下次运行生效） |
| 11 | copy.ts + appUiCopy.ts + 各组件/宿主本地文案表 | i18n 文案机制 4 套并存（≥20 文件各有文案表），新键无单一去处规则 | verified | low | R1 批判 grep 实测；R2/R3 共识「记账不动」 | 长期搁置（大动作需统筹） |
| 12 | 编排层门清单（对比三轮门记录） | 门清单逐轮选择：R2/R3 曾缺 test:extension/experience-matrix，最终门恢复五门 | verified | low | 三轮门记录对比；verify-workspace.mjs:74（R3 批判实读） | 随编排流程改进 |

## 12. Release Candidate 判定
**verdict = rc**。
- **判据（本轮收口任务的既定标准）**：最终验证门全绿 且 无结构性问题遗留（structuralProblem）。现状：五门 ok:true〔编排门数据，无原始输出可引——§0 限制〕；R3 structuralProblem=false（R1 的 true——红门带病合入——已在 R2 修复、R3/最终门确认闭环）。
- **两个 medium 遗留为何不阻塞**：#1 四面死区是观感/密度债且修复配方已在 chat 面验证定型；#9 元断言缺失是门体系增强项而非产品缺陷（规则 1 已 fail-closed，门仍在真实测量）。二者均不触及功能正确性与证据诚实性。
- **降级条件（何时回退 not-rc）**：任何最终门转红；出现新的跨轮结构性问题（structuralProblem=true）；或发布决策要求 Windows/真实 provider/sshd 覆盖而 §13 风险未先行处置。
- **判据未覆盖的维度**：a11y（本轮无专项审查，rc 不含 a11y 结论）、真实 provider/sshd/Windows 运行时验证（§13）——rc 表示「按本轮判据可进入发布流程」，不等于「所有维度已验证」。

## 13. 发布前风险汇总与下一步行动
**风险清单（「还有什么会咬我」，按优先级）**
1. **Windows 实机零验证**（最高）：vsix 面向 Windows 用户而全部验证在 macOS；建议正式发布前 Windows 实机冒烟（安装→sidecar 启动→一轮 coach 对话）。
2. **真实 provider 流未测**：探针用合成 chunk；流中 crash/401/429 中段仅有单点 pytest，无跨层 e2e。
3. **sshd 传输层未实证**：L1 e2e 仅 Linux CI（§0）。
4. **a11y 无专项结论**：唯一涉及点是 §11-5 且未核。
5. **`:has()` 兼容目标**：依赖 webview Chromium 支持，版本下限未核（coach-conversation-view.css:286-290）。
6. **repairs 无留痕**：三处自动计数的修复未经独立审查记录（§11-10）。
7. **交付物状态未覆盖**：npm run verify 已绿（发布校验矩阵），但 verify:delivery / package:vsix **未出现在最终门清单**，vsix 打包状态未知；bundled sidecar 与 HEAD 的同步状态材料未覆盖——发布前必须补。
**下一步（建议，非材料事实）**：①推送分支并开 PR 合入 main（当前无 upstream）；②跑 `npm run verify:delivery`（= verify + experience matrix + package）补齐打包验证并确认 bundled 同步；③目标版本号决策（当前发布 v1.3.4，本次 rc 对应版本未在材料中确定）；④逐项处置 §13 风险后再正式发布。
