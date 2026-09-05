# Trainer Task H2 Implementation Plan

> **For Claude/Codex:** implement only this task, keep write scope tight, and stop for review when acceptance passes.

**Goal:** 把 Trainer 的“会教”做成正式能力层，包括多种教学模式、题目生成、原理解释和训练策略切换。

**Depends on:** H1

## Product Promise

- 同一个教练可以切不同教学模式
- 不只是计划，还能讲概念、出工程题、做改造训练、解释原理
- 这些模式来自后端教练能力，不是前台堆开关

## Read First

- [Master Index](./2026-05-02-trainer-learning-loop-master-index.md)
- [principle_explainer.py](../../server/app/pedagogy/principle_explainer.py)

## Allowed Write Scope

- `server/app/pedagogy/service.py`
- `server/app/pedagogy/principle_explainer.py`
- `server/app/pedagogy/project_idea_miner.py`
- `server/app/core/models.py`
- `server/app/llm/prompts.py`
- `server/app/api/routers.py`
- `shared/src/models.ts`
- `server/tests/test_pedagogy.py`
- `server/tests/test_api.py`

## Do Not Touch

- `extension/webview/src/components/settings/**`
- `server/app/research/**`

## Implementation Checklist

1. 固化教学模式：
   - planning
   - idea implementation
   - concept teaching
   - engineering challenge
   - project adaptation
   - review reflection
   - principle explanation
2. 为不同模式定义不同输出结构与策略
3. 增强题目生成：
   - 基于当前项目
   - 基于用户弱点
   - 基于外部 repo/案例
4. 让题目和讲解能够引用 H1 的教学知识资产

## Acceptance

- 不同教学场景下输出策略明显不同
- 能生成项目相关的工程训练题
- 原理解释更像教练，而不是百科
- `cd server && python -m pytest tests/test_pedagogy.py tests/test_api.py -v`

## Handoff

- 说明模式决策入口与 exercise 结构
- 标注效果评估交给 H3
