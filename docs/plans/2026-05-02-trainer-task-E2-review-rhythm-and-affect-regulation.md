# Trainer Task E2 Implementation Plan

> **For Claude/Codex:** implement only this task, keep write scope tight, and stop for review when acceptance passes.

**Goal:** 把复习节奏和情绪调节从“有一点”提升到真正可用，让 Trainer 既会安排复习，也会根据你的挫败感和进度调节讲解力度。

**Depends on:** E1

## Product Promise

- 教练知道什么时候该复习，而不是永远只推进新内容
- 教练知道你卡住了、急了、没信心了时该怎么调节
- 复习不打断主线，而是嵌入主线

## Read First

- [Master Index](./2026-05-02-trainer-learning-loop-master-index.md)
- [affect/service.py](../../server/app/affect/service.py)
- [review_scheduler.py](../../server/app/memory/review_scheduler.py)

## Allowed Write Scope

- `server/app/affect/service.py`
- `server/app/memory/review_scheduler.py`
- `server/app/memory/service.py`
- `server/app/pedagogy/service.py`
- `server/app/core/models.py`
- `server/app/api/routers.py`
- `shared/src/models.ts`
- `server/tests/test_review_scheduler.py`
- `server/tests/test_pedagogy.py`
- `server/tests/test_api.py`

## Do Not Touch

- `server/app/research/**`
- `extension/webview/src/components/plan/**`

## Implementation Checklist

1. 强化 affect 状态：
   - frustration
   - confidence
   - urgency
   - reassurance need
   - recovery signal
2. 让 pedagogy 决策消费 affect 状态
3. 强化 spaced review：
   - due review
   - ahead-of-time reminder
   - digest mode
   - weak-spot revisit
4. 把复习项嵌入当前训练主线，不做孤立提醒
5. 对中文和英文分别生成自然复习提示
6. 建立“连续挫败时降低难度”的策略

## Acceptance

- 同一个用户连续卡住时，回复风格会明显更适配
- due review 会真实出现在计划或教练流程里
- 复习项与当前项目训练相关，而不是抽象口号
- `cd server && python -m pytest tests/test_review_scheduler.py tests/test_pedagogy.py tests/test_api.py -v`

## Handoff

- 说明 affect 和 review 如何影响教学决策
- 标注更深的题目生成留给 H2
