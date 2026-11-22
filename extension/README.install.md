# Trainer 安装说明

## 当前可直接安装形态

Trainer 扩展可打包为 `.vsix`，并在扩展内部携带独立冻结的 sidecar 二进制以及 Remote-SSH Companion（`extension/bundled/remote/trainer-workspace-companion.vsix`）。

- 每个 `.vsix` 都绑定一个系统和架构；请安装文件名与当前 VS Code Extension Host 匹配的版本，例如 `trainer-extension-1.5.3-darwin-arm64.vsix`、`trainer-extension-1.5.3-win32-x64.vsix` 或 `trainer-extension-1.5.3-linux-x64.vsix`
- 安装扩展后，无需通过 VS Code `Run Extension` 调试模式启动
- 安装版只会启动包内已验证的 sidecar 二进制
- 如果二进制缺失或与当前系统不匹配，Trainer 会提示重新安装对应 VSIX；不会尝试使用电脑上的 Python 或源码

## 打包

推荐直接在仓库根目录执行完整验证或交付打包：

```bash
npm run verify:delivery
```

如果只想单独打包 `.vsix`：

```bash
npm run package:vsix --prefix extension
```

产物会出现在 `extension/` 下，名称带有版本号和目标平台：

`trainer-extension-1.5.3-<platform>-<arch>.vsix`

## 安装到 VS Code

1. 打开 VS Code（或命令行运行 `code --install-extension extension/trainer-extension-1.5.3-<platform>-<arch>.vsix --force`）
2. 执行命令 `Extensions: Install from VSIX...`
3. 选择生成的 `.vsix`
4. 安装后重载窗口
5. 如需在 **Remote-SSH** 远端编码工作区中使用：连接远端后执行命令面板 `Trainer: Install Remote Workspace Support`（或通过一键引导安装内置的 Remote Companion 扩展）；**核心 AI 大脑、API Key 与学习记忆始终保留在本机，远端只运行受权限门控的文件读取/测试验证代理**。

## 运行要求

- 当前构建脚本会为构建机所在的平台和架构生成 sidecar 二进制；请不要把该 VSIX 安装到其他系统或架构
- `.github/workflows/release.yml` 提供 **Windows x64 (`win32-x64`)**、**macOS Apple Silicon (`darwin-arm64`)** 与 **Linux x64 (`linux-x64`)** 的 CI 构建路径；Windows ARM64 与 Linux ARM64 尚未提供原生 CI 构建证明
- 要使用 AI 对话，需要在设置中保存可用的大模型配置和 API Key（密钥仅写入操作系统钥匙串 / VS Code `SecretStorage`）

## 发布前检查

- 运行 `npm run verify:delivery`（含 `verify`、`test:experience-matrix`、`package:vsix`）并确认 `extension/trainer-extension-1.5.3-<platform>-<arch>.vsix.build.json` 中 `sourceDirty: false`
- 运行 `npm run test:server` 与 `npm run verify:ui-geometry`，以当次实际结果为准，不要依赖历史数值
- 确认产物文件名中的 `<platform>-<arch>` 与安装目标一致

## 安装后第一次使用

1. 打开侧边栏里的 `Trainer`（主导航固定为 **对话 / 资料** 两入口，右上角为 **学习抽屉 / 会话历史 / 设置**）
2. 首次即可直接在底部唯一输入框开始对话（冷启动零拦截）；要连入你的模型，点右上角齿轮进入 `设置 → 连接`：
   - **连接名称（可选）**
   - **协议**（OpenAI Chat / OpenAI Responses / Anthropic Messages / Gemini / Azure OpenAI，未知网关拒绝默认猜测）
   - **服务根地址**（例如 `https://api.example.com/v1`）
   - **网络代理**：默认 **跟随系统代理**；若本地代理环境变量导致 `502` 或连接超时，切换为 **忽略系统代理（直连）**
   - **模型** 与 **API Key**（保存后可点击 **测试连接** / **端点测速** 验证真实可用性与工具/思考能力）
3. 返回 `对话` 开始教学、代码引导或复习练习；按需在提示引导下将 `<LibraryRoot>` 绑定到本机学习库目录

如果没有保存 API Key，Trainer 会给出明确就绪引导，而不是静默阻塞或假装可用。

## 出问题先看哪里

- 如果侧边栏能开但不能发送：
  先检查 provider、协议和 API Key 是否均已保存，必要时在 `设置 → 连接` 切换 **忽略系统代理（直连）**
- 如果显示 sidecar 启动失败：
  打开 VS Code 的 `Output` 面板，切到 `Trainer`
- 如果重新打包后仍然异常：
  重新执行一次 `npm run build && npm run test:extension && npm run verify:delivery`

## 数据目录（统一 `<LibraryRoot>` 单根存储）

Trainer 贯彻**单库单根 + 代码仓零写入**：

- **学习资料与 Markdown 讲稿**：存入用户选定的 `<LibraryRoot>/Trainer Library/`（如自动保存的 `<LibraryRoot>/Trainer Library/学习讲稿/*.md`）
- **运行时状态、数据库与记忆索引**：统一存放在 `<LibraryRoot>/.trainer/runtime/`（含 `trainer.sqlite3`、Qdrant 索引与审查日志），从早期 `globalStorage` 目录自动平滑迁入
- **API 密钥**：仅由操作系统钥匙串 / VS Code `SecretStorage` 管理，绝不写入项目仓或 `<LibraryRoot>`
- **用户代码项目目录**：Trainer 永不写入隐藏目录、配置或改写源码
