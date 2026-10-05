# Trainer Information Flow Audit(信息流审计)

- **基线**:`main@6aca826`
- **日期**:2026-10-04
- **方法**:六个并行审计代理(Coach / Learning / Training / Library+Settings / 全局状态仲裁 / Windows CI),全部结论带 `file:line` 证据;本文件是后续一切 UI 修改的唯一前置依据(§三:先审计,后动手)。
- **范围声明**:本审计只关心信息流——用户为什么看到它、为什么此刻看到、看完去哪。不重写代码,不新增功能。

---

## 0. 结论摘要

| # | 发现 | 影响 | 证据 |
|---|------|------|------|
| 1 | **无全局状态仲裁**。全局 banner 是单槽 last-write-wins,约 30 处 `setOperationMessage` 调用点各自为政;Coach 首屏存在 5 层可叠加的状态面(admission 面板 / onboarding 向导 / provider 通知 / 训练恢复条 / 全局 banner) | 同屏多 banner + pill + blocked card 互相抢注意力 | `App.tsx:14155-14164, 12256-12280, 8711-8732`;`useWorkbenchState.ts:785` |
| 2 | **约 9,000 行死 UI 代码仍在塑造产品**:Toast 系统(212 行,0 引用)、5 个死 Coach 组件(~1.7k 行)、3 个死 Training 视图(~7k 行)、读优先的 `ResourcesReaderView`(124 行,0 引用,而线上 Library 是管理后台) | 死代码持续产生"重新浮出"压力与维护噪音 | `components/Toast.tsx`;`components/coach/index.ts`;`components/training/CoachTrainingView.tsx` 等;`components/resources/ResourcesReaderView.tsx` |
| 3 | **Training 完成后自动把用户甩到 Coach 并抢焦点**(`App.tsx:8121-8143` 无路由守卫),且返回 Coach 必抢焦点(`9796`) | 用户丢失空间连续性,违反 Return Contract(§二十一) | `App.tsx:8121-8143, 9796-9805` |
| 4 | **Learning 首屏承载工程语义**:7 个过滤 tab 的"证据治理"队列、"全局记忆/项目记忆隔离"图、假进度环(`percent: done?100:0`)、自打开的 Global-plan 折叠(出现第二个主按钮) | 首屏认知超载;违反 One Primary Action | `CoachPlanView.tsx:2243-2391, 1726-1747, 2462-2470, 1752` |
| 5 | **同一事实多处渲染**:当前步骤在 Coach/Learning/Training 三处;资源附带状态在 Library 批量条/Coach chip/Composer 菜单三处;provider 事实在 store 里有 4 份副本 | 用户需要在多个位置理解同一概念 | `App.tsx:12240-12253, 13204 vs 13393`;`App.tsx:10483, 10838-10944`;`useWorkbenchState.ts:154-169, 623` |
| 6 | **Windows CI 两处失败均为测试缺陷**,非产品缺陷:`workspaceContext.test.js` 一条 POSIX fixture;`remoteCompanionBridge.test.js` 在 Windows 上把 `C:\` 拼进 URI authority 导致模块加载即抛 `Invalid URL` | main 分支 Windows 红灯 | `workspaceContext.test.js:24,31`;`remoteCompanionBridge.test.js:15,46` |
| 7 | **加载态惯用法叠用**:等待 token 时同一个气泡里同时出现 streaming 三点 + 3 行 skeleton + 状态行 | 违反"每表面一种加载惯用法" | `CoachConversationView.tsx:168-172`;`CoachMessageBubble.tsx:395-406` |
| 8 | **隐藏表面 ≠ 挂起**:`WorkbenchSurfaces` 永久保活所有访问过的视图,组件无 memo,每个流式 chunk 重渲染所有隐藏表面;39 个 useEffect 无路由守卫 | 性能损耗 + 隐藏表面继续自动改状态(草稿覆盖 `5129`、训练 composer 重置 `8155`) | `WorkbenchSurfaces.tsx:9-15`;`App.tsx:5129, 8155` |

---

## 1. 认知预算(Complexity Budget)

任何页面首屏必须立刻回答四问:

1. 我在哪里?(稳定的 shell + 面包屑/返回)
2. 我现在在做什么?(当前任务/阶段)
3. 最重要的下一步是什么?(唯一 Primary Action)
4. 如果不想继续,我怎么返回?(1 click 返回)

**任何新增信息必须证明"为什么必须现在出现"。"数据已存在所以显示"不是理由。**

## 2. One Primary Action 原则

每个主视口只允许一个 accent/dominant 动作:

| Surface | 唯一 Primary |
|---|---|
| Coach | Send(流式中为 Stop) |
| Learning | Continue current step |
| Training(各 phase) | 当前 phase 的动作(Try=提交答案;candidate=开始此步;verify=验证) |
| Library | 搜索 / 打开资料 |
| Settings Detail | 与该配置相关的主操作(连接=Save connection) |

现状违规:Learning 的 Global-plan 折叠自打开出现第二 accent(`CoachPlanView.tsx:1752`);Training Try 阶段并发 8-10 个可见 affordance;Settings Workspace 详情三个竞争按钮。

## 3. Surface State Arbitration(状态仲裁规则)

状态按**用户当前任务**就近显示,禁止跨表面全局泄漏。优先级阶梯(高→低,同屏只显示最高一项):

```
L1 全局不可用     sidecar 死亡 / workspace 不被信任   → 全局唯一 blocking surface
L2 当前表面阻塞   provider 断( composer 局部错误)      → 只在 Coach Composer 区
                  workspace admission                  → 只在 Coach 顶部
                  plan blocked                         → 只在 Learning
                  verify failed                        → 只在当前 Training 卡
