# Trainer Task I1 Implementation Plan

> **For Claude/Codex:** implement only this task, keep write scope tight, and stop for review when acceptance passes.

**Goal:** 把 Trainer 的前后端主链联调到真实可用，并形成可以直接安装到 VS Code 的交付物，而不是只能调试运行。

**Depends on:** H3

## Product Promise

- 真实 VS Code 扩展链路可用
- 可打包成 `.vsix`
- 安装后不是黑屏，也不是只能本地 dev 打开

## Read First

- [Master Index](./2026-05-02-trainer-learning-loop-master-index.md)
- `package.json`
- `extension/package.json`

## Allowed Write Scope

- `extension/**`
- `server/app/**`
- `shared/src/**`
- `scripts/**`
- `docs/**`

## Do Not Touch

- 仅避免大范围无关重构

## Implementation Checklist

1. 跑通真实 sidecar 启动、健康检查、session 初始化、消息发送
2. 修复真实扩展里与浏览器预览的差异问题
3. 确保无 key、坏 key、sidecar 启动失败都不会黑屏
4. 配置打包流程，生成 `.vsix`
5. 更新安装与使用文档

## Acceptance

- `npm run build`
- 扩展可打包安装
- 安装后可正常打开、配置 key、发起对话
- `cd server && python -m pytest tests/ -v`

## Handoff

- 给出 VSIX 打包命令与安装说明
- 标注 अंतिम视觉和性能收口交给 I2
