# P4 — 真实 Provider 回归（2026-11-06）

**结论：PASS（6 项中 5 PASS + 1 NOT_EXECUTED）** — 解除 VNEXT-PROGRAM §九 P4 BLOCKED 状态。

## 环境

| 项 | 值 |
| --- | --- |
| Provider 网关 | OpenAI 兼容网关（MiniMax 系列，用户提供；URL/key 不落库，仅进程环境注入） |
| 模型 | `MiniMax-M3`（推理模型，`openai_chat_completions_compatible` 协议） |
| Sidecar | 真实进程 `run_sidecar.py --host 127.0.0.1 --port 8765`（非 TestClient） |
| 网络 | 真实公网 HTTP 网关（明文 HTTP——见风险 #1） |

## 实测结果

| # | 项 | 结论 | 证据 |
| --- | --- | --- | --- |
| 1 | Provider 连通 smoke（`scripts/provider-smoke.mjs`） | PASS | `ok: true, category: success, elapsedMs: 957` |
| 2 | 真实教学轮（`scripts/trainer-turn-smoke.mjs`） | PASS | `ok: true`，70 个流式 chunk，191s；provider_test → /turn/stream → remote_workspace → debug_loop → function 场景断言全过（scenario/current_focus/焦点防串染/语言本地化） |
| 3 | 长讲义截断（定向探测） | PASS | 请求完整生成器讲义 → **完整 2068 字**写入沙箱 notes 并注册资源（§0-§8 全：yield 执行模型/生成器表达式/send/close/迭代器协议/双场景/验证练习），回复为状态摘要 + 资源引用，无 `truncated_or_empty`；此前「推理模型吃掉 max_tokens 导致空回复」问题**未复现**（provider-smoke 的 generous probe budget 机制生效） |
| 4 | 工具成功不被 generic reanchor 覆盖（定向探测） | PASS | Agent 真实调用读文件工具读取 `sentinel_probe.py`，最终回复引用真实内容（`p4_probe_sentinel` / `"SENTINEL-P4-OK"`），grounding 成立 |
| 5 | 新会话首条消息（定向探测） | PASS | `session/start` 后立即 `/turn`（use_agent_loop: true），首条消息得到正确相关回复（Mermaid TD vs LR） |
| 6 | 空响应 recovery | NOT_EXECUTED | 健康网关无法强制制造空响应；该路径由脚本化 recovery 测试（`coaching_recovery.py` 套件）覆盖，非真模型可验证项 |

## 探测产物

- 探测脚本：`/tmp/p4-real-provider-probe.mjs`（临时文件，不入库；key 走 `TRAINER_TEST_*` 环境变量）
- 讲义资源：`resource-1374c6bd75`（工作区 `p4-long-lecture-*`，沙箱 lane 内 `notes/python-generators-lazy-evaluation.md`）

## 风险与备注

1. **网关为明文 HTTP**（`http://` 非 `https://`）：key 在传输路径上可被中间人观测。建议生产使用 HTTPS 端点；本次仅用于回归验证。
2. **key 已在聊天通道明文传递**：建议用户在验证完成后轮换该 key。
3. MiniMax-M3 推理延迟显著（短轮次 ~1s probe，完整教学轮 191s）：属模型侧特性，不是 Trainer 截断/超时缺陷；provider-smoke 已按 MiniMax 族自动放大 probe 预算（1024 输出 token）。
4. 空响应/网关误标路径仍依赖脚本化测试 + 本次未复现，保持观察项。

## 门禁账

- 本轮全部真实调用，无 mock Provider 参与（#6 除外，显式标注）。
- VNEXT-PROGRAM §九 状态更新：P4 ✅（本文件为证据）；下一入口 P5（tag + 发布 + 安全审计，对外动作需用户批准）。