L3 任务内提示     evidence 待确认 / review due / 索引中  → 各自表面内联,disclosure
L4 背景事实       连接正常、模型就绪、索引完成           → 不显示;Settings 有摘要即可
```

禁止:last-write-wins 的全局 banner 吞掉本应局部显示的错误;同一条件在 4 处独立渲染(provider 现状:`App.tsx:3982, 12271, 11834, CoachSettingsView.tsx:7270`)。

## 4. Truth Ownership Matrix(真相所有权)

每种数据**只有一个 authoritative owner**,其余位置只允许 Derived View(极简摘要或入口):

| 数据 | Owner | 允许的派生展示 |
|---|---|---|
| Conversation / 流式 | Coach surface(含 composer 草稿,按 scope) | — |
| Formal Plan / 阶段 / Current Step | Learning(NextAction 卡) | Coach:一行轻量上下文;Training:卡头 |
| Training Card / Attempt / 验证输出 | Training surface | Learning:入口;完成态:一行"正在进行: X" |
| Evidence(练习凭证) | 待确认项:Learning 内联决策;历史:Learning 折叠列表 | Coach:回复内 evidence `<details>`(已折叠) |
| Skill Projection | Progress(GrowthEvidence) | Learning:一个文字入口;Coach:不显示 |
| Review Queue | Training(复习队列) | Learning:一条"N 个到期"入口 |
| Resource / 版本 / 索引状态 | Library(reader facts) | Coach:一行附带 chip |
| Provider 连接详情 | Settings Connection Detail | Composer:一个模型/连接按钮(切换即可,不开第二个管理面板) |
| Workspace / Remote 能力 | Settings Workspace Detail | 需要远程能力时局部提示 |
| 滚动位置 / 草稿 / 折叠状态 | `useWorkbenchState` persisted layout | — |
| 操作反馈(operation message) | 仲裁函数(§3)单槽 | — |

## 5. 重复信息审计(Duplication Audit)

| 同一概念 | 出现位置 | 处置 |
|---|---|---|
| Current Step 文本 | Learning 头部 goalSummary 与 NextAction 同源同文(`App.tsx:13204-13215` vs `13393-13408`);Coach 恢复条;Training 卡头 | Learning 头部只保留阶段目标;Coach 恢复条压成一行;Training 卡头保留 |
| 训练进行中状态 | Coach 恢复 banner(`App.tsx:12235-12255`)+ Training 卡 + composer 摘要 | Coach 只留一行"正在进行: X + 继续" |
| Skill Projection | Learning Growth 折叠内 Strip 预览 + Progress 全量;组件内两套 mastery 换算(`CoachPlanView.tsx:1293-1322`) | Progress 独占;Learning 只留文字入口 |
| 资源附带状态 | Library 批量条(`ResourcesWorkbenchView.tsx:2835`)+ Coach chip(`App.tsx:14248`)+ Composer 资源菜单(`App.tsx:10838-10944`) | 保留 Coach chip;Composer 菜单去状态行;Library 去批量条 |
| Provider 健康 | Settings 索引摘要 + 详情 availability 条 + blocker 条 + Composer 菜单"刷新模型" | Settings 内去重;Composer 只保留切换 |
| Plan 决策状态 | 决策卡 + "More" 折叠里 3 行文字复述(`CoachPlanView.tsx:2403-2404, 1964-1994`) | 只保留决策卡 |
| Evidence 一词两义 | Learning"证据治理"队列 vs Progress"验证通过记录" | Learning 改称"练习记录确认";Progress 保留"成长/验证" |

## 6. 真实用户场景信息流(16 流程)

每条按:入口 → 看到什么 → 需要的决定 → Primary Action → 状态变化 → 反馈 → 下一步 → 返回。

### S1 第一次安装
入口:VS Code 打开扩展 → Coach 空 surface。看到:onboarding 向导 + workspace admission 面板可叠加(`App.tsx:12258-12259`),设置页另有 availability 条 + blocker 条双层(`CoachSettingsView.tsx:7288+7311`)。决定:填 key/选模型/选目录。Primary:检查连接。反馈:连接成功后空态变欢迎语。**问题**:两套向导可同屏;阻断深链不带 section,可能落在上次访问的 Settings 详情。**改**:仲裁后同时只显示一个接管面;深链直达 Connection。

### S2 老用户打开昨天的工作
入口:恢复会话 → Coach。看到:对话 + (若有卡)训练恢复 banner + composer 摘要。Primary:Send 或 继续。返回:三导航。**问题**:恢复条是卡片样式,与 composer 摘要重复。**改**:压成一行轻量条(§十一)。

### S3 问一个简单概念
入口:Coach。看到:气泡 + 回复内 evidence 折叠 + artifact 卡 + "···" + 后缀装饰图标。Primary:Send。**问题**:后缀 3 个装饰图标与 artifact 下一步重复;artifact 卡下平铺 9 个元数据键(证据/把握/决策/卡点/续接/教学提示)。**改**:删装饰图标;删元数据平铺,保留标题+摘要+单动作。

### S4 问当前代码为什么出错
同 S3 通路;工具活动条显示"结束原因:{reason}"等技术措辞(`AgentActivityStripSmart.tsx:212-222`)。**改**:活动条保留(真实过程),文案去运行时词汇。

### S5 理解整个项目
入口:Coach 提问(项目上下文自动带入)。看到:普通回复。**现状合格**,无 Dashboard 顶置。

### S6 继续正式学习计划
入口:Learning。看到:阶段头 + 决策卡 + NextAction + Revisit 折叠 + Roadmap 折叠(含假进度环/材料徽章)+ Growth 折叠 + 证据治理队列(7 tab)+ 自打开 Global-plan(第二 accent)+ "More" 大杂烩。Primary:Continue(被 Global-plan 第二 accent 竞争)。**问题**:首屏 DOM 巨大,工程词汇密集(证据治理/Unscoped/置信度)。**改**:队列紧凑化;去自打开;去假进度环;去记忆隔离图。

### S7 恢复一张未完成 Training Card
入口:Coach 一行条"继续" 或 Learning→练习。看到:直达当前 phase 的卡(cardOnly 正确)。Primary:当前 phase 动作。**问题**:卡外常挂 3 个常开折叠(Source&reason / Full acceptance(内含第二个 composer)/ More→Next Card)。**改**:合并为一个"任务详情"折叠;去掉第二 composer;Next Card 移到完成态。

### S8 从资料阅读跳到 Coach
入口:Library reader → Ask Coach。看到:切到 Coach,资源 chip 显示,composer 聚焦(`App.tsx:12751-12756`)。**现状合格**(单 composer 交接,无第二输入框)。返回:导航回 Library,滚动位置有 per-surface 保存(`useSurfaceScroll.ts`)。

### S9 完成 Verify → Reflect → Return
入口:Training 卡。看到:phase 单主角(正确),但完成后**自动跳 Coach + 替换草稿 + 抢焦点**(`App.tsx:8121-8143`)。**问题**:空间连续性破坏;用户被甩到随机上下文。**改**:留在卡上显示完成终态 + 唯一"回到对话"按钮,用户自己决定。

### S10 查看能力为什么算"已验证"
入口:Learning → Growth 折叠 →"View evidence" → Progress。**问题**:Learning 的"证据"字样指向两种不同东西(治理队列 vs 验证记录);行内还显示置信度百分比(伪精确)。**改**:Learning 入口改名"成长";Progress 拥有全部验证明细(现状已合理:1 back + 4 toggle)。

### S11 Provider 挂掉
入口:任意。现状:同一条件 4 处独立渲染(全局 banner / Coach 内联通知 / 中性接管态 / Settings availability),且 composer presence 条在非 Coach 视图仍显示。**改**:仲裁阶梯——正在 Coach → composer 局部错误;其他表面不泄漏;仅 L1 才全局。

### S12 SSH 断线
入口:Training 验证或远程操作。现状:远程验证中断渲染 `verdict="unknown"`,不伪造失败(`RemoteVerificationPanel.tsx:104-129`,正确);TR-100 边界通知只出现在 Training(`App.tsx:10144-10169`,正确)。**问题**:连接丢失属 L2,但全局 banner 可能同时弹。**改**:仲裁收敛后局部化。

### S13 重启 VS Code 后恢复
入口:启动 → runtime rehydration。现状:视图/滚动/草稿恢复(`useSurfaceScroll` + persisted layout);训练 attempt `startOrRecover` 有守卫。**现状基本合格**。

### S14 切换工作区
入口:Settings Workspace。现状:surfaceInstanceKey 变化强制 remount(`App.tsx:4744`),滚动词正确失效。**问题**:providerDraft 会被 host 配置覆盖(`5129`,有 dirty ref 保护,低风险)。**保持现状,记录即可**。

### S15 切换本地 / SSH
现状:能力模型经 WorkspaceGateway/Companion,产物状态机含 connection_lost 且不制造失败 Evidence(`remoteUri.ts` / `remoteWorkspaceGateway.ts:273-283`)。UI 词汇"Remote Workspace Companion"偏工程(`remoteSupportCopy.ts:23`)。**改**:文案改"远程工作区"。

### S16 切换历史会话
入口:头部 History → UtilityOverlay 抽屉(搜索 + 今日/昨日/7 天/更早分组,当前会话禁选)。**现状合格,保持**(`CoachHistoryDrawer.tsx:273-355`)。

---

## 7. 各 Surface 详细发现(证据索引)

### 7.1 Coach(`route: coach`)
- 首屏 10 个常驻动作(Send / artifact 主按钮 / 3 导航 / History / Settings / ··· / 查看证据 / 资源+ / 模型按钮;训练恢复条出现时 +1)。`App.tsx:12233-12283`;`CoachComposer.tsx:868-1219`。
- 每条回复:1 折叠 evidence + 1 主 artifact 卡(含 9 键元数据平铺 `CoachArtifactBlock.tsx:260-364`)+ 1 "···" + 3 个装饰后缀图标(`CoachMessageBubble.tsx:97-128`)。
- Composer 常驻:字数 `n/2000` 永久显示(`CoachComposer.tsx:980-984`);helper 行出现 "Blocker/evidence" 中英混杂(`App.tsx:12441-12502`)。
- artifact 点击会**静默自动发送**合成 prompt(`App.tsx:9319-9349`)。
- 恢复文案暴露 "checkpoint"(`appUiCopy.ts:2497-2513`)。
- 死组件:CoachGuidance / CoachActionStatus / CoachSessionRecap / CoachOrientationRail / CoachDeepAnalysisBlock(~1.7k 行,仅 barrel 引用)。

### 7.2 Learning(`route: plan`)
- 首屏块清单见 S6;Primary 唯一性被 Global-plan 自打开破坏(`CoachPlanView.tsx:1752, 1697-1716`)。
- 证据治理队列:7 过滤 tab + 行级三按钮 + 置信度%(`2243-2391, 1423-1426`)。
- Roadmap:每阶段进度环数据造假(`2462-2470`),材料徽章 + 嵌套列表常开(`2545-2673`)。
- 记忆隔离图、plan-change candidates(Diff/Impact/采纳/拒绝)、"More" 折叠复述决策卡(`1726-1747, 2409-2417, 2400-2419`)。
- 组件内发明状态:`fallbackGovernanceItems` 无中生有"Needs confirmation"行(`1964-1990`);两套 mastery 换算(`1293-1322`)。
- 死文案:`learningHomeDueTitle/ClearTitle` 定义未渲染(`372-373`)。

### 7.3 Training(`route: training`)
- 入口即当前卡(cardOnly 正确,`App.tsx:12949-12953`);但 Try 阶段并发 8-10 affordance。
- 卡外 3 个常开折叠:`3032-3045`(Full acceptance 在 Try 时**二次渲染整个 composer**,`3042`)。
- `{!cardOnly}` 分支(~1500 行)不可达;CoachTrainingView(3,346 行)/CoachPracticeView(1,054)/CoachFlashView(2,671) 及 6 个 Panel 组件全部死代码。
- Review 队列行暴露 FSRS 术语(`<summary>FSRS</summary> Interval…`,`3481-3491`)。
- 面包屑把 Learning 标成 "Plan"(`3025`);cardId 变化 `scrollIntoView` 与滚动恢复打架(`2446-2450`)。
- Return 后自动跳 Coach + 抢焦点(`App.tsx:8121-8143`)。

### 7.4 Library(`route: resources`)
- 管理后台优先:每行复选框(`1712-1723`)+ 文件夹复选(`1798-1814`)+ 批量删除条(`2835-2879`)+ 工具栏刷新索引(`2909-2919`)+ 行内索引徽章(`1728-1732`)+ Trash 折叠(`3159-3242`)。
- Reader:Back 正确;无阅读位置恢复;facts 5 行工程状态(Index/Trust/Freshness/Preview/Training readiness,`3309-3348`);"Ask Coach" 单 composer 交接正确。
- 死代码:`ResourcesReaderView.tsx`(读优先版本,0 引用)。

### 7.5 Settings(`route: settings`)
- Index→Detail 结构正确(`SettingsIndex.tsx:13-34`,4 类 + 一句话状态)。
- 违规:裸 `setActiveView("settings")` 深链不带 section,配合表面保活会落在**上次访问的详情**(`App.tsx:8773, 9819, 13300, 14220`)。
- Connection 详情 20+ 控件;availability 条与 blocker 条双层同屏(`7288 + 7311`);能力芯片/测速/诊断堆叠(`7709+`)。
- Composer 模型菜单与 Settings 各有一套"已保存连接 + 刷新模型"(`App.tsx:10950-11024` vs `CoachSettingsView.tsx:6968, 7060`)。

### 7.6 全局编排
- 无仲裁:见 §0-1;Toast 死系统;`FirstLookSummaryPanel` 死;`connectionStateLabel` 死(`App.tsx:1590`)。
- 表面保活不挂起:无 memo、39 个无守卫 effect;焦点抢占 2 处(`8121, 9796`)。
- 加载惯用法叠用:三点 + skeleton + 状态行同气泡(`CoachConversationView.tsx:168-172` + `CoachMessageBubble.tsx:395-406`)。
- CSS token 纪律优秀(51 文件 0 硬编码色);styles.css 9 行墓碑,实际 52 文件 ~21k 行于 `styles/sections/`。

### 7.7 Windows CI
- `workspaceContext.test.js:19-32`:**测试缺陷**——`/projects/new-project` POSIX fixture 在 Windows 被 `path.resolve` 成 `C:\projects\...`;本文件其余测试已用 `F:\` 风格 opaque fixture。修测试。
- `remoteCompanionBridge.test.js:15,46`:**测试缺陷**——`os.tmpdir()` 无前导 `/`,把 `C:\Users\...` 拼进 `vscode-remote://` authority → `Invalid URL`,模块加载即崩,3 个测试全红;mock Uri 的 `fsPath` 不符合 Windows `file:` 语义;`/tmp/outside.md` 越界 fixture POSIX 专属。修测试(harness)。
- 产品代码(`remoteUri.ts` / `remoteWorkspaceGateway.ts` / `workspaceRoots.ts`)未发现平台缺陷。

