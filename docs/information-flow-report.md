# Trainer Information Flow Report(信息流成熟化 · 最终报告)

- **基线**:`main@6aca826` → **本轮工作树**(未提交,等待评审)
- **配套文档**:[information-flow-audit.md](./information-flow-audit.md)(前置审计:16 场景信息流 + 仲裁规则 + 真相所有权矩阵)
- **方法**:audit → subtract → consolidate → verify。六个并行审计代理定位证据,六个并行实现代理执行减法(文件所有权互斥,App.tsx 单一所有者),随后守卫测试/e2e 规格两路修复,再由 e2e 黑盒测试暴露并修复 3 个真实回归;第二轮继续消化审计遗留——错误局部化与孤儿清理。
- **总量**:102 文件,+2,476 / **−24,316,净删 21,840 行**。server/ 零改动。

---

## 1. 旧的信息流是什么,哪里最复杂

审计结论(详见 audit 文档 §0):Trainer 的问题不是导航多,而是**同一时刻多个系统都在向用户喊话,且没有仲裁**:

- 全局 banner 是单槽 last-write-wins(约 30 处 `setOperationMessage` 调用点);Coach 首屏最多可叠加 5 层状态面(admission 面板 / onboarding 向导 / provider 通知 / 训练恢复卡 / 全局 banner),composer 附近还有 4 个互相打架的 blocked 谓词。
- **同一事实多处渲染**:当前步骤在 Coach/Learning/Training 三处;训练进行中是一张卡 + composer 摘要两处;Skill Projection 在 Learning 折叠里预览又在 Progress 全量展开;资源附带状态在三处;provider 事实在 store 里有 4 份副本。
- **Training 完成后自动把用户甩到 Coach 并抢焦点**;返回 Coach 必抢焦点。
- Learning 首屏塞进了工程语义:7 个过滤 tab 的"证据治理"队列、记忆隔离图、假进度环、自打开的 Global-plan 折叠(出现第二个主按钮)。
- 约 9,000 行死 UI 代码仍在仓库里塑造"还能再加回来"的压力(Toast 系统、5 个死 Coach 组件、3 个死 Training 视图 + 6 个 Panel、读优先的 ResourcesReaderView)。

## 2. 删除了什么(净减法)

| 类别 | 内容 | 规模 |
|---|---|---|
| 死组件 | `Toast.tsx`、`FirstLookSummaryPanel.tsx`、Coach:`CoachActionStatus/CoachSessionRecap/CoachOrientationRail/CoachDeepAnalysisBlock`(+2 个 copy 模块;`CoachGuidance` 因被 common 复用而保留)、Training:`CoachTrainingView/CoachFlashView/CoachPracticeView` + 6 个 Panel + `trainingPanelCopy`、`ResourcesReaderView.tsx`、孤儿 `SkillProjectionStrip.tsx`、`resourceLibraryFolders.ts` | ~12,700 行 |
| 不可达分支 | `TrainingWorkbenchView` 的 `{!cardOnly}` 分支与 wins/weak-spots 网格(cardOnly 自上一轮起硬编码为 true) | ~845 行 |
| 每条消息的 chrome | artifact 卡 9 键元数据平铺(证据/把握/决策/卡点/续接/教学提示)、3 个装饰后缀图标、永久字数计数(改为 ≥90% 才出现) | — |
| Learning 首屏 | 7 个证据过滤 tab + 行级置信度%、假进度环(`percent: done?100:0`)、材料徽章墙、记忆隔离图、自打开的 Global-plan accent、决策卡在"More"里的文字复述、发明出来的 `fallbackGovernanceItems` 状态 | CoachPlanView −594 行 |
| Library 管理后台化 | 行复选框、文件夹复选、批量删除条、工具栏刷新索引、行内索引徽章、Trash 批量恢复按钮、reader 6 行 facts 压成 Source + 1 行状态 | −289 行 |
| 死文案/术语 | "checkpoint" 全部退出用户可见文案;"证据治理/Unscoped/置信度/Blocker(中英混杂)/FSRS/handoff"改学习者语言;8 语言同步修改 | — |
| 孤儿样式与死键(第二轮) | 33 个 CSS 文件的死选择器族(Toast/死 Training 分支/死组件面板/旧 reader/旧消息气泡 v2 等)+ 6 个死 `@keyframes`;copy.ts 56 个零引用键 × 8 语言表 | CSS −8,897 行;copy −338 行 |

