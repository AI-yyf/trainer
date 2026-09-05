# Trainer Task B1 Implementation Plan

> **For Claude/Codex:** implement only this task, keep write scope tight, and stop for review when acceptance passes.

**Goal:** 让 Trainer 的消息流像 GPT/Codex 一样自然易懂，而不是结构化报告页；同时保留代码块、表格、公式、Mermaid 与思维导图渲染能力。

**Depends on:** A2

## Product Promise

- 教练回复默认是自然 prose
- 用户和 Trainer 的消息一眼区分
- 长内容可折叠，但摘要必须是人话
- 支持代码块、表格、公式、Mermaid

## Read First

- [Master Index](./2026-05-02-trainer-learning-loop-master-index.md)
- [A2](./2026-05-02-trainer-task-A2-composer-context-and-resource-attachments.md)

## Allowed Write Scope

- `extension/webview/src/components/coach/`
- `extension/webview/src/app/App.tsx`
- `extension/webview/src/styles.css`
- `server/app/llm/prompts.py`
- `server/tests/test_provider_service.py`

## Do Not Touch

- `extension/webview/src/components/plan/**`
- `server/app/memory/**`
- `server/app/research/**`

## Implementation Checklist

1. 梳理消息流的最小层级：
   - 用户消息
   - 教练消息
   - 折叠补充块
2. 减少默认结构化段落和标签感
3. 保留 markdown 富渲染，并校正小字体、行高、代码块边距
4. 增加对长内容的渐进折叠，不要默认塞满整个侧栏
5. 优化系统 prompt，让回答更像自然教练而不是系统汇报
6. 中文输入时优先自然中文回复；英文同理
7. 对示例代码做多语言代码块渲染回归检查

## Acceptance

- 中文问题收到自然中文讲解
- 长消息在不展开时也容易理解
- 代码块、表格、公式、Mermaid 正常显示
- 信息流整体更小、更清楚，不堆叠大卡片
- `npm run build --prefix extension/webview`
- `cd server && python -m pytest tests/test_provider_service.py -v`

## Handoff

- 说明 prompt 调整了哪些输出倾向
- 标记是否还有少量结构化结果要留给 B2 处理
