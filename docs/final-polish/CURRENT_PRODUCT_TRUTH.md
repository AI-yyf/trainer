# CURRENT_PRODUCT_TRUTH — final-polish 收口基线

生成：2026-10-07 · 分支 product-final-polish · v1.3.4。本文由 product / visual / arch / platform 四领域只读审计收敛而成，是收口计划的唯一现状依据。背景：docs/information-flow-report.md、docs/information-flow-audit.md。证据为 path:line（webview 根 = extension/webview/src）；标注〔复核〕的条目为规划员本会话实跑命令二次确认，其余为审计员实读/实测记录。完整验证套件由编排脚本统一运行，本文不重复。

## 产品现状
- 三目的地 shell：品牌行 + History/Settings 双 utility + 对话/学习/资料导航（templates/AppShell.tsx:29-53，标签 lib/viewLabels.ts:17）；六路由→目的地映射唯一定义于 lib/workbenchDestinations.ts:9-17（training/progress→学习，settings→header），ownsCoachComposer 限定 composer 只在 coach（同文件:19-20）。单一 webview view + 65 命令〔复核：python3 解析 extension/package.json → commands:65、views: trainer.sidebar〕。
- Coach 阻塞面单一仲裁：resolveCoachBlockingSurface〔复核：App.tsx:1613〕，workspace-admission > provider-setup > provider-notice > recovering，同一结果驱动 pane 与 composer presence 条（App.tsx:8816-8831）。
- 操作消息原子归位：setOperationMessage〔复核：App.tsx:4043〕(消息, surface)，非 error 5 秒自清（App.tsx:5852-5858）；但 77 个调用点仅约 9 个显式 scoped，provider/settings 域默认 global，错误仍会出现在无关表面（信息流报告 §9③ 记录为有意保留的债务）。
- 「发送权在用户」基本落地：suggested actions/artifact 一律预填草稿+聚焦、不发送（App.tsx:9387-9444）；两处 sendTurn 直发〔复核：App.tsx:9030、13516〕性质不同：「下一任务」是普通 intent 合成消息（可安全改预填）；「开始：X」计划恢复直发携带 buildRecoveredPlanResumeTurn 的 planRuntimeRecovery 治理载荷（App.tsx:9016-9039，经 handlePlanOrientationAction("continue_step") 触发：App.tsx:6876-6877、13455〔复核〕），服务端 persist_plan_runtime_recovery 落库供 Learning 恢复状态回读（server/app/api/routers.py:11187-11192,16465〔复核〕），改预填将断恢复闭环——保留为治理例外，其形态被 extension/tests/planGovernanceActionsSource.test.js:355-356 逐字锁定〔复核〕。
- 训练终态留在卡上：continued_in_chat 显示「已完成」区块（TrainingWorkbenchView.tsx:2665,2772-2779），「回到对话」由用户点击触发（App.tsx:13088-13091→10486-10526）；未发现自动跳转/抢焦点路径。
- 死代码层：2,478 行零引用组件+copy（QuickActions/HumanizedEmptyStates/CoachGuidance/CoachActionPill/MemoryLayerSummary/WorkspaceAuthorityFacts 及 3 个 copy 模块）〔复核：wc -l 合计 2478；精确符号 grep 全仓库 0 消费者，唯一外部引用是 components/common/index.ts barrel；App.tsx:5084 blockedCoachGuidance 为局部变量名、非组件引用〕；copy.ts 术语死键（planDashboardReviewTitle:993、trainingHandoffMismatchHint:1000、resourcesSandboxLedger:1527 等，tsx 零渲染引用〔复核〕，且残留在 CopyKey 联合类型 632/769/778）。

## 一级入口
- 恰好 3 个导航按钮 + 2 个 header utility，无第四入口（AppShell.tsx:35-52）；导航为纯文字 tab，无品牌图标。
- 两处稀释一级注意力的重复：①冷启动 root-missing 时 OnboardingWizard 与 WorkspaceAdmissionPanel 同屏叠放、两个模块同时要求「选择工作区根目录」（App.tsx:12389-12392〔复核：两渲染分支条件可同时为真〕）；②provider-send-blocked 时 Coach 同屏两处同源提示：pane 顶 coach-inline-notice（App.tsx:12404-12413〔复核〕）+ composer presence bar blocked 按钮（App.tsx:14363-14401），同条件同动作（均跳 Settings Connection）。

