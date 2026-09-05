# Trainer Task A1 Implementation Plan

> Historical snapshot from the superseded three-view phase.
> Current Trainer IA lives in [docs/ui-contract.md](../ui-contract.md): `Coach / Plan / Resources / Training / Settings`.

> **For Claude/Codex:** implement only this task, keep write scope tight, and stop for review when acceptance passes.

**Goal:** 把 Trainer 的顶层骨架稳定成真正的 `对话 / 计划 / 设置`，并且在无 API key、sidecar 未就绪、会话未恢复时都给出诚实且可操作的状态，而不是黑屏或假可用。

**Depends on:** 无

## Why This Task Exists

如果 A1 做不好，后面所有“强能力”都会被黑屏、空白态、错误态吞掉。这个任务先修产品入口真实性。

## Product Promise

- 顶层只有 `对话 / 计划 / 设置`
- 不再暴露 `研究` 一级视图
- 无 key、sidecar 异常、无 session 时都有清楚引导
- 不允许黑屏，不允许空白错位

## Read First

- [Master Index](./2026-05-02-trainer-learning-loop-master-index.md)
- [Coach-first Full Delivery Plan](./2026-05-02-trainer-coach-first-full-delivery-plan.md)

## Allowed Write Scope

- `extension/webview/src/app/App.tsx`
- `extension/webview/src/app/useWorkbenchState.ts`
- `extension/webview/src/components/coach/`
- `extension/webview/src/components/plan/`
- `extension/webview/src/components/settings/`
- `extension/webview/src/styles.css`
- `extension/src/core/webviewBridge.ts`
- `extension/src/commands/sessionCommands.ts`
- `shared/src/models.ts`
- `shared/src/protocol.ts`

## Do Not Touch

- `server/app/research/**`
- `server/app/pedagogy/**`
- `server/app/memory/**`

## Implementation Checklist

1. 清理顶层导航，只保留 `coach | plan | settings`
2. 为 `missing provider config / missing api key / sidecar not ready / loading session / recover failed` 建立统一状态模型
3. 在 webview 首屏提供真实引导：
   - 没 key：去设置
   - sidecar 未就绪：展示重试状态
   - session 恢复中：展示 skeleton
4. 把“不可发送”的原因暴露成明确文案，不要用沉默禁用
5. 校正初始布局，避免黑屏、错位和首屏白块
6. 保证 `研究` 只作为后台数据，不再成为主视图入口
7. 让刷新、重开侧栏、重连 sidecar 后能正确回到当前视图和状态

## Acceptance

- 打开侧栏不会黑屏
- 没配置 API key 时出现明确引导，而不是空白
- sidecar 未就绪时能看到状态与恢复路径
- 导航只剩 `对话 / 计划 / 设置`
- `npm run build --prefix extension/webview`
- `npm run build --prefix extension`

## Handoff

- 说明状态模型新增了哪些枚举或字段
- 说明哪些错误态还依赖后续 D1/D2 完善
