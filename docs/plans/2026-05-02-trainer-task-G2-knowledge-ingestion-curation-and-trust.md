# Trainer Task G2 Implementation Plan

> **For Claude/Codex:** implement only this task, keep write scope tight, and stop for review when acceptance passes.

**Goal:** 把 Trainer 的外部学习从“抓到了内容”推进到“有可信度、有去重、有时效、有沉淀价值”的知识摄取系统。

**Depends on:** G1

## Product Promise

- 教练不会把抓来的所有信息都当真
- 会知道来源质量、是否重复、是否过期
- 有用知识会进入长期教学底座

## Read First

- [Master Index](./2026-05-02-trainer-learning-loop-master-index.md)
- [G1](./2026-05-02-trainer-task-G1-external-research-and-source-acquisition.md)

## Allowed Write Scope

- `server/app/ingest/service.py`
- `server/app/resources/service.py`
- `server/app/core/models.py`
- `server/app/db/repository.py`
- `server/app/api/routers.py`
- `server/tests/test_api.py`
- `server/tests/test_repositories.py`

## Do Not Touch

- `extension/webview/src/components/coach/**`
- `server/app/pedagogy/**`

## Implementation Checklist

1. 为外部知识增加元数据：
   - source type
   - fetched at
   - trust score
   - freshness
   - duplicate key
2. 做最小去重和来源评分
3. 对 repo/readme/web page/pdf 等来源做统一摘要结构
4. 为后续教学知识库输出干净片段
5. 对低可信、过期、冲突信息做降权或标记

## Acceptance

- 新抓到的外部知识带来源和可信度
- 重复内容不会无限堆积
- 资源服务能输出适合 H1 使用的知识片段
- `cd server && python -m pytest tests/test_api.py tests/test_repositories.py -v`

## Handoff

- 给出知识片段的最终结构
- 标注 H1 如何消费这些片段
