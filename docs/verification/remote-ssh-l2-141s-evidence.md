# Remote-SSH L2 验收证据 — 验收机 141s（2026-11-06）

**结论：前置条件 PASS；第 1 步（服务端安装）已自动化执行并 PASS；第 2–6 步 PENDING-HUMAN。**

**2026-11-07 更新（真实执行记录）**：用远端 VS Code Server CLI
`code-server --install-extension ~/trainer-extension-1.4.0-linux-x64.vsix --force`
真实安装成功，`--list-extensions --show-versions` 返回 `local.trainer-extension@1.4.0`，
`~/.vscode-server/extensions/local.trainer-extension-1.4.0/package.json` 版本/发布者与
v1.4.0 一致（engine ^1.96.0）。

**同时发现真实阻断（已修，待新构件）**：v1.4.0 的 linux sidecar 依赖 GLIBC_2.38，
141s（Ubuntu 22.04）启动即失败（`libm.so.6: version GLIBC_2.38 not found`）；打包模式
仅有 bundled-binary 一条启动路径（源码侧车仅 Development 模式）。已把 release/
cross-platform 的 linux 构建基座改为 ubuntu-22.04（glibc 2.35），旧 release 资产
在 22.04/Debian 12 主机不可用，需随下一版发布替换。

**22.04 修复验证（真实主机）**：Cross-Platform 42257669713 产出的
`trainer-extension-1.4.0-linux-x64.vsix`（sha256 `63c9e433e35bc9e0…`）已装到 141s，
`bundled/bin/linux-x64/trainer-sidecar --help` 正常输出 usage（exit 0），
`trainer-sidecar --host 127.0.0.1 --port 34999` 启动后 `/health` 返回
`{"status":"ok","initialized":true,...}` —— glibc 阻断在 22.04 构建上消失。
注意：GitHub Release v1.4.0 的三平台资产仍是 24.04 构建（含此 bug），
正式对外需以 v1.4.1 重新发布 linux 构件。
配合清单：`docs/verification/p1-final-remote-ssh-l2-checklist.md`。

## 验收机与预置（全部自动化执行，PASS）

| 项 | 结果 | 证据 |
| --- | --- | --- |
| SSH 可达 | ✅ | `ssh 141s`（14.103.175.141, yunfei.yan）BatchMode 免密连通，`CONN_OK` |
| 远端 python3 | ✅ | Python 3.10.12 |
| 远端 git | ✅ | git 2.34.1 |
| VS Code Server | ✅ | Stable `110a328ea54b…` 已存在（用户此前连接过），`code-server` CLI 可用 |
| 测试工作区 | ✅ | `~/trainer-e2e/`（含 `src/queue_lock.py`，一个真实可读的小模块） |
| **linux-x64 VSIX 预置** | ✅ | `~/trainer-extension-1.4.0-linux-x64.vsix` = **官方 Release 资产**（170,287,950 字节，SHA-256 `4d6aa3bc…` 与 release manifest 完全一致；早期预置的 run 内构件 `0d6948…` 因 PyInstaller 字节级不可复现而替换） |

## 自动化回归层（区别于人工窗口层）

- Remote-SSH 夜间工作流持续绿（v1.3.4 时代连续 5 次 + 现分支各轮 CI Package 全绿）
- v1.4.0 跨平台 Verify（`42153160292`）9/9：Server/UI/Package × Windows/macOS/Ubuntu——
  linux-x64 VSIX 即由其 ubuntu Package job 产出并经 SHA 校验预置

## 6 步真窗口清单（需人在 VS Code → Remote-SSH 141s 窗口内执行）

| # | 步骤 | 状态 |
| --- | --- | --- |
| 1 | Remote-SSH 窗口安装 VSIX（Extensions → … → Install from VSIX… → `~/trainer-extension-1.4.0-linux-x64.vsix`） | ✅ PASS（自动化：远端 VS Code Server CLI 安装 + 版本/发布者核验；窗口内重载即生效） |
| 2 | 活动栏 Trainer 图标打开侧边栏（应进入 Coach 视图） | PENDING-HUMAN |
| 3 | 五视图切换 Coach / Plan / Resources / Training / Settings | PENDING-HUMAN |
| 4 | Coach 发一条关于远程项目的消息，流式完整回复 | PENDING-HUMAN |
| 5 | 设置中 attach 远程工作区（`~/trainer-e2e`）并确认信任状态 | PENDING-HUMAN |
| 6 | Companion capability 握手显示 verified（file/search/hash/verify） | PENDING-HUMAN |

执行完成后把结果回填本文件（或截图）即闭环；任何一步失败保留 VS Code 输出面板
Trainer 通道日志一并记录。

## 边界（如实）

- 步骤 1–6 依赖真实的人在 Remote-SSH VS Code Server 窗口内操作，无法机器人化断言
  （清单文件自身声明 §十 Layer 2 边界）；本文件把该步骤的人工成本降到零预置成本。
- 自动化回归层 ≠ 真窗口层：两层证据分开记录，不互相冒充。


## v1.4.1 官方资产验收（2026-11-07，替代此前 run 内构件）

- Release v1.4.1 linux-x64 资产 sha256 `149bbb92…` 与 build manifest `vsix.sha256` 完全一致
- 141s 服务端安装成功 → `local.trainer-extension@1.4.1`
- `bundled/bin/linux-x64/trainer-sidecar --help` exit 0；`--host 127.0.0.1 --port 34998`
  启动后 `/health` 返回 `{"status":"ok","initialized":true,...}`
- 结论：glibc 2.35 基座修复进入正式发布通道；2–6 步真窗口仍 PENDING-HUMAN
