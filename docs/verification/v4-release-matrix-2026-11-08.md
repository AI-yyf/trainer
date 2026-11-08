# V4 发布矩阵 — 三平台 VSIX（2026-11-08）

**结论：PASS（9/9 jobs；三平台 package + installed host E2E）**

- 工作流：`Trainer Cross-Platform Verify`（workflow_dispatch，`run_vsix_host_e2e=true`）
- Run：<https://github.com/AI-yyf/trainer/actions/runs/42506461999>
- Commit：`485e25e63e136f32861a209728e848fd930e464f`
- 结论：`success`，9/9 jobs
- 平台：macOS / Ubuntu 22.04 / Windows

## 三平台 VSIX

| 平台 | 文件 | Bytes | SHA-256 |
| --- | --- | --- | --- |
| macOS arm64 | `trainer-extension-1.4.1-darwin-arm64.vsix` | 134,009,884 | `21a008bfc56320de51a739ac32f26726933d32c24790de32324d81ccddebda70` |
| Linux x64 | `trainer-extension-1.4.1-linux-x64.vsix` | 168,944,187 | `7259776f3d4941868852e2b603116cbbe645a275f756bc6c252d83590a9205f6` |
| Windows x64 | `trainer-extension-1.4.1-win32-x64.vsix` | 104,763,576 | `3bf365671bc0b45e7bc9409bb0a5dd6f2647d988d992d20572b72b91a8a3aa80` |

三个 manifest 均为：

- `productVersion`: `1.4.1`
- `sourceCommit`: `485e25e…`
- `sourceDirty`: `false`

## 安装后主机 E2E

同一 run 的 Package 矩阵执行了真实安装 + installed host E2E：

| 平台 | host-report | 结果 |
| --- | --- | --- |
| macOS | `trainer-installed-host-macos-latest` | `ok: true` |
| Ubuntu 22.04 | `trainer-installed-host-ubuntu-22.04` | `ok: true` |
| Windows | `trainer-installed-host-windows-latest` | `ok: true` |

E2E 覆盖：安装扩展、激活、打开 sidebar、sidecar ready、workspace admission、resource upload、provider fixture、coach message、review queue、theory drill、scenario restore、next hop、resource detail、sandbox context、no in-Trainer preview command。

## 同 run 其他门禁

| Job 矩阵 | 结果 |
| --- | --- |
| Server (ubuntu/macos/windows) | ✅ 3/3 |
| UI (ubuntu/macos/windows) | ✅ 3/3（200 preview + 200 real-sidecar + recovery） |
| Package + installed host E2E (3 platforms) | ✅ 3/3 |

## 边界

- 这是当前 commit 的发布构建与安装证据；不等于 20 条旅程在三个平台逐条 GUI 归档。
- 真实公网 Provider 未在本 run 使用（fixture provider 仅验证连接/消息路径）。
- Remote-SSH 重连另见 `v4-remote-ssh-reconnect-2026-11-08.md`。
