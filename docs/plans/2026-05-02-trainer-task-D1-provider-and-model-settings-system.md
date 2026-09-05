# Trainer Task D1 Implementation Plan

> **For Claude/Codex:** implement only this task, keep write scope tight, and stop for review when acceptance passes.

**Goal:** 把设置页做成真实完整、可恢复、可诊断的大模型接入系统，只保留大模型心智，不再让用户面对 embedding 等无关复杂度。

**Depends on:** C2

## Product Promise

- 没有 API key 就无法正常工作，但会被明确告知
- 配置后能自动获取模型列表
- 保存、测试连接、失败原因、工作区覆盖都清楚
- 设置完整但安静，不像后台管理表单

## Read First

- [Master Index](./2026-05-02-trainer-learning-loop-master-index.md)
- [Coach-first Full Delivery Plan](./2026-05-02-trainer-coach-first-full-delivery-plan.md)

## Allowed Write Scope

- `extension/webview/src/components/settings/`
- `extension/webview/src/app/App.tsx`
- `extension/webview/src/styles.css`
- `extension/src/provider/providerConfigStore.ts`
- `extension/src/commands/sessionCommands.ts`
- `extension/src/core/webviewBridge.ts`
- `shared/src/models.ts`
- `shared/src/providerStatus.ts`
- `server/app/llm/provider_service.py`
- `server/app/api/routers.py`
- `server/tests/test_provider_service.py`
- `server/tests/test_api.py`

## Do Not Touch

- `server/app/research/**`
- `server/app/pedagogy/**`

## Implementation Checklist

1. 统一 provider 配置模型：
   - provider name
   - base URL
   - api key
   - selected model
   - last test result
   - fetched model list
2. 支持配置后自动拉取模型列表
3. 无 key / key 无效 / base URL 错误 / 模型不可用时给出明确错误态
4. 支持连接测试、重试、清空配置、打开配置文件
5. 支持工作区级覆盖与默认配置说明
6. 前端展示保存状态、同步状态、最近测试结果
7. 后端 provider 列表请求支持缓存和降级处理

## Acceptance

- 配置 base URL + key 后可自动拉模型列表
- 无 key 时主链明确不可用，但不会黑屏
- 错误配置时能看到清楚的失败原因
- 设置页更完整但不臃肿
- `npm run build --prefix extension/webview`
- `npm run build --prefix extension`
- `cd server && python -m pytest tests/test_provider_service.py tests/test_api.py -v`

## Handoff

- 说明模型列表缓存策略和失效策略
- 标注更高级的 provider 能力是否留给后续版本
