# Trainer Task H1 Implementation Plan

> **For Claude/Codex:** implement only this task, keep write scope tight, and stop for review when acceptance passes.

**Goal:** 建立 Trainer 的教学知识库，让它能把项目理解、用户历史、外部资料沉淀成可复用的教学资产，而不是每轮临时组织语言。

**Depends on:** G2

## Product Promise

- 教练会积累自己的教学素材
- 这些素材可复用于解释、出题、复习、改造指导
- 知识沉淀和用户记忆分层清楚

## Read First

- [Master Index](./2026-05-02-trainer-learning-loop-master-index.md)
- [G2](./2026-05-02-trainer-task-G2-knowledge-ingestion-curation-and-trust.md)

## Allowed Write Scope

- `server/app/core/models.py`
- `server/app/db/repository.py`
- `server/app/memory/service.py`
- `server/app/pedagogy/service.py`
- `server/app/api/routers.py`
- `server/tests/test_repositories.py`
- `server/tests/test_api.py`

## Do Not Touch

- `extension/webview/**`
- `server/app/research/**`

## Implementation Checklist

1. 定义教学知识资产：
   - concept card
   - implementation pattern
   - common pitfall
   - exercise seed
   - explanation recipe
2. 区分：
   - 用户个人记忆
   - 通用教学知识
   - 项目专属知识
3. 从项目理解、外部资料、历史教学中沉淀这些资产
4. 让后续教学能按需检索这些资产

## Acceptance

- 至少能沉淀并读取一批教学资产
- 资产能和用户记忆区分开
- `cd server && python -m pytest tests/test_repositories.py tests/test_api.py -v`

## Handoff

- 说明知识库实体结构
- 标注 H2/H3 如何使用这些资产
