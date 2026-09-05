# Trainer Task I2 Implementation Plan

> **For Claude/Codex:** implement only this task, keep write scope tight, and stop for review when acceptance passes.

**Goal:** 对 Trainer 做最后一轮体验、视觉、性能和发布验收，把它收口成一个真正高级、细腻、可长期使用的产品。

**Depends on:** I1

## Product Promise

- 字体、图标、边距、层级、状态都细腻统一
- 性能和首屏稳定
- 具备发布前验收清单

## Read First

- [Master Index](./2026-05-02-trainer-learning-loop-master-index.md)
- [I1](./2026-05-02-trainer-task-I1-end-to-end-integration-and-vsix-delivery.md)

## Allowed Write Scope

- `extension/webview/src/**`
- `extension/src/**`
- `shared/src/tokens.ts`
- `docs/**`

## Do Not Touch

- `server/app/research/**` unless blocked by release bug

## Implementation Checklist

1. 统一字体大小、图标基线、消息气泡、输入区、计划页和设置页节奏
2. 精修空状态、错误态、加载态、折叠态
3. 处理大包体、按需拆分、首屏渲染和滚动体验
4. 补齐发布前检查清单：
   - 中文/英文
   - 无 key / 有 key
   - 附带文件 / 文件夹
   - 长消息 / 代码块 / Mermaid
   - 计划更新
   - 设置保存
5. 完成 release acceptance 文档

## Acceptance

- 首屏稳定，交互细腻
- 主要状态无视觉破损
- 有发布验收清单和结果
- `npm run build`

## Handoff

- 给出最终发布前 checklist
- 标记仍存在的已知风险
