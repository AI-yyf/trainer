# Trainer Task E1 Implementation Plan

> **For Claude/Codex:** implement only this task, keep write scope tight, and stop for review when acceptance passes.

**Goal:** 把 Trainer 的长期记忆从“若干快照字段”提升为真正的教练连续性系统，能记住目标、主线、卡点、最近验证结果、常见弱点和教学偏好。

**Depends on:** D2

## Product Promise

- 教练不会每次都像第一次见你
- 会记住最近主线、验证结果和卡点
- 会逐步形成用户能力画像和教学偏好
- 这些记忆能真实影响下一轮指导

## Read First

- [Master Index](./2026-05-02-trainer-learning-loop-master-index.md)
- [memory/service.py](../../server/app/memory/service.py)
- [review_scheduler.py](../../server/app/memory/review_scheduler.py)

## Allowed Write Scope

- `server/app/memory/service.py`
- `server/app/memory/models.py`
- `server/app/db/repository.py`
- `server/app/core/models.py`
- `server/app/api/runtime.py`
- `server/app/api/routers.py`
- `shared/src/models.ts`
- `shared/src/protocol.ts`
- `extension/src/core/workbenchData.ts`
- `server/tests/test_memory.py`
- `server/tests/test_repositories.py`
- `server/tests/test_api.py`

## Do Not Touch

- `server/app/research/**`
- `extension/webview/src/components/settings/**`

## Implementation Checklist

1. 明确长期教练记忆结构：
   - long-term goals
   - active thread
   - recent wins
   - repeated blockers
   - top weaknesses
   - teaching preferences
   - recent verification outcomes
2. 区分短期会话记忆与长期工作区记忆
3. 每轮对话后回写关键信号，而不是只存最终回复
4. 允许计划和消息流读取同一份连续性状态
5. 为空工作区、旧数据迁移、损坏记录恢复提供兜底
6. 为记忆可解释性保留轻量摘要，不做复杂前台设置

## Acceptance

- 关闭再打开后，主线和关键记忆可续接
- 连续多轮后能看到弱点和最近进展被回写
- 计划和教练消息都能读到同一连续性状态
- `cd server && python -m pytest tests/test_memory.py tests/test_repositories.py tests/test_api.py -v`

## Handoff

- 说明长期记忆的数据结构
- 标注哪些复习调度能力交给 E2
