# MCP（Model Context Protocol）接入

Trainer 的教练代理可以通过最小 MCP 客户端调用外部 MCP 服务器（Gitee、
GitHub 等）的工具。这一层刻意只做 stdio 传输的
`initialize` / `tools/list` / `tools/call` 子集，默认关闭、显式启用。

- 客户端实现：`server/app/llm/mcp_client.py`
- 工具注册：发现到的每个工具都以 `mcp_<server>_<tool>` 的名字挂进 ReAct
  代理的 `ToolRegistry`（`server/app/llm/tools.py` 的
  `build_default_tool_registry(extra_tools=...)`），由
  `server/app/llm/provider_service.py` 在每一轮教练回合前发现并注入。
- 状态可见性：`GET /mcp/status`（`server/app/api/routes/mcp.py`）。

## 配置

配置只有一个来源：sidecar 进程的环境变量 `TRAINER_MCP_SERVERS`，值为 JSON
数组。为空或不设置 = MCP 不启用。

```json
[
  {
    "name": "gitee",
    "command": "npx",
    "args": ["-y", "@gitee/mcp-gitee@latest"],
    "env": { "GITEE_ACCESS_TOKEN": "<你的 Gitee 私人令牌>" }
  },
  {
    "name": "github",
    "command": "docker",
    "args": [
      "run", "-i", "--rm",
      "-e", "GITHUB_PERSONAL_ACCESS_TOKEN",
      "ghcr.io/github/github-mcp-server"
    ],
    "env": { "GITHUB_PERSONAL_ACCESS_TOKEN": "<你的 GitHub PAT>" }
  }
]
```

字段说明：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `name` | 是 | 服务器短名，只允许 `[A-Za-z0-9_-]`（其余字符会被替换为 `_`）。它决定工具前缀。重名条目会被跳过。 |
| `command` | 是 | 可执行文件路径或命令名，直接在 sidecar 所在机器上 `exec`。 |
| `args` | 否 | 命令参数数组；单个字符串会被当作一个参数。 |
| `env` | 否 | 追加到继承环境之上的环境变量（如访问令牌）。 |

### Gitee 官方 MCP server