## 各 Surface 首屏
- 冷启动：3 步梯子 workspace_root→trust_window→connect_model〔复核：shared/src/onboarding.ts:11,40-42〕，仅真冷启动触发（App.tsx:11770-11772），完成即自动消失。
- Coach：训练恢复一行 + 至多一个阻塞面 + 会话流 + composer（App.tsx:12377-12413）；首聊空态「你在做什么？」+3 个 starter，只预填不发送（App.tsx:11953-11979）。
- Learning：LearningHome = 标题+阶段+状态条+唯一 NextAction+4 个默认关闭折叠（templates/LearningHome.tsx:19-32）；次级动作收进「详情」折叠（CoachPlanView.tsx:1977-1993）；头部 goalSummary 不复制 nextStep 文案（App.tsx:13340-13343）。
- Training：单卡 FocusedPractice（App.tsx:13086 cardOnly=true），面包屑父级「学习」（TrainingWorkbenchView.tsx:2762-2768），卡外仅一个默认关闭「任务详情」折叠、无第二 composer（同文件:2681-2698）。
- Resources：hero 搜索+添加菜单+列表（ResourcesWorkbenchView.tsx:2642-2784）；reader 提供 Ask Coach/加入学习/生成练习 + 返回（同文件:3011-3025）。
- Settings：Index（4 类+一句话状态）→Detail；7 处深链全部先 requestSettingsCategory（App.tsx:4029 等），已配置连接直接落 Connection 详情（CoachSettingsView.tsx:4190-4193）。
- Progress：GrowthEvidence 四维（理解/实现/调试/迁移）状态行+全页唯一 accent（ProgressView.tsx:343-430）。
- 隐藏表面保活：路由切换只切 hidden 不卸载（app/WorkbenchSurfaces.tsx:9-15〔复核：文件位于 app/ 目录〕），导航不丢状态。

## 闭环与断点
- 七条主链路（本地工作区/Remote SSH/Provider/Skill/资源/计划/训练）当前代码全部成环（platform 审计逐链核实）；sidecar 启动 5 级候选链 + 随机实例 token 强制校验 + 健康探测 miss 不误重启（sidecarProcessManager.ts:721-784,269-281,398-399；server/app/main.py:117-132）。
- 证据诚实链路真实：客户端证据强制 self_reported（server/app/api/routes/training_attempts.py:176）；host 信任证据仅 7 白名单 source 走 /training/verification/attest（server/app/api/routes/learning.py:158-179）；删除资料按 TR-076 标记、同哈希重建清除（server/app/training/attempt_store.py:364-420）；远程验证连接丢失永不产生证据（extension/src/commands/remoteVerificationCommands.ts:103-116,266）；计划乐观锁 expected_revision 必带 + 409 八语言冲突文案（sessionCommands.ts:3034-3038；App.tsx:602-626）。
- 断点①（high）：attestation fire-and-forget——sidecar 恰好不可用时训练证据静默丢失（docblock 自认 swallowed、日志只记 error.name）而 UI 已显示「已验证通过」〔复核：extension/src/testing/trainingAttestation.ts:176-197〕；调用点 remoteVerificationCommands.ts:145,275。
- 断点②：自定义 Skill 只在 composer 前端展开（App.tsx:9502-9522），server/app/llm 零消费者（仅 models.py:2489 字段定义）。
- 断点③：VS Code 硬崩溃残留 sidecar 孤儿进程无清理无提示，固定端口被占时静默回退（extension/src/extension.ts:503-509；sidecarProcessManager.ts:522-533）。
- i18n 破口：WorkspaceAdmissionPanel 裸渲染 reconciliation.reason/state + 两句硬编码英文〔复核：WorkspaceAdmissionPanel.tsx:136-138〕；资源→训练失败文案仅 zh/en，其余 6 语言空表回退英文〔复核：ResourcesWorkbenchView.tsx:933-938〕。

## 测试与平台现状
- node:test 实测 238 文件 / 1,807 test()〔复核：ls|wc -l 与 grep -c 求和〕= 104 个源码文本守卫文件（428 测试）+ 134 个行为测试文件（1,349 测试）；AGENTS.md:92 写 215 已漂移。本机抽查 remoteCompanionBridge 3/3、sidecarProcessManager 19/19、workspaceContext 4/4 通过（platform 审计实跑）。
- 源码守卫锁定关键实现形态：planGovernanceActionsSource.test.js:355-356（恢复 sendTurn 载荷形态）、coachProviderSetupSource.test.js:148,153,172（阻塞仲裁、composer notice 开关与 pane 顶 notice 分支）、operationMessageSurfaceScopingSource.test.js（OperationMessage/scoping 在 App.tsx 内的形状）〔复核：三文件存在、关键断言命中〕——改动对应行为必须同步更新守卫，否则 test:extension 红灯。
- e2e 体验矩阵硬校验恰 200 场景〔复核：e2e/trainer-experience-matrix.js:700 `SCENARIOS.length !== 200`〕，全部运行在 browser-preview fixture 层；真实 sidecar 端到端仅 1 条 authored journey（server/tests/test_real_sidecar_experience_matrix.py:273）；异常恢复组合（流中 crash、401/429 中段、409 并发、断线重连）无真服务端对应物。
- Remote-SSH L1 e2e 仅 Linux CI 生效（scripts/run-remote-ssh-e2e.mjs:36-37），macOS 开发机恒 SKIP；约 12 处 POSIX 风格 /tmp fixture 抽读均为不触 fs 的 opaque 值（Windows 实机未验证，非缺陷断言）。
- Remote Companion：tsc --noEmit 退出码 0〔复核：本会话实跑〕；build:remote-companion 退出码 0 且构建后工作树干净（platform 审计实跑）。
- geometry 门（scripts/verify-ui-geometry.mjs 规则 1-8）锁三目的地稳定/composer 归属唯一/主按钮≤1/横向溢出≤1px；无人钉住的缺口：无垂直密度断言（首屏 93-98% 纯背景照样全绿）、无 $ 面板内部项完整断言（skill-deck.png 半行裁切漏过）、无 CSS 选择器合法性校验（损坏选择器全绿通过）。

