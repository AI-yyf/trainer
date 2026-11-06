# Remote-SSH L2 验收证据 — 验收机 141s（2026-11-06）

**结论：前置条件与预置全 PASS；6 步真窗口清单 PENDING-HUMAN（验收包已就位）。**
配合清单：`docs/verification/p1-final-remote-ssh-l2-checklist.md`。

## 验收机与预置（全部自动化执行，PASS）

| 项 | 结果 | 证据 |
| --- | --- | --- |
| SSH 可达 | ✅ | `ssh 141s`（14.103.175.141, yunfei.yan）BatchMode 免密连通，`CONN_OK` |
| 远端 python3 | ✅ | Python 3.10.12 |
| 远端 git | ✅ | git 2.34.1 |
| VS Code Server | ✅ | Stable `110a328ea54b…` 已存在（用户此前连接过），`code-server` CLI 可用 |
| 测试工作区 | ✅ | `~/trainer-e2e/`（含 `src/queue_lock.py`，一个真实可读的小模块） |
| **linux-x64 VSIX 预置** | ✅ | `~/trainer-extension-1.4.0-linux-x64.vsix`（170,286,390 字节）；SHA-256 前 16 位本地/远端一致 `0d694830e345b5b5` |

## 自动化回归层（区别于人工窗口层）

- Remote-SSH 夜间工作流持续绿（v1.3.4 时代连续 5 次 + 现分支各轮 CI Package 全绿）
- v1.4.0 跨平台 Verify（`42153160292`）9/9：Server/UI/Package × Windows/macOS/Ubuntu——
  linux-x64 VSIX 即由其 ubuntu Package job 产出并经 SHA 校验预置

## 6 步真窗口清单（需人在 VS Code → Remote-SSH 141s 窗口内执行）

| # | 步骤 | 状态 |
| --- | --- | --- |
| 1 | Remote-SSH 窗口安装 VSIX（Extensions → … → Install from VSIX… → `~/trainer-extension-1.4.0-linux-x64.vsix`） | PENDING-HUMAN |
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
