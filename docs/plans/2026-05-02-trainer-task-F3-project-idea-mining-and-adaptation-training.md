# Trainer Task F3 Implementation Plan

> **For Claude/Codex:** implement only this task, keep write scope tight, and stop for review when acceptance passes.

**Goal:** 让 Trainer 能基于现有项目主动提炼训练题，也能跟随用户意图指导“如何按你的心意改造一个已完成项目”。

**Depends on:** F2

## Product Promise

- 教练不只是回答，还会主动从项目里抽训练机会
- 能做“项目提炼训练题”
- 能做“已完成项目改造指导”
- 这些都沉到底层能力中

## Read First

- [Master Index](./2026-05-02-trainer-learning-loop-master-index.md)
- [project_idea_miner.py](../../server/app/pedagogy/project_idea_miner.py)
- [project_adaptation_coach.py](../../server/app/pedagogy/project_adaptation_coach.py)

## Allowed Write Scope

- `server/app/pedagogy/project_idea_miner.py`
- `server/app/pedagogy/project_adaptation_coach.py`
- `server/app/pedagogy/service.py`
- `server/app/core/models.py`
- `server/app/api/routers.py`
- `server/app/llm/prompts.py`
- `shared/src/models.ts`
- `server/tests/test_project_adaptation.py`
- `server/tests/test_pedagogy.py`
- `server/tests/test_api.py`

## Do Not Touch

- `server/app/research/**`
- `extension/webview/src/components/settings/**`

## Implementation Checklist

1. 强化 project idea mining：
   - 从当前项目里找训练价值高的点
   - 生成不同难度的小任务
   - 标明为什么适合你现在练
2. 强化 project adaptation guide：
   - 改造目标
   - 影响范围
   - 优先改动路径
   - 风险和验证
3. 让这两类能力能自然回流到对话和计划
4. 对“我想把项目改成 X”这类输入进行专项优化

## Acceptance

- 能从项目里提炼至少一组清楚训练题
- 能对现有项目改造给出逐步指导
- 输出不只是概念说明，而是可执行路线
- `cd server && python -m pytest tests/test_project_adaptation.py tests/test_pedagogy.py tests/test_api.py -v`

## Handoff

- 标注真正的外部 repo 下载与素材来源交给 G1
