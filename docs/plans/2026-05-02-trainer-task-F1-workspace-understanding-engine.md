# Trainer Task F1 Implementation Plan

> **For Claude/Codex:** implement only this task, keep write scope tight, and stop for review when acceptance passes.

**Goal:** 建立 Trainer 对当前项目的理解引擎，让它不只是“收到几个文件”，而是能提炼目录结构、关键模块、改造入口和训练机会。

**Depends on:** E2

## Product Promise

- 教练能看懂当前项目的大致结构
- 能指出从哪里进入实现/改造更合理
- 能从项目里提炼训练机会
- 不要求前台增加新入口

## Read First

- [Master Index](./2026-05-02-trainer-learning-loop-master-index.md)
- [resources/service.py](../../server/app/resources/service.py)
- [ingest/service.py](../../server/app/ingest/service.py)

## Allowed Write Scope

- `server/app/resources/service.py`
- `server/app/ingest/service.py`
- `server/app/core/models.py`
- `server/app/api/routers.py`
- `server/app/pedagogy/service.py`
- `server/app/pedagogy/project_idea_miner.py`
- `server/app/memory/service.py`
- `shared/src/models.ts`
- `server/tests/test_api.py`

## Do Not Touch

- `server/app/research/**`
- `extension/webview/src/components/settings/**`

## Implementation Checklist

1. 扩展资源与工作区理解模型：
   - repo summary
   - entry points
   - likely feature lanes
   - risk zones
   - training opportunities
2. 当用户附带文件/文件夹时，生成轻量项目理解摘要
3. 把项目理解沉入教练后台，不作为独立研究页
4. 优先支持当前项目内的 idea 落地和改造指导
5. 为大项目提供摘要限制与降级策略，避免拖慢回复

## Acceptance

- 附带项目资源后，教练能指出较合理的切入点
- 同一工作区的后续对话能复用项目理解摘要
- `cd server && python -m pytest tests/test_api.py -v`

## Handoff

- 说明项目理解摘要的数据结构
- 标注 idea-to-code 交给 F2 深化
