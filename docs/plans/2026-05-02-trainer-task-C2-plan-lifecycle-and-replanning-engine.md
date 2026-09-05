# Trainer Task C2 Implementation Plan

> **For Claude/Codex:** implement only this task, keep write scope tight, and stop for review when acceptance passes.

**Goal:** 让 `计划` 从静态摘要进化为真正的长期训练生命周期系统，支持生成、推进、验证、阻塞、重排和复习挂接。

**Depends on:** C1

## Product Promise

- 计划不是一次性文案，而是可推进主线
- 当前阶段、下一步、阻塞点、验证结果都能持续更新
- 用户的长期目标和短期训练任务能共存

## Read First

- [Master Index](./2026-05-02-trainer-learning-loop-master-index.md)
- [C1](./2026-05-02-trainer-task-C1-plan-mainline-experience.md)

## Allowed Write Scope

- `server/app/planner/service.py`
- `server/app/core/models.py`
- `server/app/memory/service.py`
- `server/app/api/routers.py`
- `shared/src/models.ts`
- `shared/src/protocol.ts`
- `extension/src/core/workbenchData.ts`
- `server/tests/test_planner.py`
- `server/tests/test_api.py`

## Do Not Touch

- `server/app/research/**`
- `extension/webview/src/components/settings/**`

## Implementation Checklist

1. 扩展计划模型：
   - current stage
   - current step
   - why now
   - verify method
   - blocked reason
   - next after current
2. 让对话后的关键结果可回写到计划
3. 为“任务完成/验证失败/需要改道”提供重排逻辑
4. 把计划和长期目标、短期训练、复习队列连接起来
5. 为计划生成加入更清楚的中文和英文输出结构
6. 让 webview 能稳定收到增量后的计划快照

## Acceptance

- 新会话能生成可执行计划
- 连续多轮对话后计划会更新，而不是停在初稿
- 出现阻塞时可给出新的当前步骤
- `cd server && python -m pytest tests/test_planner.py tests/test_api.py -v`
- `npm run build --prefix extension`

## Handoff

- 说明计划状态机新增了哪些字段和转移
- 标注哪些掌握度/复习数据由 E1/E2 接力完善
