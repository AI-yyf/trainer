# V4 完整性旅程：版本变化 / 记忆撤销 / Provider 故障注入（2026-11-08）

**结论：PASS（真实 sidecar 进程 + 真实 HTTP，不是 TestClient）**

- 运行方式：真实 `run_sidecar.py` 子进程，临时数据目录
- 原始产物：`docs/verification/v4-integrity-journeys.json`
- 可复现脚本：`scripts/record-v4-integrity-journeys.py`
- Provider 故障：本机 hanging HTTP endpoint，`request_defaults.timeout=5`
- 未使用任何真实 Provider 密钥；本次不构成 P（真实模型）证据

## 1. 资料版本变化（旅程 15）

1. 上传 `versioned.md` v1 并索引；
2. 启动 training attempt，记录一条引用该资料的 evidence；
3. 修改磁盘内容后重新索引，content hash 从 `09fe…` 变为 `3e25…`；
4. 用旧 `resource_version_id` 再记录 evidence。

结果：

| 断言 | 结果 |
| --- | --- |
| content hash 变化 | ✅ |
| 旧 version 被拒绝 | ✅ HTTP 409 |
| 冲突码 | `resource_version_conflict` |
| 响应带 current version id | ✅ |

这说明旧引用不会静默挂到新版本上。

## 2. 记忆偏好覆盖与撤销（旅程 19）

| 操作 | 结果 |
| --- | --- |
| 保存 `teaching_style=hands-on` | ✅ profile 返回 `hands-on` |
| 覆盖为 `concept-first` | ✅ profile 返回 `concept-first` |
| 写入 global `tone=direct` + 长期目标 | ✅ |
| 传空 preferences / goals 撤销 | ✅ 返回 `{}` / `[]` |

这说明偏好不是只写不读，撤销后真实存储也清空。

## 3. Provider 故障注入（旅程 17）

- 本机 endpoint 接收请求后挂起 20 秒；
- Provider 客户端 5 秒超时；
- `/session/message` 在约 10.7 秒内返回诚实的失败回复：

> Trainer 当前卡在 provider path，所以这轮 coaching 还不能继续。……详情：Provider test failed: Provider request failed.

| 断言 | 结果 |
| --- | --- |
| 返回非空失败说明 | ✅ |
| 不伪造训练答案 | ✅ |
| 在超时预算内返回 | ✅ |
| HTTP 200 + 明确失败文案 | ✅ |

## 复现

```bash
server/.venv/bin/python scripts/record-v4-integrity-journeys.py
```

## 边界

- 版本变化使用真实 sidecar HTTP；未在真实 VS Code GUI 中逐屏录制。
- 记忆撤销验证的是持久化 profile/global memory；真实模型下一轮的措辞变化仍属于 P 旅程。
- Provider 故障是本地挂起 endpoint，不是公网网关的真实中断；真实网关故障仍标 PARTIAL。
