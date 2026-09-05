# Trainer Task F2 Implementation Plan

> **For Claude/Codex:** implement only this task, keep write scope tight, and stop for review when acceptance passes.

**Goal:** 把“我告诉教练一个想法，教练深度引导我把它做成代码”做成 Trainer 的核心强能力。

**Depends on:** F1

## Product Promise

- 用户只说 idea，也能被带着落地
- 教练能收窄范围、定义 MVP、拆当前步骤、给验证方式
- 不会直接变成一大坨系统计划，而是自然引导

## Read First

- [Master Index](./2026-05-02-trainer-learning-loop-master-index.md)
- [pedagogy/service.py](../../server/app/pedagogy/service.py)
- [implementation_coach.py](../../server/app/pedagogy/implementation_coach.py)

## Allowed Write Scope

- `server/app/pedagogy/service.py`
- `server/app/pedagogy/implementation_coach.py`
- `server/app/core/models.py`
- `server/app/api/routers.py`
- `server/app/llm/prompts.py`
- `shared/src/models.ts`
- `server/tests/test_pedagogy.py`
- `server/tests/test_api.py`

## Do Not Touch

- `server/app/research/**`
- `extension/webview/src/components/plan/**`

## Implementation Checklist

1. 强化 implementation guide：
   - idea summary
   - scope boundary
   - MVP
   - current step
   - validation strategy
   - risk notes
   - fallback step
2. 对没有清晰需求的 idea 做收窄与澄清
3. 对当前项目内 idea 给出实际切入文件或模块
4. 让教练优先引导用户自己做，而不是直接大段代写
5. 在卡住时允许切换到 rescue 模式

## Acceptance

- 纯 idea 输入也能得到清楚的落地路径
- 路径包含当前一步和验证方式
- 对已有项目能指出切入点而不是泛泛而谈
- `cd server && python -m pytest tests/test_pedagogy.py tests/test_api.py -v`

## Handoff

- 说明 implementation guide 与计划页如何衔接
- 标注项目提炼训练交给 F3