## 架构现状
- App.tsx 14,737 行〔复核：wc -l〕= 模块层 L362-3812（约 133 个 helper + 3 个内联小组件）+ App() 本体（39 useState / 39 useEffect / 67 useMemo / 49 useCallback，grep 实测）。
- 全量订阅 store 无 selector（App.tsx:3814-3842）+ surface 渲染函数无 memo（App.tsx:14248-14257）+ 全 webview 仅 4 处 memo（全在 coach）⇒ 每个流式 chunk 重渲染所有已访问 surface（含 8,819 行 CoachSettingsView）。探针实测（headless + preview bundle，arch 审计）：300 消息会话导航 warm p50 22-72ms、300 chunk 流式 0 个 >50ms long task——当前被硬件吸收，结构成本 O(已访问 surface 数)/chunk；headless/合成 chunk/单机单样本，不能反推「结构免费」。
- 热路径四处 + 守卫缺失：provider 事实 4 份副本（useWorkbenchState.ts:154-178,632 + App.tsx:3863-3880）；composer 每键全量持久化 layout（useWorkbenchState.ts:768-777）；composerContextUsage 每 chunk O(n²)（App.tsx:5517-5551）；providerDraftSourceKey 序列化在渲染体（App.tsx:5228）；5 个跨域 effect 无 activeView 守卫（App.tsx:8258,8226,5623,5639,4950）。
- 迁移路径既定（arch 审计）：①operationMessageGovernance 纯模块（零 UI 风险）→②useProviderConnectionController→③training→④plan→⑤conversation controller；每步逐字搬移不改签名 + npm run check + 点名 e2e。

## 视觉现状（收口基线）
- 12 张金图 zh-CN dark 420×900@2x，随 b647602 刷新、与分支同步（scripts/capture-ui-golden.mjs）；无浅色/RTL 金图。整体克制：无 emoji、无第三方图标库、无双主按钮（geometry 门保证）。
- token 纪律：颜色零硬编码（hex 仅在 token fallback，trainer-design-tokens-base-styles.css:6-20）；动效全 token（唯一漏网 composer.css:948）；排版 token 354:6 占优；间距 token 38:695 基本未采纳（gap 3/5/7px 离散步进）。
- 真实破绽：①主按钮 .button--accent 仅 12% accent 着色、与次级几乎同灰，.button 无 :active 按压态〔复核：styles/sections/buttons.css:38-46〕；②focus ring 5 种配方混用（2px/1px --focus-ring 33 处、--accent 2 处、color-mix 1 处）；③@keyframes trainer-spin 双定义〔复核：views-panes.css:1014 vs primitives:63〕；④损坏选择器 `[class*=         ]`〔复核：styles/sections/surface-materials-document-column-hairline-chrome-crafted-disclosure.css:124〕使整组 reduced-motion 规则被浏览器丢弃；⑤$ 技能面板底部裁切露半行（templates.css:125-126 渐变+footer 盖不住，skill-deck.png 可见）；⑥裸 ✓/✗/— 字形当图标（CapabilityMatrix.tsx:203、ProviderQuickSetup.tsx:245,282,298、RemoteVerificationPanel.tsx:34-44）；⑦新语法导航/品牌图标 0 引用（定义在 icons/navigation/coreNav.tsx、icons/brand/trainerBrand.tsx，仅 icons/trainerIndex.ts barrel 引用〔复核〕）。
- 首装理解成本语汇：plan.png「证据还没有改写计划」系统话（CoachPlanView.tsx:314/351/394）；「验证当前文件」训练卡一步三现（真实落点：TrainingWorkbenchView.tsx:713 本地文案表与 App.tsx:987 8 语言表〔复核〕；copy.ts:978 nextMove 仅为「下一步」栏目标签，下一步/步骤标题文本来自计划数据 CoachPlanView.tsx:1829 stepStartTitle——评审勘误后修正）；头部「Trainer trainer」品牌与同名工作区并排（AppShell.tsx:35-36）。
