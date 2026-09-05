# Trainer 安装说明

## 当前可直接安装形态

Trainer 扩展可打包为 `.vsix`，并在扩展内部携带 sidecar 后端。

- 每个 `.vsix` 都绑定一个系统和架构；请安装文件名与当前 VS Code Extension Host 匹配的版本，例如 `trainer-extension-0.1.0-win32-x64.vsix`
- 安装扩展后，无需通过 VS Code `Run Extension` 调试模式启动
- 安装版只会启动包内已验证的 sidecar 二进制
- 如果二进制缺失或与当前系统不匹配，Trainer 会提示重新安装对应 VSIX；不会尝试使用电脑上的 Python 或源码

## 打包

推荐直接在仓库根目录执行完整交付检查：

```bash
npm run verify:delivery
```

这条命令会按顺序执行：

- `npm run build`
- `npm run test:extension`
- `npm run test:server`
- `npm run package:vsix`

如果只想单独打包 `.vsix`：

```bash
npm run package:vsix --prefix extension
```

产物会出现在 `extension/` 下，名称带有目标平台：

`trainer-extension-0.1.0-<platform>-<arch>.vsix`

## 安装到 VS Code

1. 打开 VS Code
2. 执行命令 `Extensions: Install from VSIX...`
3. 选择生成的 `.vsix`
4. 安装后重载窗口

## 运行要求

- 当前构建脚本会为构建机所在的平台和架构生成 sidecar 二进制；请不要把该 VSIX 安装到其他系统或架构
- Windows x64、macOS runner 的原生目标和 Linux x64 有 CI 构建路径。Windows ARM64 与 Linux ARM64 虽被打包代码识别，但还没有专用构建、安装验证和发布证据
- 要使用 AI 对话，需要在设置中保存可用的大模型配置和 API Key

## 发布前检查

- 运行 `npm run verify:delivery`，并读取这次运行的实际结果，不要依赖文档中的历史测试数量
- 确认产物文件名中的 `<platform>-<arch>` 与安装目标一致
- 发布到 Windows ARM64 或 Linux ARM64 前，先在对应原生 runner 上完成构建、安装和 sidecar 启动验证

## 安装后第一次使用

1. 打开侧边栏里的 `Trainer`
2. 进入 `设置`
3. 保存大模型配置：
   - provider 名称
   - base URL
   - model
   - API key
4. 返回 `对话` 开始训练

如果没有保存 API key，Trainer 应该显示明确提示，而不是黑屏或假装可用。

## 出问题先看哪里

- 如果侧边栏能开但不能发送：
  先检查 provider 和 API key 是否都已保存
- 如果显示 sidecar 启动失败：
  打开 VS Code 的 `Output` 面板，切到 `Trainer`
- 如果重新打包后仍然异常：
  重新执行一次 `npm run verify:delivery`

## 数据目录

扩展运行后的 sidecar 数据会写入 VS Code 扩展全局存储目录，而不是仓库源码目录。

这样安装版扩展可以正常保存：

- 会话
- 记忆
- 资源索引
- 本地数据库