**能力零删除**:所有被移除控件的能量都有新落点——批量删除→reader 内单资源删除(复用原确认流);Trash 恢复→逐项恢复按钮;材料生成→阶段折叠内保留;Next Card→Return 终态按钮;训练恢复→Coach 一行轻量条。

## 3. 移到 disclosure / 局部化的信息

- Training 卡外的 3 个常开折叠(Source & reason / Full acceptance〔内含第二个 composer!〕/ More→Next Card)→ **一个**默认关闭的"任务详情"折叠。
- Learning 的 Revisit / Roadmap / Growth / 练习记录确认 / Global-plan / Project plans 全部为默认关闭的折叠;阶段详情关闭,展开即读(且**展开不再跳转 Coach**)。
- Settings:connection 详情里 availability 条降级为"只留整体状态,去掉逐条 action"(blocker 条是唯一可执行清单);但保留完整解释文案,失败仍然可解释(§四十六:隐藏复杂度≠隐藏真实性)。
- 消息级:证据保持在已折叠的 `<details>`;复制/分享/存资料在 "···" overflow。

## 4. 不再全局显示的状态

- **建立了 `resolveCoachBlockingSurface()` 单一仲裁**(App.tsx):`workspace-admission > provider-setup > provider-notice > recovering > null`,渲染点与 composer presence 条都从它推导——**同屏最多一个阻塞面**。provider 错误只挡 Composer;Library 索引不再占用 Coach 顶部;review due 不再全局告警。
- **操作消息同样归位(第二轮)**:`setOperationMessage` 收敛为原子 helper(消息 + 表面同时写,清除即重置),新增 host 侧拦截——资源操作(delete/restore/index/upload)结果只随 Library 表面显示,409 计划修订冲突与 plan-freeze 消息只随 Learning 表面显示;79 个调用点经同一入口,不再 last-write-wins 泄漏到无关表面。
- 训练完成不再触发全局导航:删除了 `App.tsx` 的 auto-nav + 焦点抢占,草稿交接保留,终态留在卡上(见 §5)。
- 深链带目的:4 处裸 `setActiveView("settings")` 现在先 `requestSettingsCategory('connection'|'workspace')`,配合 store 新增的 `settingsCategoryRequest` 契约,不再落在"上次访问的详情页"。

## 5. 流程级收益(点击/注意力)

| 流程 | 之前 | 之后 |
|---|---|---|
| 完成 Verify→Reflect→Return | 自动跳 Coach + 替换草稿 + 抢焦点(用户"被甩") | 留在卡上看到"已完成 · 结果已带给教练"+ 显式"回到对话"(1 click,用户决定) |
| 从 Coach 深链进 Settings | 落在任意上次详情,再找 Connection(+N click) | 直达对应 Detail(1 click) |
| 点 artifact"下一题/复习" | 静默自动发送一条合成消息(用户困惑"它发了什么?") | 预填草稿 + 聚焦,发送权在用户 |
| Library 打开一份资料 | 单击选中→再进 reader(或记住双击) | 单击即读;删除/恢复在 reader/Trash 各 1 click |
| Learning 首屏 Primary | 被 Global-plan 自打开的第二 accent 竞争 | 唯一 accent = Continue current step |
| Training Try 阶段 | 8–10 个并发 affordance,含第二个 composer | 每 phase 单主按钮;卡外 1 个折叠 |

## 6. 逐 Surface 结论

- **Coach 更安静**:回复 = 内容 + 至多一个主 artifact 动作 + 折叠证据 + "···";无装饰图标、无元数据墙;训练状态压成一行"正在进行:X〔继续〕";连接问题只出现在 Composer 局部;streaming 时同一气泡只有一种加载惯用法(修掉了三点+skeleton+状态行三叠)。
- **Learning 更明确**:首屏 = 目标/阶段 + 唯一 Continue + 折叠的后续;决策卡只讲真实状态(顺带修了"待确认证据从不告警"的真 bug);成长只有一个文字入口,Projection 归 Progress 所有。
- **Training 更专注**:入口即当前卡、phase 即主角、完成即终态;面包屑改为"‹ 学习";FSRS/路由术语退出界面。
- **Library 更像阅读空间**:列表为找与开,reader 为读;状态一行;管理动作各就各位。
- **Settings 更可懂**:Index→Detail 不变,深链必达;失败态必有且仅有一个 Test 入口(回归修复后由 e2e 锁定)。
- **全局更便宜**:隐藏表面继续保活(本轮不动 §四十二 的大拆分),但隐藏表面不再抢导航、抢焦点、自动改训练 composer。

