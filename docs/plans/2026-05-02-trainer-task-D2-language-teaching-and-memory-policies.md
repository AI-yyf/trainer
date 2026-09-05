# Trainer Task D2 Implementation Plan

> **For Claude/Codex:** implement only this task, keep write scope tight, and stop for review when acceptance passes.

**Goal:** 把语言、回答风格、上下文附带策略、记忆范围、复习策略这些真正影响教学体验的设置做完整，并让它们对实际回复产生稳定作用。

**Depends on:** D1

## Product Promise

- 中文用户默认得到中文讲解
- 中英文切换是设置能力，而不是消息里的偶然行为
- 回答风格、记忆范围、复习节奏都有明确可理解的含义
- 设置改变后会真实影响教练行为

## Read First

- [Master Index](./2026-05-02-trainer-learning-loop-master-index.md)
- [D1](./2026-05-02-trainer-task-D1-provider-and-model-settings-system.md)

## Allowed Write Scope

- `extension/webview/src/components/settings/`
- `extension/webview/src/styles.css`
- `extension/src/core/workbenchData.ts`
- `shared/src/models.ts`
- `shared/src/protocol.ts`
- `server/app/core/models.py`
- `server/app/api/routers.py`
- `server/app/llm/prompts.py`
- `server/app/memory/service.py`
- `server/tests/test_api.py`

## Do Not Touch

- `server/app/research/**`
- `server/app/ingest/**`

## Implementation Checklist

1. 完整定义可配置策略：
   - language
   - answer mode
   - teaching style
   - follow current file
   - include selection
   - include diagnostics
   - memory enabled scope
   - review cadence
2. 设置页文案用用户语言描述，不暴露内部字段名
3. 保存后立即生效，并回传到 session 快照
4. prompt 层显式使用这些设置
5. 让同一个工作区的后续对话能稳定续用这些策略
6. 做中英文场景回归，避免“中文界面但英文回复”

## Acceptance

- 中文设置下，默认中文回复稳定
- 英文设置下，默认英文回复稳定
- answer mode 等设置能看见实际行为变化
- `cd server && python -m pytest tests/test_api.py -v`
- `npm run build --prefix extension/webview`

## Handoff

- 说明设置与 prompt 的映射关系
- 标注哪些长期画像策略留给 E1 细化
