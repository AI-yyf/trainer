# Trainer 分项工作计划

这份文档是 `docs/MASTER_IMPLEMENTATION_PLAN.md` 的执行拆解。

目标不是把 Trainer 做“更多”，而是把它做“更像一个可以长期依赖的教练”。

## 0. 使用规则

- 先做最小可验证切片，再扩大范围
- 先保证诚实状态，再做视觉收束
- 先打通主线，再做高级能力
- 任何新能力都必须挂回五视图之一

## 1. 计划总览

| Workstream | 主视图 | 目标 | 主要产物 |
| --- | --- | --- | --- |
| A | Coach | 对话 / 命令 / skill 的超级入口 | command deck, skill catalog, typed parts, recovery notices |
| B | Plan | 主计划 / 子计划 / 证据治理 | plan tree, freeze / restore, due reviews |
| C | Resources | 资料沙箱 / 搜索 / 预览 | sandbox root, provenance, preview tiers, FTS5 |
| D | Training | 闪记 / 实战 / 复盘 / 场景 | single-card-first, FSRS, handoff, recovery |
| E | Settings | provider / remote / i18n | provider profiles, protocol matrix, model test, language |
| F | QA | 跨平台 / 可恢复 / 可验证 | smoke, e2e, visual QA, live provider smoke |

## 2. Workstream A - Coach super-entry

### 目标

让 `Coach` 同时承担对话、命令、skill、调试、恢复、函数提示和轻量操作入口。

### 范围

- slash / skill deck
- context chips
- typed artifact blocks
- tool call / tool result / reasoning summary
- debug / review / restore 入口
- function hint 文案
- 发送、换行、清空、命令切换的快捷入口

### 主要文件

- `shared/src/skillCatalog.ts`
- `shared/src/protocol.ts`
- `extension/webview/src/components/coach/*`
- `extension/webview/src/app/App.tsx`
- `extension/src/commands/sessionCommands.ts`
- `extension/src/core/webviewBridge.ts`

### 验证

- 真实 Coach 回合能显示 typed parts
- `review / plan / task / next / flash / sandbox` 等 skill 都能从 Coach 入口触发
- 恢复态、阻塞态、工具态都清楚可见

## 3. Workstream B - Plan hierarchy

### 目标

让 Plan 成为总计划 / 项目计划 / 子计划 / 证据的治理视图，而不是文本堆叠页。

### 范围

- 主计划与子计划树
- 当前阶段与下一步
- 阻塞原因与可选分支
- 证据接纳 / 冻结 / 恢复
- review queue 和 due items

### 主要文件

- `server/app/planner/*`
- `shared/src/masterPlanGovernance.ts`
- `shared/src/planGovernance.ts`
- `shared/src/reviewQueueGovernance.ts`
- `extension/webview/src/components/plan/*`

### 验证

- 当前阶段必须一眼可见
- 子计划可展开但不抢主线
- evidence submit 会回流到计划状态

## 4. Workstream C - Resources sandbox

### 目标

让资料视图像一个受控沙箱，而不是文件管理器。

### 范围

- active workspace root / folder sovereignty
- 导入文件、URL、网页抓取
- 资料 provenance / trust / freshness
- 三层预览：rich / transformed / fallback
- SQLite FTS5 搜索
- 资源到训练卡的转换链

### 主要文件

- `server/app/resources/*`
- `server/app/ingest/*`
- `server/app/workspace/*`
- `shared/src/resourceWorkbenchGovernance.ts`
- `shared/src/workspaceAuthority.ts`
- `extension/webview/src/components/resources/*`

### 验证

- 资料能导入、索引、预览、追溯
- sandbox root 可配置、可迁移、可校验
- root 外默认不写

## 5. Workstream D - Training engine

### 目标

让 Training 变成单卡沉浸式训练流，卡片完成后能把结果回流到计划、资料和记忆。

### 范围

- flash / practice / review / scenario / transfer
- FSRS 调度
- single-card-first 首屏
- 恢复 / 继续 / 跳过 / 复盘
- 训练完成后的 evidence backflow

### 主要文件

- `server/app/training/*`
- `shared/src/trainingCardRouting.ts`
- `shared/src/trainingRecoveryGovernance.ts`
- `shared/src/trainingReturn.ts`
- `shared/src/transferEvidenceGovernance.ts`
- `extension/webview/src/components/training/*`

### 验证

- 首屏必须只突出当前卡
- 卡片完成后必须知道下一步
- 恢复后应回到正确的卡、场景或 next hop

## 6. Workstream E - Settings / provider / remote

### 目标

让 Settings 诚实展示 provider、模型、协议、语言和远程能力，不隐藏失败，也不夸大 readiness。

### 范围

- provider profile / protocol / capability matrix
- model refresh / connection test
- request defaults / `thinking` control
- remote credential mode
- 8 语言与回退
- cross-platform path semantics

### 主要文件

- `extension/src/provider/*`
- `server/app/llm/provider_service.py`
- `server/app/core/models.py`
- `shared/src/providerProtocols.ts`
- `shared/src/remoteWorkspace.ts`
- `extension/webview/src/components/settings/*`

### 现实 smoke

- `GET http://47.107.101.18:3000/v1/models` should return at least:
  - `MiniMax-M2.7-highspeed`
  - `MiniMax-M3`
- `POST /v1/chat/completions` must send UTF-8 JSON and top-level `thinking: { type: "disabled" }`
- reply must not contain `<think>`

### 验证

- provider save / import / test / model refresh all keep `requestDefaults`
- remote / local path semantics stay consistent
- 8 语言回退不破版

## 7. Workstream F - QA / recovery

### 目标

让每个主要状态都可以被验证、恢复、回放。

### 范围

- build / check / test / smoke
- browser preview recovery
- typed parts contract
- i18n coverage
- manual narrow-sidebar visual QA
- live provider smoke

### 主要命令

```powershell
npm run build --prefix extension
npm run build --prefix extension/webview
npm run check --prefix extension
npm run check --prefix extension/webview
node --test extension/tests/sessionCommands.test.js extension/tests/providerCommands.test.js extension/tests/providerWebviewCommands.test.js
scripts/check.ps1
scripts/smoke.ps1 -Strict
```

### 验证

- build / test 绿
- blocked / loading / empty / error 都真实
- resume / restore / restart 不丢上下文

## 8. 推荐执行顺序

1. Coach super-entry
2. Settings / provider / remote
3. Resources sandbox
4. Training engine
5. Plan hierarchy
6. QA / recovery 收束

## 9. 完成条件

某条 workstream 只有在以下条件满足时才算完成：

- 产物可见
- 行为可验证
- 失败态诚实
- i18n 可回退
- 不引入新的顶层 IA
- 不破坏已有真相路径
