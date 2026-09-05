# Trainer Task B2 Implementation Plan

> **For Claude/Codex:** implement only this task, keep write scope tight, and stop for review when acceptance passes.

**Goal:** 把研究、诊断、记忆、附带资源这些“后台能力”做成消息流里的轻量信息，而不是独立页面或大分析模块。

**Depends on:** B1

## Product Promise

- 用户知道这条回复参考了什么
- 这些信息不抢主内容，不像仪表盘
- 无关内容可以折叠
- `研究` 只体现为后台能力，不体现为新页面

## Read First

- [Master Index](./2026-05-02-trainer-learning-loop-master-index.md)
- [B1](./2026-05-02-trainer-task-B1-natural-chat-message-system.md)

## Allowed Write Scope

- `extension/webview/src/components/coach/`
- `extension/webview/src/app/App.tsx`
- `extension/webview/src/styles.css`
- `shared/src/sendIntelligence.ts`
- `shared/src/models.ts`
- `shared/src/protocol.ts`
- `server/app/api/routers.py`
- `server/app/core/models.py`
- `server/tests/test_api.py`

## Do Not Touch

- `extension/webview/src/components/settings/**`
- `server/app/research/service.py`

## Implementation Checklist

1. 定义轻量 intelligence 模型：
   - used current file
   - used selection
   - used diagnostics
   - used attached resources
   - used memory
   - used deeper analysis
2. 前端把 intelligence 做成可折叠的小信息条，不做大面板
3. 教练消息正文始终优先，intelligence 只做辅助理解
4. 研究结果在 UI 上统一表述为“教练额外查了/参考了”
5. 避免出现用户必须理解内部术语才能看懂的字段
6. 为无 intelligence 的普通回复保留纯净消息流

## Acceptance

- 用户能看懂“这条回复用了什么”
- 不会出现独立 research 视图依赖
- intelligence 可折叠，不干扰主消息
- `npm run build --prefix extension/webview`
- `cd server && python -m pytest tests/test_api.py -v`

## Handoff

- 给出 intelligence payload 的最终字段定义
- 标注哪些真正的外部研究能力要留给 G1/G2
