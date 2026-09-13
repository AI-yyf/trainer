<div align="center">

<img src="assets/banner.png" alt="Trainer — 住在你编辑器里的长期编程教练" width="100%" />

**一个住在你 VS Code 侧边栏里的长期编程教练。**
它做计划、出题、验收、记住你的一切——但绝不替你写代码。

[安装](#安装) · [功能总览](#五个视图) · [三步配置](#三步配置没有第四步) · [设计理念](#为什么看起来不一样) · [架构](#架构) · [English](#english)

</div>

---

## 背景

开发者卡住,从来不是因为缺教程。

是因为没有东西把学习闭环关上:和 LLM 聊完天,内容就蒸发了;视频看完了,是被动的;周二那个"差一点就懂了"的概念,周五就不见了。收藏夹越来越厚,产出却停在原地。

Trainer 从编辑器内部解决这个问题。它不是一个聊天壳子,而是一个有记忆、有课程、有考试政策的教练:

- 它把你的学习**规划**成阶段,并追踪你实际走到哪,而不是你"觉得"走到哪
- 它用闪卡、理论演练、场景实验**训练**你
- 它对照你的**真实代码验收**掌握度——聊明白 FastAPI 不算数,当前文件证明才算数
- 它跨会话、跨项目、跨周地**记住**你,并按 FSRS 遗忘曲线安排复习
- 它**绝不替你写生产代码**。你写,它教

## 三步配置,没有第四步

1. 打开 Trainer 侧边栏 → 设置
2. 粘贴中转站连接信息(国内中转站复制的整段 JSON 直接识别,自动拆出地址和密钥)→ 粘贴 API 密钥
3. 点**保存并连接**

Trainer 自动拉取在线模型列表、自动选择默认模型、自动验证流式链路。密钥错了会明确告诉你 `invalid_key_or_permission`,而不是一个含糊的转圈。

<p align="center">
  <img src="assets/screenshots/settings-quick-setup.png" alt="快速设置" width="420" />
</p>

## 五个视图

| 视图 | 职责 |
|------|------|
| **对话** | 流式教练对话,带工具访问(读文件、诊断、工作区搜索)、`$` 技能面板、图片附件、答案模式(`direct` 直接给答案;`coach-first` 先让你想) |
| **计划** | 从你的目标生成分阶段课程、进度仪表盘、计划冻结/解冻、按阶段生成学习材料 |
| **资料** | 你的资料库:markdown/PDF/DOCX/CSV/notebook/媒体上传、全文搜索、分级沙箱预览、回收站 |
| **训练** | FSRS 调度的闪卡、带验收标准的理论演练、场景实验、验证门禁的卡片推进、可延后/完成的复习队列 |
| **设置** | 供应商档案(粘贴即用)、模型切换、端点测速、思考强度、教学风格、记忆作用域、工作区准入 |

<div align="center">
  <table><tr>
    <td><img src="assets/screenshots/plan.png" alt="计划视图" width="260" /></td>
    <td><img src="assets/screenshots/resources.png" alt="资料视图" width="260" /></td>
    <td><img src="assets/screenshots/training.png" alt="训练视图" width="260" /></td>
  </tr></table>
</div>

<div align="center">
  <img src="assets/screenshots/training.png" alt="训练视图" width="420" />
</div>

## 为什么"看起来不一样"

**验收门禁。** 伪造学习最快的方式是全标完成。Trainer 拒绝这样做:训练卡推进到"已实现"必须先对当前文件跑验收。手动"标记完成"是被有意禁止的。

**诚实的失败。** 密钥错了会明确告诉你 `invalid_key_or_permission`;连不上会告诉你 `network`;模型回复损坏时会明确说"这条回复没有读清,请重发"——绝不把损坏的输出当作答案。未知网关不会被默认当成 OpenAI 兼容。

**端点测速。** 多个服务商端点并行竞速(先热身消除首包惩罚,再计时)。500ms 内绿色,1 秒内黄色。点一下就采用最快端点。

**长程状态。** 计划可冻结/解冻;会话跨重启存活;卡片进度存进 SQLite;复习按 FSRS 遗忘曲线到期,而不是按待办清单。

<p align="center">
  <img src="assets/screenshots/settings-connected.png" alt="连接成功" width="420" />
</p>

## 安全模型

- API 密钥存放在 **VS Code SecretStorage**(系统级加密),不进配置文件、不进 git
- 工作区遵循 **VS Code 原生信任机制**,未信任时写操作全部拒绝
- 六级权限模型:默认只读(INSPECT),写/删/改需要逐级验证背书
- 沙箱预览有严格的路径治理:越界路径直接 422 拒绝

## 安装

**从 VSIX**(预构建,macOS ARM64):下载 `extension/trainer-extension-0.1.0-darwin-arm64.vsix`,VS Code 扩展面板 → `···` → *从 VSIX 安装* → 重载窗口

**从源码:**

```bash
git clone https://github.com/AI-yyf/trainer.git
cd trainer && npm install
cd server && python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cd .. && npm run build
```

在 VS Code 中打开本仓库按 F5(扩展开发宿主),或安装打包好的 VSIX。

## 质量门禁

这个仓库把自己的验证体系当作产品:

| 门禁 | 数量 |
|------|------|
| 扩展测试(node --test) | 1,550 |
| 服务端测试(pytest) | 2,825 |
| 真实 VS Code 端到端 | 33 步,接入真实模型 |
| 体验矩阵(Playwright) | 200 个场景 |
| 静态分析 | ruff + pyright + tsc,零告警 |

端到端套件在真实 VS Code 实例中接入真实模型运行:激活打包后的扩展、启动内置 sidecar、保存供应商、流式完成教练回合、生成并验收训练卡、断言 webview 实际渲染的内容。

## 架构

```
VS Code 窗口
└── Trainer 侧边栏 (React 19 + Zustand, 8 语言)
    └── postMessage 桥 ── CommandRegistry ── 30+ 命令
                                     │
                     FastAPI sidecar (127.0.0.1, PyInstaller 打包)
                     ├── ReAct agent loop (读文件/诊断/搜索工具)
                     ├── 规划器 · 教学引擎 · FSRS 调度器
                     ├── 记忆 (SQLite + Qdrant 语义检索)
                     └── 资料库 (全文检索 + 分级沙箱预览)
```

- `shared/` — 双端共用的协议类型(唯一事实来源)
- `extension/` — 宿主:命令、工作区信任/准入、密钥存储、sidecar 生命周期
- `server/` — 教练大脑:agent 循环、规划器、教学引擎、FSRS、记忆、资源库
- `extension/bundled/` — 打包进 VSIX 的 sidecar(PyInstaller)

## 致谢 · Acknowledgements

Trainer 站在以下开源项目的肩膀上,感谢这些优秀的社区作品:

| 项目 | 用途 |
|------|------|
| [FastAPI](https://github.com/fastapi/fastapi) · [Uvicorn](https://github.com/encode/uvicorn) | 本地 sidecar 服务框架 |
| [React](https://github.com/facebook/react) · [Zustand](https://github.com/pmndrs/zustand) · [Vite](https://github.com/vitejs/vite) | 侧边栏工作台 |
| [py-fsrs](https://github.com/open-spaced-repetition/py-fsrs) | FSRS 遗忘曲线复习调度 |
| [Qdrant](https://github.com/qdrant/qdrant) 客户端 | 语义记忆检索 |
| [Playwright](https://github.com/microsoft/playwright) | 端到端体验矩阵 |
| [PyInstaller](https://github.com/pyinstaller/pyinstaller) | sidecar 单二进制分发 |

产品形态上深受 [CC Switch](https://github.com/farion1231/cc-switch) 的"一键切换、粘贴即用"理念启发——好的工具应该把配置成本压到接近零。

横幅由 [dora-image](https://github.com/AI-yyf/trainer) 工作流生成(gpt-image-2)。

## English

Trainer is a long-term coding coach living in your VS Code sidebar: it plans your curriculum in stages, drills you with FSRS-scheduled flash cards and theory exercises, verifies mastery against your *actual code* (chatting about FastAPI counts for nothing until the current file proves it), and remembers everything across sessions — while never writing production code for you. Works with any OpenAI-compatible provider; paste your relay's connection JSON, hit save, and the model list, default model, and streaming verification all happen in one pass. See the Chinese documentation above for the full tour, or [SPEC.md](SPEC.md) for the original specification.

## 许可

[MIT](LICENSE)
