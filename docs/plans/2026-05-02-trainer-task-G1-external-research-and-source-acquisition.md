# Trainer Task G1 Implementation Plan

> **For Claude/Codex:** implement only this task, keep write scope tight, and stop for review when acceptance passes.

**Goal:** 让 Trainer 真正具备按需向外学习的能力，能联网查资料、拉取网页正文、下载代码库线索，为教学服务。

**Depends on:** F3

## Product Promise

- `研究` 不是页面，而是后台能力
- 教练能按需查官方文档、文章、issue、repo 线索
- 外部学习服务于当前训练主线

## Read First

- [Master Index](./2026-05-02-trainer-learning-loop-master-index.md)
- [research/service.py](../../server/app/research/service.py)
- [ingest/service.py](../../server/app/ingest/service.py)

## Allowed Write Scope

- `server/app/research/service.py`
- `server/app/resources/service.py`
- `server/app/ingest/service.py`
- `server/app/api/routers.py`
- `server/app/core/models.py`
- `server/app/pedagogy/project_source_scout.py`
- `server/tests/test_api.py`

## Do Not Touch

- `extension/webview/src/components/plan/**`
- `extension/webview/src/components/settings/**`

## Implementation Checklist

1. 打开 URL 网络抓取的真实能力，并做好安全开关
2. 让 research 服务支持：
   - 网页正文抓取
   - repo 来源线索记录
   - 研究发现回流
3. 先做“按需研究”，不要做前台研究台
4. 研究结果必须带来源和时间信息
5. 为无网络、抓取失败、来源不可达提供降级

## Acceptance

- 给定 URL 能抓正文并进入资源流
- 教练可返回带来源的外部参考
- 外部研究结果以后台能力形式出现在消息流中
- `cd server && python -m pytest tests/test_api.py -v`

## Handoff

- 说明网络抓取开关与安全策略
- 标注真正的知识清洗交给 G2