---

## 8. 本轮减法计划(net-subtraction plan)

**方法:audit → subtract → consolidate → verify。不重写,不新增顶级页面,六条内部路由与全部既有能力保留(§三十九)。**

| 分区(互斥文件所有权) | 减法内容 |
|---|---|
| **App.tsx(唯一所有者)** | 建 `resolveCoachSurfaceStatus` 单一仲裁;删训练 auto-nav + 返回抢焦点;深链带 settings section;恢复条压一行;goalSummary/nextStep 去重;artifact 停止静默发送;删 Toast/FirstLookSummaryPanel/connectionStateLabel;checkpoint/Blocker 文案去术语 |
| **Coach 组件** | 删装饰后缀图标;artifact 卡去 9 键元数据平铺;加载惯用法去叠用;字数计数仅近上限显示;删 5 个死 Coach 组件 |
| **Learning 组件** | 证据队列紧凑化(去 7 tab/置信度);去假进度环与材料徽章墙;Global-plan 不自打开;删记忆隔离图;Growth 只留文字入口;删发明状态与死文案 |
| **Training 组件** | 删不可达分支 + 7k 死组件;3 折叠合 1;去第二 composer;每 phase 单主按钮;面包屑改 Learning;去 FSRS 裸术语;Return 终态留卡;scrollIntoView 加可见性守卫 |
| **Library+Settings** | 首屏去多选/批量条;行点击即读;删除能力移入 reader;facts 5 行并 1 行;settings 深链 section 请求(store 契约:`settingsCategoryRequest`);删死 ResourcesReaderView |
| **CI 测试** | 两个 Windows 失败文件的 platform-neutral fixture 修复 + 2 处 tmpdir 卫生 |

**明确不做**:不改三导航结构;不动 server/models;不做 App.tsx 大拆分(仅审计记录 §四十二 为后续方向);不删任何用户能力(删除控件的能力全部移位保留)。

## 9. 验证门

上线前回答(§四十):知道在哪里?知道当前任务?知道下一步?知道为什么?知道怎么退?有没有不需要的信息?同一事实是否重复?错误是否只影响相关区域?是否泄漏工程概念?是否有两个竞争 Primary?
门:`npm run check` 全绿;`test:extension` 全绿(含 Windows fixture 修复后在本机通过);`test:server` 全绿;`verify-ui-geometry.mjs` 通过;e2e 受影响用例更新后通过;净减代码行数为负。