[mcp-gitee](https://gitee.com/oschina/mcp-gitee) 提供预编译二进制、`go install
gitee.com/oschina/mcp-gitee@latest` 和 npx 三种方式，默认就是 stdio 传输：

- `command`: `npx`，`args`: `["-y", "@gitee/mcp-gitee@latest"]`（或直接指向
  `mcp-gitee` 二进制）
- 必需环境变量：`GITEE_ACCESS_TOKEN`；可选 `GITEE_API_BASE`
  （如 `https://gitee.com/api/v5`）。

### GitHub 官方 MCP server

[github-mcp-server](https://github.com/github/github-mcp-server) 官方分发 Docker
镜像与 Go 二进制，stdio 模式：

- Docker：`command` 为 `docker`，`args` 为
  `["run", "-i", "--rm", "ghcr.io/github/github-mcp-server"]`；令牌用 `env`
  传入 `GITHUB_PERSONAL_ACCESS_TOKEN`。
- 本地二进制：`command` 指向 `github-mcp-server`，`args` 为 `["stdio"]`。
- 可用 `--toolsets` / `GITHUB_TOOLSETS` 收窄暴露的工具集（推荐只开
  `repos,issues,pull_requests` 这类需要的集合）。

> VS Code 侧的 workspace 设置由扩展宿主在启动 sidecar 时投影为该环境变量
> （`extension/src/core/sidecarProcessManager.ts` 的进程环境），设置面板的
> 可视化编辑属于扩展侧后续工作；当前可用 `GET /mcp/status` 查看状态。

## 状态可见性与失败呈现

`GET /mcp/status` 返回设置面板所需的事实，不做静默：

```json
{
  "enabled": true,
  "config_source": "TRAINER_MCP_SERVERS",
  "server_count": 2,
  "tool_count": 6,
  "servers": [
    { "name": "gitee", "status": "ok", "protocol_version": "2025-03-26",
      "tool_count": 6, "tool_names": ["list_user_repos", "..."],
      "detail": null, "message": null },
    { "name": "github", "status": "unavailable", "tool_count": 0,
      "tool_names": [], "detail": "MCP server 'github' could not start: FileNotFoundError: ...",
      "message": "MCP 服务器不可用" }
  ]
}
```

- `status` 为 `ok` / `unavailable`（未探测过时为 `unprobed`）。
- 进程起不来、握手超时、服务器中途退出、`tools/list` 失败都会把该服务器标成
  `unavailable`，带上 `detail` 诊断和中文 `message`「MCP 服务器不可用」。
- 服务器不可用只会让它的工具缺席；其他服务器的工具照常注册。模型调用到已
  下线服务器的工具时会收到 `mcp_server_unavailable` / `mcp_timeout` 的结构化
  错误（工具消息回灌），不会假装成功。

## 安全边界

1. **显式启用、本地进程**：只有 `TRAINER_MCP_SERVERS` 里明确列出的命令会被
   执行；无配置即零进程、零工具。本切片不支持远程 SSE/HTTP 传输。
2. **权限阶梯门控**：每个工具按名字映射到 workspace 操作类型
   （`server/app/llm/mcp_client.py` 的 `classify_mcp_tool_operation`）：
   - 只读查看类（`get_*`、`list_*`、`search_*` 等）默认放行；存在 workspace
     authority 时会把这次调用记入操作账本（`mcp://<server>/<tool>`）。
   - 写操作走既有六档权限阶梯：`update/write/upload` → APPLY，
     `create/create_issue/push/merge` → GENERATE，`move/rename` → REORGANIZE，
     `delete/remove` → DESTRUCTIVE。默认档位下这些全部拒绝；且
     REORGANIZE 及以上在未受信/远程 workspace 上一律拒绝，权限授予也不能
     绕过（与内置工具同一门控）。
   - **失败关闭**：名字里没有可识别动词的工具按写操作处理。
   - 没有 workspace authority 时，只读工具仍可用；写操作返回
     `workspace_authority_unavailable`。
3. **凭据不进 Trainer 存储**：令牌通过 `env` 直接传给 MCP 子进程环境；Trainer
   不读取、不持久化这些值，也不会把它们写进日志或状态响应（状态只含服务器名、
   工具名和错误摘要）。
4. **子进程生命周期**：会话惰性启动、按服务器复用；`tools/call` 超时只会让
   当次调用返回 `mcp_timeout`，不会杀掉服务器；服务器崩溃/管道断开时会话被
   丢弃并标记 `unavailable`，下一轮可以重新拉起；sidecar 退出时统一关闭
   （先关 stdin 等优雅退出，再 terminate，最后 kill）。
5. **stdout 是协议通道**：服务器往 stdout 写入非 JSON 行只会被忽略并告警，
   不会破坏后续请求；stderr 被持续排空，防止子进程因管道写满而卡死。
6. **工具命名**：`mcp_<server>_<tool>`，非法字符替换为 `_`，超长截断到 128
   字符，同名冲突追加 `_2`、`_3` 后缀；与内置工具重名时跳过并告警。

## 超时与限额（当前默认值）

| 项 | 默认 | 位置 |
| --- | --- | --- |
| initialize 握手 | 10s | `DEFAULT_INITIALIZE_TIMEOUT_SECONDS` |
| tools/list | 10s | `DEFAULT_LIST_TIMEOUT_SECONDS` |
| tools/call | 30s | `DEFAULT_CALL_TIMEOUT_SECONDS` |
| 每个服务器工具数上限 | 256 | `MAX_TOOLS_PER_SERVER` |
| 分页轮数上限 | 8 | `MAX_LIST_PAGES` |

## 测试

`server/tests/test_mcp_client.py` 用真实 python 子进程桩服务器
（`server/tests/mcp_stub_server.py`，实现 initialize / tools-list / tools-call
最小 JSON-RPC stdio 回环）覆盖：配置解析、发现与调用、协议版本协商、env
透传、惰性回环容忍、权限阶梯（读放行 / 写拒绝 / 授予后放行 / 未受信拒绝）、
启动失败与崩溃的不可用呈现、调用超时后进程存活、退出清理。

```bash
cd server && .venv/bin/python -m pytest tests/test_mcp_client.py -q
```
