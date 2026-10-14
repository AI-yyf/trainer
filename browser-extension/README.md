# Trainer Capture（浏览器拓展）

一键把**当前网页 / PDF 链接 / GitHub 仓库**添加到 Trainer 资料库的 Chromium MV3 拓展。

## 设计边界

- **纯数据通道**：拓展不注入任何页面脚本，不读取页面内容，只发送 `{url, kind, title, workspace_id}`。
- **服务端抓取**：正文由本地 Trainer sidecar 抓取与解析（网页 → trafilatura 正文；PDF → 下载后走 PDF ingest；GitHub → 记录 repo URL + 默认分支 README）。
- **只有两个权限面向本地**：`host_permissions` 仅覆盖 `http://127.0.0.1/*` 与 `http://localhost/*`。

## 加载（开发者模式）

1. 打开 `chrome://extensions`（Edge 为 `edge://extensions`），开启右上角「开发者模式」。
2. 点击「加载已解压的扩展程序」，选择本目录（`browser-extension/`）。
3. 保持 Trainer 的 sidecar 在运行（VS Code 中打开 Trainer 即可）。

也可以在仓库根目录执行 `npm run package:browser-extension` 生成
`dist/trainer-capture-extension.zip`，解压后再按上面步骤加载。

## 使用

在网页或链接上右键：

| 菜单 | 采集内容 |
| --- | --- |
| 添加到 Trainer 资料库（当前页面） | 当前页面；若地址是 `.pdf` 或 GitHub 仓库地址，自动按 PDF / 仓库处理 |
| 添加到 Trainer 资料库（此链接） | 链接地址，规则同上 |
| 添加此 GitHub 仓库到 Trainer | 仅在 github.com 页面显示 |

采集结果通过系统通知反馈，最近 5 条记录显示在拓展弹窗里（含成功/失败状态）。

## 弹窗设置

| 设置项 | 存储 | 说明 |
| --- | --- | --- |
| 地址 | `chrome.storage.sync` | sidecar 地址，默认 `http://127.0.0.1:8765` |
| 工作区 ID | `chrome.storage.sync` | 目标工作区，默认 `workspace-default` |
| 访问令牌（可选） | `chrome.storage.local` | 当 sidecar 由 VS Code 启动时会要求 `x-trainer-token`，把它粘贴到这里（令牌每次启动不同） |

弹窗顶部的状态行会在打开时检查 `GET /health`，可用来确认地址与令牌是否可用。
