# Trainer Task H3 Implementation Plan

> **For Claude/Codex:** implement only this task, keep write scope tight, and stop for review when acceptance passes.

**Goal:** 建立 Trainer 的教学效果评估和自我改进闭环，让它不是只会“回答”，而是会根据教学结果变得更会教。

**Depends on:** H2

## Product Promise

- 教练知道你是不是学会了
- 会根据失败点和重复错误调整策略
- 会把成功/失败经验沉淀回知识库和记忆

## Read First

- [Master Index](./2026-05-02-trainer-learning-loop-master-index.md)
- [evaluator/service.py](../../server/app/evaluator/service.py)

## Allowed Write Scope

- `server/app/evaluator/service.py`
- `server/app/memory/service.py`
- `server/app/pedagogy/service.py`
- `server/app/core/models.py`
- `server/app/api/routers.py`
- `server/app/db/repository.py`
- `server/tests/test_training_flow_integration.py`
- `server/tests/test_api.py`

## Do Not Touch

- `extension/webview/**`
- `server/app/research/**`

## Implementation Checklist

1. 定义教学效果信号：
   - code landed
   - tests passed
   - repeated error
   - concept answered correctly
   - task abandoned
2. 把这些信号回写到：
   - 用户记忆
   - 弱点画像
   - 教学知识资产
3. 根据效果调整后续：
   - hint depth
   - challenge level
   - review urgency
   - explanation strategy
4. 做一条最小“教练自我改进”路径：
   - 发现某类题老失败
   - 下次换更合适的训练方式

## Acceptance

- 连续失败时，后续策略会变化
- 成功完成后，会更新掌握度与后续复习强度
- 集成测试能体现效果回写闭环
- `cd server && python -m pytest tests/test_training_flow_integration.py tests/test_api.py -v`

## Handoff

- 说明“学习效果 -> 记忆/知识/策略”的更新路径
- 标注最终集成交给 I1/I2
