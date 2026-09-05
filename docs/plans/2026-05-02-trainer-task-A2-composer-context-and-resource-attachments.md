# Trainer Task A2 Implementation Plan

> **For Claude/Codex:** implement only this task, keep write scope tight, and stop for review when acceptance passes.

**Goal:** 把输入框、上下文附带、文件/文件夹导入、发送快捷方式做成稳定的人性化主链，确保用户清楚知道“这次发送到底带了什么”。

**Depends on:** A1

## Product Promise

- 输入框安静、紧凑、像工具，不像表单
- 发送时的上下文来源清楚但不吵
- 支持最多 100 个文件或单文件夹导入
- 文件、选区、诊断、相关资源的附带规则可理解

## Read First

- [Master Index](./2026-05-02-trainer-learning-loop-master-index.md)
- [A1](./2026-05-02-trainer-task-A1-coach-shell-and-truthful-states.md)

## Allowed Write Scope

- `extension/webview/src/components/composer/`
- `extension/webview/src/app/App.tsx`
- `extension/webview/src/styles.css`
- `extension/webview/src/lib/browserSidecar.ts`
- `extension/src/commands/resourceCommands.ts`
- `extension/src/core/workbenchData.ts`
- `shared/src/sendIntelligence.ts`
- `server/app/api/routers.py`
- `server/tests/test_api.py`

## Do Not Touch

- `server/app/research/**`
- `server/app/pedagogy/**`

## Implementation Checklist

1. 重做输入区布局：更窄、更稳、更贴近 VS Code 侧栏
2. 保留高频图标操作，但控制为真正必要的少量入口
3. 统一发送快捷方式：
   - Enter / Shift+Enter
   - 中文输入法场景安全
   - 焦点恢复合理
4. 明确本轮上下文来源：
   - 当前文件
   - 选区
   - 诊断
   - 附带文件
   - 附带文件夹
5. 修复文件与文件夹导入：
   - 最多 100 个文件
   - 超限提示清楚
   - 不支持文件跳过提示清楚
6. 让导入结果在发送前后都有轻量反馈，不出现大分析面板
7. 后端确认资源请求结构稳定，避免前端显示成功但后端未真正收到

## Acceptance

- 可导入单文件、多个文件、单文件夹
- 超过 100 文件时有明确限制反馈
- 发送前用户能看懂本轮上下文
- 输入区无重边界强调，无错位
- `npm run build --prefix extension/webview`
- `npm run build --prefix extension`

## Handoff

- 说明发送链路里上下文字段的最终结构
- 标注还有哪些更深的项目理解要留给 F1
