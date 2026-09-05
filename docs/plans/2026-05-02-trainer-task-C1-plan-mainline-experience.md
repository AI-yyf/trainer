# Trainer Task C1 Implementation Plan

> **For Claude/Codex:** implement only this task, keep write scope tight, and stop for review when acceptance passes.

**Goal:** 重构 `计划` 视图，让用户一眼看懂“我现在在哪、先做什么、为什么先做、做完怎么验证”，把计划从展示卡片改成长期训练主线视图。

**Depends on:** B2

## Product Promise

- 计划默认只强调当前主线
- 背景信息和次级结构折叠
- 布局整体化、低理解成本
- 中英文都顺畅可读

## Read First

- [Master Index](./2026-05-02-trainer-learning-loop-master-index.md)
- [Coach-first UI And Feature Design](./2026-04-30-trainer-coach-first-ui-and-feature-design.md)

## Allowed Write Scope

- `extension/webview/src/components/plan/`
- `extension/webview/src/app/App.tsx`
- `extension/webview/src/styles.css`
- `extension/webview/src/lib/types.ts`
- `shared/src/models.ts`

## Do Not Touch

- `server/app/planner/**`
- `server/app/memory/**`

## Implementation Checklist

1. 计划页重心固定为 5 件事：
   - 当前目标
   - 当前阶段
   - 当前正在做的一步
   - 验证方式
   - 下一步预告
2. 把阶段队列、历史记录、复习项、观察项下沉到折叠层
3. 调整字体、密度、边距，确保计划页比对话更结构化但不更重
4. 用明确中文而不是术语堆砌来命名区块
5. 为空计划、恢复计划、旧计划兼容提供稳定展示

## Acceptance

- 用户第一次进入计划页就能知道下一步做什么
- 计划页比当前版本更简洁、更强主线感
- 无大面积术语块或重复摘要
- `npm run build --prefix extension/webview`

## Handoff

- 列出计划页最终信息层级
- 标注还缺哪些真实计划数据，交给 C2 提供
