# V4 发布矩阵 — 三平台 VSIX（2026-11-08）

**结论：PASS（9/9 jobs；三平台 package + installed host E2E）**

- 工作流：`Trainer Cross-Platform Verify`（workflow_dispatch，`run_vsix_host_e2e=true`）
- Run：<https://github.com/AI-yyf/trainer/actions/runs/42532625761>
- Commit：`10fbeb3e4c845e993f5deb57e699d602a0eda051`
- 结论：`success`，9/9 jobs
- 平台：macOS / Ubuntu 22.04 / Windows

## 三平台 VSIX

| 平台 | 文件 | Bytes | SHA-256 |
| --- | --- | --- | --- |
| macOS arm64 | `trainer-extension-1.4.1-darwin-arm64.vsix` | 134,018,007 | `09ef5b635b35555e48e9ccaa618ed840b296f96f5b8eaf13115fa63983317284` |
| Linux x64 | `trainer-extension-1.4.1-linux-x64.vsix` | 168,949,316 | `f5c389fea26fdfb6872565b82dc9ab242ee9358ee792115415d315def204b3fb` |
| Windows x64 | `trainer-extension-1.4.1-win32-x64.vsix` | 104,770,331 | `f736cda8d7e99548a1bab0a36e97479961555c713611c54f3829a7019822a1ed` |

三个 manifest 均为：

- `productVersion`: `1.4.1`
- `sourceCommit`: `10fbeb3…`
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