## 7. 跨平台与 Windows CI

- Windows CI 两处红灯均判定为**测试缺陷**(非产品):`workspaceContext.test.js` 的 POSIX fixture 改为仓库既定的 `F:\` 风格 opaque fixture;`remoteCompanionBridge.test.js` 在 Windows 把 `C:\` 拼进 URI authority 导致模块加载即抛——改为 slash 形态 hostPath(`/C:/Users/...`,真实 vscode-remote 形状)+ 符合 Windows 语义的 mock `fsPath`(`file:` 走 `fileURLToPath`)+ fixture 派生的越界探针。win32 语义模拟 8/8 验证,本机 24/24 通过。
- 产品代码(`remoteUri.ts`/`remoteWorkspaceGateway.ts`/`workspaceRoots.ts`)经审计未发现平台缺陷;能力模型(WorkspaceCapabilities / 结构化 ProcessSpec / connection_lost 不制造失败 Evidence)保持不变——平台只改 capability,不改 mental model。
- 快捷键/文案平台化、字号缩放矩阵、branch protection(§三十一/三十二/四十八)为**后续轮次**事项,本轮未动。

## 8. 验证门(全部通过)

| 门 | 结果 |
|---|---|
| `npm run check`(CSS sections + webview tsc + extension tsc) | ✅ 全绿 |
| `node --test extension/tests/*.test.js`(含新增 operationMessage 归位守卫) | ✅ 0 失败(修复 8 个守卫测试文件至新不变量;删除 1 个只测已死组件的测试文件;新增 1 个归位守卫) |
| e2e:trainer.spec + 200 例体验矩阵 + 资源/会话恢复/设置生命周期 | ✅ 单轮 **271/271**;`verify-ui-geometry.mjs` 182 项断言通过 |
| e2e 暴露的真实回归 | ✅ 3 个全部修复(Test Connection 失效态无入口 / 删除确认困在 hidden 容器 / 展开阶段详情跳转 Coach)+ 1 个不可达 dblclick 清理 |
| server | ✅ 零改动(161 个 pytest 文件不受影响) |
| 净减行数 | ✅ −21,840 |
| CI 注 | Windows Extension 用例已在本机 + win32 模拟双验证;最终以远端 CI 跑绿为准 |

## 9. 批判式收尾(§三十三)

**What improved**:同屏阻塞面从最多 5 层 → 1;Training 完成不再劫持导航;Learning/Training/Library 首屏可见动作显著减少且全部能力可达;约 1.27 万行死代码消失,后续贡献者不再面对"两个 Library/三个 Training 视图"的分裂叙事。

**What became worse**:(a) App.tsx 仍是单文件编排器(14.6k 行),仲裁函数是内嵌的而非独立 governance 模块——逻辑正确但位置仍是债务;(b) 训练恢复从"卡片"降为"一行",视觉权重更低,极少注意横幅的用户可能更晚注意到未完成的卡(由 composer 摘要冗余兜底);(c) 本轮删除使部分 copy.ts 键成为孤儿(文件按规未动),待统一清理。

**What complexity was removed**:4 个 blocked 谓词的布尔之舞、last-write-wins 的错误广播、双 composer、假进度数据、发明状态。

**What complexity was added**:`settingsCategoryRequest` 一个 store 意图字段(为换回"深链必达")、`resolveCoachBlockingSurface` 一个纯函数。合计 <60 行。

**What remains questionable**(下轮候选):① 隐藏表面仍全额渲染成本(§四十二 的 Controller 拆分 + memo 化);② Composer 模型菜单与 Settings 仍各有一套连接列表(审计 TOP5 未完全消化);③ provider/settings 域消息仍默认全局(有意保留——它们的动作入口在 Coach/Settings 本地;进一步领域化需逐条产品判断);④ 阅读位置恢复(reader scroll)仍缺;⑤ 统一 Find/Cmd+K(§九)未启动;⑥ 更老的 ~289 个零引用 copy 键(RL 词汇表/问候/streak 族)与 manifest.json 陈旧行数元数据待清;⑦ branch protection / required checks 配置(§四十八)需要仓库管理员权限。

---

**一句话**:这一轮没有让 Trainer 多任何功能,而是让它第一次做到了"每个时刻只有一个声音在说话,且说完知道用户该去哪"——后台依旧复杂,前台开始安静。
